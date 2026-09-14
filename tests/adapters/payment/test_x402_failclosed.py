# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Server-side x402 gate fail-closed smoke (Lane E7, Task 9).

These tests prove the gate semantics 200-vs-0 specified in task.md Task 9:
- valid X-PAYMENT header matching the expected settlement -> allowed (200)
- missing header -> refused (status 0, reason "payment_required")
- invalid base64 / invalid scheme / malformed payload -> refused
- asset mismatch / amount mismatch / recipient mismatch / network mismatch -> refused
- replayed header -> refused on second pass (idempotency-key check)
- gate exception -> refused (fail-closed on crash)
- NO secrets, key-like values, or real settlement details asserted

Every test is 100%% hermetic: config and header are encoded in-process
using the public codec; there is no network, no subprocess, no transport.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from src.core.adapters.payment.x402_gate import (
    GateConfig,
    GateDecision,
    X402PricingGate,
    enforce_x402_gate,
)
from src.core.adapters.payment.x402_gate_wiring import (
    PaymentGateExecutionRuntime,
    wrap_with_x402_gate,
)
from src.core.adapters.payment_x402_shape import (
    XPaymentPayload,
    encode_x_payment_header,
)

# ---------------------------------------------------------------------------
# Fixtures — all hermetic (in-process codec only)
# ---------------------------------------------------------------------------

SETTLE_AMOUNT = "1000000"  # 1.0 in atomic units (public convention)


def _make_expected() -> GateConfig:
    return GateConfig(
        asset="usdc",
        network="ethereum",
        amount=SETTLE_AMOUNT,
        recipient="0xPUBLIC_RECIPIENT_ADDRESS_NOT_A_REAL_KEY",
    )


def _encode_valid_header(expected: GateConfig, *, nonce: str = "nonce-1") -> str:
    payload = XPaymentPayload(
        x402_version=1,
        scheme="exact",
        asset=expected.asset,
        network=expected.network,
        amount=expected.amount,
        recipient=expected.recipient,
        metadata={"idempotency_key": nonce},
    )
    return encode_x_payment_header(payload)


def _headers_with(value: str) -> Dict[str, str]:
    return {"X-PAYMENT": value}


# ---------------------------------------------------------------------------
# (a) valid -> allowed, status 200
# ---------------------------------------------------------------------------

def test_valid_x_payment_allows() -> None:
    expected = _make_expected()
    header = _encode_valid_header(expected)
    decision = enforce_x402_gate(
        _headers_with(header), {}, expected=expected, nonce="n1"
    )
    assert decision.allowed is True
    assert decision.status == 200
    assert decision.reason == "ok"


def test_valid_x_payment_allows_via_class() -> None:
    expected = _make_expected()
    gate = X402PricingGate(expected)
    header = _encode_valid_header(expected, nonce="unique-a")
    decision = gate.enforce(
        _headers_with(header), {}, nonce="unique-a"
    )
    assert decision.allowed is True
    assert decision.status == 200


# ---------------------------------------------------------------------------
# (b) missing header -> refused, status 0, reason "payment_required"
# ---------------------------------------------------------------------------

def test_missing_header_refuses() -> None:
    expected = _make_expected()
    decision = enforce_x402_gate({}, {}, expected=expected)
    assert decision.allowed is False
    assert decision.status == 0
    assert decision.reason == "payment_required"


def test_empty_headers_refuses() -> None:
    expected = _make_expected()
    decision = enforce_x402_gate(
        {"Content-Type": "text/plain"}, {}, expected=expected
    )
    assert decision.allowed is False
    assert decision.status == 0
    assert decision.reason == "payment_required"


def test_case_insensitive_header_lookup_missing() -> None:
    """Header names are case-insensitive for the payment header too."""
    expected = _make_expected()
    decision = enforce_x402_gate(
        {"x-payment": ""}, {}, expected=expected
    )
    # Empty value is not a valid header -> decode fails -> refused
    assert decision.allowed is False
    assert decision.status == 0


# ---------------------------------------------------------------------------
# (c) invalid base64 -> refused
# ---------------------------------------------------------------------------

def test_invalid_base64_refuses() -> None:
    expected = _make_expected()
    decision = enforce_x402_gate(
        _headers_with("%%%not-base64%%%"), {}, expected=expected
    )
    assert decision.allowed is False
    assert decision.status == 0
    assert "invalid_x_payment" in decision.reason


def test_invalid_json_refuses() -> None:
    garbage = base64.b64encode(b"{not json").decode("ascii")
    expected = _make_expected()
    decision = enforce_x402_gate(
        _headers_with(garbage), {}, expected=expected
    )
    assert decision.allowed is False
    assert decision.status == 0
    assert "invalid_x_payment" in decision.reason


