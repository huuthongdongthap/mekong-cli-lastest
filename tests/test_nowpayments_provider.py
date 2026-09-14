"""Tests for NowPaymentsProvider — PaymentProvider adapter for NOWPayments.

Verifies:
- isinstance(provider, protocols.PaymentProvider) == True (structural check)
- All PaymentProvider protocol methods return correct types
- IPN delegation to existing handler internals
- Signature verification delegation
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.protocols import PaymentProvider  # noqa: E402
from src.raas.nowpayments_provider import NowPaymentsProvider  # noqa: E402


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------

class TestProtocolCompliance:
    """Verify NowPaymentsProvider satisfies PaymentProvider protocol."""

    def test_isinstance_payment_provider(self):
        """isinstance(provider, PaymentProvider) must be True."""
        provider = NowPaymentsProvider()
        assert isinstance(provider, PaymentProvider)

    def test_all_protocol_methods_exist(self):
        """Every method required by PaymentProvider must exist."""
        provider = NowPaymentsProvider()
        for method in ("record_usage", "check_quota", "settle_payment",
                       "quote", "request_payment", "verify", "refund"):
            assert hasattr(provider, method), f"Missing protocol method: {method}"
            assert callable(getattr(provider, method)), f"Method not callable: {method}"


# ---------------------------------------------------------------------------
# Legacy billing delegation
# ---------------------------------------------------------------------------

class TestLegacyDelegation:
    """Legacy billing methods delegate to BillingAdapter."""

    def test_record_usage_delegates(self):
        provider = NowPaymentsProvider()
        with patch("src.core.billing_adapter.get_adapter") as mock_get:
            mock_adapter = mock_get.return_value
            provider.record_usage("test-agent", 100, "claude-3")
            mock_adapter.record_usage.assert_called_once_with(
                "test-agent", 100, "claude-3", "nowpayments"
            )

    def test_check_quota_delegates(self):
        provider = NowPaymentsProvider()
        with patch("src.core.billing_adapter.get_adapter") as mock_get:
            mock_adapter = mock_get.return_value
            mock_adapter.check_quota.return_value = {
                "remaining_mcu": 500,
                "total_mcu": 1000,
                "tier": "pro",
                "reset_at": "2026-01-01",
            }
            result: Any = provider.check_quota("org-001")
            mock_adapter.check_quota.assert_called_once_with("org-001")
            assert result["remaining_mcu"] == 500

    def test_settle_payment_returns_not_implemented(self):
        provider = NowPaymentsProvider()
        result = provider.settle_payment(100.0, "USD", "recipient")
        assert result["success"] is False
        assert result["transaction_id"] is None
        assert "not implemented" in result["error"].lower()


# ---------------------------------------------------------------------------
# Extended economic-bus methods
# ---------------------------------------------------------------------------

class TestExtendedMethods:
    """Extended PaymentProvider methods return correct types and shapes."""

    def test_quote_returns_quote(self):
        provider = NowPaymentsProvider()
        q = provider.quote(49.0, "USD", "ws-001", "nowpayments")
        assert q.asset == "USD"
        assert q.network == "nowpayments"
        assert q.provider == "nowpayments"
        assert q.amount == 49.0

    def test_request_payment_returns_receipt(self):
        from src.core.protocols import PaymentRequest
        provider = NowPaymentsProvider()
        req = PaymentRequest(
            asset="BTC",
            network="bitcoin",
            amount=0.01,
            recipient="ws-001",
            scheme="onetime",
            provider="nowpayments",
        )
        receipt = provider.request_payment(req)
        assert receipt.asset == "BTC"
        assert receipt.network == "bitcoin"
        assert receipt.amount == 0.01
        assert receipt.transaction_id == ""  # not yet settled

    def test_verify_returns_false(self):
        from src.core.protocols import PaymentReceipt
        provider = NowPaymentsProvider()
        receipt = PaymentReceipt(
            asset="USD",
            network="nowpayments",
            amount=49.0,
            recipient="ws-001",
            scheme="onetime",
            provider="nowpayments",
            transaction_id="tx_001",
        )
        assert provider.verify(receipt) is False

    def test_refund_returns_not_implemented(self):
        from src.core.protocols import PaymentReceipt
        provider = NowPaymentsProvider()
        receipt = PaymentReceipt(
            asset="USD",
            network="nowpayments",
            amount=49.0,
            recipient="ws-001",
            scheme="onetime",
            provider="nowpayments",
            transaction_id="tx_002",
        )
        result = provider.refund(receipt)
        assert result["success"] is False
        assert "refund" in result["error"].lower()


# ---------------------------------------------------------------------------
# IPN processing delegation
# ---------------------------------------------------------------------------

class TestIpnDelegation:
    """IPN methods delegate to existing handler functions."""

    def test_process_ipn_delegates_to_handle_ipn(self):
        provider = NowPaymentsProvider()
        with patch("src.raas.nowpayments_webhook_handler.handle_ipn") as mock:
            mock.return_value = {"ok": True, "action": "credits_granted"}
            result = provider.process_ipn('{"payment_id": "1"}', signature="abc")
            mock.assert_called_once_with('{"payment_id": "1"}', signature="abc")
            assert result["ok"] is True

    def test_verify_signature_delegates(self):
        provider = NowPaymentsProvider()
        with patch("src.raas.nowpayments_webhook_handler.verify_ipn_signature") as mock:
            mock.return_value = True
            result = provider.verify_signature('{"x": 1}', "some-sig")
            mock.assert_called_once_with('{"x": 1}', "some-sig")
            assert result is True

    def test_process_ipn_bad_signature(self):
        """process_ipn with bad sig → handler returns ok=False."""
        from src.raas import nowpayments_webhook_handler as handler_mod
        provider = NowPaymentsProvider()

        handler_mod.IPN_SECRET = "provider-test-secret"
        payload = json.dumps({"payment_id": "p_bad", "payment_status": "finished"})

        with patch.object(handler_mod, "_log_payment"):
            result = provider.process_ipn(payload, signature="wrong-sig")

        assert result["ok"] is False
        assert result["error"] == "signature_mismatch"


# ---------------------------------------------------------------------------
# Module exports & aliases
# ---------------------------------------------------------------------------

class TestModuleExports:
    def test_nowpayments_provider_in_all(self):
        from src.raas import nowpayments_provider as mod
        assert "NowPaymentsProvider" in mod.__all__

    def test_core_adapters_payment_alias_import(self):
        """Verify thin alias at src.core.adapters.payment.nowpayments."""
        from src.core.adapters.payment.nowpayments import NowPaymentsProvider as AliasedProvider
        assert AliasedProvider is NowPaymentsProvider
        assert isinstance(AliasedProvider(), PaymentProvider)

    def test_core_adapters_payment_package_export(self):
        """Verify package export at src.core.adapters.payment."""
        from src.core.adapters.payment import NowPaymentsProvider as PkgProvider
        assert PkgProvider is NowPaymentsProvider
        assert isinstance(PkgProvider(), PaymentProvider)

    def test_router_delegates_to_payment_provider(self):
        """Verify router nowpayments_ipn endpoint delegates through NowPaymentsProvider."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient
        from src.raas.nowpayments_router import router, get_payment_provider

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        provider = get_payment_provider()
        with patch.object(provider, "process_ipn") as mock_process:
            mock_process.return_value = {
                "ok": True,
                "action": "credits_granted",
                "tier": "pro",
            }
            resp = client.post(
                "/webhooks/nowpayments",
                content=b'{"payment_id": "test_routed"}',
                headers={"x-nowpayments-sig": "test_sig_123"},
            )
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok", "action": "credits_granted"}
            mock_process.assert_called_once_with('{"payment_id": "test_routed"}', signature="test_sig_123")

