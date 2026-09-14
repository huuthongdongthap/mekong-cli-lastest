# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""BuzzRuntimeAdapter — versioned in-process facade over MekongCoreRuntime.

Wraps :class:`src.core.buzz_adapter.BuzzAdapter` (goal parsing + outbound
transport), :class:`src.core.runtime_adapter.MekongCoreRuntimeImpl`
(``run_from_payload`` execution), and :class:`src.core.mission_tracer.MissionTracer`
(step-level correlation) behind one stable, versioned interface.

Contract notes:
- ``INTERFACE_VERSION = "v0.1"`` — callers pin against this string.
- NO invented network protocol: everything is plain Python calls plus the
  injectable ``(url, payload) -> int`` transport owned by ``BuzzAdapter``.
- Approval requests deny by default, mirroring governance semantics.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from src.core.buzz_adapter import BuzzAdapter, BuzzConfigError

logger = logging.getLogger(__name__)

Approver = Callable[[str, str], bool]


@dataclass
class _Session:
    """In-process session bookkeeping."""

    session_id: str
    goal_hint: str
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "open"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_mission_id: str | None = None


class BuzzRuntimeAdapter:
    """Versioned v0.1 interface between Buzz and the core runtime.

    Methods: ``start_session / stop_session / assign_mission / stream_event /
    request_approval / cancel_mission / get_status / get_artifacts``.
    """

    INTERFACE_VERSION = "v0.1"

    def __init__(
        self,
        runtime: Any | None = None,
        tracer: Any | None = None,
        transport: Any | None = None,
        approver: Approver | None = None,
    ) -> None:
        self._runtime = runtime
        self._buzz = BuzzAdapter(transport=transport)
        self._tracer = tracer
        self._approver = approver
        self._sessions: dict[str, _Session] = {}

    @property
    def interface_version(self) -> str:
        return self.INTERFACE_VERSION

    # ------------------------------------------------------------------ #
    # Session lifecycle
    # ------------------------------------------------------------------ #

    def start_session(
        self,
        goal_hint: str = "",
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Open a session. Returns the session descriptor."""
        sid = session_id or f"session_{uuid.uuid4().hex[:8]}"
        if sid in self._sessions:
            raise ValueError(f"session already open: {sid}")
        record = _Session(session_id=sid, goal_hint=goal_hint, metadata=metadata or {})
        self._sessions[sid] = record
        return self.session_info(sid)

    def stop_session(self, session_id: str) -> dict[str, Any]:
        """Close a session. Idempotent on unknown ids."""
        record = self._sessions.get(session_id)
        if record is not None:
            record.status = "closed"
            return self.session_info(session_id)
        logger.info("stop_session ignored unknown session %s", session_id)
        return {"session_id": session_id, "status": "unknown", "interface_version": self.INTERFACE_VERSION}

    def session_info(self, session_id: str) -> dict[str, Any]:
        record = self._sessions.get(session_id)
        if record is None:
            return {"session_id": session_id, "status": "unknown", "interface_version": self.INTERFACE_VERSION}
        return {
            "interface_version": self.INTERFACE_VERSION,
            "session_id": record.session_id,
            "status": record.status,
            "goal_hint": record.goal_hint,
            "metadata": dict(record.metadata),
            "created_at": record.created_at,
            "last_mission_id": record.last_mission_id,
        }

    # ------------------------------------------------------------------ #
    # Mission execution
    # ------------------------------------------------------------------ #

    def assign_mission(
        self,
        payload: dict[str, Any],
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a mission from a Buzz-shaped payload through the core runtime.

        The payload may carry ``mission_id`` and ``callback_url``. When a
        callback URL is present, completion/failure updates are POSTed via
        the injected transport. Returns a serializable outcome descriptor.
        """
        if self._runtime is None:
            raise BuzzConfigError("BuzzRuntimeAdapter has no runtime wired")
        parsed_callback = payload.get("callback_url")
        goal_text = payload.get("goal") or payload.get("text") or ""
        try:
            # Open the mission under OUR tracer so step/finish records are
            # correlated even though run_from_payload() skips start_mission
            # when one is already active.
            self._runtime.start_mission(goal_text, tracer=self._tracer)
            result = self._runtime.run_from_payload(payload)
            mission_id = getattr(self._runtime, "_mission_id", None)
            cancelled = bool(result.metadata.get("cancelled"))
            if result.error is None:
                outcome = "completed"
            elif cancelled:
                outcome = "cancelled"
            else:
                outcome = "failed"
            data = {
                "output": result.output,
                "error": result.error,
                "task_id": result.task_id,
                "interface_version": self.INTERFACE_VERSION,
            }
            if cancelled:
                data["cancelled"] = True
        except Exception as exc:
            logger.error("Mission execution crashed: %s", exc)
            outcome = "failed"
            data = {"error": str(exc), "interface_version": self.INTERFACE_VERSION}
            mission_id = payload.get("mission_id")
        if session_id and session_id in self._sessions:
            self._sessions[session_id].last_mission_id = mission_id
        self._buzz.send_update(outcome, data, callback_url=parsed_callback)
        return {
            "interface_version": self.INTERFACE_VERSION,
            "mission_id": mission_id,
            "status": outcome,
            "data": data,
            **data,
        }

    def stream_event(self, event: str, data: dict[str, Any], callback_url: str | None = None) -> dict[str, Any]:
        """Emit a progress event (no-op delivery without a callback URL)."""
        return self._buzz.send_update(event, data, callback_url=callback_url)

    def request_approval(self, goal: str, reason: str = "") -> bool:
        """Ask whether an action is approved. Deny-by-default semantics.

        Delegates to the injected approver; without one, review-required
        actions stay unapproved exactly like governance defaults.
        """
        if self._approver is None:
            logger.warning("Approval requested for '%s' but no approver wired — denied", goal)
            return False
        try:
            return bool(self._approver(goal, reason))
        except Exception as exc:
            logger.error("Approver raised for '%s': %s — denying", goal, exc)
            return False

    def cancel_mission(self) -> dict[str, Any]:
        """Request cooperative cancellation; checked between task-loop steps."""
        runtime = self._runtime
        if runtime is None:
            return {"cancelled": False, "reason": "no runtime"}
        setattr(runtime, "_cancel_requested", True)
        return {"cancelled": True, "mission_id": getattr(runtime, "_mission_id", None)}

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    def get_status(self, mission_id: str | None = None) -> dict[str, Any]:
        """Return mission status from the tracer (or live runtime fallback)."""
        if self._tracer is not None and mission_id is not None:
            record = self._tracer.get_mission(mission_id)
            if record is not None:
                return {
                    "interface_version": self.INTERFACE_VERSION,
                    "mission_id": record.mission_id,
                    "status": record.status,
                    "step_count": len(record.steps),
                    "goal": record.goal,
                    "created_at": record.created_at,
                    "completed_at": record.completed_at,
                }
        if mission_id is None and self._runtime is not None:
            active = getattr(self._runtime, "_mission_id", None)
            return {"interface_version": self.INTERFACE_VERSION, "mission_id": active, "status": "running" if active else "idle"}
        return {"interface_version": self.INTERFACE_VERSION, "mission_id": mission_id, "status": "unknown"}

    def get_artifacts(self, mission_id: str | None = None) -> list[dict[str, Any]]:
        """Return step artifacts recorded by the tracer for a mission."""
        if self._tracer is None or mission_id is None:
            return []
        record = self._tracer.get_mission(mission_id)
        if record is None:
            return []
        return [
            {"step": s.get("step"), "timestamp": s.get("timestamp"), "result": s.get("result")}
            for s in record.steps
        ]


__all__ = ["BuzzRuntimeAdapter"]
