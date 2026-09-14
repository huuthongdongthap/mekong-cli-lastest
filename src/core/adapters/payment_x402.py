# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""X402SettlementProvider — fail-closed x402 settlement behind PaymentProvider.

Policy-gated, hermetic settlement provider for the economic bus:

- Explicit config: endpoint/asset/network/recipient are ALL required;
  missing or blank config raises X402ConfigError (never default-allow).
- Governance-gated: settle_payment/request_payment/refund go through
  Governance.request_approval; denial fails closed before any transport.
- Injected transport only: this module opens no sockets itself; every
  network hop goes through the transport callable supplied at build time.
- Shape codec reuse: quote/request payloads are encoded/decoded with
  payment_x402_shape (scheme "exact"); key-like fields are rejected
  (§18 secret hygiene) and secrets are never logged.
- Out of scope by design: wallet creation, custody, key storage, real
  money. Settlement is confirmed only by the transport response.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from src.core.governance import ActionClass, GovernanceDecision
from src.core.protocols import PaymentReceipt, PaymentRequest, Quote

from .payment_x402_shape import (
    X402_SCHEME,
    X402_VERSION,
    X_PAYMENT_HEADER,
    PaymentRequired,
    XPaymentPayload,
    _reject_forbidden_fields,
    encode_payment_required,
    encode_x_payment_header,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "x402"
ATOMIC_DECIMALS = 6  # atomic-unit scaling (1.0 -> 1_000_000, USDC convention)
_REQUIRED_FIELDS = ("endpoint", "asset", "network", "recipient")


class X402ConfigError(ValueError):
    """Raised when explicit x402 settlement config is missing or invalid."""


class X402ReplayError(ValueError):
    """Raised when a replayed idempotency key is rejected (fail-closed)."""


class X402SettlementError(ValueError):
    """Raised when settlement fails closed (approval, transport, response)."""


class X402Transport(Protocol):
    """Injected transport — the ONLY network seam this provider uses."""

    def __call__(
        self, endpoint: str, headers: Dict[str, str], body: Dict[str, Any]
    ) -> Dict[str, Any]: ...


class ApprovalGate(Protocol):
    """Governance seam — mirrors Governance.request_approval."""

    def request_approval(self, goal: str, decision: GovernanceDecision) -> bool: ...


@dataclass(frozen=True)
class X402QuotaStatus:
    """Concrete QuotaStatus-shaped carrier (satisfies the Protocol structurally)."""

    remaining_mcu: int
    total_mcu: int
    tier: str
    reset_at: str


@dataclass(frozen=True)
class X402PaymentResult:
    """Concrete PaymentResult-shaped carrier (satisfies the Protocol structurally)."""

    success: bool
    transaction_id: Optional[str] = None
    pending: bool = False
    note: Optional[str] = None
    error: Optional[str] = None


class X402SettlementProvider:
    """Fail-closed x402 settlement provider.

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
        transport: Optional[X402Transport],
    ) -> None:
        config = {
            "endpoint": endpoint,
            "asset": asset,
            "network": network,
            "recipient": recipient,
        }
        for name in _REQUIRED_FIELDS:
            value = config[name]
            if not isinstance(value, str) or not value.strip():
                raise X402ConfigError(
                    f"missing required x402 config: {name} (never default-allow)"
                )
        if governance is None or not callable(
            getattr(governance, "request_approval", None)
        ):
            raise X402ConfigError(
                "missing required x402 config: governance approval gate"
            )
        if transport is None or not callable(transport):
            raise X402ConfigError(
                "missing required x402 config: injected transport callable"
            )
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

    def check_quota(self, org_id: str) -> X402QuotaStatus:
        """Return quota status — this provider grants no free quota (fail-closed)."""
        return X402QuotaStatus(
            remaining_mcu=0,
            total_mcu=0,
            tier="X402",
            reset_at="1970-01-01T00:00:00Z",
        )

    def settle_payment(
        self, amount: float, currency: str, recipient: str
    ) -> X402PaymentResult:
        """Settle via the injected transport. Any failure path returns an
        explicit error result — never a silent or default success."""
        try:
            key = self._content_key(
                self._asset, self._network, self._to_atomic(amount), recipient
            )
            req = PaymentRequest(
                asset=self._asset,
                network=self._network,
                amount=amount,
                recipient=recipient,
                scheme=X402_SCHEME,
                provider=PROVIDER_NAME,
                metadata={"idempotency_key": key, "currency": currency},
            )
            receipt = self._settle(req, action="settle_payment")
            return X402PaymentResult(
                success=True,
                transaction_id=receipt.transaction_id,
                pending=False,
                note="x402 settlement confirmed by transport",
            )
        except ValueError as exc:  # fail closed on every rejection path
            return X402PaymentResult(
                success=False, transaction_id=None, pending=False, error=str(exc)
            )

    # ─── Extended economic-bus methods ─────────────────────────────────

    def quote(
        self, amount: float, currency: str, recipient: str, scheme: str
    ) -> Quote:
        """Return a quote whose payload is the encoded x402 PaymentRequired shape."""
        atomic = self._to_atomic(amount)
        if scheme and scheme != X402_SCHEME:
            raise ValueError(f"unsupported scheme: {scheme!r} (x402 uses {X402_SCHEME!r})")
        self._require_recipient(recipient)
        payment_required = encode_payment_required(
            PaymentRequired(
                x402_version=X402_VERSION,
                accepts_asset=self._asset,
                accepts_network=self._network,
                amount=atomic,
                recipient=self._recipient,
            )
        )
        return Quote(
            asset=self._asset,
            network=self._network,
            amount=amount,
            recipient=self._recipient,
            scheme=X402_SCHEME,
            provider=PROVIDER_NAME,
            metadata={
                "currency": currency,
                "atomic_amount": atomic,
                "payment_required": payment_required,
            },
        )

    def request_payment(self, req: PaymentRequest) -> PaymentReceipt:
        """Process a payment request: validate → governance approval → transport.

        Replayed idempotency keys are REJECTED (fail-closed, no double-settle).
        """
        self._to_atomic(req.amount)
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

    def refund(self, receipt: PaymentReceipt) -> X402PaymentResult:
        """Refund a verified receipt — also governance-gated (fail-closed)."""
        if not self.verify(receipt):
            return X402PaymentResult(
                success=False,
                transaction_id=receipt.transaction_id,
                pending=False,
                error="refund rejected: receipt not verifiable",
            )
        try:
            self._require_approval("refund", receipt.transaction_id)
        except X402SettlementError as exc:
            return X402PaymentResult(
                success=False,
                transaction_id=receipt.transaction_id,
                pending=False,
                error=str(exc),
            )
        self._refunded[receipt.transaction_id] = True
        return X402PaymentResult(
            success=True,
            transaction_id=receipt.transaction_id,
            pending=False,
            note="x402 refund recorded",
        )

    # ─── Introspection helpers (test-only) ─────────────────────────────

    def usage(self, agent: str) -> int:
        """Return accumulated token usage for an agent."""
        return self._usage.get(agent, 0)

    # ─── Internals ─────────────────────────────────────────────────────

    def _settle(self, req: PaymentRequest, action: str) -> PaymentReceipt:
        """Shared fail-closed settlement core for settle/request paths."""
        if req.asset != self._asset:
            raise ValueError(
                f"wrong asset: {req.asset!r} (provider accepts {self._asset!r})"
            )
        if req.network != self._network:
            raise ValueError(
                f"wrong network: {req.network!r} (provider accepts {self._network!r})"
            )
        if req.scheme != X402_SCHEME:
            raise ValueError(
                f"unsupported scheme: {req.scheme!r} (x402 uses {X402_SCHEME!r})"
            )
        self._require_recipient(req.recipient)
        _reject_forbidden_fields(dict(req.metadata))  # §18 secret hygiene
        atomic = self._to_atomic(req.amount)

        key = str(req.metadata.get("idempotency_key") or "")
        if not key:
            key = self._content_key(req.asset, req.network, atomic, req.recipient)
        if key in self._receipts:
            raise X402ReplayError(
                "replayed idempotency key rejected: duplicate settlement attempt"
            )

        self._require_approval(action, f"{req.asset}:{req.network}:{atomic}")

        header = encode_x_payment_header(
            XPaymentPayload(
                x402_version=X402_VERSION,
                scheme=X402_SCHEME,
                asset=req.asset,
                network=req.network,
                amount=atomic,
                recipient=req.recipient,
                metadata={"idempotency_key": key},
            )
        )
        body = encode_payment_required(
            PaymentRequired(
                x402_version=X402_VERSION,
                accepts_asset=req.asset,
                accepts_network=req.network,
                amount=atomic,
                recipient=req.recipient,
            )
        )
        # Log public payment parameters only — never headers or metadata values.
        logger.info(
            "x402 %s: asset=%s network=%s atomic_amount=%s",
            action,
            req.asset,
            req.network,
            atomic,
        )
        try:
            response = self._transport(self._endpoint, {X_PAYMENT_HEADER: header}, body)
        except Exception as exc:
            raise X402SettlementError(
                f"transport failure: {action} aborted ({type(exc).__name__})"
            ) from exc
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
            reason=f"x402 {action} requires governance approval",
            requires_approval=True,
        )
        if not self._governance.request_approval(f"x402:{action}:{detail}", decision):
            raise X402SettlementError(
                f"governance approval denied for {action}: settlement blocked"
            )

    def _require_recipient(self, recipient: str) -> None:
        """Fail-closed: only the explicitly configured recipient is payable."""
        if recipient != self._recipient:
            raise ValueError(
                "recipient mismatch: provider settles only to the configured recipient"
            )

    @staticmethod
    def _validated_tx(response: Any) -> str:
        """Accept only an explicit confirmed response carrying a transaction id."""
        if not isinstance(response, dict) or response.get("success") is not True:
            raise X402SettlementError(
                "transport response rejected: no confirmed settlement"
            )
        tx_id = response.get("transaction_id")
        if not isinstance(tx_id, str) or not tx_id.strip():
            raise X402SettlementError("transport response missing transaction_id")
        return tx_id

    @staticmethod
    def _to_atomic(amount: float) -> str:
        """Convert a positive numeric amount to an atomic-unit integer string."""
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise ValueError(f"invalid amount: {amount!r} (must be numeric)")
        if amount <= 0:
            raise ValueError(f"invalid amount: {amount!r} (must be > 0)")
        atomic = int(round(amount * 10**ATOMIC_DECIMALS))
        if atomic <= 0:
            raise ValueError(f"invalid amount: {amount!r} (rounds to zero atomic units)")
        return str(atomic)

    @staticmethod
    def _content_key(asset: str, network: str, atomic: str, recipient: str) -> str:
        payload = f"{asset}|{network}|{atomic}|{recipient}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


__all__ = [
    "X402SettlementProvider",
    "X402QuotaStatus",
    "X402PaymentResult",
    "X402ConfigError",
    "X402ReplayError",
    "X402SettlementError",
    "X402Transport",
    "ApprovalGate",
    "PROVIDER_NAME",
]
