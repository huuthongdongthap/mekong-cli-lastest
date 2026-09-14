# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""
Run command — wire MekongCoreRuntimeImpl with real dependencies.

Usage:
    mekong run --goal "Analyze monthly revenue"
    mekong run --goal "Deploy production build" --max-cost-usd 2.50

Autonomy gates are ON by default in this wiring:

- Observability: TelemetrySinkAdapter satisfies protocols.ObservabilitySink
  (emit/flush), so the runtime's observe()/commit() telemetry calls work.
- Governance: goals classified FORBIDDEN are always blocked; goals classified
  REVIEW_REQUIRED (e.g. "deploy production build") are blocked unless
  GOVERNANCE_AUTO_APPROVE=true|1|yes is set. There is no CLI bypass.
- Cost ceiling: defaults to $5.00 per mission; override with the
  MEKONG_MAX_COST_USD env var or the --max-cost-usd option (option wins).
- Mission tracing: a MissionTracer is attached via runtime.start_mission()
  before the loop runs, so steps and outcomes are correlated per mission.
"""

from __future__ import annotations

import logging
import os

import typer
from rich.console import Console
from rich.panel import Panel

from src.core.capability import CapabilityBus, InMemoryCapabilityBus
from src.core.governance import Governance
from src.core.mission_tracer import MissionTracer
from src.core.telemetry_sink_adapter import TelemetrySinkAdapter
from src.core.adapters.goal_engine_adapter import make_goal_engine_adapter

logger = logging.getLogger(__name__)

app = typer.Typer()
console = Console()

_DEFAULT_MAX_COST_USD = 5.0


def _resolve_max_cost_usd(cli_value: float | None) -> float:
    """Resolve the per-mission cost ceiling: CLI option > env var > default."""
    if cli_value is not None:
        return cli_value
    raw = os.getenv("MEKONG_MAX_COST_USD", "")
    if raw:
        try:
            return float(raw)
        except ValueError:
            console.print(
                f"[yellow]Invalid MEKONG_MAX_COST_USD={raw!r}; "
                f"falling back to ${_DEFAULT_MAX_COST_USD:.2f}[/yellow]"
            )
    return _DEFAULT_MAX_COST_USD


def _build_runtime(max_cost_usd: float | None = None, with_capabilities: bool = True):
    """Build MekongCoreRuntimeImpl with real dependencies from core modules.

    Governance is wired ON by default: forbidden goals are blocked and
    review-class goals require GOVERNANCE_AUTO_APPROVE=true|1|yes. The cost
    ceiling defaults to $5.00 per mission (override via MEKONG_MAX_COST_USD
    or the --max-cost-usd CLI option).

    Capability bus is injected by default (with_capabilities=True) and builtin
    tools are synced. If bus initialization fails, falls back gracefully without
    crashing the runtime (failure-tolerant).
    """
    from src.core.runtime_adapter import MekongCoreRuntimeImpl
    from src.core.adapters.memory_store_adapter import MemoryStoreBridge
    from src.core.billing_adapter import BillingAdapter
    from src.core.tool_registry import ToolRegistry
    from src.core.adapters.tool_capability_adapter import ToolCapabilityAdapter
    from src.core.adapters.mcp_capability_adapter import MCPCapabilityAdapter

    memory = MemoryStoreBridge()
    billing = BillingAdapter()
    tool_registry = ToolRegistry()
    telemetry = TelemetrySinkAdapter()
    governance = Governance()
    # Registry-backed dispatcher (failure-tolerant): resolves AgentId to a
    # registered AgentBase subclass via AgentRegistry. If registry init fails,
    # fall back to the null dispatcher so the runtime degrades gracefully.
    try:
        dispatcher = _RegistryDispatcher()
    except Exception as exc:
        logger.warning("Registry dispatcher init failed, falling back to null: %s", exc)
        dispatcher = _NullDispatcher()

    # Capability bus injection (opt-in, failure-tolerant)
    capability_bus: CapabilityBus | None = None
    if with_capabilities:
        try:
            capability_bus = InMemoryCapabilityBus()
            tool_adapter = ToolCapabilityAdapter(tool_registry)
            tool_adapter.sync_to_bus(capability_bus)
            # MCP capability bridge: expose MekongMcpServer tools as capabilities
            # (ids prefixed ``mcp:``). Failure-tolerant — if the MCP server is
            # unavailable the bus still works with builtin tools only.
            try:
                mcp_adapter = MCPCapabilityAdapter(bus=capability_bus)
                mcp_adapter.sync_from_mcp()
                logger.debug(
                    "Capability bus initialized with %d builtin + %d MCP tools",
                    len(tool_registry.list_tools()),
                    len(capability_bus.list_capabilities(source=None)) - len(tool_registry.list_tools()),
                )
            except Exception as exc:
                logger.warning("MCP capability sync failed, continuing without: %s", exc)
            logger.debug("Capability bus total: %d capabilities", len(capability_bus.list_capabilities()))
        except Exception as exc:
            # Failure-tolerant: log but don't crash the runtime
            logger.warning("Capability bus init failed, continuing without: %s", exc)
            capability_bus = None

    return MekongCoreRuntimeImpl(
        dispatcher=dispatcher,
        tool_registry=tool_registry,
        memory_store=memory,
        billing=billing,
        telemetry=telemetry,
        governance=governance,
        capability_bus=capability_bus,
        max_cost_usd=_resolve_max_cost_usd(max_cost_usd),
        agent_id="cli",
        goal_engine=make_goal_engine_adapter(),
    )


class _NullDispatcher:
    """Minimal dispatcher stub — runtime falls back gracefully when no dispatch()."""

    def dispatch(self, task, agent=None):  # noqa: ANN001, ANN202
        raise NotImplementedError("No dispatcher configured")


class _RegistryDispatcher:
    """Dispatcher backed by the AgentRegistry (core agent stack).

    Resolves ``task.agent`` (an ``AgentId``) to a registered ``AgentBase``
    subclass via ``AgentRegistry.get_meta_obj`` and spawns it through
    ``AgentBase.run()``. Unknown agents raise ``NotImplementedError`` — the
    same graceful failure path the null dispatcher used, so the runtime's
    execute() catches it and surfaces a terminal error instead of crashing.
    """

    def __init__(self) -> None:
        from src.core.agent_registry import get_registry

        self._registry = get_registry()

    def dispatch(self, task, agent=None):  # noqa: ANN001, ANN202
        agent_name = getattr(agent, "name", None) or self._fallback_agent_name(task)
        meta = self._registry.get_meta_obj(agent_name)
        if meta is None:
            raise NotImplementedError(f"No dispatcher configured for agent '{agent_name}'")
        try:
            agent_instance = meta.cls(name=agent_name)
        except TypeError as exc:
            raise NotImplementedError(f"Cannot instantiate agent '{agent_name}': {exc}") from exc
        # The runtime's Task wraps a Step (task.step.description); the frozen
        # test passes a bare Step directly. Resolve either shape.
        goal_text = getattr(task, "description", None)
        if goal_text is None:
            step = getattr(task, "step", task)
            goal_text = getattr(step, "description", "") or ""
        results = agent_instance.run(goal_text)
        if not results:
            return {"status": "noop", "task_id": task.id}
        final = results[-1]
        return {
            "status": "success" if final.success else "failed",
            "task_id": task.id,
            "output": final.output,
            "error": final.error,
            "agent": agent_name,
        }

    @staticmethod
    def _fallback_agent_name(task) -> str:
        """Best-effort agent name when ``task.agent`` is missing."""
        params = getattr(task, "params", None) or {}
        return params.get("agent") or "default"


@app.command(name="run")
def run_command(
    goal: str = typer.Option(..., "--goal", "-g", help="Goal description for the runtime"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Print detailed output"),
    max_cost_usd: float | None = typer.Option(
        None,
        "--max-cost-usd",
        help="Per-mission cost ceiling in USD (overrides MEKONG_MAX_COST_USD; default 5.0)",
    ),
    with_capabilities: bool = typer.Option(
        True,
        "--with-capabilities/--no-capabilities",
        help="Enable capability bus with builtin tools (default: ON). Failure-tolerant.",
    ),
) -> None:
    """Run the MekongCoreRuntime with a goal string.

    Review-class goals (e.g. deploy to production) are blocked unless
    GOVERNANCE_AUTO_APPROVE=true is set; forbidden goals are always blocked.
    """
    try:
        runtime = _build_runtime(max_cost_usd=max_cost_usd, with_capabilities=with_capabilities)
    except Exception as exc:
        console.print(f"[red]Failed to initialize runtime:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    tracer = MissionTracer()
    runtime.start_mission(goal, tracer=tracer)

    # MekongCoreRuntimeImpl.run() is synchronous (src/core/protocols.py);
    # wrapping it in asyncio.run() raises TypeError.
    try:
        result = runtime.run(goal)
    except Exception as exc:
        console.print(f"[red]Runtime error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if result.error:
        console.print(
            Panel(
                f"[bold red]Goal failed:[/bold red] {goal}\n[red]Error:[/red] {result.error}",
                title="Run Result",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    output = result.output if result.output is not None else "(no output)"
    if verbose:
        console.print(
            Panel(
                f"[bold]Goal:[/bold] {goal}\n[bold]Task:[/bold] {result.task_id}\n[bold]Output:[/bold] {output}",
                title="Run Result",
                border_style="green",
            )
        )
    else:
        console.print(f"[green]OK[/green] — {output}")


def register_run_command(app: typer.Typer) -> None:
    """Register the run command onto the main typer app."""
    app.command(name="run")(run_command)
