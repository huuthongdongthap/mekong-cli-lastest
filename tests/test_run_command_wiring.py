# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for src/commands/run.py production wiring.

Covers the real production path end-to-end (no mocks over the runtime):
- TelemetrySinkAdapter conforms to protocols.ObservabilitySink and survives
  the observe()/commit() emit calls that previously crashed with
  AttributeError on the record_event-only stub.
- Governance gate engages by default: forbidden goals blocked, review-class
  goals blocked unless GOVERNANCE_AUTO_APPROVE is set.
- Cost ceiling guard engages with the real LLMRouterAdapter estimate shape.
- Mission tracer attached via start_mission() records steps and outcome.
- Cost ceiling resolution: CLI value > MEKONG_MAX_COST_USD env > 5.0 default.
"""

from __future__ import annotations

import pytest

from src.commands.run import _build_runtime, _resolve_max_cost_usd
from src.core.capability import CapabilitySource
from src.core.governance import Governance
from src.core.protocols import ObservabilitySink
from src.core.runtime_adapter import Result


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    """Isolate runtime side effects per test.

    - chdir to tmp so Governance() writes its audit trail inside tmp_path
      instead of the repo's .mekong/ directory.
    - Point the TelemetryCollector singleton at a tmp output dir so emitted
      events never touch the real ~/.mekong telemetry buffer.
    """
    monkeypatch.chdir(tmp_path)
    import src.core.telemetry_collector as collector_mod

    monkeypatch.setattr(
        collector_mod,
        "_collector",
        collector_mod.TelemetryCollector(output_dir=str(tmp_path / "telemetry")),
    )
    monkeypatch.delenv("GOVERNANCE_AUTO_APPROVE", raising=False)
    monkeypatch.delenv("MEKONG_MAX_COST_USD", raising=False)


class TestBuildRuntimeWiring:
    def test_telemetry_conforms_to_observability_sink(self):
        rt = _build_runtime()
        assert isinstance(rt._telemetry, ObservabilitySink)
        assert hasattr(rt._telemetry, "emit")
        assert hasattr(rt._telemetry, "flush")

    def test_governance_wired_on_by_default(self):
        rt = _build_runtime()
        assert isinstance(rt._governance, Governance)

    def test_default_cost_ceiling_is_five_usd(self):
        rt = _build_runtime()
        assert rt._max_cost_usd == 5.0

    def test_cost_ceiling_override_via_param(self):
        rt = _build_runtime(max_cost_usd=1.25)
        assert rt._max_cost_usd == 1.25


class TestMcpCapabilityWiring:
    """MCP tools are exposed as capabilities via MCPCapabilityAdapter."""

    def test_mcp_capabilities_synced_to_bus(self):
        """The runtime bus must carry MCP-sourced capabilities."""
        rt = _build_runtime()
        bus = rt._capability_bus
        assert bus is not None
        mcp_caps = bus.list_capabilities(source=CapabilitySource.MCP)
        # MekongMcpServer exposes multiple cc_* tools; the adapter bridges them
        # all as `mcp:cc_*` capabilities.
        assert len(mcp_caps) > 0
        assert all(c.source == CapabilitySource.MCP for c in mcp_caps)
        assert all(c.id.startswith("mcp:") for c in mcp_caps)

    def test_runtime_degrades_gracefully_if_mcp_sync_fails(self, monkeypatch):
        """If MCPCapabilityAdapter.sync_from_mcp() raises, the bus still
        carries builtin tools — MCP failure must not crash the runtime."""
        import src.core.adapters.mcp_capability_adapter as adapter_mod

        class _BoomAdapter:
            def __init__(self, bus=None):
                self._bus = bus

            def sync_from_mcp(self):
                raise RuntimeError("MCP server unavailable")

        # _build_runtime imports MCPCapabilityAdapter lazily inside the
        # function body, so patch the source module — that's where the
        # name lookup resolves.
        monkeypatch.setattr(adapter_mod, "MCPCapabilityAdapter", _BoomAdapter)
        rt = _build_runtime()
        bus = rt._capability_bus
        assert bus is not None
        # Builtin tools still present even though MCP failed.
        assert len(bus.list_capabilities()) > 0


class TestCostCeilingResolution:
    def test_cli_value_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("MEKONG_MAX_COST_USD", "2.5")
        assert _resolve_max_cost_usd(3.0) == 3.0

    def test_env_overrides_default(self, monkeypatch):
        monkeypatch.setenv("MEKONG_MAX_COST_USD", "2.5")
        assert _resolve_max_cost_usd(None) == 2.5

    def test_default_when_unset(self):
        assert _resolve_max_cost_usd(None) == 5.0

    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("MEKONG_MAX_COST_USD", "not-a-number")
        assert _resolve_max_cost_usd(None) == 5.0

    def test_env_wired_into_runtime(self, monkeypatch):
        monkeypatch.setenv("MEKONG_MAX_COST_USD", "2.5")
        rt = _build_runtime()
        assert rt._max_cost_usd == 2.5

    def test_invalid_env_in_runtime_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("MEKONG_MAX_COST_USD", "not-a-number")
        rt = _build_runtime()
        assert rt._max_cost_usd == 5.0


class TestEndToEndRun:
    def test_run_completes_through_observe_and_emit(self):
        """The old crash path: execute() catches the dispatcher raise, then
        observe()/commit() call telemetry.emit() — must not AttributeError."""
        rt = _build_runtime()
        emitted = []
        real_emit = rt._telemetry.emit

        def _spy(event):
            emitted.append(event)
            return real_emit(event)

        rt._telemetry.emit = _spy
        result = rt.run("hello")

        assert isinstance(result, Result)
        assert result.task_id
        # Dispatcher stub raise is caught by execute(); the loop surfaces a
        # terminal error instead of propagating the exception.
        assert result.error is not None
        # The observe()/commit() path really ran through the telemetry sink.
        assert any(e.get("event_type") == "task_completed" for e in emitted)
        assert any(e.get("event_type") == "run_completed" for e in emitted)

    def test_review_goal_blocked_without_auto_approve(self):
        rt = _build_runtime()
        result = rt.run("deploy production build")
        assert result.error is not None
        assert "Action requires human approval" in result.error

    def test_forbidden_goal_blocked(self):
        rt = _build_runtime()
        result = rt.run("rm -rf /tmp/x")
        assert result.error is not None
        assert "Action forbidden" in result.error

    def test_review_goal_passes_with_auto_approve(self, monkeypatch):
        monkeypatch.setenv("GOVERNANCE_AUTO_APPROVE", "true")
        rt = _build_runtime()
        result = rt.run("deploy production build")
        assert result.error is not None  # dispatcher stub still errors
        assert "requires human approval" not in result.error
        assert "forbidden" not in result.error.lower()

    def test_cost_ceiling_blocks_execution(self):
        rt = _build_runtime(max_cost_usd=0.0000001)
        result = rt.run("hello")
        assert result.error is not None
        assert "Cost ceiling exceeded" in result.error

    def test_mission_tracer_records_steps_and_outcome(self):
        from src.core.mission_tracer import MissionTracer

        rt = _build_runtime()
        tracer = MissionTracer()
        mission_id = rt.start_mission("hello", tracer=tracer)
        assert mission_id
        rt.run("hello")

        record = tracer.get_mission(rt._mission_id)
        assert record is not None
        assert record.status in ("success", "failed")
        assert len(record.steps) >= 1


class TestGovernanceApprovalHardening:
    def test_request_approval_explicit_true_for_non_review(self):
        """Non-review decisions get an explicit True, never an implicit None."""
        from src.core.governance import ActionClass, GovernanceDecision

        gov = Governance()
        decision = GovernanceDecision(
            action_class=ActionClass.SAFE, reason="No dangerous patterns detected"
        )
        assert gov.request_approval("analyze revenue", decision) is True

    def test_request_approval_false_without_auto_approve(self):
        from src.core.governance import ActionClass, GovernanceDecision

        gov = Governance()
        decision = GovernanceDecision(
            action_class=ActionClass.REVIEW_REQUIRED,
            requires_approval=True,
            reason="Matched review pattern",
        )
        assert gov.request_approval("deploy production build", decision) is False
        assert decision.approved is False
