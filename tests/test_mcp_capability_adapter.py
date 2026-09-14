# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for MCPCapabilityAdapter — MCP→Capability bridge.

Uses the REAL MekongMcpServer (no MagicMock server masking) so that both
defects are exercised end-to-end:
  1. The adapter must import and construct MekongMcpServer (not a missing
     ``MCPServer`` name) — verified by real discovery of all cc_* tools.
  2. Handler resolution must strip the ``cc_`` prefix so that read-only tools
     actually execute through ``_handle_<base>()``.

``_FakeBus`` is retained as a legitimate CapabilityBus seam (the bus protocol
is covered by its own conformance tests); only the server is real here.
"""
from __future__ import annotations

import pytest

from src.core.adapters.mcp_capability_adapter import MCPCapabilityAdapter
from src.core.capability import Capability, CapabilitySource
from src.core.protocols import CapabilityBus as CapabilityBusProtocol

try:
    import mcp  # noqa: F401

    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False

requires_sdk = pytest.mark.skipif(
    not _SDK_AVAILABLE, reason="mcp SDK not installed — real-server tests need it"
)


class _FakeBus:
    """Minimal CapabilityBus for testing MCPCapabilityAdapter."""

    def __init__(self):
        self._caps: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        self._caps[capability.id] = capability

    def unregister(self, capability_id: str) -> bool:
        if capability_id in self._caps:
            del self._caps[capability_id]
            return True
        return False

    def get(self, capability_id: str) -> Capability | None:
        return self._caps.get(capability_id)

    def list_capabilities(self, risk_level=None, source=None):
        caps = list(self._caps.values())
        if risk_level:
            caps = [c for c in caps if c.risk_level == risk_level]
        if source:
            caps = [c for c in caps if c.source == source]
        return caps

    def discover(self, query: str):
        q = query.lower()
        return [c for c in self._caps.values()
                if q in c.name.lower() or q in c.description.lower()
                or any(q in t.lower() for t in c.tags)]

    def execute(self, capability_id: str, params: dict, context=None):
        cap = self._caps.get(capability_id)
        if cap is None:
            return {"error": f"Capability {capability_id} not found"}
        return cap.execute(params, context)

    def check_authorization(self, capability_id: str, principal: str) -> bool:
        cap = self._caps.get(capability_id)
        if cap is None or cap.authorization is None:
            return True
        return principal == cap.authorization

    def cleanup(self) -> int:
        expired = [cid for cid, cap in self._caps.items() if cap.is_expired()]
        for cid in expired:
            del self._caps[cid]
        return len(expired)


def _make_adapter() -> tuple[MCPCapabilityAdapter, _FakeBus]:
    adapter = MCPCapabilityAdapter()
    bus = _FakeBus()
    adapter.bus = bus
    return adapter, bus


class TestMCPCapabilityAdapterBasics:
    def test_adapter_creation(self):
        """MCPCapabilityAdapter must be instantiable."""
        adapter = MCPCapabilityAdapter()
        assert adapter is not None

    def test_bus_assignment(self):
        """bus property must accept and return CapabilityBus."""
        adapter = MCPCapabilityAdapter()
        bus = _FakeBus()
        adapter.bus = bus
        assert adapter.bus is bus

    def test_sync_requires_bus(self):
        """sync_from_mcp must raise if bus is not set."""
        adapter = MCPCapabilityAdapter()
        with pytest.raises(RuntimeError, match="CapabilityBus not set"):
            adapter.sync_from_mcp()

    def test_get_mcp_server_is_real_server(self):
        """_get_mcp_server must return a real MekongMcpServer, never None."""
        from src.core.mcp_server import MekongMcpServer

        adapter = MCPCapabilityAdapter()
        server = adapter._get_mcp_server()
        assert isinstance(server, MekongMcpServer)
        assert type(server).__name__ == "MekongMcpServer"

    def test_get_capability_without_bus(self):
        """get_capability returns None when bus not set."""
        adapter = MCPCapabilityAdapter()
        assert adapter.get_capability("anything") is None

    def test_fake_bus_satisfies_protocol(self):
        """_FakeBus must satisfy CapabilityBus Protocol."""
        assert isinstance(_FakeBus(), CapabilityBusProtocol)


@requires_sdk
class TestRealServerDiscovery:
    """Discovery against the REAL MekongMcpServer (no MagicMock masking)."""

    def test_sync_discovers_full_toolset(self):
        """sync_from_mcp must discover the server's full cc_* toolset (>=20)."""
        adapter, bus = _make_adapter()
        caps = adapter.sync_from_mcp()

        server = adapter._get_mcp_server()
        server_tool_count = len(getattr(server, "_tools", []))

        assert len(caps) >= 20
        assert len(caps) == server_tool_count
        assert all(isinstance(c, Capability) for c in caps)
        assert all(c.source == CapabilitySource.MCP for c in caps)

    def test_sync_registers_all_server_tools_by_id(self):
        """Every tool the server exposes must be registered as mcp:<tool_name>."""
        adapter, bus = _make_adapter()
        adapter.sync_from_mcp()

        server = adapter._get_mcp_server()
        server_tool_names = {t["name"] for t in getattr(server, "_tools", [])}
        registered_ids = {c.id for c in bus.list_capabilities()}

        assert registered_ids == {f"mcp:{name}" for name in server_tool_names}

    def test_capability_ids_keep_cc_prefix(self):
        """Capability ids must keep the public ``cc_`` prefix (mcp:cc_*)."""
        adapter, bus = _make_adapter()
        adapter.sync_from_mcp()

        cap = bus.get("mcp:cc_skills_list")
        assert cap is not None
        assert cap.id == "mcp:cc_skills_list"

    def test_sync_risk_level_medium(self):
        """MCP capabilities default to MEDIUM risk."""
        adapter, bus = _make_adapter()
        adapter.sync_from_mcp()
        cap = bus.get("mcp:cc_skills_list")
        assert cap.risk_level == "MEDIUM"

    def test_sync_tags_include_mcp(self):
        """MCP capabilities must have 'mcp' tag."""
        adapter, bus = _make_adapter()
        adapter.sync_from_mcp()
        cap = bus.get("mcp:cc_mcp_list")
        assert "mcp" in cap.tags

    def test_handler_metadata_uses_stripped_name(self):
        """metadata['handler'] must reference the prefix-stripped method name."""
        adapter, bus = _make_adapter()
        adapter.sync_from_mcp()
        cap = bus.get("mcp:cc_tasks_list")
        assert cap.metadata["handler"] == "_handle_tasks_list"

    def test_sync_idempotent(self):
        """Calling sync_from_mcp twice must not duplicate registrations."""
        adapter, bus = _make_adapter()
        first = adapter.sync_from_mcp()
        second = adapter.sync_from_mcp()

        assert len(first) >= 20
        assert second == []
        assert len(bus.list_capabilities()) == len(first)

    def test_get_capability_by_tool_name(self):
        """get_capability returns the registered capability by tool name."""
        adapter, bus = _make_adapter()
        adapter.sync_from_mcp()
        cap = adapter.get_capability("cc_skills_list")
        assert cap is not None
        assert cap.id == "mcp:cc_skills_list"


