# Tests for Wave 2: Masked Broken Import Fixes
# Verifies real import behavior — no mocks, no patches.

from __future__ import annotations

import importlib
import pathlib

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
AGI_SOURCE = _REPO_ROOT / "src" / "commands" / "agi.py"


# ── Step A: command_fabric/router.py import path fix ──────────────────────


class TestCommandFabricRouterImport:
    """Verify src.command_fabric.router is importable and re-exports expected symbols."""

    def test_module_importable(self) -> None:
        mod = importlib.import_module("src.command_fabric.router")
        assert mod is not None

    def test_route_table_symbols_available(self) -> None:
        from src.command_fabric.router import (
            CommandMatch,
            RouteEntry,
            get_all_commands,
            get_route_table,
            route_command,
        )

        assert callable(route_command)
        assert callable(get_all_commands)
        assert callable(get_route_table)
        # RouteEntry and CommandMatch should be dataclasses or classes
        assert isinstance(CommandMatch, type)
        assert isinstance(RouteEntry, type)


# ── Step B: implement/__init__.py import target fix ───────────────────────


class TestImplementGoalEngineImport:
    """Verify SQLiteGoalStore comes from the canonical goal_engine module."""

    def test_implement_module_importable(self) -> None:
        mod = importlib.import_module("src.cli.commands.implement")
        assert mod is not None

    def test_sqlite_goal_store_canonical_source(self) -> None:
        from src.mekongcli.core.goal_engine import SQLiteGoalStore
        from src.mekongcli.core.goal_engine.store import (
            SQLiteGoalStore as CanonicalStore,
        )

        assert SQLiteGoalStore is CanonicalStore
        assert isinstance(SQLiteGoalStore, type)


# ── Step C: agi_bridge.py start() fail-loud ───────────────────────────────


class TestAgiBridgeFailLoud:
    """Verify AGIBridge.start() raises FileNotFoundError for missing entry script."""

    def test_missing_entry_raises_filenotfound(self, tmp_path: pathlib.Path) -> None:
        from src.agents.agi_bridge import AGIBridge

        bridge = AGIBridge(mekong_dir=str(tmp_path))
        with pytest.raises(FileNotFoundError):
            bridge.start()

    def test_error_message_names_missing_script(self, tmp_path: pathlib.Path) -> None:
        from src.agents.agi_bridge import AGIBridge

        bridge = AGIBridge(mekong_dir=str(tmp_path))
        with pytest.raises(FileNotFoundError, match="task-watcher.js"):
            bridge.start()

    def test_consumer_source_handles_filenotfound(self) -> None:
        """Verify agi.py consumer source catches FileNotFoundError and exits.

        This is a source-level contract check — not a runtime test — to avoid
        needing a real daemon process.
        """
        source = AGI_SOURCE.read_text(encoding="utf-8")
        # Consumer must catch FileNotFoundError from bridge.start()
        assert "except FileNotFoundError" in source
        # Consumer must exit with code 1 on failure
        assert "typer.Exit(code=1)" in source
