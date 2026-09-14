# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for CloudflareExecutionRuntime — hermetic via injected transport.

Every remote call flows through a FakeTransport; this suite makes ZERO real
Cloudflare API calls (the runtime never constructs a transport implicitly).
Covers: command mapping, spec-to-worker config translation, error/timeout
paths, health/destroy lifecycle, sanitizer gating, sandboxed filesystem,
and runtime_checkable Protocol conformance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.core.exec_runtime.cloudflare import (
    CloudflareExecutionRuntime,
    CloudflareProcessControl,
    WorkerConfig,
)
from src.core.exec_runtime.types import ExecResult, ExecutionRuntime, NetworkPolicy


class FakeTransport:
    """In-memory transport: records payloads, replays canned responses."""

    def __init__(
        self,
        responses: list[dict[str, Any] | Exception] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses or [])

    def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        if self._responses:
            response = self._responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return {"exit_code": 0, "stdout": "", "stderr": ""}


@pytest.fixture()
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture()
def rt(tmp_path: Path, transport: FakeTransport) -> CloudflareExecutionRuntime:
    return CloudflareExecutionRuntime(
        root_dir=tmp_path / "sandbox",
        account_id="acct-123",
        script_name="mekong-worker",
        transport=transport,
    )


class TestProtocolConformance:
    def test_runtime_satisfies_execution_runtime_protocol(
        self, rt: CloudflareExecutionRuntime
    ):
        assert isinstance(rt, ExecutionRuntime)

    def test_all_eight_protocol_methods_present(
        self, rt: CloudflareExecutionRuntime
    ):
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


