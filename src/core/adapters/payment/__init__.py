# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Payment adapters package (Lane E4 + E7).

Canonical implementations live alongside this package:
- ``src.core.adapters.payment_x402.py`` — X402SettlementProvider (415 LOC, 31 tests)
- ``src.core.adapters.payment_x402_shape.py`` — pure-data x402 codec
- ``src.core.adapters.payment_mock.py`` — MockPaymentProvider (in-memory)
- ``src.core.adapters.payment.mpp.py`` — MPPSettlementProvider (Lane E4)
- ``src.core.adapters.payment.x402_gate.py`` — server-side pricing gate (Lane E7)
- ``src.core.adapters.payment.x402_gate_wiring.py`` — runtime injection point

This package re-exports the public names so callers can import under
``src.core.adapters.payment.*`` without touching the protected canonical
files. It is a thin alias layer — no settlement logic lives here.
"""

from __future__ import annotations

from .nowpayments import NowPaymentsProvider
from .x402_gate import (
    GateConfig,
    GateDecision,
    X402PricingGate,
    X402GateError,
    enforce_x402_gate,
)
from .x402_gate_wiring import (
    PaymentGateExecutionRuntime,
    wrap_with_x402_gate,
)

__all__ = [
    "GateConfig",
    "GateDecision",
    "NowPaymentsProvider",
    "X402PricingGate",
    "X402GateError",
    "enforce_x402_gate",
    "PaymentGateExecutionRuntime",
    "wrap_with_x402_gate",
]