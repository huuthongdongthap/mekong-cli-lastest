# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Execution runtime package — local-first, Protocol-driven.

Public surface:
- ``ExecutionRuntime`` — structural Protocol (execute/filesystem/process/
  network_policy/environment/preview/health/destroy).
- ``LocalExecutionRuntime`` — subprocess-based local implementation with
  sandboxed filesystem, sanitizer-gated shell execution, timeout/cancel.
"""

from src.core.exec_runtime.local import (
    LocalExecutionRuntime,
    LocalFilesystem,
    LocalProcessControl,
)
from src.core.exec_runtime.types import (
    ExecResult,
    ExecutionRuntime,
    NetworkPolicy,
    SandboxSpec,
)

__all__ = [
    "ExecResult",
    "ExecutionRuntime",
    "LocalExecutionRuntime",
    "LocalFilesystem",
    "LocalProcessControl",
    "NetworkPolicy",
    "SandboxSpec",
]
