"""Tests for the YAML agent registry (single source of truth).

Covers:
- ``agents.yaml`` loads into the expected number of agent definitions.
- ``DEFAULT_PROMPTS`` and ``_DEFAULT_DESCRIPTIONS`` derive from the YAML
  without duplication (no-duplication acceptance).
- Structural YAML errors raise ``RegistryLoadError`` (fail-loud).
- ``mekong agent list`` renders agents sourced from the derived registry.
- ``AgentMeta`` validation is preserved end-to-end (CRITICAL + AUTO rejected).
"""

from __future__ import annotations

import textwrap

import pytest
from typer.testing import CliRunner

from src.cli.commands.agent_commands import app as agent_app
from src.core.agent_dispatcher import DEFAULT_PROMPTS
from src.core.agent_registry import AgentRegistry, _DEFAULT_DESCRIPTIONS
from src.core.registry.loader import (
    AgentDefinition,
    RegistryLoadError,
    load_agents_yaml,
    load_descriptions,
    load_prompts,
)

runner = CliRunner()

CSUITE = ("cto", "cmo", "coo", "cfo", "cso", "planner")
PROMPT_ONLY = ("cs", "sales", "editor", "data", "analyst", "devops", "pm", "support")


class _BareAgent:
    """Minimal non-AgentBase class — register() warns but still validates meta."""

    def plan(self, _):
        return []

    def execute(self, _):
        pass


# ---------------------------------------------------------------------------
# (a) YAML → definitions
# ---------------------------------------------------------------------------


class TestYamlLoad:
    def test_loads_all_agents(self):
        """Every declarative entry in agents.yaml must parse cleanly."""
        defs = load_agents_yaml()
        assert isinstance(defs, dict)
        # 6 C-suite entries + 8 prompt-only roles = 14 total.
        assert len(defs) == 14

    def test_each_definition_has_name(self):
        for name, definition in load_agents_yaml().items():
            assert isinstance(definition, AgentDefinition)
            assert definition.name == name

    def test_csuite_entries_have_descriptions(self):
        defs = load_agents_yaml()
        for name in CSUITE:
            assert defs[name].description is not None
            assert defs[name].description.strip()

    def test_prompt_only_roles_lack_description(self):
        defs = load_agents_yaml()
        for name in PROMPT_ONLY:
            assert defs[name].description is None
            assert defs[name].prompt is not None and defs[name].prompt.strip()

    def test_cso_and_planner_have_no_prompt(self):
        """Historically cso/planner were description-only (no prompt)."""
        defs = load_agents_yaml()
        assert defs["cso"].prompt is None
        assert defs["planner"].prompt is None

    def test_csuite_policy_fields_default(self):
        defs = load_agents_yaml()
        for name in CSUITE:
            assert defs[name].risk_level == "LOW"
            assert defs[name].approval_policy == "AUTO"


# ---------------------------------------------------------------------------
# (b) derive match — no duplication
# ---------------------------------------------------------------------------


class TestDeriveNoDuplication:
    def test_descriptions_derive_from_yaml(self):
        assert _DEFAULT_DESCRIPTIONS == load_descriptions()

    def test_prompts_derive_from_yaml(self):
        assert DEFAULT_PROMPTS == load_prompts()

    def test_descriptions_shape(self):
        assert isinstance(_DEFAULT_DESCRIPTIONS, dict)
        assert all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in _DEFAULT_DESCRIPTIONS.items()
        )

    def test_prompts_shape(self):
        assert isinstance(DEFAULT_PROMPTS, dict)
        assert all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in DEFAULT_PROMPTS.items()
        )

    def test_union_is_14_agents(self):
        """6 descriptions + 12 prompts overlap on 4 C-suite → 14 total."""
        names = set(_DEFAULT_DESCRIPTIONS) | set(DEFAULT_PROMPTS)
        assert len(names) == 14


# ---------------------------------------------------------------------------
# (c) fail-loud on bad YAML
# ---------------------------------------------------------------------------


class TestRegistryLoadError:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RegistryLoadError):
            load_agents_yaml(tmp_path / "does_not_exist.yaml")

    def test_non_mapping_top_level_raises(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(RegistryLoadError):
            load_agents_yaml(path)

    def test_entry_missing_prompt_and_description_raises(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(
            textwrap.dedent(
                """\
                ghost:
                  risk_level: HIGH
                """
            ),
            encoding="utf-8",
        )
        with pytest.raises(RegistryLoadError):
            load_agents_yaml(path)

    def test_entry_not_a_mapping_raises(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("cto: just a string\n", encoding="utf-8")
        with pytest.raises(RegistryLoadError):
            load_agents_yaml(path)

    def test_malformed_yaml_raises(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("cto: [unclosed\n", encoding="utf-8")
        with pytest.raises(RegistryLoadError):
            load_agents_yaml(path)

    def test_invalid_prompt_type_raises(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("cto:\n  prompt: 123\n", encoding="utf-8")
        with pytest.raises(RegistryLoadError):
            load_agents_yaml(path)


# ---------------------------------------------------------------------------
# (d) CLI renders agents from the derived registry
# ---------------------------------------------------------------------------


class TestCliRegistry:
    def test_agent_list_shows_csuite(self):
        result = runner.invoke(agent_app, ["list"])
        assert result.exit_code == 0, result.output
        for name in CSUITE:
            assert name in result.output, f"{name!r} missing from list output"

    def test_agent_list_count_matches_singleton(self):
        from src.core.agent_registry import get_registry

        result = runner.invoke(agent_app, ["list"])
        assert result.exit_code == 0, result.output
        expected = f"Registered agents ({len(get_registry()._agents)})"
        assert expected in result.output, result.output

    def test_get_meta_obj_returns_derived_description(self):
        from src.core.agent_registry import get_registry

        meta = get_registry().get_meta_obj("cto")
        assert meta is not None
        assert meta.description == _DEFAULT_DESCRIPTIONS["cto"]


# ---------------------------------------------------------------------------
# (e) AgentMeta validation preserved end-to-end
# ---------------------------------------------------------------------------


class TestAgentMetaValidationPreserved:
    def test_critical_risk_auto_rejected(self):
        """CRITICAL + AUTO must still raise — validation survives the derive."""
        registry = AgentRegistry()
        with pytest.raises(ValueError, match="CRITICAL risk agents cannot have approval_policy=AUTO"):
            registry.register(
                "critical_auto_yaml",
                _BareAgent,
                description="x",
                risk_level="CRITICAL",
                approval_policy="AUTO",
            )

    def test_invalid_risk_level_rejected(self):
        registry = AgentRegistry()
        with pytest.raises(ValueError, match="Invalid risk_level"):
            registry.register(
                "bad_risk_yaml",
                _BareAgent,
                description="x",
                risk_level="EXTREME",
            )

    def test_critical_risk_manual_allowed(self):
        registry = AgentRegistry()
        registry.register(
            "critical_manual_yaml",
            _BareAgent,
            description="x",
            risk_level="CRITICAL",
            approval_policy="MANUAL",
        )
        meta = registry.get_meta_obj("critical_manual_yaml")
        assert meta is not None
        assert meta.risk_level == "CRITICAL"
        assert meta.approval_policy == "MANUAL"
