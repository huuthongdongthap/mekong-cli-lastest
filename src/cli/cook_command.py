# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Cook command: Plan -> Execute -> Verify (PEV) workflow."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

import typer
from engine.billing.tier_config import Tier
from engine.license.license_enforcer import require_tier
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


from src.mekongcli.core.goal_engine import GoalEngine, GoalStatus, SQLiteGoalStore
from src.mekongcli.core.verification import VerificationPipeline

console = Console()


def _goal_engine(db_path: str | None = None) -> GoalEngine:
    store = SQLiteGoalStore(db_path) if db_path else SQLiteGoalStore()
    return GoalEngine(store=store, cwd=Path.cwd())


def _print_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


def _validate_profile(profile: str) -> None:
    try:
        VerificationPipeline.validate_profile(profile)
    except ValueError as exc:
        raise typer.BadParameter(
            f"must be one of: {VerificationPipeline.profile_options()}",
            param_hint="--profile",
        ) from exc


def _cook_auto_payload(
    completed: GoalStatus,
    goal_id: str,
    title: str,
    profile: str,
    snapshot: dict[str, Any],
    db_path: str | None = None,
    auto: bool = False,
) -> dict[str, Any]:
    verification = snapshot.get("verification") or {}
    verification_results = verification.get("results") or []
    failed_gates = [
        result["name"]
        for result in verification_results
        if result.get("required") and not result.get("passed")
    ]
    db_option = f" --db {shlex.quote(db_path)}" if db_path else ""
    return {
        "id": goal_id,
        "status": completed.value,
        "title": title,
        "profile": profile,
        "auto": auto,
        "tasks_total": len(snapshot.get("tasks", [])),
        "tasks_completed": len(
            [t for t in snapshot.get("tasks", []) if t.get("status") == "completed"]
        ),
        "verification_runs": 1 if verification else 0,
        "verification_passed": verification.get("passed"),
        "failed_gates": failed_gates,
        "status_command": f"mekong goal status {goal_id}{db_option}",
        "resume_command": f"mekong goal resume {goal_id} --profile {profile}{db_option}",
        "verify_command": f"mekong goal verify {goal_id} --profile {profile}{db_option}",
        "status_json_command": f"mekong goal status {goal_id}{db_option} --json",
        "resume_json_command": f"mekong goal resume {goal_id} --profile {profile}{db_option} --json",
        "verify_json_command": f"mekong goal verify {goal_id} --profile {profile}{db_option} --json",
    }


def _cook_auto_panel_body(payload: dict[str, Any]) -> str:
    lines = [
        f"[bold]ID:[/bold] {payload['id']}",
        f"[bold]Status:[/bold] {payload['status']}",
        f"[bold]Verification Profile:[/bold] {payload['profile']}",
        f"[bold]Tasks:[/bold] {payload['tasks_completed']}/{payload['tasks_total']}",
    ]
    if payload.get("verification_passed") is not None:
        lines.append(f"[bold]Verification Passed:[/bold] {payload['verification_passed']}")
    if payload.get("failed_gates"):
        lines.append(f"[bold red]Failed Gates:[/bold red] {', '.join(payload['failed_gates'])}")
    lines.append(f"[bold]Status Command:[/bold] {payload['status_command']}")
    lines.append(f"[bold]Resume Command:[/bold] {payload['resume_command']}")
    lines.append(f"[bold]Verify Command:[/bold] {payload['verify_command']}")
    lines.append(f"[bold]Status JSON:[/bold] {payload['status_json_command']}")
    lines.append(f"[bold]Resume JSON:[/bold] {payload['resume_json_command']}")
    lines.append(f"[bold]Verify JSON:[/bold] {payload['verify_json_command']}")
    return "\n".join(lines)


