# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Docker execution runtime: container-backed adapter via the docker CLI.

Security posture (v0.2):
- Filesystem ops are confined to ``root_dir`` via ``SandboxSpec.resolve_in_root``
  (same primitive as LocalExecutionRuntime — no second confinement path).
- Shell-shaped commands pass ``CommandSanitizer(strict_mode=True)`` first —
  the exact same sanitization path as LocalExecutionRuntime.
- Network policy maps to ``--network none`` by default (deny-all); an
  allow-outbound policy maps to the default bridge network.
- Hermetic unit path: command construction, spec-to-container translation,
  and error handling run without a daemon. The only daemon touchpoint is
  the ``docker info`` probe in ``health()``, which callers/tests gate with
  skip-if-no-daemon.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
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
_DAEMON_PROBE_TIMEOUT_S = 5.0


class DockerRunner(Protocol):
    """Injected runner for docker CLI invocations.

    Mirrors ``subprocess.run`` semantics for the subset this runtime uses.
    Defaults to the real CLI runner; tests inject a fake to stay hermetic.
    """

    def run(
        self,
        args: list[str],
        *,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


class CliDockerRunner:
    """Default runner: real docker CLI via subprocess (never used in tests)."""

    def run(
        self,
        args: list[str],
        *,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 — args built from validated argv, no shell
            args,
            timeout=timeout,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


@dataclass(frozen=True)
class ContainerConfig:
    """Spec-to-container translation: what ``docker run`` receives."""

    image: str
    command: list[str]
    shell: bool
    workdir: str
    env: dict[str, str]
    network: str
    timeout_s: float

    def to_run_args(self) -> list[str]:
        """Build the full ``docker run`` argv for this config."""
        args = [
            "docker",
            "run",
            "--rm",
            "--workdir",
            self.workdir,
            "--network",
            self.network,
        ]
        for key, value in sorted(self.env.items()):
            args.extend(["--env", f"{key}={value}"])
        args.append(self.image)
        args.extend(self.command)
        return args


class DockerExecutionRuntime:
    """Concrete ExecutionRuntime running commands inside one-shot containers."""

    def __init__(
        self,
        root_dir: str | Path,
        *,
        image: str,
        runner: DockerRunner | None = None,
        env_overrides: dict[str, str] | None = None,
        allow_outbound: bool = False,
        default_timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        if not image:
            raise ValueError("image must be a non-empty string")
        self._root = Path(root_dir).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._spec = SandboxSpec(root_dir=self._root)
        self._fs = LocalFilesystem(spec=self._spec)
        self._sanitizer = CommandSanitizer(strict_mode=True)
        self._network_policy = NetworkPolicy(
            allow_outbound=allow_outbound,
            description=(
                "bridge network (outbound allowed)"
                if allow_outbound
                else "deny-all outbound (--network none)"
            ),
        )
        self._image = image
        self._runner: DockerRunner = runner or CliDockerRunner()
        self._env_overrides = dict(env_overrides or {})
        self._default_timeout_s = float(default_timeout_s)
        self._runs = 0
        self._destroyed = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # ExecutionRuntime surface
    # ------------------------------------------------------------------ #

    def execute(
        self, command: list[str] | str, *, timeout_s: float | None = None
    ) -> ExecResult:
        """Run one command in a container. Never raises for failure."""
        if self._destroyed:
            raise RuntimeError("DockerExecutionRuntime was destroyed")
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
        args = config.to_run_args()
        start = time.monotonic()
        try:
            completed = self._runner.run(
                args,
                timeout=effective_timeout,
                cwd=str(self._root),
                env=self.environment(),
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "Container command timed out after %.1fs: %r",
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
                error=f"timed out after {effective_timeout:.1f}s",
            )
        except OSError as exc:
            logger.error("Failed to launch docker CLI: %s", exc)
            return ExecResult(
                ok=False,
                exit_code=None,
                stdout="",
                stderr="",
                duration_ms=(time.monotonic() - start) * 1000,
                error=f"launch failed: {exc}",
            )
        with self._lock:
            self._runs += 1
        duration_ms = (time.monotonic() - start) * 1000
        return ExecResult(
            ok=completed.returncode == 0,
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_ms=duration_ms,
        )

    def filesystem(self) -> LocalFilesystem:
        return self._fs

    def process(self) -> DockerProcessControl:
        return DockerProcessControl(self)

    def network_policy(self) -> NetworkPolicy:
        return self._network_policy

    def environment(self) -> dict[str, str]:
        """Container env: overrides only, never the host environment."""
        return dict(self._env_overrides)

    def preview(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dry-run: report what would run without invoking the docker CLI."""
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
            "image": self._image,
            "workdir": str(self._root),
            "timeout_s": timeout_s,
            "network": self._network_flag(),
            "network_policy": self._network_policy.description,
            "would_execute": would_execute,
            "blocked_reason": blocked_reason,
        }

    def health(self) -> dict[str, Any]:
        """Report runtime health, probing the daemon via ``docker info``.

        This is the ONLY daemon touchpoint; tests gate it skip-if-no-daemon.
        """
        if self._destroyed:
            status = "destroyed"
            daemon = False
        elif shutil.which("docker") is None:
            status = "degraded"
            daemon = False
        else:
            try:
                probe = self._runner.run(
                    ["docker", "info", "--format", "{{.ServerVersion}}"],
                    timeout=_DAEMON_PROBE_TIMEOUT_S,
                )
                daemon = probe.returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                daemon = False
            status = "ok" if daemon else "degraded"
        return {
            "status": status,
            "runtime": "docker",
            "daemon_available": daemon,
            "image": self._image,
            "root_dir": str(self._root),
            "runs": self._runs,
            "network_policy": self._network_policy.description,
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

    def _network_flag(self) -> str:
        """Map the network policy onto a docker ``--network`` value."""
        return "bridge" if self._network_policy.allow_outbound else "none"

    def _build_config(
        self,
        command: list[str] | str,
        shell: bool,
        shell_command: str,
        timeout_s: float,
    ) -> ContainerConfig:
        """Translate a command + sandbox spec into the container run spec."""
        if shell:
            mapped: list[str] = ["/bin/sh", "-c", shell_command]
        else:
            mapped = [str(part) for part in command]
        return ContainerConfig(
            image=self._image,
            command=mapped,
            shell=shell,
            workdir=str(self._root),
            env=self.environment(),
            network=self._network_flag(),
            timeout_s=timeout_s,
        )


class DockerProcessControl:
    """Process facade for the container runtime.

    Containers are one-shot (``--rm``) and each run is synchronous, so no
    child processes are tracked locally; terminate is a no-op reporting False.
    """

    def __init__(self, runtime: DockerExecutionRuntime) -> None:
        self._runtime = runtime

    def active_pids(self) -> list[int]:
        return []

    def terminate(self, pid: int) -> bool:
        return False

    def terminate_all(self) -> int:
        return 0


def docker_daemon_available() -> bool:
    """Cheap daemon probe for test gating (skip-if-no-daemon)."""
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(  # noqa: S603 — fixed argv, no shell
            ["docker", "info"],
            timeout=_DAEMON_PROBE_TIMEOUT_S,
            capture_output=True,
            text=True,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return probe.returncode == 0


__all__ = [
    "CliDockerRunner",
    "ContainerConfig",
    "DockerExecutionRuntime",
    "DockerProcessControl",
    "DockerRunner",
    "docker_daemon_available",
]
