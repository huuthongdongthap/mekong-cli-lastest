# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Register the ``mekong company init`` command.

Responsibility: interactive wizard, ``--json`` schema output, ``--no-confirm``
shortcut, and the success Rich panel. Common helpers (``_get_locale``,
``_get_messages``, ``_mekong_dir``, ``_company_json_path``, ``_load_company``)
live in the parent package's ``__init__`` and are borrowed via the
``company_init`` sub-module import so that :func:`reset_cmd` (in
``reset_command.py``) and :func:`status_cmd` (in ``status_command.py``) can
share them without duplication.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from src.cli.commands.company_init import i18n as i18n_mod
from src.cli.commands.company_init import (  # noqa: F401  (re-export helper)
    _company_json_path,
    _load_company,
    _mekong_dir,
    _get_locale,
    _get_messages,
)
from src.core.company_init import (
    BUDGET_MAP,
    LANGUAGE_MAP,
    PRODUCT_MAP,
    SCENARIO_MAP,
    CompanyConfig,
    init_company,
)

console = Console()


def _run_wizard(  # noqa: C901  (wizard complexity is inherent)
    locale: str,
    output_dir: str | Path,
    *,
    assume_yes: bool,
) -> dict:
    """Run the 5-question wizard and call :func:`init_company`.

    Returns the init_company summary dict. Raises :class:`typer.Exit` on
    user abort (Ctrl-C) or failed validation; re-raises any backend error
    when ``MEKONG_DEBUG`` is set.
    """
    messages = _get_messages(locale)
    os.chdir(output_dir)

    console.print(f"\n[bold green]{messages['welcome']}[/]\n")

    # Q1 — company name (required, no sensible default)
    company_name = (
        typer.prompt(
            f"[bold cyan]{messages['q1_name']}[/]",
            default="",
            show_default=False,
        )
        .strip()
    )
    if not company_name:
        console.print("[red]Company name is required.[/]")
        raise typer.Exit(code=1)

    # Q2 — product type
    console.print(f"\n[bold]{messages['q2_header']}[/]")
    for k, v in PRODUCT_MAP.items():
        console.print(f" {k}. {v}")
    product_choice = typer.prompt(messages["q2_prompt"], type=int)
    product_type = PRODUCT_MAP.get(str(product_choice))
    if product_type is None:
        console.print("[red]Invalid choice.[/]")
        raise typer.Exit(code=1)

    # Q3 — scenario
    console.print(f"\n[bold]{messages['q3_header']}[/]")
    for k, v in SCENARIO_MAP.items():
        console.print(f" {k}. {v}")
    scenario_choice = typer.prompt(messages["q3_prompt"], type=int)
    scenario = SCENARIO_MAP.get(str(scenario_choice))
    if scenario is None:
        console.print("[red]Invalid choice.[/]")
        raise typer.Exit(code=1)

    # Q4 — budget tier
    console.print(f"\n[bold]{messages['q4_header']}[/]")
    for k, v in BUDGET_MAP.items():
        console.print(f" {k}. {v}")
    budget_choice = typer.prompt(messages["q4_prompt"], type=int)
    budget_tier = BUDGET_MAP.get(str(budget_choice))
    if budget_tier is None:
        console.print("[red]Invalid choice.[/]")
        raise typer.Exit(code=1)

    # Q5 — language
    console.print(f"\n[bold]{messages['q5_header']}[/]")
    for k, v in LANGUAGE_MAP.items():
        console.print(f" {k}. {v}")
    lang_choice = typer.prompt(messages["q5_prompt"], type=int)
    primary_language = LANGUAGE_MAP.get(str(lang_choice))
    if primary_language is None:
        console.print("[red]Invalid choice.[/]")
        raise typer.Exit(code=1)

    cfg = CompanyConfig(
        company_name=company_name,
        product_type=product_type,
        scenario=scenario,
        budget_tier=budget_tier,
        primary_language=primary_language,
    )

    if not assume_yes:
        console.print()
        console.print(
            f"[bold yellow]{messages['confirm']}[/]\n"
            f" Name: [cyan]{cfg.company_name}[/]\n"
            f" Product: [cyan]{cfg.product_type}[/]\n"
            f" Scenario: [cyan]{cfg.scenario}[/]\n"
            f" Budget: [cyan]{cfg.budget_tier}[/]\n"
            f" Language: [cyan]{cfg.primary_language}[/]\n"
        )
        confirmed = Confirm.ask("[bold]Continue?[/]", default=True)
        if not confirmed:
            console.print("[yellow]Aborted.[/]")
            raise typer.Exit(code=1)

    return init_company(cfg, base_dir=output_dir)


