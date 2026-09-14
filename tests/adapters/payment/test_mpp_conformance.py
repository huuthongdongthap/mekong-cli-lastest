# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Cross-provider conformance — X402 and MPP providers share ONE interface.

Lane E4 acceptance: MPPSettlementProvider has the identical 7-method shape
as X402SettlementProvider, and both satisfy the PaymentProvider protocol.
Every test is hermetic (§18): fake transport, fake governance, no sockets,
no keys, no real money. MockPaymentProvider (payment_mock.py) joins the
protocol check to prove the seam is polymorphic, per plan-verdict obs 4.
"""

from __future__ import annotations

import logging
import socket
from dataclasses import replace
from typing import Any, Dict, List, Tuple

import pytest

from src.core.adapters.payment.mpp import (
    MPPConfigError,
    MPPReplayError,
    MPPSettlementError,
    MPPSettlementProvider,
)
from src.core.adapters.payment.x402 import (
    X402ConfigError,
    X402ReplayError,
    X402SettlementError,
    X402SettlementProvider,
)
from src.core.adapters.payment_mock import MockPaymentProvider
from src.core.governance import ActionClass, GovernanceDecision
from src.core.protocols import PaymentProvider, PaymentRequest

SECRET_VALUE = "sk-live-0123456789abcdef"
KEY_LIKE_FIELDS = ("private_key", "seed_phrase", "mnemonic", "secret")

X402_ARGS = dict(
    endpoint="https://pay.example.invalid/settle",
    asset="USDC",
    network="base",
    recipient="0xrecipient",
)


class FakeTransport:
    """Records calls; never opens a socket. Returns a confirmed response."""

    def __init__(self, response: Dict[str, Any] | None = None) -> None:
        self.calls: List[Tuple[str, Dict[str, str], Dict[str, Any]]] = []
        self.response = response or {"success": True, "transaction_id": "conformance-tx-1"}

    def __call__(
        self, endpoint: str, headers: Dict[str, str], body: Dict[str, Any]
    ) -> Dict[str, Any]:
        self.calls.append((endpoint, dict(headers), dict(body)))
        return dict(self.response)


class FakeGovernance:
    """Records approval requests; configurable approve/deny."""

    def __init__(self, approve: bool = True) -> None:
        self.approve = approve
        self.requests: List[Tuple[str, GovernanceDecision]] = []

    def request_approval(self, goal: str, decision: GovernanceDecision) -> bool:
        self.requests.append((goal, decision))
        return self.approve


def make_x402(**overrides: Any) -> X402SettlementProvider:
    config: Dict[str, Any] = {
        **X402_ARGS,
        "governance": FakeGovernance(),
        "transport": FakeTransport(),
    }
    config.update(overrides)
    return X402SettlementProvider(**config)


def make_mpp(**overrides: Any) -> MPPSettlementProvider:
    config: Dict[str, Any] = {
        **X402_ARGS,
        "governance": FakeGovernance(),
        "transport": FakeTransport(),
    }
    config.update(overrides)
    return MPPSettlementProvider(**config)


def make_request(amount: float = 1.5, key: str = "idem-1", **overrides: Any) -> PaymentRequest:
    defaults: Dict[str, Any] = dict(
        asset=X402_ARGS["asset"],
        network=X402_ARGS["network"],
        amount=amount,
        recipient=X402_ARGS["recipient"],
        scheme="exact",
        provider="conformance",
        metadata={"idempotency_key": key},
    )
    defaults.update(overrides)
    return PaymentRequest(**defaults)


def mpp_request(amount: float = 1.5, key: str = "idem-1", **overrides: Any) -> PaymentRequest:
    defaults: Dict[str, Any] = dict(scheme="mpp")
    defaults.update(overrides)
    return make_request(amount, key, **defaults)


PROVIDER_CASES = [
    (make_x402, "exact", "x402"),
    (make_mpp, "mpp", "mpp"),
]
PROVIDERS = pytest.mark.parametrize(
    "provider_factory,scheme,prefix", PROVIDER_CASES
)


class TestProtocolConformance:
    def test_all_providers_satisfy_payment_provider_protocol(self) -> None:
        assert isinstance(make_x402(), PaymentProvider)
        assert isinstance(make_mpp(), PaymentProvider)
        assert isinstance(MockPaymentProvider(), PaymentProvider)

    @PROVIDERS
    def test_same_seven_method_shape(self, provider_factory, scheme, prefix) -> None:
        provider = provider_factory()
        for method in (
            "record_usage", "check_quota", "settle_payment",
            "quote", "request_payment", "verify", "refund",
        ):
            assert callable(getattr(provider, method, None)), (
                f"{prefix} provider missing method: {method}"
            )

    def test_alias_reexports_canonical_x402_provider(self) -> None:
        from src.core.adapters.payment import x402 as alias
        from src.core.adapters import payment_x402 as canonical

        assert alias.X402SettlementProvider is canonical.X402SettlementProvider
        assert alias.X402ConfigError is canonical.X402ConfigError
        assert alias.X402ReplayError is canonical.X402ReplayError
        assert alias.X402SettlementError is canonical.X402SettlementError


class TestConfigFailClosed:
    @pytest.mark.parametrize("missing", ["endpoint", "asset", "network", "recipient"])
    def test_x402_missing_field_raises_config_error(self, missing) -> None:
        with pytest.raises(X402ConfigError, match=missing):
            make_x402(**{missing: None})

    @pytest.mark.parametrize("missing", ["endpoint", "asset", "network", "recipient"])
    def test_mpp_missing_field_raises_config_error(self, missing) -> None:
        with pytest.raises(MPPConfigError, match=missing):
            make_mpp(**{missing: None})

    @pytest.mark.parametrize("missing", ["endpoint", "asset", "network", "recipient"])
    def test_mpp_blank_field_raises_config_error(self, missing) -> None:
        with pytest.raises(MPPConfigError, match=missing):
            make_mpp(**{missing: "   "})

    def test_mpp_missing_governance_raises_config_error(self) -> None:
        with pytest.raises(MPPConfigError, match="governance"):
            make_mpp(governance=None)

    def test_mpp_missing_transport_raises_config_error(self) -> None:
        with pytest.raises(MPPConfigError, match="transport"):
            make_mpp(transport=None)


class TestGovernanceDenialFailClosed:
    @PROVIDERS
    def test_request_payment_denied_blocks_settlement(
        self, provider_factory, scheme, prefix
    ) -> None:
        transport = FakeTransport()
        provider = provider_factory(governance=FakeGovernance(approve=False), transport=transport)
        request = mpp_request(key="gov-1") if scheme == "mpp" else make_request(key="gov-1")
        error = X402SettlementError if scheme == "exact" else MPPSettlementError
        with pytest.raises(error, match="governance approval denied"):
            provider.request_payment(request)
        assert transport.calls == []  # no transport hop after denial

    @PROVIDERS
    def test_settle_payment_denied_returns_error_result(
        self, provider_factory, scheme, prefix
    ) -> None:
        transport = FakeTransport()
        provider = provider_factory(governance=FakeGovernance(approve=False), transport=transport)
        result = provider.settle_payment(2.0, "USD", X402_ARGS["recipient"])
        assert result.success is False
        assert result.error is not None
        assert "governance approval denied" in result.error
        assert transport.calls == []

    @PROVIDERS
    def test_refund_is_also_governance_gated(
        self, provider_factory, scheme, prefix
    ) -> None:
        governance = FakeGovernance(approve=True)
        provider = provider_factory(governance=governance)
        request = mpp_request(key="gov-3") if scheme == "mpp" else make_request(key="gov-3")
        receipt = provider.request_payment(request)
        governance.approve = False
        result = provider.refund(receipt)
        assert result.success is False
        assert result.error is not None
        assert "governance approval denied" in result.error

    @PROVIDERS
    def test_request_payment_calls_governance_before_transport(
        self, provider_factory, scheme, prefix
    ) -> None:
        governance = FakeGovernance(approve=True)
        transport = FakeTransport()
        provider = provider_factory(governance=governance, transport=transport)
        request = mpp_request(key="gov-4") if scheme == "mpp" else make_request(key="gov-4")
        provider.request_payment(request)
        assert len(governance.requests) == 1
        goal, decision = governance.requests[0]
        assert goal.startswith(f"{prefix}:request_payment:")
        assert decision.action_class == ActionClass.REVIEW_REQUIRED
        assert decision.requires_approval is True
        assert len(transport.calls) == 1


class TestReplayRejection:
    @PROVIDERS
    def test_replayed_idempotency_key_rejected(
        self, provider_factory, scheme, prefix
    ) -> None:
        provider = provider_factory()
        request = mpp_request(key="replay-1") if scheme == "mpp" else make_request(key="replay-1")
        provider.request_payment(request)
        error = X402ReplayError if scheme == "exact" else MPPReplayError
        with pytest.raises(error, match="replayed"):
            provider.request_payment(request)


class TestSecretLeakNegatives:
    @PROVIDERS
    def test_metadata_with_key_like_field_rejected(
        self, provider_factory, scheme, prefix
    ) -> None:
        provider = provider_factory()
        for field_name in KEY_LIKE_FIELDS:
            base = mpp_request(key="leak-1") if scheme == "mpp" else make_request(key="leak-1")
            tampered = replace(base, metadata={field_name: SECRET_VALUE})
            with pytest.raises(Exception, match="forbidden"):
                provider.request_payment(tampered)

    @PROVIDERS
    def test_receipt_metadata_carries_no_key_like_fields(
        self, provider_factory, scheme, prefix
    ) -> None:
        provider = provider_factory()
        request = mpp_request(key="leak-2") if scheme == "mpp" else make_request(key="leak-2")
        receipt = provider.request_payment(request)
        blob = repr(receipt).lower() + repr(receipt.metadata).lower()
        for field_name in KEY_LIKE_FIELDS:
            assert field_name not in blob, f"key-like field {field_name!r} leaked"

    def test_mpp_logs_never_contain_secret(self, caplog: pytest.LogCaptureFixture) -> None:
        provider = make_mpp()
        with caplog.at_level(logging.DEBUG, logger="src.core.adapters.payment.mpp"):
            provider.request_payment(mpp_request(key=SECRET_VALUE))
            provider.settle_payment(1.0, "USD", X402_ARGS["recipient"])
        blob = caplog.text.lower()
        assert SECRET_VALUE.lower() not in blob
        assert "private_key" not in blob
        assert "seed_phrase" not in blob

    def test_mpp_codec_rejects_forbidden_fields(self) -> None:
        from src.core.adapters.payment.mpp_shape import (
            MPPShapeError,
            decode_mpp_quote,
            encode_mpp_quote,
        )

        payload = encode_mpp_quote("USDC", "base", 1.0, "0xrecipient")
        assert decode_mpp_quote(payload)["scheme"] == "mpp"
        for field_name in KEY_LIKE_FIELDS:
            tampered = dict(payload)
            tampered[field_name] = SECRET_VALUE
            with pytest.raises(MPPShapeError, match="forbidden"):
                decode_mpp_quote(tampered)


class TestHappyPathFlow:
    @PROVIDERS
    def test_quote_request_verify_refund_settle_flow(
        self, provider_factory, scheme, prefix
    ) -> None:
        transport = FakeTransport()
        provider = provider_factory(transport=transport)

        quote = provider.quote(2.0, "USD", X402_ARGS["recipient"], scheme)
        assert quote.provider == prefix
        assert quote.scheme == scheme
        assert quote.amount == 2.0
        assert quote.asset == "USDC"
        assert quote.network == "base"

        request = mpp_request(amount=2.0, key="flow-1") if scheme == "mpp" else make_request(amount=2.0, key="flow-1")
        receipt = provider.request_payment(request)
        assert receipt.transaction_id == "conformance-tx-1"
        assert provider.verify(receipt) is True

        refund = provider.refund(receipt)
        assert refund.success is True
        assert provider.verify(receipt) is False  # refunded receipt no longer verifies

        settle = provider.settle_payment(3.0, "USD", X402_ARGS["recipient"])
        assert settle.success is True
        assert settle.error is None
        assert settle.transaction_id == "conformance-tx-1"

    @PROVIDERS
    def test_mismatch_rejections(self, provider_factory, scheme, prefix) -> None:
        provider = provider_factory()

        with pytest.raises(ValueError, match="wrong asset"):
            request = mpp_request(asset="ETH", key="mm-1") if scheme == "mpp" else make_request(asset="ETH", key="mm-1")
            provider.request_payment(request)
        with pytest.raises(ValueError, match="wrong network"):
            request = mpp_request(network="solana", key="mm-2") if scheme == "mpp" else make_request(network="solana", key="mm-2")
            provider.request_payment(request)
        with pytest.raises(ValueError, match="recipient mismatch"):
            request = mpp_request(recipient="0xother", key="mm-3") if scheme == "mpp" else make_request(recipient="0xother", key="mm-3")
            provider.request_payment(request)

    @PROVIDERS
    def test_invalid_amount_rejected(self, provider_factory, scheme, prefix) -> None:
        provider = provider_factory()
        base = mpp_request if scheme == "mpp" else make_request
        with pytest.raises(ValueError, match="invalid amount"):
            provider.request_payment(base(amount=0, key="amt-1"))
        with pytest.raises(ValueError, match="invalid amount"):
            provider.request_payment(base(amount=-1.0, key="amt-2"))
        with pytest.raises(ValueError, match="invalid amount"):
            provider.request_payment(base(amount="ten", key="amt-3"))

    @PROVIDERS
    def test_transport_failure_fails_closed(self, provider_factory, scheme, prefix) -> None:
        def broken_transport(endpoint, headers, body):
            raise ConnectionError("boom")

        provider = provider_factory(transport=broken_transport)
        request = mpp_request(key="net-1") if scheme == "mpp" else make_request(key="net-1")
        error = X402SettlementError if scheme == "exact" else MPPSettlementError
        with pytest.raises(error, match="transport failure"):
            provider.request_payment(request)

    @PROVIDERS
    def test_no_real_socket_calls(self, provider_factory, scheme, prefix, monkeypatch) -> None:
        opened: List[Any] = []

        def deny_socket(*args, **kwargs):
            opened.append((args, kwargs))
            raise AssertionError("real socket call attempted")

        monkeypatch.setattr(socket, "socket", deny_socket)
        monkeypatch.setattr(socket, "create_connection", deny_socket)

        transport = FakeTransport()
        provider = provider_factory(transport=transport)
        provider.quote(1.0, "USD", X402_ARGS["recipient"], scheme)
        request = mpp_request(key="net-2") if scheme == "mpp" else make_request(key="net-2")
        receipt = provider.request_payment(request)
        provider.verify(receipt)
        provider.refund(receipt)
        provider.settle_payment(1.0, "USD", X402_ARGS["recipient"])
        assert opened == []
        assert len(transport.calls) == 2  # request_payment + settle_payment


class TestMPPSchemeAgnostic:
    def test_quote_rejects_non_mpp_scheme(self) -> None:
        provider = make_mpp()
        with pytest.raises(ValueError, match="unsupported scheme"):
            provider.quote(1.0, "USD", X402_ARGS["recipient"], "exact")

    def test_no_x402_or_usdt_hardcoding_in_mpp_module(self) -> None:
        """Executable code must not hardcode USDT or the x402 scheme.

        Docstring prose may mention them (explaining what is NOT done);
        only string literals in actual code are checked, via AST.
        """
        import ast
        from pathlib import Path

        module_path = Path(__file__).resolve().parents[3] / "src/core/adapters/payment/mpp.py"
        tree = ast.parse(module_path.read_text(encoding="utf-8"))

        # Collect every docstring node (module/class/function) for exclusion.
        docstring_nodes = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    docstring_nodes.add(id(body[0].value))

        offenders: List[str] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstring_nodes
                and ("x402" in node.value.lower() or "usdt" in node.value.lower())
            ):
                offenders.append(node.value)
        assert offenders == [], f"hardcoded scheme/asset values found: {offenders}"

    def test_verify_rejects_foreign_receipt(self) -> None:
        provider = make_mpp()
        receipt = provider.request_payment(mpp_request(key="foreign-1"))
        assert provider.verify(replace(receipt, provider="mock")) is False
        assert provider.verify(replace(receipt, transaction_id="forged")) is False
