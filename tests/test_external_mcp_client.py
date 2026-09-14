# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for the external MCP client adapter.

Covers (without requiring a live MCP server):
- Factory methods (stdio / http) build correctly
- ``from_config`` / ``parse_mcp_servers`` parse Claude-Desktop-style configs
- Error handling for malformed configs
- SDK-absent path raises a loud error
- ``list_tools`` / ``call_tool`` normalize SDK shapes
- ``close()`` is idempotent and safe after partial-connection failures

The live-server tests at the bottom require the ``mcp`` SDK AND a working
``npx``. They are guarded by ``_has_npx()`` and skipped automatically when
the environment cannot run them — they never fail the suite on a machine
without npx.
"""

from __future__ import annotations

import shutil
import sys
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest

from src.core.adapters.external_mcp_client import (
    ExternalMcpClient,
    ExternalMcpError,
    HttpConfig,
    StdioConfig,
    from_config,
    parse_mcp_servers,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _text_content(text: str) -> Any:
    """Build a mock MCP TextContent-like object."""
    part = MagicMock()
    part.text = text
    return part


def _call_tool_result(
    texts: List[str], is_error: bool = False
) -> Any:
    """Build a mock CallToolResult-like object."""
    result = MagicMock()
    result.content = [_text_content(t) for t in texts]
    result.isError = is_error
    result.is_error = is_error
    return result


def _list_tools_result(names: List[str]) -> Any:
    """Build a mock ListToolsResult-like object."""
    tools: List[Any] = []
    for name in names:
        t = MagicMock()
        t.name = name
        t.description = f"Description for {name}"
        t.inputSchema = {"type": "object", "properties": {}}
        tools.append(t)
    result = MagicMock()
    result.tools = tools
    return result


# ---------------------------------------------------------------------------
# Factory + config parsing
# ---------------------------------------------------------------------------


class TestFactories:
    """stdio / http factory methods build correctly."""

    def test_stdio_factory(self) -> None:
        client = ExternalMcpClient.stdio(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        )
        assert client._transport == "stdio"  # type: ignore[attr-defined]
        config = client._config  # type: ignore[attr-defined]
        assert isinstance(config, StdioConfig)
        assert config.command == "npx"
        assert config.args == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

    def test_http_factory(self) -> None:
        client = ExternalMcpClient.http(
            url="https://mcp.example.com/sse",
            headers={"Authorization": "Bearer xyz"},
        )
        assert client._transport == "http"  # type: ignore[attr-defined]
        config = client._config  # type: ignore[attr-defined]
        assert isinstance(config, HttpConfig)
        assert config.url == "https://mcp.example.com/sse"
        assert config.headers == {"Authorization": "Bearer xyz"}

    def test_stdio_default_args(self) -> None:
        client = ExternalMcpClient.stdio(command="python")
        config = client._config  # type: ignore[attr-defined]
        assert config.args == []


class TestFromConfig:
    """``from_config`` parses Claude-Desktop-style config dicts."""

    def test_stdio_config(self) -> None:
        client = from_config(
            {"command": "npx", "args": ["-y", "server-filesystem", "/tmp"]}
        )
        assert client._transport == "stdio"  # type: ignore[attr-defined]

    def test_http_config(self) -> None:
        client = from_config({"url": "https://host/mcp"})
        assert client._transport == "http"  # type: ignore[attr-defined]

    def test_http_config_with_headers(self) -> None:
        client = from_config(
            {"url": "https://host/mcp", "headers": {"X-Token": "abc"}}
        )
        config = client._config  # type: ignore[attr-defined]
        assert config.headers == {"X-Token": "abc"}

    def test_missing_keys_raises(self) -> None:
        with pytest.raises(ExternalMcpError, match="command.*url"):
            from_config({"bad": "config"})

    def test_empty_config_raises(self) -> None:
        with pytest.raises(ExternalMcpError):
            from_config({})


class TestParseMcpServers:
    """``parse_mcp_servers`` parses the ``mcpServers`` block."""

    def test_parse_both_transports(self) -> None:
        config = {
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "server-filesystem"],
                },
                "remote": {"url": "https://host/mcp"},
            }
        }
        clients = parse_mcp_servers(config)
        assert set(clients.keys()) == {"filesystem", "remote"}
        assert clients["filesystem"]._transport == "stdio"  # type: ignore[attr-defined]
        assert clients["remote"]._transport == "http"  # type: ignore[attr-defined]

    def test_alternate_servers_key(self) -> None:
        clients = parse_mcp_servers({"servers": {"a": {"command": "echo"}}})
        assert "a" in clients

    def test_empty_config(self) -> None:
        assert parse_mcp_servers({}) == {}

    def test_skips_non_dict_spec(self, caplog: pytest.LogCaptureFixture) -> None:
        clients = parse_mcp_servers({"mcpServers": {"bad": "not-a-dict"}})
        assert clients == {}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Error paths are loud and specific."""

    def test_closed_client_raises(self) -> None:
        client = ExternalMcpClient.stdio(command="npx")
        client.close()
        with pytest.raises(ExternalMcpError, match="closed"):
            client.list_tools()

    def test_sdk_absent_raises_loud(self) -> None:
        """When the mcp SDK is not installed, connection fails loudly."""
        with patch.dict(sys.modules, {"mcp": None, "mcp.client": None}):
            client = ExternalMcpClient.stdio(command="npx")
            with pytest.raises(ExternalMcpError, match="mcp SDK is required"):
                client.list_tools()

    def test_close_idempotent(self) -> None:
        client = ExternalMcpClient.stdio(command="npx")
        client.close()
        client.close()  # must not raise

    def test_repr(self) -> None:
        client = ExternalMcpClient.stdio(command="npx")
        assert "stdio" in repr(client)
        assert "closed=False" in repr(client)


