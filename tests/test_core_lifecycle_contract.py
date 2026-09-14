# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Core Contract tests — canonical 10-stage lifecycle of MekongCoreRuntimeImpl.

Contract order:
    GOAL -> CONTEXT -> PLAN -> DELEGATE -> EXECUTE -> OBSERVE -> VERIFY ->
    REPAIR -> REMEMBER -> COMMIT

Single canonical implementation lives in src/core/runtime_adapter.py. These
tests pin the stage-to-method mapping, the repair cap, and the mission-trace
idempotency mechanism: ``run()`` opens a mission ONLY when none is active,
while ``run_from_payload()`` bypasses ``run()`` entirely (calls ``_run_goal``
directly) so neither path can double-start a mission.

Stubs here sit ONLY at the telemetry boundary (tracer / telemetry sink /
dispatcher); business logic runs unmocked.
"""

from __future__ import annotations

import inspect
import uuid

import pytest

from src.core.runtime_adapter import (
    MekongCoreRuntimeImpl,
    RepairStrategy,
    _MAX_REPAIR_ATTEMPTS,
)

STAGE_CONTRACT = (
    "GOAL",
    "CONTEXT",
    "PLAN",
    "DELEGATE",
    "EXECUTE",
    "OBSERVE",
    "VERIFY",
    "REPAIR",
    "REMEMBER",
    "COMMIT",
)

# Stage -> real method name on MekongCoreRuntimeImpl (CONTEXT is embedded in
# goal(): the Context dataclass travels as goal()'s second parameter).
STAGE_METHODS = {
    "GOAL": "goal",
    "PLAN": "plan",
    "DELEGATE": "delegate",
    "EXECUTE": "execute",
    "OBSERVE": "observe",
    "VERIFY": "verify",
    "REPAIR": "repair",
    "REMEMBER": "remember",
    "COMMIT": "commit",
}


class _OkDispatcher:
    def dispatch(self, task, agent=None):
        return {"ok": True, "task_id": task.id}


class _FailingDispatcher:
    """Always-failing dispatcher used to exercise verify/repair paths."""

    def __init__(self):
        self.calls = 0

    def dispatch(self, task, agent=None):
        self.calls += 1
        raise RuntimeError("boom")


class RecordingTracer:
    """Telemetry-boundary stub capturing mission_start/step/finish events."""

    def __init__(self):
        self.events: list[tuple[str, object]] = []
        self.starts = 0

    def start_mission(self, goal, metadata=None):
        self.starts += 1
        mission_id = f"mission_{uuid.uuid4().hex[:8]}"
        self.events.append(("mission_start", goal))
        return mission_id

    def log_step(self, mission_id, step, result):
        self.events.append(("step", step))

    def end_mission(self, mission_id, outcome):
        self.events.append(("mission_finish", outcome))


def _runtime(dispatcher=None) -> MekongCoreRuntimeImpl:
    return MekongCoreRuntimeImpl(
        dispatcher=dispatcher or _OkDispatcher(),
        tool_registry=type("_R", (), {"execute": lambda s, t, p: {"ok": True}})(),
    )


class TestStageContract:
    def test_ten_stages_in_canonical_order(self):
        assert STAGE_CONTRACT == (
            "GOAL", "CONTEXT", "PLAN", "DELEGATE", "EXECUTE",
            "OBSERVE", "VERIFY", "REPAIR", "REMEMBER", "COMMIT",
        )

    def test_stage_mapping_targets_real_methods(self):
        for stage, method in STAGE_METHODS.items():
            attr = getattr(MekongCoreRuntimeImpl, method, None)
            assert callable(attr), f"stage {stage} maps to missing method {method}"

    def test_context_is_embedded_in_goal(self):
        params = inspect.signature(MekongCoreRuntimeImpl.goal).parameters
        assert "context" in params
        goal = MekongCoreRuntimeImpl.goal(
            _runtime(), "intent", type("Ctx", (), {})()
        )
        assert hasattr(goal, "context")

    def test_run_executes_stages_in_contract_order(self):
        rt = _runtime(dispatcher=_FailingDispatcher())
        seen: list[str] = []
        for stage, method in STAGE_METHODS.items():
            original = getattr(type(rt), method)

            def make_recorder(fn, tag):
                def recorder(*args, **kwargs):
                    if tag not in seen:
                        seen.append(tag)
                    return fn(*args, **kwargs)
                return recorder

            setattr(rt, method, make_recorder(original.__get__(rt), stage))
        rt.run("contract order probe")
        expected = [s for s in STAGE_CONTRACT if s != "CONTEXT"]
        assert seen == expected, f"observed {seen}, expected {expected}"


class TestRepairCap:
    def test_cap_constant_is_three(self):
        assert _MAX_REPAIR_ATTEMPTS == 3

    def test_failing_task_capped_at_max_repairs(self):
        dispatcher = _FailingDispatcher()
        rt = _runtime(dispatcher=dispatcher)
        result = rt.run("failing goal")
        assert result.error is not None
        # Real dispatches never exceed the cap: once _repair_count reaches 3,
        # execute()'s Gate 1 short-circuits before hitting the dispatcher.
        assert dispatcher.calls == _MAX_REPAIR_ATTEMPTS
        assert rt._repair_count == _MAX_REPAIR_ATTEMPTS

    def test_repair_escalates_once_cap_reached(self):
        rt = _runtime()
        for _ in range(_MAX_REPAIR_ATTEMPTS):
            action = rt.repair(
                type("V", (), {"failures": ["check exit_code failed"]})()
            )
            assert action.strategy in (
                RepairStrategy.RETRY,
                RepairStrategy.FALLBACK,
            )
        escalated = rt.repair(type("V", (), {"failures": ["still bad"]})())
        assert escalated.strategy == RepairStrategy.ESCALATE


class TestPlainRunMissionTrace:
    def test_plain_run_records_full_mission_trace(self):
        tracer = RecordingTracer()
        rt = _runtime()
        rt._mission_tracer = tracer  # telemetry-boundary seam injection
        result = rt.run("trace me")
        assert result.error is None
        kinds = [e[0] for e in tracer.events]
        assert kinds.count("mission_start") == 1
        assert kinds.count("step") >= 1
        assert kinds.count("mission_finish") == 1
        assert tracer.events[-1] == ("mission_finish", "success")

    def test_plain_run_without_tracer_still_correlates_telemetry(self):
        captured: list[dict] = []

        class _Sink:
            def emit(self, event):
                captured.append(event)

            def flush(self):
                pass

        rt = _runtime()
        rt._telemetry = _Sink()
        rt.run("bare correlation")
        events = [e for e in captured if e.get("event_type") in ("task_completed", "run_completed")]
        assert events, "expected telemetry emissions"
        mission_ids = {e["mission_id"] for e in events}
        assert mission_ids == {rt._mission_id}
        assert rt._mission_id is not None

    def test_pre_started_mission_not_double_started_by_run(self):
        tracer = RecordingTracer()
        rt = _runtime()
        rt.start_mission("cli style", tracer=tracer)
        rt.run("cli style")
        rt.run("cli style again")
        assert tracer.starts == 1  # continuation under the active mission


class TestPayloadPathRegression:
    def test_payload_mission_id_honored_without_double_start(self):
        rt = _runtime()
        result = rt.run_from_payload({"goal": "task", "mission_id": "mission-42"})
        assert result.error is None
        assert rt._mission_id == "mission-42"

    def test_payload_with_tracer_starts_exactly_one_mission(self):
        tracer = RecordingTracer()
        rt = _runtime()
        rt._mission_tracer = tracer
        rt.run_from_payload({"goal": "task", "mission_id": "mission-43"})
        assert tracer.starts == 1
        kinds = [e[0] for e in tracer.events]
        assert kinds.count("mission_finish") == 1

    def test_payload_path_never_routes_through_run(self):
        class _NoRunRuntime(MekongCoreRuntimeImpl):
            def run(self, goal_text):
                raise AssertionError("run_from_payload must bypass run()")

        rt = _NoRunRuntime(dispatcher=_OkDispatcher(), tool_registry=_runtime().__dict__["_tool_registry"])
        result = rt.run_from_payload({"goal": "direct path"})
        assert result.error is None


if __name__ == "__main__":
    pytest.main([__file__])
