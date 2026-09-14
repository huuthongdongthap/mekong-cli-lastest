"""Lane E9 — Agent Policy Enforcement at Capability Execution.

Tests the 5 policy gates from AgentMeta enforced in MekongCoreRuntimeImpl.execute()
before any dispatch happens:
1. risk_level — effective_risk = max(agent.risk_level, capability.risk_level); fail-closed
2. max_budget — cost guard before execute; per-mission spend tracking
3. max_iterations — cap iterations per task
4. approval_policy — route through governance.request_approval() for required risk classes
5. allowed_tools — reject capabilities not in agent's allowed list
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from src.core.agent_base import AgentBase
from src.core.agent_registry import AgentRegistry
from src.core.capability import Capability, CapabilitySource, InMemoryCapabilityBus
from src.core.governance import Governance
from src.core.runtime_adapter import (
    AgentId,
    MekongCoreRuntimeImpl,
    Step,
    Task,
)


class _IsolatedTestMixin:
    """Provides a Governance instance with a unique, cleaned-up audit path."""

    def _make_gov(self) -> Governance:
        self._tmpdir = tempfile.mkdtemp(prefix="policy_test_")
        self.addCleanup(shutil.rmtree, self._tmpdir, ignore_errors=True)
        return Governance(audit_path=os.path.join(self._tmpdir, "audit.yaml"))

    def _make_bus(self) -> InMemoryCapabilityBus:
        bus = InMemoryCapabilityBus()
        # Register test capabilities with various risk levels
        caps = [
            Capability(id="tool:read", name="Read File", description="Read a file", risk_level="LOW", source=CapabilitySource.BUILTIN, cost=0.1),
            Capability(id="tool:write", name="Write File", description="Write a file", risk_level="MEDIUM", source=CapabilitySource.BUILTIN, cost=0.5),
            Capability(id="tool:deploy", name="Deploy", description="Deploy to production", risk_level="HIGH", source=CapabilitySource.CLI, cost=1.0),
            Capability(id="tool:destroy", name="Destroy", description="Destroy infrastructure", risk_level="CRITICAL", source=CapabilitySource.CUSTOM, cost=5.0),
            Capability(id="tool:analyze", name="Analyze", description="Analyze data", risk_level="LOW", source=CapabilitySource.API, cost=0.2),
        ]
        for cap in caps:
            bus.register(cap)
        return bus

    def _make_runtime(self, capability_bus=None, governance=None, agent_registry=None, agent_id="default", max_cost_usd=None, dispatcher=None):
        """Build a runtime with only the dependencies this test needs."""

        class FakeDispatcher:
            def __init__(self, fail_on=None):
                self.fail_on = fail_on or set()
                self.calls = []

            def dispatch(self, task, agent):
                self.calls.append(task.id)
                if getattr(agent, "name", None) in self.fail_on:
                    raise NotImplementedError(f"No dispatcher configured for agent '{agent.name}'")
                return {"status": "dispatched", "task_id": task.id, "agent": getattr(agent, "name", None)}

        class FakeToolRegistry:
            def execute(self, tool, params):
                return {"ok": True, "tool": tool}

        runtime = MekongCoreRuntimeImpl(
            dispatcher=dispatcher or FakeDispatcher(),
            tool_registry=FakeToolRegistry(),
            capability_bus=capability_bus,
            governance=governance,
            agent_id=agent_id,
            max_cost_usd=max_cost_usd,
            agent_registry=agent_registry,
        )
        return runtime

    def _make_task(self, capability_id, description, agent_name="default", tool=None):
        """Create a Task with the given capability and agent.

        Note: description should be benign (avoid FORBIDDEN_PATTERNS like 'destroy',
        and REVIEW_PATTERNS like 'deploy prod') so goal-based Gate 2 doesn't block
        before we test the AgentMeta policy gates.
        """
        return Task(
            id="task-1",
            step=Step(id="step-0", description=description, params={}),
            agent=AgentId(name=agent_name),
            params={"capability_id": capability_id, "description": description, "tool": tool},
        )

    def _register_noop_agent(self, name, **meta_kwargs):
        """Register a minimal AgentBase subclass under ``name`` with given meta fields."""

        class NoopAgent(AgentBase):
            def plan(self, input_data: str):
                return []

            def execute(self, task):
                pass

        self.registry.register(name, NoopAgent, **meta_kwargs)


class TestEffectiveRiskLevelGate(_IsolatedTestMixin, unittest.TestCase):
    """Gate 1: effective_risk = max(agent.risk_level, capability.risk_level); fail-closed."""

    def setUp(self):
        self.gov = self._make_gov()
        self.bus = self._make_bus()
        self.registry = AgentRegistry()
        self._register_noop_agent("high_agent", risk_level="HIGH", approval_policy="AUTO")

    def test_agent_low_risk_capability_low_effective_low_allowed(self):
        """Agent LOW + Capability LOW -> effective LOW -> ALLOW."""
        self._register_noop_agent("default", risk_level="LOW", approval_policy="AUTO")
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="default")
        task = self._make_task("tool:read", "read file", agent_name="default")
        result = runtime.execute(task)
        self.assertIsNone(result.error, f"Expected no error, got: {result.error}")

    def test_agent_high_risk_capability_low_effective_high_requires_approval(self):
        """Agent HIGH + Capability LOW -> effective HIGH -> REVIEW_REQUIRED."""
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="high_agent")
        task = self._make_task("tool:read", "read file", agent_name="high_agent")
        result = runtime.execute(task)
        self.assertIsNotNone(result.error)
        self.assertIn("approval", result.error.lower())
        self.assertTrue(result.metadata.get("gate_blocked"))

    def test_agent_medium_risk_capability_high_effective_high_requires_approval(self):
        """Agent MEDIUM + Capability HIGH -> effective HIGH -> REVIEW_REQUIRED."""
        self._register_noop_agent("medium_agent", risk_level="MEDIUM", approval_policy="AUTO")
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="medium_agent")
        task = self._make_task("tool:deploy", "run release pipeline", agent_name="medium_agent")
        result = runtime.execute(task)
        self.assertIsNotNone(result.error)
        self.assertIn("approval", result.error.lower())

    def test_agent_critical_risk_capability_any_effective_critical_denied(self):
        """Agent CRITICAL + any capability -> effective CRITICAL -> FORBIDDEN."""
        self._register_noop_agent("critical_agent", risk_level="CRITICAL", approval_policy="MANUAL")
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="critical_agent")
        task = self._make_task("tool:read", "read file", agent_name="critical_agent")
        result = runtime.execute(task)
        self.assertIsNotNone(result.error)
        self.assertIn("forbidden", result.error.lower())

    def test_unknown_risk_level_fail_closed(self):
        """Unknown risk level on capability -> fail-closed (FORBIDDEN)."""
        bad_cap = Capability(id="tool:bad", name="Bad", description="Bad", risk_level="INVALID", source=CapabilitySource.CUSTOM)
        self.bus.register(bad_cap)
        self._register_noop_agent("default", risk_level="LOW", approval_policy="AUTO")
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="default")
        task = self._make_task("tool:bad", "bad capability", agent_name="default")
        result = runtime.execute(task)
        self.assertIsNotNone(result.error)
        self.assertIn("forbidden", result.error.lower())

    def test_auto_approve_bypasses_effective_high(self):
        """GOVERNANCE_AUTO_APPROVE=true allows effective HIGH."""
        with patch.dict(os.environ, {"GOVERNANCE_AUTO_APPROVE": "true"}):
            runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="high_agent")
            task = self._make_task("tool:read", "read file", agent_name="high_agent")
            result = runtime.execute(task)
            self.assertIsNone(result.error, f"Expected no error with auto-approve, got: {result.error}")


class TestMaxBudgetGate(_IsolatedTestMixin, unittest.TestCase):
    """Gate 2: max_budget — cost guard before execute; track per-mission spend."""

    def setUp(self):
        self.gov = self._make_gov()
        self.bus = self._make_bus()
        self.registry = AgentRegistry()
        self._register_noop_agent("budget_agent", risk_level="LOW", max_budget=2.0, approval_policy="AUTO")

    def test_within_budget_allows(self):
        """Capability cost within agent's max_budget -> ALLOW."""
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="budget_agent", max_cost_usd=10.0)
        task = self._make_task("tool:read", "read file", agent_name="budget_agent")
        result = runtime.execute(task)
        self.assertIsNone(result.error, f"Expected no error, got: {result.error}")

    def test_exceeds_budget_denied(self):
        """Cumulative per-mission spend exceeding max_budget -> DENY."""
        self._register_noop_agent("tight_agent", risk_level="LOW", max_budget=0.75, approval_policy="AUTO")
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="tight_agent", max_cost_usd=10.0)
        # tool:write costs $0.5 and is MEDIUM -> SAFE, so the first call succeeds
        # and records $0.5 of spend. The second call projects $1.0 > $0.75.
        task = self._make_task("tool:write", "write file", agent_name="tight_agent")
        result1 = runtime.execute(task)
        self.assertIsNone(result1.error, f"First call should pass, got: {result1.error}")
        result2 = runtime.execute(task)
        self.assertIsNotNone(result2.error)
        self.assertIn("budget", result2.error.lower())
        self.assertTrue(result2.metadata.get("gate_blocked"))

    def test_no_budget_set_no_limit(self):
        """Agent with max_budget=None has no budget limit."""
        self._register_noop_agent("nobudget_agent", risk_level="LOW", max_budget=None, approval_policy="AUTO")
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="nobudget_agent", max_cost_usd=10.0)
        task = self._make_task("tool:write", "write file", agent_name="nobudget_agent")
        for _ in range(5):
            result = runtime.execute(task)
            self.assertIsNone(result.error, f"Expected no error with no budget limit, got: {result.error}")

    def test_budget_reset_per_mission(self):
        """Spend tracking resets on start_mission: blocked call succeeds after reset."""
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="budget_agent", max_cost_usd=10.0)
        # tool:write costs $0.5; budget is $2.0 -> 4 calls OK, 5th blocked.
        task = self._make_task("tool:write", "write file", agent_name="budget_agent")
        for _ in range(4):
            result = runtime.execute(task)
            self.assertIsNone(result.error, f"Expected within-budget call to pass, got: {result.error}")
        blocked = runtime.execute(task)
        self.assertIsNotNone(blocked.error)
        self.assertIn("budget", blocked.error.lower())
        # New mission resets per-agent spend; the same call now passes.
        runtime.start_mission("new mission")
        after_reset = runtime.execute(task)
        self.assertIsNone(after_reset.error, f"Expected pass after mission reset, got: {after_reset.error}")


