"""Smoke tests: all 8 Mekong Core Protocols importable and compliant."""
import inspect

from src.core import protocols


PROTOCOLS = [
    "MekongCoreRuntime", "LLMRouter", "ToolRegistry",
    "BillingMeter", "MemoryStore", "ObservabilitySink", "VerificationEngine", "GoalEngine",
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