# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""
src.core.orchestrator — public API facade.

All names previously exported from src/core/orchestrator.py remain importable
from this package without any changes to callers.

NOTE: The dependency imports below (RecipePlanner, RecipeVerifier, etc.) must be
present here so that unittest.mock.patch("src.core.orchestrator.X") resolves
correctly — patch works on the namespace where the name is looked up at call time.
"""

from .models import OrchestrationStatus, OrchestrationResult, StepResult
from .display import ReportFormatter, format_status, display_report
from .rollback import RollbackHandler
from .step_executor import StepExecutor
from .runner import RecipeOrchestrator

# Re-export runner-level dependencies so tests can patch them via
# patch("src.core.orchestrator.<Name>") without change.
from ..planner import RecipePlanner, PlanningContext
from ..verifier import RecipeVerifier
from ..telemetry import TelemetryCollector
from ..memory_canonical import MemoryStore
from ..nlu import IntentClassifier
from ..execution_history import ExecutionHistory
from ..retry_policy import RetryPolicy

__all__ = [
    "RecipeOrchestrator",
    "OrchestrationResult",
    "OrchestrationStatus",
    "ReportFormatter",
    "RollbackHandler",
    "StepExecutor",
    "StepResult",
    # internal helpers re-exported for any direct callers
    "format_status",
    "display_report",
    # dependency re-exports (needed for patch() in tests)
    "RecipePlanner",
    "PlanningContext",
    "RecipeVerifier",
    "TelemetryCollector",
    "MemoryStore",
    "IntentClassifier",
    "ExecutionHistory",
    "RetryPolicy",
]
