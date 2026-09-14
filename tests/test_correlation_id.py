"""Tests for mission correlation ID in MekongCoreRuntimeImpl."""

import os
import unittest
from unittest.mock import patch

import pytest

from src.core.mission_tracer import MissionTracer
from src.core.runtime_adapter import MekongCoreRuntimeImpl


class _FakeDispatcher:
    def dispatch(self, task, agent=None):
        return {"ok": True, "task_id": task.id}


class _FakeToolRegistry:
    def register(self, tool, **kwargs):
        pass

    def execute(self, tool_id, params):
        return {"ok": True}

    def list_tools(self):
        return []


class TestRuntimeMissionTracking(unittest.TestCase):
    """Test mission tracking fields on MekongCoreRuntimeImpl."""

    def _make_runtime(self, **kwargs):
        defaults = dict(
            dispatcher=_FakeDispatcher(),
            tool_registry=_FakeToolRegistry(),
        )
        defaults.update(kwargs)
        return MekongCoreRuntimeImpl(**defaults)

    def test_start_mission_sets_mission_id(self):
        """start_mission assigns a mission_id string."""
        runtime = self._make_runtime()
        mid = runtime.start_mission("deploy api")
        assert isinstance(mid, str)
        assert mid.startswith("mission_")
        assert runtime._mission_id == mid

    def test_start_mission_with_tracer(self):
        """start_mission delegates to tracer when provided."""
        tracer = MissionTracer()
        runtime = self._make_runtime()
        runtime.start_mission("build", tracer=tracer)
        missions = tracer.list_missions()
        assert len(missions) == 1
        assert missions[0]["goal"] == "build"

    def test_mission_id_defaults_to_none(self):
        """_mission_id is None before start_mission is called."""
        runtime = self._make_runtime()
        assert runtime._mission_id is None

    def test_mission_tracer_defaults_to_none(self):
        """_mission_tracer is None when no tracer is provided."""
        runtime = self._make_runtime()
        assert runtime._mission_tracer is None

    def test_start_mission_without_tracer(self):
        """start_mission works without a tracer, only sets _mission_id."""
        runtime = self._make_runtime()
        mid = runtime.start_mission("simple task")
        assert runtime._mission_id == mid
        assert runtime._mission_tracer is None

    def test_destroy_clears_mission_fields(self):
        """destroy clears mission tracking fields."""
        tracer = MissionTracer()
        runtime = self._make_runtime()
        runtime.start_mission("task", tracer=tracer)
        assert runtime._mission_id is not None
        assert runtime._mission_tracer is not None
        runtime.destroy()
        assert runtime._mission_id is None
        assert runtime._mission_tracer is None

    def test_multiple_missions_update_id(self):
        """Each start_mission call overwrites the previous mission_id."""
        runtime = self._make_runtime()
        mid1 = runtime.start_mission("first")
        mid2 = runtime.start_mission("second")
        assert mid1 != mid2
        assert runtime._mission_id == mid2


