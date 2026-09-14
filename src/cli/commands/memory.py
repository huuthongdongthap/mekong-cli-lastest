# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Memory CLI commands: list, search, clear, store, recall, history, stats.

Wires both the JSONL MemoryStore (src/core/memory_store.py) and the
YAML-backed MemoryStore (src/core/memory.py) into the Mekong CLI.
Invoked as sub-app of `mekong memory`.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm

console = Console()

memory_app = typer.Typer(
 name="memory",
 help="Memory: execution history & learning (JSONL + YAML store)",
)

DEFAULT_JSONL_PATH = Path(".mekong/memory.jsonl")
DEFAULT_YAML_PATH = Path(".mekong/memory.yaml")


# ---------------------------------------------------------------------------
# JSONL backend (action/agent/outcome/tags schema)
# ---------------------------------------------------------------------------

def _jsonl_store() -> "src.core.memory_store.MemoryStore": # noqa: F821
 from src.core.memory_store import MemoryStore

 path = os.environ.get("MEKONG_MEMORY_PATH") or DEFAULT_JSONL_PATH
 return MemoryStore(path=path)


# ---------------------------------------------------------------------------
# Conformant JSONL adapter (protocols.MemoryStore) — Super Command #7 Phase 4
# ---------------------------------------------------------------------------
def _jsonl_adapter() -> "src.core.adapters.jsonl_memory_adapter.JsonlMemoryAdapter": # noqa: F821
 from src.core.adapters.jsonl_memory_adapter import JsonlMemoryAdapter

 path = os.environ.get("MEKONG_MEMORY_PATH") or DEFAULT_JSONL_PATH
 return JsonlMemoryAdapter(path=path)


@memory_app.command(name="list")
def memory_list(
 limit: int = typer.Option(20, "--limit", "-l", help="Max entries"),
 agent: Optional[str] = typer.Option(None, "--agent", help="Filter by agent"),
) -> None:
 """Show recent JSONL memory entries."""

 entries = _jsonl_store().recent(limit=limit)
 if agent:
  entries = [e for e in entries if e.agent == agent]
 if not entries:
  console.print("[yellow]No memory entries yet.[/yellow]")
  raise typer.Exit()

 table = Table(title=f"Memory ({len(entries)} entries)")
 table.add_column("Time", style="dim", width=19)
 table.add_column("Agent", style="cyan", width=12)
 table.add_column("Action", max_width=60)
 table.add_column("Outcome", justify="center")
 table.add_column("Tags", style="dim", max_width=30)

 for e in entries:
  style = "green" if e.outcome.lower() == "success" else (
   "red" if e.outcome.lower() == "failed" else "yellow"
  )
  table.add_row(
   e.timestamp[:19],
   (e.agent or "-")[:12],
   (e.action or "-")[:60],
   f"[{style}]{e.outcome}[/{style}]",
   ", ".join(e.tags or [])[:30],
  )

 console.print(table)


@memory_app.command(name="search")
def memory_search_cmd(
 query: str = typer.Argument(..., help="Search query (action/outcome/tags)"),
 limit: int = typer.Option(5, "--limit", "-l", help="Max results"),
) -> None:
 """Search past entries by keyword (via the conformant JSONL adapter)."""
 hits = _jsonl_adapter().search(query=query, limit=limit)
 if not hits:
  console.print(f"[yellow]No results for '{query}'.[/yellow]")
  raise typer.Exit()

 table = Table(title=f"Matches ({len(hits)}) — '{query}'")
 table.add_column("Time", style="dim", width=19)
 table.add_column("Agent", style="cyan", width=12)
 table.add_column("Action", max_width=60)
 table.add_column("Outcome", justify="center")
 table.add_column("Tags", style="dim", max_width=30)

 for h in hits:
  meta = h.metadata if isinstance(h.metadata, dict) else {}
  agent = meta.get("agent") or "-"
  tags = meta.get("tags") or []
  outcome = h.data.decode("utf-8", errors="replace") if h.data else "-"
  style = "green" if outcome.lower() == "success" else (
   "red" if outcome.lower() == "failed" else "yellow"
  )
  ts = meta.get("timestamp") or "-"
  table.add_row(
   str(ts)[:19],
   str(agent)[:12],
   (h.key or "-")[:60],
   f"[{style}]{outcome}[/{style}]",
   ", ".join(tags)[:30],
  )
 console.print(table)


