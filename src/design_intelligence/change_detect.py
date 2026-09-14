# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Change detection for the design-intelligence gate hook.

Classifies a set of changed file paths so the SDLC deploy gate can suggest
`mekong ui audit` only when user-visible surface area actually changed.
Backend-only, migration-only, CLI-only, and infra-only diffs are skipped so
the hook never adds noise to pure-backend deploys.

Pure path classification — no git dependency in the classifier itself; the
git helper is a thin wrapper so tests can drive the logic with plain lists.
"""

from __future__ import annotations

import re
import subprocess
from enum import Enum

# User-visible surface: markup, styles, and the directories that hold them.
_FRONTEND_RE = re.compile(
    r"(?:"
    r"\.(?:html?|jsx|tsx|css|scss|svelte|vue)$"
    r"|/(?:pages|layouts|routes|components|views|app)/"
    r"|/(?:styles|themes)/"
    r"|(?:^|/)tailwind\.config\."
    r"|(?:^|/)tokens\.(?:css|json|ya?ml)$"
    r"|(?:^|/)design\.tokens\."
    r")",
    re.IGNORECASE,
)

# Pure backend / infra surface — never user-visible on its own.
_BACKEND_RE = re.compile(
    r"(?:"
    r"\.(?:py|go|rs|java|rb|php)$"
    r"|/migrations?/"
    r"|/(?:cli|commands|core|services|api|middleware|seed|tree|forest|land)/"
    r"|(?:^|/)(?:Dockerfile|docker-compose|\.github/|terraform/|infra/)"
    r"|(?:^|/)(?:Makefile|pyproject\.toml|requirements.*\.txt|package\.json)$"
    r")",
    re.IGNORECASE,
)


class ChangeClass(str, Enum):
    """What kind of surface a diff touches."""

    FRONTEND = "frontend"          # at least one user-visible file
    BACKEND_ONLY = "backend-only"  # only backend/infra/CLI files
    EMPTY = "empty"                # no changed files


def classify(paths: list[str]) -> ChangeClass:
    """Classify a list of changed file paths.

    Any frontend hit wins over backend hits — a diff touching both a .py
    handler and a .tsx page still changes the user-visible surface.
    """
    if not paths:
        return ChangeClass.EMPTY
    has_frontend = any(_FRONTEND_RE.search(p) for p in paths)
    if has_frontend:
        return ChangeClass.FRONTEND
    has_backend = any(_BACKEND_RE.search(p) for p in paths)
    return ChangeClass.BACKEND_ONLY if has_backend else ChangeClass.EMPTY


def should_trigger_design_audit(paths: list[str]) -> bool:
    """True when the diff touches user-visible surface area."""
    return classify(paths) is ChangeClass.FRONTEND


def changed_files(base: str = "HEAD") -> list[str]:
    """List files changed vs `base` (working tree + staged) via git.

    Returns an empty list when git is unavailable or the repo has no
    commits — callers must treat that as "nothing to audit", never an error.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
