# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for DockerExecutionRuntime — hermetic unit path + gated integration.

The unit path (docker CLI command construction, spec-to-container config,
network-policy mapping, error handling) runs WITHOUT a daemon via an
injected FakeRunner. The only daemon touchpoint (``docker info`` probe in
health) is exercised behind ``pytest.mark.skipif`` skip-if-no-daemon.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.core.exec_runtime.docker import (
    ContainerConfig,
    DockerExecutionRuntime,
    DockerProcessControl,
    docker_daemon_available,
)
from src.core.exec_runtime.types import ExecResult, ExecutionRuntime, NetworkPolicy

_DAEMON = docker_daemon_available()
requires_daemon = pytest.mark.skipif(
    not _DAEMON, reason="docker daemon not available"
)


class FakeRunner:
    """In-memory docker CLI runner: records argv, replays canned outcomes."""

    def __init__(
        self,
        outcomes: list[subprocess.CompletedProcess[str] | Exception] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._outcomes = list(outcomes or [])

    def run(
        self,
        args: list[str],
        *,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append({"args": args, "timeout": timeout, "cwd": cwd, "env": env})
        if self._outcomes:
            outcome = self._outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


@pytest.fixture()
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture()
def rt(tmp_path: Path, runner: FakeRunner) -> DockerExecutionRuntime:
    return DockerExecutionRuntime(
        root_dir=tmp_path / "sandbox",
        image="python:3.11-slim",
        runner=runner,
    )


class TestProtocolConformance:
    def test_runtime_satisfies_execution_runtime_protocol(
        self, rt: DockerExecutionRuntime
    ):
        assert isinstance(rt, ExecutionRuntime)

    def test_all_eight_protocol_methods_present(self, rt: DockerExecutionRuntime):
        for name in (
            "execute",
            "filesystem",
            "process",
            "network_policy",
            "environment",
            "preview",
            "health",
            "destroy",
        ):
            assert callable(getattr(rt, name)), f"missing protocol method {name}"


class TestCommandConstruction:
    def test_argv_command_maps_to_docker_run(
        self, rt: DockerExecutionRuntime, runner: FakeRunner
    ):
        runner._outcomes.append(
            subprocess.CompletedProcess([], 0, stdout="hello", stderr="")
        )
        result = rt.execute(["echo", "hello"])
        assert isinstance(result, ExecResult)
        assert result.ok is True
        assert result.exit_code == 0
        assert result.stdout == "hello"
        args = runner.calls[0]["args"]
        assert args[:2] == ["docker", "run"]
        assert "--rm" in args
        assert args[-3:] == ["python:3.11-slim", "echo", "hello"]

    def test_shell_command_wrapped_in_sh_c(
        self, rt: DockerExecutionRuntime, runner: FakeRunner
    ):
        result = rt.execute("pwd")
        assert result.ok is True
        args = runner.calls[0]["args"]
        # image is last positional; the shell wrapper follows it
        assert args[-3:] == ["/bin/sh", "-c", "pwd"]
        assert args[-4] == "python:3.11-slim"

    def test_workdir_and_env_flags(
        self, tmp_path: Path
    ):
        runner = FakeRunner()
        runtime = DockerExecutionRuntime(
            root_dir=tmp_path / "sb",
            image="alpine:3",
            runner=runner,
            env_overrides={"MEKONG_MODE": "container", "A_FLAG": "1"},
        )
        runtime.execute(["ls"])
        call = runner.calls[0]
        args = call["args"]
        assert args[args.index("--workdir") + 1] == str((tmp_path / "sb").resolve())
        # env flags sorted and formatted KEY=VALUE
        env_pairs = [
            args[i + 1] for i, flag in enumerate(args) if flag == "--env"
        ]
        assert env_pairs == ["A_FLAG=1", "MEKONG_MODE=container"]
        assert call["cwd"] == str((tmp_path / "sb").resolve())
        assert call["env"] == {"MEKONG_MODE": "container", "A_FLAG": "1"}

    def test_timeout_forwarded_to_runner(
        self, rt: DockerExecutionRuntime, runner: FakeRunner
    ):
        rt.execute(["ls"], timeout_s=7.5)
        assert runner.calls[0]["timeout"] == 7.5

    def test_default_timeout_forwarded(
        self, rt: DockerExecutionRuntime, runner: FakeRunner
    ):
        rt.execute(["ls"])
        assert runner.calls[0]["timeout"] == 60.0

    def test_empty_argv_rejected(self, rt: DockerExecutionRuntime):
        with pytest.raises(ValueError, match="non-empty"):
            rt.execute([])

    def test_invalid_timeout_rejected(self, rt: DockerExecutionRuntime):
        with pytest.raises(ValueError, match="timeout_s must be positive"):
            rt.execute(["true"], timeout_s=0)

    def test_constructor_rejects_empty_image(self, tmp_path: Path):
        with pytest.raises(ValueError, match="image"):
            DockerExecutionRuntime(root_dir=tmp_path, image="", runner=FakeRunner())


class TestSpecToContainerConfig:
    def test_config_to_run_args_full_shape(self):
        config = ContainerConfig(
            image="alpine:3",
            command=["echo", "x"],
            shell=False,
            workdir="/work",
            env={"K": "V"},
            network="none",
            timeout_s=5.0,
        )
        args = config.to_run_args()
        assert args == [
            "docker", "run", "--rm",
            "--workdir", "/work",
            "--network", "none",
            "--env", "K=V",
            "alpine:3", "echo", "x",
        ]

    def test_config_no_env_omits_env_flag(self):
        config = ContainerConfig(
            image="alpine:3",
            command=["true"],
            shell=False,
            workdir="/work",
            env={},
            network="none",
            timeout_s=5.0,
        )
        assert "--env" not in config.to_run_args()


class TestNetworkPolicyMapping:
    def test_default_deny_all_maps_to_network_none(
        self, rt: DockerExecutionRuntime, runner: FakeRunner
    ):
        policy = rt.network_policy()
        assert isinstance(policy, NetworkPolicy)
        assert policy.allow_outbound is False
        rt.execute(["ls"])
        args = runner.calls[0]["args"]
        assert args[args.index("--network") + 1] == "none"

    def test_allow_outbound_maps_to_bridge(self, tmp_path: Path):
        runner = FakeRunner()
        runtime = DockerExecutionRuntime(
            root_dir=tmp_path,
            image="alpine:3",
            runner=runner,
            allow_outbound=True,
        )
        assert runtime.network_policy().allow_outbound is True
        runtime.execute(["ls"])
        args = runner.calls[0]["args"]
        assert args[args.index("--network") + 1] == "bridge"


class TestSanitizerGating:
    def test_rm_rf_root_blocked_before_cli(
        self, rt: DockerExecutionRuntime, runner: FakeRunner
    ):
        result = rt.execute("rm -rf /")
        assert result.ok is False
        assert result.exit_code is None
        assert "blocked by sanitizer" in (result.error or "")
        assert runner.calls == []  # never reached the docker CLI

    def test_chained_command_blocked(
        self, rt: DockerExecutionRuntime, runner: FakeRunner
    ):
        result = rt.execute("echo safe; rm -rf /tmp/x")
        assert result.ok is False
        assert "blocked by sanitizer" in (result.error or "")
        assert runner.calls == []

    def test_backtick_substitution_blocked(
        self, rt: DockerExecutionRuntime, runner: FakeRunner
    ):
        result = rt.execute("echo `whoami`")
        assert result.ok is False
        assert "blocked by sanitizer" in (result.error or "")
        assert runner.calls == []


class TestErrorHandling:
    def test_nonzero_exit_is_result_not_error(
        self, rt: DockerExecutionRuntime, runner: FakeRunner
    ):
        runner._outcomes.append(
            subprocess.CompletedProcess([], 3, stdout="", stderr="bad")
        )
        result = rt.execute(["false-ish"])
        assert result.ok is False
        assert result.exit_code == 3
        assert result.stderr == "bad"
        assert result.error is None

    def test_timeout_expired_maps_to_timed_out(
        self, rt: DockerExecutionRuntime, runner: FakeRunner
    ):
        runner._outcomes.append(subprocess.TimeoutExpired(cmd="docker", timeout=1.0))
        result = rt.execute(["sleep", "30"], timeout_s=1.0)
        assert result.ok is False
        assert result.timed_out is True
        assert result.exit_code is None
        assert "timed out after 1.0s" in (result.error or "")

    def test_missing_docker_binary_maps_to_launch_error(
        self, rt: DockerExecutionRuntime, runner: FakeRunner
    ):
        runner._outcomes.append(FileNotFoundError("docker not found"))
        result = rt.execute(["ls"])
        assert result.ok is False
        assert result.exit_code is None
        assert "launch failed" in (result.error or "")


class TestFilesystemSandbox:
    def test_escape_rejected(self, rt: DockerExecutionRuntime):
        with pytest.raises(PermissionError, match="escapes sandbox root"):
            rt.filesystem().read_text("../../etc/passwd")

    def test_write_read_roundtrip(self, rt: DockerExecutionRuntime):
        fs = rt.filesystem()
        assert fs.write_text("nested/file.txt", "data") == 4
        assert fs.read_text("nested/file.txt") == "data"
        assert fs.exists("nested/file.txt") is True


class TestPreviewHealthDestroy:
    def test_preview_blocked_command_without_cli(
        self, rt: DockerExecutionRuntime, runner: FakeRunner
    ):
        verdict = rt.preview({"command": "rm -rf /"})
        assert verdict["would_execute"] is False
        assert "rm_root" in verdict["blocked_reason"]
        assert verdict["image"] == "python:3.11-slim"
        assert verdict["network"] == "none"
        assert runner.calls == []  # preview never invokes the CLI

    def test_preview_safe_argv_command(
        self, rt: DockerExecutionRuntime, runner: FakeRunner
    ):
        verdict = rt.preview({"command": ["echo", "hi"], "timeout_s": 5})
        assert verdict["would_execute"] is True
        assert verdict["shell"] is False
        assert verdict["timeout_s"] == 5.0
        assert runner.calls == []

    def test_health_degraded_when_probe_fails(
        self, rt: DockerExecutionRuntime, runner: FakeRunner
    ):
        runner._outcomes.append(
            subprocess.CompletedProcess([], 1, stdout="", stderr="no daemon")
        )
        health = rt.health()
        assert health["runtime"] == "docker"
        assert health["daemon_available"] is False
        assert health["status"] in ("degraded", "destroyed")

    def test_health_ok_when_probe_succeeds(
        self, rt: DockerExecutionRuntime, runner: FakeRunner, monkeypatch: pytest.MonkeyPatch
    ):
        # Force the binary-presence check so the injected probe is exercised.
        monkeypatch.setattr(
            "src.core.exec_runtime.docker.shutil.which", lambda name: "/usr/bin/docker"
        )
        runner._outcomes.append(
            subprocess.CompletedProcess([], 0, stdout="27.0.0", stderr="")
        )
        health = rt.health()
        assert health["status"] == "ok"
        assert health["daemon_available"] is True
        probe_args = runner.calls[0]["args"]
        assert probe_args[:2] == ["docker", "info"]

    def test_destroy_then_health_and_execute(
        self, rt: DockerExecutionRuntime
    ):
        verdict = rt.destroy()
        assert verdict["status"] == "destroyed"
        assert rt.health()["status"] == "destroyed"
        with pytest.raises(RuntimeError, match="destroyed"):
            rt.execute(["true"])

    def test_process_control_is_stateless(self, rt: DockerExecutionRuntime):
        control = rt.process()
        assert isinstance(control, DockerProcessControl)
        assert control.active_pids() == []
        assert control.terminate(123) is False
        assert control.terminate_all() == 0

    def test_environment_is_overrides_only(self, tmp_path: Path):
        runtime = DockerExecutionRuntime(
            root_dir=tmp_path,
            image="alpine:3",
            runner=FakeRunner(),
            env_overrides={"ONLY_THIS": "1"},
        )
        env = runtime.environment()
        assert env == {"ONLY_THIS": "1"}
        assert "PATH" not in env  # host environment never leaks into the container


@requires_daemon
class TestDaemonIntegration:
    """Integration path — only runs when a real docker daemon is present."""

    def test_health_probe_against_real_daemon(self, tmp_path: Path):
        runtime = DockerExecutionRuntime(
            root_dir=tmp_path / "sb",
            image="alpine:3",
        )
        health = runtime.health()
        assert health["daemon_available"] is True
        assert health["status"] == "ok"

    def test_real_container_echo(self, tmp_path: Path):
        runtime = DockerExecutionRuntime(
            root_dir=tmp_path / "sb",
            image="alpine:3",
        )
        result = runtime.execute(["echo", "mekong"])
        assert result.ok is True
        assert result.stdout.strip() == "mekong"
