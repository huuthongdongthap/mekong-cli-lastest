"""Phase 2A (Step 3): Agent Registry consolidation tests.

Note: AgentRegistry already serves as the consolidated registry.
These tests verify it satisfies the AgentDispatcher Protocol's discovery needs (Protocol removed; registry still works).

E3 — Extended with declarative policy field tests (risk_level, approval_policy, etc.).
"""
import pytest

from src.core.agent_registry import AgentRegistry
from src.core.agent_base import AgentBase


class TestAgentRegistryConsolidated:
    def test_registry_loads_from_default_dir(self):
        """AgentRegistry must be instantiable."""
        registry = AgentRegistry()
        assert registry is not None

    def test_registry_list_returns_names(self):
        """list() must return list of agent name strings."""
        registry = AgentRegistry()
        names = registry.list()
        assert isinstance(names, list)

    def test_registry_get_existing(self):
        """get() must return agent class for registered agent."""
        registry = AgentRegistry()
        names = registry.list()
        if names:
            first = names[0]
            agent_cls = registry.get(first)
            assert agent_cls is not None

    def test_registry_get_missing_raises(self):
        """get() must raise KeyError for unknown agent."""
        registry = AgentRegistry()
        with pytest.raises(KeyError):
            registry.get("nonexistent_agent_xyz")

    def test_registry_has_required_fields(self):
        """Retrieved agent class must have name and role."""
        registry = AgentRegistry()
        names = registry.list()
        if names:
            agent_cls = registry.get(names[0])
            assert hasattr(agent_cls, "name")
            assert hasattr(agent_cls, "role")


class _DummyAgent(AgentBase):
    """Minimal AgentBase subclass for registration tests."""

    def plan(self, input_data: str):
        return []

    def execute(self, task):
        pass


class TestDeclarativePolicyFields:
    """E3 — Declarative policy fields on AgentMeta."""

    def test_defaults_applied_when_omitted(self):
        """Omitting policy fields yields safe defaults."""
        registry = AgentRegistry()
        registry.register("defaults_agent", _DummyAgent, description="Defaults")
        meta = registry.get_meta_obj("defaults_agent")
        assert meta is not None
        assert meta.risk_level == "LOW"
        assert meta.approval_policy == "AUTO"
        assert meta.max_budget is None
        assert meta.max_iterations is None
        assert meta.model_preference is None

    def test_explicit_policy_fields_stored(self):
        """Explicit policy fields are stored on AgentMeta."""
        registry = AgentRegistry()
        registry.register(
            "explicit_agent",
            _DummyAgent,
            description="Explicit",
            risk_level="HIGH",
            max_budget=10.0,
            max_iterations=5,
            approval_policy="MANUAL",
            model_preference="claude-sonnet",
        )
        meta = registry.get_meta_obj("explicit_agent")
        assert meta is not None
        assert meta.risk_level == "HIGH"
        assert meta.max_budget == 10.0
        assert meta.max_iterations == 5
        assert meta.approval_policy == "MANUAL"
        assert meta.model_preference == "claude-sonnet"

    def test_critical_risk_auto_approval_rejected(self):
        """CRITICAL risk + AUTO approval is an invalid combination."""
        registry = AgentRegistry()
        with pytest.raises(ValueError, match="CRITICAL risk agents cannot have approval_policy=AUTO"):
            registry.register(
                "critical_auto",
                _DummyAgent,
                risk_level="CRITICAL",
                approval_policy="AUTO",
            )

    def test_critical_risk_manual_approval_allowed(self):
        """CRITICAL risk + MANUAL approval is valid."""
        registry = AgentRegistry()
        registry.register(
            "critical_manual",
            _DummyAgent,
            risk_level="CRITICAL",
            approval_policy="MANUAL",
        )
        meta = registry.get_meta_obj("critical_manual")
        assert meta is not None
        assert meta.risk_level == "CRITICAL"
        assert meta.approval_policy == "MANUAL"

    def test_invalid_risk_level_rejected(self):
        """Invalid risk_level raises ValueError."""
        registry = AgentRegistry()
        with pytest.raises(ValueError, match="Invalid risk_level"):
            registry.register("bad_risk", _DummyAgent, risk_level="EXTREME")

    def test_invalid_approval_policy_rejected(self):
        """Invalid approval_policy raises ValueError."""
        registry = AgentRegistry()
        with pytest.raises(ValueError, match="Invalid approval_policy"):
            registry.register("bad_policy", _DummyAgent, approval_policy="ALWAYS")

    def test_all_valid_risk_levels_accepted(self):
        """All four valid risk levels are accepted."""
        registry = AgentRegistry()
        for risk in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            approval = "MANUAL" if risk == "CRITICAL" else "AUTO"
            registry.register(
                f"risk_{risk.lower()}",
                _DummyAgent,
                risk_level=risk,
                approval_policy=approval,
            )
            meta = registry.get_meta_obj(f"risk_{risk.lower()}")
            assert meta is not None
            assert meta.risk_level == risk

    def test_all_valid_approval_policies_accepted(self):
        """All three valid approval policies are accepted."""
        registry = AgentRegistry()
        for policy in ("AUTO", "MANUAL", "DENY"):
            registry.register(
                f"policy_{policy.lower()}",
                _DummyAgent,
                risk_level="LOW",
                approval_policy=policy,
            )
            meta = registry.get_meta_obj(f"policy_{policy.lower()}")
            assert meta is not None
            assert meta.approval_policy == policy

    def test_backward_compat_old_style_registration(self):
        """Old-style registration (no policy fields) still works."""
        registry = AgentRegistry()
        registry.register("old_style", _DummyAgent, description="Old style")
        assert "old_style" in registry
        meta = registry.get_meta_obj("old_style")
        assert meta is not None
        assert meta.risk_level == "LOW"
        assert meta.approval_policy == "AUTO"