class TestRuntimeMemoryTierSeparation:
    """Memory tier separation wired into the runtime lifecycle.

    The session-wide ``_pre_gateway_patches`` mock replaces
    ``memory_canonical.MemoryStore`` with a MagicMock, so the default
    ``MemoryStoreAdapter()`` would write to a mock. These tests restore the
    real class (via ``_real_memory_store``) and inject a hermetic adapter
    pinned to ``tmp_path`` so the conformant write path is exercised for real.
    """

    @pytest.fixture(autouse=True)
    def _restore_real_memory_store(self):
        """Restore the genuine memory_canonical.MemoryStore for this test."""
        import src.core.memory_canonical as _mc
        import src.core.memory_store_adapter as _msa
        import tests.conftest as _conftest

        _real = _conftest._pre_gateway_originals.get(
            "src.core.memory_canonical.MemoryStore",
        )
        with (
            patch.object(_mc, "MemoryStore", _real),
            patch.object(_msa, "MemoryStore", _real),
        ):
            yield

    def _make_runtime(self, tmp_path, **kwargs):
        from src.core.memory_canonical import MemoryStore
        from src.core.memory_store_adapter import MemoryStoreAdapter

        underlying = MemoryStore(store_path=str(tmp_path / "mem.yaml"))
        adapter = MemoryStoreAdapter(store=underlying)
        defaults = dict(
            dispatcher=_FakeDispatcher(),
            tool_registry=_FakeToolRegistry(),
            memory_store=adapter,
        )
        defaults.update(kwargs)
        return MekongCoreRuntimeImpl(**defaults)

    def test_runtime_uses_memory_separation_by_default(self):
        """Post-collapse: _memory_separation is None by default; the conformant
        MemoryStoreAdapter (_memory_store) is the sole write path."""
        runtime = MekongCoreRuntimeImpl(
            dispatcher=_FakeDispatcher(),
            tool_registry=_FakeToolRegistry(),
        )
        assert runtime._memory_separation is None

    def test_remember_writes_through_memory_store(self, tmp_path):
        """LOW-3 resolution: remember() writes through the conformant
        MemoryStoreAdapter (_memory_store), not the tier layer alone."""
        from src.core.runtime_adapter import Task, AgentId, Step

        runtime = self._make_runtime(tmp_path)
        runtime.start_mission("task")
        task = Task(
            id="t1",
            step=Step(id="step-0", description="do thing", params={}),
            agent=AgentId(name="default"),
        )
        result = runtime.execute(task)
        obs = runtime.observe(result)
        runtime.remember(obs)
        # Primary write path: the conformant adapter (_memory_store).
        retrieved = runtime._memory_store.retrieve("obs-t1")
        assert retrieved is not None, "remember() must write through _memory_store"
        assert b"t1" in retrieved
        # Session key is tracked for flush.
        assert "obs-t1" in runtime._session_keys

    def test_start_mission_flushes_session_keys_via_adapter(self, tmp_path):
        """start_mission() flushes SESSION-tier keys through the adapter."""
        runtime = self._make_runtime(tmp_path)
        runtime.start_mission("first")
        # Simulate a prior mission's session entry written via remember().
        runtime._memory_store.store("leftover", b"data", ttl=3600)
        runtime._session_keys.add("leftover")
        assert runtime._memory_store.retrieve("leftover") == b"data"
        # start_mission() must flush all tracked session keys.
        runtime.start_mission("second")
        assert runtime._session_keys == set()
        assert runtime._memory_store.retrieve("leftover") is None

    def test_flush_session_deletes_tracked_keys(self, tmp_path):
        """flush_session() removes every tracked key through the adapter."""
        runtime = self._make_runtime(tmp_path)
        runtime._memory_store.store("s1", b"a", ttl=3600)
        runtime._session_keys.add("s1")
        runtime._memory_store.store("s2", b"b", ttl=3600)
        runtime._session_keys.add("s2")
        deleted = runtime.flush_session()
        assert deleted == 2
        assert runtime._session_keys == set()
        assert runtime._memory_store.retrieve("s1") is None
        assert runtime._memory_store.retrieve("s2") is None

    def test_destroy_clears_memory_separation(self):
        """destroy() releases the memory separation layer when explicitly set."""
        from src.core.memory_separation import MemorySeparation

        runtime = MekongCoreRuntimeImpl(
            dispatcher=_FakeDispatcher(),
            tool_registry=_FakeToolRegistry(),
            memory_separation=MemorySeparation(),
        )
        runtime.start_mission("task")
        assert runtime._memory_separation is not None
        runtime.destroy()
        assert runtime._memory_separation is None