@memory_app.command(name="clear")
def memory_clear_cmd(
 force: bool = typer.Option(False, "--force", help="Skip confirmation"),
) -> None:
 """Clear all JSONL memory entries (wipe .mekong/memory.jsonl)."""
 if not force:
  console.print("[red]This deletes the entire .mekong/memory.jsonl file.[/red]")
  if not Confirm.ask("Proceed?", default=False):
   console.print("[yellow]Cancelled.[/yellow]")
   raise typer.Exit()

 removed = _jsonl_store().clear()
 console.print(f"[green]Cleared {removed} entries.[/green]")


# ---------------------------------------------------------------------------
# YAML backend (goal/status/reflection schema + vector semantic search)
# ---------------------------------------------------------------------------


def _yaml_store() -> "src.core.memory_canonical.MemoryStore": # noqa: F821
 from src.core.memory_canonical import MemoryStore

 path = os.environ.get("MEKONG_MEMORY_YAML_PATH") or str(DEFAULT_YAML_PATH)
 return MemoryStore(store_path=path)


@memory_app.command(name="store")
def memory_store_cmd(
 goal: str = typer.Argument(..., help="Goal / task description"),
 status: str = typer.Option("success", "--status", help="success|failed|partial"),
 reflection: str = typer.Option("", "--reflection", help="Post-task reflection"),
 recipe: str = typer.Option("", "--recipe", help="Recipe used"),
 duration_ms: float = typer.Option(0.0, "--duration-ms", help="Duration in ms"),
) -> None:
 """Record a goal outcome to the YAML memory store."""
 from src.core.memory_canonical import MemoryEntry

 entry = MemoryEntry(
  goal=goal,
  status=status,
  duration_ms=duration_ms,
  reflection=reflection,
  recipe_used=recipe,
  context={},
 )
 _yaml_store().record(entry)
 console.print(f"[green]Stored: {goal[:50]}... [{status}][/green]")


@memory_app.command(name="recall")
def memory_recall_cmd(
 query: str = typer.Argument(..., help="Natural-language query for semantic search"),
 top_k: int = typer.Option(5, "--top-k", "-k", help="Max results"),
) -> None:
 """Semantic search the YAML memory store by goal/reflection text."""
 try:
  results = _yaml_store().semantic_search(query, top_k=top_k)
 except Exception as exc:
  console.print(f"[red]Semantic search unavailable: {exc}[/red]")
  raise typer.Exit(1)

 if not results:
  console.print(f"[yellow]No memories similar to '{query}'.[/yellow]")
  raise typer.Exit()

 from src.core.memory_canonical import MemoryEntry
 table = Table(title=f"Recalled ({len(results)}) — '{query[:40]}'")
 table.add_column("Time", style="dim", width=10)
 table.add_column("Status", justify="center")
 table.add_column("Goal", max_width=60)
 table.add_column("Recipe", max_width=20)

 for e in results:
  if not isinstance(e, MemoryEntry):
   continue
  style = "green" if e.status == "success" else (
   "red" if e.status == "failed" else "yellow"
  )
  table.add_row(
   f"{e.timestamp:.1f}",
   f"[{style}]{e.status}[/{style}]",
   (e.goal or "-")[:60],
   (e.recipe_used or "-")[:20],
  )

 console.print(table)


@memory_app.command(name="history")
def memory_history_cmd(
 goal_pattern: str = typer.Argument("", help="Filter by goal substring (optional)"),
 limit: int = typer.Option(20, "--limit", "-l", help="Max entries"),
) -> None:
 """Show recent YAML goal entries."""
 entries = _yaml_store().recent(limit=limit)
 if goal_pattern:
  entries = [e for e in entries if goal_pattern.lower() in (e.goal or "").lower()]

 if not entries:
  console.print("[yellow]No YAML memory entries found.[/yellow]")
  raise typer.Exit()

 table = Table(title=f"YAML History ({len(entries)} entries)")
 table.add_column("Time", style="dim", width=10)
 table.add_column("Status", justify="center")
 table.add_column("Recipe", max_width=20)
 table.add_column("Goal", max_width=60)

 for e in entries:
  style = "green" if e.status == "success" else (
   "red" if e.status == "failed" else "yellow"
  )
  table.add_row(
   f"{e.timestamp:.1f}",
   f"[{style}]{e.status}[/{style}]",
   (e.recipe_used or "-")[:20],
   (e.goal or "-")[:60],
  )
 console.print(table)


