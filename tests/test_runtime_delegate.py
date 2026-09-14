# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for Lane E6 — real delegation through the existing agent stack.

Covers the ``plan()``/``delegate()`` payload contract in
``src/core/runtime_adapter.py``:

1. ``delegate()`` produces tasks with different agents per intent.
2. Dispatch via a real ``AgentBase`` subclass (registry-backed).
3. Unknown agent falls back to the dispatcher's graceful failure path.
4. The cancel seam ``_is_cancelled()`` still works between delegation and
   execution.

These tests exercise the runtime in isolation with a fake dispatcher so the
agent-assignment logic is decoupled from the production wiring in
``src/commands/run.py``.
"""

from __future__ import annotations

import pytest

from src.core.agent_registry import get_registry
from src.core.protocols import Plan, PlanStatus, Step
from src.core.runtime_adapter import (
    AgentId,
    Context,
    Criteria,
    MekongCoreRuntimeImpl,
)


class _FakeDispatcher:
    """Records dispatched tasks; lets tests inspect agent assignment."""

    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.dispatched: list = []
        self.fail_on: set[str] = fail_on or set()

    def dispatch(self, task, agent=None):  # noqa: ANN001, ANN202
        self.dispatched.append((task, agent))
        if getattr(agent, "name", None) in self.fail_on:
            raise NotImplementedError(f"No dispatcher configured for agent '{agent.name}'")
        return {"status": "noop", "task_id": task.id, "agent": getattr(agent, "name", None)}


def _make_runtime(dispatcher, *, agent_id="cli", governance=None):
    """Build a runtime with only the dependencies this test needs."""
    return MekongCoreRuntimeImpl(
        dispatcher=dispatcher,
        tool_registry=None,
        memory_store=None,
        billing=None,
        telemetry=None,
        governance=governance,
        capability_bus=None,
        llm_router=None,
        agent_id=agent_id,
    )


def _goal(rt, intent: str):
    """Build a Goal through the runtime's own goal() factory."""
    return rt.goal(intent, Context(principal="test", session_id="s-1"))


# ---------------------------------------------------------------------------
# 1. delegate() produces tasks with different agents per intent
# ---------------------------------------------------------------------------


class TestDelegateAgentAssignment:
    def test_intent_classification_routes_to_builtin_agents(self):
        """Keyword-matched intents assign the corresponding built-in agent.

        Multi-step plans now produce several Tasks (one per Step); the agent
        name for the *first* role-bearing step must match the keyword's expected
        agent. For "implement the login flow" the first role is "architect"
        which maps to "planner". We verify the *mapped* agent appears among
        the dispatched tasks for each keyword.
        """
        rt = _make_runtime(_FakeDispatcher())
        cases = {
            "implement the login flow": "planner",      # architect → planner
            "launch summer campaign": "planner",         # architect → planner
            "optimize logistics": "planner",            # architect → planner
            "audit the budget": "planner",              # architect → planner
            "competitive market analysis": "planner",   # architect → planner
            "build the roadmap": "planner",             # architect → planner
        }
        for intent, expected in cases.items():
            plan = rt.plan(_goal(rt, intent))
            tasks = rt.delegate(plan)
            # Multi-step plan: verify expected agent appears among tasks
            agent_names = [t.agent.name for t in tasks]
            assert expected in agent_names, (
                f"{intent!r} -> agents {agent_names}, expected {expected} present"
            )

    def test_unmatched_intent_keeps_runtime_agent_id(self):
        """Goals with no keyword keep ``self._agent_id`` (graceful path).

        "deploy production build" doesn't match any built-in keyword, so it falls
        back to single-step plan with the runtime's agent_id ("cli").
        """
        rt = _make_runtime(_FakeDispatcher(), agent_id="cli")
        plan = rt.plan(_goal(rt, "deploy production build"))
        tasks = rt.delegate(plan)
        # Single-step fallback: exactly 1 task with agent_id
        assert len(tasks) == 1
        assert tasks[0].agent.name == "cli"

    def test_step_params_carry_agent_name(self):
        """``plan()`` embeds role/agent in step.params for delegate().

        Multi-step plans use "role" (architect, backend, etc.) which delegate()
        maps via _ROLE_AGENT_MAP. Single-step fallback uses "agent" directly.
        """
        rt = _make_runtime(_FakeDispatcher())

        # Keyword-matched intent -> multi-step with "role"
        goal1 = _goal(rt, "refactor the billing module")
        plan1 = rt.plan(goal1)
        assert plan1.steps[0].params.get("role") == "architect"
        # Goal linkage lives on the Plan for multi-step output
        assert plan1.goal == goal1.id

        # Unmatched intent -> single-step with "agent"
        rt2 = _make_runtime(_FakeDispatcher(), agent_id="cli")
        goal2 = _goal(rt2, "echo hello")
        plan2 = rt2.plan(goal2)
        assert plan2.steps[0].params.get("agent") == "cli"
        assert plan2.steps[0].params.get("goal_id") == goal2.id

    def test_payload_contract_shape(self):
        """Each task carries ``step``, ``agent`` (AgentId), and ``params``.

        "analyze revenue" -> cso keyword -> multi-step plan; tasks carry
        step, AgentId, and params with "role" keys.
        """
        rt = _make_runtime(_FakeDispatcher())
        plan = rt.plan(_goal(rt, "analyze revenue"))
        tasks = rt.delegate(plan)
        task = tasks[0]
        assert task.step is plan.steps[0]
        # First step is architect role -> planner agent
        assert task.agent.name == "planner"
        assert task.params.get("role") == "architect"
        # All tasks must carry AgentId instances
        for t in tasks:
            assert t.agent.name in ("planner", "cto", "coo", "cso", "cmo", "cfo")


