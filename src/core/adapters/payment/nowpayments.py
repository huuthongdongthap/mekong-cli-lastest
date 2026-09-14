# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""NOWPayments alias module (Economic Bus / PaymentProvider).

Thin alias providing the import path ``src.core.adapters.payment.nowpayments``
re-exporting ``NowPaymentsProvider`` from ``src.raas.nowpayments_provider``.
Does NOT reimplement or copy any settlement or webhook logic.
"""

from __future__ import annotations

from src.raas.nowpayments_provider import NowPaymentsProvider

__all__ = [
    "NowPaymentsProvider",
]
