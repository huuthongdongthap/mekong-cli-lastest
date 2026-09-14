# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""MPP protocol-shape helpers — pure data encode/decode only.

Models the *shape* of the MPP payment protocol: a quote payload is a
plain JSON object carrying asset/network/amount/recipient/scheme. This
module performs NO network calls, holds NO wallet, signs NOTHING, and
moves NO money. MPP is one scheme among many; the PaymentProvider
protocol is scheme-agnostic.

Security (§18): payloads carry only public payment parameters
(asset/network/amount/recipient/scheme). Private keys, seed phrases, and
signatures are explicitly out of scope and rejected on decode.
"""

from __future__ import annotations

from typing import Any, Dict

MPP_SCHEME = "mpp"

# Field names that must never appear in an MPP-shaped payload (§18).
_FORBIDDEN_FIELDS = frozenset(
    {"private_key", "privateKey", "seed", "seed_phrase", "mnemonic", "secret", "secret_key"}
)


class MPPShapeError(ValueError):
    """Raised when an MPP-shaped payload fails validation."""


def reject_forbidden_fields(payload: Dict[str, Any]) -> None:
    """Reject payloads carrying key-like fields (§18 secret hygiene)."""
    found = _FORBIDDEN_FIELDS.intersection(payload.keys())
    if found:
        raise MPPShapeError(f"forbidden key-like field(s) in payload: {sorted(found)}")


def encode_mpp_quote(asset: str, network: str, amount: float, recipient: str) -> Dict[str, Any]:
    """Serialize a quote into a JSON-safe MPP payload dict."""
    if not asset or not network or not recipient:
        raise MPPShapeError("quote encode: asset/network/recipient required")
    return {
        "scheme": MPP_SCHEME,
        "asset": asset,
        "network": network,
        "amount": amount,
        "recipient": recipient,
    }


def decode_mpp_quote(body: Dict[str, Any]) -> Dict[str, Any]:
    """Decode and validate an MPP quote payload, fail-closed."""
    reject_forbidden_fields(body)
    if not isinstance(body, dict):
        raise MPPShapeError("mpp payload must be an object")
    for required in ("asset", "network", "amount", "recipient"):
        if not body.get(required):
            raise MPPShapeError(f"mpp payload missing field: {required}")
    return body


__all__ = [
    "MPPShapeError",
    "MPP_SCHEME",
    "reject_forbidden_fields",
    "encode_mpp_quote",
    "decode_mpp_quote",
]