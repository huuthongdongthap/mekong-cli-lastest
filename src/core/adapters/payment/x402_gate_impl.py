"""Implementation of the x402 pricing gate: nonce registry and the gate
class itself. Split from the type definitions so each module stays focused
and under the LOC limit. The gate class imports its own config/decision
types; helpers import this module for the class and re-export the public
wrapper."""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from .x402_gate_types import GateConfig, GateDecision, X402GateError, _REFUSED_STATUS, _ALLOWED_STATUS
from ..payment_x402_shape import X_PAYMENT_HEADER, XPaymentPayload, decode_x_payment_header


def _lookup_header(headers: Dict[str, Any], name: str) -> Optional[Any]:
    if not isinstance(headers, dict):
        return None
    lowered = name.lower()
    return next((value for key, value in headers.items() if isinstance(key, str) and key.lower() == lowered), None)


def _replay_key(payload: XPaymentPayload, *, nonce: Optional[str] = None) -> str:
    if nonce:
        return str(nonce)
    key = (payload.metadata or {}).get("idempotency_key")
    if isinstance(key, str) and key.strip():
        return key
    return f"{payload.asset}|{payload.network}|{payload.amount}|{payload.recipient}"


class _NonceSet:
    """Thread-safe in-memory nonce registry (replay protection).

    Bounded to the process lifetime; replays within a single gate instance
    are rejected. This is an in-memory store by design (§18): no durable
    ledger, no persistence, no network.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def consume(self, nonce: str) -> bool:
        """Return True if the nonce is fresh and mark it consumed.

        Returns False on a replay. Non-empty non-str input is refused.
        """
        if not isinstance(nonce, str) or not nonce.strip():
            return False
        with self._lock:
            if nonce in self._seen:
                return False
            self._seen.add(nonce)
            return True


class X402PricingGate:
    """Server-side gate for the ``X-PAYMENT`` header.

    Construct once per process with the expected settlement shape. Every
    call to :meth:`enforce` is hermetic: no I/O, no secrets, no transport.
    """

    def __init__(self, expected: GateConfig) -> None:
        if not isinstance(expected, GateConfig):
            raise X402GateError("expected must be a GateConfig instance")
        for name in ("asset", "network", "amount", "recipient"):
            value = getattr(expected, name)
            if not isinstance(value, str) or not value.strip():
                raise X402GateError(f"GateConfig.{name} must be a non-empty string")
        self._expected = expected
        self._nonces = _NonceSet()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def enforce(
        self, headers: Dict[str, Any], body: Dict[str, Any], *, nonce: Optional[str] = None
    ) -> GateDecision:
        """Evaluate one inbound request against the expected settlement.

        ``headers`` is the full request header map (case-insensitive key
        lookup); ``body`` is accepted but not inspected — x402 carries
        payment in the header. ``nonce`` overrides the replay key; when
        omitted the payload's ``metadata.idempotency_key`` is used,
        falling back to a content hash so a header without an explicit key
        still gets one-shot protection.

        Returns a GateDecision. Never raises: any internal error maps to a
        refusal (fail-closed on crash).
        """
        try:
            return self._enforce(headers, body, nonce=nonce)
        except Exception as exc:  # fail-closed: never trust a crashing gate
            return GateDecision(allowed=False, status=_REFUSED_STATUS, reason=f"gate error: {type(exc).__name__}")

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _enforce(
        self, headers: Dict[str, Any], body: Dict[str, Any], *, nonce: Optional[str] = None
    ) -> GateDecision:
        header_value = _lookup_header(headers, X_PAYMENT_HEADER)
        if header_value is None:
            return GateDecision(
                allowed=False,
                status=_REFUSED_STATUS,
                reason="payment_required",
            )
        try:
            payload = decode_x_payment_header(str(header_value))
        except Exception as exc:
            return GateDecision(
                allowed=False,
                status=_REFUSED_STATUS,
                reason=f"invalid_x_payment: {type(exc).__name__}",
            )
        return self._check_payload(payload, nonce=nonce)

    def _check_payload(
        self, payload: XPaymentPayload, *, nonce: Optional[str] = None
    ) -> GateDecision:
        expected = self._expected
        if payload.scheme != expected.scheme:
            return GateDecision(
                allowed=False,
                status=_REFUSED_STATUS,
                reason=f"scheme_mismatch: got {payload.scheme!r}, want {expected.scheme!r}",
            )
        if payload.asset != expected.asset:
            return GateDecision(
                allowed=False,
                status=_REFUSED_STATUS,
                reason=f"asset_mismatch: got {payload.asset!r}, want {expected.asset!r}",
            )
        if payload.network != expected.network:
            return GateDecision(
                allowed=False,
                status=_REFUSED_STATUS,
                reason=f"network_mismatch: got {payload.network!r}, want {expected.network!r}",
            )
        if payload.recipient != expected.recipient:
            return GateDecision(
                allowed=False,
                status=_REFUSED_STATUS,
                reason="recipient_mismatch: sender not the configured recipient",
            )
        if payload.amount != expected.amount:
            return GateDecision(
                allowed=False,
                status=_REFUSED_STATUS,
                reason=f"amount_mismatch: got {payload.amount!r}, want {expected.amount!r}",
            )
        key = _replay_key(payload, nonce=nonce)
        if not self._nonces.consume(key):
            return GateDecision(
                allowed=False,
                status=_REFUSED_STATUS,
                reason="replay_detected: idempotency key already consumed",
            )
        return GateDecision(allowed=True, status=_ALLOWED_STATUS, reason="ok")


__all__ = ["X402PricingGate"]
