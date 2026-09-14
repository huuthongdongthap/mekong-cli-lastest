# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Telemetry Emitter — real ObservabilitySink with mission_id correlation.

Produces complete 3-phase traces (start / step / finish) where every emitted
event carries a non-empty ``mission_id`` (core-contract invariant 5). Composes
the existing :class:`TelemetryCollector` for persistence rather than forking
it, so consent handling and buffering stay in one place.

The emitter records every event in ``self.events`` regardless of consent so
callers and tests can inspect the full correlated trace; the collector side
no-ops when consent has not been granted.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from src.core.telemetry_collector import TelemetryCollector, get_collector

# Event type names for the three trace phases.
PHASE_START = "mission_start"
PHASE_STEP = "mission_step"
PHASE_FINISH = "mission_finish"


class TelemetryEmitter:
    """ObservabilitySink that emits start/step/finish events with mission_id.

    Satisfies ``protocols.ObservabilitySink`` (``emit`` / ``flush``) and adds
    an explicit 3-phase API (``emit_start`` / ``emit_step`` / ``emit_finish``)
    that the runtime calls to guarantee a complete correlated trace on both
    ``run()`` and ``run_from_payload()`` paths.
    """

    def __init__(self, collector: Optional[TelemetryCollector] = None) -> None:
        self._collector = collector or get_collector()
        # Full correlated trace, independent of consent, for inspection/tests.
        self.events: List[Dict[str, Any]] = []

    # ===== 3-phase trace API =====

    def emit_start(self, mission_id: Optional[str], goal: str) -> Dict[str, Any]:
        """Emit the mission start phase."""
        event = self._record(PHASE_START, mission_id, {"goal": goal})
        mid = event["mission_id"]
        self._safe(lambda: self._collector.session_start(mission_id=mid))
        return event

    def emit_step(self, mission_id: Optional[str], step: Dict[str, Any]) -> Dict[str, Any]:
        """Emit a single step phase."""
        event = self._record(PHASE_STEP, mission_id, dict(step))
        mid = event["mission_id"]
        self._safe(
            lambda: self._collector.command_executed(
                command_name=str(step.get("title", "step")),
                duration_ms=int(float(step.get("duration_seconds", 0.0) or 0.0) * 1000),
                exit_code=int(step.get("exit_code", 0) or 0),
                error_type="step_failed" if step.get("error") else None,
                mission_id=mid,
            )
        )
        return event

    def emit_finish(self, mission_id: Optional[str], outcome: str) -> Dict[str, Any]:
        """Emit the mission finish phase."""
        event = self._record(PHASE_FINISH, mission_id, {"outcome": outcome})
        mid = event["mission_id"]
        if outcome != "success":
            self._safe(
                lambda: self._collector.error_occurred(
                    error_type="mission_failed",
                    error_message=str(outcome),
                    mission_id=mid,
                )
            )
        self._safe(lambda: self._collector.session_end(mission_id=mid))
        return event

    # ===== ObservabilitySink protocol =====

    def emit(self, event: Dict[str, Any]) -> None:
        """Emit a generic telemetry event, enforcing mission_id correlation.

        Routes the runtime's ``task_completed`` / ``run_completed`` events onto
        the step / finish phases so any sink-driven emission still lands in the
        correlated trace. Unknown event types are recorded verbatim.
        """
        event_type = event.get("event_type", "unknown")
        mission_id = event.get("mission_id")
        if event_type == "task_completed":
            self.emit_step(
                mission_id,
                {
                    "title": event.get("command", "task"),
                    "task_id": event.get("task_id"),
                    "error": event.get("error"),
                    "estimated_cost": event.get("estimated_cost"),
                    "duration_seconds": float(event.get("metric", 0.0) or 0.0),
                },
            )
        elif event_type == "run_completed":
            outcome = "failed" if event.get("error") else "success"
            self.emit_finish(mission_id, outcome)
        else:
            self._record(event_type, mission_id, dict(event))

    def flush(self) -> None:
        """Flush buffered events. The collector flushes on size/atexit."""

    # ===== Inspection helpers =====

    def phases(self) -> List[str]:
        """Return the ordered event_type sequence of the recorded trace."""
        return [e["event_type"] for e in self.events]

    def mission_ids(self) -> set:
        """Return the set of mission_ids across all recorded events."""
        return {e.get("mission_id") for e in self.events}

    # ===== internals =====

    def _record(
        self, event_type: str, mission_id: Optional[str], properties: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Record an event, guaranteeing a non-empty mission_id."""
        resolved = mission_id if mission_id else self._fallback_mission_id()
        event: Dict[str, Any] = {
            "event_type": event_type,
            "mission_id": resolved,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for key, value in properties.items():
            if key not in ("event_type", "mission_id", "timestamp"):
                event[key] = value
        self.events.append(event)
        return event

    @staticmethod
    def _fallback_mission_id() -> str:
        return f"mission_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _safe(fn: Callable[[], None]) -> None:
        """Run a collector call best-effort; telemetry never breaks the loop."""
        try:
            fn()
        except Exception:
            pass


def create_emitter(collector: Optional[TelemetryCollector] = None) -> TelemetryEmitter:
    """Create a TelemetryEmitter, optionally bound to a specific collector."""
    return TelemetryEmitter(collector=collector)
