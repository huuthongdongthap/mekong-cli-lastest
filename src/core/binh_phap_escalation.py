# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Binh Phap Escalation Routing — Dual-path: ZuneF (team) vs Anthropic (dev).

TWO distinct credential scopes:
  • ZUNEF path  → our token, ZuneF gateway, usage settled centrally
  • ANTHROPIC   → dev's own API key, direct Anthropic call

Env vars in priority order:
  Strategic (Fable 5) : ZUNEF_FABLE_BASE_URL / ZUNEF_FABLE_MODEL → FABLE_BASE_URL / FABLE_MODEL → ANTHROPIC_BASE_URL / FABLE_MODEL_DEFAULT
  Default  (Opus 4.8) : ZUNEF_OPUS_BASE_URL / ZUNEF_OPUS_MODEL  → OPUS_BASE_URL / OPUS_MODEL  → ANTHROPIC_BASE_URL / OPUS_MODEL_DEFAULT
  Shared API key      : ZUNEF_API_KEY > ANTHROPIC_API_KEY
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ── Defaults (fallback when nothing is set) ──────────────────────────────
FABLE_MODEL = "claude-fable-5"
OPUS_MODEL = "claude-opus-4-8"
ANTHROPIC_DIRECT_BASE_URL = "https://api.anthropic.com/v1"


def _first_env(*keys: str, default: str) -> str:
    """Return the first set env var, or default."""
    for k in keys:
        v = os.getenv(k)
        if v:
            return v
    return default


def _resolve(slug: str, model: str) -> dict[str, str]:
    """Build provider config for one model slot."""
    base_url = _first_env(
        f"ZUNEF_{slug}_BASE_URL",
        f"{slug}_BASE_URL",
        "ANTHROPIC_BASE_URL",
        default=ANTHROPIC_DIRECT_BASE_URL,
    )
    resolved_model = _first_env(
        f"ZUNEF_{slug}_MODEL",
        f"{slug}_MODEL",
        default=model,
    )
    provider_name = f"zunef-{slug.lower()}" if any(
        os.getenv(k) for k in (f"ZUNEF_{slug}_BASE_URL", f"ZUNEF_{slug}_MODEL")
    ) else f"anthropic-{slug.lower()}"

    return {
        "base_url": base_url,
        "model": resolved_model,
        "provider_name": provider_name,
        "api_key_env": "ZUNEF_API_KEY" if "ZUNEF_" in base_url or any(
            os.getenv(k) for k in (f"ZUNEF_{slug}_BASE_URL", f"ZUNEF_{slug}_MODEL")
        ) else "ANTHROPIC_API_KEY",
    }


def resolve_llm_provider(escalation_level: str) -> dict[str, str]:
    """Route escalation level to the correct model.

    Escalation levels map to model tiers:
    - "strategic" / "cloud_opus" / "AUTONOMOUS"  → Opus (strongest, for strategic work)
    - "cloud_sonnet" / "standard"                 → Sonnet (balanced)
    - "local_mlx" / "tactical"                    → Fable/Haiku (fast, local)

    ZuneF env vars take priority; falls back to plain Anthropic.
    """
    escalation_lower = escalation_level.lower()
    if escalation_lower in ("strategic", "cloud_opus", "autonomous"):
        slug, model = "OPUS", OPUS_MODEL
    elif escalation_lower in ("cloud_sonnet", "standard"):
        slug, model = "SONNET", "claude-sonnet-4-6"
    else:
        slug, model = "FABLE", FABLE_MODEL

    return _resolve(slug, model)


ESCALATION_PROVIDERS: dict[str, dict[str, str]] = {
    "local_mlx": resolve_llm_provider("local_mlx"),
    "cloud_sonnet": resolve_llm_provider("cloud_sonnet"),
    "cloud_opus": resolve_llm_provider("cloud_opus"),
}


def create_provider_for_level(escalation_level: str) -> Any:
    """Create LLMProvider for the given level."""
    try:
        from .providers import OpenAICompatibleProvider
    except ImportError:
        return None

    config = resolve_llm_provider(escalation_level)
    api_key = os.getenv(config.get("api_key_env", "ANTHROPIC_API_KEY"), "")
    if not api_key:
        logger.warning(
            "Missing API key (%s); provider unavailable for %s",
            config.get("api_key_env"), escalation_level,
        )
        return None

    return OpenAICompatibleProvider(
        base_url=config["base_url"],
        api_key=api_key,
        model=config["model"],
        provider_name=config["provider_name"],
        timeout=120,
    )
