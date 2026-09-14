"""Tests for LLM prompt rendering in company_init.py (Phase 4)."""

from __future__ import annotations

import json
import os
import urllib.request  # noqa: F401
from unittest.mock import MagicMock, patch

import pytest

from src.core.company_init import (
    AGENT_ROLES,
    CompanyConfig,
    _get_llm_api_key,
    _get_llm_base_url,
    _get_llm_model,
    _SCRUB_MAX_RENDERED_BYTES,
    _SECRET_PATTERNS,
    generate_config_files,
    render_agent_prompts_llm,
    scrub_secrets,
    validate_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> CompanyConfig:
    """Build a minimal valid CompanyConfig for tests."""
    defaults = {
        "company_name": "TestCorp",
        "product_type": "saas",
        "scenario": "hybrid",
        "budget_tier": "minimal",
        "primary_language": "en",
    }
    defaults.update(overrides)
    return CompanyConfig(**defaults)


def _make_templates(company: str = "TestCorp", lang: str = "en") -> dict[str, str]:
    """Return per-role templates with placeholders pre-resolved."""
    return {
        role: (
            f"You are the {role.upper()} of {company}.\n"
            f"Language: {lang}\n"
            f"Focus: test.\n"
            f"Rule 1. Rule 2."
        )
        for role in AGENT_ROLES
    }


def _mock_llm_content(role: str, company: str) -> str:
    """A deterministic short LLM response for a given role."""
    return (
        f"[{role.upper()} of {company}]\n"
        f"Language: {role} optimized for {company} in the SaaS domain.\n"
        f"Directives: Rule A. Rule B. Rule C."
    )


# ===================================================================
# Test 1: Without env var -> static templates (backward compatibility)
# ===================================================================


class TestStaticFallback:
    """When no API key is set, output matches the existing static path."""

    def test_no_env_var_uses_static_prompts(self):
        """Without ANTHROPIC_API_KEY or LLM_API_KEY, templates are formatted inline."""
        cfg = _make_config(company_name="StaticCo", primary_language="vi")
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("ANTHROPIC_API_KEY", "LLM_API_KEY")}
        with patch.dict(os.environ, clean_env, clear=True):
            files = generate_config_files(cfg)

        for role in AGENT_ROLES:
            content = files[f".mekong/agents/{role}.md"]
            assert "StaticCo" in content, f"Role {role} missing company name"
            assert "vi" in content, f"Role {role} missing language"

    def test_identity_static_vs_llm_disabled(self):
        """llm_render=False produces identical agent-file output."""
        cfg = _make_config(company_name="SameCo", primary_language="en")
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("ANTHROPIC_API_KEY", "LLM_API_KEY")}
        with patch.dict(os.environ, clean_env, clear=True):
            files_no_key = generate_config_files(cfg)
            files_forced = generate_config_files(cfg, llm_render=False)

        for role in AGENT_ROLES:
            key = f".mekong/agents/{role}.md"
            assert files_no_key[key] == files_forced[key], f"Mismatch for role {role}"

    def test_12_files_still_generated_without_key(self):
        cfg = _make_config()
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("ANTHROPIC_API_KEY", "LLM_API_KEY")}
        with patch.dict(os.environ, clean_env, clear=True):
            files = generate_config_files(cfg)
        assert len(files) == 12


# ===================================================================
# Test 2: Mock LLM client -> output includes company name / role
# ===================================================================


