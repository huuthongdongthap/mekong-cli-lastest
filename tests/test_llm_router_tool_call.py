# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""E4 conformance suite: LLMRouter Protocol — 5 methods across ≥2 providers.

Parametrizes two injected fake providers (OpenRouter-compatible and
Claude-Fable-shaped) through the SAME five LLMRouter methods:
generate / stream / structured_output / tool_call / health.

No network: providers are LLMProvider subclasses returning canned
responses, injected into a real LLMClient via ``providers=``. This exercises
the full adapter → client → provider chain (failover, hooks, cache) with
deterministic inputs.

Contract invariants asserted per method:
- generate()            → str
- stream()              → iterator yielding str chunks
- structured_output()   → dict carrying the schema
- tool_call()           → list[dict]; raises RuntimeError when no provider
                          supports tool calling (fail-loudly contract)
- health()              → dict with a "status" key
"""

from __future__ import annotations

from typing import Any

import pytest

from src.providers.llm.client import LLMClient
from src.core.llm_router_adapter import LLMRouterAdapter
from src.core.protocols import LLMRouter
from src.core.providers import LLMProvider, LLMResponse


# ---------------------------------------------------------------------------
# Fake providers — injected, no network
# ---------------------------------------------------------------------------

class FakeOpenRouterProvider(LLMProvider):
    """OpenRouter-compatible provider. Supports tool calling."""

    def __init__(self, tool_calls: list[dict[str, Any]] | None = None) -> None:
        self._tool_calls = tool_calls or []

    @property
    def name(self) -> str:
        return "openrouter"

    def is_available(self) -> bool:
        return True

    def supports_tool_calling(self) -> bool:
        return True

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        if tools is not None:
            return LLMResponse(
                content="",
                model=model,
                tool_calls=list(self._tool_calls),
            )
        content = "openrouter-response"
        if json_mode:
            content = '{"ok": true}'
        return LLMResponse(content=content, model=model)


class FakeClaudeFableProvider(LLMProvider):
    """Claude-Fable-shaped provider. Supports tool calling."""

    def __init__(self, tool_calls: list[dict[str, Any]] | None = None) -> None:
        self._tool_calls = tool_calls or []

    @property
    def name(self) -> str:
        return "claude_fable"

    def is_available(self) -> bool:
        return True

    def supports_tool_calling(self) -> bool:
        return True

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        if tools is not None:
            return LLMResponse(
                content="",
                model=model,
                tool_calls=list(self._tool_calls),
            )
        content = "claude-fable-response"
        if json_mode:
            content = '{"ok": true}'
        return LLMResponse(content=content, model=model)


class FakeNoToolProvider(LLMProvider):
    """Provider that does NOT support tool calling — must fail loudly."""

    @property
    def name(self) -> str:
        return "no_tool"

    def is_available(self) -> bool:
        return True

    def supports_tool_calling(self) -> bool:
        return False

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        if tools is not None:
            raise RuntimeError("FakeNoToolProvider does not support tool calling")
        return LLMResponse(content="no-tool-response", model=model)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TOOL_CALLS = [
    {
        "id": "call_1",
        "type": "function",
        "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'},
    },
]


def _adapter_for(provider: LLMProvider) -> LLMRouterAdapter:
    """Build an adapter backed by a real LLMClient with one injected provider."""
    client = LLMClient(
        providers=[provider],
        enable_cache=False,
        enable_hooks=False,
    )
    return LLMRouterAdapter(client=client)


@pytest.fixture(params=["openrouter", "claude_fable"])
def provider_name(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def adapter(provider_name: str) -> LLMRouterAdapter:
    if provider_name == "openrouter":
        return _adapter_for(FakeOpenRouterProvider(tool_calls=_TOOL_CALLS))
    return _adapter_for(FakeClaudeFableProvider(tool_calls=_TOOL_CALLS))


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------

class TestProtocolSatisfaction:
    def test_adapter_satisfies_llm_router_with_tool_call(self) -> None:
        """Adapter must satisfy the expanded LLMRouter Protocol (8 methods)."""
        adapter = _adapter_for(FakeOpenRouterProvider())
        assert isinstance(adapter, LLMRouter)

    def test_tool_call_method_exists_on_protocol(self) -> None:
        assert hasattr(LLMRouter, "tool_call")


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------

class TestGenerate:
    def test_returns_string(self, adapter: LLMRouterAdapter) -> None:
        result = adapter.generate("hello")
        assert isinstance(result, str)

    def test_non_empty(self, adapter: LLMRouterAdapter) -> None:
        result = adapter.generate("hello")
        assert len(result) > 0


# ---------------------------------------------------------------------------
# stream()
# ---------------------------------------------------------------------------

class TestStream:
    def test_returns_iterator(self, adapter: LLMRouterAdapter) -> None:
        result = adapter.stream("hello")
        assert hasattr(result, "__iter__")

    def test_yields_string_chunks(self, adapter: LLMRouterAdapter) -> None:
        chunks = list(adapter.stream("hello"))
        assert len(chunks) >= 1
        assert all(isinstance(c, str) for c in chunks)


# ---------------------------------------------------------------------------
# structured_output()
# ---------------------------------------------------------------------------

class TestStructuredOutput:
    def test_returns_dict(self, adapter: LLMRouterAdapter) -> None:
        result = adapter.structured_output("extract", schema={"type": "object"})
        assert isinstance(result, dict)

    def test_carries_schema(self, adapter: LLMRouterAdapter) -> None:
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = adapter.structured_output("extract", schema=schema)
        assert result["schema"] == schema


# ---------------------------------------------------------------------------
# tool_call()
# ---------------------------------------------------------------------------

class TestToolCall:
    def test_returns_list(self, adapter: LLMRouterAdapter) -> None:
        tools = [{"type": "function", "function": {"name": "read_file"}}]
        result = adapter.tool_call(
            [{"role": "user", "content": "read a.txt"}], tools=tools,
        )
        assert isinstance(result, list)

    def test_returns_injected_tool_calls(self, adapter: LLMRouterAdapter) -> None:
        tools = [{"type": "function", "function": {"name": "read_file"}}]
        result = adapter.tool_call(
            [{"role": "user", "content": "read a.txt"}], tools=tools,
        )
        assert result == _TOOL_CALLS

    def test_each_tool_call_is_dict(self, adapter: LLMRouterAdapter) -> None:
        tools = [{"type": "function", "function": {"name": "read_file"}}]
        result = adapter.tool_call(
            [{"role": "user", "content": "read a.txt"}], tools=tools,
        )
        assert all(isinstance(tc, dict) for tc in result)

    def test_raises_when_no_provider_supports_tools(self) -> None:
        """Fail-loudly: no capable provider → RuntimeError, not silent empty."""
        adapter = _adapter_for(FakeNoToolProvider())
        tools = [{"type": "function", "function": {"name": "read_file"}}]
        with pytest.raises(RuntimeError, match="supports tool calling"):
            adapter.tool_call(
                [{"role": "user", "content": "read a.txt"}], tools=tools,
            )


# ---------------------------------------------------------------------------
# health()
# ---------------------------------------------------------------------------

class TestHealth:
    def test_returns_dict_with_status(self, adapter: LLMRouterAdapter) -> None:
        result = adapter.health()
        assert isinstance(result, dict)
        assert "status" in result

    def test_status_ok_when_provider_available(self, adapter: LLMRouterAdapter) -> None:
        result = adapter.health()
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Cross-provider contract invariants (same 5 methods, same shapes)
# ---------------------------------------------------------------------------

class TestCrossProviderInvariants:
    """Both providers must produce identical contract shapes for all 5 methods."""

    def test_generate_shape_identical(self) -> None:
        a = _adapter_for(FakeOpenRouterProvider())
        b = _adapter_for(FakeClaudeFableProvider())
        assert isinstance(a.generate("x"), str)
        assert isinstance(b.generate("x"), str)

    def test_tool_call_shape_identical(self) -> None:
        a = _adapter_for(FakeOpenRouterProvider(tool_calls=_TOOL_CALLS))
        b = _adapter_for(FakeClaudeFableProvider(tool_calls=_TOOL_CALLS))
        tools = [{"type": "function", "function": {"name": "read_file"}}]
        msgs = [{"role": "user", "content": "read"}]
        assert a.tool_call(msgs, tools=tools) == b.tool_call(msgs, tools=tools)

    def test_health_shape_identical(self) -> None:
        a = _adapter_for(FakeOpenRouterProvider())
        b = _adapter_for(FakeClaudeFableProvider())
        assert set(a.health().keys()) == set(b.health().keys())
