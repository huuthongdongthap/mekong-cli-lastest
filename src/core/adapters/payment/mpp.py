# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""MPPSettlementProvider — fail-closed MPP settlement behind PaymentProvider.

Same 7-method shape as X402SettlementProvider, adapted to scheme "mpp".

Invariants (mirroring proven x402): explicit config required (MPPConfigError
on missing — never default-allow); governance-gated settle/request/refund
(denial fails closed before transport); injected transport only, no sockets;
scheme-agnostic executable code (no USDT hardcoded); §18 out of scope.

Data/shape/codec types live in ``mpp_data.py`` / ``mpp_shape.py``; this
file owns the provider class end-to-end (constructor, config validation,
settlement logic) like the canonical ``payment_x402.py``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from src.core.governance import ActionClass, GovernanceDecision
from src.core.protocols import PaymentReceipt, PaymentRequest, Quote

from .mpp_data import (
    ApprovalGate,
    MPPPaymentResult,
    MPPQuotaStatus,
    MPPReplayError,
    MPPSettlementError,
    MPPTransport,
    PROVIDER_NAME,
    _REQUIRED_FIELDS,
)
from .mpp_shape import MPP_SCHEME, encode_mpp_quote, reject_forbidden_fields

logger = logging.getLogger(__name__)


class MPPConfigError(ValueError):
    """Raised when explicit MPP settlement config is missing or invalid."""


