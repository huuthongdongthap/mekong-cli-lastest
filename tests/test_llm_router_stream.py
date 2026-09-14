"""Tests for stream() and structured_output() on LLMRouter Protocol and adapter."""
from io import BytesIO
from unittest.mock import MagicMock, patch

from src.core.llm_cache import LLMCache
from src.core.llm_router_adapter import LLMRouterAdapter
from src.core.protocols import LLMRouter
from src.core.providers import (
    GeminiProvider,
    LLMProvider,
    LLMResponse,
    OfflineProvider,
    OpenAICompatibleProvider,
)
from src.providers.llm.client import LLMClient


def _adapter_with_mock_client() -> tuple[LLMRouterAdapter, MagicMock]:
    """Build an adapter backed by a mocked LLMClient (no real API calls)."""
    adapter = LLMRouterAdapter()
    mock_client = MagicMock(spec=LLMClient)
    adapter._llm_client = mock_client
    return adapter, mock_client


class TestLLMRouterStream:
    """Test LLMRouter Protocol stream() method."""

    def test_stream_returns_iterator(self):
        """stream() must return an iterator."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.chat.return_value = LLMResponse(content="hello")
        result = adapter.stream("analyze this task")
        assert hasattr(result, "__iter__")
        assert hasattr(result, "__next__")

    def test_stream_yields_content(self):
        """stream() must yield content chunks delegated from LLMClient.chat()."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.chat.return_value = LLMResponse(content="hello world")
        chunks = list(adapter.stream("test prompt"))
        assert len(chunks) >= 1
        assert chunks[0] == "hello world"
        mock_client.chat.assert_called_once()

    def test_stream_with_model_parameter(self):
        """stream() must forward model to LLMClient.chat()."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.chat.return_value = LLMResponse(content="ok")
        list(adapter.stream("test prompt", model="claude-3"))
        _, kwargs = mock_client.chat.call_args
        assert kwargs.get("model") == "claude-3"

    def test_stream_fallback_when_client_unavailable(self):
        """stream() must yield fallback content when LLMClient.chat() fails."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.chat.side_effect = RuntimeError("provider down")
        chunks = list(adapter.stream("some long prompt here"))
        assert len(chunks) >= 1
        assert isinstance(chunks[0], str)

    def test_stream_delegates_to_client_when_available(self):
        """stream() must delegate to underlying LLMClient.chat() when available."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.chat.return_value = LLMResponse(content="chunk1")
        chunks = list(adapter.stream("test"))
        assert chunks == ["chunk1"]
        mock_client.chat.assert_called_once()


class TestLLMRouterStructuredOutput:
    """Test LLMRouter Protocol structured_output() method."""

    def test_structured_output_returns_dict(self):
        """structured_output() must return a dict."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.generate_json.return_value = {"name": "Alice"}
        result = adapter.structured_output("test prompt", schema={"type": "object"})
        assert isinstance(result, dict)

    def test_structured_output_includes_schema(self):
        """structured_output() result must include the schema."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.generate_json.return_value = {"name": "Alice"}
        result = adapter.structured_output("extract name", schema=schema)
        assert result["schema"] == schema

    def test_structured_output_fallback_when_client_unavailable(self):
        """structured_output() must return fallback dict when LLMClient fails."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.generate_json.side_effect = RuntimeError("provider down")
        schema = {"type": "object"}
        result = adapter.structured_output("some prompt", schema=schema)
        assert isinstance(result, dict)
        assert "schema" in result
        assert result["schema"] == schema

    def test_structured_output_delegates_to_client_when_available(self):
        """structured_output() must delegate to LLMClient.generate_json()."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.generate_json.return_value = {"text": "ok", "data": {}}
        schema = {"type": "object"}
        result = adapter.structured_output("test", schema=schema)
        assert result["parsed"] == {"text": "ok", "data": {}}
        assert result["schema"] == schema
        mock_client.generate_json.assert_called_once()

    def test_structured_output_with_schema(self):
        """structured_output() must accept and use schema parameter."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.generate_json.return_value = {"email": "a@b.com"}
        schema = {"type": "object", "properties": {"email": {"type": "string"}}}
        result = adapter.structured_output("extract email", schema=schema)
        assert result["schema"] == schema


class TestLLMRouterExpanded:
    """Test LLMRouter Protocol still satisfies after expansion."""

    def test_adapter_satisfies_expanded_protocol(self):
        """LLMRouterAdapter must satisfy expanded LLMRouter Protocol."""
        adapter = LLMRouterAdapter()
        assert isinstance(adapter, LLMRouter)


