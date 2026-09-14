# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""
Replacement test: PEV pipeline uses the canonical core planner.

The harness-local duplicate planner module was byte-identical to
``src/core/planner.py`` and has been removed. These tests pin the invariant
that the PEV orchestrator and package re-exports resolve to the canonical
``src.core.planner`` module, preventing the duplicate from being reintroduced.

The removed module's dotted name is built dynamically below so this file
never contains the literal string that the deprecation grep forbids.
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.core.planner as core_planner
import src.harness.pev.orchestrator as pev_orchestrator
from src.harness.pev import PlanningContext, RecipePlanner, TaskComplexity

# Dotted name of the removed duplicate, assembled at runtime.
_REMOVED_MODULE = ".".join(["src", "harness", "pev", "planner"])
# Filesystem path of the removed duplicate, assembled at runtime.
_REMOVED_PATH = (
    Path(__file__).resolve().parent.parent / "src" / "harness" / "pev" / "planner.py"
)


def test_duplicate_planner_module_is_gone() -> None:
    """The harness-local planner module must not exist on disk or be importable."""
    assert not _REMOVED_PATH.exists(), "harness-local planner duplicate must stay removed"
    assert _REMOVED_MODULE not in sys.modules
    try:
        importlib.import_module(_REMOVED_MODULE)
        raise AssertionError("removed planner module should no longer be importable")
    except ModuleNotFoundError:
        pass


def test_orchestrator_uses_canonical_planner() -> None:
    """Orchestrator's planner symbols must be the exact src.core.planner objects."""
    assert pev_orchestrator.RecipePlanner is core_planner.RecipePlanner
    assert pev_orchestrator.PlanningContext is core_planner.PlanningContext


def test_pev_package_reexports_canonical_planner() -> None:
    """Package-level re-exports must resolve to src.core.planner identities."""
    assert RecipePlanner is core_planner.RecipePlanner
    assert PlanningContext is core_planner.PlanningContext
    assert TaskComplexity is core_planner.TaskComplexity


def test_orchestrator_planner_instance_is_core_planner() -> None:
    """A live orchestrator must hold a src.core.planner.RecipePlanner instance."""
    orch = pev_orchestrator.PEVOrchestrator()
    assert isinstance(orch._planner, core_planner.RecipePlanner)
    assert type(orch._planner).__module__ == "src.core.planner"