class MPPSettlementProvider:
    """Fail-closed MPP settlement provider (PaymentProvider shape).

    Satisfies the extended PaymentProvider protocol (src.core.protocols).
    Holds no keys, creates no wallets, never opens a socket directly.
    """

    def __init__(
        self,
        *,
        endpoint: Optional[str],
        asset: Optional[str],
        network: Optional[str],
        recipient: Optional[str],
        governance: Optional[ApprovalGate],
        transport: Optional[MPPTransport],
    ) -> None:
        config = dict(endpoint=endpoint, asset=asset, network=network, recipient=recipient)
        for name in _REQUIRED_FIELDS:
            value = config[name]
            if not isinstance(value, str) or not value.strip():
                raise MPPConfigError(f"missing required mpp config: {name} (never default-allow)")
        if governance is None or not callable(getattr(governance, "request_approval", None)):
            raise MPPConfigError("missing required mpp config: governance approval gate")
        if transport is None or not callable(transport):
            raise MPPConfigError("missing required mpp config: injected transport callable")
        self._endpoint = str(endpoint).strip()
        self._asset = str(asset).strip()
        self._network = str(network).strip()
        self._recipient = str(recipient).strip()
        self._governance = governance
        self._transport = transport
        self._receipts: Dict[str, PaymentReceipt] = {}
        self._refunded: Dict[str, bool] = {}
        self._usage: Dict[str, int] = {}

    # ─── Legacy PaymentProvider methods ────────────────────────────────

    def record_usage(self, agent: str, tokens: int, model: str) -> None:
        """Accumulate token usage per agent (in-memory only)."""
        self._usage[agent] = self._usage.get(agent, 0) + max(0, int(tokens))

    def check_quota(self, org_id: str) -> MPPQuotaStatus:
        """Return quota status — this provider grants no free quota (fail-closed)."""
        return MPPQuotaStatus(
            remaining_mcu=0,
            total_mcu=0,
            tier="MPP",
            reset_at="1970-01-01T00:00:00Z",
        )

    def settle_payment(self, amount: float, currency: str, recipient: str) -> MPPPaymentResult:
        """Settle via the injected transport. Any failure path returns an
        explicit error result — never a silent or default success."""
        try:
            receipt = self._settle(
                PaymentRequest(
                    asset=self._asset,
                    network=self._network,
                    amount=amount,
                    recipient=recipient,
                    scheme=MPP_SCHEME,
                    provider=PROVIDER_NAME,
                    metadata={"idempotency_key": uuid.uuid4().hex, "currency": currency},
                ),
                action="settle_payment",
            )
            return MPPPaymentResult(
                success=True,
                transaction_id=receipt.transaction_id,
                note="mpp settlement confirmed by transport",
            )
        except ValueError as exc:  # fail closed on every rejection path
            return MPPPaymentResult(success=False, error=str(exc))

    # ─── Extended economic-bus methods ─────────────────────────────────

    def quote(self, amount: float, currency: str, recipient: str, scheme: str) -> Quote:
        """Return a quote whose payload is the encoded MPP quote shape."""
        self._validate_amount(amount)
        if scheme and scheme != MPP_SCHEME:
            raise ValueError(f"unsupported scheme: {scheme!r} (mpp uses {MPP_SCHEME!r})")
        self._require_recipient(recipient)
        return Quote(
            asset=self._asset,
            network=self._network,
            amount=amount,
            recipient=self._recipient,
            scheme=MPP_SCHEME,
            provider=PROVIDER_NAME,
            metadata={
                "currency": currency,
                "payment_required": encode_mpp_quote(
                    self._asset, self._network, amount, self._recipient
                ),
            },
        )

    def request_payment(self, req: PaymentRequest) -> PaymentReceipt:
        """Process a payment request: validate → governance approval → transport.

        Replayed idempotency keys are REJECTED (fail-closed, no double-settle).
        """
        self._validate_amount(req.amount)
        return self._settle(req, action="request_payment")

    def verify(self, receipt: PaymentReceipt) -> bool:
        """True only if this provider issued the receipt and it is unrefunded."""
        if receipt.provider != PROVIDER_NAME:
            return False
        if receipt.asset != self._asset or receipt.network != self._network:
            return False
        key = receipt.metadata.get("idempotency_key")
        if not key:
            return False
        stored = self._receipts.get(str(key))
        if stored is None or stored.transaction_id != receipt.transaction_id:
            return False
        return not self._refunded.get(receipt.transaction_id, False)

    def refund(self, receipt: PaymentReceipt) -> MPPPaymentResult:
        """Refund a verified receipt — also governance-gated (fail-closed)."""
        if not self.verify(receipt):
            return MPPPaymentResult(
                success=False,
                transaction_id=receipt.transaction_id,
                error="refund rejected: receipt not verifiable",
            )
        try:
            self._require_approval("refund", receipt.transaction_id)
        except MPPSettlementError as exc:
            return MPPPaymentResult(
                success=False, transaction_id=receipt.transaction_id, error=str(exc)
            )
        self._refunded[receipt.transaction_id] = True
        return MPPPaymentResult(
            success=True, transaction_id=receipt.transaction_id, note="mpp refund recorded"
        )

    # ─── Introspection helpers ─────────────────────────────────────────

    def usage(self, agent: str) -> int:
        """Return accumulated token usage for an agent."""
        return self._usage.get(agent, 0)

    # ─── Internals ─────────────────────────────────────────────────────

    def _settle(self, req: PaymentRequest, action: str) -> PaymentReceipt:
        """Shared fail-closed settlement core for settle/request paths."""
        self._validate_amount(req.amount)
        if req.asset != self._asset:
            raise ValueError(f"wrong asset: {req.asset!r} (provider accepts {self._asset!r})")
        if req.network != self._network:
            raise ValueError(f"wrong network: {req.network!r} (provider accepts {self._network!r})")
        if req.scheme != MPP_SCHEME:
            raise ValueError(f"unsupported scheme: {req.scheme!r} (mpp uses {MPP_SCHEME!r})")
        self._require_recipient(req.recipient)
        reject_forbidden_fields(dict(req.metadata))  # §18 secret hygiene

        key = str(req.metadata.get("idempotency_key") or uuid.uuid4().hex)
        if key in self._receipts:
            raise MPPReplayError("replayed idempotency key rejected: duplicate settlement attempt")

        self._require_approval(action, f"{req.asset}:{req.network}:{req.amount}")

        body = encode_mpp_quote(req.asset, req.network, req.amount, req.recipient)
        # Log public payment parameters only — never headers or metadata values.
        logger.info("mpp %s: asset=%s network=%s amount=%s", action, req.asset, req.network, req.amount)
        try:
            response = self._transport(self._endpoint, {"X-MPP-PAYMENT": key}, body)
        except Exception as exc:
            raise MPPSettlementError(f"transport failure: {action} aborted ({type(exc).__name__})") from exc
        tx_id = self._validated_tx(response)

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
        return receipt

    def _require_approval(self, action: str, detail: str) -> None:
        """Route the action through governance; denial fails closed."""
        decision = GovernanceDecision(
            action_class=ActionClass.REVIEW_REQUIRED,
            reason=f"mpp {action} requires governance approval",
            requires_approval=True,
        )
        if not self._governance.request_approval(f"mpp:{action}:{detail}", decision):
            raise MPPSettlementError(f"governance approval denied for {action}: settlement blocked")

    def _require_recipient(self, recipient: str) -> None:
        """Fail-closed: only the explicitly configured recipient is payable."""
        if recipient != self._recipient:
            raise ValueError("recipient mismatch: provider settles only to the configured recipient")

    @staticmethod
    def _validated_tx(response: Any) -> str:
        """Accept only an explicit confirmed response carrying a transaction id."""
        if not isinstance(response, dict) or response.get("success") is not True:
            raise MPPSettlementError("transport response rejected: no confirmed settlement")
        tx_id = response.get("transaction_id")
        if not isinstance(tx_id, str) or not tx_id.strip():
            raise MPPSettlementError("transport response missing transaction_id")
        return tx_id

    @staticmethod
    def _validate_amount(amount: Any) -> None:
        """Reject non-numeric, boolean, or non-positive amounts."""
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise ValueError(f"invalid amount: {amount!r} (must be numeric)")
        if amount <= 0:
            raise ValueError(f"invalid amount: {amount!r} (must be > 0)")


__all__ = [
    "MPPSettlementProvider",
    "MPPConfigError",
    "MPPPaymentResult",
    "MPPQuotaStatus",
    "MPPTransport",
    "PROVIDER_NAME",
    "MPPReplayError",
    "MPPSettlementError",
]
