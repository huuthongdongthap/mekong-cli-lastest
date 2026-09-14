# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Mission-level trace correlation for autonomous runs.

Provides end-to-end mission tracing that ties together individual steps,
telemetry events, and outcomes under a single correlation ID.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class MissionRecord:
    """End-to-end mission trace record."""

    mission_id: str
    goal: str
    status: str = "running"
    steps: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MissionTracer:
    """Mission-level trace correlation for autonomous runs.

    Each mission gets a unique correlation ID. Steps are logged with
    timestamps and results. The final outcome is recorded when the
    mission completes.
    """

    def __init__(self) -> None:
        self._missions: dict[str, MissionRecord] = {}
        # Lane E8: ordered stage labels (goal→commit) for the agent lifecycle.
        # Steps (task.id keyed) remain the primary trace; stages are the
        # high-level lifecycle overlay consumed by ``mekong cook``'s summary.
        self.stages: list[dict[str, Any]] = []

    def record_stage(self, stage: str, metadata: dict[str, Any] | None = None) -> None:
        """Append a high-level lifecycle stage (e.g. ``"goal"``, ``"commit"``).

        Backward compatible — existing callers that only use ``log_step``
        are unaffected; ``stages`` starts empty and is only populated when
        the canonical runtime (``runtime_adapter._run_goal``) drives the
        lifecycle through this tracer.
        """
        self.stages.append(
            {
                "stage": stage,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata or {},
            }
        )

    def start_mission(
        self, goal: str, metadata: Optional[dict[str, Any]] = None
    ) -> str:
        """Start a new mission trace. Returns mission_id."""
        mission_id = f"mission_{uuid.uuid4().hex[:8]}"
        record = MissionRecord(
            mission_id=mission_id,
            goal=goal,
            metadata=metadata or {},
        )
        self._missions[mission_id] = record
        logger.info("Mission started: %s goal=%s", mission_id, goal)
        return mission_id

    def log_step(
        self, mission_id: str, step: str, result: dict[str, Any]
    ) -> None:
        """Log a step in a mission."""
        if mission_id not in self._missions:
            logger.warning("log_step for unknown mission %s", mission_id)
            return
        self._missions[mission_id].steps.append(
            {
                "step": step,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "result": result,
            }
        )

    def end_mission(
        self, mission_id: str, outcome: str
    ) -> Optional[dict[str, Any]]:
        """End a mission trace. Returns summary dict or None if mission not found."""
        if mission_id not in self._missions:
            logger.warning("end_mission for unknown mission %s", mission_id)
            return None
        record = self._missions[mission_id]
        record.status = outcome
        record.completed_at = datetime.now(timezone.utc).isoformat()
        return {
            "mission_id": record.mission_id,
            "goal": record.goal,
            "status": record.status,
            "step_count": len(record.steps),
            "created_at": record.created_at,
            "completed_at": record.completed_at,
        }

    def get_mission(self, mission_id: str) -> Optional[MissionRecord]:
        """Get a mission record by ID."""
        return self._missions.get(mission_id)

    def list_missions(self) -> list[dict[str, Any]]:
        """List all missions."""
        return [
            {
                "mission_id": m.mission_id,
                "goal": m.goal,
                "status": m.status,
                "step_count": len(m.steps),
                "created_at": m.created_at,
            }
            for m in self._missions.values()
        ]
