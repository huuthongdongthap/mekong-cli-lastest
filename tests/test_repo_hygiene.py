# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Repo-hygiene regression tests (gitignore vs tracked sources).

Root cause guarded here: the blanket ``build/`` rule in .gitignore used to
swallow the ``src/cli/commands/build/`` SOURCE directory, so fresh clones and
git worktrees were missing the CLI build command modules — breaking test
collection and ``build_app()``. The .gitignore now carries explicit
exceptions; this test pins them so the files can never silently disappear
from the index again.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SOURCES = "src/cli/commands/build"


def _tracked_files(path: str) -> list[str]:
    """Return git-tracked file paths under `path` (repo-root-relative)."""
    result = subprocess.run(
        ["git", "ls-files", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"git ls-files failed: {result.stderr}"
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_cli_build_sources_are_tracked():
    """The `mekong build` command sources must exist in the git index."""
    tracked = _tracked_files(BUILD_SOURCES)
    assert len(tracked) >= 2, (
        f"Expected at least 2 tracked files under {BUILD_SOURCES}, got {tracked}. "
        "The .gitignore 'build/' rule is swallowing the source directory again."
    )


def test_cli_build_source_files_present_in_index():
    """Both known source modules are individually tracked."""
    tracked = set(_tracked_files(BUILD_SOURCES))
    for required in (f"{BUILD_SOURCES}/__init__.py", f"{BUILD_SOURCES}/i18n.py"):
        assert required in tracked, f"{required} missing from git index"
