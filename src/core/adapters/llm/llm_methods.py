# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Method implementations shared by every LLM provider preset.

Split out of base.py so the transport + class skeleton stays under the file
LOC limit. Presets subclass ``ConfigurableLLMAdapter`` (which extends this
mixin) and inherit generate/stream/structured_output/tool_call/health
without re-implementing any of them.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from src.core.ports.llm import LLMNotSupportedError

logger = logging.getLogger(__name__)


class LLMMethodImplementations:
    """Mixin with the five LLMProviderPort method implementations.

    Subclasses must provide ``self.name``, ``self.default_model``,
    ``self.supports_*`` flags, ``self._resolve_transport()`` and
    ``self._chat()``, plus ``self._config`` and ``self._transport``.
    """

    name: str
    default_model: str
    env_base_url: str
    supports_tool_calling: bool
    supports_streaming: bool
    supports_structured_output: bool
    _transport: Any
    _config: dict[str, Any]

    def _resolve_transport(self):  # pragma: no cover - subclass responsibility
        raise NotImplementedError

    def _chat(self, messages, model, **kwargs):  # pragma: no cover
        raise NotImplementedError

    @property
    def model(self) -> str:  # pragma: no cover - subclass responsibility
        return ""

    # ------------------------------------------------------------------
    # LLMProviderPort methods
    # ------------------------------------------------------------------

    def generate(
        self, prompt: str, *, model: str | None = None, **kwargs: Any
    ) -> str:
        response = self._chat([{"role": "user", "content": prompt}], model, **kwargs)
        return response.content

    def stream(
        self, prompt: str, *, model: str | None = None, **kwargs: Any
    ):
        """Yield response chunks. No native streaming in the transport, so
        the completed response is yielded as one chunk — identical to
        LLMRouterAdapter.stream semantics (DUPLICATION_MAP #5).

        The capability flag is checked BEFORE the generator body runs, so
        calling stream() with streaming disabled raises immediately instead
        of silently succeeding until first iteration."""
        if not self.supports_streaming:
            raise LLMNotSupportedError(
                f"{self.name}: supports_streaming=False — streaming disabled"
            )
        response = self._chat([{"role": "user", "content": prompt}], model, **kwargs)
        yield response.content

    def structured_output(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self.supports_structured_output:
            raise LLMNotSupportedError(
                f"{self.name}: supports_structured_output=False — "
                "structured output disabled"
            )
        response = self._chat(
            [{"role": "user", "content": prompt}],
            model,
            json_mode=True,
            **kwargs,
        )
        try:
            parsed = json.loads(response.content)
        except json.JSONDecodeError:
            logger.warning("[%s] structured_output: non-JSON response", self.name)
            return {"raw_content": response.content, "schema": schema}
        return {"parsed": parsed, "schema": schema}

    def tool_call(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """OpenAI-compatible tool calling; semantics aligned with
        protocols.LLMRouter.tool_call (capability flag first, then chat with
        tools=, return the response's tool_calls list)."""
        if not self.supports_tool_calling:
            raise LLMNotSupportedError(
                f"{self.name}: supports_tool_calling=False — tool calling disabled"
            )
        response = self._chat(messages, model, tools=tools, **kwargs)
        return list(response.tool_calls or [])

    def health(self) -> dict[str, Any]:
        """Status dict — canonical shape {"status": str, "model": str, ...}."""
        return {
            "status": "ok",
            "provider": self.name,
            "model": self.model,
            "configured": bool(
                self._transport is not None
                or self._config.get("base_url")
                or os.getenv(self.env_base_url, "")
            ),
            "capabilities": {
                "tool_calling": self.supports_tool_calling,
                "streaming": self.supports_streaming,
                "structured_output": self.supports_structured_output,
            },
        }


__all__ = ["LLMMethodImplementations"]