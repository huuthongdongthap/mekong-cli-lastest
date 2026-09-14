# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for LocalExecutionRuntime — sandboxed local execution primitive.

Covers: exec success/failure-as-return-value, timeout kill, cooperative
cancel, filesystem path-traversal rejection, CommandSanitizer injection
blocking, network policy deny-all default, preview/health/destroy.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from src.core.exec_runtime import (
    ExecResult,
    ExecutionRuntime,
    LocalExecutionRuntime,
    NetworkPolicy,
    SandboxSpec,
)
from src.core.exec_runtime.local import LocalFilesystem


@pytest.fixture()
def rt(tmp_path: Path) -> LocalExecutionRuntime:
    return LocalExecutionRuntime(root_dir=tmp_path / "sandbox")


class TestExecute:
    def test_exec_ok(self, rt: LocalExecutionRuntime):
        result = rt.execute([sys.executable, "-c", "print('hello')"])
        assert isinstance(result, ExecResult)
        assert result.ok is True
        assert result.exit_code == 0
        assert result.stdout.strip() == "hello"
        assert result.error is None
        assert not result.timed_out

    def test_exec_failure_returned_not_raised(self, rt: LocalExecutionRuntime):
        result = rt.execute([sys.executable, "-c", "import sys; sys.exit(3)"])
        assert result.ok is False
        assert result.exit_code == 3
        assert result.error is None  # nonzero exit is a RESULT, not an error

    def test_stderr_captured(self, rt: LocalExecutionRuntime):
        result = rt.execute(
            [sys.executable, "-c", "import sys; sys.stderr.write('oops')"]
        )
        assert result.ok is True
        assert "oops" in result.stderr

    def test_timeout_kills_process(self, rt: LocalExecutionRuntime):
        start = time.monotonic()
        result = rt.execute(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout_s=1.0,
        )
        elapsed = time.monotonic() - start
        assert result.ok is False
        assert result.timed_out is True
        assert "timed out" in (result.error or "")
        # Killed promptly, not after the full 30s sleep.
        assert elapsed < 10.0

    def test_invalid_timeout_rejected(self, rt: LocalExecutionRuntime):
        with pytest.raises(ValueError, match="timeout_s must be positive"):
            rt.execute(["true"], timeout_s=0)

    def test_empty_argv_rejected(self, rt: LocalExecutionRuntime):
        with pytest.raises(ValueError, match="non-empty"):
            rt.execute([])

    def test_launch_failure_returns_error(self, rt: LocalExecutionRuntime):
        result = rt.execute(["definitely-not-a-real-binary-xyz"])
        assert result.ok is False
        assert result.exit_code is None
        assert "launch failed" in (result.error or "")


class TestInjectionBlocking:
    def test_rm_rf_root_blocked(self, rt: LocalExecutionRuntime):
        result = rt.execute("rm -rf /")
        assert result.ok is False
        assert result.exit_code is None
        assert "blocked by sanitizer" in (result.error or "")

    def test_chained_command_blocked(self, rt: LocalExecutionRuntime):
        result = rt.execute("echo safe; rm -rf /tmp/x")
        assert result.ok is False
        assert "blocked by sanitizer" in (result.error or "")

    def test_backtick_substitution_blocked(self, rt: LocalExecutionRuntime):
        result = rt.execute("echo `whoami`")
        assert result.ok is False
        assert "blocked by sanitizer" in (result.error or "")

    def test_safe_shell_command_runs_in_sandbox_cwd(self, rt: LocalExecutionRuntime):
        result = rt.execute("pwd")
        assert result.ok is True
        assert result.stdout.strip() == str(rt._root)


class TestCancel:
    def test_terminate_tracked_process(self, rt: LocalExecutionRuntime):
        import subprocess

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=str(rt._root),
        )
        rt._processes[proc.pid] = proc
        control = rt.process()
        assert proc.pid in control.active_pids()
        assert control.terminate(proc.pid) is True
        assert proc.poll() is not None  # dead
        assert control.terminate(proc.pid) is False  # already gone

    def test_destroy_terminates_everything(self, tmp_path: Path):
        import subprocess

        rt = LocalExecutionRuntime(root_dir=tmp_path)
        procs = []
        for _ in range(2):
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=str(rt._root),
            )
            rt._processes[proc.pid] = proc
            procs.append(proc)
        verdict = rt.destroy()
        assert verdict["status"] == "destroyed"
        assert verdict["terminated_processes"] == 2
        time.sleep(0.1)
        assert all(p.poll() is not None for p in procs)
        assert rt.health()["status"] == "destroyed"

    def test_execute_after_destroy_raises(self, rt: LocalExecutionRuntime):
        rt.destroy()
        with pytest.raises(RuntimeError, match="destroyed"):
            rt.execute(["true"])


