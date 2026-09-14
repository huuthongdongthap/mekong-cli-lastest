"""Tests for root CLI command-surface manifest."""

from __future__ import annotations

import json
from pathlib import Path

from src.core.command_surface import (
    CommandSurfaceManifest,
    current_root_commands,
    validate_command_surface,
)


def test_default_command_surface_matches_root_cli() -> None:
    validation = validate_command_surface()

    assert validation.valid is True
    assert validation.current_count == validation.manifest_count
    assert validation.current_count >= 50
    assert validation.missing_from_manifest == []
    assert validation.stale_in_manifest == []


def test_command_surface_reports_missing_command(tmp_path: Path) -> None:
    current = sorted(current_root_commands())
    data = {
        "schema": "mekong.command_surface.v1",
        "version": "test",
        "description": "test",
        "commands": current[:-1],
    }
    path = tmp_path / "command-surface.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    validation = validate_command_surface(CommandSurfaceManifest.load(path))

    assert validation.valid is False
    assert validation.missing_from_manifest == [current[-1]]
