# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Integration test — MCP adapter <-> capability bus round-trip.

Proves the full path: capability request -> MCPCapabilityAdapter ->
MekongMcpServer handler -> response -> InMemoryCapabilityBus.

Architecture under test:
  1. A REAL MCP server runs as a subprocess speaking JSON-RPC over stdio
     (same ``mcp_proc`` fixture pattern as test_mcp_server_integration.py).
     The subprocess proves the server is genuine: real handshake, real
     tools/list, real tools/call.
  2. MCPCapabilityAdapter.sync_from_mcp() discovers the server's toolset and
     registers every tool as a Capability on a REAL InMemoryCapabilityBus
     (no _FakeBus — the production bus implementation).
  3. bus.execute() round-trips through the adapter into the server's
     handlers and returns real results.
  4. Cross-check: the toolset advertised by the subprocess server over
     JSON-RPC MUST equal the capability set the adapter registered on the
     bus — proving the adapter<->bus path covers the real server exactly.

The adapter invokes handlers in-process (its documented contract); the
subprocess independently proves the server speaks the real MCP protocol and
exposes the same toolset the adapter registers.
"""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
from pathlib import Path

import pytest

from src.core.adapters.mcp_capability_adapter import MCPCapabilityAdapter
from src.core.capability import CapabilitySource, InMemoryCapabilityBus

MODULE = "src.core.mcp_server"
PROTOCOL_VERSION = "2024-11-05"
SERVER_TIMEOUT = 15.0


@pytest.fixture(scope="module")
def mcp_proc():
    """Spawn real MCP server subprocess with stdio transport.

    Yields (write, read, proc) helpers.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", MODULE],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(Path.cwd())},
        cwd=Path.cwd(),
        text=True,
    )

    sel = selectors.DefaultSelector()
    assert proc.stdout is not None
    sel.register(proc.stdout, selectors.EVENT_READ)

    def write(msg: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(msg, separators=(",", ":")) + "\n")
        proc.stdin.flush()

    def read(timeout: float = SERVER_TIMEOUT) -> dict | None:
        if sel.select(timeout=timeout):
            line = proc.stdout.readline()
            if not line:
                return None
            return json.loads(line.strip())
        return None

    yield write, read, proc

    sel.close()
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def adapter_bus():
    """Real MCPCapabilityAdapter wired to a real InMemoryCapabilityBus.

    sync_from_mcp() discovers and registers the server's full toolset.
    """
    bus = InMemoryCapabilityBus()
    adapter = MCPCapabilityAdapter(bus=bus)
    caps = adapter.sync_from_mcp()
    assert len(caps) >= 20, f"Expected >=20 MCP capabilities, got {len(caps)}"
    return adapter, bus


def _subprocess_tool_names(write, read_) -> set[str]:
    """Handshake + tools/list against the real subprocess server."""
    write({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "adapter-bus-test", "version": "1.0.0"},
        },
    })
    resp = read_()
    assert resp is not None, "No initialize response from real MCP server"
    assert resp.get("result", {}).get("protocolVersion") == PROTOCOL_VERSION
    write({"jsonrpc": "2.0", "method": "notifications/initialized"})

    write({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    resp = read_()
    assert resp is not None, "No tools/list response from real MCP server"
    tools = resp.get("result", {}).get("tools", [])
    return {t["name"] for t in tools}


# ═══════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.integration
def test_real_subprocess_server_speaks_mcp_protocol(mcp_proc):
    """The subprocess server must complete a real JSON-RPC MCP handshake."""
    write, read_, proc = mcp_proc
    names = _subprocess_tool_names(write, read_)
    assert proc.poll() is None, "MCP server subprocess died during handshake"
    assert len(names) >= 20, f"Real server exposed only {len(names)} tools"


@pytest.mark.integration
def test_adapter_registers_full_toolset_on_real_bus(adapter_bus):
    """sync_from_mcp must register every tool on the real InMemoryCapabilityBus."""
    _, bus = adapter_bus
    caps = bus.list_capabilities(source=CapabilitySource.MCP)
    assert len(caps) >= 20
    assert all(c.source == CapabilitySource.MCP for c in caps)
    assert all(c.id.startswith("mcp:cc_") for c in caps)


@pytest.mark.integration
def test_subprocess_toolset_matches_bus_capabilities(mcp_proc, adapter_bus):
    """Tools advertised by the real subprocess server over JSON-RPC must
    exactly equal the capabilities the adapter registered on the bus."""
    write, read_, _ = mcp_proc
    _, bus = adapter_bus

    subprocess_names = _subprocess_tool_names(write, read_)
    bus_names = {
        c.id.removeprefix("mcp:")
        for c in bus.list_capabilities(source=CapabilitySource.MCP)
    }
    assert bus_names == subprocess_names, (
        f"Adapter/bus toolset diverges from real server: "
        f"missing={subprocess_names - bus_names} extra={bus_names - subprocess_names}"
    )


@pytest.mark.integration
def test_bus_execute_round_trip_read_only_tool(adapter_bus):
    """bus.execute must round-trip through the adapter to a real handler."""
    _, bus = adapter_bus
    result = bus.execute("mcp:cc_skills_list", {})
    assert result.get("ok") is True, f"Round-trip failed: {result}"
    assert result.get("tool") == "cc_skills_list"
    payload = result.get("result")
    assert isinstance(payload, str)
    assert '"ok": true' in payload


@pytest.mark.integration
def test_bus_execute_round_trip_task_lifecycle(adapter_bus):
    """Full create/list/done/delete lifecycle through bus.execute."""
    _, bus = adapter_bus

    def call(tool: str, params: dict) -> dict:
        r = bus.execute(f"mcp:{tool}", params)
        assert r.get("ok") is True, f"{tool} failed: {r}"
        return json.loads(r["result"])

    created = call("cc_tasks_create", {"subject": "adapter-bus integration task"})
    task_id = created.get("data", {}).get("task", {}).get("task_id", "")
    assert task_id, f"No task_id in create response: {created}"

    listed = call("cc_tasks_list", {"status": ""})
    ids = [t.get("task_id") for t in listed.get("data", {}).get("tasks", [])]
    assert task_id in ids

    done = call("cc_tasks_done", {"task_id": task_id})
    assert done.get("ok") is True

    deleted = call("cc_tasks_delete", {"task_id": task_id})
    assert deleted.get("ok") is True


@pytest.mark.integration
def test_bus_execute_unknown_capability_returns_error(adapter_bus):
    """Executing an unregistered capability must return an error, not raise."""
    _, bus = adapter_bus
    result = bus.execute("mcp:cc_does_not_exist", {})
    assert "error" in result
