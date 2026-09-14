# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""
src/cli/sdlc/deploy.py — `mekong deploy` sub-app.

Commands:
  mekong deploy <feature>   Load TASKS.todo, scaffold DEPLOY_REPORT.md,
                            print tester agent prompt with gate check results.

The agent (tester) reads CLAUDE.deploy.md + TASKS.todo, verifies CI gates
via `gh run list`, then fills in .mekong/DEPLOY_REPORT.md.

Gate verification delegated to src/cli/sdlc/gate_check.py.
"""

from __future__ import annotations

import typer
from rich.console import Console

from src.cli.sdlc.agent_dispatch import (
    load_prior_output,
    print_agent_instructions,
    resolve_context,
    scaffold_output,
)
from src.cli.sdlc.gate_check import check_ci_gates, suggest_design_audit
from src.commands.deploy import (
    rollback as deploy_rollback_cmd,
    run as deploy_run_cmd,
    status as deploy_status_cmd,
)

deploy_app = typer.Typer(
    name="deploy",
    help="Deploy phase: verify CI gates and emit ship/hold report.",
    add_completion=False,
)

# Mount platform deployment commands from src/commands/deploy.py
deploy_app.command("run")(deploy_run_cmd)
deploy_app.command("status")(deploy_status_cmd)
deploy_app.command("rollback")(deploy_rollback_cmd)

console = Console()

_PHASE = "deploy"
_AGENT = "tester"
_CONTRACT = "CLAUDE.deploy.md"
_PRIOR_OUTPUT = "TASKS.todo"
_TEMPLATE = "DEPLOY_OUTPUT.template.md"
_OUTPUT = "DEPLOY_REPORT.md"


@deploy_app.command("new")
def deploy_cmd(
    feature: str = typer.Argument(..., help="Feature slug, e.g. auth-mfa"),
    skip_gate_check: bool = typer.Option(
        False,
        "--skip-gate-check",
        help="Skip CI gate check (solo hotfix fast-path — use with caution)",
    ),
    skip_prior_check: bool = typer.Option(
        False,
        "--skip-prior-check",
        help="Skip check for TASKS.todo (solo fast-path)",
    ),
    overwrite: bool = typer.Option(
        True,
        "--overwrite/--no-overwrite",
        help="Overwrite existing DEPLOY_REPORT.md (default: yes — idempotent)",
    ),
    design_audit: bool = typer.Option(
        False,
        "--design-audit",
        help="Opt-in: suggest `mekong ui audit` when the diff touches UI surface",
    ),
) -> None:
    """
    Start the deploy phase for <feature>.

    Checks CI gates (g1-validation through merge-gate from gates.yml),
    loads TASKS.todo, scaffolds DEPLOY_REPORT.md, prints tester agent prompt.
    """
    mekong_root, out_dir, phases_dir = resolve_context(feature)

    contract_path = phases_dir / _CONTRACT
    if not contract_path.exists():
        console.print(
            f"[red]Contract not found:[/red] {contract_path}\n"
            "Ensure .mekong/phases/CLAUDE.deploy.md exists."
        )
        raise typer.Exit(code=1)

    # Gate verification — blocks on red, warns on unavailable
    if not skip_gate_check:
        console.print("[bold]Checking CI gates (.github/workflows/gates.yml)...[/bold]")
        gates_green = check_ci_gates()
        if not gates_green:
            console.print(
                "\n[red bold]HOLD:[/red bold] CI gates are not green. "
                "Fix failing gates before deploying.\n"
                "Use [cyan]--skip-gate-check[/cyan] only for solo hotfixes."
            )
            raise typer.Exit(code=1)
        console.print("[green]Gates:[/green] check passed\n")
    else:
        console.print("[yellow]Gate check skipped (--skip-gate-check)[/yellow]")

    # Opt-in design gate — advisory only, never blocks the deploy.
    if design_audit:
        suggest_design_audit()

    prior_content = load_prior_output(
        filename=_PRIOR_OUTPUT,
        feature=feature,
        mekong_root=mekong_root,
        required=not skip_prior_check,
    )
    if prior_content:
        console.print(f"[green]Loaded:[/green] {out_dir / _PRIOR_OUTPUT}")

    out_path = scaffold_output(
        template_name=_TEMPLATE,
        output_filename=_OUTPUT,
        feature=feature,
        mekong_root=mekong_root,
        overwrite=overwrite,
    )
    console.print(f"[green]Scaffolded:[/green] {out_path}")

    print_agent_instructions(
        phase=_PHASE,
        feature=feature,
        contract_path=contract_path,
        output_path=out_path,
        agent_name=_AGENT,
        prior_output_path=out_dir / _PRIOR_OUTPUT if prior_content else None,
    )

    console.print(
        "[dim]Post-deploy:[/dim] Run "
        f"[bold cyan]mekong eval-agent {feature} --days 1[/bold cyan] "
        "after 24h to verify success rate."
    )
    console.print(
        "[dim]Dashboard:[/dim] Run "
        "[bold cyan]mekong metrics[/bold cyan] to check live signal counts."
    )
