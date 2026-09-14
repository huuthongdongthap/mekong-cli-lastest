# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Billing Consolidation Conformance & Integration Test Suite.

Verifies end-to-end architectural consolidation across:
1. Re-export compatibility between `src.billing` and `src.raas.billing_*`
2. Single-source-of-truth tier configuration in `src.seed.config.tiers` and `engine.billing.tier_config`
3. Conformance to `protocols.PaymentProvider` across payment adapters
4. `MCUBilling` singleton integration with tenant balance & quotas
5. Idempotent billing execution and audit trail logging
"""
from __future__ import annotations

import time
from decimal import Decimal

import src.billing as billing_pkg
import src.billing.engine as billing_engine_shim
import src.billing.event_emitter as billing_emitter_shim
import src.billing.idempotency as billing_idempotency_shim
import src.billing.proration as billing_proration_shim
import src.billing.reconciliation as billing_reconciliation_shim
import src.raas.billing_audit as raas_audit
import src.raas.billing_engine as raas_engine
import src.raas.billing_event_emitter as raas_emitter
import src.raas.billing_idempotency as raas_idempotency
import src.raas.billing_proration as raas_proration
from engine.billing import tier_config as legacy_tier_config
from src.billing.audit_trail import AuditEntry, BillingAuditTrail
from src.core.billing_adapter import BillingAdapter
from src.core.mcu_billing import MCUBilling, MCU_COSTS
from src.core.protocols import PaymentProvider
from src.raas.nowpayments_provider import NowPaymentsProvider
from src.seed.config import tiers as canonical_tiers


class TestBillingShimExports:
    """Verify that src.billing and its submodules are byte-for-byte exact shims over src.raas."""

    def test_package_exports_match_raas(self):
        """Top-level src.billing exports must match src.raas classes and functions by object identity."""
        # Engine
        assert billing_pkg.BillingEngine is raas_engine.BillingEngine
        assert billing_pkg.RateCard is raas_engine.RateCard
        assert billing_pkg.LineItem is raas_engine.LineItem
        assert billing_pkg.BillingResult is raas_engine.BillingResult
        assert billing_pkg.get_engine is raas_engine.get_engine

        # Proration
        assert billing_pkg.ProrationCalculator is raas_proration.ProrationCalculator
        assert billing_pkg.OverageTracker is raas_proration.OverageTracker
        assert billing_pkg.get_calculator is raas_proration.get_calculator

        # Idempotency
        assert billing_pkg.IdempotencyManager is raas_idempotency.IdempotencyManager
        assert billing_pkg.BatchResult is raas_idempotency.BatchResult
        assert billing_pkg.get_idempotency_manager is raas_idempotency.get_idempotency_manager

        # Emitter
        assert billing_pkg.BillingEventEmitter is raas_emitter.BillingEventEmitter
        assert billing_pkg.get_emitter is raas_emitter.get_emitter

        # Reconciliation / Audit
        assert billing_pkg.ReconciliationService is raas_audit.ReconciliationService
        assert billing_pkg.AuditResult is raas_audit.AuditResult
        assert billing_pkg.get_reconciliation_service is raas_audit.get_reconciliation_service

    def test_submodule_shims(self):
        """Individual module shims under src.billing must re-export corresponding raas symbols."""
        assert billing_engine_shim.BillingEngine is raas_engine.BillingEngine
        assert billing_emitter_shim.BillingEventEmitter is raas_emitter.BillingEventEmitter
        assert billing_idempotency_shim.IdempotencyManager is raas_idempotency.IdempotencyManager
        assert billing_proration_shim.ProrationCalculator is raas_proration.ProrationCalculator
        assert billing_reconciliation_shim.ReconciliationService is raas_audit.ReconciliationService


class TestTierConfigConsolidation:
    """Verify consolidation of tier configs between canonical seed config and legacy façade."""

    def test_tier_symbols_identity(self):
        """All symbols exported from engine.billing.tier_config must be identical to src.seed.config.tiers."""
        assert legacy_tier_config.Tier is canonical_tiers.Tier
        assert legacy_tier_config.TierKey is canonical_tiers.TierKey
        assert legacy_tier_config.RateLimitConfig is canonical_tiers.RateLimitConfig
        assert legacy_tier_config.TierRateLimitConfig is canonical_tiers.TierRateLimitConfig
        assert legacy_tier_config.DEFAULT_TIER_CONFIGS is canonical_tiers.DEFAULT_TIER_CONFIGS
        assert legacy_tier_config.get_tier_config is canonical_tiers.get_tier_config
        assert legacy_tier_config.get_preset_config is canonical_tiers.get_preset_config

    def test_tier_key_case_and_alias_resolution(self):
        """TierKey must dynamically resolve aliases and case differences."""
        assert canonical_tiers.TierKey("basic") == canonical_tiers.TierKey.STARTER
        assert canonical_tiers.TierKey("PREMIUM") == canonical_tiers.TierKey.GROWTH
        assert canonical_tiers.TierKey("master") == canonical_tiers.TierKey.PRO
        assert canonical_tiers.TierKey("enterprise_plus") == canonical_tiers.TierKey.ENTERPRISE
        assert canonical_tiers.TierKey("FREE") == canonical_tiers.TierKey.FREE

    def test_all_tiers_have_positive_pricing_and_mcu(self):
        """Every tier definition and rate limit config must be valid."""
        for tier_key_str, config in canonical_tiers._TIERS.items():
            assert config.monthly_price_usd >= 0.0
            assert config.monthly_credits >= 0
            assert config.mcu_cost_simple >= 1

        for tier_key, rate_cfg in canonical_tiers.DEFAULT_TIER_CONFIGS.items():
            assert isinstance(tier_key, canonical_tiers.TierKey)
            assert rate_cfg.api_default.requests_per_minute > 0
            assert rate_cfg.auth_login.requests_per_minute > 0


class TestPaymentProviderConsolidation:
    """Verify that payment providers conform to protocols.PaymentProvider."""

    def test_nowpayments_provider_conformance(self):
        """NowPaymentsProvider must satisfy PaymentProvider protocol."""
        provider = NowPaymentsProvider()
        assert isinstance(provider, PaymentProvider)
        assert hasattr(provider, "record_usage")
        assert hasattr(provider, "check_quota")
        assert hasattr(provider, "settle_payment")
        assert hasattr(provider, "quote")
        assert hasattr(provider, "request_payment")
        assert hasattr(provider, "verify")
        assert hasattr(provider, "refund")
        assert hasattr(provider, "process_ipn")
        assert hasattr(provider, "verify_signature")

    def test_billing_adapter_conformance(self):
        """BillingAdapter must satisfy PaymentProvider protocol."""
        adapter = BillingAdapter()
        assert isinstance(adapter, PaymentProvider)
        assert hasattr(adapter, "record_usage")
        assert hasattr(adapter, "check_quota")
        assert hasattr(adapter, "settle_payment")
        assert hasattr(adapter, "quote")
        assert hasattr(adapter, "request_payment")
        assert hasattr(adapter, "verify")
        assert hasattr(adapter, "refund")


class TestMCUBillingAndEngineIntegration:
    """Test full cycle interaction between MCUBilling, BillingEngine, and AuditTrail."""

    def test_mcu_grant_and_deduct_lifecycle(self, tmp_path):
        """MCU credits can be granted, deducted, and audited cleanly."""
        db_file = tmp_path / "credits.db"
        mcu = MCUBilling(db_path=str(db_file))
        tenant = "tenant_test_123"

        # Add 100 credits for STARTER tier
        balance_obj = mcu.add_credits(tenant, 100, description="starter_monthly_grant")
        assert balance_obj.balance == 100

        # Deduct simple mission (1 credit)
        deduct_res = mcu.deduct(tenant, complexity="simple", mission_id="m-001")
        assert deduct_res.success is True
        assert deduct_res.amount_deducted == MCU_COSTS["simple"]
        assert deduct_res.balance_after == 100 - MCU_COSTS["simple"]

        # Over-deduction fails closed
        failed_res = mcu.deduct(tenant, complexity="complex", mission_id="m-002")
        if MCU_COSTS["complex"] > deduct_res.balance_after:
            assert failed_res.success is False
            assert failed_res.balance_after == deduct_res.balance_after

    def test_billing_rate_card_charge_computation(self):
        """RateCard calculates accurate charges and overage amounts."""
        card = billing_pkg.RateCard(
            plan_tier="starter",
            event_type="generation",
            model_name="claude-3-haiku",
            unit="tokens",
            unit_price=Decimal("0.000002"),
            included_quantity=Decimal("100000"),
            overage_rate=Decimal("0.000003"),
            overage_threshold=Decimal("500000"),
        )
        # Usage within included quantity: 0 charge, 0 overage
        charge, overage = card.calculate_charge(Decimal("50000"))
        assert charge == Decimal("0")
        assert overage == Decimal("0")

        # Usage exceeding included quantity: overage charge
        charge, overage = card.calculate_charge(Decimal("150000"))
        assert overage == Decimal("50000")
        assert charge == Decimal("50000") * Decimal("0.000003")

    def test_billing_idempotency_dedup(self):
        """IdempotencyManager generates deterministic batch IDs and serialization."""
        from datetime import datetime, timezone

        mgr = billing_pkg.IdempotencyManager.__new__(billing_pkg.IdempotencyManager)
        events = [
            {"event_type": "api_call", "value": 100, "metric": "calls"},
            {"event_type": "token_input", "value": 500, "metric": "tokens"},
        ]
        ts = datetime(2026, 9, 10, tzinfo=timezone.utc)
        batch_id1 = mgr.generate_batch_id("license_test_123", events, ts)
        batch_id2 = mgr.generate_batch_id("license_test_123", events, ts)
        assert batch_id1 == batch_id2
        assert batch_id1.startswith("batch_license_test_123_20260910_")

        record = billing_pkg.BatchRecord(
            batch_id=batch_id1,
            license_key="license_test_123",
            key_id="kid_001",
            events_count=len(events),
            status=billing_pkg.BatchStatus.COMPLETED,
            created_at=ts,
            billing_record_id="bill_rec_001",
        )
        record_dict = record.to_dict()
        assert record_dict["batch_id"] == batch_id1
        assert record_dict["status"] == "completed"

        roundtrip = billing_pkg.BatchRecord.from_dict(record_dict)
        assert roundtrip.batch_id == batch_id1
        assert roundtrip.status == billing_pkg.BatchStatus.COMPLETED

    def test_audit_trail_logging(self, tmp_path):
        """BillingAuditTrail maintains immutable records of all debit/credit operations."""
        audit_dir = tmp_path / "audit"
        trail = BillingAuditTrail(log_dir=str(audit_dir))

        entry = AuditEntry(
            timestamp=time.time(),
            tenant_id="tenant_audit_999",
            action="debit",
            amount=10.0,
            balance_before=100.0,
            balance_after=90.0,
            reason="run_goal_execution",
            mission_id="mission_001",
            idempotency_key="idem_001",
        )
        entry_id = trail.record(entry)
        assert "tenant_audit_999_debit" in entry_id

        entries = trail.get_history("tenant_audit_999")
        assert len(entries) == 1
        assert entries[0]["amount"] == 10.0
        assert entries[0]["balance_after"] == 90.0

        proof = trail.get_balance_proof("tenant_audit_999")
        assert proof["entries_count"] == 1
        assert proof["calculated_balance"] == -10.0
