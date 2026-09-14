# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for CloudflareExecutionAdapter — the single import site binding the
core to the Cloudflare Worker runtime.

Hermetic: every remote call flows through a FakeTransport. Zero real
Cloudflare API calls. Mirrors the pattern of ``tests/test_exec_runtime_cloudflare.py``
but pins the ADAPTER contract (bus registration, fail-loud config,
capability dispatch) rather than the runtime internals.
"""

from __future__ import annotations

import pytest

from src.core.adapters.cloudflare import (
    CloudflareAdapterConfigError,
    CloudflareExecutionAdapter,
)
from src.core.capability import InMemoryCapabilityBus


class FakeTransport:
    """In-memory CloudflareTransport that records every dispatch."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._responses: list[dict] = []

    def dispatch(self, payload: dict) -> dict:
        self.calls.append(payload)
        return self._responses.pop(0) if self._responses else {
            "exit_code": 0,
            "stdout": "ok",
            "stderr": "",
        }


def _adapter(root_dir: str, **overrides: object) -> CloudflareExecutionAdapter:
    return CloudflareExecutionAdapter(
        root_dir=root_dir,
        account_id="acct",
        script_name="worker",
        transport=FakeTransport(),
        **overrides,
    )


class TestAdapterConstruction:
    def test_constructs_with_transport(self, tmp_path):
        adapter = _adapter(str(tmp_path))
        assert adapter.runtime is not None

    def test_missing_account_id_raises_config_error(self, tmp_path):
        with pytest.raises(CloudflareAdapterConfigError, match="account_id"):
            CloudflareExecutionAdapter(
                root_dir=str(tmp_path),
                account_id="",
                script_name="worker",
                transport=FakeTransport(),
            )

    def test_missing_script_name_raises_config_error(self, tmp_path):
        with pytest.raises(CloudflareAdapterConfigError, match="script_name"):
            CloudflareExecutionAdapter(
                root_dir=str(tmp_path),
                account_id="acct",
                script_name="",
                transport=FakeTransport(),
            )

    def test_missing_transport_raises_config_error(self, tmp_path):
        with pytest.raises(CloudflareAdapterConfigError, match="transport"):
            CloudflareExecutionAdapter(
                root_dir=str(tmp_path),
                account_id="acct",
                script_name="worker",
                transport=None,
            )


class TestCapabilitySurface:
    def test_surfaces_four_capabilities(self, tmp_path):
        ids = {c.id for c in _adapter(str(tmp_path)).capabilities()}
        assert ids == {
            "cf.worker.execute",
            "cf.worker.fs",
            "cf.worker.health",
            "cf.worker.destroy",
        }

    def test_execute_capability_is_high_risk(self, tmp_path):
        cap = next(
            c
            for c in _adapter(str(tmp_path)).capabilities()
            if c.id == "cf.worker.execute"
        )
        assert cap.risk_level == "HIGH"
        assert cap.authorization == "cf.execute"
        assert cap.cost == 1.0

    def test_sync_to_bus_registers_all(self, tmp_path):
        adapter = _adapter(str(tmp_path))
        bus = InMemoryCapabilityBus()
        registered = adapter.sync_to_bus(bus)
        assert len(registered) == 4
        assert len(bus.list_capabilities()) == 4

    def test_sync_to_bus_is_idempotent(self, tmp_path):
        adapter = _adapter(str(tmp_path))
        bus = InMemoryCapabilityBus()
        adapter.sync_to_bus(bus)
        adapter.sync_to_bus(bus)
        assert len(bus.list_capabilities()) == 4


class TestCapabilityDispatch:
    def test_execute_capability_dispatches_to_worker(self, tmp_path):
        adapter = _adapter(str(tmp_path))
        result = adapter.execute("cf.worker.execute", {"command": "echo hi"})
        assert result["ok"] is True
        assert result["exit_code"] == 0
        assert result["stdout"] == "ok"

    def test_fs_capability_reports_root(self, tmp_path):
        adapter = _adapter(str(tmp_path))
        result = adapter.execute("cf.worker.fs", {})
        assert result["filesystem"] == "available"
        assert str(tmp_path) in result["root"]

    def test_health_capability_probes_runtime(self, tmp_path):
        adapter = _adapter(str(tmp_path))
        result = adapter.execute("cf.worker.health", {})
        assert result["status"] == "ok"
        assert result["runtime"] == "cloudflare"

    def test_destroy_capability_tears_down(self, tmp_path):
        adapter = _adapter(str(tmp_path))
        result = adapter.execute("cf.worker.destroy", {})
        assert result["destroyed"] is True
        assert adapter.runtime.destroyed is True

    def test_unknown_capability_raises_config_error(self, tmp_path):
        adapter = _adapter(str(tmp_path))
        with pytest.raises(CloudflareAdapterConfigError, match="unknown"):
            adapter.execute("cf.worker.bogus", {})


class TestImportNeutralityGate:
    """T8 isolation contract: the core spine must not import the Cloudflare
    runtime, even after the adapter exists. The adapter is the only bridge,
    so it lives outside the spine (``src/core/adapters/``), not inside it.
    """

    BLOCKED = frozenset({
        "src.core.exec_runtime.cloudflare",
        "src.core.exec_runtime.docker",
        "src.core.adapters.cloudflare",
    })

    def test_import_core_does_not_pull_cloudflare_runtime(self):
        import subprocess
        import sys
        import textwrap

        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        code = textwrap.dedent(
            """
            import sys
            import src.core
            for name in {blocked!r}:
                assert name not in sys.modules, (
                    f"import src.core pulled remote-adapter module: {{name}}"
                )
            """
        ).format(blocked=sorted(self.BLOCKED))
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"import src.core pulled a remote-adapter module:\n"
            f"{result.stdout}\n{result.stderr}"
        )

    def test_adapter_is_importable_with_zero_credentials(self):
        """Importing the adapter package must not require any config."""
        from src.core.adapters import cloudflare  # noqa: F401
        from src.core.adapters.cloudflare import CloudflareExecutionAdapter  # noqa: F401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])