@requires_sdk
class TestRealHandlerExecution:
    """Execute real handlers through the bus — no mock-che."""

    def test_execute_skills_list_read_only(self):
        """cc_skills_list (read-only) must execute through the stripped handler."""
        adapter, bus = _make_adapter()
        adapter.sync_from_mcp()

        result = bus.get("mcp:cc_skills_list").execute({})
        assert result["ok"] is True
        assert result["tool"] == "cc_skills_list"

    def test_execute_mcp_list_read_only(self):
        """cc_mcp_list (read-only) must execute through the stripped handler."""
        adapter, bus = _make_adapter()
        adapter.sync_from_mcp()

        result = bus.get("mcp:cc_mcp_list").execute({})
        assert result["ok"] is True
        assert result["tool"] == "cc_mcp_list"

    def test_execute_via_bus_execute(self):
        """bus.execute() must route to the real handler and return ok=True."""
        adapter, bus = _make_adapter()
        adapter.sync_from_mcp()

        result = bus.execute("mcp:cc_skills_list", {})
        assert result["ok"] is True

    def test_execute_result_wraps_handler_json(self):
        """execute() must wrap the handler's JSON string under 'result'."""
        adapter, bus = _make_adapter()
        adapter.sync_from_mcp()

        result = bus.get("mcp:cc_mcp_list").execute({})
        assert result["ok"] is True
        # The handler returns a JSON string; it must be present under 'result'.
        assert isinstance(result["result"], str)
        assert '"ok": true' in result["result"]