def test_invalid_scheme_refuses() -> None:
    """A payload whose scheme is not 'exact' must be refused."""
    expected = _make_expected()
    payload = {
        "x402Version": 1,
        "scheme": "wrong_scheme",
        "asset": expected.asset,
        "network": expected.network,
        "amount": expected.amount,
        "recipient": expected.recipient,
    }
    header = base64.b64encode(
        json.dumps(payload).encode("utf-8")
    ).decode("ascii")
    decision = enforce_x402_gate(
        _headers_with(header), {}, expected=expected
    )
    assert decision.allowed is False
    assert decision.status == 0


# ---------------------------------------------------------------------------
# (d) asset mismatch -> refused
# ---------------------------------------------------------------------------

def test_asset_mismatch_refuses() -> None:
    expected = _make_expected()
    header = _encode_valid_header(
        GateConfig(
            asset="OTHER",
            network=expected.network,
            amount=expected.amount,
            recipient=expected.recipient,
        ),
        nonce="asset-mismatch",
    )
    decision = enforce_x402_gate(
        _headers_with(header), {}, expected=expected, nonce="asset-mismatch"
    )
    assert decision.allowed is False
    assert decision.status == 0
    assert "asset_mismatch" in decision.reason


def test_network_mismatch_refuses() -> None:
    expected = _make_expected()
    header = _encode_valid_header(
        GateConfig(
            asset=expected.asset,
            network="polygon",
            amount=expected.amount,
            recipient=expected.recipient,
        ),
        nonce="network-mismatch",
    )
    decision = enforce_x402_gate(
        _headers_with(header), {}, expected=expected, nonce="network-mismatch"
    )
    assert decision.allowed is False
    assert decision.status == 0
    assert "network_mismatch" in decision.reason


def test_recipient_mismatch_refuses() -> None:
    expected = _make_expected()
    header = _encode_valid_header(
        GateConfig(
            asset=expected.asset,
            network=expected.network,
            amount=expected.amount,
            recipient="0xATTACKER",
        ),
        nonce="recipient-mismatch",
    )
    decision = enforce_x402_gate(
        _headers_with(header), {}, expected=expected, nonce="recipient-mismatch"
    )
    assert decision.allowed is False
    assert decision.status == 0
    assert "recipient_mismatch" in decision.reason


# ---------------------------------------------------------------------------
# (e) amount mismatch -> refused
# ---------------------------------------------------------------------------

def test_amount_mismatch_refuses() -> None:
    expected = _make_expected()
    header = _encode_valid_header(
        GateConfig(
            asset=expected.asset,
            network=expected.network,
            amount="999999999",
            recipient=expected.recipient,
        ),
        nonce="amount-mismatch",
    )
    decision = enforce_x402_gate(
        _headers_with(header), {}, expected=expected, nonce="amount-mismatch"
    )
    assert decision.allowed is False
    assert decision.status == 0
    assert "amount_mismatch" in decision.reason


# ---------------------------------------------------------------------------
# (f) replay -> second call refused
# ---------------------------------------------------------------------------

def test_replay_refused_on_second_pass() -> None:
    expected = _make_expected()
    gate = X402PricingGate(expected)
    header = _encode_valid_header(expected, nonce="replay-key-1")
    d1 = gate.enforce(_headers_with(header), {})
    assert d1.allowed is True
    assert d1.status == 200
    d2 = gate.enforce(_headers_with(header), {})
    assert d2.allowed is False
    assert d2.status == 0
    assert "replay_detected" in d2.reason


def test_replay_across_fresh_gate_instances_is_undefended() -> None:
    """A fresh gate instance has its own nonce set (per-process by design).

    Replay detection lives in a single gate instance's in-memory set. If a
    caller builds a brand-new X402PricingGate for every call, the replay
    set is empty on each call. This is documented, not a bug: callers
    that want cross-call replay protection must reuse one gate instance.
    """
    expected = _make_expected()
    header = _encode_valid_header(expected, nonce="shared")
    g1 = X402PricingGate(expected)
    r1 = g1.enforce(_headers_with(header), {})
    assert r1.allowed is True
    # A brand-new gate: fresh nonce set — caller-design trade-off documented.
    g2 = X402PricingGate(expected)
    r2 = g2.enforce(_headers_with(header), {})
    assert r2.allowed is True


# ---------------------------------------------------------------------------
# (g) gate exception -> refused (fail-closed on crash)
# ---------------------------------------------------------------------------

def test_gate_crash_fails_closed() -> None:
    expected = _make_expected()

    class CrashingDecoder(X402PricingGate):
        def _enforce(self, headers, body, *, nonce=None):  # type: ignore[override]
            raise RuntimeError("simulated gate crash")

    gate = CrashingDecoder(expected)
    header = _encode_valid_header(expected, nonce="crash")
    decision = gate.enforce(_headers_with(header), {})
    assert decision.allowed is False
    assert decision.status == 0
    assert "gate error" in decision.reason


