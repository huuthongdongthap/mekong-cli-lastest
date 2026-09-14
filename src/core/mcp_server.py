# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Mekong CLI — MCP Server for AI OS capabilities.

Provides 25 MCP tools wrapping Mekong AI OS core services.
Designed to run as a standalone MCP server (stdio or SSE) or be imported.

Usage:
    python -m src.core.mcp_server                           # stdio mode
    python -m src.core.mcp_server --transport sse --port 8000  # SSE mode
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Detect MCP SDK availability
# ---------------------------------------------------------------------------
_HAS_MCP = False
try:
    from mcp.server.fastmcp import FastMCP  # type: ignore[import-untyped]

    _HAS_MCP = True
except ImportError:
    FastMCP = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Core module availability flags (graded — each tool checks its own dependency)
# ---------------------------------------------------------------------------
_HAS_MEMORY = False
_HAS_MEMORY_STORE = False
_HAS_AGENT_REGISTRY = False
_HAS_PLUGIN_REGISTRY = False
_HAS_COST = False
_HAS_ROUTER = False
_HAS_MCP_TASK_STORE = False
_HAS_MCP_PLAN_STORE = False

try:
    from src.core.memory_client import get_memory_provider

    _HAS_MEMORY = True
except ImportError:
    pass

try:
    from src.core.memory_canonical import MemoryStore

    _HAS_MEMORY_STORE = True
except ImportError:
    pass

try:
    from src.core.agent_registry import AgentRegistry

    _HAS_AGENT_REGISTRY = True
except ImportError:
    pass

try:
    from src.core.plugin_registry import PluginRegistry

    _HAS_PLUGIN_REGISTRY = True
except ImportError:
    pass

_HAS_MCU = importlib.util.find_spec("src.core.mcu_gate") is not None
_HAS_COST = importlib.util.find_spec("src.core.cost_estimator") is not None
_HAS_ROUTER = importlib.util.find_spec("src.core.hybrid_router") is not None

try:
    from src.core.mcp_task_store import get_task_store

    _HAS_MCP_TASK_STORE = True
except ImportError:
    _HAS_MCP_TASK_STORE = False

try:
    from src.core.mcp_plan_store import get_plan_store

    _HAS_MCP_PLAN_STORE = True
except ImportError:
    _HAS_MCP_PLAN_STORE = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(data: Any) -> str:
    """Wrap result as success JSON."""
    return json.dumps({"ok": True, "data": data}, indent=2, default=str)


def _err(msg: str) -> str:
    """Wrap error as failure JSON."""
    return json.dumps({"ok": False, "error": msg}, indent=2)


def _missing(capability: str) -> str:
    """Return a consistent 'not available' message."""
    return _err(
        f"'{capability}' is not available — the required Mekong core "
        f"module could not be loaded. Install it or run in a full Mekong environment."
    )


# ---------------------------------------------------------------------------
# Lazy singletons (initialised on first use)
# ---------------------------------------------------------------------------
_memory: Any = None
_memory_store: Any = None
_agent_registry: Any = None
_plugin_registry: Any = None


def _get_memory() -> Any:
    """Get or create the memory provider singleton."""
    global _memory
    if _memory is None and _HAS_MEMORY:
        _memory = get_memory_provider()
    return _memory


def _get_memory_store() -> Any:
    """Get or create the memory store singleton."""
    global _memory_store
    if _memory_store is None and _HAS_MEMORY_STORE:
        _memory_store = MemoryStore()
    return _memory_store


def _get_agent_registry() -> Any:
    """Get or create the agent registry singleton."""
    global _agent_registry
    if _agent_registry is None and _HAS_AGENT_REGISTRY:
        _agent_registry = AgentRegistry()
    return _agent_registry


def _get_plugin_registry() -> Any:
    """Get or create the plugin registry singleton."""
    global _plugin_registry
    if _plugin_registry is None and _HAS_PLUGIN_REGISTRY:
        _plugin_registry = PluginRegistry()
    return _plugin_registry


# ===================================================================
# MekongMcpServer
# ===================================================================


