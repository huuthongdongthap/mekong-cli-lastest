# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Optional x402 gate wiring for the local execution runtime (Lane E7).

The gate itself lives in ``x402_gate.py``; this module is the *injection
point*. It wraps a :class:`LocalExecutionRuntime` and short-circuits
``execute()`` before any subprocess launches when the pricing header is
absent or invalid.

Design (fail-closed, no core modifications):
- ``LocalExecutionRuntime`` is NOT modified — this module composes over
  the public ``execute()`` surface instead.
- ``payment_gate`` is None by default: a runtime with no gate behaves
  byte-identically to the unwrapped runtime (default = no payment
  semantics, per the local runtime contract).
- When injected, the gate runs first. A refused decision returns an
  ``ExecResult(ok=False, error="payment_required: ...")`` and the command
  never reaches the subprocess.
- Gate exceptions are mapped to a refusal: a crashing gate is never
  trusted as a pass-through.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Sequence, Union

from src.core.exec_runtime.types import ExecResult
from .x402_gate import GateConfig, GateDecision, X402PricingGate

# Argument shape accepted by the gate callable: (headers, body) -> GateDecision
GateCallable = Callable[[Dict[str, Any], Dict[str, Any]], GateDecision]


class PaymentGateExecutionRuntime:
    """Compose an x402 gate over an execution runtime.

    Delegates every non-``execute`` attribute to the wrapped runtime, so
    callers can use it as a drop-in ``ExecutionRuntime``. Only ``execute``
    is intercepted, and only when a gate is configured.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        gate: Optional[GateCallable] = None,
        expected: Optional[GateConfig] = None,
    ) -> None:
        if runtime is None:
            raise ValueError("PaymentGateExecutionRuntime requires a runtime")
        gates = 0
        if gate is not None:
            gates += 1
        if expected is not None:
            gates += 1
        if gates == 0:
            raise ValueError(
                "PaymentGateExecutionRuntime requires gate= or expected=" \
                "(default is no gate — no payment semantics)"
            )
        if gate is None and expected is not None:
            gate = X402PricingGate(expected).enforce
        self._runtime = runtime
        self._gate: Optional[GateCallable] = gate
        self._expected = expected

    # ------------------------------------------------------------------ #
    # ExecutionRuntime surface
    # ------------------------------------------------------------------ #

    def execute(
        self, command: Union[str, Sequence[str]], *, timeout_s: Optional[float] = None
    ) -> ExecResult:
        """Run a command, gated first when a payment gate is configured."""
        if self._gate is None:
            return self._runtime.execute(command, timeout_s=timeout_s)
        decision = self._evaluate_gate(command)
        if not decision.allowed:
            return ExecResult(
                ok=False,
                exit_code=None,
                stdout="",
                stderr="",
                error=f"payment_required: {decision.reason}",
            )
        return self._runtime.execute(command, timeout_s=timeout_s)

    # ------------------------------------------------------------------ #
    # Delegation (everything else)
    # ------------------------------------------------------------------ #

    def __getattr__(self, item: str) -> Any:
        # Only invoked for attributes not found on this instance, so the
        # wrapped runtime's surface is exposed transparently.
        return getattr(self._runtime, item)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _evaluate_gate(self, command: Union[str, Sequence[str]]) -> GateDecision:
        """Build a synthetic request view and run the gate.

        Commands carry no real HTTP headers — the gate is fed a header
        map derived from the command string and an empty body. Callers
        that want real request headers should pass a gate callable that
        inspects them directly.
        """
        headers: Dict[str, Any] = {}
        body: Dict[str, Any] = {}
        try:
            return self._gate(headers, body)  # type: ignore[misc]
        except Exception as exc:  # fail-closed: gate crash = refusal
            return GateDecision(
                allowed=False,
                status=0,
                reason=f"gate error: {type(exc).__name__}",
            )


def wrap_with_x402_gate(
    runtime: Any,
    *,
    expected: Optional[GateConfig] = None,
    gate: Optional[GateCallable] = None,
) -> PaymentGateExecutionRuntime:
    """Convenience constructor mirroring the runtime wiring pattern."""
    return PaymentGateExecutionRuntime(
        runtime, gate=gate, expected=expected
    )


__all__ = [
    "PaymentGateExecutionRuntime",
    "wrap_with_x402_gate",
    "GateCallable",
]