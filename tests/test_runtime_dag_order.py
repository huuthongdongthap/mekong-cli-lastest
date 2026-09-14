# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for DAG-aware task ordering in ``_run_goal``.

Covers the ``_topological_task_order`` helper and its integration into
``MekongCoreRuntimeImpl._run_goal`` in ``src/core/runtime_adapter.py``:

1. Single-step plans pass through unchanged.
2. Plans with no dependencies preserve input order (fast path).
3. Linear dependency chains execute in the correct order.
4. Diamond DAGs (A→B, A→C, B→D, C→D) emit A first and D last.
5. Cyclic dependencies raise ``RuntimeError`` (fail loud).
6. ``_run_goal`` executes tasks in topological order (integration).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.core.protocols import Plan, PlanStatus, Step
from src.core.runtime_adapter import (
    AgentId,
    Context,
    MekongCoreRuntimeImpl,
    Task,
    _plan_has_dependencies,
    _topological_task_order,
)


def _make_task(step_id: str, deps: list[str] | None = None) -> Task:
    return Task(
        id=f"t-{step_id}",
        step=Step(id=step_id, description=f"step {step_id}", dependencies=deps or []),
        agent=AgentId(name="cli"),
        params={},
    )


# ---------------------------------------------------------------------------
# 1. Single-step plan unchanged
# ---------------------------------------------------------------------------
def test_single_step_plan_unchanged() -> None:
    t0 = _make_task("a")
    result = _topological_task_order([t0])
    assert result == [t0]


# ---------------------------------------------------------------------------
# 2. No dependencies preserves input order
# ---------------------------------------------------------------------------
def test_no_dependencies_preserves_input_order() -> None:
    t0 = _make_task("x")
    t1 = _make_task("y")
    t2 = _make_task("z")
    result = _topological_task_order([t0, t1, t2])
    assert result == [t0, t1, t2]


# ---------------------------------------------------------------------------
# 3. Linear chain A→B→C orders correctly
# ---------------------------------------------------------------------------
def test_linear_chain_orders_correctly() -> None:
    t_a = _make_task("a")
    t_b = _make_task("b", deps=["a"])
    t_c = _make_task("c", deps=["b"])
    result = _topological_task_order([t_a, t_c, t_b])
    assert [t.step.id for t in result] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# 4. Diamond DAG: A→B, A→C, B→D, C→D
# ---------------------------------------------------------------------------
def test_diamond_dag_orders_correctly() -> None:
    t_a = _make_task("a")
    t_b = _make_task("b", deps=["a"])
    t_c = _make_task("c", deps=["a"])
    t_d = _make_task("d", deps=["b", "c"])
    result = _topological_task_order([t_d, t_b, t_a, t_c])
    ids = [t.step.id for t in result]
    assert ids[0] == "a"
    assert ids[-1] == "d"
    assert set(ids[1:3]) == {"b", "c"}


# ---------------------------------------------------------------------------
# 5. Cyclic dependency raises RuntimeError
# ---------------------------------------------------------------------------
def test_cyclic_dependency_raises() -> None:
    t_a = _make_task("a", deps=["b"])
    t_b = _make_task("b", deps=["a"])
    with pytest.raises(RuntimeError, match="circular"):
        _topological_task_order([t_a, t_b])


# ---------------------------------------------------------------------------
# 6. Integration: _run_goal runs tasks in topological order
# ---------------------------------------------------------------------------
class _FakeDispatcher:
    def dispatch(self, task, agent=None):  # noqa: ANN001, ANN202
        return {"status": "noop", "task_id": task.id, "agent": getattr(agent, "name", None)}


def _make_runtime() -> MekongCoreRuntimeImpl:
    return MekongCoreRuntimeImpl(
        dispatcher=_FakeDispatcher(),
        tool_registry=None,
        memory_store=None,
        billing=None,
        telemetry=None,
        capability_bus=None,
        llm_router=None,
        agent_id="cli",
    )


def test_goal_runs_in_topological_order() -> None:
    """_run_goal should execute multi-step plans in dependency order."""
    rt = _make_runtime()
    # Build a diamond plan: a → {b, c} → d
    plan = Plan(
        id="p-1",
        goal="test diamond",
        steps=[
            Step(id="a", description="a"),
            Step(id="b", description="b", dependencies=["a"]),
            Step(id="c", description="c", dependencies=["a"]),
            Step(id="d", description="d", dependencies=["b", "c"]),
        ],
        status=PlanStatus.PENDING,
    )

    recorded: list[str] = []
    original_run_task_loop = rt._run_task_loop

    def recording_run_task_loop(task, criteria):  # noqa: ANN001, ANN202
        recorded.append(task.step.id)
        return original_run_task_loop(task, criteria)

    goal = rt.goal("test diamond", Context(principal="test", session_id="s-dag"))

    with (
        patch.object(rt, "plan", return_value=plan),
        patch.object(
            rt,
            "delegate",
            return_value=[
                _make_task(step_id=s.id, deps=s.dependencies) for s in plan.steps
            ],
        ),
        patch.object(rt, "_run_task_loop", side_effect=recording_run_task_loop),
    ):
        rt._run_goal(goal, start=0.0)

    assert recorded[0] == "a"
    assert recorded[-1] == "d"
    assert set(recorded[1:3]) == {"b", "c"}


# ---------------------------------------------------------------------------
# 7. _plan_has_dependencies fast-path check
# ---------------------------------------------------------------------------
def test_plan_has_dependencies_true_when_steps_have_deps() -> None:
    plan = Plan(
        id="p-2",
        goal="g",
        steps=[Step(id="s1", description="d1", dependencies=["s0"])],
    )
    assert _plan_has_dependencies(plan) is True


def test_plan_has_dependencies_false_when_no_deps() -> None:
    plan = Plan(
        id="p-3",
        goal="g",
        steps=[Step(id="s1", description="d1"), Step(id="s2", description="d2")],
    )
    assert _plan_has_dependencies(plan) is False
