# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Payment provider tests — economic bus (§18: no real money).

Covers MockPaymentProvider (deterministic, idempotent, no IO), the
x402 protocol-shape codec (pure data, no network, no wallet), and the
BillingAdapter not-implemented seams. No keys, no network, no custody.
"""

import pytest

from src.core.adapters.payment_mock import MockPaymentProvider
from src.core.adapters.payment_x402_shape import (
    X402_VERSION,
    X402ShapeError,
    XPaymentPayload,
    PaymentRequired,
    decode_payment_required,
    decode_x_payment_header,
    encode_payment_required,
    encode_x_payment_header,
)
from src.core.billing_adapter import BillingAdapter
from src.core.protocols import PaymentProvider, PaymentRequest

KEY_LIKE_FIELDS = ("private_key", "seed", "secret", "mnemonic")


def make_request(amount=1.5, asset="USDC", network="base", key="idem-1", **overrides):
    defaults = dict(
        asset=asset,
        network=network,
        amount=amount,
        recipient="recipient-abc",
        scheme="exact",
        provider="mock",
        metadata={"idempotency_key": key},
    )
    defaults.update(overrides)
    return PaymentRequest(**defaults)


class TestMockProviderHappyPath:
    def test_satisfies_payment_provider_protocol(self):
        assert isinstance(MockPaymentProvider(), PaymentProvider)

    def test_quote_request_verify_settle_flow(self):
        provider = MockPaymentProvider()
        quote = provider.quote(2.0, "USD", "recipient-abc", "exact")
        assert quote.amount == 2.0
        assert quote.asset == "USDC"
        assert quote.provider == "mock"

        receipt = provider.request_payment(make_request(amount=2.0, key="flow-1"))
        assert receipt.transaction_id.startswith("mock-tx-")
        assert provider.verify(receipt) is True
        assert provider.settled_amount(receipt.transaction_id) == 2.0

        settle = provider.settle_payment(3.0, "USD", "recipient-abc")
        assert settle.success is True
        assert settle.error is None

    def test_deterministic_tx_id(self):
        p1, p2 = MockPaymentProvider(), MockPaymentProvider()
        r1 = p1.request_payment(make_request(key="det-1"))
        r2 = p2.request_payment(make_request(key="det-1"))
        assert r1.transaction_id == r2.transaction_id

    def test_check_quota_static_status(self):
        status = MockPaymentProvider().check_quota("org-1")
        assert status.remaining_mcu == 10_000
        assert status.total_mcu == 10_000
        assert status.tier == "MOCK"

    def test_record_usage_accumulates(self):
        provider = MockPaymentProvider()
        provider.record_usage("agent-1", 100, "model-a")
        provider.record_usage("agent-1", 50, "model-b")
        assert provider.usage("agent-1") == 150


class TestMockProviderValidation:
    def test_invalid_amount_zero_raises(self):
        with pytest.raises(ValueError, match="invalid amount"):
            MockPaymentProvider().request_payment(make_request(amount=0))

    def test_invalid_amount_negative_raises(self):
        with pytest.raises(ValueError, match="invalid amount"):
            MockPaymentProvider().quote(-1.0, "USD", "r", "exact")

    def test_invalid_amount_non_numeric_raises(self):
        with pytest.raises(ValueError, match="invalid amount"):
            MockPaymentProvider().request_payment(make_request(amount="ten"))

    def test_settle_invalid_amount_returns_error_result(self):
        result = MockPaymentProvider().settle_payment(-5.0, "USD", "r")
        assert result.success is False
        assert result.error is not None
        assert "invalid amount" in result.error

    def test_wrong_asset_rejected(self):
        with pytest.raises(ValueError, match="wrong asset"):
            MockPaymentProvider().request_payment(make_request(asset="ETH"))

    def test_wrong_network_rejected(self):
        with pytest.raises(ValueError, match="wrong network"):
            MockPaymentProvider().request_payment(make_request(network="solana"))


class TestMockProviderIdempotency:
    def test_replay_same_key_returns_same_receipt_no_double_settle(self):
        provider = MockPaymentProvider()
        first = provider.request_payment(make_request(amount=4.0, key="replay-1"))
        second = provider.request_payment(make_request(amount=4.0, key="replay-1"))
        assert first == second
        assert first.transaction_id == second.transaction_id
        # Settled exactly once — replay did not double-settle.
        assert provider.settled_amount(first.transaction_id) == 4.0

    def test_different_keys_settle_independently(self):
        provider = MockPaymentProvider()
        r1 = provider.request_payment(make_request(key="a"))
        r2 = provider.request_payment(make_request(key="b"))
        assert r1.transaction_id != r2.transaction_id


class TestMockProviderRefund:
    def test_refund_happy_path(self):
        provider = MockPaymentProvider()
        receipt = provider.request_payment(make_request(key="refund-1"))
        result = provider.refund(receipt)
        assert result.success is True
        assert result.error is None
        assert provider.settled_amount(receipt.transaction_id) == 0.0
        # Refunded receipt no longer verifies.
        assert provider.verify(receipt) is False

    def test_refund_unknown_receipt_rejected(self):
        provider = MockPaymentProvider()
        receipt = provider.request_payment(make_request(key="refund-2"))
        result = MockPaymentProvider().refund(receipt)  # different provider
        assert result.success is False
        assert result.error is not None


class TestSecretLeakage:
    """§18 — receipts and logs must never carry key-like material."""

    def test_receipt_repr_has_no_key_like_fields(self):
        provider = MockPaymentProvider()
        receipt = provider.request_payment(make_request(key="leak-check"))
        blob = repr(receipt).lower() + repr(receipt.metadata).lower()
        for field_name in KEY_LIKE_FIELDS:
            assert field_name not in blob, f"key-like field {field_name!r} leaked"

    def test_quote_and_result_reprs_have_no_key_like_fields(self):
        provider = MockPaymentProvider()
        quote = provider.quote(1.0, "USD", "r", "exact")
        result = provider.settle_payment(1.0, "USD", "r")
        blob = (repr(quote) + repr(result)).lower()
        for field_name in KEY_LIKE_FIELDS:
            assert field_name not in blob, f"key-like field {field_name!r} leaked"

    def test_x402_decode_rejects_key_like_payload_fields(self):
        for field_name in KEY_LIKE_FIELDS:
            header = encode_x_payment_header(
                XPaymentPayload(
                    x402_version=X402_VERSION,
                    scheme="exact",
                    asset="USDC",
                    network="base",
                    amount="1000000",
                    recipient="r",
                )
            )
            # Tamper: inject a key-like field into the encoded payload.
            import base64
            import json

            body = json.loads(base64.b64decode(header))
            body[field_name] = "should-never-pass"
            tampered = base64.b64encode(
                json.dumps(body).encode("utf-8")
            ).decode("ascii")
            with pytest.raises(X402ShapeError, match="forbidden"):
                decode_x_payment_header(tampered)


class TestX402Shape:
    """Pure-data codec — no network, no wallet, no settlement."""

    def test_payment_required_roundtrip(self):
        pr = PaymentRequired(
            x402_version=X402_VERSION,
            accepts_asset="USDC",
            accepts_network="base",
            amount="1000000",
            recipient="0xrecipient",
        )
        body = encode_payment_required(pr)
        decoded = decode_payment_required(body)
        assert decoded == pr

    def test_x_payment_header_roundtrip(self):
        payload = XPaymentPayload(
            x402_version=X402_VERSION,
            scheme="exact",
            asset="USDC",
            network="base",
            amount="250000",
            recipient="0xrecipient",
        )
        header = encode_x_payment_header(payload)
        assert decode_x_payment_header(header) == payload

    def test_scheme_validation_rejects_unknown_scheme(self):
        payload = XPaymentPayload(
            x402_version=X402_VERSION,
            scheme="lightning",
            asset="USDC",
            network="base",
            amount="1",
            recipient="r",
        )
        with pytest.raises(X402ShapeError, match="unsupported scheme"):
            encode_x_payment_header(payload)

    def test_invalid_base64_header_rejected(self):
        with pytest.raises(X402ShapeError, match="base64"):
            decode_x_payment_header("!!!not-base64!!!")

    def test_non_integer_amount_rejected(self):
        pr = PaymentRequired(
            x402_version=X402_VERSION,
            accepts_asset="USDC",
            accepts_network="base",
            amount="12.5",
            recipient="r",
        )
        with pytest.raises(X402ShapeError, match="integer"):
            encode_payment_required(pr)


class TestBillingAdapterNotImplementedSeams:
    """BillingAdapter keeps legacy delegation; new methods fail explicitly."""

    def test_refund_returns_explicit_error_result(self):
        adapter = BillingAdapter()
        receipt = MockPaymentProvider().request_payment(make_request(key="adapter-1"))
        result = adapter.refund(receipt)
        assert result["success"] is False
        assert "not implemented" in result["error"]

    def test_verify_returns_false(self):
        adapter = BillingAdapter()
        receipt = MockPaymentProvider().request_payment(make_request(key="adapter-2"))
        assert adapter.verify(receipt) is False

    def test_quote_carries_error_marker(self):
        adapter = BillingAdapter()
        quote = adapter.quote(1.0, "USD", "r", "exact")
        assert "not implemented" in quote.metadata["error"]

    def test_request_payment_carries_error_marker(self):
        adapter = BillingAdapter()
        receipt = adapter.request_payment(make_request(key="adapter-3"))
        assert "not implemented" in receipt.metadata["error"]

    def test_legacy_settle_payment_still_delegates_to_mcu_stub(self):
        adapter = BillingAdapter()
        result = adapter.settle_payment(1.0, "USD", "r")
        # MCUBilling settle stub preserved: pending=True.
        assert result["pending"] is True
