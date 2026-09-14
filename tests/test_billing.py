"""Tests for billing critical path — NOWPayments IPN, checkout validation, pricing engine.

Covers:
- verify_ipn_signature: HMAC-SHA512 verification
- handle_ipn: payment processing, credit grant, duplicate prevention
- _extract_tier: tier detection from order metadata
- Checkout: tier validation, invoice creation guard rails
- Pricing: RateCard.calculate_charge, Plan.credits_to_dollars
- BillingResult: serialization, line item aggregation
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import importlib.util

import pytest

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

_WEBHOOK_HANDLER_PATH = Path(__file__).parent.parent / "src" / "raas" / "nowpayments_webhook_handler.py"


def _load_webhook_handler():
    """Load nowpayments_webhook_handler.py via importlib."""
    spec = importlib.util.spec_from_file_location("nowpayments_webhook_handler", _WEBHOOK_HANDLER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# NOWPayments IPN signature verification
# ---------------------------------------------------------------------------

class TestVerifyIpnSignature:
    """Tests for HMAC-SHA512 IPN signature validation."""

    def _make_sig(self, secret: str, payload: str) -> str:
        """Helper: generate expected HMAC-SHA512 signature."""
        sorted_payload = json.dumps(json.loads(payload), sort_keys=True)
        return hmac.new(
            secret.encode(),
            sorted_payload.encode(),
            hashlib.sha512,
        ).hexdigest()

    def test_valid_signature_accepted(self):
        secret = "test-ipn-secret-abc123"
        payload = json.dumps({"payment_id": "1234", "payment_status": "finished"})
        sig = self._make_sig(secret, payload)
        mod = _load_webhook_handler()
        mod.IPN_SECRET = secret
        result = mod.verify_ipn_signature(payload, sig)
        assert result is True

    def test_wrong_signature_rejected(self):
        secret = "test-ipn-secret-abc123"
        payload = json.dumps({"payment_id": "1234", "payment_status": "finished"})
        mod = _load_webhook_handler()
        mod.IPN_SECRET = secret
        result = mod.verify_ipn_signature(payload, "bad-signature-here")
        assert result is False

    def test_empty_secret_rejects_all(self):
        """No secret configured → reject for security."""
        mod = _load_webhook_handler()
        mod.IPN_SECRET = ""
        result = mod.verify_ipn_signature('{"x":1}', "any-sig")
        assert result is False

    def test_signature_checks_sorted_keys(self):
        """Signature must use sorted JSON — order-independent."""
        secret = "sorted-key-test"
        # Two payloads with same data, different key order
        payload_a = '{"b": 2, "a": 1}'
        payload_b = '{"a": 1, "b": 2}'
        sig_a = self._make_sig(secret, payload_a)
        mod = _load_webhook_handler()
        mod.IPN_SECRET = secret
        # sig_a must validate payload_b (same sorted content)
        assert mod.verify_ipn_signature(payload_b, sig_a) is True


# ---------------------------------------------------------------------------
# Tier extraction
# ---------------------------------------------------------------------------

class TestExtractTier:
    """Tests for _extract_tier from order metadata."""

    def setup_method(self):
        self.mod = _load_webhook_handler()

    def test_tier_from_order_id(self):
        data = {"order_id": "ws123-pro-monthly", "order_description": ""}
        assert self.mod._extract_tier(data) == "pro"

    def test_tier_from_order_description(self):
        data = {"order_id": "some-random-id", "order_description": "OpenClaw Growth plan"}
        assert self.mod._extract_tier(data) == "growth"

    def test_tier_enterprise(self):
        data = {"order_id": "ws_ent_001-enterprise-annual", "order_description": ""}
        assert self.mod._extract_tier(data) == "enterprise"

    def test_fallback_to_starter(self):
        # Note: avoid strings containing tier names as substrings (e.g. "product" contains "pro")
        data = {"order_id": "xyz999", "order_description": "unknown basic plan"}
        assert self.mod._extract_tier(data) == "starter"

    def test_case_insensitive_matching(self):
        data = {"order_id": "WS_001-PRO-plan", "order_description": ""}
        # order_id is lowercased before matching
        assert self.mod._extract_tier(data) == "pro"


# ---------------------------------------------------------------------------
# handle_ipn: full IPN processing flow
# ---------------------------------------------------------------------------

class TestHandleIpn:
    """Integration tests for handle_ipn using an in-memory CreditAccountRepository."""

    def setup_method(self):
        self.mod = _load_webhook_handler()

    def _build_payload(self, status: str, tier: str = "pro", payment_id: str = "pay_001") -> str:
        order_id = f"ws_test-{tier}-monthly"
        return json.dumps({
            "payment_id": payment_id,
            "payment_status": status,
            "order_id": order_id,
            "order_description": f"OpenClaw {tier} plan",
            "pay_amount": "149.00",
            "pay_currency": "usdttrc20",
            "price_amount": 149,
            "price_currency": "usd",
        })

    def test_finished_payment_grants_credits(self, tmp_path):
        """Happy path: finished payment → credits granted to workspace."""
        from src.raas.credit_account_repository import CreditAccountRepository

        # Use tmp_path db to avoid leaking state
        db_file = tmp_path / "workspaces.db"
        repo = CreditAccountRepository(db_file)
        repo.create_account("ws_test")

        payload = self._build_payload("finished", "pro")

        with patch.object(self.mod, "CreditAccountRepository", return_value=repo), \
             patch.object(self.mod, "_log_payment"):
            result = self.mod.handle_ipn(payload, signature="")

        assert result["ok"] is True
        assert result["action"] == "credits_granted"
        assert result["tier"] == "pro"
        assert result["credits"] == 1200  # Pro tier = 1200 credits
        assert result["workspace_id"] == "ws_test"
        assert repo.get_balance("ws_test") == 1200

    def test_confirmed_payment_grants_credits(self, tmp_path):
        """'confirmed' status is also accepted."""
        from src.raas.credit_account_repository import CreditAccountRepository

        db_file = tmp_path / "workspaces.db"
        repo = CreditAccountRepository(db_file)
        repo.create_account("ws_test")

        payload = self._build_payload("confirmed", "starter")

        with patch.object(self.mod, "CreditAccountRepository", return_value=repo), \
             patch.object(self.mod, "_log_payment"):
            result = self.mod.handle_ipn(payload, signature="")

        assert result["ok"] is True
        assert result["credits"] == 300  # Starter = 300 credits

    def test_waiting_status_ignored(self, tmp_path):
        """Non-terminal statuses must NOT grant credits."""
        payload = self._build_payload("waiting", "enterprise")

        with patch.object(self.mod, "_log_payment"):
            result = self.mod.handle_ipn(payload, signature="")

        assert result["ok"] is True
        assert result["action"] == "ignored"
        assert "waiting" in result["reason"]

    def test_expired_status_ignored(self):
        payload = self._build_payload("expired", "pro")
        with patch.object(self.mod, "_log_payment"):
            result = self.mod.handle_ipn(payload, signature="")
        assert result["action"] == "ignored"

    def test_failed_status_ignored(self):
        payload = self._build_payload("failed", "pro")
        with patch.object(self.mod, "_log_payment"):
            result = self.mod.handle_ipn(payload, signature="")
        assert result["action"] == "ignored"

    def test_invalid_signature_rejected(self):
        """Bad HMAC signature must be rejected before any processing."""
        mod = _load_webhook_handler()
        mod.IPN_SECRET = "real-secret"
        payload = self._build_payload("finished", "pro")

        result = mod.handle_ipn(payload, signature="wrong-sig-0000")
        assert result["ok"] is False
        assert result["error"] == "signature_mismatch"

    def test_no_signature_skips_verification(self, tmp_path):
        """Empty signature string bypasses HMAC check (dev mode)."""
        from src.raas.credit_account_repository import CreditAccountRepository

        db_file = tmp_path / "workspaces.db"
        repo = CreditAccountRepository(db_file)
        repo.create_account("ws_test")
        payload = self._build_payload("finished", "growth")

        with patch.object(self.mod, "CreditAccountRepository", return_value=repo), \
             patch.object(self.mod, "_log_payment"):
            result = self.mod.handle_ipn(payload, signature="")

        assert result["ok"] is True

    def test_tier_credits_mapping(self, tmp_path):
        """Each tier maps to the correct credit amount."""
        from src.raas.credit_account_repository import CreditAccountRepository
        expected = {"starter": 300, "pro": 1200, "growth": 3500, "enterprise": 7000}

        for tier, expected_credits in expected.items():
            db_file = tmp_path / f"ws_{tier}.db"
            repo = CreditAccountRepository(db_file)
            repo.create_account("ws_test")
            payload = self._build_payload("finished", tier, payment_id=f"pay_{tier}")

            with patch.object(self.mod, "CreditAccountRepository", return_value=repo), \
                 patch.object(self.mod, "_log_payment"):
                result = self.mod.handle_ipn(payload, signature="")

            assert result["credits"] == expected_credits, f"Wrong credits for tier={tier}"

    def test_workspace_id_extracted_from_order_id(self, tmp_path):
        """workspace_id is the part before the first '-' in order_id."""
        from src.raas.credit_account_repository import CreditAccountRepository

        db_file = tmp_path / "workspaces.db"
        repo = CreditAccountRepository(db_file)
        payload_data = {
            "payment_id": "pay_999",
            "payment_status": "finished",
            "order_id": "myworkspace-pro-monthly",
            "order_description": "pro plan",
        }
        payload = json.dumps(payload_data)

        with patch.object(self.mod, "CreditAccountRepository", return_value=repo), \
             patch.object(self.mod, "_log_payment"):
            result = self.mod.handle_ipn(payload, signature="")

        assert result["workspace_id"] == "myworkspace"

    def test_order_id_without_dash_uses_default(self, tmp_path):
        """Order ID with no '-' defaults workspace_id to 'default'."""
        from src.raas.credit_account_repository import CreditAccountRepository

        db_file = tmp_path / "workspaces.db"
        repo = CreditAccountRepository(db_file)
        payload_data = {
            "payment_id": "pay_888",
            "payment_status": "finished",
            "order_id": "nodashorderid",
            "order_description": "starter plan",
        }
        payload = json.dumps(payload_data)

        with patch.object(self.mod, "CreditAccountRepository", return_value=repo), \
             patch.object(self.mod, "_log_payment"):
            result = self.mod.handle_ipn(payload, signature="")

        assert result["workspace_id"] == "default"


# ---------------------------------------------------------------------------
# Checkout: tier validation guard rails
# ---------------------------------------------------------------------------

class TestCheckoutValidation:
    """Tests for nowpayments_checkout tier validation (no HTTP calls)."""

    def setup_method(self):
        # Import module using hyphenated filename via importlib
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "nowpayments_checkout",
            Path(__file__).parent.parent / "src" / "raas" / "nowpayments_checkout.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.mod = mod

    def test_create_payment_rejects_unknown_tier(self):
        """ValueError must be raised for unknown tier strings."""
        with pytest.raises(ValueError, match="Unknown tier"):
            self.mod.create_payment("diamond", "ws-001-diamond-month")

    def test_create_invoice_rejects_unknown_tier(self):
        with pytest.raises(ValueError, match="Unknown tier"):
            self.mod.create_invoice("platinum", "ws-001")

    def test_get_subscription_link_rejects_unknown_tier(self):
        with pytest.raises(ValueError, match="Unknown tier"):
            self.mod.get_subscription_link("freeforever")

    def test_known_tiers_pass_validation(self):
        """All four known tiers must not raise on validation."""
        for tier in ("starter", "pro", "growth", "enterprise"):
            # Should not raise — will fail at HTTP step, which we mock
            with patch.object(self.mod, "_api_request", return_value={"invoice_url": "https://x"}):
                result = self.mod.create_invoice(tier, f"ws-{tier}")
            assert result is not None

    def test_get_subscription_link_returns_nowpayments_url(self):
        """Subscription link format: https://nowpayments.io/payment/?iid={plan_id}"""
        link = self.mod.get_subscription_link("pro")
        assert "nowpayments.io/payment/" in link
        assert "iid=" in link

    def test_tier_prices_match_spec(self):
        """Verify tier pricing matches the $49/$149/$299/$499 spec."""
        expected_prices = {"starter": 49, "pro": 149, "growth": 299, "enterprise": 499}
        for tier, price in expected_prices.items():
            assert self.mod.TIERS[tier]["price_usd"] == price

    def test_tier_credits_match_spec(self):
        """Verify credit allocations match spec."""
        expected_credits = {"starter": 300, "pro": 1200, "growth": 3500, "enterprise": 7000}
        for tier, credits in expected_credits.items():
            assert self.mod.TIERS[tier]["credits"] == credits


