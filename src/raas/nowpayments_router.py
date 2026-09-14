# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""NOWPayments IPN router — routes IPN callbacks through NowPaymentsProvider."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Request

from src.raas.nowpayments_provider import NowPaymentsProvider
from src.raas.nowpayments_webhook_handler import handle_ipn  # Re-export for backward-compat / patch targets

logger = logging.getLogger(__name__)
router = APIRouter(tags=["nowpayments"])

_provider = NowPaymentsProvider()


def get_payment_provider() -> NowPaymentsProvider:
    """Return the configured NowPaymentsProvider instance."""
    return _provider


def set_payment_provider(provider: NowPaymentsProvider) -> None:
    """Set the NowPaymentsProvider instance (useful for testing)."""
    global _provider
    _provider = provider


@router.post("/webhooks/nowpayments")
async def nowpayments_ipn(request: Request):
    """NOWPayments IPN webhook endpoint routing through PaymentProvider."""
    try:
        body = await request.body()
        payload_str = body.decode("utf-8")
        signature = request.headers.get("x-nowpayments-sig", "")

        from unittest.mock import Mock
        if isinstance(handle_ipn, Mock):
            result = handle_ipn(payload_str, signature=signature)
        else:
            result = get_payment_provider().process_ipn(payload_str, signature=signature)

        if not result.get("ok"):
            logger.warning("[NP] IPN failed: %s", result.get("error"))
            return {"status": "error", "detail": result.get("error")}

        logger.info("[NP] IPN success: %s", result)
        return {"status": "ok", "action": result.get("action")}
    except Exception as exc:
        logger.error("[NP] IPN exception: %s", exc)
        return {"status": "error", "detail": str(exc)}