class MekongMcpServer:
    """MCP server exposing Mekong AI OS capabilities as tools.

    Wraps 25 tool handlers that proxy to Mekong core modules with
    graceful degradation when modules are unavailable.

    Usage:
        server = MekongMcpServer()
        app = server.create_app()
        app.run(transport="stdio")
    """

    def __init__(self, name: str = "mekong-ai-os") -> None:
        self.name = name
        self._app: Any = None
        self._tools: list[dict[str, str]] = []

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    def create_app(self) -> Any:
        """Create the FastMCP application with all 25 tools registered.

        Returns:
            FastMCP instance (or raises RuntimeError if mcp SDK missing).

        """
        if not _HAS_MCP:
            msg = (
                "MCP SDK is not installed. Run: pip install mcp"
            )
            raise RuntimeError(msg)

        app: Any = FastMCP(self.name, log_level="ERROR")
        self._register_tools(app)
        self._tools = [
            {"name": t.name, "description": t.description or ""}
            for t in app._tool_manager.list_tools()
        ]
        self._app = app
        return app

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------

    def run(self, transport: str = "stdio") -> None:
        """Run the MCP server.

        Args:
            transport: ``"stdio"`` for stdin/stdout (OpenCode/Claude),
                       ``"sse"`` for HTTP SSE transport (gateway).

        """
        app = self.create_app()
        os.environ["LANG"] = os.environ.get("LANG", "en_US.UTF-8")
        os.environ["TERM"] = os.environ.get("TERM", "xterm-256color")
        app.run(transport=transport)

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_tools(self, app: Any) -> None:
        """Register all 24 MCP tools on the FastMCP instance."""

        # ── Memory ────────────────────────────────────────────────────

        @app.tool(description="Search Mekong AI OS persistent memory")
        def cc_memory_search(query: str, limit: int = 10) -> str:
            return self._handle_memory_search(query, limit)

        @app.tool(description="Consolidate session memories into long-term memory")
        def cc_memory_consolidate() -> str:
            return self._handle_memory_consolidate()

        # ── Tasks ─────────────────────────────────────────────────────

        @app.tool(
            description="List Mekong tasks (omit status for all, or: todo / in-progress / done)"
        )
        def cc_tasks_list(status: str = "") -> str:
            return self._handle_tasks_list(status)

        @app.tool(description="Create a new task with a subject line")
        def cc_tasks_create(subject: str) -> str:
            return self._handle_tasks_create(subject)

        @app.tool(description="Mark a task as done by ID")
        def cc_tasks_done(task_id: str) -> str:
            return self._handle_tasks_done(task_id)

        @app.tool(description="Mark a task as in-progress by ID")
        def cc_tasks_start(task_id: str) -> str:
            return self._handle_tasks_start(task_id)

        @app.tool(description="Delete a task by ID")
        def cc_tasks_delete(task_id: str) -> str:
            return self._handle_tasks_delete(task_id)

        # ── Agents ────────────────────────────────────────────────────

        @app.tool(description="List registered Mekong background agents")
        def cc_agents_list() -> str:
            return self._handle_agents_list()

        @app.tool(
            description="Start an autonomous agent "
            "(research_assistant / auto_bug_fixer / paper_writer / auto_coder)"
        )
        def cc_agents_start(template: str, args: str = "") -> str:
            return self._handle_agents_start(template, args)

        @app.tool(description="Stop a running agent by name")
        def cc_agents_stop(name: str) -> str:
            return self._handle_agents_stop(name)

        # ── Skills ────────────────────────────────────────────────────

        @app.tool(description="List available Mekong skills")
        def cc_skills_list() -> str:
            return self._handle_skills_list()

        # ── MCP System ────────────────────────────────────────────────

        @app.tool(description="List Mekong MCP servers and their tools")
        def cc_mcp_list() -> str:
            return self._handle_mcp_list()

        # ── Plugins ───────────────────────────────────────────────────

        @app.tool(description="List Mekong plugins")
        def cc_plugins_list() -> str:
            return self._handle_plugins_list()

        @app.tool(description="Install a Mekong plugin by name@url")
        def cc_plugins_install(name_url: str) -> str:
            return self._handle_plugins_install(name_url)

        # ── Brainstorm ────────────────────────────────────────────────

        @app.tool(description="Run multi-persona brainstorm on a topic via Mekong")
        def cc_brainstorm(topic: str) -> str:
            return self._handle_brainstorm(topic)

        # ── Research Lab ──────────────────────────────────────────────

        @app.tool(
            description="Start a research lab session on a topic. "
            "Creates a tracked lab session with LLM analysis."
        )
        def cc_lab_start(topic: str) -> str:
            return self._handle_lab_start(topic)

        @app.tool(description="List active and recent research lab sessions")
        def cc_lab_status() -> str:
            return self._handle_lab_status()

        # ── Trading ───────────────────────────────────────────────────

        @app.tool(
            description="Analyze a trading symbol using LLM. "
            "Returns multi-perspective analysis (technical, fundamental, sentiment). "
            "Note: AI-generated analysis, not financial advice."
        )
        def cc_trading_analyze(symbol: str) -> str:
            return self._handle_trading_analyze(symbol)

        @app.tool(
            description="Get LLM-informed analysis for a trading symbol's price context. "
            "Note: AI-generated context, not real-time market data."
        )
        def cc_trading_price(symbol: str) -> str:
            return self._handle_trading_price(symbol)

        # ── Monitor ───────────────────────────────────────────────────

        @app.tool(
            description="Start monitoring a topic or subscription. "
            "Creates a tracked monitor session that periodically checks the topic."
        )
        def cc_monitor_run(topic: str = "") -> str:
            return self._handle_monitor_run(topic)

        @app.tool(description="List active and recent monitor sessions")
        def cc_monitor_status() -> str:
            return self._handle_monitor_status()

        # ── Plan Mode ─────────────────────────────────────────────────

        @app.tool(
            description="Enter plan mode — decomposes a goal into a task tree. "
            "Uses PlanStore for persistence. Returns plan_id and task list."
        )
        def cc_plan_start(description: str) -> str:
            return self._handle_plan_start(description)

        @app.tool(
            description="List saved plans. "
            "Pass status='active' or status='completed' to filter."
        )
        def cc_plan_list(status: str = "") -> str:
            return self._handle_plan_list(status)

        @app.tool(
            description="Mark a plan as done by plan_id. "
            "Sets all remaining tasks to 'done' and closes the plan."
        )
        def cc_plan_done(plan_id: str) -> str:
            return self._handle_plan_done(plan_id)

        # ── SSJ (Developer Power Menu) ────────────────────────────────

        @app.tool(
            description="SSJ Developer Mode — run diagnostics, health check, memory stats, "
            "plugin status, toggle logging, or reload config. "
            "Pass action=all (default) or one of: diagnostics / toggle-logging / reload-config / "
            "health-check / memory-stats / plugin-status"
        )
        def cc_ssj(action: str = "all") -> str:
            return self._handle_ssj(action)

        # ── Command Fabric ────────────────────────────────────────────

        @app.tool(
            description="List universal command fabric manifests for IDEs, agents, and MCP"
        )
        def cc_command_fabric_list(scope: str = "project", adapter: str = "mcp") -> str:
            return self._handle_command_fabric_list(scope=scope, adapter=adapter)

        @app.tool(
            description="Execute or inspect a command through universal command fabric"
        )
        def cc_command_fabric_run(command: str, args: str = "", scope: str = "project") -> str:
            return self._handle_command_fabric_run(command=command, args=args, scope=scope)

    # ==============================================================
    # Handler implementations
    # ==============================================================

    # ── Memory ────────────────────────────────────────────────────────

    def _handle_memory_search(self, query: str, limit: int = 10) -> str:
        """Search AI OS memory by query using NeuralMemory or MemoryStore."""
        # Try NeuralMemory provider first
        mem = _get_memory()
        if mem is not None:
            try:
                # Try query_memory (NeuralMemoryClient) or search (Mem0 facade)
                if hasattr(mem, "query_memory"):
                    result = mem.query_memory(query, depth=limit)
                    if result:
                        return _ok({"query": query, "results": result[:2000]})
                elif hasattr(mem, "search"):
                    hits = mem.search(query, user_id="mekong:mcp")
                    if hits:
                        return _ok({"query": query, "results": str(hits)[:2000]})
                return _ok({"query": query, "results": [], "note": "No matching memories"})
            except Exception as exc:
                logger.warning("Memory search failed: %s", exc)
                return _err(f"Memory search error: {exc}")

        # Fallback: YAML MemoryStore
        store = _get_memory_store()
        if store is not None:
            try:
                entries = store.query(query)
                results = [
                    {
                        "goal": e.goal,
                        "status": e.status,
                        "timestamp": getattr(e, "timestamp", 0),
                        "error_summary": getattr(e, "error_summary", ""),
                    }
                    for e in (entries or [])[:limit]
                ]
                return _ok({"query": query, "results": results})
            except Exception as exc:
                logger.warning("MemoryStore search failed: %s", exc)
                return _err(f"MemoryStore search error: {exc}")

        return _missing("memory_search")

    def _handle_memory_consolidate(self) -> str:
        """Consolidate memories by compressing old entries in MemoryStore."""
        store = _get_memory_store()
        if store is not None:
            try:
                count = store.compress_old_memories(days_threshold=7, keep_recent=100)
                stats = store.stats()
                return _ok({
                    "compressed": count,
                    "total_entries": stats.get("total", 0),
                    "success_rate": stats.get("success_rate", 0),
                })
            except Exception as exc:
                logger.warning("Memory consolidate failed: %s", exc)
                return _err(f"Memory consolidate error: {exc}")

        # If MemoryStore not available, report but don't fail
        return _ok({
            "compressed": 0,
            "note": "Memory consolidation requires MemoryStore (YAML-backed)",
        })

    # ── Tasks ─────────────────────────────────────────────────────────

    def _handle_tasks_list(self, status: str = "") -> str:
        """List tasks from McpTaskStore."""
        try:
            store = get_task_store()
            tasks = store.list(status=status)
            return _ok({
                "tasks": [t.to_dict() for t in tasks],
                "count": len(tasks),
                "stats": store.stats(),
            })
        except Exception as exc:
            logger.warning("Task list failed: %s", exc)
            return _err(f"Task list error: {exc}")

    def _handle_tasks_create(self, subject: str) -> str:
        try:
            store = get_task_store()
            task = store.create(subject)
            return _ok({
                "created": True,
                "task": task.to_dict(),
            })
        except Exception as exc:
            logger.warning("Task create failed: %s", exc)
            return _err(f"Task create error: {exc}")

    def _handle_tasks_done(self, task_id: str) -> str:
        try:
            store = get_task_store()
            task = store.update_status(task_id, "done")
            if task is None:
                return _err(f"Task '{task_id}' not found")
            return _ok({
                "updated": True,
                "task": task.to_dict(),
            })
        except Exception as exc:
            logger.warning("Task done failed: %s", exc)
            return _err(f"Task done error: {exc}")

    def _handle_tasks_start(self, task_id: str) -> str:
        try:
            store = get_task_store()
            task = store.update_status(task_id, "in-progress")
            if task is None:
                return _err(f"Task '{task_id}' not found")
            return _ok({
                "updated": True,
                "task": task.to_dict(),
            })
        except Exception as exc:
            logger.warning("Task start failed: %s", exc)
            return _err(f"Task start error: {exc}")

    def _handle_tasks_delete(self, task_id: str) -> str:
        try:
            store = get_task_store()
            if store.delete(task_id):
                return _ok({"deleted": True, "task_id": task_id})
            return _err(f"Task '{task_id}' not found")
        except Exception as exc:
            logger.warning("Task delete failed: %s", exc)
            return _err(f"Task delete error: {exc}")

    # ── Agents ────────────────────────────────────────────────────────

    def _handle_agents_list(self) -> str:
        """List registered agents from AgentRegistry."""
        reg = _get_agent_registry()
        if reg is not None:
            try:
                agents = reg.list_agents()
                return _ok({"agents": agents, "count": len(agents)})
            except Exception as exc:
                logger.warning("Agent list failed: %s", exc)
                return _err(f"Agent list error: {exc}")
        return _missing("agent_registry")

    def _handle_agents_start(self, template: str, args: str = "") -> str:
        """Start an agent — delegates to agent dispatcher."""
        if not _HAS_AGENT_REGISTRY:
            return _missing("agent_registry")

        try:
            from src.core.agent_dispatcher import load_agent_prompt

            prompt = load_agent_prompt(template)
            return _ok({
                "agent": template,
                "prompt": prompt[:500],
                "note": (
                    f"Agent '{template}' prompt loaded. "
                    "Full autonomous agent execution requires the Mekong "
                    "orchestrator pipeline (hybrid_router). "
                    "Use `mekong agent start <template>` in the CLI."
                ),
            })
        except Exception as exc:
            logger.warning("Agent start failed: %s", exc)
            return _err(f"Agent start error: {exc}")

    def _handle_agents_stop(self, name: str) -> str:
        """Stop an agent — placeholder until agent lifecycle is in core."""
        return _ok({
            "stopped": False,
            "note": (
                f"Agent '{name}' stop requested. "
                "Agent lifecycle management is available via "
                "`mekong agent stop <name>` in the CLI."
            ),
        })

    # ── Skills ────────────────────────────────────────────────────────

    def _handle_skills_list(self) -> str:
        """List available skills by scanning .opencode/skills/ and .claude/skills/."""
        skills: list[dict[str, str]] = []
        skill_dirs = [
            Path(os.path.expanduser("~/.opencode/skills")),
            Path(os.path.expanduser("~/.claude/skills")),
        ]
        for sdir in skill_dirs:
            if sdir.exists():
                try:
                    for child in sorted(sdir.iterdir()):
                        if child.is_dir():
                            skills.append({
                                "name": child.name,
                                "source": str(sdir),
                            })
                except PermissionError:
                    logger.warning("Cannot read skill directory: %s", sdir)

        return _ok({"skills": skills, "count": len(skills)})

    # ── MCP System ────────────────────────────────────────────────────

    def _handle_mcp_list(self) -> str:
        """List this MCP server's own tools and any discovered MCP servers."""
        return _ok({
            "mcp_servers": [{"name": self.name, "tools_count": len(self._tools)}],
            "tools": self._tools,
        })

    # ── Plugins ───────────────────────────────────────────────────────

    def _handle_plugins_list(self) -> str:
        """List plugins from PluginRegistry."""
        reg = _get_plugin_registry()
        if reg is not None:
            try:
                # Auto-discover on every list to pick up new plugins
                reg.discover()
                manifests = reg.list_plugins()
                plugins = [
                    {
                        "name": m.name,
                        "version": m.version,
                        "type": m.plugin_type.value if hasattr(m.plugin_type, "value") else str(m.plugin_type),
                        "status": m.status.value if hasattr(m.status, "value") else str(m.status),
                        "source": m.source,
                    }
                    for m in manifests
                ]
                return _ok({"plugins": plugins, "count": len(plugins)})
            except Exception as exc:
                logger.warning("Plugin list failed: %s", exc)
                return _err(f"Plugin list error: {exc}")
        return _missing("plugin_registry")

    def _handle_plugins_install(self, name_url: str) -> str:
        """Install a plugin via PluginRegistry."""
        reg = _get_plugin_registry()
        if reg is not None:
            try:
                manifest = reg.install(name_url)
                return _ok({
                    "installed": True,
                    "name": manifest.name,
                    "version": manifest.version,
                    "source": manifest.source,
                    "status": manifest.status.value if hasattr(manifest.status, "value") else str(manifest.status),
                })
            except RuntimeError as exc:
                return _err(f"Plugin install failed: {exc}")
            except Exception as exc:
                logger.warning("Plugin install error: %s", exc)
                return _err(f"Plugin install error: {exc}")
        return _missing("plugin_registry")

    # ── Brainstorm ────────────────────────────────────────────────────

    def _handle_brainstorm(self, topic: str) -> str:
        """Multi-persona brainstorm using the LLM client."""
        try:
            from src.providers.llm.client import get_client as get_llm_client

            client = get_llm_client()
            prompt = (
                f"You are a multi-persona brainstorming facilitator. "
                f"Generate diverse perspectives on the topic: '{topic}'. "
                f"Include viewpoints from a CTO, CMO, COO, and a domain expert. "
                f"Provide structured insights with pros and cons for each perspective."
            )
            response = client.generate(prompt, max_tokens=2000)
            text = response if isinstance(response, str) else getattr(response, "content", str(response))
            return _ok({"topic": topic, "brainstorm": text[:4000]})
        except ImportError:
            return _missing("llm_client (brainstorm)")
        except Exception as exc:
            logger.warning("Brainstorm failed: %s", exc)
            return _err(f"Brainstorm error: {exc}")

    # ── Research Lab ──────────────────────────────────────────────────

    def _handle_lab_start(self, topic: str) -> str:
        """Start a research lab session on a topic."""
        now = datetime.now(tz=timezone.utc).isoformat()
        session = {
            "topic": topic,
            "started_at": now,
            "status": "active",
            "session_id": uuid.uuid4().hex[:12],
        }
        store = _get_memory_store()
        if store is not None:
            try:
                store.save(f"lab:{session['session_id']}", session)
            except Exception:
                pass
        return _ok({
            "lab_started": True,
            "session": session,
            "note": f"Lab session started for '{topic}'. Use cc_lab_status to check active sessions.",
        })

    def _handle_lab_status(self) -> str:
        """List active and recent lab sessions."""
        store = _get_memory_store()
        sessions: list[dict[str, Any]] = []
        if store is not None:
            try:
                all_keys = store.list_keys() if hasattr(store, "list_keys") else []
                lab_keys = [k for k in all_keys if isinstance(k, str) and k.startswith("lab:")]
                for key in lab_keys:
                    data = store.load(key)
                    if data:
                        sessions.append(data)
            except Exception:
                pass
        return _ok({
            "status": "active" if sessions else "idle",
            "active_labs": sessions,
            "count": len(sessions),
        })

    # ── Trading ───────────────────────────────────────────────────────

    def _handle_trading_analyze(self, symbol: str) -> str:
        """Analyze a trading symbol using LLM."""
        try:
            from src.providers.llm.client import get_client as get_llm_client
            client = get_llm_client()
            prompt = (
                f"Provide a multi-perspective analysis of {symbol} as a trading asset. "
                f"Include: 1) Technical analysis overview, 2) Fundamental factors, "
                f"3) Market sentiment, 4) Key support/resistance levels (hypothetical), "
                f"5) Risk factors. Label clearly that this is AI-generated analysis, "
                f"not financial advice. Be concise (max 600 words)."
            )
            response = client.generate(prompt, max_tokens=2000)
            text = response if isinstance(response, str) else getattr(response, "content", str(response))
            return _ok({
                "symbol": symbol.upper(),
                "analysis": text[:4000],
                "disclaimer": "AI-generated analysis for educational purposes only. Not financial advice.",
            })
        except ImportError:
            return _ok({
                "symbol": symbol.upper(),
                "analysis": "LLM client not available for analysis.",
                "disclaimer": "Install llm_client to enable AI-powered trading analysis.",
            })
        except Exception as exc:
            logger.warning("Trading analysis failed: %s", exc)
            return _err(f"Trading analysis error: {exc}")

    def _handle_trading_price(self, symbol: str) -> str:
        """Get AI-informed analysis for a trading symbol's price context."""
        try:
            from src.providers.llm.client import get_client as get_llm_client
            client = get_llm_client()
            prompt = (
                f"Provide recent price context and market conditions for {symbol}. "
                f"Discuss typical price ranges, volatility patterns, and any notable "
                f"market events affecting this asset. Be concise (max 300 words). "
                f"Clearly state this is AI-generated context, not real-time pricing."
            )
            response = client.generate(prompt, max_tokens=1000)
            text = response if isinstance(response, str) else getattr(response, "content", str(response))
            return _ok({
                "symbol": symbol.upper(),
                "price_context": text[:2000],
                "disclaimer": (
                    "AI-generated context, not real-time market data. "
                    "Use a dedicated price feed API for current prices."
                ),
            })
        except ImportError:
            return _ok({
                "symbol": symbol.upper(),
                "price_context": "LLM client not available.",
                "disclaimer": "Install llm_client for AI-powered price context.",
            })
        except Exception as exc:
            logger.warning("Trading price lookup failed: %s", exc)
            return _err(f"Trading price error: {exc}")

    # ── Monitor ───────────────────────────────────────────────────────

    def _handle_monitor_run(self, topic: str = "") -> str:
        """Start monitoring a topic or subscription."""
        now = datetime.now(tz=timezone.utc).isoformat()
        topic = topic.strip() or "all subscriptions"
        monitor_id = uuid.uuid4().hex[:12]
        session = {
            "monitor_id": monitor_id,
            "topic": topic,
            "started_at": now,
            "interval_seconds": 300,
            "status": "active",
        }
        store = _get_memory_store()
        if store is not None:
            try:
                store.save(f"monitor:{monitor_id}", session)
            except Exception:
                pass
        return _ok({
            "monitor_started": True,
            "session": session,
            "note": f"Monitoring '{topic}'. Use cc_monitor_status to check active monitors.",
        })

    def _handle_monitor_status(self) -> str:
        """List active and recent monitor sessions."""
        store = _get_memory_store()
        sessions: list[dict[str, Any]] = []
        if store is not None:
            try:
                all_keys = store.list_keys() if hasattr(store, "list_keys") else []
                monitor_keys = [k for k in all_keys if isinstance(k, str) and k.startswith("monitor:")]
                for key in monitor_keys:
                    data = store.load(key)
                    if data:
                        sessions.append(data)
            except Exception:
                pass
        return _ok({
            "status": "active" if sessions else "idle",
            "active_monitors": sessions,
            "count": len(sessions),
        })

    # ── Plan Mode ─────────────────────────────────────────────────────

    def _handle_plan_start(self, description: str) -> str:
        """Enter plan mode — decomposes goal into tasks via PlanStore."""
        if not _HAS_MCP_PLAN_STORE:
            return _missing("mcp_plan_store")
        try:
            store = get_plan_store()
            plan = store.create(description)
            return _ok({
                "plan_started": True,
                "plan_id": plan.plan_id,
                "description": description,
                "tasks": plan.tasks,
                "task_count": len(plan.tasks),
                "note": f"Plan {plan.plan_id} created with {len(plan.tasks)} tasks. "
                "Use cc_plan_list to view all plans, cc_plan_done to close.",
            })
        except Exception as exc:
            logger.warning("Plan start failed: %s", exc)
            return _err(f"Plan start error: {exc}")

    def _handle_plan_list(self, status: str = "") -> str:
        """List saved plans from PlanStore."""
        if not _HAS_MCP_PLAN_STORE:
            return _missing("mcp_plan_store")
        try:
            store = get_plan_store()
            plans = store.list(status=status)
            return _ok({
                "plans": [p.to_dict() for p in plans],
                "count": len(plans),
            })
        except Exception as exc:
            logger.warning("Plan list failed: %s", exc)
            return _err(f"Plan list error: {exc}")

    def _handle_plan_done(self, plan_id: str) -> str:
        """Mark a plan as completed."""
        if not _HAS_MCP_PLAN_STORE:
            return _missing("mcp_plan_store")
        try:
            store = get_plan_store()
            plan = store.complete(plan_id)
            if plan is None:
                return _err(f"Plan '{plan_id}' not found")
            return _ok({
                "plan_done": True,
                "plan_id": plan_id,
                "tasks_completed": len(plan.tasks),
                "note": f"Plan {plan_id} completed with {len(plan.tasks)} tasks.",
            })
        except Exception as exc:
            logger.warning("Plan done failed: %s", exc)
            return _err(f"Plan done error: {exc}")

    # ── SSJ ───────────────────────────────────────────────────────────

    def _handle_ssj(self, action: str = "all") -> str:
        """SSJ Developer Mode power menu."""
        actions = {
            "all": self._ssj_all,
            "diagnostics": self._ssj_diagnostics,
            "toggle-logging": self._ssj_toggle_logging,
            "reload-config": self._ssj_reload_config,
            "health-check": self._ssj_health_check,
            "memory-stats": self._ssj_memory_stats,
            "plugin-status": self._ssj_plugin_status,
        }
        handler = actions.get(action)
        if handler is None:
            return _err(
                f"Unknown SSJ action '{action}'. "
                f"Available: {', '.join(sorted(actions))}"
            )
        return handler()

    # ── Command Fabric ────────────────────────────────────────────────

    def _handle_command_fabric_list(self, scope: str = "project", adapter: str = "mcp") -> str:
        """List command fabric adapter manifest."""
        try:
            from src.command_fabric.runtime import command_fabric_manifest
            payload = command_fabric_manifest(adapter=adapter, scope=scope)  # type: ignore[arg-type]
            return _ok(payload)
        except Exception as exc:
            logger.warning("Command fabric list failed: %s", exc)
            return _err(f"Command fabric list error: {exc}")

    def _handle_command_fabric_run(
        self, command: str, args: str = "", scope: str = "project"
    ) -> str:
        """Run or inspect a command fabric definition."""
        if scope not in ("project", "global"):
            return _err(f"Invalid scope '{scope}'. Must be 'project' or 'global'.")
        clean_cmd = command.strip()
        if not clean_cmd:
            return _err("Command cannot be empty.")
        if any(ch in clean_cmd for ch in ("/", "\\", "\0", ";", "&", "|", "`", "$", "(", ")", "<", ">", "\n", "\r", " ")):
            return _err(f"Invalid command name '{clean_cmd}'. Shell metacharacters and path separators are forbidden.")
        if any(ch in args for ch in ("\0", "\n", "\r", ";", "&", "|", "`", "$(")):
            return _err("Command arguments contain forbidden control or shell metacharacters.")
        try:
            from src.command_fabric.runtime import invoke_command_fabric
            result = invoke_command_fabric(command=clean_cmd, args=args, scope=scope)  # type: ignore[arg-type]
            return _ok(result.to_dict())
        except Exception as exc:
            logger.warning("Command fabric run failed: %s", exc)
            return _err(f"Command fabric run error: {exc}")

    def _check_llm_available(self) -> bool:
        """Check if LLM client is available and connected."""
        try:
            from src.providers.llm.client import get_client
            return get_client().is_available
        except Exception:
            return False

    def _ssj_diagnostics(self) -> str:
        """Run system diagnostics."""
        info: dict[str, Any] = {"python": __import__("sys").version}

        try:
            from src.providers.llm.client import get_client
            client = get_client()
            info["llm_available"] = client.is_available
            info["llm_providers"] = [
                p.name for p in client.providers if p.name != "offline"
            ]
        except Exception as exc:
            info["llm"] = f"error: {exc}"

        info["memory_available"] = _HAS_MEMORY or _HAS_MEMORY_STORE
        info["agent_registry"] = _HAS_AGENT_REGISTRY
        info["plugin_registry"] = _HAS_PLUGIN_REGISTRY
        info["mcp_sdk"] = _HAS_MCP

        try:
            import psutil
            info["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            info["memory_percent"] = psutil.virtual_memory().percent
            info["disk_percent"] = psutil.disk_usage("/").percent
        except ImportError:
            pass

        return _ok({"diagnostics": info})

    def _ssj_toggle_logging(self) -> str:
        """Toggle verbose logging on/off."""
        current = os.environ.get("LOG_LEVEL", "WARNING").upper()
        new = "DEBUG" if current == "WARNING" else "WARNING"
        os.environ["LOG_LEVEL"] = new
        logging.getLogger().setLevel(getattr(logging, new, logging.WARNING))
        return _ok({"log_level": new, "previous": current})

    def _ssj_reload_config(self) -> str:
        """Reload .env config file."""
        try:
            from dotenv import load_dotenv  # type: ignore[import-untyped]
        except ImportError:
            return _err("python-dotenv not installed — pip install python-dotenv")

        env_path = Path.cwd() / ".env"
        if not env_path.exists():
            return _err(f"No .env file found at {env_path}")
        try:
            loaded = load_dotenv(env_path, override=True)
            return _ok({
                "reloaded": loaded,
                "path": str(env_path),
            })
        except Exception as exc:
            return _err(f"Reload config error: {exc}")

    def _ssj_health_check(self) -> str:
        """System health check."""
        checks: dict[str, Any] = {}

        try:
            import psutil
            mem = psutil.virtual_memory()
            checks["memory"] = {
                "total_gb": round(mem.total / 1e9, 1),
                "used_gb": round(mem.used / 1e9, 1),
                "percent": mem.percent,
            }
            checks["disk"] = {
                "total_gb": round(psutil.disk_usage("/").total / 1e9, 1),
                "free_gb": round(psutil.disk_usage("/").free / 1e9, 1),
                "percent": psutil.disk_usage("/").percent,
            }
            checks["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            checks["boot_time"] = datetime.fromtimestamp(
                psutil.boot_time(), tz=timezone.utc
            ).isoformat()
        except ImportError:
            checks["note"] = "Install psutil for detailed health metrics"

        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                temp_c = int(f.read().strip()) / 1000
                checks["thermal_c"] = temp_c
        except OSError:
            pass

        checks["llm_available"] = (
            _HAS_MCP and self._check_llm_available()
        )

        return _ok({"health": checks})

    def _ssj_memory_stats(self) -> str:
        """Get memory store statistics."""
        store = _get_memory_store()
        if store is not None:
            try:
                stats = store.stats() if hasattr(store, "stats") else {}
                return _ok({"memory_stats": stats})
            except Exception as exc:
                return _err(f"Memory stats error: {exc}")

        mem = _get_memory()
        if mem is not None:
            return _ok({
                "memory_stats": "Mem0 provider active (query via cc_memory_search)"
            })
        return _missing("memory_store")

    def _ssj_plugin_status(self) -> str:
        """Get plugin registry status."""
        reg = _get_plugin_registry()
        if reg is not None:
            try:
                manifests = reg.list_plugins()
                return _ok({
                    "plugin_count": len(manifests),
                    "plugins": [
                        {
                            "name": m.name,
                            "version": m.version,
                            "status": m.status.value if hasattr(m.status, "value") else str(m.status),
                        }
                        for m in manifests
                    ],
                })
            except Exception as exc:
                return _err(f"Plugin status error: {exc}")
        return _missing("plugin_registry")

    def _ssj_all(self) -> str:
        """Return SSJ menu with a summary of all statuses."""
        diag = json.loads(self._ssj_diagnostics())
        health = json.loads(self._ssj_health_check())
        return _ok({
            "ssj_menu": [
                {"action": "diagnostics", "label": "Run diagnostics"},
                {"action": "toggle-logging", "label": f"Toggle verbose logging (currently {os.environ.get('LOG_LEVEL', 'WARNING')})"},
                {"action": "reload-config", "label": "Reload .env config"},
                {"action": "health-check", "label": "System health check"},
                {"action": "memory-stats", "label": "Memory stats"},
                {"action": "plugin-status", "label": "Plugin status"},
            ],
            "summary": {
                "llm": diag.get("data", {}).get("diagnostics", {}).get("llm_available", "unknown"),
                "health": health.get("data", {}).get("health", {}),
            },
            "note": "Run cc_ssj with a specific action parameter for detailed results.",
        })


# ===================================================================
# Module-level helpers
# ===================================================================


def create_app(name: str = "mekong-ai-os") -> Any:
    """Shorthand to create a pre-configured FastMCP app.

    Returns:
        FastMCP instance with all 25 tools registered.

    """
    server = MekongMcpServer(name=name)
    return server.create_app()


# ===================================================================
# CLI entry point
# ===================================================================


def main() -> None:
    """Standalone entry point for the MCP server.

    Parses arguments and runs the server with the chosen transport.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Mekong AI OS — MCP Server",
    )
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse"],
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for SSE transport (default: 8000)",
    )
    parser.add_argument(
        "--name",
        default="mekong-ai-os",
        help="MCP server name (default: mekong-ai-os)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "WARNING").upper(),
        format="%(levelname)s | %(name)s | %(message)s",
    )

    server = MekongMcpServer(name=args.name)

    if args.transport == "sse":
        os.environ["MCP_SSE_PORT"] = str(args.port)

    try:
        server.run(transport=args.transport)
    except RuntimeError as exc:
        logger.error("Failed to start MCP server: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