# ---------------------------------------------------------------------------
# list_tools / call_tool normalization (mocked session)
# ---------------------------------------------------------------------------


def _connected_client(session: Any) -> ExternalMcpClient:
    """Attach a pre-built mock session to a client, bypassing connection.

    Also starts a real blocking portal so ``portal.call(...)`` works — the
    client drives the async SDK through the portal, not through a bare
    ``anyio.from_thread.run`` call.
    """
    from anyio.from_thread import start_blocking_portal

    client = ExternalMcpClient.stdio(command="npx")
    client._portal_cm = start_blocking_portal()
    client._portal = client._portal_cm.__enter__()
    client._session = session
    return client


class TestListTools:
    """``list_tools`` normalizes the SDK shape."""

    def test_empty_toolset(self) -> None:
        session = MagicMock()
        session.list_tools = _coro_fn(lambda: _list_tools_result([]))
        client = _connected_client(session)
        assert client.list_tools() == []

    def test_multiple_tools(self) -> None:
        session = MagicMock()
        session.list_tools = _coro_fn(
            lambda: _list_tools_result(["read_file", "write_file"])
        )
        client = _connected_client(session)
        tools = client.list_tools()
        assert len(tools) == 2
        assert tools[0]["name"] == "read_file"
        assert tools[0]["description"] == "Description for read_file"
        assert "inputSchema" in tools[0]

    def test_tool_without_description(self) -> None:
        """Tool with None description → empty string."""
        t = MagicMock()
        t.name = "bare"
        t.description = None
        t.inputSchema = {}
        result = MagicMock()
        result.tools = [t]
        session = MagicMock()
        session.list_tools = _coro_fn(lambda: result)
        client = _connected_client(session)
        tools = client.list_tools()
        assert tools[0]["description"] == ""


class TestCallTool:
    """``call_tool`` normalizes the SDK shape."""

    def test_success(self) -> None:
        session = MagicMock()
        session.call_tool = _coro_fn(
            lambda n, a: _call_tool_result(["hello world"])
        )
        client = _connected_client(session)
        result = client.call_tool("echo", {"text": "hi"})
        assert result["is_error"] is False
        assert result["text"] == "hello world"
        assert result["content"] == ["hello world"]

    def test_error_result(self) -> None:
        session = MagicMock()
        session.call_tool = _coro_fn(
            lambda n, a: _call_tool_result(["boom"], is_error=True)
        )
        client = _connected_client(session)
        result = client.call_tool("bad", {})
        assert result["is_error"] is True

    def test_multiple_content_parts(self) -> None:
        session = MagicMock()
        session.call_tool = _coro_fn(
            lambda n, a: _call_tool_result(["line1", "line2"])
        )
        client = _connected_client(session)
        result = client.call_tool("multi", {})
        assert result["content"] == ["line1", "line2"]
        assert result["text"] == "line1\nline2"

    def test_call_failure_raises(self) -> None:
        session = MagicMock()

        async def _boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("server crashed")

        session.call_tool = _boom
        client = _connected_client(session)
        with pytest.raises(ExternalMcpError, match="call_tool\\('x'\\) failed"):
            client.call_tool("x", {})


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    """Synchronous context manager protocol."""

    def test_enter_exit(self) -> None:
        client = ExternalMcpClient.stdio(command="npx")
        with client as c:
            assert c is client
            assert not client._closed  # type: ignore[attr-defined]
        assert client._closed  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Live-server tests (guarded — skipped when npx is unavailable)
# ---------------------------------------------------------------------------


def _has_npx() -> bool:
    return shutil.which("npx") is not None


@pytest.mark.skipif(not _has_npx(), reason="npx not available")
class TestLiveFilesystemServer:
    """Live integration against the official filesystem MCP server.

    These tests are skipped automatically on machines without ``npx``. They
    prove the adapter drives a real handshake + tool list + tool call.
    """

    def test_connect_and_list_tools(self) -> None:
        """Real stdio server exposes tools."""
        client = ExternalMcpClient.stdio(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            timeout=60.0,
        )
        with client:
            tools = client.list_tools()
            assert len(tools) > 0
            names = {t["name"] for t in tools}
            # The filesystem server always exposes these.
            assert "read_file" in names or "list_directory" in names

    def test_call_tool_live(self) -> None:
        """Real stdio server responds to a tool call."""
        import tempfile
        import os

        # Create a temp file the server can read.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, dir="/tmp"
        ) as f:
            f.write("hello from mekong")
            tmp_path = f.name

        try:
            client = ExternalMcpClient.stdio(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                timeout=60.0,
            )
            with client:
                result = client.call_tool("read_file", {"path": tmp_path})
                assert result["is_error"] is False
                assert "hello from mekong" in result["text"]
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Helpers to make MagicMock work with anyio.from_thread.run
# ---------------------------------------------------------------------------


def _coro_fn(fn: Any) -> Any:
    """Wrap a plain callable into a coroutine function for ``portal.call``.

    ``anyio.start_blocking_portal().call(cb, *args)`` awaits ``cb(*args)``,
    so ``cb`` must be a coroutine function. This wraps a sync lambda that
    returns a value into the shape the portal expects.
    """

    async def _coro(*args: Any, **kwargs: Any) -> Any:
        return fn(*args, **kwargs)

    return _coro
