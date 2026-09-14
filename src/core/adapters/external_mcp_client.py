# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""External MCP client adapter — consume tools from third-party MCP servers.

Wraps the official ``mcp`` SDK client (``mcp.client.stdio`` /
``mcp.client.streamable_http`` + ``ClientSession``) behind a small, fail-loud
interface so the rest of Mekong never imports the SDK directly.

Two transports are supported:

* **stdio** — spawn a local subprocess (e.g. ``npx -y @modelcontextprotocol/server-filesystem``).
* **http** — connect to a remote Streamable-HTTP endpoint (e.g. a hosted MCP gateway).

Usage::

    client = ExternalMcpClient.stdio(
        command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    )
    tools = client.list_tools()          # [{name, description, inputSchema}, ...]
    result = client.call_tool("read_file", {"path": "/tmp/x.txt"})
    client.close()

The ``mcp`` SDK is fully async. This adapter bridges it into synchronous CLI
code via ``anyio.start_blocking_portal()``: a worker thread runs the anyio
event loop while the caller thread blocks on ``portal.call(...)``. No token
juggling, no manual loop management — the portal owns the loop for the
client's lifetime.

Architecture: this adapter is the **consumer** side of the MCP protocol.
``src/core/mcp_server.py`` is the **producer** side (Mekong exposes its own
tools). Together they close architecture gap #5 — MCP client-side consumption
of external servers.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import anyio

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StdioConfig:
    """Configuration for a stdio-transport MCP server."""

    command: str
    args: List[str] = field(default_factory=list)
    env: Optional[Dict[str, str]] = None
    cwd: Optional[str] = None
    timeout: float = 30.0


@dataclass(frozen=True)
class HttpConfig:
    """Configuration for a Streamable-HTTP MCP server."""

    url: str
    headers: Optional[Dict[str, str]] = None
    timeout: float = 30.0
    sse_read_timeout: float = 60.0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ExternalMcpError(RuntimeError):
    """Base error for external MCP client failures."""


class ExternalMcpTimeout(ExternalMcpError):
    """Server did not respond within the configured timeout."""


class ExternalMcpTransportError(ExternalMcpError):
    """Transport-level failure (subprocess crash, HTTP error, etc.)."""


# ---------------------------------------------------------------------------
# Lazy SDK imports
# ---------------------------------------------------------------------------


def _load_stdio():
    """Load stdio transport + ClientSession; raise a loud error if missing."""
    try:
        from mcp.client.stdio import stdio_client, StdioServerParameters  # type: ignore[import-untyped]
        from mcp import ClientSession  # type: ignore[import-untyped]

        return stdio_client, StdioServerParameters, ClientSession
    except ImportError as exc:
        raise ExternalMcpError(
            "mcp SDK is required for stdio transport. "
            "Install it: pip install mcp"
        ) from exc


def _load_http():
    """Load Streamable-HTTP transport + ClientSession; raise if missing."""
    try:
        from mcp.client.streamable_http import streamablehttp_client  # type: ignore[import-untyped]
        from mcp import ClientSession  # type: ignore[import-untyped]

        return streamablehttp_client, ClientSession
    except ImportError as exc:
        raise ExternalMcpError(
            "mcp SDK is required for http transport. "
            "Install it: pip install mcp"
        ) from exc


# ---------------------------------------------------------------------------
# Synchronous facade
# ---------------------------------------------------------------------------


