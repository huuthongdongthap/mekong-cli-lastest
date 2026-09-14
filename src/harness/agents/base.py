# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Mekong CLI - Harness Agent Base Module (Converged Facade).

Re-exports canonical AgentBase, Task, Result, TaskStatus, and StepHooksDict
from src.core.agent_base to ensure a single, authoritative AgentBase contract.
Preserves complete backward compatibility for all harness callers.
"""

from __future__ import annotations

from src.core.agent_base import (
    AgentBase,
    Result,
    StepHooksDict,
    Task,
    TaskStatus,
)

__all__ = [
    "AgentBase",
    "Result",
    "StepHooksDict",
    "Task",
    "TaskStatus",
]
