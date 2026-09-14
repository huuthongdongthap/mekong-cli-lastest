# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""MockPaymentProvider — deterministic in-memory PaymentProvider.

Test/dev provider for the economic bus. Guarantees:
- No IO, no network, no keys, no wallet, no real money (§18).
- Deterministic: same inputs always produce the same outputs.
- Idempotent: requests sharing ``metadata["idempotency_key"]`` return the
  SAME receipt and never double-settle.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, Optional

from src.core.protocols import (
    PaymentReceipt,
    PaymentRequest,
    Quote,
)


@dataclass(frozen=True)
class MockQuotaStatus:
    """Concrete QuotaStatus-shaped carrier (satisfies the Protocol structurally)."""

    remaining_mcu: int
    total_mcu: int
    tier: str
    reset_at: str


@dataclass(frozen=True)
class MockPaymentResult:
    """Concrete PaymentResult-shaped carrier (satisfies the Protocol structurally)."""

    success: bool
    transaction_id: Optional[str] = None
    pending: bool = False
    note: Optional[str] = None
    error: Optional[str] = None

PROVIDER_NAME = "mock"
DEFAULT_ASSET = "USDC"
DEFAULT_NETWORK = "base"
DEFAULT_SCHEME = "exact"


class MockPaymentProvider:
    """Deterministic, idempotent, in-memory PaymentProvider.

    Satisfies the extended PaymentProvider protocol (src.core.protocols).
    All state lives in plain dicts — nothing is persisted, nothing leaves
    the process.
    """

    def __init__(
        self,
        asset: str = DEFAULT_ASSET,
        network: str = DEFAULT_NETWORK,
        scheme: str = DEFAULT_SCHEME,
    ) -> None:
        self._asset = asset
        self._network = network
        self._scheme = scheme
        # idempotency_key -> receipt
        self._receipts: Dict[str, PaymentReceipt] = {}
        # transaction_id -> settled amount (for double-settle detection)
        self._settled: Dict[str, float] = {}
        # transaction_id -> refunded flag
        self._refunded: Dict[str, bool] = {}
        self._usage: Dict[str, int] = {}

    # ─── Legacy PaymentProvider methods ────────────────────────────────

    def record_usage(self, agent: str, tokens: int, model: str) -> None:
        """Accumulate token usage per agent (in-memory only)."""
        self._usage[agent] = self._usage.get(agent, 0) + max(0, int(tokens))

    def check_quota(self, org_id: str) -> MockQuotaStatus:
        """Return a static quota status (mock has no quota limits)."""
        return MockQuotaStatus(
            remaining_mcu=10_000,
            total_mcu=10_000,
            tier="MOCK",
            reset_at="1970-01-01T00:00:00Z",
        )

    def settle_payment(
        self, amount: float, currency: str, recipient: str
    ) -> MockPaymentResult:
        """Settle via the mock ledger — deterministic, no real money."""
        if amount <= 0:
            return MockPaymentResult(
                success=False,
                transaction_id=None,
                pending=False,
                note=None,
                error=f"invalid amount: {amount!r} (must be > 0)",
            )
        tx_id = self._deterministic_tx_id(
            self._asset, self._network, amount, recipient, self._scheme, ""
        )
        self._settled[tx_id] = self._settled.get(tx_id, 0.0) + amount
        return MockPaymentResult(
            success=True,
            transaction_id=tx_id,
            pending=False,
            note="mock settlement",
        )

    # ─── Extended economic-bus methods ─────────────────────────────────

    def quote(
        self, amount: float, currency: str, recipient: str, scheme: str
    ) -> Quote:
        """Return a deterministic quote. Invalid amount raises ValueError."""
        self._validate_amount(amount)
        return Quote(
            asset=self._asset,
            network=self._network,
            amount=amount,
            recipient=recipient,
            scheme=scheme or self._scheme,
            provider=PROVIDER_NAME,
            metadata={"currency": currency},
        )

    def request_payment(self, req: PaymentRequest) -> PaymentReceipt:
        """Process a payment request.

        Validation order: amount → asset → network. Idempotent on
        ``metadata["idempotency_key"]`` — a replayed key returns the
        original receipt unchanged and does NOT double-settle.
        """
        self._validate_amount(req.amount)
        if req.asset != self._asset:
            raise ValueError(
                f"wrong asset: {req.asset!r} (provider accepts {self._asset!r})"
            )
        if req.network != self._network:
            raise ValueError(
                f"wrong network: {req.network!r} (provider accepts {self._network!r})"
            )

        key = self._idempotency_key(req)
        existing = self._receipts.get(key)
        if existing is not None:
            return existing  # replay — same receipt, no double-settle

        tx_id = self._deterministic_tx_id(
            req.asset, req.network, req.amount, req.recipient, req.scheme, key
        )
        receipt = PaymentReceipt(
            asset=req.asset,
            network=req.network,
            amount=req.amount,
            recipient=req.recipient,
            scheme=req.scheme,
            provider=PROVIDER_NAME,
            transaction_id=tx_id,
            metadata={"idempotency_key": key},
        )
        self._receipts[key] = receipt
        self._settled[tx_id] = req.amount  # settle exactly once
        return receipt

    def verify(self, receipt: PaymentReceipt) -> bool:
        """Verify a receipt against the mock ledger.

        True only if this provider issued the receipt and it has not been
        refunded.
        """
        stored = self._receipts.get(self._idempotency_key_from_receipt(receipt))
        if stored is None or stored.transaction_id != receipt.transaction_id:
            return False
        if self._refunded.get(receipt.transaction_id, False):
            return False
        return True

    def refund(self, receipt: PaymentReceipt) -> MockPaymentResult:
        """Refund a previously issued receipt. Idempotent per receipt."""
        if not self.verify(receipt):
            return MockPaymentResult(
                success=False,
                transaction_id=receipt.transaction_id,
                pending=False,
                note=None,
                error="refund rejected: receipt not verifiable",
            )
        self._refunded[receipt.transaction_id] = True
        self._settled.pop(receipt.transaction_id, None)
        return MockPaymentResult(
            success=True,
            transaction_id=receipt.transaction_id,
            pending=False,
            note="mock refund",
        )

    # ─── Introspection helpers (test-only) ─────────────────────────────

    def settled_amount(self, transaction_id: str) -> float:
        """Return total settled amount for a transaction (0 if none)."""
        return self._settled.get(transaction_id, 0.0)

    def usage(self, agent: str) -> int:
        """Return accumulated token usage for an agent."""
        return self._usage.get(agent, 0)

    # ─── Internals ─────────────────────────────────────────────────────

    @staticmethod
    def _validate_amount(amount: float) -> None:
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise ValueError(f"invalid amount: {amount!r} (must be numeric)")
        if amount <= 0:
            raise ValueError(f"invalid amount: {amount!r} (must be > 0)")

    @staticmethod
    def _idempotency_key(req: PaymentRequest) -> str:
        key = req.metadata.get("idempotency_key")
        if key:
            return str(key)
        # Fall back to a deterministic content hash so identical requests
        # without an explicit key are still idempotent.
        payload = f"{req.asset}|{req.network}|{req.amount}|{req.recipient}|{req.scheme}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _idempotency_key_from_receipt(receipt: PaymentReceipt) -> str:
        key = receipt.metadata.get("idempotency_key")
        if key:
            return str(key)
        payload = (
            f"{receipt.asset}|{receipt.network}|{receipt.amount}|"
            f"{receipt.recipient}|{receipt.scheme}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _deterministic_tx_id(
        asset: str,
        network: str,
        amount: float,
        recipient: str,
        scheme: str,
        key: str,
    ) -> str:
        payload = f"{asset}|{network}|{amount}|{recipient}|{scheme}|{key}"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"mock-tx-{digest[:16]}"


__all__ = [
    "MockPaymentProvider",
    "MockPaymentResult",
    "MockQuotaStatus",
    "PROVIDER_NAME",
]