def register(app: typer.Typer) -> None:
    """Wire ``init_cmd`` into *app*."""

    @app.command("init")
    def init_cmd(  # noqa: C901
        ctx: typer.Context,  # noqa: ARG001  (reserved for future completion)
        output_dir=typer.Option(
            ".",
            "--dir",
            "-d",
            exists=False,
            file_okay=False,
            dir_okay=True,
            help="Project root to write into (default: CWD).",
        ),
        force: bool = typer.Option(
            False,
            "--force",
            help="Re-init even if .mekong/company.json already exists.",
        ),
        json_schema: bool = typer.Option(
            False,
            "--json",
            help="Print the 5-question wizard schema and exit.",
        ),
        no_confirm: bool = typer.Option(
            False,
            "--no-confirm",
            "--yes",
            "--assume-yes",
            help="Skip the interactive confirmation.",
        ),
        locale: str = typer.Option(
            "en",
            "--locale",
            help="Bilingual prompt language: en | vi.",
        ),
    ) -> None:
        """Set up the current workspace (.mekong/ + 12 config files)."""
        path = Path(output_dir).resolve()

        # --json schema mode (no I/O, no files written)
        if json_schema:
            schema = [
                {
                    "field": "company_name",
                    "question": i18n_mod.get_messages("en")["q1_name"],
                    "mapper": PRODUCT_MAP,
                },
                {
                    "field": "product_type",
                    "question": i18n_mod.get_messages("en")["q2_prompt"],
                    "mapper": PRODUCT_MAP,
                },
                {
                    "field": "scenario",
                    "question": i18n_mod.get_messages("en")["q3_prompt"],
                    "mapper": SCENARIO_MAP,
                },
                {
                    "field": "budget_tier",
                    "question": i18n_mod.get_messages("en")["q4_prompt"],
                    "mapper": BUDGET_MAP,
                },
                {
                    "field": "primary_language",
                    "question": i18n_mod.get_messages("en")["q5_prompt"],
                    "mapper": LANGUAGE_MAP,
                },
            ]
            typer.echo(json.dumps({"questions": schema}, indent=2))
            raise typer.Exit(code=0)

        company_json = _company_json_path(path)
        if company_json.exists() and not force:
            messages = _get_messages(locale)
            console.print(
                f"[bold red]Already initialized[/] — "
                f"{messages['already_setup']}"
            )
            raise typer.Exit(code=1)

        try:
            result = _run_wizard(
                locale,
                output_dir=path,
                assume_yes=no_confirm,
            )
        except typer.Exit:
            raise
        except Exception as exc:  # noqa: BLE001
            console.print(
                f"[red]{i18n_mod.get_messages(locale)['error']}:[/] {exc}"
            )
            if os.environ.get("MEKONG_DEBUG"):
                raise
            raise typer.Exit(code=1) from exc

        company_name = result.get("company_name", "?")
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("key", style="cyan", no_wrap=True)
        table.add_column("value", style="green")
        table.add_row("company", company_name)
        table.add_row("scenario", result.get("scenario", "?"))
        table.add_row("budget", result.get("budget_tier", "?"))
        table.add_row("lang", result.get("primary_language", "?"))
        table.add_row("files", str(result.get("files_created", 0)))
        table.add_row("mcu_seeded", str(result.get("mcu_seeded", 0)))
        table.add_row("cost_estimate", result.get("cost_estimate", "?"))

        panel = Panel(
            table,
            title=f"[bold green]✓ Company Initialized — {company_name}[/]",
            border_style="green",
            expand=False,
        )
        console.print(panel)
