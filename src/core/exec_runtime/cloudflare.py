# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Cloudflare execution runtime: remote adapter behind an injected transport.

Security posture (v0.3):
- Filesystem ops are confined to ``root_dir`` via ``SandboxSpec.resolve_in_root``
  (same primitive as LocalExecutionRuntime — no second confinement path).
- Shell-shaped commands pass ``CommandSanitizer(strict_mode=True)`` first —
  the exact same sanitization path as LocalExecutionRuntime.
- Network enforcement is transport-level: the injected ``CloudflareTransport``
  controls all outbound traffic.  When ``allow_outbound=False``, dispatch is
  blocked before reaching the transport.
- Hermetic by construction: every remote call goes through the injected
  ``CloudflareTransport``. No transport is ever constructed implicitly, so
  this module can never reach the real Cloudflare API on its own.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from src.core.command_sanitizer import CommandSanitizer
from src.core.exec_runtime.local import LocalFilesystem
from src.core.exec_runtime.types import ExecResult, NetworkPolicy, SandboxSpec

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 60.0


class CloudflareTransport(Protocol):
    """Injected transport for remote execution calls.

    Implementations own the wire protocol (HTTP, RPC, in-memory fake).
    ``dispatch`` must return a JSON-shaped dict and must raise
    ``TimeoutError`` when the remote side exceeds its deadline.
    """

    def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class WorkerConfig:
    """Spec-to-worker translation: what the remote worker receives."""

    account_id: str
    script_name: str
    command: list[str]
    shell: bool
    cwd: str
    env: dict[str, str]
    timeout_s: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "script_name": self.script_name,
            "command": list(self.command),
            "shell": self.shell,
            "cwd": self.cwd,
            "env": dict(self.env),
            "timeout_s": self.timeout_s,
        }