class TestNativeTokenStreaming:
    """Tests for native token-by-token streaming across transport, client, and adapter."""

    def test_adapter_stream_token_by_token_delegation(self):
        """adapter.stream() delegates to client.stream() yielding individual tokens."""
        mock_client = MagicMock(spec=LLMClient)
        mock_client.stream.return_value = iter(["token1", " ", "token2", "!"])
        adapter = LLMRouterAdapter(client=mock_client)

        tokens = list(adapter.stream("Say hello"))
        assert tokens == ["token1", " ", "token2", "!"]
        mock_client.stream.assert_called_once_with(
            [{"role": "user", "content": "Say hello"}],
            model=None,
        )

    def test_openai_compatible_provider_stream_sse_parsing(self):
        """OpenAICompatibleProvider.stream parses SSE data lines and terminates on [DONE]."""
        provider = OpenAICompatibleProvider(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4o",
        )
        assert provider.supports_streaming() is True

        sse_payload = (
            b": keepalive\n\n"
            b"data: {\"choices\": [{\"delta\": {\"content\": \"Mekong\"}}]}\n\n"
            b"invalid line ignored\n"
            b"data: {\"choices\": [{\"delta\": {\"content\": \" CLI\"}}]}\n\n"
            b"data: [DONE]\n\n"
            b"data: {\"choices\": [{\"delta\": {\"content\": \"should not appear\"}}]}\n\n"
        )
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = BytesIO(sse_payload)
            chunks = list(provider.stream([{"role": "user", "content": "hi"}]))

        assert chunks == ["Mekong", " CLI"]

    def test_gemini_provider_default_stream_fallback(self):
        """GeminiProvider inherits default stream() which yields single chat response."""
        provider = GeminiProvider(api_key="")
        assert provider.supports_streaming() is False
        with patch.object(provider, "chat", return_value=LLMResponse(content="gemini response")):
            chunks = list(provider.stream([{"role": "user", "content": "hi"}]))
        assert chunks == ["gemini response"]

    def test_offline_provider_stream(self):
        """OfflineProvider yields offline placeholder string."""
        offline = OfflineProvider()
        chunks = list(offline.stream([{"role": "user", "content": "do work"}]))
        assert len(chunks) == 1
        assert "[OFFLINE MODE]" in chunks[0]
        assert "do work" in chunks[0]

    def test_llm_client_stream_with_failover(self):
        """LLMClient.stream fails over from a failing provider to a healthy one."""
        failing_provider = MagicMock(spec=LLMProvider)
        failing_provider.name = "provider1"
        failing_provider.is_available.return_value = True
        failing_provider.stream.side_effect = RuntimeError("connection reset")

        working_provider = MagicMock(spec=LLMProvider)
        working_provider.name = "provider2"
        working_provider.is_available.return_value = True
        working_provider.stream.return_value = iter(["Hello", " from", " provider2"])

        client = LLMClient(providers=[failing_provider, working_provider])
        chunks = list(client.stream([{"role": "user", "content": "greet"}]))

        assert chunks == ["Hello", " from", " provider2"]
        failing_provider.stream.assert_called_once()
        working_provider.stream.assert_called_once()

    def test_llm_client_stream_cache_hit(self):
        """LLMClient.stream serves from cache when cached entry exists."""
        cache = LLMCache()

        provider = MagicMock(spec=LLMProvider)
        provider.name = "provider"
        provider.is_available.return_value = True

        client = LLMClient(providers=[provider], model="test-model")
        client.cache = cache
        cache.put([{"role": "user", "content": "cached prompt"}], "cached answer", "test-model", 0.7, {})
        chunks = list(client.stream([{"role": "user", "content": "cached prompt"}]))

        assert chunks == ["cached answer"]
        provider.stream.assert_not_called()

    def test_llm_client_stream_offline_fallback(self):
        """LLMClient.stream yields offline response when all providers fail."""
        failing_provider = MagicMock(spec=LLMProvider)
        failing_provider.name = "provider1"
        failing_provider.is_available.return_value = True
        failing_provider.stream.side_effect = RuntimeError("API key invalid")

        client = LLMClient(providers=[failing_provider])
        chunks = list(client.stream([{"role": "user", "content": "status check"}]))

        assert len(chunks) == 1
        assert "[OFFLINE MODE]" in chunks[0]
        assert "status check" in chunks[0]