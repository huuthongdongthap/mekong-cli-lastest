# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Cloudflare execution adapter — wraps the Cloudflare Worker runtime as a
source of Capabilities on the canonical bus.

Architecture (T8 of SUPER COMMAND #5):
- The core spine (``src/core/``) has ZERO direct Cloudflare imports. The
  worker runtime lives in :mod:`src.core.exec_runtime.cloudflare`, itself
  hermetic-by-construction: every remote call flows through an injected
  ``CloudflareTransport`` and no transport is ever built implicitly.
- THIS adapter is the single import site that binds the core to the CF
  runtime. It is importable with zero arguments and zero credentials; any
  call that would need a real worker raises ``CloudflareAdapterConfigError``
  at call time, never at import time (mirrors ``LLMConfigError``).
- Capabilities surfaced: ``cf.worker.execute`` (HIGH), ``cf.worker.fs``
  (MEDIUM), ``cf.worker.health`` (LOW), ``cf.worker.destroy`` (LOW).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.capability import Capability, CapabilityBus, CapabilitySource
from src.core.exec_runtime.cloudflare import (
    CloudflareExecutionRuntime,
    CloudflareTransport,
)

DEFAULT_TIMEOUT_S = 30.0


class CloudflareAdapterConfigError(ValueError):
    """Required Cloudflare configuration is missing (fail-loud).

    Importing this module never requires credentials — the adapter is
    fully usable with no arguments. This fires only at construction time
    when a real worker is requested but an identity/transport is missing.
    """


@dataclass
class CloudflareExecutionAdapter:
    """Adapter that exposes a Cloudflare Worker runtime as bus Capabilities.

    Construct with an injected transport (the same ``CloudflareTransport``
    Protocol the runtime itself requires). Without one, construction raises
    ``CloudflareAdapterConfigError`` — there is no implicit default.
    """

    root_dir: str | Path
    account_id: str | None = None
    script_name: str | None = None
    transport: CloudflareTransport | None = None
    env_overrides: dict[str, str] | None = None
    timeout_s: float = DEFAULT_TIMEOUT_S

    def __post_init__(self) -> None:
        if not self.account_id:
            raise CloudflareAdapterConfigError(
                "CloudflareExecutionAdapter requires a non-empty account_id"
            )
        if not self.script_name:
            raise CloudflareAdapterConfigError(
                "CloudflareExecutionAdapter requires a non-empty script_name"
            )
        if self.transport is None:
            raise CloudflareAdapterConfigError(
                "CloudflareExecutionAdapter requires an injected transport — "
                "pass a CloudflareTransport; never build one implicitly"
            )
        self._runtime = CloudflareExecutionRuntime(
            root_dir=self.root_dir,
            account_id=self.account_id,
            script_name=self.script_name,
            transport=self.transport,
            env_overrides=self.env_overrides,
            default_timeout_s=self.timeout_s,
        )

    @property
    def runtime(self) -> CloudflareExecutionRuntime:
        """The wrapped worker runtime (hermetic — all traffic via transport)."""
        return self._runtime

    # ------------------------------------------------------------------ #
    # Capability surface
    # ------------------------------------------------------------------ #

    def capabilities(self) -> list[Capability]:
        """Return the Capabilities this adapter contributes to the bus."""
        return [
            Capability(
                id="cf.worker.execute",
                name="Cloudflare Worker Execute",
                description=(
                    "Run a shell command on a stateless Cloudflare Worker; "
                    "artifacts land in the local sandbox root. Sanitizer and "
                    "network policy enforced before dispatch."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "argv": {"type": "array", "items": {"type": "string"}},
                        "timeout_s": {"type": "number", "minimum": 0},
                    },
                },
                risk_level="HIGH",
                source=CapabilitySource.CUSTOM,
                cost=1.0,
                authorization="cf.execute",
                tags=["cloudflare", "worker", "shell"],
                metadata={"adapter": "cloudflare_execution", "script": self.script_name},
            ),
            Capability(
                id="cf.worker.fs",
                name="Cloudflare Worker Filesystem",
                description="Sandbox-confined filesystem facade over the worker root.",
                input_schema={"type": "object"},
                risk_level="MEDIUM",
                source=CapabilitySource.CUSTOM,
                cost=0.0,
                authorization="cf.fs",
                tags=["cloudflare", "worker", "filesystem"],
            ),
            Capability(
                id="cf.worker.health",
                name="Cloudflare Worker Health",
                description="Probe the worker runtime for liveness.",
                input_schema={"type": "object"},
                risk_level="LOW",
                source=CapabilitySource.CUSTOM,
                cost=0.0,
                tags=["cloudflare", "worker", "health"],
            ),
            Capability(
                id="cf.worker.destroy",
                name="Cloudflare Worker Destroy",
                description="Tear down the worker runtime (idempotent).",
                input_schema={"type": "object"},
                risk_level="LOW",
                source=CapabilitySource.CUSTOM,
                cost=0.0,
                tags=["cloudflare", "worker", "lifecycle"],
            ),
        ]

    def sync_to_bus(self, bus: CapabilityBus) -> list[Capability]:
        """Register every capability this adapter owns. Idempotent."""
        caps = self.capabilities()
        for cap in caps:
            bus.register(cap)
        return caps

    # ------------------------------------------------------------------ #
    # Dispatch helpers — the bus calls these when a capability is invoked
    # ------------------------------------------------------------------ #

    def execute(self, capability_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a capability invocation to the underlying runtime."""
        if capability_id == "cf.worker.execute":
            result = self._runtime.execute(
                params.get("command") or params.get("argv") or "",
                timeout_s=params.get("timeout_s"),
            )
            return {
                "ok": result.ok,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "error": result.error,
                "duration_ms": result.duration_ms,
            }
        if capability_id == "cf.worker.fs":
            return {"filesystem": "available", "root": str(self._runtime.health().get("root_dir", ""))}
        if capability_id == "cf.worker.health":
            return self._runtime.health()
        if capability_id == "cf.worker.destroy":
            self._runtime.destroy()
            return {"destroyed": True}
        raise CloudflareAdapterConfigError(
            f"unknown Cloudflare capability: {capability_id!r}"
        )


__all__ = ["CloudflareExecutionAdapter", "CloudflareAdapterConfigError"]