# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""BillingAdapter — unified billing interface wrapping MCUBilling.

Implements the PaymentProvider protocol from src.core.protocols, providing
a single entry point for all billing operations (record_usage, check_quota,
settle_payment, estimate_cost). All underlying state is persisted via
MCUBilling's SQLite-backed CreditStore.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.core.protocols import PaymentResult, QuotaStatus, PaymentRequest, PaymentReceipt, Quote


@dataclass(frozen=True)
class BillingUsageEvent:
    """Structured usage event for billing recording."""

    agent: str
    tokens: int
    model: str
    operation: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class BillingAdapter:
    """Unified billing interface wrapping MCUBilling.

    Wires the canonical MCUBilling singleton behind a consistent interface
    so that RaaS, API routes, and other consumers share one billing core
    without duplicating logic.
    """

    def __init__(self, mcu_billing: Any = None) -> None:
        from src.core.mcu_billing import MCUBilling

        self._billing = mcu_billing if mcu_billing is not None else MCUBilling()

    @property
    def billing(self) -> Any:
        """Return the underlying MCUBilling instance (read-only access)."""
        return self._billing

    def record_usage(
        self, agent: str, tokens: int, model: str, operation: str
    ) -> None:
        """Record usage via MCUBilling.

        Args:
            agent: Agent identifier (tenant or agent name).
            tokens: Number of tokens consumed (non-negative).
            model: LLM model identifier used.
            operation: Operation name (e.g. chat, completion).
        """
        self._billing.record_usage(agent, tokens, model, operation)

    def check_quota(self, tenant_id: str) -> Dict[str, Any]:
        """Check quota via MCUBilling.

        Returns a dict with the required QuotaStatus fields so consumers
        never depend on the concrete QuotaStatus type.
        """
        status: QuotaStatus = self._billing.check_quota(tenant_id)
        return {
            "remaining_mcu": status.remaining_mcu,
            "total_mcu": status.total_mcu,
            "tier": status.tier,
            "reset_at": status.reset_at,
            "low_balance": getattr(status, "low_balance", False),
        }

    def settle_payment(
        self, amount: float, currency: str, recipient: str
    ) -> Dict[str, Any]:
        """Settle payment via MCUBilling.

        Returns a dict with the required PaymentResult fields so consumers
        never depend on the concrete PaymentResult type.
        """
        result: PaymentResult = self._billing.settle_payment(
            amount, currency, recipient
        )
        # MCUBilling PaymentResult stub has no `success` field — infer from
        # `pending`: the stub returns pending=True meaning "not yet settled".
        success = not result.pending
        return {
            "success": success,
            "transaction_id": result.transaction_id,
            "pending": result.pending,
            "note": result.note,
        }

    # ─── Extended PaymentProvider interface (economic bus) ─────────────
    #
    # MCUBilling is an internal credit ledger, not a payment network.
    # The extended methods below are explicit not-implemented seams:
    # they return PaymentResult(error=...) instead of raising, so callers
    # get a clear, typed failure. Real settlement (x402/MPP) is deferred
    # to a dedicated PaymentProvider adapter.

    _NOT_IMPLEMENTED = (
        "not implemented: MCUBilling is an internal credit ledger; "
        "use a dedicated PaymentProvider adapter for settlement"
    )

    def quote(
        self, amount: float, currency: str, recipient: str, scheme: str
    ) -> Quote:
        """Return a quote for a prospective payment.

        MCUBilling has no external settlement, so quoting is not supported.
        Returns a zero-value Quote carrying an explicit error marker in
        metadata instead of raising.
        """
        return Quote(
            asset=currency,
            network="mcu-internal",
            amount=amount,
            recipient=recipient,
            scheme=scheme,
            provider="mcu-billing",
            metadata={"error": self._NOT_IMPLEMENTED},
        )

    def request_payment(self, req: PaymentRequest) -> PaymentReceipt:
        """Initiate a payment request.

        Not supported by MCUBilling — returns a receipt carrying an
        explicit error marker in metadata instead of raising.
        """
        return PaymentReceipt(
            asset=req.asset,
            network=req.network,
            amount=req.amount,
            recipient=req.recipient,
            scheme=req.scheme,
            provider="mcu-billing",
            transaction_id="",
            metadata={"error": self._NOT_IMPLEMENTED},
        )

    def verify(self, receipt: PaymentReceipt) -> bool:
        """Verify a payment receipt.

        Not supported by MCUBilling — always returns False for receipts
        it did not issue.
        """
        return False

    def refund(self, receipt: PaymentReceipt) -> Dict[str, Any]:
        """Refund a settled payment.

        Not supported by MCUBilling — returns a PaymentResult-shaped dict
        with an explicit error instead of raising.
        """
        return {
            "success": False,
            "transaction_id": None,
            "pending": False,
            "note": None,
            "error": self._NOT_IMPLEMENTED,
        }

    def estimate_cost(self, model: str, tokens: int) -> Dict[str, Any]:
        """Estimate cost for a given model and token count.

        Falls back to a zero-cost dict if MCUBilling does not implement
        estimate_cost (it currently does not).
        """
        if hasattr(self._billing, "estimate_cost"):
            est: Any = self._billing.estimate_cost(model, tokens)
            return {
                "model": est.model,
                "input_tokens": getattr(est, "input_tokens", tokens),
                "output_tokens": getattr(est, "output_tokens", tokens),
                "cost_usd": float(est.cost_usd),
                "currency": getattr(est, "currency", "USD"),
            }
        return {
            "model": model,
            "tokens": tokens,
            "cost_usd": 0.0,
            "currency": "USD",
        }

    def record_usage_event(self, event: BillingUsageEvent) -> None:
        """Record a structured BillingUsageEvent.

        Convenience wrapper so callers can pass a single dataclass instead
        of four separate arguments.
        """
        self.record_usage(
            agent=event.agent,
            tokens=event.tokens,
            model=event.model,
            operation=event.operation,
        )

    def get_balance(self, tenant_id: str) -> int:
        """Return the current MCU balance for a tenant."""
        return self._billing.get_balance(tenant_id)

    def add_credits(self, tenant_id: str, amount: int, reason: str = "") -> None:
        """Add MCU credits to a tenant."""
        self._billing.add_credits(tenant_id, amount, reason)


# Module-level singleton for convenience.
_adapter: Optional[BillingAdapter] = None


def get_adapter() -> BillingAdapter:
    """Return the module-level BillingAdapter singleton."""
    global _adapter
    if _adapter is None:
        _adapter = BillingAdapter()
    return _adapter


def reset_adapter() -> None:
    """Reset the module-level singleton (for testing)."""
    global _adapter
    _adapter = None


__all__ = [
    "BillingAdapter",
    "BillingUsageEvent",
    "get_adapter",
    "reset_adapter",
]