# ---------------------------------------------------------------------------
# Pricing engine: RateCard and Plan calculations
# ---------------------------------------------------------------------------

class TestRateCardCalculation:
    """Tests for RateCard.calculate_charge (no DB dependencies)."""

    def _make_rate_card(
        self,
        included: str = "100",
        unit_price: str = "0.01",
        overage_rate: str | None = None,
    ):
        from src.raas.billing_engine import RateCard
        return RateCard(
            plan_tier="pro",
            event_type="api_call",
            model_name=None,
            unit="call",
            unit_price=Decimal(unit_price),
            included_quantity=Decimal(included),
            overage_rate=Decimal(overage_rate) if overage_rate else None,
            overage_threshold=None,
        )

    def test_within_included_zero_charge(self):
        card = self._make_rate_card(included="100")
        charge, overage = card.calculate_charge(Decimal("50"))
        assert charge == Decimal("0")
        assert overage == Decimal("0")

    def test_exactly_included_zero_charge(self):
        card = self._make_rate_card(included="100")
        charge, overage = card.calculate_charge(Decimal("100"))
        assert charge == Decimal("0")

    def test_overage_uses_unit_price_when_no_overage_rate(self):
        """When overage_rate is None, unit_price is used for overage."""
        card = self._make_rate_card(included="100", unit_price="0.05")
        charge, overage = card.calculate_charge(Decimal("110"))
        assert overage == Decimal("10")
        assert charge == Decimal("10") * Decimal("0.05")  # 0.50

    def test_overage_uses_explicit_overage_rate(self):
        card = self._make_rate_card(included="100", unit_price="0.05", overage_rate="0.02")
        charge, overage = card.calculate_charge(Decimal("120"))
        assert overage == Decimal("20")
        assert charge == Decimal("20") * Decimal("0.02")  # 0.40

    def test_partial_included_remaining(self):
        """When some included quota already consumed, only remainder counts."""
        card = self._make_rate_card(included="100", unit_price="0.10")
        # 60 of 100 included already used → only 40 remaining
        charge, overage = card.calculate_charge(Decimal("80"), included_remaining=Decimal("40"))
        assert overage == Decimal("40")
        assert charge == Decimal("40") * Decimal("0.10")

    def test_zero_quantity_zero_charge(self):
        card = self._make_rate_card()
        charge, _ = card.calculate_charge(Decimal("0"))
        assert charge == Decimal("0")

    def test_large_overage_precision(self):
        """Decimal precision must survive large numbers."""
        card = self._make_rate_card(included="1000", unit_price="0.001")
        charge, overage = card.calculate_charge(Decimal("999999"))
        assert overage == Decimal("998999")
        assert charge == Decimal("998999") * Decimal("0.001")