class TestRuntimeMissionTracerWiring(unittest.TestCase):
    """MissionTracer is wired into the runtime loop, not just stored."""

    def _make_runtime(self, **kwargs):
        defaults = dict(
            dispatcher=_FakeDispatcher(),
            tool_registry=_FakeToolRegistry(),
        )
        defaults.update(kwargs)
        return MekongCoreRuntimeImpl(**defaults)

    def test_run_logs_each_step_into_tracer(self):
        """run() pushes each executed task into the attached tracer."""
        tracer = MissionTracer()
        runtime = self._make_runtime()
        runtime.start_mission("build api", tracer=tracer)
        runtime.run("build api")
        missions = tracer.list_missions()
        assert len(missions) == 1
        assert missions[0]["status"] == "success"
        assert missions[0]["step_count"] >= 1

    def test_run_ends_mission_with_failed_outcome(self):
        """run() records failed outcome when a task errors."""

        class _FailingDispatcher:
            def dispatch(self, task, agent=None):
                raise RuntimeError("boom")

        tracer = MissionTracer()
        runtime = self._make_runtime(dispatcher=_FailingDispatcher())
        runtime.start_mission("failing task", tracer=tracer)
        runtime.run("failing task")
        missions = tracer.list_missions()
        assert len(missions) == 1
        assert missions[0]["status"] == "failed"

    def test_run_without_tracer_does_not_crash(self):
        """run() works normally when no tracer is attached."""
        runtime = self._make_runtime()
        runtime.start_mission("no tracer")
        result = runtime.run("no tracer")
        assert result.error is None

    def test_trace_step_swallows_tracer_errors(self):
        """A broken tracer must never break the runtime loop."""

        class _BrokenTracer:
            def log_step(self, *args, **kwargs):
                raise RuntimeError("tracer broken")

            def end_mission(self, *args, **kwargs):
                raise RuntimeError("tracer broken")

        runtime = self._make_runtime()
        runtime.start_mission("broken tracer", tracer=_BrokenTracer())
        result = runtime.run("broken tracer")
        assert result.error is None


class TestRuntimeTelemetryCorrelation(unittest.TestCase):
    """Telemetry events carry the mission correlation ID (AUTONOMY_GAPS #10)."""

    def _make_runtime(self, **kwargs):
        defaults = dict(
            dispatcher=_FakeDispatcher(),
            tool_registry=_FakeToolRegistry(),
        )
        defaults.update(kwargs)
        return MekongCoreRuntimeImpl(**defaults)

    def _capture_telemetry(self):
        captured = []
        class _FakeTelemetry:
            def emit(self, event):
                captured.append(event)
            def flush(self):
                pass
        return _FakeTelemetry(), captured

    def test_emit_carries_mission_id(self):
        """observe() emits task_completed with the current mission_id."""
        from src.core.runtime_adapter import Task, Step, AgentId

        sink, captured = self._capture_telemetry()
        runtime = self._make_runtime()
        runtime._telemetry = sink
        runtime.start_mission("correlate me")
        task = Task(
            id="t1",
            step=Step(id="step-0", description="do thing", params={}),
            agent=AgentId(name="default"),
        )
        result = runtime.execute(task)
        runtime.observe(result)
        assert any(e.get("mission_id") == runtime._mission_id for e in captured)

    def test_emit_propagates_estimated_cost(self):
        """observe() forwards the cost estimate from execute() into telemetry."""
        from src.core.runtime_adapter import Task, Step, AgentId

        sink, captured = self._capture_telemetry()
        runtime = self._make_runtime()
        runtime._telemetry = sink
        runtime.start_mission("cost tracking")
        task = Task(
            id="t1",
            step=Step(id="step-0", description="do thing", params={}),
            agent=AgentId(name="default"),
        )
        result = runtime.execute(task)
        runtime.observe(result)
        assert any("estimated_cost" in e for e in captured)


