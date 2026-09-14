# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for Buzz outbound transport + BuzzRuntimeAdapter (v0.1 interface).

Covers:
- BuzzAdapter transport injection, callback POST on send_update, silent
  no-op without callback_url (backward-compat), error swallowing with log.
- Serialization round-trip through receive_goal/send_update.
- BuzzRuntimeAdapter: sessions, assign_mission end-to-end with a real
  MekongCoreRuntimeImpl + MissionTracer, stream_event, request_approval,
  cooperative cancel between steps, get_status/get_artifacts.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from src.core.buzz_adapter import BuzzAdapter, BuzzConfigError
from src.core.buzz_runtime_adapter import BuzzRuntimeAdapter
from src.core.mission_tracer import MissionTracer
from src.core.runtime_adapter import MekongCoreRuntimeImpl


class RecordingTransport:
    """Fake transport capturing every (url, payload) delivery."""

    def __init__(self, status: int = 200) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.status = status

    def __call__(self, url: str, payload: dict[str, Any]) -> int:
        self.calls.append((url, payload))
        return self.status


class _OkDispatcher:
    def dispatch(self, task: Any, agent: Any = None) -> dict[str, Any]:
        return {"ok": True, "task_id": task.id}


def _runtime(dispatcher: Any = None) -> MekongCoreRuntimeImpl:
    return MekongCoreRuntimeImpl(
        dispatcher=dispatcher or _OkDispatcher(),
        tool_registry=type("_R", (), {"execute": lambda s, t, p: {"ok": True}})(),
    )


class TestBuzzTransport:
    def test_default_transport_is_urllib_callable(self):
        from src.core.buzz_adapter import _urllib_transport

        adapter = BuzzAdapter()
        assert callable(adapter.transport)
        assert adapter.transport is _urllib_transport

    def test_send_update_without_callback_is_silent_noop(self):
        transport = RecordingTransport()
        adapter = BuzzAdapter(transport=transport)
        result = adapter.send_update("running", {"progress": 10})
        assert result == {"status": "running", "data": {"progress": 10}}
        assert transport.calls == []  # nothing delivered

    def test_send_update_with_callback_posts_payload(self):
        transport = RecordingTransport()
        adapter = BuzzAdapter(transport=transport)
        adapter.send_update("completed", {"output": "done"}, callback_url="https://buzz.test/cb")
        assert len(transport.calls) == 1
        url, payload = transport.calls[0]
        assert url == "https://buzz.test/cb"
        assert payload == {"status": "completed", "data": {"output": "done"}}

    def test_transport_error_is_swallowed_and_logged(self, caplog):
        def boom(url: str, payload: dict[str, Any]) -> int:
            raise ConnectionError("network down")

        adapter = BuzzAdapter(transport=boom)
        with caplog.at_level(logging.WARNING, logger="src.core.buzz_adapter"):
            result = adapter.send_update("failed", {"err": "x"}, callback_url="https://buzz.test/cb")
        assert result == {"status": "failed", "data": {"err": "x"}}  # mission did not crash
        assert any(rec.getMessage() and "Buzz transport raised" in rec.getMessage()
                   for rec in caplog.records)

    def test_non_2xx_status_still_returns_update(self):
        transport = RecordingTransport(status=503)
        adapter = BuzzAdapter(transport=transport)
        result = adapter.send_update("running", {}, callback_url="https://buzz.test/cb")
        assert result == {"status": "running", "data": {}}
        assert transport.calls[0][0] == "https://buzz.test/cb"


class TestSerializationRoundTrip:
    def test_receive_goal_then_send_update_round_trip(self):
        transport = RecordingTransport()
        adapter = BuzzAdapter(transport=transport)
        inbound = {
            "goal": "ship it",
            "context": {"env": "staging"},
            "callback_url": "https://buzz.test/cb",
            "mission_id": "m-77",
        }
        parsed = adapter.receive_goal(inbound)
        # JSON-serializable both ways.
        assert json.loads(json.dumps(parsed)) == parsed
        out = adapter.send_update(
            "completed", {"mission_id": parsed["mission_id"]},
            callback_url=parsed["callback_url"],
        )
        assert json.loads(json.dumps(out)) == out
        url, payload = transport.calls[0]
        assert url == parsed["callback_url"]
        assert payload["data"]["mission_id"] == "m-77"