class TestPlanCreditsToDollars:
    """Tests for Plan.credits_to_dollars unit economics calculation."""

    def setup_method(self):
        from src.raas.pricing import get_plan, PlanTier
        self.get_plan = get_plan
        self.PlanTier = PlanTier

    def test_starter_credits_rate(self):
        """Starter: $29/500 credits = $0.058/credit."""
        plan = self.get_plan(self.PlanTier.STARTER)
        # 500 credits consumed = full $29
        assert plan.credits_to_dollars(500) == 29.0

    def test_pro_credits_rate(self):
        """Pro: $99/2500 credits."""
        plan = self.get_plan(self.PlanTier.PRO)
        assert plan.credits_to_dollars(2500) == 99.0

    def test_zero_credits_zero_dollars(self):
        plan = self.get_plan(self.PlanTier.STARTER)
        assert plan.credits_to_dollars(0) == 0.0

    def test_free_plan_zero_price(self):
        """Free plan has $0 price, credits_to_dollars should return 0."""
        plan = self.get_plan(self.PlanTier.FREE)
        assert plan.credits_to_dollars(50) == 0.0

    def test_partial_usage_proportional(self):
        """Half credits used → half the price."""
        plan = self.get_plan(self.PlanTier.STARTER)
        half_price = plan.credits_to_dollars(250)
        assert abs(half_price - 14.5) < 0.01

    def test_enterprise_unlimited_zero_calculation(self):
        """Enterprise has 0 credits (unlimited) → no per-credit charge."""
        plan = self.get_plan(self.PlanTier.ENTERPRISE)
        assert plan.credits_to_dollars(99999) == 0.0


