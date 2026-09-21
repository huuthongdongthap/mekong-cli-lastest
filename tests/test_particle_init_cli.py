"""Tests for the ZenOS particle init Typer CLI command.

Verifies:
  - `mekong particle init --dry-run <name>` exits 0 and creates no files.
  - `mekong particle init <name>` scaffolds template files from mekong/skel/.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.cli.app_setup import build_app  # noqa: E402

runner = CliRunner()


@pytest.fixture()
def clean(tmp_path: Path) -> Path:
    """Empty working dir."""
    return tmp_path


class TestParticleInitCli:
    def test_particle_init_dry_run(self, clean: Path) -> None:
        """`mekong particle init --dry-run <name>` exits 0 and creates no files."""
        app = build_app()
        result = runner.invoke(
            app,
            ["particle", "init", "TestParticle", "--dry-run", "--dir", str(clean)],
        )
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        assert "[DRY RUN]" in result.stdout
        assert not (clean / "TestParticle").exists()
        written = list(clean.rglob("*"))
        assert written == [], f"dry-run must write 0 files, found: {written}"

    def test_particle_init_dry_run_lists_files(self, clean: Path) -> None:
        """Output in dry-run mode lists files that would be created."""
        app = build_app()
        result = runner.invoke(
            app,
            ["particle", "init", "PreviewParticle", "--dry-run", "--dir", str(clean)],
        )
        assert result.exit_code == 0
        assert "Files that would be created:" in result.stdout
        assert "ZENOS.md" in result.stdout or "PreviewParticle" in result.stdout

    def test_particle_init_real_creation(self, clean: Path) -> None:
        """Normal init creates the particle directory and copies files from skel."""
        app = build_app()
        result = runner.invoke(
            app,
            ["particle", "init", "RealParticle", "--dir", str(clean)],
        )
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        particle_dir = clean / "RealParticle"
        assert particle_dir.exists()
        assert particle_dir.is_dir()
        # Verify skeleton files were copied
        assert (particle_dir / "ZENOS.md").exists()
        assert (particle_dir / "workflows" / "governance.yaml").exists()