class TestMaxIterationsGate(_IsolatedTestMixin, unittest.TestCase):
    """Gate 3: max_iterations — cap iterations per task."""

    def setUp(self):
        self.gov = self._make_gov()
        self.bus = self._make_bus()
        self.registry = AgentRegistry()
        self._register_noop_agent("iter_agent", risk_level="LOW", max_iterations=2, approval_policy="AUTO")

    def test_within_iterations_allows(self):
        """Task within max_iterations -> ALLOW."""
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="iter_agent")
        task = self._make_task("tool:read", "read file", agent_name="iter_agent")
        result = runtime.execute(task)
        self.assertIsNone(result.error, f"Expected no error, got: {result.error}")

    def test_exceeds_iterations_denied(self):
        """Iteration count at/over max_iterations -> DENY."""
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="iter_agent")
        # Simulate prior repair iterations (repair() increments this counter).
        runtime._repair_count = 2
        task = self._make_task("tool:read", "read file", agent_name="iter_agent")
        result = runtime.execute(task)
        self.assertIsNotNone(result.error)
        self.assertIn("iteration", result.error.lower())
        self.assertTrue(result.metadata.get("gate_blocked"))

    def test_no_iterations_limit_no_cap(self):
        """Agent with max_iterations=None has no iteration cap."""
        self._register_noop_agent("noiter_agent", risk_level="LOW", max_iterations=None, approval_policy="AUTO")
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="noiter_agent")
        runtime._repair_count = 2
        task = self._make_task("tool:read", "read file", agent_name="noiter_agent")
        result = runtime.execute(task)
        self.assertIsNone(result.error, f"Expected no cap without max_iterations, got: {result.error}")


