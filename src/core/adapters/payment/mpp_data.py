# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""MPP data, error and protocol types — pure definitions, no settlement logic.

Split out of mpp.py so the settlement provider stays under the file-LOC
limit. This module imports only stdlib + dataclasses; ``src.core.governance``
and ``src.core.protocols`` stay out of it, so importing the data types is
free of any runtime dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

PROVIDER_NAME = "mpp"
_REQUIRED_FIELDS = ("endpoint", "asset", "network", "recipient")


class MPPConfigError(ValueError):
    """Missing or invalid explicit MPP settlement config."""


class MPPReplayError(ValueError):
    """Replayed idempotency key rejected (fail-closed)."""


class MPPSettlementError(ValueError):
    """Settlement failed closed (approval, transport, response)."""


class MPPTransport(Protocol):
    def __call__(self, endpoint: str, headers: Dict[str, str], body: Dict[str, Any]) -> Dict[str, Any]: ...


class ApprovalGate(Protocol):
    def request_approval(self, goal: str, decision: Any) -> bool: ...


@dataclass(frozen=True)
class MPPQuotaStatus:
    remaining_mcu: int
    total_mcu: int
    tier: str
    reset_at: str


@dataclass(frozen=True)
class MPPPaymentResult:
    success: bool
    transaction_id: Optional[str] = None
    pending: bool = False
    note: Optional[str] = None
    error: Optional[str] = None


__all__ = [
    "PROVIDER_NAME",
    "_REQUIRED_FIELDS",
    "MPPConfigError",
    "MPPReplayError",
    "MPPSettlementError",
    "MPPTransport",
    "ApprovalGate",
    "MPPQuotaStatus",
    "MPPPaymentResult",
]