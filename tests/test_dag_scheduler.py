# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Unit tests for the unified DAGScheduler in src/core/dag_scheduler.py
and its PEV bridge in src/harness/pev/dag_scheduler.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.dag_scheduler import (
    DAGScheduler,
    validate_dag,
)
from src.harness.pev.dag_scheduler import (
    DAGScheduler as PevDAGScheduler,
    validate_dag as pev_validate_dag,
)


@dataclass
class DummyStep:
    order: int
    title: str = "test"
    dependencies: list[int] | None = None


# ---------------------------------------------------------------------------
# Topological Execution Order & Parallel Groups
# ---------------------------------------------------------------------------


def test_empty_steps() -> None:
    sched = DAGScheduler([])
    assert sched.get_execution_order() == []
    assert sched.get_parallel_groups() == []
    assert not sched.has_dependencies()
    assert validate_dag([]) is None


def test_single_step_object() -> None:
    steps = [DummyStep(order=1)]
    sched = DAGScheduler(steps)
    assert sched.get_execution_order() == [1]
    assert sched.get_parallel_groups() == [[1]]
    assert not sched.has_dependencies()
    assert validate_dag(steps) is None


def test_single_step_dict() -> None:
    steps = [{"order": 0, "title": "init"}]
    sched = DAGScheduler(steps)
    assert sched.get_execution_order() == [0]
    assert sched.get_parallel_groups() == [[0]]
    assert not sched.has_dependencies()
    assert validate_dag(steps) is None


def test_linear_chain_objects() -> None:
    # 1 -> 2 -> 3
    steps = [
        DummyStep(order=1, dependencies=[]),
        DummyStep(order=2, dependencies=[1]),
        DummyStep(order=3, dependencies=[2]),
    ]
    sched = DAGScheduler(steps)
    assert sched.has_dependencies()
    assert sched.get_execution_order() == [1, 2, 3]
    assert sched.get_parallel_groups() == [[1], [2], [3]]
    assert validate_dag(steps) is None


def test_linear_chain_reversed_input() -> None:
    # 3 depends on 2, 2 depends on 1 (given in reverse order [3, 2, 1])
    steps = [
        DummyStep(order=3, dependencies=[2]),
        DummyStep(order=2, dependencies=[1]),
        DummyStep(order=1, dependencies=[]),
    ]
    sched = DAGScheduler(steps)
    assert sched.get_execution_order() == [1, 2, 3]
    assert sched.get_parallel_groups() == [[1], [2], [3]]
    assert validate_dag(steps) is None


def test_diamond_dag_parallel_groups() -> None:
    # 1 -> (2, 3) -> 4
    steps = [
        DummyStep(order=1, dependencies=[]),
        DummyStep(order=2, dependencies=[1]),
        DummyStep(order=3, dependencies=[1]),
        DummyStep(order=4, dependencies=[2, 3]),
    ]
    sched = DAGScheduler(steps)
    assert sched.has_dependencies()
    order = sched.get_execution_order()
    assert order[0] == 1
    assert set(order[1:3]) == {2, 3}
    assert order[3] == 4

    groups = sched.get_parallel_groups()
    assert groups[0] == [1]
    assert set(groups[1]) == {2, 3}
    assert groups[2] == [4]
    assert validate_dag(steps) is None


def test_dict_steps_with_depends_on() -> None:
    # Dict steps with "id" and "depends_on"
    steps = [
        {"id": 10, "depends_on": []},
        {"id": 20, "depends_on": [10]},
        {"id": 30, "depends_on": [10]},
        {"id": 40, "depends_on": [20, 30]},
    ]
    sched = DAGScheduler(steps)
    assert sched.has_dependencies()
    groups = sched.get_parallel_groups()
    assert groups[0] == [10]
    assert set(groups[1]) == {20, 30}
    assert groups[2] == [40]
    assert validate_dag(steps) is None


def test_cycle_detection_in_validate_dag() -> None:
    # 1 -> 2 -> 1
    steps = [
        DummyStep(order=1, dependencies=[2]),
        DummyStep(order=2, dependencies=[1]),
    ]
    err = validate_dag(steps)
    assert err is not None
    assert "Circular dependency" in err


def test_pev_bridge_reexport_and_validation() -> None:
    # Test through src.harness.pev.dag_scheduler re-export
    steps = [
        {"order": 1, "dependencies": []},
        {"order": 2, "dependencies": [1]},
    ]
    sched = PevDAGScheduler(steps)
    assert sched.get_execution_order() == [1, 2]
    assert sched.get_parallel_groups() == [[1], [2]]

    is_valid, msg = pev_validate_dag(steps)
    assert is_valid is True
    assert msg is None

    # Cyclic
    bad_steps = [
        {"order": 1, "dependencies": [2]},
        {"order": 2, "dependencies": [1]},
    ]
    is_valid, msg = pev_validate_dag(bad_steps)
    assert is_valid is False
    assert msg is not None
    assert "Circular dependency" in msg


# ---------------------------------------------------------------------------
# Concurrent Execution & Downstream Cancellation
# ---------------------------------------------------------------------------


class MockExecResult:
    def __init__(self, passed: bool = True, text: str = "ok"):
        self.verification = type("Verification", (), {"passed": passed})()
        self.text = text


def test_execute_all_success() -> None:
    steps = [
        DummyStep(order=1),
        DummyStep(order=2, dependencies=[1]),
    ]
    sched = DAGScheduler(steps, max_workers=2)

    executed: list[int] = []

    def executor(step: Any) -> MockExecResult:
        executed.append(step.order)
        return MockExecResult(passed=True)

    results = sched.execute_all(executor)
    assert len(results) == 2
    assert results[1].success is True
    assert results[2].success is True
    assert sched.is_done()
    assert executed == [1, 2]


def test_execute_all_failure_cancels_downstream() -> None:
    # 1 (fails) -> 2 (should be cancelled)
    # 3 (independent, succeeds)
    steps = [
        DummyStep(order=1),
        DummyStep(order=2, dependencies=[1]),
        DummyStep(order=3),
    ]
    sched = DAGScheduler(steps, max_workers=2)

    def executor(step: Any) -> MockExecResult:
        if step.order == 1:
            return MockExecResult(passed=False)
        return MockExecResult(passed=True)

    results = sched.execute_all(executor)
    assert results[1].success is False
    assert 2 in sched.cancelled_steps
    assert 2 not in results
    assert results[3].success is True
    assert sched.is_done()
