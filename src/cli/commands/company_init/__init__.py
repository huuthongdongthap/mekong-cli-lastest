# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Company init Typer sub-app — thin app factory.

Mekong company-config init. Scaffolds business configuration into ``.mekong/``
(company.json, 8 agent prompts, mcu_balance.json, claude_company_section.md).
This is NOT AgentKit ``ak init`` — for AgentKit ownership tracking see
``/ak:init`` (or ``ak init``).

Registers three commands under ``mekong company``:

* ``init``   — 5-question wizard / ``--json`` schema / ``--dry-run`` preview (init_command.py)
* ``status`` — read ``.mekong/company.json`` Rich panel   (status_command.py)
* ``reset``  — idempotent preview / ``--force`` wipe    (reset_command.py)

Import path used by ``src/cli/app_setup.py`` and tests remains stable::

    from src.cli.commands.company_init import app

Legacy helper functions (``_get_locale``, ``_get_messages``, ``_mekong_dir``,
``_company_json_path``, ``_load_company``) are re-exported at the package level
so sibling command modules can do::

    from src.cli.commands.company_init import _load_company
"""

from __future__ import annotations

import json

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from src.cli.commands.company_init.i18n import DEFAULT_LOCALE, get_messages as _gm


# ---------------------------------------------------------------------------
# Shared helpers (re-exported for sibling modules that import from the package)
# ---------------------------------------------------------------------------

DEFAULT_LOCALE = DEFAULT_LOCALE  # noqa: F811 — shadow the i18n constant intentionally


def _get_locale(locale_opt: str) -> str:  # pragma: no cover — thin wrapper
    return locale_opt if locale_opt in ("en", "vi") else DEFAULT_LOCALE


def _get_messages(locale: str) -> dict[str, str]:
    return _gm(_get_locale(locale))


def _mekong_dir(base_dir: "Path") -> "Path":  # type: ignore[valid-type]
    return base_dir / ".mekong"


def _company_json_path(base_dir: "Path") -> "Path":  # type: ignore[valid-type]
    return _mekong_dir(base_dir) / "company.json"


def _load_company(base_dir: "Path") -> Optional[dict]:  # type: ignore[valid-type]
    p = _company_json_path(base_dir)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# App wiring
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="company",
    help="Company / workspace configuration",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)

console = Console()

# Delayed imports avoid a top-level circular dependency between the sub-modules
# and this package. They still live in the same package so the public import
# path ``from src.cli.commands.company_init import app`` is fully preserved.

from src.cli.commands.company_init import (  # noqa: E402 — must come after app
    init_command,
    reset_command,
    status_command,
)

init_command.register(app)
status_command.register(app)
reset_command.register(app)
