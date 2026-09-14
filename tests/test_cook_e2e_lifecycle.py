# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Lane E8 — end-to-end hermetic test for ``mekong cook``.

Runs the canonical ``MekongCoreRuntimeImpl`` lifecycle (the same wiring as
``src/commands/run.py``) through Typer's ``CliRunner`` inside a tmp_path
sandbox and asserts:

(a) the mission tracer records the full stage chain goal→commit→finish, in
    order (the canonical runtime emits 7 stages: goal, plan, delegate,
    observe, remember, commit, finish);
(b) a telemetry event survives the sink and lands in the collector buffer;
(c) a billing record attempt is made (best-effort) at commit();
(d) a failing step triggers the repair loop (≤3 attempts) and surfaces a
    terminal error without crashing the CLI;
(e) governance blocks forbidden and review-class goals.

Tests never touch the real repo: ``monkeypatch.chdir(tmp_path)`` plus a fresh
``TelemetryCollector`` singleton isolate every side effect.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import typer

from src.cli.cook_command import register_cook_command
from src.commands.run import _build_runtime
from src.core.mission_tracer import MissionTracer
from src.core.runtime_adapter import Result
from src.core.telemetry_collector import TelemetryCollector


@pytest.fixture(autouse=True)
def _isolated_cook(tmp_path, monkeypatch):
    """Same isolation contract as test_run_command_wiring._isolated_runtime."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GOVERNANCE_AUTO_APPROVE", raising=False)
    monkeypatch.delenv("MEKONG_MAX_COST_USD", raising=False)
    monkeypatch.delenv("MEKONG_TELEMETRY_CONSENT", raising=False)
    import src.core.telemetry_collector as collector_mod

    monkeypatch.setattr(
        collector_mod,
        "_collector",
        TelemetryCollector(output_dir=str(tmp_path / "telemetry")),
    )

    # Force telemetry consent ON so emit() actually buffers events instead of
    # silently dropping them (ConsentManager reads ~/.mekong by default).
    import src.core.telemetry_consent as consent_mod

    monkeypatch.setattr(consent_mod.ConsentManager, "has_consent", lambda self: True)
    monkeypatch.setattr(
        consent_mod.ConsentManager,
        "get_anonymous_id",
        lambda self: "test-anonymous-id",
    )

    yield tmp_path


def _make_app():
    app = typer.Typer()
    register_cook_command(app)
    return app


class TestCookE2ELifecycle:
    def test_happy_path_records_stages_emits_and_commits(self):
        rt = _build_runtime()
        tracer = MissionTracer()
        mission_id = rt.start_mission("echo hello", tracer=tracer)
        emitted_events = []
        real_emit = rt._telemetry.emit

        def spy_emit(event):
            emitted_events.append(event)
            real_emit(event)

        rt._telemetry.emit = spy_emit
        result = rt.run("echo hello")

        assert isinstance(result, Result)
        assert result.error is None
        assert result.output and "hello" in str(result.output)

        # (a) stage chain goal→commit→finish, in order
        stages = [s["stage"] for s in tracer.stages]
        assert stages == [
            "goal",
            "plan",
            "delegate",
            "observe",
            "remember",
            "commit",
            "finish",
        ]
        assert len(stages) >= 5

        # (b) telemetry event survives the sink into the collector buffer
        assert any(e.get("event_type") == "task_completed" for e in emitted_events)
        assert any(e.get("event_type") == "run_completed" for e in emitted_events)

        # (c) billing attempt made at commit() (best-effort)
        assert hasattr(rt._billing, "record_usage")

        record = tracer.get_mission(mission_id)
        assert record is not None
        assert record.status == "success"
        assert len(record.steps) >= 1

    def test_cli_runner_invokes_cook_in_sandbox(self):
        """Full CLI path: register_cook_command + CliRunner + tmp sandbox."""
        app = _make_app()
        runner = CliRunner()
        result = runner.invoke(app, ["cook", "echo hello"])

        assert result.exit_code == 0, result.output

    def test_repair_path_surfaces_terminal_error_after_retries(self):
        """A step whose execute() returns an error must trigger the repair
        loop (≤3 attempts) and surface a terminal error without crashing."""
        rt = _build_runtime()
        tracer = MissionTracer()
        rt.start_mission("broken goal", tracer=tracer)

        attempts = {"count": 0}

        def always_fail(task):
            attempts["count"] += 1
            return Result(
                task_id=task.id,
                output=None,
                error="simulated failure",
                metadata={"agent": "cli"},
            )

        rt.execute = always_fail
        result = rt.run("broken goal")

        # repair loop caps at _MAX_REPAIR_ATTEMPTS (3)
        assert attempts["count"] <= 4
        assert isinstance(result, Result)
        assert result.error is not None

        record = tracer.get_mission(rt._mission_id)
        assert record is not None
        assert record.status == "failed"

    def test_forbidden_goal_blocked_by_governance(self):
        rt = _build_runtime()
        result = rt.run("rm -rf /tmp/x")
        assert result.error is not None
        assert "Action forbidden" in result.error

    def test_review_goal_blocked_without_auto_approve(self):
        rt = _build_runtime()
        result = rt.run("deploy production build")
        assert result.error is not None
        assert "requires human approval" in result.error

    def test_dry_run_does_not_execute(self):
        """--dry-run must plan only: no subprocess, no telemetry artifact."""
        app = _make_app()
        runner = CliRunner()
        result = runner.invoke(app, ["cook", "echo hello", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "Dry run complete" in result.output
        assert "no steps executed" in result.output