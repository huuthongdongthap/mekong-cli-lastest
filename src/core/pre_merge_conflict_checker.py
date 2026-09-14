# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Mekong CLI - Pre-Merge Conflict Checker.

Wraps `git merge-tree` to detect conflicts before a final merge,
reducing integration failures in worktree-based parallel agent workflows.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ConflictFile:
    path: str
    conflict_type: str  # "content", "add/add", "modify/delete", etc.


@dataclass
class MergeCheckResult:
    has_conflicts: bool
    conflicting_files: list[ConflictFile]
    source_branch: str
    target_branch: str
    checked_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_git(args: list[str], repo_path: str | None) -> subprocess.CompletedProcess:
    # Pin the locale: CONFLICT line parsing below matches English wording only.
    env = {**os.environ, "LC_ALL": "C"}
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True, text=True, timeout=30, cwd=repo_path, env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("git command timed out") from exc


def _assert_git_repo(repo_path: str | None) -> None:
    result = _run_git(["rev-parse", "--git-dir"], repo_path)
    if result.returncode != 0:
        raise RuntimeError(
            f"Not a git repository: {repo_path or '(current directory)'}"
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_merge_base(branch_a: str, branch_b: str, repo_path: str | None = None) -> str:
    """Return the merge-base commit SHA for two branches.

    Raises RuntimeError if git unavailable, not a repo, or no common ancestor.
    """
    _assert_git_repo(repo_path)
    result = _run_git(["merge-base", branch_a, branch_b], repo_path)
    if result.returncode != 0:
        raise RuntimeError(
            f"Cannot find merge base for '{branch_a}' and '{branch_b}': "
            f"{result.stderr.strip()}"
        )
    return result.stdout.strip()


def check_merge_conflicts(
    source_branch: str,
    target_branch: str,
    repo_path: str | None = None,
) -> MergeCheckResult:
    """Dry-run merge source into target via ``git merge-tree --write-tree``.

    Returns a MergeCheckResult. Raises RuntimeError if git unavailable or not a repo.
    """
    _assert_git_repo(repo_path)
    logger.debug("merge-tree check: source=%s target=%s", source_branch, target_branch)

    # Modern two-branch form: exit code 1 = conflicts; CONFLICT lines in stdout.
    result = _run_git(
        ["merge-tree", "--write-tree", source_branch, target_branch], repo_path
    )
    has_conflicts = result.returncode != 0

    seen: set[str] = set()
    conflicting_files: list[ConflictFile] = []
    for line in (result.stdout + result.stderr).splitlines():
        line = line.strip()
        if not line.startswith("CONFLICT ("):
            continue
        conflict_type = line[line.index("(") + 1 : line.index(")")]
        file_path = line.rsplit(" in ", 1)[-1].strip() if " in " in line else ""
        if file_path and file_path not in seen:
            seen.add(file_path)
            conflicting_files.append(ConflictFile(path=file_path, conflict_type=conflict_type))
            logger.info("Conflict: %s (%s)", file_path, conflict_type)

    return MergeCheckResult(
        has_conflicts=has_conflicts,
        conflicting_files=conflicting_files,
        source_branch=source_branch,
        target_branch=target_branch,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_HINTS: dict[str, str] = {
    "content": "Manually edit conflict markers (<<<<<<< / ======= / >>>>>>>).",
    "add/add": "Both branches added the file; pick one version or merge manually.",
    "modify/delete": "One branch deleted the file; decide whether to keep or remove it.",
    "rename/rename": "Rename conflict; choose a canonical name and update all references.",
    "rename/delete": "One branch renamed, the other deleted; align on the final state.",
}


def format_conflict_report(result: MergeCheckResult) -> str:
    """Return a human-readable pre-merge conflict report."""
    status = "CONFLICTS FOUND" if result.has_conflicts else "Clean — no conflicts"
    lines = [
        "Pre-Merge Conflict Report",
        "=" * 40,
        f"Source  : {result.source_branch}",
        f"Target  : {result.target_branch}",
        f"Status  : {status}",
    ]
    if result.conflicting_files:
        lines.append(f"Conflicts: {len(result.conflicting_files)} file(s)\n")
        for cf in result.conflicting_files:
            hint = _HINTS.get(cf.conflict_type, "Resolve manually.")
            lines += [f"  [{cf.conflict_type}] {cf.path}", f"    → {hint}"]
    else:
        lines.append("\nNo conflicting files detected.")
    return "\n".join(lines)