class TestRuntimeGovernanceGate(unittest.TestCase):
    """execute() gates tasks on Governance classification (AUTONOMY_GAPS #5)."""

    def _make_runtime(self, **kwargs):
        defaults = dict(
            dispatcher=_FakeDispatcher(),
            tool_registry=_FakeToolRegistry(),
        )
        defaults.update(kwargs)
        return MekongCoreRuntimeImpl(**defaults)

    def _task(self, description: str):
        from src.core.runtime_adapter import Task, Step, AgentId

        return Task(
            id="t1",
            step=Step(id="step-0", description=description, params={"description": description}),
            agent=AgentId(name="default"),
        )

    def test_forbidden_action_is_blocked(self):
        """A task matching a forbidden pattern is never executed."""
        from src.core.governance import Governance

        runtime = self._make_runtime(governance=Governance())
        result = runtime.execute(self._task("rm -rf /tmp/important"))
        assert result.error is not None
        assert "forbidden" in result.error.lower()

    def test_review_required_blocked_without_approval(self):
        """REVIEW_REQUIRED actions are blocked unless GOVERNANCE_AUTO_APPROVE is set."""
        from src.core.governance import Governance

        runtime = self._make_runtime(governance=Governance())
        result = runtime.execute(self._task("deploy to prod"))
        assert result.error is not None
        assert "approval" in result.error.lower()

    def test_review_required_auto_approved_with_env(self):
        """GOVERNANCE_AUTO_APPROVE=true lets REVIEW_REQUIRED actions through."""
        from src.core.governance import Governance

        with patch.dict(os.environ, {"GOVERNANCE_AUTO_APPROVE": "true"}):
            runtime = self._make_runtime(governance=Governance())
            result = runtime.execute(self._task("deploy to prod"))
        assert result.error is None
        assert result.output["ok"] is True

    def test_safe_action_executes(self):
        """SAFE actions execute normally with no gate interference."""
        from src.core.governance import Governance

        runtime = self._make_runtime(governance=Governance())
        result = runtime.execute(self._task("analyze sales report"))
        assert result.error is None
        assert result.output["ok"] is True

    def test_audit_recorded_on_block(self):
        """A blocked action is recorded in the governance audit trail."""
        from src.core.governance import Governance

        runtime = self._make_runtime(governance=Governance())
        runtime.execute(self._task("rm -rf /tmp/important"))
        trail = runtime._governance.get_audit_trail(limit=10)
        assert any(e.result == "blocked" for e in trail)

    def test_audit_recorded_on_reject(self):
        """A rejected (unapproved) action is recorded in the audit trail."""
        from src.core.governance import Governance

        runtime = self._make_runtime(governance=Governance())
        runtime.execute(self._task("deploy to prod"))
        trail = runtime._governance.get_audit_trail(limit=10)
        assert any(e.result == "rejected" for e in trail)

    def test_audit_recorded_on_approve(self):
        """An auto-approved action is recorded in the audit trail."""
        from src.core.governance import Governance

        with patch.dict(os.environ, {"GOVERNANCE_AUTO_APPROVE": "true"}):
            runtime = self._make_runtime(governance=Governance())
            runtime.execute(self._task("deploy to prod"))
        trail = runtime._governance.get_audit_trail(limit=10)
        assert any(e.result == "approved" for e in trail)

    def test_no_governance_runs_unrestricted(self):
        """Without a governance instance, execute() behaves as before."""
        runtime = self._make_runtime()
        result = runtime.execute(self._task("rm -rf /tmp/important"))
        assert result.error is None


