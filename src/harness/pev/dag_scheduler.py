# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""DAG scheduler for PEV orchestrator — unified with canonical core scheduler."""
from __future__ import annotations

from typing import Any

from src.core.dag_scheduler import (
    DAGScheduler,
    DAGStepResult,
    validate_dag as _core_validate_dag,
)


def validate_dag(steps: list[Any]) -> tuple[bool, str | None]:
    """Validate DAG for PEV callers, returning (is_valid, error_message)."""
    err = _core_validate_dag(steps)
    return (err is None, err)


__all__ = ["DAGScheduler", "DAGStepResult", "validate_dag"]