class CloudflareExecutionRuntime:
    """Concrete ExecutionRuntime dispatching commands to a Cloudflare worker.

    The filesystem facade stays local and sandbox-confined (the worker is
    stateless; artifacts live in the local sandbox root). All remote traffic
    flows through the injected transport — zero implicit network.
    """

    def __init__(
        self,
        root_dir: str | Path,
        *,
        account_id: str,
        script_name: str,
        transport: CloudflareTransport,
        env_overrides: dict[str, str] | None = None,
        default_timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        if not account_id:
            raise ValueError("account_id must be a non-empty string")
        if not script_name:
            raise ValueError("script_name must be a non-empty string")
        self._root = Path(root_dir).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._spec = SandboxSpec(root_dir=self._root)
        self._fs = LocalFilesystem(spec=self._spec)
        self._sanitizer = CommandSanitizer(strict_mode=True)
        self._allow_outbound: bool = True
        self._account_id = account_id
        self._script_name = script_name
        self._transport = transport
        self._env_overrides = dict(env_overrides or {})
        self._default_timeout_s = float(default_timeout_s)
        self._dispatches = 0
        self._destroyed = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # ExecutionRuntime surface
    # ------------------------------------------------------------------ #

    def execute(
        self, command: list[str] | str, *, timeout_s: float | None = None
    ) -> ExecResult:
        """Dispatch one command to the worker. Never raises for failure."""
        if self._destroyed:
            raise RuntimeError("CloudflareExecutionRuntime was destroyed")
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
            shell_command = str(check.sanitized_command)
            shell = True
        else:
            if not command:
                raise ValueError("argv command must be a non-empty list of strings")
            shell_command = ""
            shell = False
        config = self._build_config(command, shell, shell_command, effective_timeout)
        # --- transport-level network enforcement ---
        if not self._allow_outbound:
            return ExecResult(
                ok=False,
                exit_code=None,
                stdout="",
                stderr="",
                error="network policy denies outbound transport dispatch",
            )
        start = time.monotonic()
        try:
            response = self._transport.dispatch(config.to_payload())
        except TimeoutError as exc:
            logger.warning(
                "Remote command timed out after %.1fs: %r",
                effective_timeout,
                config.command,
            )
            return ExecResult(
                ok=False,
                exit_code=None,
                stdout="",
                stderr="",
                duration_ms=(time.monotonic() - start) * 1000,
                timed_out=True,
                error=f"timed out after {effective_timeout:.1f}s: {exc}",
            )
        except Exception as exc:  # transport failure is a result, not a raise
            logger.error("Transport dispatch failed: %s", exc)
            return ExecResult(
                ok=False,
                exit_code=None,
                stdout="",
                stderr="",
                duration_ms=(time.monotonic() - start) * 1000,
                error=f"transport error: {exc}",
            )
        with self._lock:
            self._dispatches += 1
        duration_ms = (time.monotonic() - start) * 1000
        if not isinstance(response, dict):
            return ExecResult(
                ok=False,
                exit_code=None,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
                error=f"malformed transport response: {type(response).__name__}",
            )
        exit_code = response.get("exit_code")
        if not isinstance(exit_code, int):
            return ExecResult(
                ok=False,
                exit_code=None,
                stdout="",
                stderr="",
                duration_ms=duration_ms,
                error="malformed transport response: exit_code missing or not int",
            )
        return ExecResult(
            ok=exit_code == 0,
            exit_code=exit_code,
            stdout=str(response.get("stdout", "")),
            stderr=str(response.get("stderr", "")),
            duration_ms=duration_ms,
        )

    def filesystem(self) -> LocalFilesystem:
        return self._fs

    def process(self) -> CloudflareProcessControl:
        return CloudflareProcessControl(self)

    def network_policy(self) -> NetworkPolicy:
        if self._allow_outbound:
            return NetworkPolicy(
                allow_outbound=True,
                allowed_hosts=("*",),
                description="outbound allowed (transport controls access)",
            )
        return NetworkPolicy(
            allow_outbound=False,
            allowed_hosts=(),
            description="deny-all outbound (transport dispatch blocked)",
        )

    def set_network_policy(self, *, allow_outbound: bool) -> None:
        """Update the network enforcement policy.

        When ``allow_outbound=False``, ``execute()`` refuses to dispatch
        through the transport, returning a loud error result instead.
        """
        self._allow_outbound = bool(allow_outbound)

    def environment(self) -> dict[str, str]:
        """Minimal remote env: overrides only, never the host environment."""
        return dict(self._env_overrides)

    def preview(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dry-run: report what would be dispatched without touching the transport."""
        command = request.get("command", "")
        blocked_reason = ""
        would_execute = True
        if isinstance(command, str):
            check = self._sanitizer.sanitize(str(command))
            would_execute = check.is_safe
            blocked_reason = "" if check.is_safe else check.blocked_reason
        timeout_s = float(request.get("timeout_s", self._default_timeout_s))
        return {
            "command": command,
            "shell": isinstance(command, str),
            "cwd": str(self._root),
            "timeout_s": timeout_s,
            "account_id": self._account_id,
            "script_name": self._script_name,
            "network_policy": self.network_policy().description,
            "would_execute": would_execute,
            "blocked_reason": blocked_reason,
        }

    def health(self) -> dict[str, Any]:
        with self._lock:
            dispatches = self._dispatches
        return {
            "status": "destroyed" if self._destroyed else "ok",
            "runtime": "cloudflare",
            "account_id": self._account_id,
            "script_name": self._script_name,
            "root_dir": str(self._root),
            "dispatches": dispatches,
            "network_policy": self.network_policy().description,
        }

    def destroy(self) -> dict[str, Any]:
        self._destroyed = True
        return {"status": "destroyed", "terminated_processes": 0}

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @property
    def destroyed(self) -> bool:
        return self._destroyed

    def _build_config(
        self,
        command: list[str] | str,
        shell: bool,
        shell_command: str,
        timeout_s: float,
    ) -> WorkerConfig:
        """Translate a command + sandbox spec into the worker payload spec."""
        if shell:
            mapped: list[str] = ["/bin/sh", "-c", shell_command]
        else:
            mapped = [str(part) for part in command]
        return WorkerConfig(
            account_id=self._account_id,
            script_name=self._script_name,
            command=mapped,
            shell=shell,
            cwd=str(self._root),
            env=self.environment(),
            timeout_s=timeout_s,
        )


class CloudflareProcessControl:
    """Process facade for the remote runtime.

    The worker is stateless and each dispatch is synchronous, so no child
    processes are tracked locally; terminate is a no-op that reports False.
    """

    def __init__(self, runtime: CloudflareExecutionRuntime) -> None:
        self._runtime = runtime

    def active_pids(self) -> list[int]:
        return []

    def terminate(self, pid: int) -> bool:
        return False

    def terminate_all(self) -> int:
        return 0


__all__ = [
    "CloudflareExecutionRuntime",
    "CloudflareProcessControl",
    "CloudflareTransport",
    "WorkerConfig",
]
