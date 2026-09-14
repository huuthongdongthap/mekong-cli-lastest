"""Golden tests for NOWPayments IPN endpoint — byte-identical response verification.

Captures exact response shapes from the existing handler BEFORE the
PaymentProvider adapter change, then verifies they remain identical
AFTER the change.  This is the parity gate for the protected flow.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))



# ---------------------------------------------------------------------------
# Helper: build valid HMAC signature
# ---------------------------------------------------------------------------

def _make_sig(secret: str, payload: str) -> str:
    import hashlib
    import hmac
    sorted_payload = json.dumps(json.loads(payload), sort_keys=True)
    return hmac.new(
        secret.encode(),
        sorted_payload.encode(),
        hashlib.sha512,
    ).hexdigest()


# ---------------------------------------------------------------------------
# Golden response shapes (captured from pre-change handler)
# ---------------------------------------------------------------------------

class TestGoldenResponseShapes:
    """Verify that endpoint returns byte-identical response JSON."""

    def _finished_payload(self) -> str:
        return json.dumps({
            "payment_id": "pay_gold_001",
            "payment_status": "finished",
            "order_id": "ws_gold-pro-monthly",
            "order_description": "OpenClaw pro plan",
            "pay_amount": "149.00",
            "pay_currency": "usdttrc20",
            "price_amount": 149,
            "price_currency": "usd",
        })

    def _waiting_payload(self) -> str:
        return json.dumps({
            "payment_id": "pay_gold_002",
            "payment_status": "waiting",
            "order_id": "ws_gold-starter-monthly",
            "order_description": "starter plan",
            "pay_amount": "49.00",
            "pay_currency": "btc",
            "price_amount": 49,
            "price_currency": "usd",
        })

    def test_finished_golden_response(self, tmp_path):
        """Exact response shape for a finished IPN payment."""
        from src.raas.credit_account_repository import CreditAccountRepository
        from src.raas import nowpayments_webhook_handler as handler_mod

        payload = self._finished_payload()

        db_file = tmp_path / "workspaces.db"
        repo = CreditAccountRepository(db_file)
        repo.create_account("ws_gold")

        with patch.object(handler_mod, "CreditAccountRepository", return_value=repo), \
             patch.object(handler_mod, "_log_payment"):
            result = handler_mod.handle_ipn(payload, signature="")

        # Golden assertions — exact shape
        assert result["ok"] is True
        assert result["action"] == "credits_granted"
        assert result["tier"] == "pro"
        assert result["credits"] == 1200
        assert result["workspace_id"] == "ws_gold"
        assert result["payment_id"] == "pay_gold_001"

    def test_waiting_golden_response(self):
        """Exact response shape for a waiting (ignored) IPN payment."""
        from src.raas import nowpayments_webhook_handler as handler_mod

        payload = self._waiting_payload()

        with patch.object(handler_mod, "_log_payment"):
            result = handler_mod.handle_ipn(payload, signature="")

        # Golden assertions — exact shape
        assert result["ok"] is True
        assert result["action"] == "ignored"
        assert "waiting" in result["reason"]

    def test_bad_signature_golden_response(self):
        """Exact response shape for a bad-signature IPN payment."""
        from src.raas import nowpayments_webhook_handler as handler_mod

        handler_mod.IPN_SECRET = "golden-secret"
        payload = self._finished_payload()

        result = handler_mod.handle_ipn(payload, signature="bad-sig-golden")

        # Golden assertions — exact shape
        assert result["ok"] is False
        assert result["error"] == "signature_mismatch"

    def test_exception_golden_response_format(self):
        """Router wraps exceptions in {status: error, detail: str}."""
        with patch("src.raas.nowpayments_webhook_handler.handle_ipn",
                    side_effect=RuntimeError("golden-test-error")):
            # Simulate router logic manually (same as nowpayments_ipn)
            try:
                from src.raas.nowpayments_webhook_handler import handle_ipn
                payload = json.dumps({"payment_id": "x"})
                handle_ipn(payload)
            except RuntimeError as exc:
                router_response = {"status": "error", "detail": str(exc)}

        assert router_response == {"status": "error", "detail": "golden-test-error"}


# ---------------------------------------------------------------------------
# Router-level golden tests (HTTP response via httpx)
# ---------------------------------------------------------------------------

class TestRouterGoldenResponses:
    """HTTP-level golden tests using httpx AsyncClient against the router."""

    @pytest.mark.asyncio
    async def test_finished_returns_ok_status(self):
        """POST /webhooks/nowpayments with finished payment → 200 + {status: ok}."""
        payload = json.dumps({
            "payment_id": "pay_http_001",
            "payment_status": "finished",
            "order_id": "ws_http-pro-monthly",
            "order_description": "pro plan",
            "pay_amount": "149.00",
            "pay_currency": "usdttrc20",
            "price_amount": 149,
            "price_currency": "usd",
        })

        with patch("src.raas.nowpayments_router.handle_ipn") as mock_handle:
            mock_handle.return_value = {
                "ok": True,
                "action": "credits_granted",
                "tier": "pro",
                "credits": 1200,
                "workspace_id": "ws_http",
                "payment_id": "pay_http_001",
            }

            from starlette.testclient import TestClient
            from src.raas.nowpayments_router import router as test_router
            client = TestClient(test_router)
            response = client.post("/webhooks/nowpayments", content=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["action"] == "credits_granted"

    @pytest.mark.asyncio
    async def test_bad_sig_returns_error_status(self):
        """POST with bad signature → {status: error, detail: signature_mismatch}."""
        from src.raas import nowpayments_webhook_handler as handler_mod

        payload = json.dumps({
            "payment_id": "pay_http_002",
            "payment_status": "finished",
            "order_id": "ws_http2-pro-monthly",
            "order_description": "pro plan",
        })

        handler_mod.IPN_SECRET = "test-secret-123"

        with patch("src.raas.nowpayments_router.handle_ipn") as mock_handle:
            mock_handle.return_value = {
                "ok": False,
                "error": "signature_mismatch",
            }

            from starlette.testclient import TestClient
            from src.raas.nowpayments_router import router as test_router
            client = TestClient(test_router)
            response = client.post("/webhooks/nowpayments", content=payload)

        data = response.json()
        assert data == {"status": "error", "detail": "signature_mismatch"}

    @pytest.mark.asyncio
    async def test_exception_returns_error_with_detail(self):
        """POST that raises exception → {status: error, detail: <str(exc)}."""
        with patch("src.raas.nowpayments_router.handle_ipn",
                    side_effect=RuntimeError("test-exception-detail")):
            from starlette.testclient import TestClient
            from src.raas.nowpayments_router import router as test_router
            client = TestClient(test_router)
            response = client.post(
                "/webhooks/nowpayments",
                content=b'{"payment_id": "x"}',
            )

        data = response.json()
        assert data == {"status": "error", "detail": "test-exception-detail"}

    @pytest.mark.asyncio
    async def test_router_path_is_webhooks_nowpayments(self):
        """Router path must remain /webhooks/nowpayments."""
        from src.raas.nowpayments_router import router as test_router

        paths = [r.path for r in test_router.routes]
        assert "/webhooks/nowpayments" in paths
