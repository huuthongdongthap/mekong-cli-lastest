# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Server-side x402 pricing-header gate (Lane E7).

Decodes an inbound ``X-PAYMENT`` header and compares it against an
expected settlement shape. The caller receives a GateDecision; the gate
never raises on an invalid header, so a failed payment reads as
"connection refused" rather than a bypass.

Fail-closed: the gate is *off* by construction (no payment semantics in
the local runtime default); an explicit ``payment_gate`` injection enables
it. Any internal crash maps to a refusal — a crashing gate is never
trusted as a pass-through. Replay protection uses an in-memory nonce set.
No sockets, no transport, no secrets. The codec is reused verbatim from
``payment_x402_shape``; this module adds only the server-side check.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .x402_gate_types import GateConfig, GateDecision, X402GateError
from .x402_gate_impl import X402PricingGate


def enforce_x402_gate(
    headers: Dict[str, Any],
    body: Dict[str, Any],
    *,
    expected: GateConfig,
    nonce: Optional[str] = None,
) -> GateDecision:
    """Module-level convenience wrapper around :class:`X402PricingGate`."""
    return X402PricingGate(expected).enforce(headers, body, nonce=nonce)


__all__ = [
    "GateConfig",
    "GateDecision",
    "X402PricingGate",
    "X402GateError",
    "enforce_x402_gate",
]