class TestBuzzRuntimeAdapterInterface:
    INTERFACE_METHODS = (
        "start_session", "stop_session", "assign_mission", "stream_event",
        "request_approval", "cancel_mission", "get_status", "get_artifacts",
    )

    def test_interface_version(self):
        assert BuzzRuntimeAdapter.INTERFACE_VERSION == "v0.1"

    def test_all_interface_methods_present(self):
        for name in self.INTERFACE_METHODS:
            assert callable(getattr(BuzzRuntimeAdapter, name, None)), name


class TestSessions:
    def test_start_and_stop_session(self):
        bra = BuzzRuntimeAdapter()
        info = bra.start_session("quarterly report", session_id="s-1")
        assert info["status"] == "open"
        assert info["interface_version"] == "v0.1"
        stopped = bra.stop_session("s-1")
        assert stopped["status"] == "closed"

    def test_duplicate_session_rejected(self):
        bra = BuzzRuntimeAdapter()
        bra.start_session("a", session_id="dup")
        with pytest.raises(ValueError, match="already open"):
            bra.start_session("b", session_id="dup")

    def test_stop_unknown_session_is_idempotent(self):
        bra = BuzzRuntimeAdapter()
        assert bra.stop_session("ghost")["status"] == "unknown"


class TestAssignMission:
    def test_assign_mission_runs_runtime_and_traces_steps(self):
        tracer = MissionTracer()
        transport = RecordingTransport()
        bra = BuzzRuntimeAdapter(runtime=_runtime(), tracer=tracer, transport=transport)
        outcome = bra.assign_mission({
            "goal": "do work",
            "callback_url": "https://buzz.test/cb",
            "mission_id": "m-1",
        })
        assert outcome["status"] == "completed"
        assert outcome["error"] is None
        assert outcome["interface_version"] == "v0.1"
        # Completion update delivered to the payload's callback URL.
        assert transport.calls[-1][0] == "https://buzz.test/cb"
        assert transport.calls[-1][1]["status"] == "completed"
        # Tracer recorded the mission and its steps.
        missions = tracer.list_missions()
        assert len(missions) >= 1
        record = tracer.get_mission(outcome["mission_id"])
        assert record is not None
        assert len(record.steps) >= 1

    def test_assign_mission_failure_delivers_failed_update(self):
        class _FailDispatcher:
            def dispatch(self, task: Any, agent: Any = None) -> dict[str, Any]:
                raise RuntimeError("kaput")

        transport = RecordingTransport()
        bra = BuzzRuntimeAdapter(
            runtime=_runtime(dispatcher=_FailDispatcher()),
            transport=transport,
        )
        outcome = bra.assign_mission(
            {"goal": "break", "callback_url": "https://buzz.test/cb"}
        )
        assert outcome["status"] == "failed"
        # Repair cap surfaces a terminal error after exhausting retries.
        assert outcome["data"]["error"]
        assert transport.calls[-1][1]["status"] == "failed"
        assert transport.calls[-1][0] == "https://buzz.test/cb"

    def test_assign_mission_without_callback_does_not_call_transport(self):
        transport = RecordingTransport()
        bra = BuzzRuntimeAdapter(runtime=_runtime(), transport=transport)
        outcome = bra.assign_mission({"goal": "quiet task"})
        assert outcome["status"] == "completed"
        assert transport.calls == []

    def test_assign_mission_without_runtime_raises(self):
        bra = BuzzRuntimeAdapter()
        with pytest.raises(BuzzConfigError, match="no runtime wired"):
            bra.assign_mission({"goal": "x"})

    def test_crashing_runtime_is_caught_not_raised(self):
        class _ExplodingRuntime:
            _mission_id = None

            def start_mission(self, *a: Any, **k: Any) -> str:
                return "m-x"

            def run_from_payload(self, payload: dict[str, Any]) -> Any:
                raise ValueError("payload from hell")

        transport = RecordingTransport()
        bra = BuzzRuntimeAdapter(runtime=_ExplodingRuntime(), transport=transport)
        outcome = bra.assign_mission(
            {"goal": "boom", "callback_url": "https://buzz.test/cb"},
            session_id="s-9",
        )
        assert outcome["status"] == "failed"
        assert "payload from hell" in outcome["data"]["error"]
        assert transport.calls[-1][1]["status"] == "failed"
        assert transport.calls[-1][0] == "https://buzz.test/cb"


