# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""LLM adapter package — provider presets behind LLMProviderPort.

Canonical HTTP client lives in ``src/providers/llm/client.py`` (622 lines,
multi-provider failover + OpenRouter-compatible). This package is a thin
adapter layer on top of it: each preset (claude/qwen/deepseek/local) is a
subclass of ``ConfigurableLLMAdapter`` (base.py) that only overrides the
preset name, default model and env-var names. No second HTTP client exists
here.

Two entry points:

- ``build_llm_provider(name, config)`` — factory, one entry point, four presets.
- Direct: ``from src.core.adapters.llm import ClaudeLLMAdapter``.

Backward-compat: this module also re-exports the canonical client symbols
(``LLMClient``, ``LLMResponse``, ``get_client``) so legacy importers that do
``from src.core.adapters.llm import *`` keep resolving — the canonical
implementation lives in ``src.providers.llm`` (DEPRECATION.md resolution
target); this re-export is a thin shim, not a second implementation.
"""

from __future__ import annotations

from typing import Any

from src.core.adapters.llm.base import ConfigurableLLMAdapter
from src.core.adapters.llm.claude import ClaudeLLMAdapter
from src.core.adapters.llm.deepseek import DeepSeekLLMAdapter
from src.core.adapters.llm.local import LocalLLMAdapter
from src.core.adapters.llm.qwen import QwenLLMAdapter
from src.core.ports.llm import LLMConfigError, LLMProviderPort

# Preset registry — single source of truth for adapter name -> class.
_PRESETS: dict[str, type[ConfigurableLLMAdapter]] = {
    "claude": ClaudeLLMAdapter,
    "qwen": QwenLLMAdapter,
    "deepseek": DeepSeekLLMAdapter,
    "local": LocalLLMAdapter,
}


def get_llm_adapter_class(name: str) -> type[ConfigurableLLMAdapter] | None:
    return _PRESETS.get(name)


def build_llm_provider(name: str, config: dict[str, Any] | None = None):
    """Factory: one entry point, four provider presets (DRY review fix).

    ``name`` ∈ {"claude", "qwen", "deepseek", "local"} — returns the matching
    preset adapter. Unknown name raises ``LLMConfigError`` (fail-loud).
    """
    cls = _PRESETS.get(name)
    if cls is None:
        raise LLMConfigError(
            f"unknown LLM provider preset: {name!r} "
            "(expected one of: claude, qwen, deepseek, local)"
        )
    return cls(config=config)


def build(name: str, config: dict[str, Any] | None = None) -> LLMProviderPort:
    """Build a preset adapter by name (alias for ``build_llm_provider``)."""
    return build_llm_provider(name, config)


__all__ = [
    "ConfigurableLLMAdapter",
    "ClaudeLLMAdapter",
    "DeepSeekLLMAdapter",
    "LocalLLMAdapter",
    "QwenLLMAdapter",
    "LLMProviderPort",
    "build",
    "build_llm_provider",
    "get_llm_adapter_class",
]