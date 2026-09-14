# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Conformance suite for GoalEngine protocol (P3.1 SC6).

Parametrized over:
1. GoalEngineAdapter with real GoalEngine service (SQLite store)
2. GoalEngineAdapter with stub service (hermetic, zero I/O)

Tests all 3 protocol methods: decompose(), adapt(), commit().
Asserts return types, Plan shape (id, goal, steps[], status),
Step shape (id, description, dependencies[], params).

Acceptance: ≥6 tests, hermetic, runs <5s.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from src.core.adapters.goal_engine_adapter import GoalEngineAdapter, make_goal_engine_adapter
from src.core.protocols import Plan, PlanStatus, Step
from src.mekongcli.core.goal_engine.models import AgentRole, GoalTask, GoalStatus, TaskStatus
from src.mekongcli.core.goal_engine.store import SQLiteGoalStore


# ---------------------------------------------------------------------------
# Stub service for hermetic testing (no DB, no network)
# ---------------------------------------------------------------------------


class StubGoalEngineService:
    """Minimal GoalEngineService stub that returns deterministic task graphs."""

    def __init__(self) -> None:
        self._goal_counter = 0

    def create_goal(self, title: str):
        from src.mekongcli.core.goal_engine.models import Goal

        self._goal_counter += 1
        goal_id = f"stub-goal-{self._goal_counter}"
        return Goal(id=goal_id, title=title)

    def run_goal(self, goal_id: str, **kwargs):

        goal = self.create_goal(f"executed-{goal_id}")
        goal.status = GoalStatus.SATISFIED
        return goal


class StubGoalStore:
    """In-memory store returning a fixed 7-step task graph."""

    def __init__(self) -> None:
        self._tasks: list[GoalTask] = []

    def get_tasks(self, goal_id: str) -> list[GoalTask]:
        """Return deterministic 7-role task graph matching real planner output."""
        if not self._tasks:
            self._tasks = [
                GoalTask(
                    id="stub-task-architect",
                    goal_id=goal_id,
                    title="Define architecture and module boundaries",
                    description=f"Architect the delivery plan for: {goal_id}",
                    role=AgentRole.ARCHITECT,
                    status=TaskStatus.PENDING,
                    depends_on=[],
                    max_attempts=3,
                    command=None,
                ),
                GoalTask(
                    id="stub-task-backend",
                    goal_id=goal_id,
                    title="Implement backend and orchestration contracts",
                    description="Build the service interfaces, persistence, and orchestration behavior.",
                    role=AgentRole.BACKEND,
                    status=TaskStatus.PENDING,
                    depends_on=["stub-task-architect"],
                    max_attempts=3,
                    command=None,
                ),
                GoalTask(
                    id="stub-task-infra",
                    goal_id=goal_id,
                    title="Prepare runtime, infra, and observability hooks",
                    description="Wire local runtime, compose profile, telemetry, and operational defaults.",
                    role=AgentRole.INFRA,
                    status=TaskStatus.PENDING,
                    depends_on=["stub-task-architect"],
                    max_attempts=3,
                    command=None,
                ),
                GoalTask(
                    id="stub-task-qa",
                    goal_id=goal_id,
                    title="Verify behavior with tests and adversarial checks",
                    description="Run the verification profile and record evidence.",
                    role=AgentRole.QA,
                    status=TaskStatus.PENDING,
                    depends_on=["stub-task-backend", "stub-task-infra"],
                    max_attempts=3,
                    command=None,
                ),
                GoalTask(
                    id="stub-task-security",
                    goal_id=goal_id,
                    title="Review safety boundaries and secret exposure risk",
                    description="Check command safety, permissions, and dependency/security gates.",
                    role=AgentRole.SECURITY,
                    status=TaskStatus.PENDING,
                    depends_on=["stub-task-backend", "stub-task-infra"],
                    max_attempts=3,
                    command=None,
                ),
                GoalTask(
                    id="stub-task-docs",
                    goal_id=goal_id,
                    title="Document workflow and operational usage",
                    description="Update user-facing docs, architecture notes, and examples.",
                    role=AgentRole.DOCS,
                    status=TaskStatus.PENDING,
                    depends_on=["stub-task-backend", "stub-task-infra"],
                    max_attempts=3,
                    command=None,
                ),
                GoalTask(
                    id="stub-task-reviewer",
                    goal_id=goal_id,
                    title="Final acceptance and consistency check",
                    description="Check consistency, duplicate systems, and acceptance criteria.",
                    role=AgentRole.REVIEWER,
                    status=TaskStatus.PENDING,
                    depends_on=["stub-task-qa", "stub-task-security", "stub-task-docs"],
                    max_attempts=3,
                    command=None,
                ),
            ]
        return self._tasks


