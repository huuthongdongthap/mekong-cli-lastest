from dataclasses import dataclass
from ..payment_x402_shape import X402_SCHEME

_REFUSED_STATUS = 0
_ALLOWED_STATUS = 200

@dataclass(frozen=True)
class GateConfig:
    """Expected settlement shape the server will accept.

    All four fields are required — an unset field means the gate refuses
    everything (never default-allow, mirroring the x402 provider contract).
    """

    asset: str
    network: str
    amount: str
    recipient: str
    scheme: str = X402_SCHEME


@dataclass(frozen=True)
class GateDecision:
    """Outcome of one gate evaluation. Never raises on invalid input.

    ``allowed`` carries the verdict; ``status`` and ``reason`` describe it.
    Callers must treat ``allowed=False`` as a refusal — the gate itself
    guarantees this by construction (invalid header -> refused, never
    allowed).
    """

    allowed: bool
    status: int
    reason: str


class X402GateError(ValueError):
    """Raised internally by the gate; always mapped to a refusal by the
    caller wrapper (fail-closed on crash)."""


__all__ = ["GateConfig", "GateDecision", "X402GateError"]
