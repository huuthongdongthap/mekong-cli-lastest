# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""LLMProviderPort — provider-level port for LLM adapters (Task 2, SC#5).

Two distinct layers in Mekong Core:

- ``src/core/protocols.py::LLMRouter`` — ROUTER level: classify/select_model/
  estimate_cost/generate/stream/structured_output/tool_call/health. It routes
  AMONG providers.
- ``src/core/ports/llm.py::LLMProviderPort`` (this module) — PROVIDER level:
  the single-provider contract each adapter implements. The router selects
  between implementations of this port. Two layers, deliberately separate.

Structural typing only (runtime_checkable Protocol) — no implementation
imports here, no HTTP, no SDK. Adapters live in ``src/core/adapters/llm/``
and wrap the canonical routing logic in ``src/providers/llm/client.py``
(there is exactly ONE HTTP client in the repo; adapters never add a second).

Error semantics (fail-loud contract, mirrors x402 payment provider):

- Missing required config with no transport injected -> ``LLMConfigError``
  (never default-allow, never silent fake).
- Method unsupported by a specific provider -> ``LLMNotSupportedError``
  naming the capability flag that is off.
"""

from __future__ import annotations

from typing import Any, Iterator, Protocol, runtime_checkable


class LLMConfigError(ValueError):
    """Required provider config missing and no transport injected (fail-loud)."""


class LLMNotSupportedError(NotImplementedError):
    """Provider does not support the requested capability — never silent fake."""


@runtime_checkable
class LLMProviderPort(Protocol):
    """Provider-level LLM contract (structural, no inheritance required)."""

    def generate(
        self, prompt: str, *, model: str | None = None, **kwargs: Any
    ) -> str:
        """Text completion for a prompt. Returns response content."""
        ...

    def stream(
        self, prompt: str, *, model: str | None = None, **kwargs: Any
    ) -> Iterator[str]:
        """Yield response chunks. MUST return an iterator (not a full str)."""
        ...

    def structured_output(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """JSON-constrained output parsed to a dict, guided by ``schema``."""
        ...

    def tool_call(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """OpenAI-compatible tool calling (``tools`` schema list).

        Semantics align with ``protocols.LLMRouter.tool_call`` (see
        llm_router_adapter.py:161): capability-flag pre-check, then chat with
        ``tools=``; returns the provider's ``tool_calls`` list. Adapters whose
        provider has tool calling disabled raise ``LLMNotSupportedError``.
        """
        ...

    def health(self) -> dict[str, Any]:
        """Status dict. Canonical shape: ``{"status": str, "model": str, ...}``."""
        ...


__all__ = ["LLMProviderPort", "LLMConfigError", "LLMNotSupportedError"]