class TestApprovalPolicyGate(_IsolatedTestMixin, unittest.TestCase):
    """Gate 4: approval_policy — route through governance.request_approval()."""

    def setUp(self):
        self.gov = self._make_gov()
        self.bus = self._make_bus()
        self.registry = AgentRegistry()

    def test_approval_policy_auto_allows(self):
        """approval_policy=AUTO + SAFE risk class -> no approval needed."""
        self._register_noop_agent("auto_agent", risk_level="LOW", approval_policy="AUTO")
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="auto_agent")
        task = self._make_task("tool:read", "read file", agent_name="auto_agent")
        result = runtime.execute(task)
        self.assertIsNone(result.error, f"Expected no error, got: {result.error}")

    def test_approval_policy_manual_requires_approval(self):
        """approval_policy=MANUAL + REVIEW_REQUIRED risk -> human approval required."""
        self._register_noop_agent("manual_agent", risk_level="HIGH", approval_policy="MANUAL")
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="manual_agent")
        task = self._make_task("tool:read", "read file", agent_name="manual_agent")
        result = runtime.execute(task)
        self.assertIsNotNone(result.error)
        self.assertIn("approval", result.error.lower())

    def test_approval_policy_deny_always_denies(self):
        """approval_policy=DENY -> always denied regardless of risk."""
        self._register_noop_agent("deny_agent", risk_level="LOW", approval_policy="DENY")
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="deny_agent")
        task = self._make_task("tool:read", "read file", agent_name="deny_agent")
        result = runtime.execute(task)
        self.assertIsNotNone(result.error)
        self.assertIn("deny", result.error.lower())

    def test_no_transport_before_approval(self):
        """On denial, no dispatch/transport hop happens (transport.calls == [])."""
        self._register_noop_agent("manual_agent2", risk_level="HIGH", approval_policy="MANUAL")

        class TrackingDispatcher:
            def __init__(self):
                self.calls = []

            def dispatch(self, task, agent):
                self.calls.append(task.id)
                return {"status": "dispatched"}

        dispatcher = TrackingDispatcher()
        runtime = self._make_runtime(
            capability_bus=self.bus,
            governance=self.gov,
            agent_registry=self.registry,
            agent_id="manual_agent2",
            dispatcher=dispatcher,
        )
        task = self._make_task("tool:deploy", "run release pipeline", agent_name="manual_agent2")
        result = runtime.execute(task)
        self.assertIsNotNone(result.error)
        self.assertEqual(dispatcher.calls, [], "Dispatcher called before approval - invariant violated")


