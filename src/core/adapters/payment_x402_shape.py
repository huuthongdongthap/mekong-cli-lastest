# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""x402 protocol-shape helpers — pure data encode/decode only.

This module models the *shape* of the x402 payment protocol:
- ``PaymentRequired`` — the 402 response body a server would send.
- ``X-PAYMENT`` header — the base64-encoded payment payload a client
  would attach to a retried request.

REAL SETTLEMENT DEFERRED: this module performs NO network calls, holds NO
wallet, signs NOTHING, and moves NO money. It is a data-shape codec used
by tests and future adapters. x402 is one scheme among many — the
PaymentProvider protocol is scheme-agnostic (see MockPaymentProvider for
the polymorphism proof).

Security (§18): payloads carry only public payment parameters
(asset/network/amount/recipient/scheme). Private keys, seed phrases, and
signatures are explicitly out of scope and rejected on decode.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import Any, Dict

X_PAYMENT_HEADER = "X-PAYMENT"
X402_SCHEME = "exact"
X402_VERSION = 1

# Field names that must never appear in an x402-shaped payload (§18).
_FORBIDDEN_FIELDS = frozenset(
    {"private_key", "privateKey", "seed", "seed_phrase", "mnemonic", "secret", "secret_key"}
)


@dataclass(frozen=True)
class PaymentRequired:
    """Pure-data shape of an HTTP 402 Payment Required response body."""

    x402_version: int
    accepts_asset: str
    accepts_network: str
    amount: str  # string-encoded per x402 convention (atomic units)
    recipient: str
    scheme: str = X402_SCHEME
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class XPaymentPayload:
    """Pure-data shape of the decoded X-PAYMENT header value."""

    x402_version: int
    scheme: str
    asset: str
    network: str
    amount: str
    recipient: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class X402ShapeError(ValueError):
    """Raised when an x402-shaped payload fails validation."""


def encode_payment_required(pr: PaymentRequired) -> Dict[str, Any]:
    """Serialize a PaymentRequired to a JSON-safe dict."""
    _validate_amount_str(pr.amount)
    return {
        "x402Version": pr.x402_version,
        "accepts": [
            {
                "asset": pr.accepts_asset,
                "network": pr.accepts_network,
                "amount": pr.amount,
                "recipient": pr.recipient,
                "scheme": pr.scheme,
            }
        ],
        "metadata": dict(pr.metadata),
    }


def decode_payment_required(body: Dict[str, Any]) -> PaymentRequired:
    """Parse and validate a 402 response body dict into PaymentRequired."""
    _reject_forbidden_fields(body)
    version = body.get("x402Version")
    if version != X402_VERSION:
        raise X402ShapeError(f"unsupported x402Version: {version!r}")
    accepts = body.get("accepts")
    if not isinstance(accepts, list) or len(accepts) != 1:
        raise X402ShapeError("accepts must be a list with exactly one entry")
    entry = accepts[0]
    if not isinstance(entry, dict):
        raise X402ShapeError("accepts[0] must be an object")
    for required in ("asset", "network", "amount", "recipient"):
        if not entry.get(required):
            raise X402ShapeError(f"accepts[0] missing field: {required}")
    _validate_amount_str(str(entry["amount"]))
    return PaymentRequired(
        x402_version=int(version),
        accepts_asset=str(entry["asset"]),
        accepts_network=str(entry["network"]),
        amount=str(entry["amount"]),
        recipient=str(entry["recipient"]),
        scheme=str(entry.get("scheme", X402_SCHEME)),
        metadata=dict(body.get("metadata") or {}),
    )


def encode_x_payment_header(payload: XPaymentPayload) -> str:
    """Encode an XPaymentPayload into the X-PAYMENT header value (base64 JSON)."""
    if payload.scheme != X402_SCHEME:
        raise X402ShapeError(f"unsupported scheme: {payload.scheme!r}")
    _validate_amount_str(payload.amount)
    body = {
        "x402Version": payload.x402_version,
        "scheme": payload.scheme,
        "asset": payload.asset,
        "network": payload.network,
        "amount": payload.amount,
        "recipient": payload.recipient,
        "metadata": dict(payload.metadata),
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def decode_x_payment_header(header_value: str) -> XPaymentPayload:
    """Decode and validate an X-PAYMENT header value into XPaymentPayload."""
    try:
        raw = base64.b64decode(header_value.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise X402ShapeError(f"X-PAYMENT header is not valid base64: {exc}") from exc
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise X402ShapeError(f"X-PAYMENT header is not valid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise X402ShapeError("X-PAYMENT payload must be a JSON object")
    _reject_forbidden_fields(body)
    if body.get("x402Version") != X402_VERSION:
        raise X402ShapeError(f"unsupported x402Version: {body.get('x402Version')!r}")
    if body.get("scheme") != X402_SCHEME:
        raise X402ShapeError(f"unsupported scheme: {body.get('scheme')!r}")
    for required in ("asset", "network", "amount", "recipient"):
        if not body.get(required):
            raise X402ShapeError(f"X-PAYMENT payload missing field: {required}")
    _validate_amount_str(str(body["amount"]))
    return XPaymentPayload(
        x402_version=int(body["x402Version"]),
        scheme=str(body["scheme"]),
        asset=str(body["asset"]),
        network=str(body["network"]),
        amount=str(body["amount"]),
        recipient=str(body["recipient"]),
        metadata=dict(body.get("metadata") or {}),
    )


def _validate_amount_str(amount: str) -> None:
    """Amount must be a positive integer in atomic units (x402 convention)."""
    try:
        value = int(amount)
    except (TypeError, ValueError) as exc:
        raise X402ShapeError(f"amount must be an integer string, got {amount!r}") from exc
    if value <= 0:
        raise X402ShapeError(f"amount must be > 0, got {value}")


def _reject_forbidden_fields(body: Dict[str, Any]) -> None:
    """Reject payloads carrying key-like fields (§18 secret hygiene)."""
    found = _FORBIDDEN_FIELDS.intersection(body.keys())
    if found:
        raise X402ShapeError(f"forbidden key-like field(s) in payload: {sorted(found)}")


__all__ = [
    "PaymentRequired",
    "XPaymentPayload",
    "X402ShapeError",
    "X_PAYMENT_HEADER",
    "X402_SCHEME",
    "X402_VERSION",
    "encode_payment_required",
    "decode_payment_required",
    "encode_x_payment_header",
    "decode_x_payment_header",
]