ADAPTER_FACTORIES = [
    pytest.param(
        lambda: GoalEngineAdapter(service=StubGoalEngineService(), store=StubGoalStore()),
        id="stub-service",
    ),
    pytest.param(
        lambda: make_goal_engine_adapter(store=SQLiteGoalStore(), cwd=Path("/tmp/test_goal_engine_conformance")),
        id="real-service",
    ),
]


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
def test_adapter_satisfies_protocol(factory):
    adapter = factory()
    assert hasattr(adapter, "decompose")
    assert hasattr(adapter, "adapt")
    assert hasattr(adapter, "commit")


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
def test_decompose_returns_plan(factory):
    adapter = factory()
    plan = adapter.decompose("analyze revenue")
    assert isinstance(plan, Plan)
    assert isinstance(plan.id, str) and plan.id
    assert isinstance(plan.goal, str) and plan.goal
    assert isinstance(plan.steps, list)
    assert len(plan.steps) == 7  # real and stub both produce 7 steps
    assert plan.status == PlanStatus.PENDING


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
def test_plan_steps_have_unique_ids(factory):
    adapter = factory()
    plan = adapter.decompose("build the roadmap")
    step_ids = [s.id for s in plan.steps]
    assert len(step_ids) == len(set(step_ids)), "step ids must be unique"


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
def test_plan_steps_have_valid_dependencies(factory):
    adapter = factory()
    plan = adapter.decompose("analyze revenue")
    all_step_ids = {s.id for s in plan.steps}
    for step in plan.steps:
        for dep in step.dependencies:
            assert dep in all_step_ids, f"step {step.id} references unknown dependency {dep}"


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
def test_plan_steps_have_no_cycles(factory):
    adapter = factory()
    plan = adapter.decompose("optimize logistics")

    # Simple cycle detection: topological sort must succeed
    visited = set()
    rec_stack = set()

    def dfs(step_id: str) -> bool:
        if step_id in rec_stack:
            return False
        if step_id in visited:
            return True
        visited.add(step_id)
        rec_stack.add(step_id)
        step = next(s for s in plan.steps if s.id == step_id)
        for dep in step.dependencies:
            if not dfs(dep):
                return False
        rec_stack.remove(step_id)
        return True

    for step in plan.steps:
        assert dfs(step.id), f"cycle detected in plan {plan.id}"


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
def test_step_shape(factory):
    adapter = factory()
    plan = adapter.decompose("audit the budget")
    step = plan.steps[0]
    assert isinstance(step, Step)
    assert isinstance(step.id, str) and step.id
    assert isinstance(step.description, str) and step.description
    assert isinstance(step.dependencies, list)
    assert isinstance(step.params, dict)
    # params must contain role for multi-step plans
    assert "role" in step.params
    assert step.params["role"] in [r.value for r in AgentRole]
    assert "title" in step.params
    assert "max_attempts" in step.params


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
def test_adapt_returns_new_plan_with_failure_context(factory):
    adapter = factory()
    original_plan = adapter.decompose("competitive market analysis")

    # Use a simple object that satisfies FailureInfo protocol (has .step, .error, .output, .retries)
    class _Failure:
        def __init__(self, step, error, output, retries):
            self.step = step
            self.error = error
            self.output = output
            self.retries = retries

    failure = _Failure("stub-task-backend", "connection timeout", "partial output", 1)

    new_plan = adapter.adapt(original_plan, failure)
    assert isinstance(new_plan, Plan)
    assert new_plan.id != original_plan.id
    assert "adapted_from" in new_plan.metadata
    assert new_plan.metadata["adapted_from"] == original_plan.id
    assert "failure" in new_plan.metadata
    assert new_plan.metadata["failure"]["step"] == "stub-task-backend"
    assert new_plan.metadata["failure"]["error"] == "connection timeout"
    assert new_plan.metadata["failure"]["retries"] == 1
    assert new_plan.status == PlanStatus.PENDING


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
def test_commit_returns_result(factory):
    adapter = factory()
    plan = adapter.decompose("implement the login flow")
    result = adapter.commit(plan)

    # Result shape: GoalEngineResult dataclass with success, output, error, metadata
    assert hasattr(result, "success")
    assert hasattr(result, "output")
    assert hasattr(result, "error")
    assert hasattr(result, "metadata")
    assert isinstance(result.success, bool)
    assert result.metadata.get("plan_id") == plan.id
    assert "svc_goal_id" in result.metadata


# ---------------------------------------------------------------------------
# Role→agent mapping sanity (verify _ROLE_AGENT_MAP coverage)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
def test_plan_covers_all_seven_roles(factory):
    adapter = factory()
    plan = adapter.decompose("launch summer campaign")
    roles = [step.params["role"] for step in plan.steps]
    expected = {"architect", "backend", "infra", "qa", "security", "docs", "reviewer"}
    assert set(roles) == expected


# ---------------------------------------------------------------------------
# Factory hermeticity
# ---------------------------------------------------------------------------


def test_factory_injects_store_hermetically(tmp_path: Path):
    """make_goal_engine_adapter accepts explicit store for test isolation."""
    store = SQLiteGoalStore(tmp_path / "test_goals.sqlite3")
    adapter = make_goal_engine_adapter(store=store, cwd=tmp_path)
    plan = adapter.decompose("test goal")
    assert isinstance(plan, Plan)
    assert len(plan.steps) == 7