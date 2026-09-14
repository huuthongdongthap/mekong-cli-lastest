# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""
src/cli/sdlc/gate_check.py — CI gate verification for the deploy phase.

Queries GitHub Actions for the latest gates.yml run and prints a summary table.
Gate job IDs match .github/workflows/gates.yml exactly:
  g1-validation, g2-security, g3-quality, g4-dep-audit, g5-deploy-ready, merge-gate

Returns True if latest run conclusion == "success", False otherwise.
Non-blocking (returns True) when gh CLI is unavailable — solo fast-path.
"""

from __future__ import annotations

import json
import re
import subprocess

from rich.console import Console
from rich.table import Table

from src.design_intelligence.change_detect import (
    changed_files,
    should_trigger_design_audit,
)

console = Console()


def suggest_design_audit(base: str = "HEAD") -> bool:
    """Opt-in hook: suggest `mekong ui audit` when the diff touches UI surface.

    Returns True only when changed files include user-visible surface
    (html/jsx/tsx/css/tailwind/pages/layouts/routes/tokens). Backend-only,
    migration-only, CLI-only, and infra-only diffs return False so the hook
    never adds noise to pure-backend deploys.
    """
    paths = changed_files(base)
    if not should_trigger_design_audit(paths):
        return False
    console.print(
        "[cyan]Design gate:[/cyan] diff touches user-visible surface — "
        "run [bold cyan]mekong ui audit <file>[/bold cyan] before shipping."
    )
    return True


def _detect_repo() -> str | None:
    """Infer owner/repo from git remote origin URL — handles https + ssh."""
    try:
        url = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
    except Exception:
        return None
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None

# Ordered gate list — job IDs from .github/workflows/gates.yml
GATES = [
    ("g1-validation", "G1 Validation"),
    ("g2-security", "G2 Security"),
    ("g3-quality", "G3 Quality"),
    ("g4-dep-audit", "G4 Dep Audit"),
    ("g5-deploy-ready", "G5 Deploy Ready"),
    ("merge-gate", "Merge Gate"),
]


def check_ci_gates() -> bool:
    """
    Query the latest gates.yml run via gh CLI.

    Returns:
        True if conclusion is "success" or gh is unavailable (non-blocking).
        False if conclusion is "failure" or "cancelled".
    """
    cmd = [
        "gh", "run", "list", "-L", "1",
        "--workflow=gates.yml",
        "--json", "status,conclusion,url",
    ]
    repo = _detect_repo()
    if repo:
        cmd.extend(["--repo", repo])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
        )
    except FileNotFoundError:
        console.print(
            "[yellow]Warning:[/yellow] gh CLI not found. "
            "Install with: brew install gh\n"
            "Skipping gate check — verify CI manually before shipping."
        )
        return True
    except subprocess.TimeoutExpired:
        console.print("[yellow]Warning:[/yellow] gh CLI timed out. Skipping gate check.")
        return True

    if result.returncode != 0 or not result.stdout.strip():
        console.print(
            "[yellow]Warning:[/yellow] Could not query GitHub Actions "
            "(no runs found or not authenticated). Skipping gate check."
        )
        return True

    try:
        runs = json.loads(result.stdout)
    except json.JSONDecodeError:
        console.print("[yellow]Warning:[/yellow] Unexpected gh output — skipping gate check.")
        return True

    if not runs:
        console.print("[dim]No gates.yml runs found — skipping gate check.[/dim]")
        return True

    run = runs[0]
    status = run.get("status", "unknown")
    conclusion = run.get("conclusion") or "in_progress"
    url = run.get("url", "")

    _print_gate_table(status, conclusion)
    if url:
        console.print(f"[dim]Run URL: {url}[/dim]")

    return conclusion == "success"


def _print_gate_table(status: str, conclusion: str) -> None:
    """Print a Rich table summarising all gates with the run-level conclusion."""
    conclusion_color = (
        "green" if conclusion == "success"
        else "red" if conclusion in ("failure", "cancelled")
        else "yellow"
    )
    table = Table(show_header=True, header_style="bold magenta", box=None)
    table.add_column("Gate", style="bold", min_width=20)
    table.add_column("Workflow Status", min_width=16)
    table.add_column("Conclusion", min_width=12)
    for _job_id, gate_name in GATES:
        table.add_row(
            gate_name,
            status,
            f"[{conclusion_color}]{conclusion}[/{conclusion_color}]",
        )
    console.print(table)