class TestExecuteCommandMapping:
    def test_argv_command_dispatched_verbatim(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        transport._responses.append({"exit_code": 0, "stdout": "hello", "stderr": ""})
        result = rt.execute(["echo", "hello"])
        assert isinstance(result, ExecResult)
        assert result.ok is True
        assert result.exit_code == 0
        assert result.stdout == "hello"
        assert result.error is None
        assert len(transport.calls) == 1
        payload = transport.calls[0]
        assert payload["command"] == ["echo", "hello"]
        assert payload["shell"] is False

    def test_shell_command_wrapped_in_sh_c(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        result = rt.execute("pwd")
        assert result.ok is True
        payload = transport.calls[0]
        assert payload["command"] == ["/bin/sh", "-c", "pwd"]
        assert payload["shell"] is True

    def test_nonzero_exit_is_result_not_error(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        transport._responses.append({"exit_code": 3, "stdout": "", "stderr": "bad"})
        result = rt.execute(["false-ish"])
        assert result.ok is False
        assert result.exit_code == 3
        assert result.stderr == "bad"
        assert result.error is None

    def test_empty_argv_rejected(self, rt: CloudflareExecutionRuntime):
        with pytest.raises(ValueError, match="non-empty"):
            rt.execute([])

    def test_invalid_timeout_rejected(self, rt: CloudflareExecutionRuntime):
        with pytest.raises(ValueError, match="timeout_s must be positive"):
            rt.execute(["true"], timeout_s=0)

    def test_constructor_rejects_empty_account_id(self, tmp_path: Path):
        with pytest.raises(ValueError, match="account_id"):
            CloudflareExecutionRuntime(
                root_dir=tmp_path,
                account_id="",
                script_name="w",
                transport=FakeTransport(),
            )

    def test_constructor_rejects_empty_script_name(self, tmp_path: Path):
        with pytest.raises(ValueError, match="script_name"):
            CloudflareExecutionRuntime(
                root_dir=tmp_path,
                account_id="a",
                script_name="",
                transport=FakeTransport(),
            )


class TestSanitizerGating:
    def test_rm_rf_root_blocked_before_dispatch(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        result = rt.execute("rm -rf /")
        assert result.ok is False
        assert result.exit_code is None
        assert "blocked by sanitizer" in (result.error or "")
        assert transport.calls == []  # never reached the wire

    def test_chained_command_blocked(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        result = rt.execute("echo safe; rm -rf /tmp/x")
        assert result.ok is False
        assert "blocked by sanitizer" in (result.error or "")
        assert transport.calls == []

    def test_backtick_substitution_blocked(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        result = rt.execute("echo `whoami`")
        assert result.ok is False
        assert "blocked by sanitizer" in (result.error or "")
        assert transport.calls == []


class TestSpecToWorkerConfig:
    def test_config_carries_account_script_cwd_env_timeout(
        self, tmp_path: Path
    ):
        transport = FakeTransport()
        runtime = CloudflareExecutionRuntime(
            root_dir=tmp_path / "sb",
            account_id="acct-9",
            script_name="worker-9",
            transport=transport,
            env_overrides={"MEKONG_MODE": "remote"},
        )
        runtime.execute(["ls"], timeout_s=7.5)
        payload = transport.calls[0]
        assert payload["account_id"] == "acct-9"
        assert payload["script_name"] == "worker-9"
        assert payload["cwd"] == str((tmp_path / "sb").resolve())
        assert payload["env"] == {"MEKONG_MODE": "remote"}
        assert payload["timeout_s"] == 7.5

    def test_default_timeout_applied_to_payload(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        rt.execute(["ls"])
        assert transport.calls[0]["timeout_s"] == 60.0

    def test_worker_config_to_payload_roundtrip(self):
        config = WorkerConfig(
            account_id="a",
            script_name="s",
            command=["echo", "x"],
            shell=False,
            cwd="/work",
            env={"K": "V"},
            timeout_s=5.0,
        )
        payload = config.to_payload()
        assert payload == {
            "account_id": "a",
            "script_name": "s",
            "command": ["echo", "x"],
            "shell": False,
            "cwd": "/work",
            "env": {"K": "V"},
            "timeout_s": 5.0,
        }


class TestErrorAndTimeoutPaths:
    def test_transport_timeout_maps_to_timed_out(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        transport._responses.append(TimeoutError("deadline exceeded"))
        result = rt.execute(["sleep", "30"], timeout_s=1.0)
        assert result.ok is False
        assert result.timed_out is True
        assert result.exit_code is None
        assert "timed out after 1.0s" in (result.error or "")

    def test_transport_exception_maps_to_error_result(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        transport._responses.append(ConnectionError("wire is down"))
        result = rt.execute(["ls"])
        assert result.ok is False
        assert result.exit_code is None
        assert result.timed_out is False
        assert "transport error" in (result.error or "")
        assert "wire is down" in (result.error or "")

    def test_malformed_response_not_dict(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        transport._responses.append(["not", "a", "dict"])  # type: ignore[arg-type]
        result = rt.execute(["ls"])
        assert result.ok is False
        assert "malformed transport response" in (result.error or "")

    def test_malformed_response_missing_exit_code(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        transport._responses.append({"stdout": "no exit code"})
        result = rt.execute(["ls"])
        assert result.ok is False
        assert "exit_code" in (result.error or "")


class TestFilesystemSandbox:
    def test_escape_rejected(self, rt: CloudflareExecutionRuntime):
        with pytest.raises(PermissionError, match="escapes sandbox root"):
            rt.filesystem().read_text("../../etc/passwd")

    def test_write_read_roundtrip(self, rt: CloudflareExecutionRuntime):
        fs = rt.filesystem()
        assert fs.write_text("nested/file.txt", "data") == 4
        assert fs.read_text("nested/file.txt") == "data"
        assert fs.exists("nested/file.txt") is True


class TestPolicyEnvironmentPreview:
    def test_network_policy_default_allow_outbound(self, rt: CloudflareExecutionRuntime):
        policy = rt.network_policy()
        assert isinstance(policy, NetworkPolicy)
        assert policy.allow_outbound is True
        assert policy.allowed_hosts == ("*",)

    def test_environment_is_overrides_only_no_host_leak(
        self, tmp_path: Path
    ):
        runtime = CloudflareExecutionRuntime(
            root_dir=tmp_path,
            account_id="a",
            script_name="s",
            transport=FakeTransport(),
            env_overrides={"ONLY_THIS": "1"},
        )
        env = runtime.environment()
        assert env == {"ONLY_THIS": "1"}
        assert "PATH" not in env  # host environment never leaks to the worker

    def test_preview_blocked_command_without_dispatch(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        verdict = rt.preview({"command": "rm -rf /"})
        assert verdict["would_execute"] is False
        assert "rm_root" in verdict["blocked_reason"]
        assert verdict["account_id"] == "acct-123"
        assert verdict["script_name"] == "mekong-worker"
        assert transport.calls == []  # preview never dispatches

    def test_preview_safe_argv_command(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        verdict = rt.preview({"command": ["echo", "hi"], "timeout_s": 5})
        assert verdict["would_execute"] is True
        assert verdict["shell"] is False
        assert verdict["timeout_s"] == 5.0
        assert transport.calls == []


class TestHealthDestroyLifecycle:
    def test_health_ok_and_dispatch_count(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        health = rt.health()
        assert health["status"] == "ok"
        assert health["runtime"] == "cloudflare"
        assert health["dispatches"] == 0
        rt.execute(["ls"])
        rt.execute(["ls"])
        assert rt.health()["dispatches"] == 2

    def test_destroy_then_health_reports_destroyed(
        self, rt: CloudflareExecutionRuntime
    ):
        verdict = rt.destroy()
        assert verdict["status"] == "destroyed"
        assert rt.health()["status"] == "destroyed"

    def test_execute_after_destroy_raises(
        self, rt: CloudflareExecutionRuntime
    ):
        rt.destroy()
        with pytest.raises(RuntimeError, match="destroyed"):
            rt.execute(["true"])

    def test_process_control_is_stateless(
        self, rt: CloudflareExecutionRuntime
    ):
        control = rt.process()
        assert isinstance(control, CloudflareProcessControl)
        assert control.active_pids() == []
        assert control.terminate(123) is False
        assert control.terminate_all() == 0


class TestNetworkEnforcement:
    """Transport-level network enforcement for CloudflareExecutionRuntime.

    When allow_outbound=False, execute() must refuse to dispatch through the
    transport and return a loud error instead of silently running.
    """

    def test_deny_all_blocks_transport_dispatch(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        """With allow_outbound=False, transport.dispatch is never called."""
        rt.set_network_policy(allow_outbound=False)
        result = rt.execute(["echo", "should-not-dispatch"])
        assert result.ok is False
        assert result.exit_code is None
        assert "network policy denies outbound" in (result.error or "")
        assert transport.calls == []  # transport was never invoked

    def test_deny_all_blocks_shell_command(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        """With allow_outbound=False, shell commands are also blocked."""
        rt.set_network_policy(allow_outbound=False)
        result = rt.execute("pwd")
        assert result.ok is False
        assert "network policy denies outbound" in (result.error or "")
        assert transport.calls == []

    def test_allow_outbound_permits_dispatch(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        """With allow_outbound=True (default), dispatch proceeds normally."""
        transport._responses.append({"exit_code": 0, "stdout": "ok", "stderr": ""})
        result = rt.execute(["echo", "ok"])
        assert result.ok is True
        assert len(transport.calls) == 1

    def test_network_policy_dynamic_toggle(
        self, tmp_path: Path, transport: FakeTransport
    ):
        """set_network_policy flips enforcement without re-creating runtime."""
        rt = CloudflareExecutionRuntime(
            root_dir=tmp_path / "sb",
            account_id="a",
            script_name="s",
            transport=transport,
        )
        assert rt.network_policy().allow_outbound is True
        rt.set_network_policy(allow_outbound=False)
        assert rt.network_policy().allow_outbound is False
        assert "deny-all" in rt.network_policy().description
        # Verify dispatch is blocked
        result = rt.execute(["ls"])
        assert result.ok is False
        assert transport.calls == []
        # Flip back and verify dispatch works
        rt.set_network_policy(allow_outbound=True)
        transport._responses.append({"exit_code": 0, "stdout": "", "stderr": ""})
        result2 = rt.execute(["ls"])
        assert result2.ok is True
        assert len(transport.calls) == 1

    def test_network_policy_deny_all_description(
        self, rt: CloudflareExecutionRuntime
    ):
        """Network policy description reflects enforcement state."""
        rt.set_network_policy(allow_outbound=False)
        policy = rt.network_policy()
        assert policy.allow_outbound is False
        assert policy.allowed_hosts == ()
        assert "deny-all" in policy.description.lower()

    def test_network_policy_allow_outbound_description(
        self, rt: CloudflareExecutionRuntime
    ):
        """Network policy description reflects allowed state."""
        policy = rt.network_policy()
        assert policy.allow_outbound is True
        assert policy.allowed_hosts == ("*",)
        assert "allowed" in policy.description.lower()

    def test_deny_all_still_sanitizes_before_checking_network(
        self, rt: CloudflareExecutionRuntime, transport: FakeTransport
    ):
        """Sanitizer runs first; network check is after but both enforce."""
        rt.set_network_policy(allow_outbound=False)
        result = rt.execute("rm -rf /")
        # Sanitizer blocks this before network check
        assert result.ok is False
        assert "blocked by sanitizer" in (result.error or "")
        assert transport.calls == []

    def test_health_reports_network_policy(
        self, rt: CloudflareExecutionRuntime
    ):
        """Health output includes current network policy."""
        health = rt.health()
        assert "network_policy" in health
        assert "allowed" in health["network_policy"].lower()
        rt.set_network_policy(allow_outbound=False)
        health2 = rt.health()
        assert "deny-all" in health2["network_policy"].lower()

    def test_preview_reports_network_policy(
        self, rt: CloudflareExecutionRuntime
    ):
        """Preview output reflects current network policy."""
        verdict = rt.preview({"command": "echo hi"})
        assert "allowed" in verdict["network_policy"].lower()
        rt.set_network_policy(allow_outbound=False)
        verdict2 = rt.preview({"command": "echo hi"})
        assert "deny-all" in verdict2["network_policy"].lower()
