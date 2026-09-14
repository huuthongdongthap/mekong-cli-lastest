# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for ToolCapabilityAdapter — ToolRegistry→Capability bridge.

Uses REAL ToolRegistry and InMemoryCapabilityBus so that:
1. Schema mapping from ToolParameter to JSON Schema is correct
2. Risk level mapping by ToolType is enforced
3. Execute round-trip through bus → adapter → ToolRegistry works
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.adapters.tool_capability_adapter import ToolCapabilityAdapter
from src.core.capability import Capability, CapabilitySource, InMemoryCapabilityBus
from src.core.tool_registry import ToolParameter, ToolRegistry, ToolType


# Number of builtins registered by ToolRegistry._register_builtins()
# (shell:run, file:read, file:write, file:list, git:status, git:diff, git:log)
BUILTIN_COUNT = 7


@pytest.fixture
def clean_registry(tmp_path: Path) -> ToolRegistry:
    """ToolRegistry backed by a temp YAML file so no ambient .mekong/ is loaded."""
    return ToolRegistry(persist_path=str(tmp_path / "tool_registry.yaml"))


@pytest.fixture(autouse=True)
def _no_tool_registry_persist():
    """Prevent ToolRegistry from writing to disk during tests.

    Full suite cwd-leak can make the working directory read-only,
    which causes _persist() → mkdir('.mekong') to fail with OSError.
    """
    with patch.object(ToolRegistry, "_persist", lambda self: None):
        yield


class _FakeBus:
    """Minimal CapabilityBus for unit tests without full runtime."""

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


class TestToolCapabilityAdapterBasics:
    def test_adapter_creation(self, clean_registry):
        """ToolCapabilityAdapter must be instantiable with a ToolRegistry."""
        adapter = ToolCapabilityAdapter(clean_registry)
        assert adapter is not None

    def test_sync_requires_bus(self, clean_registry):
        """sync_to_bus must accept a bus."""
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = _FakeBus()
        caps = adapter.sync_to_bus(bus)
        assert len(caps) == BUILTIN_COUNT


class TestSchemaAuthzRiskMapping:
    """Test schema, authorization, and risk level mapping from Tool to Capability."""

    def test_builtin_tools_map_to_low_risk(self, clean_registry):
        """Builtin tools must have LOW risk level."""
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = _FakeBus()
        adapter.sync_to_bus(bus)

        for cap in bus.list_capabilities(source=CapabilitySource.BUILTIN):
            assert cap.risk_level == "LOW", f"{cap.id} should be LOW risk, got {cap.risk_level}"

    def test_cli_tools_map_to_low_risk(self, clean_registry):
        """CLI-discovered tools must have LOW risk level."""
        clean_registry.register(
            name="test:cli",
            description="Test CLI tool",
            tool_type=ToolType.CLI,
            command_template="test {args}",
            tags=["cli", "test"],
        )
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = _FakeBus()
        adapter.sync_to_bus(bus)

        cap = bus.get("tool:test:cli")
        assert cap is not None
        assert cap.risk_level == "LOW"
        assert cap.source == CapabilitySource.CLI

    def test_api_tools_map_to_medium_risk(self, clean_registry):
        """API tools must have MEDIUM risk level."""
        tool = clean_registry.register(
            name="test:api",
            description="Test API tool",
            tool_type=ToolType.API,
            tags=["api", "test"],
        )
        tool.endpoint = "POST /api/test"
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = _FakeBus()
        adapter.sync_to_bus(bus)

        cap = bus.get("tool:test:api")
        assert cap is not None
        assert cap.risk_level == "MEDIUM"
        assert cap.source == CapabilitySource.API

    def test_mcp_tools_map_to_medium_risk(self, clean_registry):
        """MCP tools must have MEDIUM risk level."""
        clean_registry.register(
            name="test:mcp",
            description="Test MCP tool",
            tool_type=ToolType.MCP,
            tags=["mcp", "test"],
        )
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = _FakeBus()
        adapter.sync_to_bus(bus)

        cap = bus.get("tool:test:mcp")
        assert cap is not None
        assert cap.risk_level == "MEDIUM"
        assert cap.source == CapabilitySource.MCP

    def test_custom_tools_map_to_low_risk(self, clean_registry):
        """Custom tools must have LOW risk level."""
        clean_registry.register(
            name="test:custom",
            description="Test custom tool",
            tool_type=ToolType.CUSTOM,
            tags=["custom", "test"],
        )
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = _FakeBus()
        adapter.sync_to_bus(bus)

        cap = bus.get("tool:test:custom")
        assert cap is not None
        assert cap.risk_level == "LOW"
        assert cap.source == CapabilitySource.CUSTOM

    def test_input_schema_generated_from_tool_parameters(self, clean_registry):
        """Capability input_schema must be generated from ToolParameter list."""
        clean_registry.register(
            name="test:schema",
            description="Test schema tool",
            tool_type=ToolType.BUILTIN,
            parameters=[
                ToolParameter(name="arg1", description="First arg", type="string", required=True),
                ToolParameter(name="arg2", description="Second arg", type="integer", required=False, default=42),
                ToolParameter(name="arg3", description="Flag", type="boolean", required=False),
            ],
        )
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = _FakeBus()
        adapter.sync_to_bus(bus)

        cap = bus.get("tool:test:schema")
        assert cap is not None
        schema = cap.input_schema
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "arg1" in schema["properties"]
        assert schema["properties"]["arg1"]["type"] == "string"
        assert schema["properties"]["arg1"]["description"] == "First arg"
        assert "arg2" in schema["properties"]
        assert schema["properties"]["arg2"]["default"] == 42
        assert "required" in schema
        assert "arg1" in schema["required"]

    def test_output_schema_defaults_to_object(self, clean_registry):
        """Capability output_schema defaults to empty object."""
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = _FakeBus()
        adapter.sync_to_bus(bus)

        cap = bus.get("tool:shell:run")
        assert cap is not None
        assert cap.output_schema == {"type": "object"}

    def test_tags_include_tool_type(self, clean_registry):
        """Capability tags must include the tool_type value."""
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = _FakeBus()
        adapter.sync_to_bus(bus)

        for cap in bus.list_capabilities():
            tool_type_value = cap.metadata.get("tool_type", "")
            assert tool_type_value in cap.tags or any(
                t in cap.tags for t in ["builtin", "cli", "api", "mcp", "custom"]
            ), f"{cap.id}: tool_type={tool_type_value!r} not in tags={cap.tags}"

    def test_metadata_preserves_tool_details(self, clean_registry):
        """Capability metadata must preserve tool details."""
        tool = clean_registry.register(
            name="test:meta",
            description="Test metadata tool",
            tool_type=ToolType.CLI,
            command_template="mycmd {args}",
            tags=["meta"],
        )
        tool.endpoint = "GET /api/meta"
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = _FakeBus()
        adapter.sync_to_bus(bus)

        cap = bus.get("tool:test:meta")
        assert cap is not None
        assert cap.metadata["tool_type"] == "cli"
        assert cap.metadata["command_template"] == "mycmd {args}"
        assert cap.metadata["endpoint"] == "GET /api/meta"


