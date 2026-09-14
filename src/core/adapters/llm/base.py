# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""ConfigurableLLMAdapter — transport + base class, shared by four presets.

suntzu ROUND-1 finding #4: four separate adapters would share >80% logic.
Resolution: this single base + thin preset subclasses
(claude/qwen/deepseek/local, each ≤30 LOC, overriding only preset name,
default model, env-var names and default endpoint). Method implementations
(generate/stream/structured_output/tool_call/health) live in
``llm_methods.py`` so this file stays under the LOC limit; the presets
subclass this base and inherit them all.

It wraps the canonical routing stack — there is exactly ONE HTTP client in
the repo (``src/providers/llm/client.py`` / ``OpenAICompatibleProvider``);
this adapter reuses it and adds no second. Two injection modes, both
hermetic-testable:

1. ``transport`` — callable ``chat(messages, model, temperature,
   max_tokens, json_mode, tools) -> LLMResponse`` (an
   ``OpenAICompatibleProvider`` in production, a fake in tests). Injected
   transport = zero implicit network.
2. ``config`` — explicit ``{"base_url", "api_key", "model", "timeout"}``;
   falls back to provider env vars, then to the preset's default endpoint.
   Nothing configured and no transport → ``LLMConfigError`` at call time
   (fail-loud, never default-allow, never silent fake).
"""

from __future__ import annotations

import logging
from typing import Any


from .llm_http import ChatTransport, build_compatible_client, resolve_config
from .llm_methods import LLMMethodImplementations

logger = logging.getLogger(__name__)


class ConfigurableLLMAdapter(LLMMethodImplementations):
    """Transport + config resolution for the four preset adapters."""

    name: str = "llm"
    default_model: str = ""
    env_key: str = ""
    env_base_url: str = ""

    def __init__(
        self,
        transport: ChatTransport | None = None,
        config: dict[str, Any] | None = None,
        *,
        supports_tool_calling: bool = True,
        supports_streaming: bool = True,
        supports_structured_output: bool = True,
    ) -> None:
        self._transport = transport
        self._config: dict[str, Any] = dict(config or {})
        self._implicit_transport: ChatTransport | None = None
        self.supports_tool_calling = supports_tool_calling
        self.supports_streaming = supports_streaming
        self.supports_structured_output = supports_structured_output

    # ------------------------------------------------------------------
    # Transport resolution (fail-loud)
    # ------------------------------------------------------------------

    def _resolve_transport(self) -> ChatTransport:
        if self._transport is not None:
            return self._transport
        if self._implicit_transport is None:
            self._implicit_transport = self._build_transport_from_config()
        return self._implicit_transport

    def _build_transport_from_config(self) -> ChatTransport:
        """Build the transport from explicit config or env (fail-loud)."""
        base_url, api_key, model = resolve_config(
            self._config, name=self.name, default_model=self.default_model,
            env_key=self.env_key, env_base_url=self.env_base_url,
        )
        return build_compatible_client(
            name=self.name, base_url=base_url, api_key=api_key, model=model,
            timeout=int(self._config.get("timeout", 60)),
        )

    @property
    def model(self) -> str:
        return self._config.get("model") or self.default_model or "unknown"

    def _chat(self, messages, model, **kwargs):
        """Resolve transport (callable or .chat()-exposing object) and call.

        Callables (test fakes, OpenAICompatibleProvider wrapped in a closure)
        are invoked directly; provider objects expose .chat(). This preserves
        both injection modes without a second HTTP client."""
        transport = self._resolve_transport()
        chat_fn = transport if callable(transport) else transport.chat
        return chat_fn(
            messages,
            model=model or self.default_model or "",
            temperature=kwargs.pop("temperature", 0.7),
            max_tokens=kwargs.pop("max_tokens", 2048),
            json_mode=kwargs.pop("json_mode", False),
            tools=kwargs.pop("tools", None),
            **kwargs,
        )


__all__ = ["ConfigurableLLMAdapter", "ChatTransport"]