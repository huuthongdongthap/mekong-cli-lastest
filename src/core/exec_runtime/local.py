# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Local-first execution runtime: sandboxed subprocess + filesystem primitive.

Security posture (v0.2):
- Filesystem ops are confined to ``root_dir`` (symlink-aware path resolution).
- Shell-shaped commands pass ``CommandSanitizer(strict_mode=True)`` first.
- Network policy: when ``allow_outbound=False``, commands are wrapped in a
  network-deny sandbox (``sandbox-exec`` on macOS, ``unshare -n`` on Linux).
  If the enforcement tool is unavailable, execution fails loud rather than
  running unprotected.
- Timeouts always reap the child; cancellation terminates tracked processes.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.command_sanitizer import CommandSanitizer
from src.core.exec_runtime.types import ExecResult, NetworkPolicy, SandboxSpec

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 60.0


@dataclass
class LocalFilesystem:
    """Filesystem ops facade confined to a sandbox root."""

    spec: SandboxSpec

    def read_text(self, rel_path: str) -> str:
        return self.spec.resolve_in_root(rel_path).read_text(encoding="utf-8")

    def write_text(self, rel_path: str, content: str) -> int:
        target = self.spec.resolve_in_root(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return len(content)

    def list_dir(self, rel_path: str = ".") -> list[str]:
        base = self.spec.resolve_in_root(rel_path)
        return sorted(entry.name for entry in base.iterdir())

    def delete(self, rel_path: str) -> bool:
        target = self.spec.resolve_in_root(rel_path)
        if target.is_dir():
            target.rmdir()
            return True
        target.unlink(missing_ok=True)
        return True

    def exists(self, rel_path: str) -> bool:
        return self.spec.resolve_in_root(rel_path).exists()


class LocalExecutionRuntime:
    """Concrete ExecutionRuntime running everything on this host."""

    def __init__(
        self,
        root_dir: str | Path,
        *,
        env_overrides: dict[str, str] | None = None,
        default_timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._root = Path(root_dir).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._spec = SandboxSpec(root_dir=self._root)
        self._fs = LocalFilesystem(spec=self._spec)
        self._sanitizer = CommandSanitizer(strict_mode=True)
        self._allow_outbound: bool = True
        self._sandbox_exec: str | None = self._find_sandbox_exec()
        self._env_overrides = dict(env_overrides or {})
        self._default_timeout_s = float(default_timeout_s)
        self._processes: dict[int, subprocess.Popen[Any]] = {}
        self._terminated: set[int] = set()
        self._destroyed = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # ExecutionRuntime surface
    # ------------------------------------------------------------------ #

    def execute(
        self, command: list[str] | str, *, timeout_s: float | None = None
    ) -> ExecResult:
        """Run one command. Returns an ExecResult; never raises for failure."""
        if self._destroyed:
            raise RuntimeError("LocalExecutionRuntime was destroyed")
        effective_timeout = (
            float(timeout_s) if timeout_s is not None else self._default_timeout_s
        )
        if effective_timeout <= 0:
            raise ValueError(f"timeout_s must be positive, got {timeout_s}")
        if isinstance(command, str):
            check = self._sanitizer.sanitize(command)
            if not check.is_safe:
                logger.warning(
                    "Blocked shell command: %s (%s)", command, check.blocked_reason
                )
                return ExecResult(
                    ok=False,
                    exit_code=None,
                    stdout="",
                    stderr="",
                    error=f"blocked by sanitizer: {check.blocked_reason}",
                )
            args: Any = check.sanitized_command
            use_shell = True
        else:
            if not command:
                raise ValueError("argv command must be a non-empty list of strings")
            args = [str(part) for part in command]
            use_shell = False
        # --- network enforcement: wrap command in deny-all sandbox ---
        if not self._allow_outbound:
            wrapped, wrap_err = self._wrap_for_network_deny(args, use_shell)
            if wrap_err is not None:
                return ExecResult(
                    ok=False,
                    exit_code=None,
                    stdout="",
                    stderr="",
                    error=f"network enforcement unavailable: {wrap_err}",
                )
            args = wrapped
            use_shell = False  # wrapper is always argv-style

        start = time.monotonic()
        try:
            proc = subprocess.Popen(  # noqa: S603 — argv/sanitizer validated above
                args,
                shell=use_shell,
                cwd=str(self._root),
                env=self.environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            logger.error("Failed to launch %r: %s", args, exc)
            return ExecResult(
                ok=False,
                exit_code=None,
                stdout="",
                stderr="",
                error=f"launch failed: {exc}",
            )
        with self._lock:
            self._processes[proc.pid] = proc
        try:
            out, err = proc.communicate(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            logger.warning(
                "Command timed out after %.1fs: %r", effective_timeout, args
            )
            return ExecResult(
                ok=False,
                exit_code=proc.returncode,
                stdout=out or "",
                stderr=err or "",
                duration_ms=(time.monotonic() - start) * 1000,
                timed_out=True,
                error=f"timed out after {effective_timeout:.1f}s",
            )
        finally:
            with self._lock:
                self._processes.pop(proc.pid, None)
        duration_ms = (time.monotonic() - start) * 1000
        with self._lock:
            was_cancelled = proc.pid in self._terminated
        return ExecResult(
            ok=proc.returncode == 0,
            exit_code=proc.returncode,
            stdout=out or "",
            stderr=err or "",
            duration_ms=duration_ms,
            cancelled=was_cancelled,
        )

    def filesystem(self) -> LocalFilesystem:
        return self._fs

    def process(self) -> LocalProcessControl:
        return LocalProcessControl(self)

    def network_policy(self) -> NetworkPolicy:
        if self._allow_outbound:
            return NetworkPolicy(
                allow_outbound=True,
                allowed_hosts=("*",),
                description="outbound allowed (no sandbox restriction)",
            )
        return NetworkPolicy(
            allow_outbound=False,
            allowed_hosts=(),
            description="deny-all outbound (sandbox-exec/unshare enforced)",
        )

    def set_network_policy(self, *, allow_outbound: bool) -> None:
        """Update the network enforcement policy.

        When ``allow_outbound=False`` is set, subsequent ``execute()`` calls
        are wrapped in a network-deny sandbox.  If the enforcement tool is
        unavailable, ``execute()`` returns a loud error rather than running
        unprotected.
        """
        self._allow_outbound = bool(allow_outbound)

    def environment(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self._env_overrides)
        return env

    def preview(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dry-run: report what would happen without touching the machine."""
        command = request.get("command", "")
        blocked_reason = ""
        would_execute = True
        if isinstance(command, str):
            check = self._sanitizer.sanitize(str(command))
            would_execute = check.is_safe
            blocked_reason = "" if check.is_safe else check.blocked_reason
        return {
            "command": command,
            "shell": isinstance(command, str),
            "cwd": str(self._root),
            "timeout_s": float(request.get("timeout_s", self._default_timeout_s)),
            "network_policy": self.network_policy().description,
            "would_execute": would_execute,
            "blocked_reason": blocked_reason,
        }

    def health(self) -> dict[str, Any]:
        with self._lock:
            active = sum(1 for proc in self._processes.values() if proc.poll() is None)
        return {
            "status": "destroyed" if self._destroyed else "ok",
            "root_dir": str(self._root),
            "active_processes": active,
            "network_policy": self.network_policy().description,
        }

    def destroy(self) -> dict[str, Any]:
        killed = self.process().terminate_all()
        self._destroyed = True
        return {"status": "destroyed", "terminated_processes": killed}

    # ------------------------------------------------------------------ #
    # Internals used by LocalProcessControl
    # ------------------------------------------------------------------ #

    @property
    def destroyed(self) -> bool:
        return self._destroyed

    def _snapshot_pids(self) -> list[int]:
        with self._lock:
            return [pid for pid, proc in self._processes.items() if proc.poll() is None]

    def _mark_terminated(self, pid: int) -> None:
        with self._lock:
            self._terminated.add(pid)

    # ------------------------------------------------------------------ #
    # Network enforcement internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_sandbox_exec() -> str | None:
        """Locate ``sandbox-exec`` binary if available on this host."""
        import shutil as _shutil

        path = _shutil.which("sandbox-exec")
        return path if path is not None else None

    def _wrap_for_network_deny(
        self,
        args: list[str],
        use_shell: bool,
    ) -> tuple[list[str], str | None]:
        """Wrap a command in a network-deny sandbox.

        Returns ``(wrapped_args, None)`` on success or
        ``(original_args, error_message)`` when enforcement is unavailable.
        """
        platform_name = sys.platform
        if platform_name == "darwin" and self._sandbox_exec is not None:
            profile = "(version 1)(allow default)(deny network*)"
            return [self._sandbox_exec, "-p", profile] + args, None
        if platform_name == "linux":
            unshare_path = self._find_unshare()
            if unshare_path is not None:
                return [unshare_path, "-n"] + args, None
            return args, (
                "unshare not found — cannot enforce network isolation on Linux"
            )
        return args, (
            f"sandbox-exec not available on {platform_name!r} — "
            "cannot enforce network isolation"
        )

    @staticmethod
    def _find_unshare() -> str | None:
        """Locate ``unshare`` binary if available."""
        import shutil as _shutil

        path = _shutil.which("unshare")
        return path if path is not None else None


class LocalProcessControl:
    """Process-management facade: enumerate and terminate tracked children."""

    def __init__(self, runtime: LocalExecutionRuntime) -> None:
        self._runtime = runtime

    def active_pids(self) -> list[int]:
        return self._runtime._snapshot_pids()

    def terminate(self, pid: int) -> bool:
        """SIGTERM then SIGKILL one tracked child.

        Returns True only when the child was alive and got signalled.
        """
        found = self._lookup(pid)
        if found is None or found.poll() is not None:
            return False
        self._runtime._mark_terminated(pid)
        found.terminate()
        try:
            found.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            found.kill()
            found.wait(timeout=2.0)
        return True

    def terminate_all(self) -> int:
        count = 0
        for pid in self.active_pids():
            if self.terminate(pid):
                count += 1
        return count

    def _lookup(self, pid: int) -> subprocess.Popen[Any] | None:
        with self._runtime._lock:
            return self._runtime._processes.get(pid)


__all__ = ["LocalExecutionRuntime", "LocalFilesystem", "LocalProcessControl"]
