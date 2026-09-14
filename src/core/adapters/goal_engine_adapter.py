# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Conformant adapter: wraps the live GoalEngine service to satisfy the
``protocols.GoalEngine`` Protocol (src/core/protocols.py).

Protocol → live service mapping:
- decompose(goal)          → create_goal + extract planner task graph → Plan
- adapt(plan, failure)     → create_goal with failure context → new Plan
- commit(plan)             → run_goal + map outcome → Result

The live service (src/mekongcli/core/goal_engine/service.py) manages goals,
tasks, and verification internally. This adapter translates between the
protocol surface and the service API — it wraps, never rewrites, the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, cast

from src.core.protocols import FailureInfo, Plan, PlanStatus, Result, Step
from src.mekongcli.core.goal_engine import GoalEngine as GoalEngineService
from src.mekongcli.core.goal_engine.models import GoalStatus, GoalTask
from src.mekongcli.core.goal_engine.store import SQLiteGoalStore


@dataclass
class GoalEngineResult:
    """Concrete Result-shaped result (the Protocol itself is not instantiable)."""

    success: bool
    output: Any = None
    error: str | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class GoalEngineAdapter:
    """Wraps the live GoalEngine service to satisfy protocols.GoalEngine."""

    def __init__(
        self,
        service: GoalEngineService | None = None,
        store: SQLiteGoalStore | None = None,
        cwd: Path | str = ".",
        verification_profile: str = "standard",
    ) -> None:
        self._verification_profile = verification_profile
        if service is None:
            store = store if store is not None else SQLiteGoalStore()
            service = GoalEngineService(store=store, cwd=cwd)
        self._service = service
        # Task graphs are read through the service's own store so the adapter
        # never opens a second database handle.
        resolved_store = store if store is not None else getattr(service, "store", None)
        if resolved_store is None:
            raise ValueError(
                "GoalEngineAdapter requires a store: the injected service exposes "
                "no 'store' attribute and no store was provided"
            )
        self._store = cast(SQLiteGoalStore, resolved_store)

    # --- protocols.GoalEngine interface ---

    def decompose(self, goal: str) -> Plan:
        """Create a goal and return its planner task graph as a core Plan."""
        svc_goal = self._service.create_goal(goal)
        tasks = self._store.get_tasks(svc_goal.id)
        return self._build_plan(svc_goal.id, goal, tasks, PlanStatus.PENDING)

    def adapt(self, plan: Plan, failure: FailureInfo) -> Plan:
        """Re-plan with failure context by creating a new goal.

        The live service has no explicit replan method, so we create a new
        goal whose title carries the failure context and return its fresh
        task graph.
        """
        context = (
            f"Previous attempt failed at step '{failure.step}': {failure.error}. "
            f"Retries so far: {failure.retries}. Last output: {failure.output}"
        )
        new_goal_title = f"Retry: {plan.goal} | Context: {context}"

        svc_goal = self._service.create_goal(new_goal_title)
        tasks = self._store.get_tasks(svc_goal.id)
        new_plan = self._build_plan(svc_goal.id, new_goal_title, tasks, PlanStatus.PENDING)
        new_plan.metadata.update(
            {
                "adapted_from": plan.id,
                "failure": {
                    "step": failure.step,
                    "error": failure.error,
                    "retries": failure.retries,
                },
            }
        )
        return new_plan

    def commit(self, plan: Plan) -> Result:
        """Execute the plan's goal and return a core Result."""
        svc_goal_id = plan.metadata.get("svc_goal_id")
        if not svc_goal_id:
            svc_goal = self._service.create_goal(plan.goal)
            svc_goal_id = svc_goal.id

        try:
            completed_goal = self._service.run_goal(
                svc_goal_id,
                verification_profile=self._verification_profile,
                execute_commands=False,
            )
        except Exception as e:
            return GoalEngineResult(
                success=False,
                output=None,
                error=f"Execution failed: {e}",
                metadata={"plan_id": plan.id, "svc_goal_id": svc_goal_id},
            )

        success = completed_goal.status == GoalStatus.SATISFIED
        tasks = self._store.get_tasks(svc_goal_id)
        task_results = [
            {
                "task_id": t.id,
                "title": t.title,
                "status": t.status.value,
                "summary": t.result_summary,
            }
            for t in tasks
        ]

        return GoalEngineResult(
            success=success,
            output={"tasks": task_results, "goal_status": completed_goal.status.value},
            error=None if success else f"Goal ended with status: {completed_goal.status.value}",
            metadata={
                "plan_id": plan.id,
                "svc_goal_id": svc_goal_id,
            },
        )

    # --- Helpers ---

    def _build_plan(
        self,
        svc_goal_id: str,
        goal: str,
        tasks: List[GoalTask],
        status: PlanStatus,
    ) -> Plan:
        steps = [self._task_to_step(task) for task in tasks]
        return Plan(
            id=svc_goal_id,
            goal=goal,
            steps=steps,
            status=status,
            metadata={"svc_goal_id": svc_goal_id},
        )

    @staticmethod
    def _task_to_step(task: GoalTask) -> Step:
        return Step(
            id=task.id,
            description=task.description,
            dependencies=list(task.depends_on),
            params={
                "role": task.role.value,
                "title": task.title,
                "command": task.command,
                "max_attempts": task.max_attempts,
            },
        )


def make_goal_engine_adapter(
    store: SQLiteGoalStore | None = None,
    cwd: Path | str = ".",
    verification_profile: str = "standard",
) -> GoalEngineAdapter:
    """Factory for creating a GoalEngineAdapter with default service."""
    return GoalEngineAdapter(store=store, cwd=cwd, verification_profile=verification_profile)


__all__ = [
    "GoalEngineAdapter",
    "GoalEngineResult",
    "make_goal_engine_adapter",
]
