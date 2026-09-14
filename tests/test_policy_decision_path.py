"""E3 — Policy Decision Path tests.

Tests the single canonical decision path for capability risk classification:
- 4 risk levels × outcomes (ALLOW/APPROVE/DENY)
- Audit entry exists per execution
- Auto-approve loud (caplog + audit trail) when GOVERNANCE_AUTO_APPROVE=1
- Unauthorized capability (not in bus) → DENY
- Agent fields validate: CRITICAL agent + approval_policy=AUTO → ValueError
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from src.core.capability import Capability, CapabilitySource, InMemoryCapabilityBus
from src.core.governance import ActionClass, Governance
from src.core.agent_registry import AgentRegistry
from src.core.agent_base import AgentBase


class _IsolatedGovernanceMixin:
    """Provides a Governance instance with a unique, cleaned-up audit path."""

    def _make_gov(self) -> Governance:
        self._tmpdir = tempfile.mkdtemp(prefix="policy_test_")
        self.addCleanup(shutil.rmtree, self._tmpdir, ignore_errors=True)
        return Governance(audit_path=os.path.join(self._tmpdir, "audit.yaml"))


class TestPolicyDecisionMatrix(_IsolatedGovernanceMixin, unittest.TestCase):
    """Test 4 risk levels × outcomes matrix."""

    def setUp(self):
        self.gov = self._make_gov()
        self.bus = InMemoryCapabilityBus()

    def test_low_risk_allow(self):
        """LOW risk → SAFE (ALLOW)."""
        cap = Capability(
            id="test:low",
            name="Low Risk",
            description="Low risk capability",
            risk_level="LOW",
            source=CapabilitySource.BUILTIN,
        )
        self.bus.register(cap)

        decision = self.gov.classify_risk(cap.risk_level)
        self.assertEqual(decision.action_class, ActionClass.SAFE)
        self.assertFalse(decision.requires_approval)

    def test_medium_risk_allow_with_audit(self):
        """MEDIUM risk → SAFE (+mandatory audit)."""
        cap = Capability(
            id="test:medium",
            name="Medium Risk",
            description="Medium risk capability",
            risk_level="MEDIUM",
            source=CapabilitySource.API,
        )
        self.bus.register(cap)

        decision = self.gov.classify_risk(cap.risk_level)
        self.assertEqual(decision.action_class, ActionClass.SAFE)
        # Audit entry recorded
        trail = self.gov.get_audit_trail()
        self.assertTrue(any(e.goal == "capability:MEDIUM" for e in trail))

    def test_high_risk_requires_approval(self):
        """HIGH risk → REVIEW_REQUIRED (APPROVE gate)."""
        cap = Capability(
            id="test:high",
            name="High Risk",
            description="High risk capability",
            risk_level="HIGH",
            source=CapabilitySource.MCP,
        )
        self.bus.register(cap)

        decision = self.gov.classify_risk(cap.risk_level)
        self.assertEqual(decision.action_class, ActionClass.REVIEW_REQUIRED)
        self.assertTrue(decision.requires_approval)

    def test_critical_risk_denied(self):
        """CRITICAL risk → FORBIDDEN (DENY)."""
        cap = Capability(
            id="test:critical",
            name="Critical Risk",
            description="Critical risk capability",
            risk_level="CRITICAL",
            source=CapabilitySource.CUSTOM,
        )
        self.bus.register(cap)

        decision = self.gov.classify_risk(cap.risk_level)
        self.assertEqual(decision.action_class, ActionClass.FORBIDDEN)
        self.assertFalse(decision.requires_approval)


class TestAuditEntryPerExecution(_IsolatedGovernanceMixin, unittest.TestCase):
    """Audit entry must exist for every execution path."""

    def setUp(self):
        self.gov = self._make_gov()

    def test_audit_on_safe_classification(self):
        """SAFE classification records audit with result=executed (approved=False until request_approval called)."""
        decision = self.gov.classify("read file")
        self.assertEqual(decision.action_class, ActionClass.SAFE)

        trail = self.gov.get_audit_trail()
        self.assertEqual(len(trail), 1)
        entry = trail[0]
        self.assertEqual(entry.action_class, "safe")
        self.assertEqual(entry.result, "executed")
        # approved=False because request_approval() not called yet;
        # it is set to True when caller invokes request_approval for SAFE actions.
        self.assertFalse(entry.approved)

    def test_audit_on_forbidden_classification(self):
        """FORBIDDEN classification records audit with result=blocked."""
        decision = self.gov.classify("rm -rf /data")
        self.assertEqual(decision.action_class, ActionClass.FORBIDDEN)

        trail = self.gov.get_audit_trail()
        self.assertEqual(len(trail), 1)
        entry = trail[0]
        self.assertEqual(entry.action_class, "forbidden")
        self.assertEqual(entry.result, "blocked")
        self.assertFalse(entry.approved)

    def test_audit_on_review_without_approval(self):
        """REVIEW_REQUIRED without approval records audit with result=rejected."""
        decision = self.gov.classify("deploy to prod")
        self.assertEqual(decision.action_class, ActionClass.REVIEW_REQUIRED)

        # Don't set GOVERNANCE_AUTO_APPROVE — should reject
        result = self.gov.request_approval("deploy to prod", decision)
        self.assertFalse(result)

        trail = self.gov.get_audit_trail()
        self.assertEqual(len(trail), 1)
        entry = trail[0]
        self.assertEqual(entry.action_class, "review_required")
        self.assertEqual(entry.result, "rejected")
        self.assertFalse(entry.approved)

    def test_audit_on_review_with_approval(self):
        """REVIEW_REQUIRED with GOVERNANCE_AUTO_APPROVE records audit with result=approved."""
        with patch.dict(os.environ, {"GOVERNANCE_AUTO_APPROVE": "true"}):
            decision = self.gov.classify("deploy to prod")
            self.assertEqual(decision.action_class, ActionClass.REVIEW_REQUIRED)

            result = self.gov.request_approval("deploy to prod", decision)
            self.assertTrue(result)

            trail = self.gov.get_audit_trail()
            self.assertEqual(len(trail), 1)
            entry = trail[0]
            self.assertEqual(entry.action_class, "review_required")
            self.assertEqual(entry.result, "approved")
            self.assertTrue(entry.approved)

    def test_audit_on_risk_classification(self):
        """classify_risk records audit for each risk level."""
        # LOW → SAFE + audit executed
        self.gov.classify_risk("LOW")
        trail = self.gov.get_audit_trail()
        self.assertTrue(any(e.goal == "capability:LOW" and e.result == "executed" for e in trail))

        # MEDIUM → SAFE + audit executed
        self.gov.classify_risk("MEDIUM")
        trail = self.gov.get_audit_trail()
        self.assertTrue(any(e.goal == "capability:MEDIUM" and e.result == "executed" for e in trail))

        # HIGH → REVIEW_REQUIRED (no audit until approval gate runs)
        self.gov.classify_risk("HIGH")
        trail = self.gov.get_audit_trail()
        high_entries = [e for e in trail if e.goal == "capability:HIGH"]
        # HIGH defers audit to request_approval; no entry yet is acceptable,
        # but if present it must be review_required.
        for entry in high_entries:
            self.assertEqual(entry.action_class, "review_required")

        # CRITICAL → FORBIDDEN + audit blocked
        self.gov.classify_risk("CRITICAL")
        trail = self.gov.get_audit_trail()
        self.assertTrue(any(e.goal == "capability:CRITICAL" and e.result == "blocked" for e in trail))


class TestAutoApproveLoud(_IsolatedGovernanceMixin, unittest.TestCase):
    """Auto-approve must be loud: WARNING log + audit trail."""

    def setUp(self):
        self.gov = self._make_gov()

    def test_auto_approve_logs_warning(self):
        """Auto-approve via GOVERNANCE_AUTO_APPROVE logs WARNING."""
        with patch.dict(os.environ, {"GOVERNANCE_AUTO_APPROVE": "true"}):
            with self.assertLogs(logger="src.core.governance", level="WARNING") as cm:
                decision = self.gov.classify("deploy to prod")
                result = self.gov.request_approval("deploy to prod", decision)

            self.assertTrue(result)
            # Check for the auto-approve WARNING log
            warning_logs = [log for log in cm.output if "auto-approving" in log.lower()]
            self.assertTrue(len(warning_logs) > 0, f"Expected auto-approve WARNING log, got: {cm.output}")

    def test_auto_approve_records_approved_audit(self):
        """Auto-approve records audit with result=approved."""
        with patch.dict(os.environ, {"GOVERNANCE_AUTO_APPROVE": "true"}):
            decision = self.gov.classify("deploy to prod")
            self.gov.request_approval("deploy to prod", decision)

        trail = self.gov.get_audit_trail()
        entry = trail[0]
        self.assertEqual(entry.result, "approved")
        self.assertTrue(entry.approved)

    def test_auto_approve_variations(self):
        """Test GOVERNANCE_AUTO_APPROVE variations: '1', 'yes', 'true'."""
        for val in ("1", "yes", "true"):
            with self.subTest(val=val):
                gov = self._make_gov()
                with patch.dict(os.environ, {"GOVERNANCE_AUTO_APPROVE": val}):
                    with self.assertLogs(logger="src.core.governance", level="WARNING") as cm:
                        decision = gov.classify("push to main")
                        result = gov.request_approval("push to main", decision)

                self.assertTrue(result)
                warning_logs = [log for log in cm.output if "auto-approving" in log.lower()]
                self.assertTrue(len(warning_logs) > 0)

    def test_no_auto_approve_logs_warning_too(self):
        """Without auto-approve, logs WARNING about human approval needed."""
        env = {k: v for k, v in os.environ.items() if k != "GOVERNANCE_AUTO_APPROVE"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertLogs(logger="src.core.governance", level="WARNING") as cm:
                decision = self.gov.classify("deploy to prod")
                result = self.gov.request_approval("deploy to prod", decision)

            self.assertFalse(result)
            warning_logs = [log for log in cm.output if "human approval" in log.lower()]
            self.assertTrue(len(warning_logs) > 0)


class TestUnauthorizedCapabilityDenied(_IsolatedGovernanceMixin, unittest.TestCase):
    """Capability not in bus → DENY."""

    def setUp(self):
        self.gov = self._make_gov()
        self.bus = InMemoryCapabilityBus()

    def test_capability_not_in_bus_returns_error(self):
        """Executing capability not in bus returns error (handled by bus.execute)."""
        # This tests the bus behavior, not governance directly
        result = self.bus.execute("nonexistent:cap", {})
        self.assertIn("error", result)
        self.assertIn("not found", result["error"])

    def test_governance_does_not_classify_unknown_capability(self):
        """Governance only classifies capabilities that exist in bus."""
        # Capability not registered — governance not involved
        cap = self.bus.get("unknown:cap")
        self.assertIsNone(cap)

        # classify_risk still works on risk level strings
        decision = self.gov.classify_risk("HIGH")
        self.assertEqual(decision.action_class, ActionClass.REVIEW_REQUIRED)

    def test_capability_authorization_denied(self):
        """Capability with authorization rejects unauthorized principals."""
        cap = Capability(
            id="admin:delete",
            name="Admin Delete",
            description="Delete anything",
            risk_level="HIGH",
            authorization="admin",
        )
        self.bus.register(cap)

        # Authorized
        self.assertTrue(self.bus.check_authorization("admin:delete", "admin"))
        # Unauthorized
        self.assertFalse(self.bus.check_authorization("admin:delete", "user"))


class TestAgentFieldsValidation(unittest.TestCase):
    """Agent declarative fields validation."""

    def test_critical_risk_with_auto_approval_raises(self):
        """CRITICAL risk agent + approval_policy=AUTO → ValueError."""
        registry = AgentRegistry()

        class DummyAgent(AgentBase):
            def plan(self, input_data: str):
                return []

            def execute(self, task):
                pass

        with self.assertRaises(ValueError) as cm:
            registry.register(
                "critical_auto",
                DummyAgent,
                description="Critical agent with auto approval",
                risk_level="CRITICAL",
                approval_policy="AUTO",
            )
        self.assertIn("CRITICAL risk agents cannot have approval_policy=AUTO", str(cm.exception))

    def test_valid_risk_levels(self):
        """All valid risk levels accepted."""
        registry = AgentRegistry()

        class DummyAgent(AgentBase):
            def plan(self, input_data: str):
                return []

            def execute(self, task):
                pass

        for risk in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            with self.subTest(risk=risk):
                # CRITICAL needs non-AUTO approval_policy
                approval = "MANUAL" if risk == "CRITICAL" else "AUTO"
                registry.register(
                    f"agent_{risk.lower()}",
                    DummyAgent,
                    risk_level=risk,
                    approval_policy=approval,
                )

    def test_invalid_risk_level_raises(self):
        """Invalid risk_level → ValueError."""
        registry = AgentRegistry()

        class DummyAgent(AgentBase):
            def plan(self, input_data: str):
                return []

            def execute(self, task):
                pass

        with self.assertRaises(ValueError) as cm:
            registry.register(
                "bad_risk",
                DummyAgent,
                risk_level="INVALID",
            )
        self.assertIn("Invalid risk_level", str(cm.exception))

    def test_invalid_approval_policy_raises(self):
        """Invalid approval_policy → ValueError."""
        registry = AgentRegistry()

        class DummyAgent(AgentBase):
            def plan(self, input_data: str):
                return []

            def execute(self, task):
                pass

        with self.assertRaises(ValueError) as cm:
            registry.register(
                "bad_approval",
                DummyAgent,
                approval_policy="INVALID",
            )
        self.assertIn("Invalid approval_policy", str(cm.exception))

    def test_defaults_backward_compat(self):
        """Agents without declarative fields use defaults and register successfully."""
        registry = AgentRegistry()

        class DummyAgent(AgentBase):
            def plan(self, input_data: str):
                return []

            def execute(self, task):
                pass

        # Old-style registration (no policy fields) should work
        registry.register("old_style", DummyAgent, description="Old style agent")

        meta = registry.get_meta_obj("old_style")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.risk_level, "LOW")
        self.assertEqual(meta.approval_policy, "AUTO")
        self.assertIsNone(meta.max_budget)
        self.assertIsNone(meta.max_iterations)
        self.assertIsNone(meta.model_preference)

    def test_explicit_defaults_work(self):
        """Explicit default values work the same as implicit."""
        registry = AgentRegistry()

        class DummyAgent(AgentBase):
            def plan(self, input_data: str):
                return []

            def execute(self, task):
                pass

        registry.register(
            "explicit_defaults",
            DummyAgent,
            risk_level="LOW",
            max_budget=None,
            max_iterations=None,
            approval_policy="AUTO",
            model_preference=None,
        )

        meta = registry.get_meta_obj("explicit_defaults")
        self.assertEqual(meta.risk_level, "LOW")
        self.assertEqual(meta.approval_policy, "AUTO")


class TestRuntimeCapabilityDecisionPath(_IsolatedGovernanceMixin, unittest.TestCase):
    """Integration test: runtime.execute() → capability bus → governance."""

    def _make_runtime(self, capability_bus=None, governance=None):
        from src.core.runtime_adapter import MekongCoreRuntimeImpl

        class FakeDispatcher:
            def dispatch(self, task, agent):
                return {"ok": True, "dispatched": True}

        class FakeToolRegistry:
            def execute(self, tool, params):
                return {"ok": True, "tool": tool}

        return MekongCoreRuntimeImpl(
            dispatcher=FakeDispatcher(),
            tool_registry=FakeToolRegistry(),
            capability_bus=capability_bus,
            governance=governance,
        )

    def _make_task(self, capability_id: str, description: str):
        return type("Task", (), {
            "id": "task-1",
            "step": type("Step", (), {"description": description})(),
            "agent": type("AgentId", (), {"name": "default"})(),
            "params": {"capability_id": capability_id},
        })()

    def test_capability_low_risk_executes(self):
        """LOW risk capability executes without gate."""
        gov = self._make_gov()
        bus = InMemoryCapabilityBus()

        cap = Capability(
            id="tool:read",
            name="Read File",
            description="Read a file",
            risk_level="LOW",
            source=CapabilitySource.BUILTIN,
        )
        bus.register(cap)

        runtime = self._make_runtime(capability_bus=bus, governance=gov)
        task = self._make_task("tool:read", "read file")

        result = runtime.execute(task)
        self.assertIsNone(result.error)

    def test_capability_high_risk_blocked_without_approval(self):
        """HIGH risk capability blocked without GOVERNANCE_AUTO_APPROVE."""
        gov = self._make_gov()
        bus = InMemoryCapabilityBus()

        cap = Capability(
            id="tool:deploy",
            name="Deploy",
            description="Deploy to production",
            risk_level="HIGH",
            source=CapabilitySource.CLI,
        )
        bus.register(cap)

        runtime = self._make_runtime(capability_bus=bus, governance=gov)
        # Benign description so goal-based Gate 2 passes; the HIGH-risk
        # capability itself must trigger the Gate 2.5 approval block.
        task = self._make_task("tool:deploy", "run release pipeline")

        result = runtime.execute(task)
        self.assertIsNotNone(result.error)
        self.assertIn("approval", result.error.lower())
        self.assertTrue(result.metadata.get("gate_blocked"))

    def test_capability_high_risk_auto_approved(self):
        """HIGH risk capability allowed with GOVERNANCE_AUTO_APPROVE."""
        with patch.dict(os.environ, {"GOVERNANCE_AUTO_APPROVE": "true"}):
            gov = self._make_gov()
            bus = InMemoryCapabilityBus()

            cap = Capability(
                id="tool:deploy",
                name="Deploy",
                description="Deploy to production",
                risk_level="HIGH",
                source=CapabilitySource.CLI,
            )
            bus.register(cap)

            runtime = self._make_runtime(capability_bus=bus, governance=gov)
            task = self._make_task("tool:deploy", "run release pipeline")

            result = runtime.execute(task)
            self.assertIsNone(result.error)

    def test_capability_critical_risk_denied_even_with_auto_approve(self):
        """CRITICAL risk capability denied even with GOVERNANCE_AUTO_APPROVE."""
        with patch.dict(os.environ, {"GOVERNANCE_AUTO_APPROVE": "true"}):
            gov = self._make_gov()
            bus = InMemoryCapabilityBus()

            cap = Capability(
                id="tool:destroy",
                name="Destroy",
                description="Destroy infrastructure",
                risk_level="CRITICAL",
                source=CapabilitySource.CUSTOM,
            )
            bus.register(cap)

            runtime = self._make_runtime(capability_bus=bus, governance=gov)
            # Benign description so goal-based Gate 2 passes; the CRITICAL-risk
            # capability itself must trigger the Gate 2.5 FORBIDDEN block.
            task = self._make_task("tool:destroy", "decommission old servers")

            result = runtime.execute(task)
            self.assertIsNotNone(result.error)
            self.assertIn("forbidden", result.error.lower())
            self.assertTrue(result.metadata.get("gate_blocked"))


if __name__ == "__main__":
    unittest.main()