class TestAllowedToolsGate(_IsolatedTestMixin, unittest.TestCase):
    """Gate 5: allowed_tools — reject capabilities not in agent's allowed list."""

    def setUp(self):
        self.gov = self._make_gov()
        self.bus = self._make_bus()
        self.registry = AgentRegistry()
        self._register_noop_agent(
            "restricted_agent",
            risk_level="LOW",
            allowed_tools=["tool:read", "tool:analyze"],
            approval_policy="AUTO",
        )

    def test_allowed_tool_passes(self):
        """Capability in allowed_tools -> ALLOW."""
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="restricted_agent")
        task = self._make_task("tool:read", "read file", agent_name="restricted_agent")
        result = runtime.execute(task)
        self.assertIsNone(result.error, f"Expected no error, got: {result.error}")

    def test_disallowed_tool_rejected(self):
        """Capability NOT in allowed_tools -> REJECT (before approval gate)."""
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="restricted_agent")
        task = self._make_task("tool:deploy", "run release pipeline", agent_name="restricted_agent")
        result = runtime.execute(task)
        self.assertIsNotNone(result.error)
        self.assertIn("not allowed", result.error.lower())

    def test_empty_allowed_tools_allows_all(self):
        """Empty allowed_tools list -> all tools allowed (backward compat)."""
        self._register_noop_agent("open_agent", risk_level="LOW", allowed_tools=[], approval_policy="AUTO")
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="open_agent")
        task = self._make_task("tool:write", "write file", agent_name="open_agent")
        result = runtime.execute(task)
        self.assertIsNone(result.error, f"Expected no error with empty allowed_tools, got: {result.error}")

    def test_wildcard_allowed_tools_allows_all(self):
        """allowed_tools=['*'] -> all tools allowed."""
        self._register_noop_agent("wildcard_agent", risk_level="LOW", allowed_tools=["*"], approval_policy="AUTO")
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="wildcard_agent")
        task = self._make_task("tool:write", "write file", agent_name="wildcard_agent")
        result = runtime.execute(task)
        self.assertIsNone(result.error, f"Expected no error with wildcard allowed_tools, got: {result.error}")

    def test_unknown_agent_preserves_current_behavior(self):
        """Unknown/unregistered agent: keep current behavior (no extra enforcement)."""
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="unknown_agent")
        task = self._make_task("tool:read", "read file", agent_name="unknown_agent")
        result = runtime.execute(task)
        self.assertIsNone(result.error, f"Expected no error for unknown agent, got: {result.error}")