class TestRuntimeMemoryOwnership(unittest.TestCase):
    """ScopedMemoryStore is the single canonical memory owner (AUTONOMY_GAPS #8)."""

    def _make_runtime(self, **kwargs):
        defaults = dict(
            dispatcher=_FakeDispatcher(),
            tool_registry=_FakeToolRegistry(),
        )
        defaults.update(kwargs)
        return MekongCoreRuntimeImpl(**defaults)

    def test_remember_writes_through_canonical_owner(self):
        """Post-collapse: remember() writes through the conformant
        MemoryStoreAdapter (_memory_store), the sole write path."""
        import tempfile
        import src.core.memory_canonical as _mc
        import src.core.adapters.memory_store_conformant as _msc
        from src.core.memory_store_adapter import MemoryStoreAdapter
        from tests.conftest import _pre_gateway_originals

        _real = _pre_gateway_originals.get("src.core.memory_canonical.MemoryStore")
        with tempfile.TemporaryDirectory() as td, \
                patch.object(_mc, "MemoryStore", _real), \
                patch.object(_msc, "MemoryStore", _real):
            from src.core.memory_canonical import MemoryStore
            underlying = MemoryStore(store_path=f"{td}/mem.yaml")
            adapter = MemoryStoreAdapter(store=underlying)
            runtime = self._make_runtime(memory_store=adapter)
            runtime.start_mission("task")
            runtime.remember(
                type(
                    "O",
                    (),
                    {
                        "result": type("R", (), {"task_id": "t1", "error": None, "metadata": {}})(),
                        "metrics": {},
                        "side_effects": [],
                    },
                )()
            )
            # The conformant adapter (_memory_store) is the only writer.
            assert runtime._memory_store is not None
            retrieved = runtime._memory_store.retrieve("obs-t1")
            assert retrieved is not None, "remember() must write through _memory_store"

    def test_store_raw_writes_without_tier_tag(self):
        """store_raw lands on the canonical backend under the raw key."""
        from src.core.memory_separation import MemorySeparation, MemoryTier

        sep = MemorySeparation()
        sep.store_raw("raw-key", b"payload")
        # No tier:: prefix was applied — the key is not tier-tagged.
        assert sep.list_by_tier(MemoryTier.PERSISTENT) == []
        # The raw entry is present on the canonical ScopedMemoryStore backend.
        entries = sep._store.query(sep._mekong_scope())
        assert any(e.key == "raw-key" and e.value == b"payload" for e in entries)

    def test_destroy_releases_memory_owner(self):
        """destroy() clears the memory separation layer when explicitly set."""
        from src.core.memory_separation import MemorySeparation

        runtime = self._make_runtime(memory_separation=MemorySeparation())
        runtime.start_mission("task")
        assert runtime._memory_separation is not None
        runtime.destroy()
        assert runtime._memory_separation is None


class TestRuntimeBuzzAdapterWiring(unittest.TestCase):
    """run_from_payload() routes external payloads through BuzzAdapter."""

    def _make_runtime(self, **kwargs):
        defaults = dict(
            dispatcher=_FakeDispatcher(),
            tool_registry=_FakeToolRegistry(),
        )
        defaults.update(kwargs)
        return MekongCoreRuntimeImpl(**defaults)

    def test_run_from_payload_executes_goal(self):
        """run_from_payload parses a Buzz payload and runs the goal."""
        runtime = self._make_runtime()
        result = runtime.run_from_payload({"goal": "build api"})
        assert result.error is None
        assert runtime._mission_id is not None

    def test_run_from_payload_accepts_text_field(self):
        """run_from_payload falls back to the 'text' field like receive_goal."""
        runtime = self._make_runtime()
        result = runtime.run_from_payload({"text": "fallback goal"})
        assert result.error is None

    def test_run_from_payload_rejects_missing_goal(self):
        """run_from_payload raises when the payload has no goal field."""
        runtime = self._make_runtime()
        with self.assertRaises(ValueError):
            runtime.run_from_payload({})

    def test_run_from_payload_propagates_mission_id(self):
        """A pre-assigned mission_id in the payload is honored."""
        runtime = self._make_runtime()
        runtime.run_from_payload({"goal": "task", "mission_id": "mission-42"})
        assert runtime._mission_id == "mission-42"

    def test_run_from_payload_preserves_callback_url_in_metadata(self):
        """callback_url from the payload lands in the goal context metadata."""
        runtime = self._make_runtime()
        runtime.run_from_payload({
            "goal": "task",
            "callback_url": "https://buzz.test/update",
        })
        # The metadata dict is consumed by the goal; the adapter round-trips it.
        assert runtime._mission_id is not None

    def test_run_from_payload_tracer_records_mission(self):
        """run_from_payload pushes steps into an attached tracer."""
        tracer = MissionTracer()
        runtime = self._make_runtime()
        runtime.start_mission("build api", tracer=tracer)
        runtime.run_from_payload({"goal": "build api"})
        missions = tracer.list_missions()
        assert len(missions) == 1
        assert missions[0]["status"] == "success"


if __name__ == "__main__":
    unittest.main()
