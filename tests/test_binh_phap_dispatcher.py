"""Tests for Binh Phap Dispatcher — topology-to-PEV bridge."""

import json
import pytest
from pathlib import Path


@pytest.fixture
def tmp_company(tmp_path: Path):
    """Create a temporary company.json for topology engine."""
    company = tmp_path / "company.json"
    company.write_text(json.dumps({
        "binh_phap_state": {
            "topology": "3d",
            "current_dimension": "vertical",
            "cycle_number": 0,
            "cycle_history": [],
            "current_groups": {},
            "next_command": "swot",
            "auto_dispatch": False,
            "target_mrr": 1000,
        }
    }))
    return str(company)


class TestBinhPhapDispatcher:
    """Test dispatcher translates topology decisions correctly."""

    def test_vertical_dispatch(self, tmp_company: str) -> None:
        from src.core.binh_phap_dispatcher import BinhPhapDispatcher
        d = BinhPhapDispatcher(company_json=tmp_company)
        action = d.next_action()
        assert action["action"] == "execute"
        assert action["command"] == "swot"
        assert action["dimension"] == "vertical"
        assert isinstance(action["needs_approval"], bool)

    def test_report_result_advances(self, tmp_company: str) -> None:
        from src.core.binh_phap_dispatcher import BinhPhapDispatcher
        d = BinhPhapDispatcher(company_json=tmp_company)
        d.report_result("swot", success=True)
        action = d.next_action()
        assert action["command"] == "plan"

    def test_failure_tracking(self, tmp_company: str) -> None:
        from src.core.binh_phap_dispatcher import BinhPhapDispatcher
        d = BinhPhapDispatcher(company_json=tmp_company)
        d.report_result("swot", success=False, error="failed")
        assert d.topology.consecutive_failures == 1

    def test_event_handling(self, tmp_company: str) -> None:
        from src.core.binh_phap_dispatcher import BinhPhapDispatcher
        d = BinhPhapDispatcher(company_json=tmp_company)
        actions = d.handle_event("ci.failed", source="github")
        assert len(actions) > 0
        assert actions[0]["event"] == "ci.failed"
        assert "debug" in actions[0]["commands"]

    def test_status_report(self, tmp_company: str) -> None:
        from src.core.binh_phap_dispatcher import BinhPhapDispatcher
        d = BinhPhapDispatcher(company_json=tmp_company)
        status = d.get_status()
        assert status["dimension"] == "vertical"
        assert status["next_command"] == "swot"
        assert "groups" in status

    def test_cycle_lesson(self, tmp_company: str) -> None:
        from src.core.binh_phap_dispatcher import BinhPhapDispatcher
        d = BinhPhapDispatcher(company_json=tmp_company)
        d.report_cycle_lesson(
            mrr=500.0,
            customers=10,
            lessons=["Show HN drove 50 signups"],
        )
        state = d.topology.state
        assert len(state["cycle_history"]) == 1
        assert state["cycle_history"][0]["result"]["mrr"] == 500.0

    def test_stop_after_max_failures(self, tmp_company: str) -> None:
        from src.core.binh_phap_dispatcher import BinhPhapDispatcher
        d = BinhPhapDispatcher(company_json=tmp_company)
        for _ in range(3):
            d.report_result("swot", success=False)
        action = d.next_action()
        assert action["action"] == "stop"

    def test_unknown_event_returns_no_reaction(self, tmp_company: str) -> None:
        from src.core.binh_phap_dispatcher import BinhPhapDispatcher
        d = BinhPhapDispatcher(company_json=tmp_company)
        actions = d.handle_event("unknown.event.type")
        assert len(actions) == 1
        assert actions[0]["commands"] == []


class TestEscalationRouting:
    """Test LLM escalation routing — local_mlx → cloud_sonnet → cloud_opus."""

    def test_resolve_local_mlx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.binh_phap_escalation import resolve_llm_provider
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.delenv("ZUNEF_FABLE_BASE_URL", raising=False)
        config = resolve_llm_provider("local_mlx")
        assert config["base_url"].startswith("http")
        assert "fable" in config["model"]
        assert "fable" in config["provider_name"]

    def test_resolve_cloud_sonnet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.binh_phap_escalation import resolve_llm_provider
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.delenv("ZUNEF_SONNET_BASE_URL", raising=False)
        config = resolve_llm_provider("cloud_sonnet")
        assert config["base_url"].startswith("https://")
        assert "sonnet" in config["model"]
        assert "sonnet" in config["provider_name"]

    def test_resolve_cloud_opus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.binh_phap_escalation import resolve_llm_provider
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.delenv("ZUNEF_OPUS_BASE_URL", raising=False)
        config = resolve_llm_provider("cloud_opus")
        assert config["base_url"].startswith("https://")
        assert "opus" in config["model"]
        assert "opus" in config["provider_name"]

    def test_resolve_unknown_defaults_to_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.core.binh_phap_escalation import resolve_llm_provider
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        config = resolve_llm_provider("unknown_level")
        assert "fable" in config["model"]
        assert "fable" in config["provider_name"]

    def test_get_llm_for_command(self, tmp_company: str) -> None:
        from src.core.binh_phap_dispatcher import BinhPhapDispatcher
        d = BinhPhapDispatcher(company_json=tmp_company)
        # standup = AUTONOMOUS → local_mlx
        config = d.get_llm_for_command("standup")
        assert config["escalation_level"] == "local_mlx"
        # launch = APPROVE → cloud_sonnet
        config = d.get_llm_for_command("launch")
        assert config["escalation_level"] == "cloud_sonnet"
        # pivot = STRATEGIC → cloud_opus
        config = d.get_llm_for_command("pivot")
        assert config["escalation_level"] == "cloud_opus"

    def test_escalation_provider_configs_complete(self) -> None:
        from src.core.binh_phap_escalation import ESCALATION_PROVIDERS
        for level, config in ESCALATION_PROVIDERS.items():
            assert "base_url" in config, f"{level} missing base_url"
            assert "model" in config, f"{level} missing model"
            assert "provider_name" in config, f"{level} missing provider_name"
