"""Claude preset adapter (thin override — see base.py for shared logic)."""

from __future__ import annotations

from src.core.adapters.llm.base import ConfigurableLLMAdapter


class ClaudeLLMAdapter(ConfigurableLLMAdapter):
    """Claude preset: Anthropic-compatible endpoint via LLM_BASE_URL/LLM_API_KEY
    (or OpenRouter when LLM_BASE_URL points there)."""

    name = "claude"
    default_model = "claude-sonnet-4-6-20250514"
    default_base_url = "https://api.anthropic.com/v1"
    env_key = "LLM_API_KEY"
    env_base_url = "LLM_BASE_URL"

    def __init__(self, transport=None, config=None, **kwargs):
        super().__init__(transport=transport, config=config, **kwargs)