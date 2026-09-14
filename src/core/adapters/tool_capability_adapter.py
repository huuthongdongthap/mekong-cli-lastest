# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tool Capability Adapter — wraps ToolRegistry.list_tools() as Capability instances.

Provides the bridge between ToolRegistry and the CapabilityBus.
Each registered Tool becomes a Capability with:
  - id = "tool:<tool_name>" (e.g., "tool:shell:run", "tool:git:status")
  - source = CapabilitySource mapped from ToolType
  - risk_level from tool metadata or default LOW for builtins
  - input_schema generated from ToolParameter list
  - execute() delegates to ToolRegistry.execute()
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.core.capability import Capability, CapabilityBus, CapabilitySource
from src.core.tool_registry import Tool, ToolRegistry, ToolType

logger = logging.getLogger(__name__)


# Map ToolType to CapabilitySource
_TOOL_TYPE_TO_SOURCE = {
    ToolType.BUILTIN: CapabilitySource.BUILTIN,
    ToolType.CLI: CapabilitySource.CLI,
    ToolType.API: CapabilitySource.API,
    ToolType.MCP: CapabilitySource.MCP,
    ToolType.CUSTOM: CapabilitySource.CUSTOM,
}


# Default risk level by ToolType
_TOOL_TYPE_TO_RISK = {
    ToolType.BUILTIN: "LOW",
    ToolType.CLI: "LOW",
    ToolType.API: "MEDIUM",
    ToolType.MCP: "MEDIUM",
    ToolType.CUSTOM: "LOW",
}


class ToolCapabilityAdapter:
    """Adapter that wraps ToolRegistry tools as Capability instances.

    Usage:
        adapter = ToolCapabilityAdapter(tool_registry)
        adapter.sync_to_bus(bus)  # discover + register all tools as capabilities

        # Now available via CapabilityBus:
        caps = bus.list_capabilities(source=CapabilitySource.BUILTIN)
        result = bus.execute("tool:shell:run", {"command": "echo hi"})
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._tool_registry = tool_registry
        self._registered: set[str] = set()

    def sync_to_bus(self, bus: CapabilityBus) -> List[Capability]:
        """Discover all tools and register them as Capabilities on the bus.

        Returns list of Capability instances created.
        Idempotent: calling again skips already-registered tools.
        """
        tools = self._tool_registry.list_tools()
        capabilities: List[Capability] = []

        for tool in tools:
            if tool.name in self._registered:
                continue

            cap = self._tool_to_capability(tool)
            # Monkey-patch execute to delegate to tool_registry.
            # setattr (not direct assignment) so pyright does not flag
            # reassigning the dataclass method "execute".
            setattr(
                cap,
                "execute",
                lambda params, ctx=None, t=tool.name: self._execute_tool(t, params, ctx),
            )

            bus.register(cap)
            self._registered.add(tool.name)
            capabilities.append(cap)

        logger.info("ToolCapabilityAdapter: synced %d capabilities", len(capabilities))
        return capabilities

    def _tool_to_capability(self, tool: Tool) -> Capability:
        """Convert a Tool to a Capability."""
        source = _TOOL_TYPE_TO_SOURCE.get(tool.tool_type, CapabilitySource.CUSTOM)
        risk_level = _TOOL_TYPE_TO_RISK.get(tool.tool_type, "LOW")

        # Build JSON Schema from ToolParameter list
        input_schema = self._build_input_schema(tool.parameters)

        # Build output schema (empty for now, could be enhanced)
        output_schema = {"type": "object"}

        return Capability(
            id=f"tool:{tool.name}",
            name=tool.name,
            description=tool.description,
            input_schema=input_schema,
            output_schema=output_schema,
            risk_level=risk_level,
            source=source,
            cost=0.0,
            authorization=None,
            tags=list(tool.tags) + [tool.tool_type.value],
            metadata={
                "tool_type": tool.tool_type.value,
                "command_template": tool.command_template,
                "endpoint": tool.endpoint,
            },
        )

    def _build_input_schema(self, parameters: List[Any]) -> Dict[str, Any]:
        """Build JSON Schema from ToolParameter list."""
        schema: Dict[str, Any] = {"type": "object", "properties": {}}
        required: List[str] = []

        for param in parameters:
            # ToolParameter has: name, description, type, required, default
            prop: Dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.default is not None:
                prop["default"] = param.default
            schema["properties"][param.name] = prop
            if param.required:
                required.append(param.name)

        if required:
            schema["required"] = required

        return schema

    def _execute_tool(self, tool_name: str, params: Dict[str, Any], context: Dict[str, Any] | None) -> Dict[str, Any]:
        """Execute a tool via ToolRegistry and normalize result shape."""
        result = self._tool_registry.execute(tool_name, params)
        # ToolRegistry.execute returns {"success": bool, "output": str, "duration_ms": float}
        # Capability.execute expects Dict[str, Any] — normalize to include ok flag
        if result.get("success"):
            return {"ok": True, "result": result.get("output", ""), "duration_ms": result.get("duration_ms", 0)}
        else:
            return {"ok": False, "error": result.get("output", "Unknown error"), "duration_ms": result.get("duration_ms", 0)}

    def get_capability(self, tool_name: str, bus: CapabilityBus) -> Capability | None:
        """Get a single capability by tool name."""
        return bus.get(f"tool:{tool_name}")

    def unregister_all(self, bus: CapabilityBus) -> int:
        """Unregister all capabilities synced by this adapter. Returns count removed."""
        count = 0
        for tool_name in self._registered:
            if bus.unregister(f"tool:{tool_name}"):
                count += 1
        self._registered.clear()
        return count


__all__ = ["ToolCapabilityAdapter"]