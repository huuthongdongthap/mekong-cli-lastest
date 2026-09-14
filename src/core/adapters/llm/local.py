"""Local preset adapter (thin override — see base.py for shared logic)."""

from __future__ import annotations

import os

from src.core.adapters.llm.base import ConfigurableLLMAdapter


class LocalLLMAdapter(ConfigurableLLMAdapter):
    """Local preset: Ollama/MLX endpoint (OLLAMA_BASE_URL / LOCAL_LLM_URL),
    offline-capable — no api_key required, base_url is the only gate."""

    name = "local"
    default_model = "qwen3.6-35b"
    env_key = "OLLAMA_API_KEY"
    env_base_url = "OLLAMA_BASE_URL"

    def __init__(self, transport=None, config=None, **kwargs):
        super().__init__(transport=transport, config=config, **kwargs)

    def _build_transport_from_config(self):
        # Local endpoints run without auth by default; fall back to
        # LOCAL_LLM_URL when OLLAMA_BASE_URL is unset (mirror client.py:302-325).
        if not self._config.get("base_url") and not os.getenv(self.env_base_url, ""):
            local_url = os.getenv("LOCAL_LLM_URL", "")
            if local_url:
                self._config = {**self._config, "base_url": local_url}
        return super()._build_transport_from_config()

    def health(self) -> dict:
        info = super().health()
        info["offline_capable"] = True
        return info