# ---------------------------------------------------------------------------
# BillingResult serialization
# ---------------------------------------------------------------------------

class TestBillingResultSerialization:
    """Tests for BillingResult.to_dict() and LineItem.to_dict()."""

    def test_line_item_to_dict_has_all_keys(self):
        from datetime import datetime, timezone
        from src.raas.billing_engine import LineItem

        item = LineItem(
            event_type="api_call",
            model_name="claude-3",
            quantity=Decimal("150"),
            unit="call",
            unit_price=Decimal("0.01"),
            subtotal=Decimal("1.50"),
            final_amount=Decimal("1.50"),
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        d = item.to_dict()
        for key in ("event_type", "model_name", "quantity", "unit", "unit_price", "subtotal", "final_amount"):
            assert key in d

    def test_line_item_final_amount_computed_when_zero(self):
        """final_amount auto-computed as subtotal - discount when not given."""
        from src.raas.billing_engine import LineItem

        item = LineItem(
            event_type="token_input",
            model_name=None,
            quantity=Decimal("1000"),
            unit="token",
            unit_price=Decimal("0.001"),
            subtotal=Decimal("1.00"),
            discount=Decimal("0.10"),
            final_amount=Decimal("0"),  # triggers __post_init__ computation
        )
        assert item.final_amount == Decimal("0.90")

    def test_billing_result_to_dict_serializes_line_items(self):
        from datetime import datetime, timezone
        from src.raas.billing_engine import BillingResult, LineItem

        result = BillingResult(
            license_key="lk_test",
            key_id="kid_001",
            period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
            total=Decimal("10.50"),
        )
        result.line_items.append(
            LineItem(
                event_type="api_call",
                model_name=None,
                quantity=Decimal("100"),
                unit="call",
                unit_price=Decimal("0.01"),
                subtotal=Decimal("1.00"),
                final_amount=Decimal("1.00"),
            )
        )
        d = result.to_dict()
        assert d["license_key"] == "lk_test"
        assert d["total"] == "10.50"
        assert len(d["line_items"]) == 1
        assert d["line_items"][0]["event_type"] == "api_call"

    def test_billing_result_empty_events(self):
        """Empty line_items list serializes cleanly."""
        from datetime import datetime, timezone
        from src.raas.billing_engine import BillingResult

        result = BillingResult(
            license_key="lk_empty",
            key_id="",
            period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
        )
        d = result.to_dict()
        assert d["line_items"] == []
        assert d["total"] == "0"


# ---------------------------------------------------------------------------
# Idempotency: BatchRecord serialization
# ---------------------------------------------------------------------------

class TestBatchRecordSerialization:
    """Tests for BatchRecord/BatchResult data integrity (no DB)."""

    def test_batch_status_enum_values(self):
        from src.billing.idempotency import BatchStatus
        assert BatchStatus.PENDING == "pending"
        assert BatchStatus.PROCESSING == "processing"
        assert BatchStatus.COMPLETED == "completed"
        assert BatchStatus.FAILED == "failed"

    def test_batch_id_generation_deterministic(self):
        """Same license + events + date → same batch_id."""
        from datetime import datetime, timezone
        from src.billing.idempotency import IdempotencyManager

        manager = IdempotencyManager.__new__(IdempotencyManager)
        events = [
            {"event_type": "api_call", "value": 100, "metric": "calls"},
            {"event_type": "token_input", "value": 500, "metric": "tokens"},
        ]
        ts = datetime(2026, 4, 1, tzinfo=timezone.utc)
        id1 = manager.generate_batch_id("lk_test", events, ts)
        id2 = manager.generate_batch_id("lk_test", events, ts)
        assert id1 == id2

    def test_batch_id_different_events_differ(self):
        from datetime import datetime, timezone
        from src.billing.idempotency import IdempotencyManager

        manager = IdempotencyManager.__new__(IdempotencyManager)
        ts = datetime(2026, 4, 1, tzinfo=timezone.utc)
        events_a = [{"event_type": "api_call", "value": 100, "metric": "calls"}]
        events_b = [{"event_type": "api_call", "value": 200, "metric": "calls"}]
        assert manager.generate_batch_id("lk", events_a, ts) != manager.generate_batch_id("lk", events_b, ts)

    def test_batch_id_order_independent(self):
        """Event order must not affect batch_id (sorted before hashing)."""
        from datetime import datetime, timezone
        from src.billing.idempotency import IdempotencyManager

        manager = IdempotencyManager.__new__(IdempotencyManager)
        ts = datetime(2026, 4, 1, tzinfo=timezone.utc)
        ev1 = {"event_type": "api_call", "value": 10, "metric": "calls"}
        ev2 = {"event_type": "token_input", "value": 50, "metric": "tokens"}
        id_ab = manager.generate_batch_id("lk", [ev1, ev2], ts)
        id_ba = manager.generate_batch_id("lk", [ev2, ev1], ts)
        assert id_ab == id_ba

    def test_batch_record_from_dict_roundtrip(self):
        from datetime import datetime, timezone
        from src.billing.idempotency import BatchRecord, BatchStatus

        now = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        record = BatchRecord(
            batch_id="batch_lk_20260401_abc123",
            license_key="lk_test",
            key_id="kid_001",
            events_count=5,
            status=BatchStatus.COMPLETED,
            created_at=now,
            billing_record_id="br_001",
        )
        d = record.to_dict()
        restored = BatchRecord.from_dict(d)

        assert restored.batch_id == record.batch_id
        assert restored.status == BatchStatus.COMPLETED
        assert restored.billing_record_id == "br_001"
        assert restored.events_count == 5


# ---------------------------------------------------------------------------
# Plan catalog completeness
# ---------------------------------------------------------------------------

class TestPlanCatalog:
    """Tests for plan catalog integrity."""

    def test_all_tiers_have_non_negative_price(self):
        from src.raas.pricing import list_plans
        for plan in list_plans():
            assert plan.price_monthly >= 0

    def test_all_tiers_have_features(self):
        from src.raas.pricing import list_plans
        for plan in list_plans():
            assert len(plan.features) > 0, f"Plan {plan.tier} has no features"

    def test_plan_tiers_are_unique(self):
        from src.raas.pricing import list_plans
        tiers = [p.tier for p in list_plans()]
        assert len(tiers) == len(set(tiers))

    def test_projections_are_ordered(self):
        from src.raas.pricing import get_projections
        projections = get_projections()
        months = [p.month for p in projections]
        assert months == sorted(months)

    def test_projections_mrr_grows(self):
        from src.raas.pricing import get_projections
        projections = get_projections()
        mrrs = [p.mrr for p in projections]
        for i in range(1, len(mrrs)):
            assert mrrs[i] > mrrs[i - 1], "MRR must grow each projection period"