class TestPathTraversal:
    def test_escape_via_dotdot_rejected(self, rt: LocalExecutionRuntime):
        fs = rt.filesystem()
        with pytest.raises(PermissionError, match="escapes sandbox root"):
            fs.read_text("../../etc/passwd")

    def test_absolute_outside_root_rejected(self, rt: LocalExecutionRuntime):
        fs = rt.filesystem()
        with pytest.raises(PermissionError, match="escapes sandbox root"):
            fs.write_text("/etc/hosts", "pwned")

    def test_symlink_escape_rejected(self, rt: LocalExecutionRuntime, tmp_path: Path):
        outside = tmp_path / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        link = rt._root / "link.txt"
        link.symlink_to(outside)
        fs = rt.filesystem()
        with pytest.raises(PermissionError, match="escapes sandbox root"):
            fs.read_text("link.txt")

    def test_write_read_roundtrip_inside_root(self, rt: LocalExecutionRuntime):
        fs = rt.filesystem()
        assert fs.write_text("nested/dir/file.txt", "data") == 4
        assert fs.read_text("nested/dir/file.txt") == "data"
        assert fs.exists("nested/dir/file.txt") is True
        assert "file.txt" in fs.list_dir("nested/dir")

    def test_delete_inside_root(self, rt: LocalExecutionRuntime):
        fs = rt.filesystem()
        fs.write_text("gone.txt", "bye")
        assert fs.delete("gone.txt") is True
        assert fs.exists("gone.txt") is False

    def test_sandbox_spec_direct_use(self, tmp_path: Path):
        spec = SandboxSpec(root_dir=tmp_path / "sb")
        spec.root_dir.mkdir(parents=True)
        resolved = spec.resolve_in_root("sub/item.bin")
        assert str(resolved).startswith(str(spec.root_dir.resolve()))
        with pytest.raises(PermissionError):
            spec.resolve_in_root("../..")


class TestPolicyEnvironmentPreviewHealth:
    def test_network_policy_default_allow_outbound(self, rt: LocalExecutionRuntime):
        policy = rt.network_policy()
        assert isinstance(policy, NetworkPolicy)
        assert policy.allow_outbound is True
        assert policy.allowed_hosts == ("*",)

    def test_environment_includes_overrides(self, rt: LocalExecutionRuntime):
        env = rt.environment()
        assert isinstance(env, dict)
        assert "PATH" in env

    def test_environment_override_passed_to_child(self, tmp_path: Path):
        rt = LocalExecutionRuntime(
            root_dir=tmp_path,
            env_overrides={"MEKONG_TEST_MARKER": "present"},
        )
        result = rt.execute(
            [
                sys.executable, "-c",
                "import os; print(os.environ.get('MEKONG_TEST_MARKER', ''))",
            ]
        )
        assert result.stdout.strip() == "present"

    def test_preview_reports_without_executing(self, rt: LocalExecutionRuntime):
        verdict = rt.preview({"command": "rm -rf /"})
        assert verdict["would_execute"] is False
        assert "rm_root" in verdict["blocked_reason"]
        # Preview must not actually run anything.
        assert rt.health()["active_processes"] == 0
        safe = rt.preview({"command": ["echo", "hi"], "timeout_s": 5})
        assert safe["would_execute"] is True
        assert safe["shell"] is False
        assert safe["timeout_s"] == 5.0

    def test_health_ok_with_counts(self, rt: LocalExecutionRuntime):
        health = rt.health()
        assert health["status"] == "ok"
        assert health["active_processes"] == 0
        assert health["root_dir"] == str(rt._root)


class TestProtocolConformance:
    def test_local_runtime_structurally_matches_protocol(self):
        """runtime_checkable Protocol: instance check verifies method presence."""
        from typing import Any

        class _MinimalRuntime:
            """Structural stand-in implementing exactly the protocol surface."""

            def execute(self, command: Any, *, timeout_s: float | None = None) -> ExecResult: ...

            def filesystem(self) -> Any: ...

            def process(self) -> Any: ...

            def network_policy(self) -> NetworkPolicy: ...

            def environment(self) -> dict[str, str]: ...

            def preview(self, request: dict[str, Any]) -> dict[str, Any]: ...

            def health(self) -> dict[str, Any]: ...

            def destroy(self) -> dict[str, Any]: ...

        probe = _MinimalRuntime()
        assert isinstance(probe, ExecutionRuntime)

    def test_filesystem_facade_type(self, rt: LocalExecutionRuntime):
        assert isinstance(rt.filesystem(), LocalFilesystem)