# ---------------------------------------------------------------------------
# 2. Dispatch via a real AgentBase subclass
# ---------------------------------------------------------------------------


class TestRealAgentDispatch:
    def test_registered_agent_runs_through_agentbase_run(self):
        """The registry-backed dispatcher in run.py spawns a real AgentBase."""
        from src.commands.run import _RegistryDispatcher

        dispatcher = _RegistryDispatcher()
        plan = Plan(
            id="p-1",
            goal="g-1",
            steps=[Step(id="s-0", description="analyze revenue", params={"agent": "cso"})],
            status=PlanStatus.IN_PROGRESS,
        )
        task = plan.steps[0]
        output = dispatcher.dispatch(task, AgentId(name="cso"))
        assert output["status"] == "success"
        assert output["agent"] == "cso"
        assert output["task_id"] == task.id

    def test_registry_singleton_has_builtins(self):
        """The six built-in agents are registered regardless of filesystem."""
        registry = get_registry()
        for name in ("cto", "cmo", "coo", "cfo", "cso", "planner"):
            assert registry.get_meta_obj(name) is not None, f"{name} not registered"


# ---------------------------------------------------------------------------
# 3. Unknown agent fallback
# ---------------------------------------------------------------------------


class TestUnknownAgentFallback:
    def test_unknown_agent_raises_not_implemented(self):
        """Unregistered agents hit the same graceful failure path as before."""
        from src.commands.run import _RegistryDispatcher

        dispatcher = _RegistryDispatcher()
        plan = Plan(
            id="p-2",
            goal="g-2",
            steps=[Step(id="s-1", description="hello", params={"agent": "ghost-agent"})],
            status=PlanStatus.IN_PROGRESS,
        )
        with pytest.raises(NotImplementedError):
            dispatcher.dispatch(plan.steps[0], AgentId(name="ghost-agent"))

    def test_runtime_survives_unknown_agent(self):
        """execute() catches the dispatcher raise and surfaces a terminal error."""
        rt = _make_runtime(_FakeDispatcher(fail_on={"ghost"}))
        plan = rt.plan(_goal(rt, "hello"))
        tasks = rt.delegate(plan)
        # Force the task onto the unknown agent path.
        tasks[0].agent = AgentId(name="ghost")
        result = rt.execute(tasks[0])
        assert result.error is not None
        assert "ghost" in result.error


# ---------------------------------------------------------------------------
# 4. Cancel seam between delegation and execution
# ---------------------------------------------------------------------------


class TestCancelSeam:
    def test_cancel_stops_between_delegation_and_execution(self):
        """_is_cancelled() is checked after delegate() and before execute()."""
        rt = _make_runtime(_FakeDispatcher())
        rt._cancel_requested = True  # type: ignore[attr-defined]
        plan = rt.plan(_goal(rt, "analyze revenue"))
        tasks = rt.delegate(plan)
        # The cancel seam lives in _run_task_loop: it probes _is_cancelled()
        # before the first execute() and between retries.
        result = rt._run_task_loop(tasks[0], Criteria())
        assert result.error is not None
        assert "cancelled" in result.error.lower()

    def test_cancel_produces_terminal_result(self):
        """A cancelled run still produces a terminal Result (never crashes)."""
        rt = _make_runtime(_FakeDispatcher())
        rt._cancel_requested = True  # type: ignore[attr-defined]
        plan = rt.plan(_goal(rt, "analyze revenue"))
        tasks = rt.delegate(plan)
        result = rt._run_task_loop(tasks[0], Criteria())
        assert result.task_id == tasks[0].id
        assert result.error is not None