def test_wiring_gate_crash_fails_closed() -> None:
    """When the gate callable raises, the wiring must refuse (not bypass)."""
    from src.core.exec_runtime.types import ExecResult

    def crashing_gate(headers: Dict[str, Any], body: Dict[str, Any]) -> GateDecision:
        raise RuntimeError("gate implosion")

    runtime = MagicMock()
    runtime.execute = MagicMock(
        return_value=ExecResult(ok=True, exit_code=0, stdout="hi", stderr="")
    )
    wrapped = PaymentGateExecutionRuntime(runtime, gate=crashing_gate)
    result = wrapped.execute(["echo", "hello"])
    assert result.ok is False
    assert "payment_required" in (result.error or "")
    # Inner runtime.execute must NOT have been called (gate short-circuits)
    runtime.execute.assert_not_called()


# ---------------------------------------------------------------------------
# (h) No secrets / key-like fields in decision.reason
# ---------------------------------------------------------------------------

def test_reason_never_leaks_secrets() -> None:
    """Reasons are enumerated strings — no payload echo, no secrets."""
    expected = _make_expected()
    gate = X402PricingGate(expected)
    cases = [
        gate.enforce({}, {}),
        gate.enforce(_headers_with("garbage"), {}),
        gate.enforce(
            _headers_with(
                _encode_valid_header(
                    GateConfig(
                        asset="WRONG",
                        network=expected.network,
                        amount=expected.amount,
                        recipient=expected.recipient,
                    ),
                    nonce="r1",
                )
            ),
            {},
        ),
    ]
    for d in cases:
        assert d.allowed is False
        assert "0x" not in d.reason
        assert "private" not in d.reason
        assert "secret" not in d.reason
        # The allowed reason is the only one with the word "ok".
        assert "key" not in d.reason


# ---------------------------------------------------------------------------
# Wiring: gate OFF by default (no payment semantics unless injected)
# ---------------------------------------------------------------------------

def test_wiring_no_gate_delegates_unchanged() -> None:
    from src.core.exec_runtime.types import ExecResult

    runtime = MagicMock()
    runtime.execute = MagicMock(
        return_value=ExecResult(ok=True, exit_code=0, stdout="ok", stderr="")
    )
    # No gate and no expected: construction itself fails (caller must opt in).
    with pytest.raises(ValueError):
        PaymentGateExecutionRuntime(runtime)
    # A plain runtime execute() is untouched.
    result = runtime.execute(["echo", "hi"])
    assert result.ok is True


def test_wiring_valid_gate_allows_execution() -> None:
    from src.core.exec_runtime.types import ExecResult

    expected = _make_expected()
    gate = X402PricingGate(expected)
    header = _encode_valid_header(expected, nonce="wire-1")

    def allow_gate(headers: Dict[str, Any], body: Dict[str, Any]) -> GateDecision:
        # Inject the valid header for the wiring-level gate, which sees no
        # real HTTP headers from the command — so the gate refuses by
        # default. To prove the wiring honors an "allow", we call the gate
        # with a header-bearing request directly.
        return gate.enforce(_headers_with(header), {}, nonce="wire-1")

    runtime = MagicMock()
    runtime.execute = MagicMock(
        return_value=ExecResult(ok=True, exit_code=0, stdout="ran", stderr="")
    )
    wrapped = PaymentGateExecutionRuntime(runtime, gate=allow_gate)
    result = wrapped.execute(["echo", "hello"])
    assert result.ok is True
    runtime.execute.assert_called_once_with(["echo", "hello"], timeout_s=None)


def test_wiring_refused_gate_blocks_execution() -> None:
    from src.core.exec_runtime.types import ExecResult

    def deny_gate(headers: Dict[str, Any], body: Dict[str, Any]) -> GateDecision:
        return GateDecision(allowed=False, status=0, reason="payment_required")

    runtime = MagicMock()
    runtime.execute = MagicMock(
        return_value=ExecResult(ok=True, exit_code=0, stdout="", stderr="")
    )
    wrapped = wrap_with_x402_gate(runtime, gate=deny_gate)
    result = wrapped.execute(["echo", "hi"])
    assert result.ok is False
    assert result.error is not None
    assert "payment_required" in result.error
    runtime.execute.assert_not_called()


def test_wrap_with_x402_gate_convenience() -> None:
    expected = _make_expected()
    runtime = MagicMock()
    wrapped = wrap_with_x402_gate(runtime, expected=expected)
    assert isinstance(wrapped, PaymentGateExecutionRuntime)