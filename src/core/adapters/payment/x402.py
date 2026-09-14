# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""x402 alias module (Lane E4).

DEPRECATION NOTE — alias, NOT a move:

The canonical implementation of X402SettlementProvider remains in
``src/core/adapters/payment_x402.py`` (415 LOC, 31 tests, protected
smoke in GH Actions). This module is a thin alias that provides the
import path ``src.core.adapters.payment.x402`` required by the Lane E4
package contract.

Anti-shim-patrol: this file re-exports ONLY the public names. It does
NOT reimplement, copy, or override any settlement logic. If a future
wave repoints importers to this path, the canonical file may be
consolidated — but that is a separate, explicit change, not this one.

Trade-off accepted: alias preserves 31 existing tests + protected smoke
untouched rather than churning them for a cosmetic path change.
"""

from __future__ import annotations

from src.core.adapters.payment_x402 import (
    X402ConfigError,
    X402ReplayError,
    X402SettlementError,
    X402SettlementProvider,
)

__all__ = [
    "X402SettlementProvider",
    "X402ConfigError",
    "X402ReplayError",
    "X402SettlementError",
]