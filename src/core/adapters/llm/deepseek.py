"""DeepSeek preset adapter (thin override — see base.py for shared logic)."""

from __future__ import annotations

from src.core.adapters.llm.base import ConfigurableLLMAdapter


class DeepSeekLLMAdapter(ConfigurableLLMAdapter):
    """DeepSeek preset: api.deepseek.com compatible endpoint (DEEPSEEK_API_KEY)."""

    name = "deepseek"
    default_model = "deepseek-chat"
    default_base_url = "https://api.deepseek.com"
    env_key = "DEEPSEEK_API_KEY"
    env_base_url = "LLM_BASE_URL"

    def __init__(self, transport=None, config=None, **kwargs):
        super().__init__(transport=transport, config=config, **kwargs)