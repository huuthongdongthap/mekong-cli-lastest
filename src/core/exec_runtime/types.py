# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Execution-runtime primitives: result types, sandbox, and the Protocol.

Kept dependency-free (stdlib only) so both local and future remote runtimes
can import it without pulling execution machinery.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ExecResult:
    """Outcome of one command execution. Never raises for process failure."""

    ok: bool
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: float = 0.0
    timed_out: bool = False
    cancelled: bool = False
    error: str | None = None


@dataclass(frozen=True)
class NetworkPolicy:
    """Network policy struct with deny-all default.

    Enforcement varies by runtime:
    - Local: best-effort OS-level enforcement (sandbox-exec/unshare) when allow_outbound=False
    - Docker: --network none (deny-all) or bridge (allow_outbound)
    - Cloudflare: transport-level gating (injected transport controls outbound)
    """

    allow_outbound: bool = False
    allowed_hosts: tuple[str, ...] = ()
    description: str = "deny-all outbound (enforced per runtime)"


@dataclass
class SandboxSpec:
    """Filesystem confinement spec: every path op must resolve inside root."""

    root_dir: Path

    def resolve_in_root(self, rel_path: str) -> Path:
        """Resolve ``rel_path`` under the sandbox root, rejecting escapes.

        Raises ``PermissionError`` when the resolved path lands outside the
        root (symlink traversal included) or is absolute pointing outside.
        """
        if os.path.isabs(rel_path):
            candidate = Path(rel_path)
        else:
            candidate = self.root_dir / rel_path
        resolved = candidate.resolve()
        root_resolved = self.root_dir.resolve()
        if resolved != root_resolved and root_resolved not in resolved.parents:
            raise PermissionError(
                f"path escapes sandbox root: {rel_path!r} -> {resolved}"
            )
        return resolved


@runtime_checkable
class ExecutionRuntime(Protocol):
    """Structural contract for execution runtimes (local first, remote later).

    Implementations own subprocess/filesystem/network/environment concerns;
    callers stay runtime-agnostic.
    """

    def execute(self, command: list[str] | str, *, timeout_s: float | None = None) -> ExecResult: ...

    def filesystem(self) -> Any:
        """Return the filesystem operations facade (sandboxed)."""
        ...

    def process(self) -> Any:
        """Return process-management facade (list/terminate tracked procs)."""
        ...

    def network_policy(self) -> NetworkPolicy:
        """Return the effective network policy."""
        ...

    def environment(self) -> dict[str, str]:
        """Return the sanitized environment dict handed to child processes."""
        ...

    def preview(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dry-run a request: describe what would happen without doing it."""
        ...

    def health(self) -> dict[str, Any]:
        """Report runtime health."""
        ...

    def destroy(self) -> dict[str, Any]:
        """Terminate all tracked processes and release resources."""
        ...


__all__ = ["ExecResult", "NetworkPolicy", "SandboxSpec", "ExecutionRuntime"]
