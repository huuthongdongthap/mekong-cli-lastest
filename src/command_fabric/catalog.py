# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Neutral command catalog for global IDE/CLI adapters.

The command fabric reads existing command source files instead of duplicating
their definitions. Adapters can export this catalog to shells, IDEs, MCP, SDKs,
and agent runtimes without maintaining separate command lists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from src.command_fabric.records import (
    CommandRecord,
    command_record_from_markdown as parse_command_record,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMMANDS_DIR = PROJECT_ROOT / ".claude" / "commands"
INTEGRATION_COMMANDS_DIR = PROJECT_ROOT / ".claude" / "_integration" / "commands"
DEFAULT_USER_COMMANDS_DIR = Path.home() / ".claude" / "commands"
DEFAULT_CONTRACTS_DIR = PROJECT_ROOT / "factory" / "contracts" / "commands"


def _resolve_commands_dir(commands_dir: Path) -> Path:
    if commands_dir == DEFAULT_COMMANDS_DIR and not commands_dir.exists() and INTEGRATION_COMMANDS_DIR.exists():
        return INTEGRATION_COMMANDS_DIR
    return commands_dir


def command_record_from_markdown(path: Path, root: Path = PROJECT_ROOT) -> CommandRecord:
    """Create a command record from one `.claude/commands/*.md` file."""
    return parse_command_record(path, root=root, contracts_dir=DEFAULT_CONTRACTS_DIR)


def build_command_catalog(
    commands_dir: Path = DEFAULT_COMMANDS_DIR,
    root: Path = PROJECT_ROOT,
) -> list[CommandRecord]:
    """Build the sorted command fabric catalog from source command files."""
    actual_dir = _resolve_commands_dir(commands_dir)
    records = [
        command_record_from_markdown(path, root=root)
        for path in sorted(actual_dir.glob("*.md"))
        if path.is_file()
    ]
    return sorted(records, key=lambda record: record.name)


def _readable_command_records(commands_dir: Path, root: Path) -> list[CommandRecord]:
    """Return readable command records from one command directory."""
    actual_dir = _resolve_commands_dir(commands_dir)
    if not actual_dir.exists():
        return []

    records: list[CommandRecord] = []
    for path in sorted(commands_dir.glob("*.md")):
        try:
            records.append(command_record_from_markdown(path, root=root))
        except OSError:
            continue
        except UnicodeDecodeError:
            continue
    return records


def build_global_command_catalog(
    commands_dirs: Sequence[Path] | None = None,
    root: Path = PROJECT_ROOT,
) -> list[CommandRecord]:
    """Build a merged project + user command catalog for non-slash runtimes.

    Project commands win name conflicts so `mekong` behavior remains canonical,
    while user-level ClaudeKit commands are still visible to wrappers, APIs,
    IDEs, and agent CLIs that cannot rely on Claude Code's slash-command UI.
    """
    dirs = list(commands_dirs) if commands_dirs is not None else [
        DEFAULT_COMMANDS_DIR,
        DEFAULT_USER_COMMANDS_DIR,
    ]
    by_name: dict[str, CommandRecord] = {}
    for commands_dir in dirs:
        for record in _readable_command_records(commands_dir, root):
            by_name.setdefault(record.name, record)
    return sorted(by_name.values(), key=lambda record: record.name)


def export_command_catalog(
    records: list[CommandRecord] | None = None,
    source: str = ".claude/commands + ~/.claude/commands",
) -> dict[str, Any]:
    """Export command catalog as a stable machine-readable payload."""
    command_records = records if records is not None else build_global_command_catalog()
    return {
        "schema": "mekong.command_fabric.v1",
        "version": "2026.06.03",
        "source": source,
        "count": len(command_records),
        "commands": [record.to_dict() for record in command_records],
    }


__all__ = [
    "CommandRecord",
    "build_command_catalog",
    "build_global_command_catalog",
    "command_record_from_markdown",
    "export_command_catalog",
]