class TestCancelBetweenSteps:
    def test_cancel_mission_sets_flag_on_runtime(self):
        rt = _runtime()
        bra = BuzzRuntimeAdapter(runtime=rt)
        verdict = bra.cancel_mission()
        assert verdict["cancelled"] is True
        assert getattr(rt, "_cancel_requested") is True

    def test_cancel_flag_checked_before_execute(self):
        rt = _runtime()
        rt._cancel_requested = True
        executed: list[Any] = []

        class _SpyDispatcher:
            def dispatch(self, task: Any, agent: Any = None) -> dict[str, Any]:
                executed.append(task.id)
                return {"ok": True}

        rt._dispatcher = _SpyDispatcher()  # type: ignore[assignment]
        result = rt.run_from_payload({"goal": "never runs"})
        assert executed == []
        assert result.error == "mission cancelled"
        assert result.metadata.get("cancelled") is True

    def test_cancel_between_repair_attempts_short_circuits_loop(self):
        attempts: list[int] = []

        class _FlakyThenCancelled:
            def dispatch(self, task: Any, agent: Any = None) -> dict[str, Any]:
                attempts.append(1)
                if len(attempts) == 1:
                    # Flip the cancel flag mid-mission; the loop must observe
                    # it BEFORE the next execute attempt.
                    rt._cancel_requested = True
                return {"ok": False}

        rt = _runtime(dispatcher=_FlakyThenCancelled())
        bra = BuzzRuntimeAdapter(runtime=rt)
        outcome = bra.assign_mission({"goal": "long mission"})
        assert outcome["status"] == "cancelled"
        assert outcome["data"]["cancelled"] is True
        assert outcome["error"] == "mission cancelled"
        # Exactly one real attempt happened; the second was cancelled away.
        assert len(attempts) == 1


class TestStreamEventAndApproval:
    def test_stream_event_noop_without_callback(self):
        transport = RecordingTransport()
        bra = BuzzRuntimeAdapter(transport=transport)
        event = bra.stream_event("progress", {"pct": 40})
        assert event == {"status": "progress", "data": {"pct": 40}}
        assert transport.calls == []

    def test_stream_event_delivers_with_callback(self):
        transport = RecordingTransport()
        bra = BuzzRuntimeAdapter(transport=transport)
        bra.stream_event("progress", {"pct": 40}, callback_url="https://buzz.test/ev")
        assert transport.calls == [("https://buzz.test/ev", {"status": "progress", "data": {"pct": 40}})]

    def test_request_approval_denies_by_default(self):
        bra = BuzzRuntimeAdapter()
        assert bra.request_approval("delete production db") is False

    def test_request_approval_delegates_to_approver(self):
        bra = BuzzRuntimeAdapter(approver=lambda goal, reason: reason == "human said yes")
        assert bra.request_approval("risky thing", reason="human said yes") is True
        assert bra.request_approval("risky thing", reason="because") is False

    def test_request_approval_swallows_approver_errors(self):
        def bad_approver(goal: str, reason: str) -> bool:
            raise RuntimeError("approver offline")

        bra = BuzzRuntimeAdapter(approver=bad_approver)
        assert bra.request_approval("anything") is False


class TestStatusAndArtifacts:
    def test_get_status_from_tracer(self):
        tracer = MissionTracer()
        bra = BuzzRuntimeAdapter(runtime=_runtime(), tracer=tracer)
        outcome = bra.assign_mission({"goal": "tracked"})
        status = bra.get_status(outcome["mission_id"])
        assert status["mission_id"] == outcome["mission_id"]
        assert status["status"] in ("success", "failed")

    def test_get_status_unknown_mission(self):
        bra = BuzzRuntimeAdapter(tracer=MissionTracer())
        assert bra.get_status("missing")["status"] == "unknown"

    def test_get_status_live_fallback(self):
        rt = _runtime()
        bra = BuzzRuntimeAdapter(runtime=rt)
        live = bra.get_status()
        assert live["status"] == "idle"
        rt.start_mission("g")
        live = bra.get_status()
        assert live["status"] == "running"
        assert live["mission_id"] == getattr(rt, "_mission_id")

    def test_get_artifacts_returns_traced_steps(self):
        tracer = MissionTracer()
        bra = BuzzRuntimeAdapter(runtime=_runtime(), tracer=tracer)
        outcome = bra.assign_mission({"goal": "artifact hunt"})
        artifacts = bra.get_artifacts(outcome["mission_id"])
        assert isinstance(artifacts, list)
        assert len(artifacts) >= 1
        assert all(set(a) >= {"step", "result"} for a in artifacts)

    def test_get_artifacts_empty_without_tracer(self):
        bra = BuzzRuntimeAdapter()
        assert bra.get_artifacts("whatever") == []
