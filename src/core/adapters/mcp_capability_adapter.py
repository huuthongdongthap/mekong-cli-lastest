# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""MCP Adapter — wraps MekongMcpServer tools as Capability instances.

Provides the bridge between MCP tools and the CapabilityBus.
Each MCP tool becomes a Capability with:
  - id = "mcp:<tool_name>" (tool_name is the public name the server exposes,
    e.g. "mcp:cc_tasks_list" — the ``cc_`` prefix is preserved in the id)
  - source = CapabilitySource.MCP
  - risk_level = MEDIUM (configurable)
  - execute() delegates to MekongMcpServer._handle_<base>() where ``base`` is
    the tool name with the ``cc_`` prefix stripped (handlers are registered
    without the prefix, e.g. ``cc_tasks_list`` -> ``_handle_tasks_list``).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from src.core.capability import Capability, CapabilityBus, CapabilitySource
from src.core.mcp_server import MekongMcpServer

logger = logging.getLogger(__name__)

# Prefix the MCP server prepends to every public tool name. Handlers on the
# server are registered WITHOUT this prefix, so it must be stripped when
# resolving ``_handle_*`` methods but kept in the capability id.
_TOOL_PREFIX = "cc_"


class MCPCapabilityAdapter:
    """Adapter that wraps MekongMcpServer tools as Capability instances.

    Usage:
        adapter = MCPCapabilityAdapter()
        adapter.sync_from_mcp()  # discover + register all MCP tools

        # Now available via CapabilityBus:
        caps = adapter.bus.list_capabilities(source=CapabilitySource.MCP)
        result = adapter.bus.execute("mcp:cc_tasks_list", {"status": "todo"})
    """

    def __init__(
        self,
        bus: CapabilityBus | None = None,
        mcp_server: Any | None = None,
    ) -> None:
        """Construct the adapter.

        ``mcp_server`` is optional: when supplied it is used verbatim (duck-
        typed — see ``_get_mcp_server``), so an EXTERNAL-shaped server that
        exposes ``create_app()`` + ``_tools`` can be synced without being a
        concrete ``MekongMcpServer``. When omitted the canonical
        ``MekongMcpServer`` is lazily constructed (fail-loud at import).
        """
        self._bus = bus
        self._mcp_server: Any = mcp_server
        self._registered: set[str] = set()

    @property
    def bus(self) -> CapabilityBus | None:
        return self._bus

    @bus.setter
    def bus(self, value: CapabilityBus | None) -> None:
        self._bus = value

    def _get_mcp_server(self) -> Any:
        """Lazily create the real MekongMcpServer instance.

        Return type is deliberately ``Any``: the adapter only relies on a
        structural protocol — ``create_app()`` populating ``_tools`` (list of
        dicts with a ``name`` key) plus ``_handle_<base>`` methods. Any object
        satisfying that shape (the canonical ``MekongMcpServer`` or an
        external-shaped server) is interchangeable here. The class itself is
        imported at module load time so a missing or renamed server class
        fails loudly at import rather than being swallowed into a silent
        zero-tool sync. Construction itself never returns None.
        """
        if self._mcp_server is not None:
            return self._mcp_server
        self._mcp_server = MekongMcpServer()
        return self._mcp_server

    def _get_tool_names(self) -> list[str]:
        """Get list of registered MCP tool names.

        Calls create_app() so the server populates its ``_tools`` list. If the
        MCP SDK is not installed create_app() raises RuntimeError; that is a
        legitimate degraded environment, so we surface an empty tool list here
        (the import-level failure is already loud at module load).
        """
        server = self._get_mcp_server()
        try:
            server.create_app()
            return [t.get("name", "") for t in getattr(server, "_tools", []) if t.get("name")]
        except Exception as exc:
            logger.warning("MCPCapabilityAdapter: cannot list tools (%s)", exc)
            return []

    @staticmethod
    def _handler_base(tool_name: str) -> str:
        """Strip the ``cc_`` prefix to get the handler method base name."""
        if tool_name.startswith(_TOOL_PREFIX):
            return tool_name[len(_TOOL_PREFIX):]
        return tool_name

    def _build_handler(self, tool_name: str):
        """Build an execute handler for a given MCP tool name.

        Maps tool_name -> MekongMcpServer._handle_<base>() where ``base`` is
        the tool name with the ``cc_`` prefix stripped. Falls back to a generic
        handler if the specific method is not found.
        """
        server = self._get_mcp_server()
        base = self._handler_base(tool_name)
        handler_name = f"_handle_{base}"
        handler = getattr(server, handler_name, None)
        if handler is None:
            # Fallback: no matching handler on the server for this tool.
            return lambda params, ctx=None: {
                "error": f"No handler for MCP tool '{tool_name}'",
                "available": self._get_tool_names(),
            }

        def _exec(params: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
            try:
                result = handler(**params)
                return {"ok": True, "result": result, "tool": tool_name}
            except TypeError:
                # If handler expects positional args, try positional
                return {"error": f"Parameter mismatch for {tool_name}"}
            except Exception as exc:
                logger.error("MCP tool %s error: %s", tool_name, exc)
                return {"ok": False, "error": str(exc), "tool": tool_name}

        return _exec

    def sync_from_mcp(self) -> list[Capability]:
        """Discover all MCP tools and register them as Capabilities.

        Returns list of Capability instances created.
        Requires bus to be set before calling.
        """
        if self._bus is None:
            raise RuntimeError("CapabilityBus not set on MCPCapabilityAdapter")

        tool_names = self._get_tool_names()
        capabilities: list[Capability] = []

        for tool_name in tool_names:
            if tool_name in self._registered:
                continue

            server = self._get_mcp_server()
            tool_meta = {}
            if hasattr(server, "_tools"):
                for t in server._tools:
                    if t.get("name") == tool_name:
                        tool_meta = t
                        break

            base = self._handler_base(tool_name)
            cap = Capability(
                id=f"mcp:{tool_name}",
                name=tool_meta.get("name", tool_name),
                description=tool_meta.get("description", f"MCP tool: {tool_name}"),
                input_schema={},
                risk_level="MEDIUM",
                source=CapabilitySource.MCP,
                cost=0.0,
                tags=["mcp"],
                metadata={"handler": f"_handle_{base}"},
            )
            # Monkey-patch execute to call real handler.
            # setattr (not direct assignment) so pyright does not flag
            # reassigning the dataclass method "execute".
            setattr(cap, "execute", self._build_handler(tool_name))

            self._bus.register(cap)
            self._registered.add(tool_name)
            capabilities.append(cap)

        logger.info("MCPCapabilityAdapter: synced %d capabilities", len(capabilities))
        return capabilities

    def get_capability(self, tool_name: str) -> Capability | None:
        """Get a single MCP capability by tool name."""
        if self._bus is None:
            return None
        return self._bus.get(f"mcp:{tool_name}")


__all__ = ["MCPCapabilityAdapter"]
