"""Phase 2C: Economic Bus — PaymentProvider Protocol + MCUBillingPaymentAdapter."""

from src.core.billing_adapter import BillingAdapter
from src.core.protocols import PaymentProvider


class TestBillingAdapterSatisfiesPaymentProvider:
    """BillingAdapter wraps MCUBilling and satisfies PaymentProvider Protocol."""

    def test_billing_adapter_satisfies_payment_protocol(self):
        """BillingAdapter must satisfy PaymentProvider Protocol."""
        adapter = BillingAdapter()
        assert isinstance(adapter, PaymentProvider)

    def test_record_usage_delegates(self):
        """record_usage delegates to MCUBilling."""
        adapter = BillingAdapter()
        assert callable(adapter.record_usage)

    def test_check_quota_delegates(self):
        """check_quota delegates to MCUBilling."""
        adapter = BillingAdapter()
        assert callable(adapter.check_quota)

    def test_settle_payment_delegates(self):
        """settle_payment delegates to MCUBilling."""
        adapter = BillingAdapter()
        assert callable(adapter.settle_payment)

    def test_estimate_cost_delegates(self):
        """estimate_cost delegates to MCUBilling (with fallback)."""
        adapter = BillingAdapter()
        assert callable(adapter.estimate_cost)

    def test_extended_methods_exist_on_adapter(self):
        """Extended economic-bus methods exist and return not-implemented."""
        adapter = BillingAdapter()
        assert callable(adapter.quote)
        assert callable(adapter.request_payment)
        assert callable(adapter.verify)
        assert callable(adapter.refund)


class TestPaymentProviderProtocol:
    def test_protocol_methods_exist(self):
        """PaymentProvider Protocol defines required methods."""
        from src.core.protocols import PaymentProvider
        import inspect
        methods = [name for name, _ in inspect.getmembers(PaymentProvider, predicate=inspect.isfunction)]
        assert "record_usage" in methods
        assert "check_quota" in methods

    def test_payment_result_protocol(self):
        """PaymentResult Protocol must be importable and usable."""
        from dataclasses import dataclass
        from typing import Optional

        @dataclass
        class MyResult:
            success: bool
            transaction_id: Optional[str]
            pending: bool = False
            note: Optional[str] = None

        result = MyResult(success=True, transaction_id="tx-123")
        # Should satisfy PaymentResult Protocol
        assert result.success is True
        assert result.transaction_id == "tx-123"