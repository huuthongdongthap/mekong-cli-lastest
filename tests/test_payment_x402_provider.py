# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""X402SettlementProvider tests — fail-closed x402 settlement (§18).

Every test is hermetic: fake transport, fake governance, no sockets, no
wallets, no keys, no real money. Each fail-closed invariant has a test
that fails if the invariant is violated.
"""

from __future__ import annotations

import logging
import socket
from typing import Any, Dict, List, Tuple

import pytest

from src.core.adapters.payment_x402 import (
    PROVIDER_NAME,
    X402ConfigError,
    X402ReplayError,
    X402SettlementError,
    X402SettlementProvider,
)
from src.core.governance import ActionClass, GovernanceDecision
from src.core.protocols import PaymentProvider, PaymentRequest

SECRET_VALUE = "sk-live-0123456789abcdef"


class FakeTransport:
    """Records calls; never opens a socket. Returns a confirmed response."""

    def __init__(self, response: Dict[str, Any] | None = None) -> None:
        self.calls: List[Tuple[str, Dict[str, str], Dict[str, Any]]] = []
        self.response = response or {"success": True, "transaction_id": "x402-tx-1"}

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


def make_config(**overrides: Any) -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "endpoint": "https://pay.example.invalid/settle",
        "asset": "USDC",
        "network": "base",
        "recipient": "0xrecipient",
        "governance": FakeGovernance(),
        "transport": FakeTransport(),
    }
    config.update(overrides)
    return config


def make_request(amount: float = 1.5, key: str = "idem-1", **overrides: Any) -> PaymentRequest:
    defaults = dict(
        asset="USDC",
        network="base",
        amount=amount,
        recipient="0xrecipient",
        scheme="exact",
        provider=PROVIDER_NAME,
        metadata={"idempotency_key": key},
    )
    defaults.update(overrides)
    return PaymentRequest(**defaults)


class TestConfigFailClosed:
    """Invariant 1 — missing explicit config raises ConfigError, one field at a time."""

    @pytest.mark.parametrize("missing", ["endpoint", "asset", "network", "recipient"])
    def test_missing_field_raises_config_error(self, missing: str) -> None:
        with pytest.raises(X402ConfigError, match=missing):
            X402SettlementProvider(**make_config(**{missing: None}))

    @pytest.mark.parametrize("missing", ["endpoint", "asset", "network", "recipient"])
    def test_blank_field_raises_config_error(self, missing: str) -> None:
        with pytest.raises(X402ConfigError, match=missing):
            X402SettlementProvider(**make_config(**{missing: "   "}))

    def test_missing_governance_raises_config_error(self) -> None:
        with pytest.raises(X402ConfigError, match="governance"):
            X402SettlementProvider(**make_config(governance=None))

    def test_missing_transport_raises_config_error(self) -> None:
        with pytest.raises(X402ConfigError, match="transport"):
            X402SettlementProvider(**make_config(transport=None))


class TestGovernanceGate:
    """Invariant 2 — settle/request go through Governance approval; no bypass."""

    def test_request_payment_calls_governance_before_transport(self) -> None:
        governance = FakeGovernance(approve=True)
        transport = FakeTransport()
        provider = X402SettlementProvider(
            **make_config(governance=governance, transport=transport)
        )
        provider.request_payment(make_request(key="gov-1"))
        assert len(governance.requests) == 1
        goal, decision = governance.requests[0]
        assert goal.startswith("x402:request_payment:")
        assert decision.action_class == ActionClass.REVIEW_REQUIRED
        assert decision.requires_approval is True
        assert len(transport.calls) == 1

    def test_request_payment_denied_blocks_settlement(self) -> None:
        transport = FakeTransport()
        provider = X402SettlementProvider(
            **make_config(governance=FakeGovernance(approve=False), transport=transport)
        )
        with pytest.raises(X402SettlementError, match="governance approval denied"):
            provider.request_payment(make_request(key="gov-2"))
        assert transport.calls == []  # no transport hop after denial

    def test_settle_payment_denied_returns_error_result(self) -> None:
        transport = FakeTransport()
        provider = X402SettlementProvider(
            **make_config(governance=FakeGovernance(approve=False), transport=transport)
        )
        result = provider.settle_payment(2.0, "USD", "0xrecipient")
        assert result.success is False
        assert result.error is not None
        assert "governance approval denied" in result.error
        assert transport.calls == []

    def test_settle_payment_approved_calls_governance(self) -> None:
        governance = FakeGovernance(approve=True)
        provider = X402SettlementProvider(
            **make_config(governance=governance, transport=FakeTransport())
        )
        result = provider.settle_payment(2.0, "USD", "0xrecipient")
        assert result.success is True
        assert any(goal.startswith("x402:settle_payment:") for goal, _ in governance.requests)

    def test_refund_is_also_governance_gated(self) -> None:
        governance = FakeGovernance(approve=True)
        provider = X402SettlementProvider(
            **make_config(governance=governance, transport=FakeTransport())
        )
        receipt = provider.request_payment(make_request(key="gov-3"))
        governance.approve = False
        result = provider.refund(receipt)
        assert result.success is False
        assert result.error is not None
        assert "governance approval denied" in result.error


class TestSecretHygiene:
    """Invariant 3 — keys/seeds never logged; forbidden fields rejected."""

    def test_logs_never_contain_secret(self, caplog: pytest.LogCaptureFixture) -> None:
        provider = X402SettlementProvider(
            **make_config(transport=FakeTransport())
        )
        with caplog.at_level(logging.DEBUG, logger="src.core.adapters.payment_x402"):
            provider.request_payment(
                make_request(key="leak-1", metadata={"idempotency_key": SECRET_VALUE})
            )
            provider.settle_payment(1.0, "USD", "0xrecipient")
        blob = caplog.text.lower()
        assert SECRET_VALUE.lower() not in blob
        assert "private_key" not in blob
        assert "seed_phrase" not in blob

    def test_metadata_with_key_like_field_rejected(self) -> None:
        provider = X402SettlementProvider(**make_config())
        for field_name in ("private_key", "seed_phrase", "mnemonic", "secret"):
            with pytest.raises(Exception, match="forbidden"):
                provider.request_payment(
                    make_request(key="leak-2", metadata={field_name: SECRET_VALUE})
                )

    def test_receipt_metadata_carries_no_key_like_fields(self) -> None:
        provider = X402SettlementProvider(**make_config())
        receipt = provider.request_payment(make_request(key="leak-3"))
        blob = repr(receipt).lower() + repr(receipt.metadata).lower()
        for field_name in ("private_key", "seed_phrase", "mnemonic", "secret"):
            assert field_name not in blob


class TestInjectedTransportOnly:
    """Invariant 4 — network ONLY via injected transport; zero real sockets."""

    def test_no_real_socket_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        opened: List[Any] = []

        def deny_socket(*args: Any, **kwargs: Any) -> Any:
            opened.append((args, kwargs))
            raise AssertionError("real socket call attempted")

        monkeypatch.setattr(socket, "socket", deny_socket)
        monkeypatch.setattr(socket, "create_connection", deny_socket)

        transport = FakeTransport()
        provider = X402SettlementProvider(
            **make_config(endpoint="https://pay.example.invalid/settle", transport=transport)
        )
        provider.quote(1.0, "USD", "0xrecipient", "exact")
        receipt = provider.request_payment(make_request(key="net-1"))
        provider.verify(receipt)
        provider.refund(receipt)
        provider.settle_payment(1.0, "USD", "0xrecipient")

        assert opened == []
        assert len(transport.calls) == 2  # request_payment + settle_payment
        endpoint, headers, body = transport.calls[0]
        assert endpoint == "https://pay.example.invalid/settle"
        assert "X-PAYMENT" in headers
        assert body["accepts"][0]["asset"] == "USDC"

    def test_transport_failure_fails_closed(self) -> None:
        def broken_transport(
            endpoint: str, headers: Dict[str, str], body: Dict[str, Any]
        ) -> Dict[str, Any]:
            raise ConnectionError("boom")

        provider = X402SettlementProvider(
            **make_config(transport=broken_transport)
        )
        with pytest.raises(X402SettlementError, match="transport failure"):
            provider.request_payment(make_request(key="net-2"))

    def test_unconfirmed_transport_response_rejected(self) -> None:
        provider = X402SettlementProvider(
            **make_config(transport=FakeTransport(response={"success": False}))
        )
        with pytest.raises(X402SettlementError, match="no confirmed settlement"):
            provider.request_payment(make_request(key="net-3"))

    def test_response_missing_tx_id_rejected(self) -> None:
        provider = X402SettlementProvider(
            **make_config(transport=FakeTransport(response={"success": True}))
        )
        with pytest.raises(X402SettlementError, match="transaction_id"):
            provider.request_payment(make_request(key="net-4"))


class TestReplayAndMismatch:
    """Invariant 5 — replay / wrong-asset / wrong-network requests rejected."""

    def test_replayed_idempotency_key_rejected(self) -> None:
        provider = X402SettlementProvider(**make_config())
        provider.request_payment(make_request(key="replay-1"))
        with pytest.raises(X402ReplayError, match="replayed"):
            provider.request_payment(make_request(key="replay-1"))

    def test_replayed_content_hash_rejected_without_explicit_key(self) -> None:
        provider = X402SettlementProvider(**make_config())
        provider.request_payment(make_request(key="", metadata={}))
        with pytest.raises(X402ReplayError, match="replayed"):
            provider.request_payment(make_request(key="", metadata={}))

    def test_wrong_asset_rejected(self) -> None:
        provider = X402SettlementProvider(**make_config())
        with pytest.raises(ValueError, match="wrong asset"):
            provider.request_payment(make_request(asset="ETH", key="mismatch-1"))

    def test_wrong_network_rejected(self) -> None:
        provider = X402SettlementProvider(**make_config())
        with pytest.raises(ValueError, match="wrong network"):
            provider.request_payment(make_request(network="solana", key="mismatch-2"))

    def test_wrong_recipient_rejected(self) -> None:
        provider = X402SettlementProvider(**make_config())
        with pytest.raises(ValueError, match="recipient mismatch"):
            provider.request_payment(make_request(recipient="0xother", key="mismatch-3"))

    def test_wrong_scheme_rejected(self) -> None:
        provider = X402SettlementProvider(**make_config())
        with pytest.raises(ValueError, match="unsupported scheme"):
            provider.request_payment(make_request(scheme="lightning", key="mismatch-4"))


class TestProtocolConformanceAndFlow:
    """Happy path + protocol conformance (still hermetic)."""

    def test_satisfies_payment_provider_protocol(self) -> None:
        assert isinstance(X402SettlementProvider(**make_config()), PaymentProvider)

    def test_quote_request_verify_refund_flow(self) -> None:
        transport = FakeTransport()
        provider = X402SettlementProvider(**make_config(transport=transport))

        quote = provider.quote(2.0, "USD", "0xrecipient", "exact")
        assert quote.provider == PROVIDER_NAME
        assert quote.scheme == "exact"
        assert quote.metadata["atomic_amount"] == "2000000"
        assert quote.metadata["payment_required"]["accepts"][0]["amount"] == "2000000"

        receipt = provider.request_payment(make_request(amount=2.0, key="flow-1"))
        assert receipt.transaction_id == "x402-tx-1"
        assert provider.verify(receipt) is True

        refund = provider.refund(receipt)
        assert refund.success is True
        assert provider.verify(receipt) is False  # refunded receipt no longer verifies

    def test_quote_rejects_unknown_scheme(self) -> None:
        provider = X402SettlementProvider(**make_config())
        with pytest.raises(ValueError, match="unsupported scheme"):
            provider.quote(1.0, "USD", "0xrecipient", "lightning")

    def test_invalid_amount_rejected(self) -> None:
        provider = X402SettlementProvider(**make_config())
        with pytest.raises(ValueError, match="invalid amount"):
            provider.request_payment(make_request(amount=0, key="amt-1"))
        with pytest.raises(ValueError, match="invalid amount"):
            provider.request_payment(make_request(amount=-1.0, key="amt-2"))
        with pytest.raises(ValueError, match="invalid amount"):
            provider.request_payment(make_request(amount="ten", key="amt-3"))

    def test_settle_payment_happy_path(self) -> None:
        provider = X402SettlementProvider(**make_config())
        result = provider.settle_payment(3.0, "USD", "0xrecipient")
        assert result.success is True
        assert result.transaction_id == "x402-tx-1"
        assert result.error is None

    def test_settle_payment_invalid_amount_returns_error_result(self) -> None:
        provider = X402SettlementProvider(**make_config())
        result = provider.settle_payment(-5.0, "USD", "0xrecipient")
        assert result.success is False
        assert result.error is not None

    def test_check_quota_grants_nothing(self) -> None:
        status = X402SettlementProvider(**make_config()).check_quota("org-1")
        assert status.remaining_mcu == 0
        assert status.total_mcu == 0
        assert status.tier == "X402"

    def test_record_usage_accumulates(self) -> None:
        provider = X402SettlementProvider(**make_config())
        provider.record_usage("agent-1", 100, "model-a")
        provider.record_usage("agent-1", 50, "model-b")
        assert provider.usage("agent-1") == 150

    def test_verify_rejects_foreign_receipt(self) -> None:
        provider = X402SettlementProvider(**make_config())
        receipt = provider.request_payment(make_request(key="foreign-1"))
        from dataclasses import replace

        assert provider.verify(replace(receipt, provider="mock")) is False
        assert provider.verify(replace(receipt, transaction_id="forged")) is False
