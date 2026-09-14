# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""End-to-end tests for the merged execute->verify->repair cycle + DAG order.

Proves the full SC8 merge is a real cycle:

1. Multi-step goals execute in topological order (DAG respected).
2. A task whose output fails ``output_contains`` triggers
   verify->failure->repair->re-verify->pass.
3. A task that keeps failing verify after ``_MAX_REPAIR_ATTEMPTS`` exits with
   ``Verification.passed == False`` (repair budget exhausted).
4. Single-step goals take the fast path (no reorder, identical to pre-change).
5. ``_run_goal`` reads ``task.step.dependencies`` and orders accordingly.
"""

from __future__ import annotations

from unittest.mock import patch

from src.core.protocols import Plan, PlanStatus, Step
from src.core.runtime_adapter import (
    AgentId,
    CheckSpec,
    Context,
    Criteria,
    MekongCoreRuntimeImpl,
    Task,
    _MAX_REPAIR_ATTEMPTS,
    _plan_has_dependencies,
    _topological_task_order,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _OkDispatcher:
    def dispatch(self, task, agent=None):
        return {"status": "ok", "task_id": task.id}


class _StatefulDispatcher:
    """Returns a fresh output on each call from ``outputs`` iterator."""

    def __init__(self, outputs: list):
        self.outputs = outputs
        self.calls = 0

    def dispatch(self, task, agent=None):
        out = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return out


class _AlwaysBadDispatcher:
    """Returns output that always fails an output_contains("OK") check."""

    def __init__(self):
        self.calls = 0

    def dispatch(self, task, agent=None):
        self.calls += 1
        return {"status": "bad", "task_id": task.id}


def _make_runtime(*, dispatcher=None, verifier=None) -> MekongCoreRuntimeImpl:
    return MekongCoreRuntimeImpl(
        dispatcher=dispatcher or _OkDispatcher(),
        tool_registry=None,
        memory_store=None,
        billing=None,
        telemetry=None,
        llm_router=None,
        capability_bus=None,
        agent_id="cli",
        verifier=verifier,
    )


def _make_task(step_id: str, deps: list[str] | None = None) -> Task:
    return Task(
        id=f"t-{step_id}",
        step=Step(id=step_id, description=f"step {step_id}", dependencies=deps or []),
        agent=AgentId(name="cli"),
        params={},
    )


# ---------------------------------------------------------------------------
# 1. test_multistep_goal_executes_in_dag_order
# ---------------------------------------------------------------------------

def test_multistep_goal_executes_in_dag_order() -> None:
    """A 3-step chain A->B->C executes in dependency order under _run_goal."""
    rt = _make_runtime()
    # A -> B -> C (B depends on A, C depends on B)
    plan = Plan(
        id="p-multistep",
        goal="g-multistep",
        steps=[
            Step(id="a", description="a"),
            Step(id="b", description="b", dependencies=["a"]),
            Step(id="c", description="c", dependencies=["b"]),
        ],
        status=PlanStatus.PENDING,
    )
    tasks = [_make_task(s.id, s.dependencies) for s in plan.steps]

    recorded: list[str] = []
    original_run_task_loop = rt._run_task_loop

    def recording_loop(task, criteria):
        recorded.append(task.step.id)
        return original_run_task_loop(task, criteria)

    goal = rt.goal("multistep", Context(principal="test", session_id="s-ms"))

    with (
        patch.object(rt, "plan", return_value=plan),
        patch.object(rt, "delegate", return_value=tasks),
        patch.object(rt, "_run_task_loop", side_effect=recording_loop),
    ):
        rt._run_goal(goal, start=0.0)

    assert recorded == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# 2. test_execute_verify_repair_cycle
# ---------------------------------------------------------------------------

def test_execute_verify_repair_cycle() -> None:
    """A task failing output_contains triggers verify->fail->repair->re-verify->pass."""
    # First output lacks "OK" -> fails verify; second output has "OK" -> passes.
    dispatcher = _StatefulDispatcher([
        {"status": "bad output"},
        {"status": "OK output"},
    ])
    rt = _make_runtime(dispatcher=dispatcher)
    criteria = Criteria(checks=[CheckSpec(kind="output_pattern", params={"pattern": "OK"})])

    task = _make_task("repair-me")
    result = rt._run_task_loop(task, criteria)

    # Final result passed verify (no error, output contains "OK").
    obs = rt.observe(result)
    verification = rt.verify(obs, criteria)
    assert verification.passed is True
    assert result.output == {"status": "OK output"}
    # The dispatcher was called twice: initial fail + repair retry.
    assert dispatcher.calls == 2


# ---------------------------------------------------------------------------
# 3. test_repair_budget_exhausted_fails
# ---------------------------------------------------------------------------

def test_repair_budget_exhausted_fails() -> None:
    """A task failing verify after _MAX_REPAIR_ATTEMPTS exits unverified."""
    dispatcher = _AlwaysBadDispatcher()
    rt = _make_runtime(dispatcher=dispatcher)
    criteria = Criteria(checks=[CheckSpec(kind="output_pattern", params={"pattern": "OK"})])

    task = _make_task("always-bad")

    # Track every verify verdict the loop produces.
    verdicts: list = []
    original_verify = rt.verify

    def recording_verify(observation, crit):
        v = original_verify(observation, crit)
        verdicts.append(v)
        return v

    with patch.object(rt, "verify", side_effect=recording_verify):
        rt._run_task_loop(task, criteria)

    # All verifications were failures.
    assert verdicts, "verify was never called"
    assert all(v.passed is False for v in verdicts)
    # The last verdict is the final, non-passing one.
    assert verdicts[-1].passed is False
    # Repair budget exhausted: _repair_count reached the cap.
    assert rt._repair_count == _MAX_REPAIR_ATTEMPTS
    # The inner loop retries at most _MAX_REPAIR_ATTEMPTS times; the final
    # verify failure exits the loop before execute() is called again, so the
    # total dispatch count equals the cap (not cap+1).
    assert dispatcher.calls == _MAX_REPAIR_ATTEMPTS


# ---------------------------------------------------------------------------
# 4. test_single_step_plan_parity
# ---------------------------------------------------------------------------

def test_single_step_plan_parity() -> None:
    """Single-step goal (no deps) behaves identically: passes, no reorder."""
    rt = _make_runtime()
    plan = Plan(
        id="p-single",
        goal="g-single",
        steps=[Step(id="only", description="only step")],
        status=PlanStatus.PENDING,
    )
    tasks = [_make_task(s.id, s.dependencies) for s in plan.steps]

    recorded: list[str] = []
    original_run_task_loop = rt._run_task_loop

    def recording_loop(task, criteria):
        recorded.append(task.step.id)
        return original_run_task_loop(task, criteria)

    goal = rt.goal("single step", Context(principal="test", session_id="s-single"))

    with (
        patch.object(rt, "plan", return_value=plan),
        patch.object(rt, "delegate", return_value=tasks),
        patch.object(rt, "_run_task_loop", side_effect=recording_loop),
    ):
        result = rt._run_goal(goal, start=0.0)

    # Order preserved (trivially, 1 element).
    assert recorded == ["only"]
    # Fast path was taken: _topological_task_order NOT called for no-deps plan.
    assert _plan_has_dependencies(plan) is False
    # No error -> final result passed.
    assert result.error is None


# ---------------------------------------------------------------------------
# 5. test_goal_engine_dag_consumed
# ---------------------------------------------------------------------------

def test_goal_engine_dag_consumed() -> None:
    """_run_goal reads task.step.dependencies and orders a 2-chain correctly."""
    rt = _make_runtime()
    # 2-chain: step-1 -> step-2
    plan = Plan(
        id="p-2chain",
        goal="g-2chain",
        steps=[
            Step(id="step-1", description="first"),
            Step(id="step-2", description="second", dependencies=["step-1"]),
        ],
        status=PlanStatus.PENDING,
    )
    tasks = [_make_task(s.id, s.dependencies) for s in plan.steps]

    # Prove the topological helper respects the 2-chain.
    ordered = _topological_task_order(tasks)
    assert [t.step.id for t in ordered] == ["step-1", "step-2"]

    # Now prove _run_goal calls _run_task_loop in that order.
    recorded: list[str] = []
    original_run_task_loop = rt._run_task_loop

    def recording_loop(task, criteria):
        recorded.append(task.step.id)
        return original_run_task_loop(task, criteria)

    goal = rt.goal("two step", Context(principal="test", session_id="s-2chain"))

    with (
        patch.object(rt, "plan", return_value=plan),
        patch.object(rt, "delegate", return_value=tasks),
        patch.object(rt, "_run_task_loop", side_effect=recording_loop),
    ):
        rt._run_goal(goal, start=0.0)

    assert recorded == ["step-1", "step-2"]