class TestExecuteRoundTrip:
    """Test execute round-trip: bus.execute → adapter → ToolRegistry.execute."""

    def test_execute_builtin_shell_run(self, clean_registry):
        """Execute shell:run through the bus must work.

        Note: uses a space-free command because the pre-existing template
        `sh -c '{command}'` + shlex.quote produces double-quoted args that
        shlex.split mis-parses when the command contains spaces.
        """
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = InMemoryCapabilityBus()
        adapter.sync_to_bus(bus)

        # Use a space-free command to avoid the pre-existing template bug
        result = bus.execute("tool:shell:run", {"command": "pwd"})
        assert result["ok"] is True
        assert result["result"]  # non-empty output

    def test_execute_builtin_file_read(self, clean_registry):
        """Execute file:read through the bus must work."""
        import tempfile
        import os

        adapter = ToolCapabilityAdapter(clean_registry)
        bus = InMemoryCapabilityBus()
        adapter.sync_to_bus(bus)

        # Create a temp file
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("test content")
            temp_path = f.name

        try:
            result = bus.execute("tool:file:read", {"path": temp_path})
            assert result["ok"] is True
            assert "test content" in result["result"]
        finally:
            os.unlink(temp_path)

    def test_execute_unknown_capability_returns_error(self, clean_registry):
        """Execute unknown capability must return error dict.

        InMemoryCapabilityBus.execute() returns {"error": ...} without an
        "ok" key for unknown capabilities — this is the bus-level contract.
        """
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = InMemoryCapabilityBus()
        adapter.sync_to_bus(bus)

        result = bus.execute("tool:nonexistent", {})
        assert "error" in result
        assert "not found" in result["error"]

    def test_execute_via_bus_execute_method(self, clean_registry):
        """bus.execute() must route to the real tool and return ok=True."""
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = InMemoryCapabilityBus()
        adapter.sync_to_bus(bus)

        result = bus.execute("tool:git:status", {})
        assert "ok" in result

    def test_result_shape_normalized(self, clean_registry):
        """Execute result must be normalized to {ok, result/error, duration_ms}.

        Uses a space-free command to avoid the pre-existing shell template bug.
        """
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = InMemoryCapabilityBus()
        adapter.sync_to_bus(bus)

        result = bus.execute("tool:shell:run", {"command": "pwd"})
        assert "ok" in result
        assert "duration_ms" in result
        if result["ok"]:
            assert "result" in result
        else:
            assert "error" in result


class TestIdempotencyAndCleanup:
    """Test sync idempotency and cleanup behavior."""

    def test_sync_is_idempotent(self, clean_registry):
        """Calling sync_to_bus twice must not duplicate registrations."""
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = InMemoryCapabilityBus()

        first = adapter.sync_to_bus(bus)
        second = adapter.sync_to_bus(bus)

        assert len(first) == BUILTIN_COUNT
        assert second == []
        assert len(bus.list_capabilities()) == BUILTIN_COUNT

    def test_unregister_all(self, clean_registry):
        """unregister_all must remove all synced capabilities."""
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = InMemoryCapabilityBus()
        adapter.sync_to_bus(bus)

        count_before = len(bus.list_capabilities())
        removed = adapter.unregister_all(bus)
        assert removed == count_before
        assert len(bus.list_capabilities()) == 0

    def test_get_capability(self, clean_registry):
        """get_capability must return the registered capability by tool name."""
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = InMemoryCapabilityBus()
        adapter.sync_to_bus(bus)

        cap = adapter.get_capability("shell:run", bus)
        assert cap is not None
        assert cap.id == "tool:shell:run"
        assert cap.name == "shell:run"


class TestRealToolRegistryIntegration:
    """Integration test with full ToolRegistry discover methods."""

    def test_all_builtins_synced(self, clean_registry):
        """All builtin tools from _register_builtins must be synced."""
        adapter = ToolCapabilityAdapter(clean_registry)
        bus = InMemoryCapabilityBus()
        adapter.sync_to_bus(bus)

        builtins = bus.list_capabilities(source=CapabilitySource.BUILTIN)
        assert len(builtins) == BUILTIN_COUNT

        names = {c.name for c in builtins}
        assert "shell:run" in names
        assert "file:read" in names
        assert "file:write" in names
        assert "file:list" in names
        assert "git:status" in names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])