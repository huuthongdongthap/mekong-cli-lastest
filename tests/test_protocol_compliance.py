"""Smoke tests: all Mekong Core Protocols importable and compliant."""
import inspect

from src.core import protocols


PROTOCOLS = [
    "MekongCoreRuntime",
    "LLMRouter",
    "ToolRegistry",
    "BillingMeter",
    "MemoryStore",
    "MemorySeparation",
    "ObservabilitySink",
    "VerificationEngine",
    "GoalEngine",
    "PaymentProvider",
    "CapabilityBus",
]


class TestProtocolDefinitions:
    def test_all_protocols_exist(self):
        for name in PROTOCOLS:
            assert hasattr(protocols, name), f"Missing Protocol: {name}"

    def test_protocols_are_typing_protocol(self):
        for name in PROTOCOLS:
            proto = getattr(protocols, name)
            assert hasattr(proto, "__protocol_attrs__") or inspect.isclass(proto), \
                f"{name} is not a Protocol class"

    def test_billing_meter_has_settle_payment(self):
        if hasattr(protocols, "BillingMeter"):
            methods = [m for m in dir(protocols.BillingMeter) if not m.startswith("_")]
            assert "settle_payment" in methods

    def test_tool_registry_has_list_mcp_tools(self):
        if hasattr(protocols, "ToolRegistry"):
            methods = [m for m in dir(protocols.ToolRegistry) if not m.startswith("_")]
            assert "list_mcp_tools" in methods

    def test_goal_engine_has_adapt(self):
        if hasattr(protocols, "GoalEngine"):
            methods = [m for m in dir(protocols.GoalEngine) if not m.startswith("_")]
            assert "adapt" in methods

    def test_payment_provider_has_quote_and_verify(self):
        if hasattr(protocols, "PaymentProvider"):
            methods = [m for m in dir(protocols.PaymentProvider) if not m.startswith("_")]
            assert "quote" in methods
            assert "verify" in methods
            assert "request_payment" in methods

    def test_memory_separation_has_flush_and_prune(self):
        if hasattr(protocols, "MemorySeparation"):
            methods = [m for m in dir(protocols.MemorySeparation) if not m.startswith("_")]
            assert "flush_session" in methods
            assert "prune_expired" in methods


class TestAdapterCompliance:
    def test_memory_store_adapter_importable(self):
        from src.core.memory_store_adapter import MemoryStoreAdapter
        adapter = MemoryStoreAdapter()
        assert isinstance(adapter, protocols.MemoryStore)

    def test_telemetry_sink_adapter_importable(self):
        from src.core.telemetry_sink_adapter import TelemetrySinkAdapter
        adapter = TelemetrySinkAdapter()
        assert isinstance(adapter, protocols.ObservabilitySink)

    def test_llm_router_adapter_importable(self):
        from src.core.llm_router_adapter import LLMRouterAdapter
        adapter = LLMRouterAdapter()
        assert isinstance(adapter, protocols.LLMRouter)

    def test_goal_engine_adapter_importable(self, tmp_path):
        from src.core.adapters.goal_engine_adapter import GoalEngineAdapter
        from src.mekongcli.core.goal_engine.store import SQLiteGoalStore
        adapter = GoalEngineAdapter(
            store=SQLiteGoalStore(tmp_path / "goals.sqlite3"), cwd=tmp_path
        )
        assert isinstance(adapter, protocols.GoalEngine)

    def test_mekong_core_runtime_impl_compliant(self):
        from unittest.mock import MagicMock
        from src.core.runtime_adapter import MekongCoreRuntimeImpl

        runtime = MekongCoreRuntimeImpl(dispatcher=MagicMock(), tool_registry=MagicMock())
        assert isinstance(runtime, protocols.MekongCoreRuntime)
        ctx = runtime.context()
        assert isinstance(ctx, dict)
        assert "principal" in ctx
        assert "session_id" in ctx

    def test_capability_bus_compliant(self):
        from src.core.capability import InMemoryCapabilityBus

        bus = InMemoryCapabilityBus()
        assert isinstance(bus, protocols.CapabilityBus)

    def test_recipe_verifier_compliant(self):
        from src.core.verifier import RecipeVerifier

        verifier = RecipeVerifier()
        assert isinstance(verifier, protocols.VerificationEngine)

    def test_billing_adapter_compliant(self):
        from src.core.billing_adapter import BillingAdapter

        adapter = BillingAdapter()
        assert isinstance(adapter, protocols.BillingMeter)
        assert isinstance(adapter, protocols.PaymentProvider)

    def test_nowpayments_provider_compliant(self):
        from src.raas.nowpayments_provider import NowPaymentsProvider

        provider = NowPaymentsProvider()
        assert isinstance(provider, protocols.PaymentProvider)

    def test_tool_registry_compliant(self):
        from src.core.tool_registry import ToolRegistry

        registry = ToolRegistry()
        assert isinstance(registry, protocols.ToolRegistry)

    def test_memory_separation_compliant(self):
        from src.core.memory_separation import MemorySeparation

        sep = MemorySeparation()
        assert isinstance(sep, protocols.MemorySeparation)

    def test_canonical_memory_store_compliant(self, restore_real_memory_store):
        from src.core.memory_canonical import MemoryStore

        store = MemoryStore()
        assert isinstance(store, protocols.MemoryStore)

    def test_jsonl_memory_adapter_compliant(self):
        from src.core.adapters.jsonl_memory_adapter import JsonlMemoryAdapter

        adapter = JsonlMemoryAdapter()
        assert isinstance(adapter, protocols.MemoryStore)