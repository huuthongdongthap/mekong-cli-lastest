# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""SDD Phase 3: Implement runner -- `mekong implement run <feature>`.

Wraps the goal engine (goal create + goal run --auto) with spec context
injected into goal metadata. Does NOT duplicate goal logic -- delegates
to existing goal_commands.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from src.cli.sdlc.agent_dispatch import _mekong_root

console = Console()

implement_app = typer.Typer(
    name="implement",
    help="SDD: execute implementation from task list",
    no_args_is_help=True,
    add_completion=False,
)


def _find_spec_dir(specs_base: Path, slug: str) -> Optional[Path]:
    """Find the spec directory matching *slug* under *specs_base/*."""
    if not specs_base.is_dir():
        return None
    for entry in sorted(specs_base.iterdir()):
        if not entry.is_dir():
            continue
        parts = entry.name.split("-", 1)
        if len(parts) == 2 and slug in parts[1]:
            return entry
    return None


def _find_goal_id_by_title(title: str) -> Optional[str]:
    """Search goal DB for a goal matching *title*, return its ID if found."""
    # Call `mekong goal list --json` and match
    try:
        result = subprocess.run(
            [sys.executable, "-m", "src.main", "goal", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(Path.cwd()),
        )
        if result.returncode != 0:
            return None
        goals = json.loads(result.stdout or "[]")
        for g in goals:
            if title.lower() in g.get("title", "").lower():
                return g["id"]
    except Exception:
        pass
    return None


@implement_app.command("run")
def implement_run(
    feature_slug: str = typer.Argument(
        ..., help="Feature slug, e.g. add-auth"
    ),
    spec_dir: Path = typer.Option(
        Path("specs"),
        "--spec-dir",
        "-d",
        help="Base directory containing NNN-<slug> spec dirs.",
    ),
    agent_name: str = typer.Option(
        "fullstack-developer",
        "--agent",
        help="Agent to dispatch for implementation.",
    ),
    auto: bool = typer.Option(
        True,
        "--auto/--no-auto",
        help="Auto-execute: create goal and run immediately (default: --auto).",
    ),
) -> None:
    """Execute implementation for a feature using prior task context.

    Finds the spec directory and its tasks.md, then:
      1. Creates a goal titled with the feature slug + spec dir
      2. Injects spec context into goal metadata
      3. Runs the goal engine (delegates to existing `mekong goal run --auto`)

    Does NOT duplicate goal logic -- wraps the existing goal engine.
    """
    resolved = spec_dir.resolve()
    spec_section = _find_spec_dir(resolved, feature_slug)
    if spec_section is None:
        console.print(
            f"[red]No spec directory found for slug '{feature_slug}' "
            f"under {resolved}[/red]"
        )
        raise typer.Exit(code=1)

    spec_path = spec_section / "spec.md"
    tasks_path = spec_section / "tasks.md"

    missing: list[str] = []
    if not spec_path.exists():
        missing.append(str(spec_path))
    if not tasks_path.exists():
        missing.append(str(tasks_path))
    if missing:
        console.print(
            "[red]Missing prerequisite files:[/red]\n"
            + "\n".join(f"  - {m}" for m in missing)
        )
        console.print(
            f"Hint: run [cyan]mekong specify run <desc>[/cyan] "
            f"then [cyan]mekong tasks run {feature_slug}[/cyan] first."
        )
        raise typer.Exit(code=1)

    spec_content = spec_path.read_text(encoding="utf-8")
    tasks_content = tasks_path.read_text(encoding="utf-8")

    goal_title = f"SDD: implement {feature_slug} -- {spec_section.name}"

    if auto:
        console.print("[cyan]Creating goal...[/cyan]")

        # Step 1: Create the goal via goal engine wrapper
        goal_id = _create_goal(goal_title)
        if goal_id is None:
            # Fallback: try to find existing goal with matching title
            goal_id = _find_goal_id_by_title(goal_title)
            if goal_id:
                console.print(
                    f"[yellow]Reusing existing goal: {goal_id}[/yellow]"
                )

        if goal_id is None:
            console.print(
                "[red]Failed to create or find goal. "
                "Run `mekong goal create '<title>'` manually.[/red]"
            )
            raise typer.Exit(code=1)

        console.print(f"[green]Goal created: {goal_id}[/green]")

        # Step 2: Inject spec context into goal metadata
        _inject_spec_context(goal_id, spec_path, tasks_path, spec_content, tasks_content)

        # Step 3: Delegate to goal run --auto (no duplication of goal logic)
        console.print(
            f"[cyan]Running goal with {agent_name} agent...[/cyan]"
            f"\n[dim]Context: spec={spec_path.name}, "
            f"tasks={tasks_path.name}[/dim]"
        )

        # Read the tasks file and present TDD-ordered summary
        console.print("[bold yellow]Task Order (TDD):[/bold yellow]")
        _preview_tasks(tasks_content)

        console.print(
            "\n[bold cyan]Delegating to goal engine...[/bold cyan]"
            f"\nGoal ID: {goal_id}"
        )

        # Delegate to the goal engine via subprocess (no import coupling)
        _run_goal_engine(goal_id)
    else:
        # Print agent instructions for manual invocation
        _print_agent_instructions(
            feature_slug, spec_path, tasks_path, agent_name
        )


def _create_goal(title: str) -> Optional[str]:
    """Create a goal via the goal engine, return goal ID."""
    try:
        from src.mekongcli.core.goal_engine import GoalEngine, SQLiteGoalStore

        store = SQLiteGoalStore()
        engine = GoalEngine(store=store, cwd=Path.cwd())
        goal = engine.create_goal(title)
        return goal.id
    except Exception as exc:
        console.print(
            f"[yellow]Could not create goal directly: {exc}[/yellow]\n"
            "[dim]Falling back to subprocess invocation.[/dim]"
        )
        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "src.main",
                    "goal", "create", title,
                ],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(Path.cwd()),
            )
            if result.returncode == 0:
                # Parse ID from output
                for line in result.stdout.splitlines():
                    if line.startswith("ID:"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
    return None


def _inject_spec_context(
    goal_id: str,
    spec_path: Path,
    tasks_path: Path,
    spec_content: str,
    tasks_content: str,
) -> None:
    """Inject spec and tasks content into goal metadata.

    Stores context in the goal's memory/context slot so the agent
    executing the goal has full spec-kit context available.
    """
    # Write context to a sidecar file the goal engine can surface
    mekong_root = _mekong_root()
    context_dir = mekong_root / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    context_file = context_dir / f"{goal_id}.json"

    context = {
        "goal_id": goal_id,
        "feature_slug": spec_path.parent.name.split("-", 1)[-1],
        "spec_path": str(spec_path.relative_to(Path.cwd())),
        "tasks_path": str(tasks_path.relative_to(Path.cwd())),
        "spec_full_text": spec_content,
        "tasks_full_text": tasks_content,
    }
    context_file.write_text(
        json.dumps(context, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    console.print(
        f"[dim]Spec context written: {context_file}[/dim]"
    )


def _run_goal_engine(goal_id: str) -> None:
    """Delegate to `mekong goal run --auto <id>` -- no goal logic duplication."""
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "src.main",
                "goal", "run", goal_id,
                "--auto",
                "--profile", "standard",
            ],
            cwd=str(Path.cwd()),
        )
        if result.returncode != 0:
            console.print(
                f"[red]Goal run exited with code {result.returncode}[/red]"
            )
            raise typer.Exit(code=result.returncode)
    except FileNotFoundError:
        console.print(
            "[red]Could not invoke goal engine. "
            "Run [cyan]mekong goal run <id> --auto[/cyan] manually.[/red]"
        )
        raise typer.Exit(code=1)


def _preview_tasks(tasks_content: str) -> None:
    """Print a condensed TDD task preview from tasks.md content."""
    lines = tasks_content.splitlines()
    in_section: Optional[str] = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            in_section = stripped.lstrip("# ").strip()
            continue
        if stripped.startswith("- [ ]") and in_section:
            console.print(f"  {stripped}")


def _print_agent_instructions(
    feature_slug: str,
    spec_path: Path,
    tasks_path: Path,
    agent_name: str,
) -> None:
    """Print agent instructions for manual implementation (no auto mode)."""
    output_path = Path(f".mekong/features/{feature_slug}/IMPLEMENT.md")
    console.print(
        Panel(
            f"[bold]Feature:[/bold] {feature_slug}\n"
            f"[bold]Spec:[/bold] {spec_path}\n"
            f"[bold]Tasks:[/bold] {tasks_path}\n"
            f"[bold]Agent:[/bold] {agent_name}",
            title="[bold cyan]Implement Instructions[/]",
            border_style="cyan",
            expand=False,
        )
    )
    console.print(
        "\n[bold yellow]--- Agent Prompt (copy to agent session) ---[/bold yellow]"
    )
    console.print(
        f"You are the {agent_name} agent implementing {feature_slug}.\n\n"
        f"1. Read the spec: {spec_path}\n"
        f"2. Read the task list: {tasks_path}\n"
        f"3. Execute tasks in TDD order (tests first, then impl, then integration)\n"
        f"4. Write implementation output to: {output_path}\n\n"
        f"Follow all instructions in the spec and task list. "
        f"Execute [P] (parallel-safe) tasks concurrently where possible."
    )
    console.print("[bold yellow]--- End Prompt ---[/bold yellow]\n")
