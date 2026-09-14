"""Unit and integration tests for /v1/quota endpoints mounted on the gateway."""
from __future__ import annotations

from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from src.gateway import app
import src.api.raas_billing_service as rbs
from src.api.raas_billing_service import get_billing_service
from src.raas.credit_rate_limiter import TIER_LIMITS


@pytest.fixture(autouse=True)
def clean_billing_service():
    """Reset the billing service singleton before and after each test."""
    rbs._service = None
    yield
    rbs._service = None


@pytest.fixture
def client():
    """Test client mounted on the central gateway FastAPI app."""
    return TestClient(app)


class TestQuotaTiersEndpoint:
    """Test public GET /v1/quota/tiers endpoint."""

    def test_get_tiers_public_access(self, client):
        resp = client.get("/v1/quota/tiers")
        assert resp.status_code == 200
        data = resp.json()
        assert "tiers" in data

        tiers = data["tiers"]
        # All configured tiers in TIER_LIMITS must be present
        for tier_name in TIER_LIMITS:
            assert tier_name in tiers
            tier_info = tiers[tier_name]
            assert "daily_limit" in tier_info
            assert "monthly_limit" in tier_info
            assert "allow_overage" in tier_info
            assert "overage_rate_per_credit" in tier_info
            assert "max_overage_credits" in tier_info
            assert "warning_threshold_pct" in tier_info
            assert isinstance(tier_info["daily_limit"], int)
            assert isinstance(tier_info["monthly_limit"], int)
            assert isinstance(tier_info["allow_overage"], bool)


class TestQuotaStatusEndpoint:
    """Test GET /v1/quota/status endpoint for authenticated tenants."""

    def test_quota_status_default_free(self, client):
        resp = client.get("/v1/quota/status")
        assert resp.status_code == 200
        data = resp.json()

        assert "tenant_id" in data
        assert data["tier"] == "free"

        usage = data["usage"]
        assert usage["mcu_used"] == 0
        assert usage["mcu_limit"] > 0
        assert usage["mcu_remaining"] == usage["mcu_limit"]
        assert usage["usage_percentage"] == 0.0

        overage = data["overage"]
        assert "allow_overage" in overage
        assert "overage_rate" in overage
        assert overage["overage_credits"] == 0
        assert overage["overage_charges_usd"] == 0.0

        warnings = data["warnings"]
        assert warnings["approaching_limit"] is False
        assert warnings["quota_exceeded"] is False
        assert warnings["overage_cap_reached"] is False

    def test_quota_status_approaching_limit_warning(self, client, monkeypatch):
        # Set tenant id
        tenant_id = "tenant-approaching"
        monkeypatch.setenv("MEKONG_TEST_TENANT_ID", tenant_id)

        service = get_billing_service()
        ledger = service._get_or_create_ledger(tenant_id)
        # Limit is 100 on free plan, set used to 85 (85% >= 80% warning threshold)
        ledger.mcu_used = 85

        resp = client.get("/v1/quota/status")
        assert resp.status_code == 200
        data = resp.json()

        assert data["usage"]["mcu_used"] == 85
        assert data["usage"]["usage_percentage"] == 85.0
        assert data["warnings"]["approaching_limit"] is True
        assert data["warnings"]["quota_exceeded"] is False

    def test_quota_status_quota_exceeded_and_overage_cap(self, client, monkeypatch):
        tenant_id = "tenant-exceeded"
        monkeypatch.setenv("MEKONG_TEST_TENANT_ID", tenant_id)

        service = get_billing_service()
        ledger = service._get_or_create_ledger(tenant_id)
        # Exceed limit
        ledger.plan = "starter"
        ledger.mcu_limit = 500
        ledger.mcu_used = 600
        ledger.overage_credits = 100
        ledger.overage_charges_usd = Decimal("1.50")

        resp = client.get("/v1/quota/status")
        assert resp.status_code == 200
        data = resp.json()

        assert data["tier"] == "starter"
        assert data["usage"]["mcu_used"] == 600
        assert data["overage"]["overage_credits"] == 100
        assert data["overage"]["overage_charges_usd"] == 1.50
        assert data["warnings"]["quota_exceeded"] is True


class TestQuotaHistoryEndpoint:
    """Test GET /v1/quota/history endpoint."""

    def test_quota_history_empty(self, client):
        resp = client.get("/v1/quota/history")
        assert resp.status_code == 200
        data = resp.json()

        assert "tenant_id" in data
        assert data["tier"] == "free"
        assert data["entries"] == []
        assert data["total_entries"] == 0

    def test_quota_history_with_usage_entries(self, client, monkeypatch):
        tenant_id = "tenant-history"
        monkeypatch.setenv("MEKONG_TEST_TENANT_ID", tenant_id)

        service = get_billing_service()
        service.charge_mcu(tenant_id, task_id="task-1", complexity="simple")
        service.charge_mcu(tenant_id, task_id="task-2", complexity="standard")

        resp = client.get("/v1/quota/history?limit=10")
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_entries"] == 2
        assert len(data["entries"]) == 2
        task_ids = [e["task_id"] for e in data["entries"]]
        assert "task-1" in task_ids
        assert "task-2" in task_ids
