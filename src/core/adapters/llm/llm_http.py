# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""HTTP-transport construction for the LLM adapter layer.

Split out of base.py so the adapter class stays under the file-LOC limit.
This module is the ONLY place in ``src.core.adapters.llm`` that touches the
canonical HTTP client — one client, no second implementation.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Union

from src.core.ports.llm import LLMConfigError
from src.core.providers import LLMProvider, LLMResponse, OpenAICompatibleProvider

# The adapter accepts two interchangeable transport shapes (see base.py
# `_chat`): a bare callable invoked directly, or an LLMProvider instance
# whose `.chat()` is used. The alias is the union — otherwise the canonical
# OpenAICompatibleProvider would not satisfy it (pyright reportArgumentType).
ChatTransport = Union[Callable[..., LLMResponse], "LLMProvider"]


def build_compatible_client(
    *,
    name: str,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int = 60,
) -> OpenAICompatibleProvider:
    """Construct the canonical OpenAICompatibleProvider with fail-loud checks.

    A blank base_url or api_key raises LLMConfigError — never default-allow,
    never fabricate an endpoint. Resolution order mirrors
    ``src/providers/llm/client.py`` env detection.
    """
    if not base_url:
        raise LLMConfigError(
            f"{name}: missing base_url — pass config "
            f'{{"base_url": ..., "api_key": ...}} or set env {name}_BASE_URL '
            f"(no transport injected + no config = fail-loud, no default-allow)"
        )
    if not api_key:
        raise LLMConfigError(
            f"{name}: missing api_key — pass config or set env {name}_API_KEY"
        )
    return OpenAICompatibleProvider(
        base_url=base_url,
        api_key=api_key,
        model=model,
        provider_name=name,
        timeout=timeout,
    )


def resolve_config(cfg: dict[str, Any], *, name: str, default_model: str,
                   env_key: str, env_base_url: str) -> tuple[str, str, str]:
    """Return (base_url, api_key, model) from explicit config or env.

    Mirrors the env-detection order in ``src/providers/llm/client.py``.
    """
    base_url = cfg.get("base_url") or os.getenv(env_base_url, "")
    api_key = cfg.get("api_key") or os.getenv(env_key, "")
    model = cfg.get("model") or default_model
    return base_url, api_key, model


__all__ = ["ChatTransport", "LLMResponse", "build_compatible_client", "resolve_config"]