# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Conformance suite for the four LLM provider adapters (Task 2, SC#5).

Parametrized over claude/qwen/deepseek/local with an in-memory fake
transport injected — hermetic, zero network, zero secrets. Each provider
runs the SAME five methods; the suite asserts return types, error
semantics (ConfigError when config missing, NotSupportedError when a
capability flag is off), health shape, and stream-is-iterator.

Acceptance bar: ≥2 providers pass (expected 4/4).
"""

from __future__ import annotations

import pytest

from src.core.adapters.llm import (
    ClaudeLLMAdapter,
    DeepSeekLLMAdapter,
    LocalLLMAdapter,
    QwenLLMAdapter,
    build_llm_provider,
)
from src.core.providers import LLMResponse
from src.core.ports.llm import (
    LLMConfigError,
    LLMNotSupportedError,
    LLMProviderPort,
)

ALL_ADAPTERS = [
    pytest.param(ClaudeLLMAdapter, id="claude"),
    pytest.param(QwenLLMAdapter, id="qwen"),
    pytest.param(DeepSeekLLMAdapter, id="deepseek"),
    pytest.param(LocalLLMAdapter, id="local"),
]

# Env vars the adapters may read during implicit transport resolution.
# Cleared per-test so fail-loud assertions stay hermetic on dev machines.
ADAPTER_ENV_VARS = ["LLM_BASE_URL", "LLM_API_KEY", "DASHSCOPE_API_KEY",
                     "DEEPSEEK_API_KEY", "OLLAMA_BASE_URL", "LOCAL_LLM_URL"]


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    for var in ADAPTER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _fake_transport(*, tool_calls=None, content="hello world", model="fake-model"):
    """In-memory transport returning canned responses — no network, no socket."""

    def _chat(messages, model=None, temperature=0.7, max_tokens=2048,
              json_mode=False, tools=None, **kwargs):
        return LLMResponse(content=content, model=model or "fake-model",
                           usage={"total_tokens": 42}, raw={"fake": True},
                           tool_calls=tool_calls or [])

    return _chat


# ---------------------------------------------------------------------------
# Structural / isinstance conformance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS)
def test_adapters_satisfy_port_protocol(adapter_cls):
    adapter = adapter_cls(transport=_fake_transport())
    assert isinstance(adapter, LLMProviderPort)


def test_factory_unknown_name_raises_config_error():
    with pytest.raises(LLMConfigError):
        build_llm_provider("does-not-exist")


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS)
def test_missing_config_raises_config_error_when_no_transport(adapter_cls):
    # No transport + no config + no matching env var -> fail-loud, never default
    adapter = adapter_cls(transport=None, config={})
    with pytest.raises(LLMConfigError):
        adapter.generate("ping")


# ---------------------------------------------------------------------------
# 5-method conformance (same methods, same assertions, all providers)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS)
def test_generate_returns_str(adapter_cls):
    adapter = adapter_cls(transport=_fake_transport())
    out = adapter.generate("hello")
    assert isinstance(out, str) and out == "hello world"


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS)
def test_stream_is_iterator(adapter_cls):
    gen = adapter_cls(transport=_fake_transport()).stream("hello")
    assert hasattr(gen, "__iter__") and hasattr(gen, "__next__")
    collected = list(gen)
    assert collected and isinstance(collected[0], str)


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS)
def test_structured_output_returns_dict(adapter_cls):
    out = adapter_cls(transport=_fake_transport()).structured_output("give me json", {"type": "object"})
    assert isinstance(out, dict)


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS)
def test_health_shape(adapter_cls):
    info = adapter_cls(transport=_fake_transport()).health()
    assert isinstance(info, dict)
    assert isinstance(info["status"], str)
    assert isinstance(info["model"], str)
    assert "provider" in info


# ---------------------------------------------------------------------------
# tool_call semantics (align with protocols.LLMRouter.tool_call)
# ---------------------------------------------------------------------------


def test_tool_call_returns_list_when_supported():
    transport = _fake_transport(tool_calls=[{"id": "call_1", "type": "function"}])
    out = ClaudeLLMAdapter(transport=transport).tool_call(
        [{"role": "user", "content": "x"}], [{"type": "function"}])
    assert isinstance(out, list) and out[0]["id"] == "call_1"


def test_tool_call_disabled_raises_not_supported():
    adapter = DeepSeekLLMAdapter(transport=_fake_transport())
    adapter.supports_tool_calling = False
    with pytest.raises(LLMNotSupportedError):
        adapter.tool_call([{"role": "user", "content": "x"}], [{"type": "function"}])


def test_structured_output_disabled_raises_not_supported():
    adapter = LocalLLMAdapter(transport=_fake_transport())
    adapter.supports_structured_output = False
    with pytest.raises(LLMNotSupportedError):
        adapter.structured_output("x", {})


def test_stream_disabled_raises_not_supported():
    adapter = QwenLLMAdapter(transport=_fake_transport())
    adapter.supports_streaming = False
    with pytest.raises(LLMNotSupportedError):
        list(adapter.stream("x"))


# ---------------------------------------------------------------------------
# Factory + config injection for tests (hermetic, zero network)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS)
def test_config_injection_is_hermetic(adapter_cls):
    # config dict alone must build a transport (no env vars, no network —
    # the real round-trip uses an injected fake so the test stays hermetic).
    adapter = adapter_cls(config={"base_url": "http://localhost:7860/v1",
                                  "api_key": "fake-key", "model": "fake-model"})
    assert adapter._resolve_transport() is not None
    adapter._transport = _fake_transport()
    adapter._implicit_transport = None
    assert isinstance(adapter.generate("ping"), str)


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS)
def test_factory_build_matches_class(adapter_cls):
    config = {"base_url": "http://localhost:1", "api_key": "x"}
    via_factory = build_llm_provider(adapter_cls.name, config=config)
    direct = adapter_cls(transport=_fake_transport())
    assert via_factory.health()["provider"] == direct.health()["provider"] == adapter_cls.name