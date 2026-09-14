# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Invariant 5 — Mission trace correlation via TelemetryEmitter.

Pins core-contract.md invariant 5: all telemetry carries ``mission_id``;
``run()`` and ``run_from_payload()`` both produce complete start/step/finish
traces. The emitter composes TelemetryCollector (never forks it) and records
every event in ``emitter.events`` regardless of consent so the correlated
trace is inspectable in tests.

Stubs sit ONLY at the telemetry boundary (dispatcher / tool registry); the
runtime loop runs unmocked.
"""

from __future__ import annotations

import pytest

from src.core.protocols import ObservabilitySink
from src.core.runtime_adapter import MekongCoreRuntimeImpl
from src.core.telemetry_collector import TelemetryCollector
from src.core.telemetry_emitter import (
    PHASE_FINISH,
    PHASE_START,
    PHASE_STEP,
    TelemetryEmitter,
)


class _OkDispatcher:
    def dispatch(self, task, agent=None):
        return {"ok": True, "task_id": task.id}


def _emitter(tmp_path) -> TelemetryEmitter:
    """Emitter bound to a tmp collector so tests never touch ~/.mekong."""
    collector = TelemetryCollector(output_dir=str(tmp_path / "telemetry"))
    return TelemetryEmitter(collector=collector)


def _runtime(tmp_path, emitter: TelemetryEmitter) -> MekongCoreRuntimeImpl:
    return MekongCoreRuntimeImpl(
        dispatcher=_OkDispatcher(),
        tool_registry=type("_R", (), {"execute": lambda s, t, p: {"ok": True}})(),
        telemetry=emitter,
    )


class TestEmitterProtocol:
    def test_conforms_to_observability_sink(self, tmp_path):
        emitter = _emitter(tmp_path)
        assert isinstance(emitter, ObservabilitySink)
        assert hasattr(emitter, "emit")
        assert hasattr(emitter, "flush")

    def test_record_guarantees_non_empty_mission_id(self, tmp_path):
        emitter = _emitter(tmp_path)
        event = emitter._record("custom", None, {"k": "v"})
        assert event["mission_id"]
        assert event["mission_id"].startswith("mission_")

    def test_explicit_mission_id_preserved(self, tmp_path):
        emitter = _emitter(tmp_path)
        event = emitter.emit_start("mission-abc", "goal")
        assert event["mission_id"] == "mission-abc"


class TestRunPathThreePhaseTrace:
    def test_run_produces_start_step_finish(self, tmp_path):
        emitter = _emitter(tmp_path)
        rt = _runtime(tmp_path, emitter)
        result = rt.run("trace the plain run")
        assert result.error is None

        phases = emitter.phases()
        assert phases.count(PHASE_START) == 1
        assert phases.count(PHASE_STEP) >= 1
        assert phases.count(PHASE_FINISH) == 1
        # Ordering: start first, finish last.
        assert phases[0] == PHASE_START
        assert phases[-1] == PHASE_FINISH

    def test_run_every_event_has_non_empty_mission_id(self, tmp_path):
        emitter = _emitter(tmp_path)
        rt = _runtime(tmp_path, emitter)
        rt.run("correlate me")
        assert emitter.events, "expected at least one emitted event"
        for event in emitter.events:
            assert event.get("mission_id"), f"event missing mission_id: {event}"

    def test_run_all_events_share_single_mission_id(self, tmp_path):
        emitter = _emitter(tmp_path)
        rt = _runtime(tmp_path, emitter)
        rt.run("single correlation")
        assert emitter.mission_ids() == {rt._mission_id}


class TestRunFromPayloadPathThreePhaseTrace:
    def test_payload_produces_start_step_finish(self, tmp_path):
        emitter = _emitter(tmp_path)
        rt = _runtime(tmp_path, emitter)
        result = rt.run_from_payload({"goal": "payload task", "mission_id": "mission-42"})
        assert result.error is None

        phases = emitter.phases()
        assert phases.count(PHASE_START) == 1
        assert phases.count(PHASE_STEP) >= 1
        assert phases.count(PHASE_FINISH) == 1
        assert phases[0] == PHASE_START
        assert phases[-1] == PHASE_FINISH

    def test_payload_honors_pre_assigned_mission_id(self, tmp_path):
        emitter = _emitter(tmp_path)
        rt = _runtime(tmp_path, emitter)
        rt.run_from_payload({"goal": "payload task", "mission_id": "mission-42"})
        assert rt._mission_id == "mission-42"
        # Every event correlates under the payload's pre-assigned id.
        assert emitter.mission_ids() == {"mission-42"}

    def test_payload_every_event_has_non_empty_mission_id(self, tmp_path):
        emitter = _emitter(tmp_path)
        rt = _runtime(tmp_path, emitter)
        rt.run_from_payload({"goal": "payload task", "mission_id": "mission-99"})
        assert emitter.events
        for event in emitter.events:
            assert event.get("mission_id"), f"event missing mission_id: {event}"


class TestNoUncorrelatedEvents:
    def test_emit_without_mission_id_gets_fallback(self, tmp_path):
        emitter = _emitter(tmp_path)
        emitter.emit({"event_type": "task_completed", "mission_id": None})
        assert emitter.events[-1]["mission_id"]
        assert emitter.events[-1]["mission_id"].startswith("mission_")

    def test_emit_routes_task_completed_to_step(self, tmp_path):
        emitter = _emitter(tmp_path)
        emitter.emit({"event_type": "task_completed", "mission_id": "m-1"})
        assert emitter.phases()[-1] == PHASE_STEP

    def test_emit_routes_run_completed_to_finish(self, tmp_path):
        emitter = _emitter(tmp_path)
        emitter.emit({"event_type": "run_completed", "mission_id": "m-1", "error": None})
        assert emitter.phases()[-1] == PHASE_FINISH
        assert emitter.events[-1]["outcome"] == "success"

    def test_emit_run_completed_with_error_marks_failed(self, tmp_path):
        emitter = _emitter(tmp_path)
        emitter.emit({"event_type": "run_completed", "mission_id": "m-1", "error": "boom"})
        assert emitter.events[-1]["outcome"] == "failed"


if __name__ == "__main__":
    pytest.main([__file__])