class TestLLMRendering:
    """When an API key is present (or llm_render=True), LLM is called."""

    @patch(f"{__name__}.urllib.request.urlopen")
    def test_llm_render_injects_company_name(self, mock_urlopen):
        """Rendered prompts contain the company name from the config."""
        cfg = _make_config(company_name="AcmeAI")

        responses = []
        for role in AGENT_ROLES:
            body = json.dumps({
                "choices": [{"message": {"content": _mock_llm_content(role, "AcmeAI")}}],
            }).encode("utf-8")
            resp = MagicMock()
            resp.read.return_value = body
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            responses.append(resp)

        mock_urlopen.side_effect = responses

        templates = _make_templates(company="AcmeAI", lang="en")
        rendered = render_agent_prompts_llm(cfg, templates, api_key="sk-test-12345")

        for role in AGENT_ROLES:
            assert "AcmeAI" in rendered[role], f"Role {role} missing company name"
            assert role.upper() in rendered[role], f"Role {role} missing role label"

    @patch(f"{__name__}.urllib.request.urlopen")
    def test_llm_render_via_generate_config_files(self, mock_urlopen):
        """generate_config_files uses LLM when llm_render=True."""
        cfg = _make_config(company_name="LLMCo", primary_language="en")

        responses = []
        for role in AGENT_ROLES:
            content = _mock_llm_content(role, "LLMCo")
            body = json.dumps({
                "choices": [{"message": {"content": content}}],
            }).encode("utf-8")
            resp = MagicMock()
            resp.read.return_value = body
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            responses.append(resp)

        mock_urlopen.side_effect = responses

        files = generate_config_files(cfg, llm_render=True)

        for role in AGENT_ROLES:
            assert "LLMCo" in files[f".mekong/agents/{role}.md"]

    @patch(f"{__name__}.urllib.request.urlopen")
    def test_llm_env_var_triggers_rendering(self, mock_urlopen):
        """Setting ANTHROPIC_API_KEY auto-enables LLM rendering."""
        cfg = _make_config()

        responses = []
        for role in AGENT_ROLES:
            body = json.dumps({
                "choices": [{"message": {"content": f"prompt for {role}"}}],
            }).encode("utf-8")
            resp = MagicMock()
            resp.read.return_value = body
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            responses.append(resp)

        mock_urlopen.side_effect = responses

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-anthropic-key"}, clear=False):
            generate_config_files(cfg)

        assert mock_urlopen.call_count == 8, "Expected 8 LLM calls (one per role)"

    def test_env_key_detection(self):
        """_get_llm_api_key picks up both ANTHROPIC_API_KEY and LLM_API_KEY."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "a"}, clear=False):
            assert _get_llm_api_key() == "a"
        with patch.dict(os.environ, {"LLM_API_KEY": "b"}, clear=False):
            assert _get_llm_api_key() == "b"
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "a", "LLM_API_KEY": "b"}, clear=False):
            assert _get_llm_api_key() == "a"  # ANTHROPIC preferred
        with patch.dict(os.environ, {}, clear=True):
            assert _get_llm_api_key() is None

    def test_llm_base_url_default(self):
        assert _get_llm_base_url() == "https://api.anthropic.com/v1"

    def test_llm_base_url_from_env(self):
        with patch.dict(os.environ, {"LLM_BASE_URL": "https://example.com/v1"}, clear=False):
            assert _get_llm_base_url() == "https://example.com/v1"

    def test_llm_model_default(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _get_llm_model() == "claude-sonnet-4-6-20250514"

    def test_llm_model_from_env(self):
        with patch.dict(os.environ, {"LLM_MODEL": "claude-opus-4"}, clear=False):
            assert _get_llm_model() == "claude-opus-4"


# ===================================================================
# Test 3: Scrubbing catches leaked keys / secrets / oversize
# ===================================================================


class TestSecretScrubbing:
    """scrub_secrets() must raise ValueError on various secret patterns."""

    # --- Clean text passes ---

    def test_clean_text_passes(self):
        """Normal prompt text with no secrets should not raise."""
        scrub_secrets("You are the CTO of AcmeCo.\nFocus: Architecture.")

    def test_clean_markdown_fence_passes(self):
        """Fenced block without secrets should pass."""
        clean_fence = "```json\n{\n  \"name\": \"value\",\n  \"count\": 42\n}\n```"
        # 4 KV pairs but no secret keywords -> should pass (4 <= threshold 5)
        scrub_secrets(clean_fence)

    # --- Plain-text secret pattern rejects ---

    def test_api_key_pattern(self):
        with pytest.raises(ValueError, match="secret"):
            scrub_secrets("api_key: sk-abcdef1234567890")

    def test_authorization_bearer(self):
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdefghijklmnop"
        with pytest.raises(ValueError, match="secret"):
            scrub_secrets(f"Authorization: Bearer {token}")

    def test_bearer_token_pattern(self):
        token = "aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"
        with pytest.raises(ValueError, match="secret"):
            scrub_secrets(f"bearer {token}")

    def test_sk_prefix_pattern(self):
        """sk- followed by 20+ alphanumeric chars must be caught."""
        with pytest.raises(ValueError, match="secret"):
            # "sk-" + 24 chars (>=20 required by the pattern)
            scrub_secrets("my key is sk-AbcXyz1234567890ABCDEF")

    def test_password_pattern(self):
        with pytest.raises(ValueError, match="secret"):
            scrub_secrets("password = super_secret_pass")

    def test_token_pattern(self):
        with pytest.raises(ValueError, match="secret"):
            scrub_secrets("token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef")

    # --- Size guard ---

    def test_oversized_just_at_limit_passes(self):
        """Exactly at the 2 KB limit should pass."""
        exactly = "x" * _SCRUB_MAX_RENDERED_BYTES
        scrub_secrets(exactly)

    def test_oversized_over_limit_raises(self):
        """One byte over the limit raises ValueError."""
        over = "a" * (_SCRUB_MAX_RENDERED_BYTES + 1)
        with pytest.raises(ValueError, match="bytes"):
            scrub_secrets(over)

    # --- Markdown fence (large block with secret keyword) ---

    def test_markdown_fence_large_block_raises(self):
        """Fenced block with >5 KV pairs + secret keyword -> fence rule catches it.

        Key obfuscation avoids plain-text patterns so the fence-specific scan
        is the one that fires.
        """
        # 7 KV pairs, value contains "secret" embedded mid-text
        large_block = (
            "```yaml\n"
            "k1: a\n"
            "k2: b\n"
            "k3: c\n"
            "k4: d\n"
            "k5: e\n"
            "k6: contains my secret value\n"  # "secret" embedded in value text
            "k7: g\n"
            "```"
        )
        # 7 > 5 threshold + "secret" keyword -> fence rule triggers
        with pytest.raises(ValueError, match="Markdown fenced block"):
            scrub_secrets(large_block)

    # --- Context label ---

    def test_context_label_appears_in_error(self):
        with pytest.raises(ValueError, match=r"\[cto\]"):
            scrub_secrets("api_key: sk-leaked", context="cto")

    # --- Sanity ---

    def test_secrets_patterns_list_length(self):
        """Sanity: _SECRET_PATTERNS has at least 5 patterns."""
        assert len(_SECRET_PATTERNS) >= 5


# ===================================================================
# Backward compat: existing tests still pass
# ===================================================================


class TestBackwardCompat:
    """Ensure Phase 4 changes don't break existing behavior."""

    def test_validate_config_unchanged(self):
        assert validate_config(_make_config()) == []
        assert len(validate_config(_make_config(company_name=""))) > 0

    def test_agent_roles_count(self):
        assert len(AGENT_ROLES) == 8

    def test_generate_no_key_12_files(self):
        cfg = _make_config()
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("ANTHROPIC_API_KEY", "LLM_API_KEY")}
        with patch.dict(os.environ, clean_env, clear=True):
            files = generate_config_files(cfg)
        assert len(files) == 12

    def test_generate_agent_file_content(self):
        cfg = _make_config(company_name="CompatCo", primary_language="en")
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("ANTHROPIC_API_KEY", "LLM_API_KEY")}
        with patch.dict(os.environ, clean_env, clear=True):
            files = generate_config_files(cfg)
        for role in AGENT_ROLES:
            assert "CompatCo" in files[f".mekong/agents/{role}.md"]
            assert "en" in files[f".mekong/agents/{role}.md"]

    def test_generate_llm_render_none_auto_detect(self):
        """llm_render=None with no key set still uses static path."""
        cfg = _make_config()
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("ANTHROPIC_API_KEY", "LLM_API_KEY")}
        with patch.dict(os.environ, clean_env, clear=True):
            files = generate_config_files(cfg, llm_render=None)
        assert len(files) == 12
        for role in AGENT_ROLES:
            assert "TestCorp" in files[f".mekong/agents/{role}.md"]