class ExternalMcpClient:
    """Synchronous facade over the async ``mcp`` SDK client.

    Construct via the ``stdio()`` / ``http()`` factory methods. The underlying
    connection is established lazily on first use and reused for the lifetime
    of the instance. Call ``close()`` when done (or use the synchronous
    context manager protocol).
    """

    def __init__(self) -> None:
        self._transport_cm: Any = None
        self._session_cm: Any = None
        self._session: Any = None
        self._exit_stack: Optional[Any] = None
        self._portal_cm: Optional[Any] = None
        self._portal: Optional[Any] = None
        self._closed: bool = False
        # Session lifecycle lives in ONE background task. See
        # ``_session_loop`` — this is the only way to keep the MCP SDK's
        # ``BaseSession.__aenter__`` / ``__aexit__`` (which each create and
        # cancel an anyio task group) inside the same task where they were
        # entered. Splitting enter/exit across ``portal.call`` invocations
        # strands cancel scopes in the wrong task and raises
        # "Attempted to exit a cancel scope that isn't the current task's".
        self._close_event: Optional[Any] = None
        self._loop_future: Optional[Any] = None

    # -- factories ---------------------------------------------------------

    @classmethod
    def stdio(
        cls,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: float = 30.0,
    ) -> "ExternalMcpClient":
        """Build a stdio-transport client.

        Mirrors the ``npx ...`` invocation pattern used by Claude Desktop /
        Cursor / VS Code MCP configs.
        """
        client = cls()
        client._config = StdioConfig(
            command=command,
            args=args or [],
            env=env,
            cwd=cwd,
            timeout=timeout,
        )
        client._transport = "stdio"
        return client

    @classmethod
    def http(
        cls,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
        sse_read_timeout: float = 60.0,
    ) -> "ExternalMcpClient":
        """Build a Streamable-HTTP-transport client."""
        client = cls()
        client._config = HttpConfig(
            url=url,
            headers=headers,
            timeout=timeout,
            sse_read_timeout=sse_read_timeout,
        )
        client._transport = "http"
        return client

    # -- connection lifecycle ----------------------------------------------

    def _ensure_connected(self) -> None:
        """Lazily establish the underlying session."""
        if self._session is not None:
            return
        if self._closed:
            raise ExternalMcpError("client is closed")

        # Probe the SDK import BEFORE starting the portal. If the SDK is
        # absent, ``_load_*`` raises ``ExternalMcpError`` ("mcp SDK is
        # required...") directly — we want that loud, specific error to
        # propagate unchanged, not be swallowed by the transport's broad
        # ``except`` and re-wrapped as ``ExternalMcpTransportError``.
        if self._transport == "stdio":
            _load_stdio()
        else:
            _load_http()

        # Start a blocking portal so sync code can drive the async SDK.
        # ``start_blocking_portal`` lives on ``anyio.from_thread`` (not on the
        # top-level ``anyio`` namespace), so we import it explicitly.
        from anyio.from_thread import start_blocking_portal

        self._portal_cm = start_blocking_portal()
        self._portal = self._portal_cm.__enter__()

        if self._transport == "stdio":
            self._connect_stdio()
        else:
            self._connect_http()

    def _connect_stdio(self) -> None:
        """Spawn the stdio session lifecycle in one long-lived background task.

        The MCP SDK's ``BaseSession.__aenter__`` creates an anyio task group
        and ``__aexit__`` cancels and exits it — both MUST run in the same
        task. ``portal.call`` runs each invocation in a fresh task, so we
        cannot enter on one ``call`` and exit on another. Instead we use
        ``start_task_soon`` to run a coroutine that owns the whole
        enter → serve → exit span, gated by an anyio ``Event``:

        * enter the transport + session, publish the session via a future,
          then wait on ``_close_event``;
        * when ``close()`` fires the event, exit the contexts in this same
          task.

        Short RPCs (``list_tools`` / ``call_tool``) still go through
        ``portal.call`` — they don't enter/exit context managers, so they're
        safe as separate tasks.
        """
        stdio_client, StdioServerParameters, ClientSession = _load_stdio()
        config: StdioConfig = self._config  # type: ignore[assignment]

        params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env or {**os.environ},
            cwd=config.cwd,
        )

        self._close_event = anyio.Event()
        session_future: "Future[Any]" = Future()

        async def _session_loop() -> None:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    if not session_future.done():
                        session_future.set_result(session)
                    await self._close_event.wait()

        try:
            self._loop_future = self._portal.start_task_soon(_session_loop)  # type: ignore[union-attr]
            self._session = session_future.result()
        except Exception as exc:
            # Tear down the background task so close() is idempotent.
            self._signal_close()
            if self._loop_future is not None:
                try:
                    self._loop_future.result()
                except Exception:
                    logger.debug("session loop cleanup failed", exc_info=True)
            raise ExternalMcpTransportError(
                f"failed to connect to stdio MCP server {config.command!r}: {exc}"
            ) from exc

    def _connect_http(self) -> None:
        """Spawn the HTTP session lifecycle in one long-lived background task.

        See ``_connect_stdio`` for the single-task rationale.
        """
        streamablehttp_client, ClientSession = _load_http()
        config: HttpConfig = self._config  # type: ignore[assignment]

        self._close_event = anyio.Event()
        session_future: "Future[Any]" = Future()

        async def _session_loop() -> None:
            async with streamablehttp_client(
                url=config.url,
                headers=config.headers,
                timeout=config.timeout,
                sse_read_timeout=config.sse_read_timeout,
            ) as (read, write, _get_session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    if not session_future.done():
                        session_future.set_result(session)
                    await self._close_event.wait()

        try:
            self._loop_future = self._portal.start_task_soon(_session_loop)  # type: ignore[union-attr]
            self._session = session_future.result()
        except Exception as exc:
            self._signal_close()
            if self._loop_future is not None:
                try:
                    self._loop_future.result()
                except Exception:
                    logger.debug("session loop cleanup failed", exc_info=True)
            raise ExternalMcpTransportError(
                f"failed to connect to HTTP MCP server {config.url!r}: {exc}"
            ) from exc

    def _signal_close(self) -> None:
        """Fire the close event so the session loop can exit its contexts."""
        if self._close_event is not None:
            try:
                self._portal.call(self._close_event.set)  # type: ignore[union-attr]
            except Exception:
                logger.debug("close event set failed", exc_info=True)

    # -- public API --------------------------------------------------------

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return the server's advertised toolset.

        Each tool dict carries ``name``, ``description``, and ``inputSchema``
        (JSON Schema). Mirrors the shape the MCP SDK returns from
        ``session.list_tools()``.
        """
        self._ensure_connected()
        assert self._session is not None

        try:
            tool_result = self._portal.call(self._session.list_tools)  # type: ignore[union-attr]
        except Exception as exc:
            raise ExternalMcpError(f"list_tools failed: {exc}") from exc

        tools: List[Dict[str, Any]] = []
        for t in getattr(tool_result, "tools", []):
            tools.append(
                {
                    "name": t.name,
                    "description": getattr(t, "description", "") or "",
                    "inputSchema": getattr(t, "inputSchema", {}) or {},
                }
            )
        return tools

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Call a tool by name and return a normalized result dict.

        The returned dict mirrors the SDK ``CallToolResult`` shape:
        ``{"content": [...], "is_error": bool, "text": "..."}``.
        """
        self._ensure_connected()
        assert self._session is not None

        try:
            result = self._portal.call(  # type: ignore[union-attr]
                self._session.call_tool, name, arguments or {}
            )
        except Exception as exc:
            raise ExternalMcpError(f"call_tool({name!r}) failed: {exc}") from exc

        content_parts: List[str] = []
        for part in getattr(result, "content", []):
            # TextContent carries a ``text`` attribute; fall back to str().
            text = getattr(part, "text", None)
            if text is not None:
                content_parts.append(text)
            else:
                content_parts.append(str(part))

        return {
            "content": content_parts,
            "is_error": bool(getattr(result, "isError", False) or getattr(result, "is_error", False)),
            "text": "\n".join(content_parts),
        }

    def close(self) -> None:
        """Close the underlying session, transport, and portal.

        Idempotent: calling on an already-closed client is a no-op.
        """
        if self._closed:
            return
        # Signal the session loop to exit its context managers, then wait for
        # it to finish. Both halves run in the SAME task (see
        # ``_connect_stdio``), so the MCP SDK's task-group enter/exit stays
        # nested correctly.
        self._signal_close()
        if self._loop_future is not None:
            try:
                self._loop_future.result()
            except Exception:
                logger.debug("session loop shutdown failed", exc_info=True)
        self._loop_future = None
        self._close_event = None
        self._session = None
        self._session_cm = None
        self._transport_cm = None
        self._exit_stack = None
        if self._portal_cm is not None:
            try:
                self._portal_cm.__exit__(None, None, None)
            except Exception:
                logger.debug("portal cleanup failed", exc_info=True)
        self._portal_cm = None
        self._portal = None
        self._closed = True

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> "ExternalMcpClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        transport = getattr(self, "_transport", "?")
        return f"<ExternalMcpClient transport={transport} closed={self._closed}>"


# ---------------------------------------------------------------------------
# Convenience: parse a Claude-Desktop-style MCP config entry
# ---------------------------------------------------------------------------


def from_config(config: Dict[str, Any]) -> ExternalMcpClient:
    """Build an ``ExternalMcpClient`` from a JSON config dict.

    Accepts the Claude Desktop / Cursor / VS Code shape::

        {"command": "npx", "args": ["-y", "server-filesystem", "/tmp"]}
        {"url": "https://host/mcp", "headers": {"Authorization": "Bearer ..."}}}

    Raises ``ExternalMcpError`` when neither ``command`` nor ``url`` is present.
    """
    if "command" in config:
        return ExternalMcpClient.stdio(
            command=config["command"],
            args=config.get("args"),
            env=config.get("env"),
            cwd=config.get("cwd"),
            timeout=float(config.get("timeout", 30.0)),
        )
    if "url" in config:
        return ExternalMcpClient.http(
            url=config["url"],
            headers=config.get("headers"),
            timeout=float(config.get("timeout", 30.0)),
            sse_read_timeout=float(config.get("sse_read_timeout", 60.0)),
        )
    raise ExternalMcpError(
        "MCP config must contain either 'command' (stdio) or 'url' (http); "
        f"got keys: {sorted(config)}"
    )


def parse_mcp_servers(config: Dict[str, Any]) -> Dict[str, ExternalMcpClient]:
    """Parse the ``mcpServers`` block from a Claude-Desktop-style config.

    Returns a mapping of server name → connected-capable client. Each client
    is NOT yet connected — connection is lazy on first use.
    """
    servers = config.get("mcpServers") or config.get("servers") or {}
    result: Dict[str, ExternalMcpClient] = {}
    for name, spec in servers.items():
        if not isinstance(spec, dict):
            continue
        try:
            result[name] = from_config(spec)
        except ExternalMcpError as exc:
            logger.warning("skipping MCP server %r: %s", name, exc)
    return result
