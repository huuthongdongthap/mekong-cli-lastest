"""Qwen preset adapter (thin override — see base.py for shared logic)."""

from __future__ import annotations

from src.core.adapters.llm.base import ConfigurableLLMAdapter


class QwenLLMAdapter(ConfigurableLLMAdapter):
    """Qwen preset: DashScope-compatible endpoint (DASHSCOPE_API_KEY)."""

    name = "qwen"
    default_model = "qwen3-coder-plus"
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    env_key = "DASHSCOPE_API_KEY"
    env_base_url = "LLM_BASE_URL"

    def __init__(self, transport=None, config=None, **kwargs):
        super().__init__(transport=transport, config=config, **kwargs)