@requires_sdk
class TestFallbackAndDegradation:
    def test_fallback_unknown_tool(self):
        """A tool with no matching handler must hit the fallback error path."""
        adapter, _ = _make_adapter()
        handler = adapter._build_handler("cc_nonexistent_tool")
        result = handler({})
        assert "error" in result
        assert "No handler" in result["error"]

    def test_sync_empty_when_sdk_unavailable(self):
        """When the MCP SDK is absent, create_app raises and sync returns []."""
        import src.core.mcp_server as mcp_module

        adapter, bus = _make_adapter()
        original = mcp_module._HAS_MCP
        mcp_module._HAS_MCP = False
        try:
            caps = adapter.sync_from_mcp()
            assert caps == []
        finally:
            mcp_module._HAS_MCP = original


class _ExternalShapedServer:
    """Duck-typed MCP server: exposes ``create_app()`` + ``_tools`` plus the
    ``_handle_<base>`` dispatch methods, exactly like ``MekongMcpServer``.

    The adapter never imports this name — it only relies on the structural
    protocol (``create_app`` populates ``_tools``; ``_handle_<base>`` is
    resolved via ``getattr``). This is Task 5 acceptance: an EXTERNAL-shaped
    server can be synced onto the bus without being a concrete
    ``MekongMcpServer``.
    """

    def __init__(self, name: str = "external-ai-os") -> None:
        self.name = name
        self._tools: list[dict[str, str]] = [
            {"name": "external_tool", "description": "External MCP tool"},
        ]

    def create_app(self) -> dict[str, str]:
        """Return a dummy app object — the adapter never inspects its type."""
        return {"name": self.name}

    def _handle_external_tool(self, payload: str = "default") -> str:
        return f"external-handler:{payload}"


class TestExternalShapedServerSync:
    """Task 5 acceptance: an EXTERNAL-shaped server (duck-typed) syncs onto
    the bus and ``bus.execute("mcp:<tool>")`` routes through the governance
    path with zero subprocess / zero library call."""

    def test_external_server_syncs_capabilities(self):
        """An external-shaped server yields one registered MCP capability."""
        bus = _FakeBus()
        adapter = MCPCapabilityAdapter(bus=bus, mcp_server=_ExternalShapedServer())
        caps = adapter.sync_from_mcp()

        assert len(caps) == 1
        cap = caps[0]
        assert cap.id == "mcp:external_tool"
        assert cap.source == CapabilitySource.MCP
        assert cap.risk_level == "MEDIUM"
        assert bus.get("mcp:external_tool") is cap

    def test_external_server_execute_via_bus(self):
        """bus.execute("mcp:external_tool") routes to the external handler."""
        bus = _FakeBus()
        adapter = MCPCapabilityAdapter(bus=bus, mcp_server=_ExternalShapedServer())
        adapter.sync_from_mcp()

        result = bus.execute("mcp:external_tool", {"payload": "hi"})
        assert result["ok"] is True
        assert result["tool"] == "external_tool"
        assert "external-handler:hi" in result["result"]

    def test_external_server_is_not_mekong_mcp_server(self):
        """Acceptance Task 5: the external server is NOT a MekongMcpServer."""
        from src.core.mcp_server import MekongMcpServer

        adapter = MCPCapabilityAdapter(mcp_server=_ExternalShapedServer())
        assert not isinstance(adapter._get_mcp_server(), MekongMcpServer)
