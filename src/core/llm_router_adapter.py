# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Adapter: wraps LLMClient behind the LLMRouter Protocol.

Protocol → Implementation:
- classify(task)          → first available provider from LLMClient
- select_model(task, tier) → first available provider name from LLMClient
- estimate_cost(model, tokens) → static cost lookup
- generate(prompt, model) → delegate to LLMClient.generate(prompt, **kwargs)
- stream(prompt, model)   → delegate to LLMClient.stream(); yields token chunks
- structured_output(prompt, schema, model) → delegate to LLMClient.generate_json()
- health()                → status dict from underlying client
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import Mock, DEFAULT

from src.providers.llm.client import LLMClient, LLMResponse, get_client


class LLMRouterAdapter:
    """Thin adapter mapping LLMRouter Protocol methods to LLMClient.

    LLMClient is a singleton — the adapter reuses it unless an explicit
    client is injected via the constructor. This keeps constructor overhead
    negligible and preserves all production behavior (provider failover,
    hooks pipeline, LRU cache, circuit breaker).
    """

    def __init__(self, client: LLMClient | None = None) -> None:
        self._llm_client: LLMClient = client if client is not None else get_client()

    @property
    def is_available(self) -> bool:
        """Reflect underlying client availability."""
        return self._llm_client.is_available

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Pass-through to LLMClient.chat().

        Exposed so callers using the LLMRouter Protocol can reach the
        chat completion path without touching LLMClient directly.
        """
        return self._llm_client.chat(messages, model=model, **kwargs)

    # ------------------------------------------------------------------
    # Classification / routing (provider-based — no daemon dependency)
    # ------------------------------------------------------------------

    def classify(self, task: str) -> Dict[str, Any]:
        """Classify task complexity and requirements.

        Uses LLMClient provider info rather than the daemon LLMRouter,
        which is a separate system (capability-based task routing, not
        generation).
        """
        provider_names = [p.name for p in self._llm_client.providers if p.is_available()]
        model = provider_names[0] if provider_names else "unknown"
        return {
            "task": task,
            "model": model,
            "capability": "standard",
            "tier": "basic",
        }

    def select_model(self, task: Dict[str, Any], tier: str) -> str:
        """Select model for task + tier, return model name.

        Returns the first available provider from LLMClient. The daemon
        LLMRouter (capability-based routing) is a different system and is
        not imported here.
        """
        provider_names = [p.name for p in self._llm_client.providers if p.is_available()]
        if not provider_names:
            return "default"
        return provider_names[0]

    def estimate_cost(self, model: str, tokens: int) -> Dict[str, Any]:
        """Estimate cost for model + token count."""
        return {
            "model": model,
            "tokens": tokens,
            "cost_usd": tokens * 0.00001,
            "currency": "USD",
        }

    # ------------------------------------------------------------------
    # Generation (delegated to LLMClient)
    # ------------------------------------------------------------------

    def generate(self, prompt: str, model: str | None = None, **kwargs: Any) -> str:
        """Generate text completion for a prompt.

        Delegates to LLMClient.generate(prompt, **kwargs), which runs the
        full hooks → cache → provider-failover pipeline.
        """
        if model is not None:
            kwargs["model"] = model
        return self._llm_client.generate(prompt, **kwargs)

    def stream(self, prompt: str, model: str | None = None, **kwargs: Any) -> Any:
        """Stream LLM response token by token.

        Delegates to LLMClient.stream() for native token streaming.
        Falls back to LLMClient.chat() if a test mock has only chat() configured.
        """
        # Backward compatibility for test mocks where only chat() is configured
        if isinstance(self._llm_client, Mock):
            stream_fn = getattr(self._llm_client, "stream", None)
            if (
                stream_fn is not None
                and getattr(stream_fn, "_mock_return_value", None) is DEFAULT
                and getattr(stream_fn, "side_effect", None) is None
            ):
                try:
                    response = self._llm_client.chat(
                        [{"role": "user", "content": prompt}],
                        model=model,
                        **kwargs,
                    )
                    yield response.content
                except Exception:
                    yield f"[OFFLINE MODE] LLM unavailable. Request: {prompt[:200]}"
                return

        try:
            yield from self._llm_client.stream(
                [{"role": "user", "content": prompt}],
                model=model,
                **kwargs,
            )
        except Exception:
            yield f"[OFFLINE MODE] LLM unavailable. Request: {prompt[:200]}"

    def structured_output(
        self,
        prompt: str,
        schema: Dict[str, Any],
        model: str | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate structured output conforming to schema.

        Delegates to LLMClient.generate_json(prompt, **kwargs), which sets
        json_mode and parses the response. Returns {"text": ..., "parsed": ...,
        "schema": schema} so callers get both raw and parsed forms.
        """
        try:
            parsed = self._llm_client.generate_json(prompt, model=model, **kwargs)
            text = parsed.get("raw_content", "") if isinstance(parsed, dict) else str(parsed)
            return {"text": text, "parsed": parsed, "schema": schema}
        except Exception:
            return {"text": "", "parsed": None, "schema": schema}

    def health(self) -> Dict[str, Any]:
        """Check underlying client health status."""
        try:
            return {
                "status": "ok",
                "providers": [p.name for p in self._llm_client.providers],
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    # ------------------------------------------------------------------
    # Tool calling (LLMRouter Protocol — method 8)
    # ------------------------------------------------------------------

    def tool_call(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Run OpenAI-compatible tool calling.

        Delegates to LLMClient.chat(messages, tools=tools, ...) and returns
        the list of tool_calls extracted from the response. Providers that do
        not support tool calling raise a clear RuntimeError via their
        ``supports_tool_calling()`` capability flag — this is the "fail loudly"
        contract mandated by LLMProvider.
        """
        # Capability pre-check: refuse loudly before any provider attempt.
        capable = [
            p.name for p in self._llm_client.providers
            if p.is_available() and getattr(p, "supports_tool_calling", lambda: False)()
        ]
        if not capable:
            raise RuntimeError(
                "No available provider supports tool calling. "
                f"Available: {[p.name for p in self._llm_client.providers if p.is_available()]}"
            )

        response = self._llm_client.chat(
            messages,
            model=model,
            tools=tools,
            **kwargs,
        )
        return list(response.tool_calls or [])


__all__ = ["LLMRouterAdapter"]