@memory_app.command(name="stats")
def memory_stats_cmd() -> None:
 """Memory store statistics (JSONL + YAML)."""
 j_store = _jsonl_store()
 y_store = _yaml_store()

 j_recent = j_store.recent(limit=1000)
 j_success = sum(1 for e in j_recent if e.outcome.lower() == "success")
 j_failed = sum(1 for e in j_recent if e.outcome.lower() == "failed")

 y_stats = y_store.stats() if hasattr(y_store, "stats") else {}

 panel_text = (
 f"[bold]JSONL}}[/bold]  entries (recent 1k): {len(j_recent)}  "
 f"success: {j_success}  failed: {j_failed}\n"
 f"[bold]YAML  [/bold] total: {y_stats.get('total', '?')}  "
 f"success rate: {y_stats.get('success_rate', '?')}  "
 f"collections: {y_stats.get('collections', '?')}"
 )
 console.print(Panel(panel_text, title="Memory Stats", border_style="cyan"))


@memory_app.command(name="delete")
def memory_delete_cmd(
 goal: str = typer.Argument(..., help="Goal text to delete (exact match in YAML)"),
) -> None:
 """Delete a YAML memory entry by exact goal text match."""
 store = _yaml_store()
 entries = store.recent(limit=2000)
 matches = [e for e in entries if (e.goal or "") == goal]
 if not matches:
  console.print(f"[yellow]No entry found for goal: {goal!r}[/yellow]")
  raise typer.Exit()

 if not Confirm.ask(f"Delete {len(matches)} matching entries?", default=False):
  console.print("[yellow]Cancelled.[/yellow]")
  raise typer.Exit()

 # MemoryStore.recent() returns copies; actual deletion requires store
 # internals. Use the clear + re-save approach only if collection supports it.
 console.print(
 f"[yellow]Delete not yet implemented for YAML store (found {len(matches)} matches). "
 f"Remove entry manually from .mekong/memory.yaml.[/yellow]"
 )


# ---------------------------------------------------------------------------
# C4 Learning Loop — `mekong learn`
# ---------------------------------------------------------------------------

_learn_app = typer.Typer(
    name="learn",
    help="Learning loop: inspect outcomes, patterns, and retry suggestions",
)
memory_app.add_typer(_learn_app)


@_learn_app.command(name="record")
def learn_record_cmd(
    execution_id: str = typer.Argument(..., help="Execution / workflow ID"),
    status: str = typer.Option("success", "--status", help="success|failure|retry|partial"),
    retry_count: int = typer.Option(0, "--retries", help="Number of retries performed"),
    error: str | None = typer.Option(None, "--error", help="Error message or type"),
    provider: str | None = typer.Option(None, "--provider", help="LLM / service provider"),
    command: str | None = typer.Option(None, "--command", help="Command that was executed"),
    duration_ms: float = typer.Option(0.0, "--duration-ms", help="Wall-clock ms"),
) -> None:
    """Record an execution outcome into MemoryBridge (D1).

    This is the programmatic entry point for the learning loop.  The
    executor calls it automatically when the C4 retry hooks are attached;
    operators can also call it directly for manual recordings.
    """
    from src.learning.outcome_recorder import (
        ExecutionOutcome,
        OutcomeStatus,
        OutcomeRecorder,
    )

    try:
        outcome_status = OutcomeStatus(status.lower())
    except ValueError:
        console.print(f"[red]Invalid status '{status}'. Use: success|failure|retry|partial[/red]")
        raise typer.Exit(1)

    error_type = None
    error_message = None
    if error:
        from src.learning.retry_hooks import _classify_error
        error_type = _classify_error(error)
        error_message = error

    recorder = OutcomeRecorder.get_instance()
    outcome = ExecutionOutcome(
        execution_id=execution_id,
        status=outcome_status,
        retry_count=retry_count,
        error_type=error_type,
        error_message=error_message,
        provider=provider,
        command=command,
        duration_ms=duration_ms,
    )
    record_id = recorder.record(outcome)
    console.print(f"[green]Recorded[/green] {execution_id} -> {status} (record={record_id[:12]})")


