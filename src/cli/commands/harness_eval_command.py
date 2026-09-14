# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Root-level ``harness-eval`` command for the CEO Solo harness contract.

Runs the deterministic harness evals from ``src/harness/evals/solo_ceo.py``.
CI invokes it exactly as::

    python3 -m src.main harness-eval --json

Exit code is 0 only when every eval passes, otherwise 1.

Bilingual Vietnamese + English output.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console

console = Console()


def _run_harness_eval(json_output: bool) -> None:
    """Run harness evals and exit 0 iff every eval passes."""
    from src.harness.evals.solo_ceo import run_solo_ceo_harness_evals

    payload = run_solo_ceo_harness_evals()
    passed_count = int(payload["passed_count"])
    total = int(payload["total"])
    all_passed = passed_count == total

    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for result in payload["results"]:
            icon = "[green]✓[/green]" if result["passed"] else "[red]✗[/red]"
            console.print(f"  {icon} {result['id']} {result['name']}")
            if not result["passed"] and result["failure"]:
                console.print(f"      [dim]{result['failure']}[/dim]")
        summary = (
            "[bold green]ALL EVALS PASSED / TẤT CẢ EVAL ĐỀU ĐẠT[/bold green]"
            if all_passed
            else "[bold red]EVALS FAILED / EVAL THẤT BẠI[/bold red]"
        )
        console.print(f"\n{summary}  {passed_count}/{total}")

    raise typer.Exit(code=0 if all_passed else 1)


def register_harness_eval_command(app: typer.Typer) -> None:
    """Register the flat ``harness-eval`` command on the root app."""

    @app.command(name="harness-eval")
    def harness_eval(
        json_output: bool = typer.Option(
            False,
            "--json",
            help="In kết quả dạng JSON / Print eval result as JSON.",
        ),
    ) -> None:
        """Chạy bộ eval harness / Run deterministic harness evals."""
        _run_harness_eval(json_output)


__all__ = ["register_harness_eval_command"]