def register_cook_command(app: typer.Typer) -> None:
    """Register the cook command onto the typer app."""

    @require_tier(Tier.FREE)
    @app.command(name="cook-auto")
    def cook_auto(
        goal: list[str] = typer.Argument(
            ...,
            help="High-level goal to execute autonomously",
        ),
        profile: str = typer.Option(
            "smoke",
            "--profile",
            help="Verification profile: standard|smoke|none",
        ),
        execute_commands: bool = typer.Option(
            False,
            "--execute-commands",
            help="Run task commands when present",
        ),
        auto: bool = typer.Option(
            False,
            "--auto",
            help="Accept AGY auto mode",
        ),
        timeout_seconds: float | None = typer.Option(
            None,
            "--timeout",
            help="Max seconds before cancelling goal execution",
        ),
        db_path: str | None = typer.Option(
            None,
            "--db",
            help="Override goal database path",
        ),
        json_output: bool = typer.Option(
            False,
            "--json",
            "-j",
            help="Machine-readable JSON output",
        ),
    ) -> None:
        """Create, run, checkpoint, and verify a durable autonomous goal."""
        _validate_profile(profile)
        goal_title = " ".join(goal).strip()
        if not goal_title:
            raise typer.BadParameter("goal cannot be empty", param_hint="GOAL")
        engine = _goal_engine(db_path)
        created = engine.create_goal(goal_title)
        completed = engine.run_goal(
            created.id,
            verification_profile=profile,
            execute_commands=execute_commands,
            timeout_seconds=timeout_seconds,
        )
        snapshot = engine.status(created.id)
        payload = _cook_auto_payload(
            completed.status,
            completed.id,
            completed.title,
            profile,
            snapshot,
            db_path,
            auto,
        )

        if json_output:
            _print_json(payload)
        else:
            style = "green" if completed.status == GoalStatus.SATISFIED else "red"
            console.print(
                Panel(
                    _cook_auto_panel_body(payload),
                    title="Cook Auto Complete",
                    border_style=style,
                )
            )

        if completed.status != GoalStatus.SATISFIED:
            raise typer.Exit(code=1)

    @require_tier(Tier.FREE)
    @app.command(name="cook-auto-parallel")
    def cook_auto_parallel(
        goal: list[str] = typer.Argument(
            ...,
            help="High-level goal to execute autonomously in parallel",
        ),
        profile: str = typer.Option(
            "smoke",
            "--profile",
            help="Verification profile: standard|smoke|none",
        ),
        execute_commands: bool = typer.Option(
            False,
            "--execute-commands",
            help="Run task commands when present",
        ),
        auto: bool = typer.Option(
            False,
            "--auto",
            help="Accept AGY auto mode",
        ),
        db_path: str | None = typer.Option(
            None,
            "--db",
            help="Override goal database path",
        ),
        json_output: bool = typer.Option(
            False,
            "--json",
            "-j",
            help="Machine-readable JSON output",
        ),
        max_workers: int = typer.Option(
            3,
            "--workers",
            help="Max parallel execution threads",
        ),
        timeout_seconds: float | None = typer.Option(
            None,
            "--timeout",
            help="Max seconds before cancelling goal execution",
        ),
    ) -> None:
        """Create, run in parallel, checkpoint, and verify a durable autonomous goal."""
        _validate_profile(profile)
        if max_workers <= 0:
            raise typer.BadParameter("workers must be a positive integer", param_hint="--workers")
        goal_title = " ".join(goal).strip()
        if not goal_title:
            raise typer.BadParameter("goal cannot be empty", param_hint="GOAL")
        engine = _goal_engine(db_path)
        created = engine.create_goal(goal_title)
        completed = engine.run_goal_parallel(
            created.id,
            verification_profile=profile,
            execute_commands=execute_commands,
            max_workers=max_workers,
            timeout_seconds=timeout_seconds,
        )
        snapshot = engine.status(created.id)
        payload = _cook_auto_payload(
            completed.status,
            completed.id,
            completed.title,
            profile,
            snapshot,
            db_path,
            auto,
        )

        if json_output:
            _print_json(payload)
        else:
            style = "green" if completed.status == GoalStatus.SATISFIED else "red"
            console.print(
                Panel(
                    _cook_auto_panel_body(payload),
                    title="Cook Auto Parallel Complete",
                    border_style=style,
                )
            )

        if completed.status != GoalStatus.SATISFIED:
            raise typer.Exit(code=1)

    @require_tier(Tier.FREE)
    @app.command()
    def cook(
        goal: str = typer.Argument(..., help="High-level goal to plan, execute, and verify"),
        strict: bool = typer.Option(True, help="Strict verification mode"),
        no_rollback: bool = typer.Option(False, help="Disable rollback on failure"),
        verbose: bool = typer.Option(False, "--verbose", "-v", help="Show step-by-step output"),
        dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Plan only, no execution"),
        json_output: bool = typer.Option(False, "--json", "-j", help="Machine-readable JSON output"),
        agi_dash: bool = typer.Option(False, "--agi-dash", help="Show AGI dashboard after execution"),
    ) -> None:
        """Cook: Plan -> Execute -> Verify workflow.

        Lane E8: this command now drives the canonical ``MekongCoreRuntimeImpl``
        lifecycle (Goal -> Plan -> Delegate -> Execute -> Observe -> Verify ->
        Repair -> Remember -> Commit) instead of the legacy Binh Phap
        ``RecipeOrchestrator`` engine. The old engine is kept as a legacy
        consumer (see ``src/core/orchestrator.py``) -- it is NOT deleted.

        CLI surface is preserved byte-for-byte: every argument, option and
        help string above is unchanged. ``--dry-run`` now calls
        ``runtime.plan()`` directly instead of ``RecipePlanner``.
        """
        from src.cli.agi_dashboard import show_agi_dashboard
        from src.core.mission_tracer import MissionTracer

        if dry_run:
            from src.commands.run import _build_runtime

            runtime = _build_runtime()
            from src.core.runtime_adapter import Context

            planned_goal = runtime.goal(
                goal,
                Context(principal="cli", session_id="dry-run"),
            )
            plan_result = runtime.plan(planned_goal)
            plan_table = Table(title="Steps (not executed)")
            plan_table.add_column("#", style="bold cyan", justify="right")
            plan_table.add_column("Task", style="bold")
            plan_table.add_column("Description", style="dim")
            plan_table.add_column("Deps", style="dim")
            for i, step in enumerate(plan_result.steps):
                deps = ", ".join(step.dependencies) if step.dependencies else "-"
                plan_table.add_row(str(i + 1), step.id, step.description[:80], deps)
            console.print(
                Panel(
                    f"[bold]{goal}[/bold]",
                    title="Dry Run - Plan Only",
                    border_style="yellow",
                )
            )
            console.print(plan_table)
            console.print(
                f"\n[yellow]Dry run complete - no steps executed. "
                f"Plan status: {'ok' if plan_result.status else 'blocked'}[/yellow]"
            )
            return

        from src.commands.run import _build_runtime

        runtime = _build_runtime()
        tracer = MissionTracer()
        runtime.start_mission(goal, tracer=tracer)

        if verbose:
            console.print(
                Panel(
                    f"[bold]Goal:[/bold] {goal}\n"
                    f"[bold]Strict:[/bold] {strict}\n"
                    f"[bold]Rollback:[/bold] {not no_rollback}\n"
                    f"[bold]Engine:[/bold] canonical MekongCoreRuntimeImpl",
                    title="Cook Configuration",
                    border_style="dim",
                )
            )

        result = runtime.run(goal)

        if json_output:
            mission_record = None
            if tracer._missions:
                mission_record = list(tracer._missions.values())[0]
            output = {
                "status": "success" if result.error is None else "failed",
                "goal": goal,
                "task_id": result.task_id,
                "output": result.output,
                "error": result.error,
                "metadata": result.metadata,
                "stages": [s["stage"] for s in tracer.stages],
                "steps": len(mission_record.steps) if mission_record else 0,
            }
            console.print(json.dumps(output, indent=2, default=str))

        if result.error is not None:
            if verbose:
                console.print(
                    Panel(
                        f"- {result.error}",
                        title="Errors",
                        border_style="red",
                    )
                )
            raise typer.Exit(code=1)

        if verbose:
            console.print("\n[bold green]Mission accomplished![/bold green]")

        if agi_dash or verbose:
            show_agi_dashboard(goal, result)