@_learn_app.command(name="patterns")
def learn_patterns_cmd(
    min_occurrences: int = typer.Option(3, "--min", help="Min times a pattern must repeat"),
    json_output: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Surface recurring failure patterns (D3).

    Groups recorded failures by (error_type, provider) and reports
    patterns that exceed the occurrence threshold.
    """
    from src.learning.retry_hooks import get_pattern_warnings

    patterns = get_pattern_warnings(min_occurrences=min_occurrences)
    if not patterns:
        console.print("[green]No failure patterns detected.[/green]")
        raise typer.Exit()

    if json_output:
        console.print_json(__import__("json").dumps(patterns, indent=2))
        return

    table = Table(title="Failure Patterns", border_style="red")
    table.add_column("Error Type", style="red")
    table.add_column("Provider", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Last Seen", style="dim")
    table.add_column("Suggested Action", max_width=50)

    for p in patterns:
        table.add_row(
            p["error_type"],
            p["provider"],
            str(p["occurrences"]),
            __import__("datetime").datetime.fromtimestamp(p["last_seen"]).strftime("%Y-%m-%d %H:%M"),
            p["suggested_action"],
        )

    console.print(table)


@_learn_app.command(name="similar")
def learn_similar_cmd(
    execution_id: str = typer.Argument(..., help="Execution ID to find similar outcomes for"),
    json_output: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Show similar past executions and their outcomes (D2)."""
    from src.learning.outcome_recorder import OutcomeRecorder

    recorder = OutcomeRecorder.get_instance()
    target = None
    for o in recorder._outcome_index:
        if o.execution_id == execution_id:
            target = o
            break

    similar = recorder.find_similar_failures(
        error_type=target.error_type if target else None,
        provider=target.provider if target else None,
        command=target.command if target else None,
        limit=10,
    )

    if not similar:
        console.print(f"[yellow]No similar past executions found for '{execution_id}'.[/yellow]")
        raise typer.Exit()

    if json_output:
        import json

        console.print_json(json.dumps([o.to_dict() for o in similar], indent=2))
        return

    table = Table(title=f"Similar to {execution_id}")
    table.add_column("Execution ID", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Retries", justify="right")
    table.add_column("Error", max_width=40)
    table.add_column("Provider")
    table.add_column("Duration (ms)", justify="right")

    for o in similar:
        style = "green" if o.status.value == "success" else "red"
        table.add_row(
            o.execution_id,
            f"[{style}]{o.status.value}[/{style}]",
            str(o.retry_count),
            (o.error_message or "-")[:40],
            o.provider or "-",
            f"{o.duration_ms:.0f}",
        )

    console.print(table)


@_learn_app.command(name="stats")
def learn_stats_cmd() -> None:
    """Show learning-loop statistics (outcomes recorded, success rate, avg retries)."""
    from src.learning.outcome_recorder import OutcomeRecorder

    stats = OutcomeRecorder.get_instance().stats()
    panel_text = (
        f"[bold]Total Outcomes:[/bold] {stats['total']}\n"
        f"[bold]Success Rate:[/bold] {stats['success_rate']}%\n"
        f"[bold]Failures:[/bold] {stats['failure_count']}\n"
        f"[bold]Avg Retries:[/bold] {stats['avg_retries']}"
    )
    console.print(Panel(panel_text, title="Learning Loop Stats", border_style="cyan"))


@_learn_app.command(name="threshold")
def learn_threshold_cmd(
    error_type: str | None = typer.Option(None, "--error-type", help="Error category"),
    provider: str | None = typer.Option(None, "--provider", help="Provider name"),
    current: int = typer.Option(3, "--current", help="Current retry max_attempts"),
    max_threshold: int = typer.Option(5, "--max", help="Maximum threshold"),
) -> None:
    """Suggest auto-tuned retry threshold (D4).

    Queries MemoryBridge for similar past failures and recommends
    a retry threshold based on average retries consumed.
    """
    from src.learning.outcome_recorder import OutcomeRecorder

    suggested = OutcomeRecorder.get_instance().suggest_retry_threshold(
        error_type=error_type,
        provider=provider,
        current_threshold=current,
        max_threshold=max_threshold,
    )
    changed = "unchanged"
    if suggested > current:
        changed = "[yellow]raise[/yellow]"
    elif suggested < current:
        changed = "[dim]lower[/dim]"
    console.print(
        f"Suggested retry threshold: [bold]{suggested}[/bold] "
        f"(current={current}, recommendation={changed})"
    )


@_learn_app.command(name="clear")
def learn_clear_cmd(
    force: bool = typer.Option(False, "--force", help="Skip confirmation"),
) -> None:
    """Clear all recorded learning outcomes."""
    if not force:
        console.print("[red]This deletes all recorded execution outcomes from MemoryBridge.[/red]")
        if not Confirm.ask("Proceed?", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit()
    from src.learning.outcome_recorder import OutcomeRecorder, _reset_singleton

    OutcomeRecorder.get_instance().clear()
    _reset_singleton()
    console.print("[green]Learning outcomes cleared.[/green]")


__all__ = ["memory_app"]