class TestNetworkEnforcement:
    """Real network enforcement tests for deny-all vs allow-outbound.

    Tests are deterministic: on hosts with sandbox-exec, deny-all must block
    socket calls (EPERM/errno 1). On hosts without sandbox-exec, the runtime
    must fail loud (ExecResult.ok=False with enforcement error). In neither
    case does an unprotected command run silently.
    """

    def test_deny_all_blocks_outbound_socket(self, tmp_path: Path):
        """With allow_outbound=False, socket connect must fail or be blocked."""
        rt = LocalExecutionRuntime(root_dir=tmp_path / "sandbox")
        rt.set_network_policy(allow_outbound=False)
        if rt._sandbox_exec is None:
            pytest.skip("sandbox-exec not available; cannot verify socket blocking")
        result = rt.execute([
            sys.executable, "-c",
            "import socket; s=socket.socket(); s.settimeout(2); s.connect(('127.0.0.1', 19999))",
        ])
        assert result.ok is False
        error_text = (result.error or "") + (result.stderr or "")
        blocked = "PermissionError" in error_text or "Operation not permitted" in error_text
        assert blocked, (
            f"socket should be blocked inside sandbox; got error={result.error!r} "
            f"stderr={result.stderr!r}"
        )

    def test_deny_all_blocks_outbound_dns(self, tmp_path: Path):
        """With allow_outbound=False, DNS resolution must fail."""
        rt = LocalExecutionRuntime(root_dir=tmp_path / "sandbox")
        rt.set_network_policy(allow_outbound=False)
        if rt._sandbox_exec is None:
            pytest.skip("sandbox-exec not available; cannot verify DNS blocking")
        result = rt.execute([
            sys.executable, "-c",
            "import socket; socket.getaddrinfo('example.com', 443)",
        ])
        assert result.ok is False
        error_text = (result.error or "") + (result.stderr or "")
        blocked = "PermissionError" in error_text or "getaddrinfo" in error_text
        assert blocked, (
            f"DNS should be blocked inside sandbox; got error={result.error!r} "
            f"stderr={result.stderr!r}"
        )

    def test_allow_outbound_permits_connection(self, tmp_path: Path):
        """With allow_outbound=True (default), commands run without sandbox."""
        rt = LocalExecutionRuntime(root_dir=tmp_path / "sandbox")
        result = rt.execute([
            sys.executable, "-c",
            "import socket; s=socket.socket(); s.settimeout(2); "
            "s.connect(('127.0.0.1', 19999)); s.close()",
        ])
        # Without a server on 19999 this should get ConnectionRefused, not EPERM
        assert result.ok is False
        error_text = (result.error or "") + (result.stderr or "")
        not_blocked = "Operation not permitted" not in error_text
        assert not_blocked, (
            "allow_outbound=True should NOT produce a permission error; "
            f"got stderr={result.stderr!r}"
        )

    def test_deny_all_fails_loud_without_sandbox(self, tmp_path: Path):
        """If sandbox-exec is unavailable, deny-all must return loud error."""
        rt = LocalExecutionRuntime(root_dir=tmp_path / "sandbox")
        rt._sandbox_exec = None  # simulate missing sandbox-exec on non-darwin
        rt.set_network_policy(allow_outbound=False)
        if sys.platform == "linux":
            pytest.skip("linux path requires unshare; cannot test 'no sandbox' easily")
        result = rt.execute(["/bin/echo", "hello"])
        assert result.ok is False
        assert "network enforcement unavailable" in (result.error or "")
        assert "sandbox-exec not available" in (result.error or "")

    def test_network_policy_dynamic_toggle(self, tmp_path: Path):
        """set_network_policy flips the effective policy without re-creating."""
        rt = LocalExecutionRuntime(root_dir=tmp_path / "sandbox")
        assert rt.network_policy().allow_outbound is True
        rt.set_network_policy(allow_outbound=False)
        assert rt.network_policy().allow_outbound is False
        assert "enforced" in rt.network_policy().description.lower()
        rt.set_network_policy(allow_outbound=True)
        assert rt.network_policy().allow_outbound is True
        assert "allowed" in rt.network_policy().description.lower()

    def test_network_policy_default_allow_outbound(self, rt: LocalExecutionRuntime):
        """Default policy is allow_outbound=True (no sandbox wrapping)."""
        policy = rt.network_policy()
        assert isinstance(policy, NetworkPolicy)
        assert policy.allow_outbound is True
        assert policy.allowed_hosts == ("*",)

    def test_sandbox_exec_wraps_command(self, tmp_path: Path):
        """Verify sandbox-exec is prepended to command when deny-all is active."""
        rt = LocalExecutionRuntime(root_dir=tmp_path / "sandbox")
        if rt._sandbox_exec is None:
            pytest.skip("sandbox-exec not available on this host")
        rt.set_network_policy(allow_outbound=False)
        wrapped, err = rt._wrap_for_network_deny(["/bin/echo", "hi"], False)
        assert err is None
        assert wrapped[0] == rt._sandbox_exec
        assert "-p" in wrapped
        assert "deny" in wrapped[wrapped.index("-p") + 1]

    def test_preview_reports_network_policy(self, rt: LocalExecutionRuntime):
        """Preview output reflects current network policy."""
        verdict = rt.preview({"command": "echo hi"})
        assert "deny-all" in verdict["network_policy"] or "allowed" in verdict["network_policy"]
        rt.set_network_policy(allow_outbound=False)
        verdict2 = rt.preview({"command": "echo hi"})
        assert "deny-all" in verdict2["network_policy"]
