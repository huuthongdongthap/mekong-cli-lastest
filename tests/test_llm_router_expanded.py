"""Phase 2A: LLMRouter Protocol expansion — generate/health methods."""
from unittest.mock import MagicMock, PropertyMock

from src.providers.llm.client import LLMClient
from src.core.llm_router_adapter import LLMRouterAdapter
from src.core.protocols import LLMRouter


def _adapter_with_mock_client() -> tuple[LLMRouterAdapter, MagicMock]:
    """Build an adapter backed by a mocked LLMClient (no real API calls)."""
    adapter = LLMRouterAdapter()
    mock_client = MagicMock(spec=LLMClient)
    adapter._llm_client = mock_client
    return adapter, mock_client


class TestLLMRouterExpanded:
    """Test expanded LLMRouter Protocol (generate + health)."""

    def test_adapter_satisfies_expanded_protocol(self):
        """LLMRouterAdapter must satisfy expanded LLMRouter Protocol."""
        adapter = LLMRouterAdapter()
        assert isinstance(adapter, LLMRouter)

    def test_generate_returns_string(self):
        """generate() must return a string delegated from LLMClient.generate()."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.generate.return_value = "real llm output"
        result = adapter.generate("Hello world")
        assert isinstance(result, str)
        assert result == "real llm output"
        mock_client.generate.assert_called_once()

    def test_generate_with_model(self):
        """generate(model=...) must forward model to LLMClient.generate()."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.generate.return_value = "ok"
        adapter.generate("Test prompt here", model="claude-3")
        mock_client.generate.assert_called_once_with("Test prompt here", model="claude-3")

    def test_generate_passes_kwargs(self):
        """generate() must forward **kwargs to LLMClient.generate()."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.generate.return_value = "ok"
        adapter.generate("Test", temperature=0.7, max_tokens=100)
        mock_client.generate.assert_called_once_with(
            "Test", temperature=0.7, max_tokens=100,
        )

    def test_generate_uses_model_when_provided(self):
        """generate(model=...) forwards the model to LLMClient (no bypass)."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.generate.return_value = "ok"
        adapter.generate("Any prompt", model="custom-model")
        mock_client.generate.assert_called_once_with("Any prompt", model="custom-model")

    def test_health_returns_status_dict(self):
        """health() must return dict with status key."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.providers = [MagicMock(name="qwen")]
        result = adapter.health()
        assert isinstance(result, dict)
        assert "status" in result

    def test_health_ok_when_client_available(self):
        """health() returns ok when underlying client loads."""
        adapter, mock_client = _adapter_with_mock_client()
        mock_client.providers = [MagicMock(name="qwen")]
        result = adapter.health()
        assert result["status"] == "ok"
        assert "providers" in result

    def test_health_error_on_client_failure(self):
        """health() returns error status when underlying client fails."""
        adapter, mock_client = _adapter_with_mock_client()
        type(mock_client).providers = PropertyMock(
            side_effect=RuntimeError("client down"),
        )
        result = adapter.health()
        assert result["status"] == "error"
        assert "error" in result

    def test_classify_still_works(self):
        """Original classify() must still work after expansion."""
        adapter = LLMRouterAdapter()
        mock_router = MagicMock()
        mock_router.route.return_value = MagicMock(name="claude-3", tier="basic")
        adapter._router = mock_router
        result = adapter.classify("deploy to production")
        assert "model" in result
        assert "task" in result

    def test_estimate_cost_still_works(self):
        """Original estimate_cost() must still work."""
        adapter = LLMRouterAdapter()
        result = adapter.estimate_cost("claude-3", 1000)
        assert result["cost_usd"] == 1000 * 0.00001
        assert result["currency"] == "USD"