class TestCombinedGates(_IsolatedTestMixin, unittest.TestCase):
    """Test interactions between multiple gates."""

    def setUp(self):
        self.gov = self._make_gov()
        self.bus = self._make_bus()
        self.registry = AgentRegistry()

    def test_high_risk_agent_with_manual_approval_and_budget(self):
        """Agent HIGH risk + MANUAL approval + budget limit."""
        self._register_noop_agent(
            "complex_agent",
            risk_level="HIGH",
            max_budget=1.0,
            max_iterations=2,
            approval_policy="MANUAL",
            allowed_tools=["tool:read"],
        )
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="complex_agent", max_cost_usd=10.0)

        # Allowed tool but effective HIGH risk + MANUAL -> approval required.
        task = self._make_task("tool:read", "read file", agent_name="complex_agent")
        result = runtime.execute(task)
        self.assertIsNotNone(result.error)
        self.assertIn("approval", result.error.lower())

        # With auto-approve the same call passes all gates.
        with patch.dict(os.environ, {"GOVERNANCE_AUTO_APPROVE": "true"}):
            result2 = runtime.execute(task)
            self.assertIsNone(result2.error, f"Expected pass with auto-approve, got: {result2.error}")

    def test_allowed_tool_but_exceeds_budget(self):
        """Tool is allowed but cost exceeds budget -> budget gate fires."""
        self._register_noop_agent(
            "budget_limited",
            risk_level="LOW",
            max_budget=0.1,
            allowed_tools=["tool:read", "tool:write", "tool:deploy"],
            approval_policy="AUTO",
        )
        runtime = self._make_runtime(capability_bus=self.bus, governance=self.gov, agent_registry=self.registry, agent_id="budget_limited", max_cost_usd=10.0)
        # tool:deploy costs $1.0 > $0.1 budget; budget gate runs before approval.
        task = self._make_task("tool:deploy", "run release pipeline", agent_name="budget_limited")
        result = runtime.execute(task)
        self.assertIsNotNone(result.error)
        self.assertIn("budget", result.error.lower())


if __name__ == "__main__":
    unittest.main()
