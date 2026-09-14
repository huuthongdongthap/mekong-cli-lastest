# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for DAG downstream cancellation and repair strategies in MekongCoreRuntimeImpl."""

from __future__ import annotations

from src.core.protocols import Plan, PlanStatus, Step
from src.core.runtime_adapter import (
    CheckSpec,
    Context,
    Criteria,
    Goal,
    MekongCoreRuntimeImpl,
    RepairAction,
    RepairStrategy,
    Result,
    Task,
)


def _make_step(step_id: str, deps: list[str] | None = None) -> Step:
    return Step(
        id=step_id,
        description=f"Step {step_id}",
        params={"agent": "tester"},
        dependencies=list(deps or []),
    )


class _OkDispatcher:
    def dispatch(self, task, agent=None):
        return {"status": "ok", "task_id": task.id}


def _make_runtime() -> MekongCoreRuntimeImpl:
    rt = MekongCoreRuntimeImpl(
        dispatcher=_OkDispatcher(),
        tool_registry=None,
        memory_store=None,
        billing=None,
        telemetry=None,
        llm_router=None,
        capability_bus=None,
        agent_id="cli",
    )
    return rt


def test_dag_linear_chain_upstream_failure_cancels_downstream() -> None:
    """A -> B -> C. When A fails verification/repair, B and C must be cancelled."""
    rt = _make_runtime()

    executed_steps: list[str] = []

    def mock_execute(task: Task) -> Result:
        executed_steps.append(task.step.id)
        if task.step.id == "A":
            # Upstream failure: exit_code 1
            return Result(task_id=task.id, output="", error="A failed", metadata={})
        return Result(task_id=task.id, output="ok", error=None, metadata={})

    rt.execute = mock_execute  # type: ignore[method-assign]

    # Goal with linear steps A -> B -> C
    steps = [
        _make_step("A", deps=[]),
        _make_step("B", deps=["A"]),
        _make_step("C", deps=["B"]),
    ]
    plan = Plan(id="p1", goal="g1", steps=steps, status=PlanStatus.PENDING)
    rt.plan = lambda g: plan  # type: ignore[method-assign]

    goal = Goal(
        id="g1",
        intent="run linear chain",
        context=Context(principal="test", session_id="s1"),
        criteria=Criteria(checks=[CheckSpec(kind="exit_code", params={"expected": 0})]),
    )

    res = rt._run_goal(goal, start=0.0)

    # A was executed, failed, attempted repairs, then gave up.
    # B and C must NOT have been executed via execute()
    assert "A" in executed_steps
    assert "B" not in executed_steps
    assert "C" not in executed_steps
    assert res.error is not None


def test_dag_diamond_partial_failure_only_cancels_dependent_branch() -> None:
    """Diamond: A -> B, A -> C; (B, C) -> D.
    If B fails, D is cancelled, but C still executes and succeeds.
    """
    rt = _make_runtime()
    executed_steps: list[str] = []

    def mock_execute(task: Task) -> Result:
        step_id = task.step.id
        executed_steps.append(step_id)
        if step_id == "B":
            return Result(task_id=task.id, output="", error="B failed", metadata={})
        return Result(task_id=task.id, output=f"{step_id} ok", error=None, metadata={})

    rt.execute = mock_execute  # type: ignore[method-assign]

    steps = [
        _make_step("A", deps=[]),
        _make_step("B", deps=["A"]),
        _make_step("C", deps=["A"]),
        _make_step("D", deps=["B", "C"]),
    ]
    plan = Plan(id="p-diamond", goal="g1", steps=steps, status=PlanStatus.PENDING)
    rt.plan = lambda g: plan  # type: ignore[method-assign]

    goal = Goal(
        id="g1",
        intent="run diamond",
        context=Context(principal="test", session_id="s1"),
        criteria=Criteria(checks=[CheckSpec(kind="exit_code", params={"expected": 0})]),
    )

    res = rt._run_goal(goal, start=0.0)

    # A, B, and C should have executed; D should be cancelled (depends on B which failed)
    assert "A" in executed_steps
    assert "B" in executed_steps
    assert "C" in executed_steps
    assert "D" not in executed_steps
    assert res.error is not None


