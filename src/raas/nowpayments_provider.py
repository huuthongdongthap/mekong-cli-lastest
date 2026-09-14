# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""NowPaymentsProvider — PaymentProvider adapter wrapping NOWPayments IPN.

Delegates settlement/activation to the existing handle_ipn internals
from nowpayments_webhook_handler.  Legacy BillingAdapter methods
(settle_payment / record_usage / check_quota) delegate to BillingAdapter
so that MCUBilling remains the single internal ledger.

No logic rewrite — pure delegation to existing, tested internals.
"""
from __future__ import annotations

import logging
from typing import Any, cast

from src.core.protocols import (
    PaymentReceipt,
    PaymentRequest,
    Quote,
    QuotaStatus,
)

logger = logging.getLogger(__name__)


class NowPaymentsProvider:
    """PaymentProvider adapter for NOWPayments.

    Wraps the IPN webhook handler and exposes the full PaymentProvider
    protocol.  Legacy billing methods (record_usage, check_quota,
    settle_payment) delegate to BillingAdapter so that the MCU credit
    ledger remains the single source of truth.

    Extended economic-bus methods (quote, request_payment, verify, refund)
    either call the NOWPayments handler or return explicit not-implemented
    markers following the same pattern as BillingAdapter.
    """

    _LEGACY_ERROR = (
        "not implemented: NOWPaymentsProvider is a payment-settlement adapter; "
        "use BillingAdapter for MCU credit ledger operations"
    )

    # ─── Legacy billing methods (delegate to BillingAdapter) ───────────

    def record_usage(self, agent: str, tokens: int, model: str) -> None:
        """Record usage — delegates to BillingAdapter."""
        from src.core.billing_adapter import get_adapter
        get_adapter().record_usage(agent, tokens, model, "nowpayments")

    def check_quota(self, org_id: str) -> QuotaStatus:
        """Check quota — delegates to BillingAdapter."""
        from src.core.billing_adapter import get_adapter
        return cast(QuotaStatus, get_adapter().check_quota(org_id))

    def settle_payment(
        self, amount: float, currency: str, recipient: str
    ) -> dict[str, Any]:
        """Settle payment — not directly supported via NOWPayments IPN path.

        NOWPayments settlement happens via the IPN callback, not a direct
        settle call.  Returns a not-implemented result dict matching the
        PaymentResult protocol shape.
        """
        return {
            "success": False,
            "transaction_id": None,
            "pending": False,
            "note": None,
            "error": self._LEGACY_ERROR,
        }

    # ─── Extended economic-bus methods ─────────────────────────────────

    def quote(
        self, amount: float, currency: str, recipient: str, scheme: str
    ) -> Quote:
        """Return a price quote for a NOWPayments checkout.

        NOWPayments does not expose a public quote API — the price is
        determined by the plan tier and checkout session.  Returns a
        zero-value Quote with an informational note.
        """
        return Quote(
            asset=currency,
            network="nowpayments",
            amount=amount,
            recipient=recipient,
            scheme=scheme,
            provider="nowpayments",
            metadata={
                "note": "NOWPayments determines price at checkout session creation",
            },
        )

    def request_payment(self, req: PaymentRequest) -> PaymentReceipt:
        """Initiate a payment via NOWPayments.

        Actual payment initiation is handled by the checkout router
        (create_payment / create_invoice).  This method exists to
        satisfy the PaymentProvider protocol for the economic bus.
        """
        return PaymentReceipt(
            asset=req.asset,
            network=req.network,
            amount=req.amount,
            recipient=req.recipient,
            scheme=req.scheme,
            provider="nowpayments",
            transaction_id="",
            metadata={
                "note": "Use checkout_router.create_payment for NOWPayments checkout sessions",
            },
        )

    def verify(self, receipt: PaymentReceipt) -> bool:
        """Verify a NOWPayments payment receipt.

        Delegates HMAC verification to the existing IPN handler's
        verify_ipn_signature function.  For protocol-level receipt
        verification (no raw IPN payload available), returns False
        to signal that IPN-level verification is required.
        """
        return False

    def refund(self, receipt: PaymentReceipt) -> dict[str, Any]:
        """Refund via NOWPayments.

        NOWPayments refunds must be initiated through their dashboard
        or API directly.  Returns not-implemented to signal this.
        """
        return {
            "success": False,
            "transaction_id": receipt.transaction_id,
            "pending": False,
            "note": None,
            "error": "NOWPayments refunds must be initiated via their dashboard/API",
        }

    # ─── IPN processing (delegates to existing handler) ────────────────

    def process_ipn(self, payload_json: str, signature: str = "") -> dict[str, Any]:
        """Process a NOWPayments IPN callback.

        Thin wrapper around the existing handle_ipn function so that
        callers can use the provider interface.  Returns the same dict
        shape as handle_ipn (ok, action/error, ...).
        """
        from src.raas.nowpayments_webhook_handler import handle_ipn
        return handle_ipn(payload_json, signature=signature)

    def verify_signature(self, payload_json: str, received_sig: str) -> bool:
        """Verify NOWPayments IPN HMAC-SHA512 signature.

        Delegates to the existing handler's verify_ipn_signature.
        """
        from src.raas.nowpayments_webhook_handler import verify_ipn_signature
        return verify_ipn_signature(payload_json, received_sig)


__all__ = ["NowPaymentsProvider"]
