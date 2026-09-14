"""Dual-provider interface test: two LLMClient configs satisfy LLMRouter."""
from unittest.mock import MagicMock

from src.providers.llm.client import LLMClient, LLMResponse
from src.core.llm_router_adapter import LLMRouterAdapter
from src.core.protocols import LLMRouter
from src.core.providers import OfflineProvider, OpenAICompatibleProvider


class TestDualProviderProtocol:
    """Prove at least 2 provider configs satisfy the same LLMRouter Protocol."""

    def test_two_providers_satisfy_same_protocol(self):
        """Two different LLMClient configs wrapped in adapter both satisfy Protocol."""
        provider_a = OpenAICompatibleProvider(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-test",
            provider_name="openai-direct",
        )
        provider_b = OfflineProvider()
        client_a = LLMClient(providers=[provider_a])
        client_b = LLMClient(providers=[provider_b])

        adapter_a = LLMRouterAdapter(client=client_a)
        adapter_b = LLMRouterAdapter(client=client_b)

        assert isinstance(adapter_a, LLMRouter)
        assert isinstance(adapter_b, LLMRouter)

    def test_generate_delegates_to_client(self):
        """generate() call chain delegates to LLMClient.generate()."""
        adapter = LLMRouterAdapter()
        mock_client = MagicMock(spec=LLMClient)
        mock_client.generate.return_value = "delegated output"
        adapter._llm_client = mock_client

        result = adapter.generate("hello", model="claude-3", temperature=0.5)

        assert result == "delegated output"
        mock_client.generate.assert_called_once_with(
            "hello", model="claude-3", temperature=0.5,
        )

    def test_chat_delegates_to_client(self):
        """LLMClient.chat() is reachable and used through the adapter."""
        adapter = LLMRouterAdapter()
        mock_client = MagicMock(spec=LLMClient)
        mock_client.chat.return_value = LLMResponse(content="streamed chunk")
        adapter._llm_client = mock_client

        chunks = list(adapter.stream("hello", model="claude-3"))

        assert chunks == ["streamed chunk"]
        mock_client.chat.assert_called_once()
        _, kwargs = mock_client.chat.call_args
        assert kwargs.get("model") == "claude-3"

    def test_is_available_reflects_client(self):
        """is_available property reflects underlying client state."""
        adapter = LLMRouterAdapter()
        mock_client = MagicMock(spec=LLMClient)
        mock_client.is_available = True
        adapter._llm_client = mock_client

        assert adapter.is_available is True

        mock_client.is_available = False
        assert adapter.is_available is False