def test_repair_escalate_strategy_halts_and_marks_failed() -> None:
    """When repair returns ESCALATE, the task immediately halts retries and fails downstream."""
    rt = _make_runtime()
    call_counts: dict[str, int] = {}

    def mock_execute(task: Task) -> Result:
        call_counts[task.step.id] = call_counts.get(task.step.id, 0) + 1
        return Result(task_id=task.id, output="", error="fail", metadata={})

    rt.execute = mock_execute  # type: ignore[method-assign]

    # Mock repair to return ESCALATE
    rt.repair = lambda v: RepairAction(strategy=RepairStrategy.ESCALATE)  # type: ignore[method-assign]

    steps = [
        _make_step("1", deps=[]),
        _make_step("2", deps=["1"]),
    ]
    plan = Plan(id="p-esc", goal="g1", steps=steps, status=PlanStatus.PENDING)
    rt.plan = lambda g: plan  # type: ignore[method-assign]

    goal = Goal(
        id="g1",
        intent="test escalate",
        context=Context(principal="test", session_id="s1"),
        criteria=Criteria(checks=[CheckSpec(kind="exit_code", params={"expected": 0})]),
    )

    res = rt._run_goal(goal, start=0.0)

    # Step 1 should only have been attempted once because ESCALATE aborts retry loop
    assert call_counts["1"] == 1
    # Step 2 should have been cancelled without executing
    assert "2" not in call_counts
    assert res.error is not None


def test_repair_rollback_strategy_halts_and_marks_failed() -> None:
    """When repair returns ROLLBACK, the task immediately halts and cancels downstream."""
    rt = _make_runtime()
    call_counts: dict[str, int] = {}

    def mock_execute(task: Task) -> Result:
        call_counts[task.step.id] = call_counts.get(task.step.id, 0) + 1
        return Result(task_id=task.id, output="", error="rollback needed", metadata={})

    rt.execute = mock_execute  # type: ignore[method-assign]
    rt.repair = lambda v: RepairAction(strategy=RepairStrategy.ROLLBACK)  # type: ignore[method-assign]

    steps = [
        _make_step("step-init", deps=[]),
        _make_step("step-dependent", deps=["step-init"]),
    ]
    plan = Plan(id="p-rb", goal="g1", steps=steps, status=PlanStatus.PENDING)
    rt.plan = lambda g: plan  # type: ignore[method-assign]

    goal = Goal(
        id="g1",
        intent="test rollback",
        context=Context(principal="test", session_id="s1"),
        criteria=Criteria(checks=[CheckSpec(kind="exit_code", params={"expected": 0})]),
    )

    res = rt._run_goal(goal, start=0.0)

    assert call_counts["step-init"] == 1
    assert "step-dependent" not in call_counts
    assert res.error is not None


def test_repair_retry_success_allows_downstream_to_complete() -> None:
    """A task that fails initially but succeeds on retry allows downstream tasks to run."""
    rt = _make_runtime()
    call_counts: dict[str, int] = {}

    def mock_execute(task: Task) -> Result:
        call_counts[task.step.id] = call_counts.get(task.step.id, 0) + 1
        if task.step.id == "upstream":
            if call_counts["upstream"] == 1:
                return Result(task_id=task.id, output="fail first time", error="transient error", metadata={})
            return Result(task_id=task.id, output="success second time", error=None, metadata={})
        return Result(task_id=task.id, output="downstream success", error=None, metadata={})

    rt.execute = mock_execute  # type: ignore[method-assign]

    steps = [
        _make_step("upstream", deps=[]),
        _make_step("downstream", deps=["upstream"]),
    ]
    plan = Plan(id="p-retry", goal="g1", steps=steps, status=PlanStatus.PENDING)
    rt.plan = lambda g: plan  # type: ignore[method-assign]

    goal = Goal(
        id="g1",
        intent="test retry recovery",
        context=Context(principal="test", session_id="s1"),
        criteria=Criteria(checks=[CheckSpec(kind="exit_code", params={"expected": 0})]),
    )

    res = rt._run_goal(goal, start=0.0)

    assert call_counts["upstream"] == 2
    assert call_counts["downstream"] == 1
    assert res.error is None
    assert "downstream success" in str(res.output)

