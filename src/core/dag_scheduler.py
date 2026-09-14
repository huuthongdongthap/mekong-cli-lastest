# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Mekong CLI - DAG Scheduler.

Topological execution of recipe steps with dependency tracking.
Steps without mutual dependencies run concurrently via ThreadPoolExecutor.
Falls back to sequential when no dependencies defined.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DAGStepResult:
    """Result of a single DAG step execution."""

    order: Any
    success: bool
    result: Any = None
    error: str | None = None


def _get_order(step: Any, default: Any = 0) -> Any:
    """Extract integer order or string id from a step (object, dict, or Task)."""
    target = getattr(step, "step", step)
    if isinstance(target, dict):
        val = target.get("order", target.get("id", default))
    else:
        val = getattr(target, "order", getattr(target, "id", default))
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        if val.isdigit():
            return int(val)
        return val
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _get_dependencies(step: Any) -> list[Any]:
    """Extract list of dependency orders or ids from a step (object, dict, or Task)."""
    target = getattr(step, "step", step)
    if isinstance(target, dict):
        raw = target.get("dependencies", target.get("depends_on", [])) or []
    else:
        raw = getattr(target, "dependencies", getattr(target, "depends_on", [])) or []
    deps: list[Any] = []
    for d in raw:
        if isinstance(d, int):
            deps.append(d)
        elif isinstance(d, str):
            if d.isdigit():
                deps.append(int(d))
            else:
                deps.append(d)
        else:
            try:
                deps.append(int(d))
            except (ValueError, TypeError):
                pass
    return deps


class DAGScheduler:
    """DAG-based scheduler for recipe steps.

    Identifies steps whose dependencies are satisfied and executes them
    concurrently using ThreadPoolExecutor (stdlib, no asyncio).

    Args:
        steps: List of recipe steps with .order and .dependencies (or dicts)
        max_workers: Thread pool size (default: 4)

    """

    def __init__(self, steps: list, max_workers: int = 4) -> None:
        self.steps = steps
        self._steps = {_get_order(s, idx): s for idx, s in enumerate(steps)}
        self._max_workers = max_workers
        self._completed: set[Any] = set()
        self._failed: set[Any] = set()
        self._cancelled: set[Any] = set()
        self._lock = threading.Lock()

    def get_ready_steps(self) -> list:
        """Return steps whose dependencies are all completed."""
        ready = []
        with self._lock:
            for order, step in self._steps.items():
                if order in self._completed or order in self._failed or order in self._cancelled:
                    continue
                deps = _get_dependencies(step)
                if all(d in self._completed for d in deps):
                    ready.append(step)
        return ready

    def mark_completed(self, order: Any) -> None:
        """Mark step as successfully completed."""
        with self._lock:
            self._completed.add(order)

    def mark_failed(self, order: Any) -> None:
        """Mark step as failed and cancel downstream dependents."""
        with self._lock:
            self._failed.add(order)
            self._cancel_downstream(order)

    def _cancel_downstream(self, failed_order: Any) -> None:
        """Cancel steps that depend on a failed step (transitive)."""
        queue = [failed_order]
        while queue:
            current = queue.pop(0)
            for order, step in self._steps.items():
                if order in self._cancelled:
                    continue
                deps = _get_dependencies(step)
                if current in deps:
                    self._cancelled.add(order)
                    queue.append(order)

    def is_done(self) -> bool:
        """True when all steps are completed, failed, or cancelled."""
        all_orders = set(self._steps.keys())
        return all_orders == (self._completed | self._failed | self._cancelled)

    @property
    def cancelled_steps(self) -> set[Any]:
        """Steps cancelled due to upstream failure."""
        return self._cancelled.copy()

    def has_dependencies(self) -> bool:
        """Check if any step has non-empty dependencies."""
        for step in self._steps.values():
            deps = _get_dependencies(step)
            if deps:
                return True
        return False

    def get_execution_order(self, strict: bool = False) -> list[Any]:
        """Return topological execution order of steps by order/index or id.

        If no dependencies, returns orders in original sequence.
        If cyclic:
            - If strict=True, raises RuntimeError with remaining circular steps.
            - If strict=False, logs a warning and returns orders in original sequence.
        If a dependency is missing:
            - If strict=True, raises RuntimeError.
            - If strict=False, ignores missing dependency and continues.
        """
        if not self._steps:
            return []

        if not self.has_dependencies():
            return list(self._steps.keys())

        orders = list(self._steps.keys())
        in_degree: dict[Any, int] = {o: 0 for o in orders}
        adj: dict[Any, list[Any]] = defaultdict(list)

        for order, step in self._steps.items():
            deps = _get_dependencies(step)
            for dep in deps:
                if dep in self._steps:
                    adj[dep].append(order)
                    in_degree[order] += 1
                elif strict:
                    raise RuntimeError(
                        f"task '{order}' depends on unknown step '{dep}'"
                    )

        queue = [o for o in orders if in_degree[o] == 0]
        exec_order: list[Any] = []

        while queue:
            curr = queue.pop(0)
            exec_order.append(curr)
            for nbr in adj.get(curr, []):
                in_degree[nbr] -= 1
                if in_degree[nbr] == 0:
                    queue.append(nbr)

        if len(exec_order) != len(orders):
            remaining = [o for o in orders if o not in set(exec_order)]
            if strict:
                raise RuntimeError(
                    f"circular task dependency detected among: {remaining}"
                )
            logger.warning(
                "Circular dependency detected in get_execution_order; falling back to input order"
            )
            return list(self._steps.keys())

        return exec_order

    def get_parallel_groups(self) -> list[list[Any]]:
        """Return steps partitioned into parallel execution groups (waves).

        Each wave contains step orders that can run concurrently because all
        their dependencies belong to prior waves.
        """
        if not self._steps:
            return []

        if not self.has_dependencies():
            return [list(self._steps.keys())]

        orders = list(self._steps.keys())
        in_degree: dict[Any, int] = {o: 0 for o in orders}
        adj: dict[Any, list[Any]] = defaultdict(list)

        for order, step in self._steps.items():
            deps = _get_dependencies(step)
            for dep in deps:
                if dep in self._steps:
                    adj[dep].append(order)
                    in_degree[order] += 1

        current_wave = [o for o in orders if in_degree[o] == 0]
        groups: list[list[Any]] = []
        processed = 0

        while current_wave:
            groups.append(current_wave)
            processed += len(current_wave)
            next_wave: list[Any] = []
            for curr in current_wave:
                for nbr in adj.get(curr, []):
                    in_degree[nbr] -= 1
                    if in_degree[nbr] == 0:
                        next_wave.append(nbr)
            current_wave = next_wave

        if processed != len(orders):
            logger.warning(
                "Circular dependency detected in get_parallel_groups; falling back to single group"
            )
            return [list(self._steps.keys())]

        return groups

    def execute_all(
        self,
        executor_fn: Callable,
        on_complete: Callable | None = None,
    ) -> dict[Any, DAGStepResult]:
        """Execute all steps respecting DAG dependencies.

        Args:
            executor_fn: Callable(step) → result with .verification.passed
            on_complete: Optional callback(order, dag_result) after each step

        Returns:
            Dict mapping step order → DAGStepResult

        """
        results: dict[Any, DAGStepResult] = {}
        in_flight: set[Any] = set()

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures: dict[Future, Any] = {}

            while not self.is_done():
                ready = self.get_ready_steps()
                new_ready = [s for s in ready if _get_order(s) not in in_flight]

                for step in new_ready:
                    step_order = _get_order(step)
                    in_flight.add(step_order)
                    future = pool.submit(executor_fn, step)
                    futures[future] = step

                if not futures:
                    break

                done_futures = []
                for future in as_completed(futures):
                    step = futures[future]
                    step_order = _get_order(step)
                    try:
                        result = future.result()
                        passed = getattr(
                            getattr(result, "verification", None),
                            "passed", False,
                        )
                        dag_result = DAGStepResult(
                            order=step_order,
                            success=passed,
                            result=result,
                        )
                    except Exception as e:
                        logger.exception("Step %d failed: %s", step_order, e)
                        dag_result = DAGStepResult(
                            order=step_order, success=False, error=str(e),
                        )
                        passed = False

                    results[step_order] = dag_result

                    if passed:
                        self.mark_completed(step_order)
                    else:
                        self.mark_failed(step_order)

                    if on_complete:
                        on_complete(step_order, dag_result)

                    done_futures.append(future)

                for f in done_futures:
                    del futures[f]

        return results


def validate_dag(steps: list) -> str | None:
    """Validate DAG has no circular dependencies.

    Returns:
        Error message if circular, None if valid.

    """
    if not steps:
        return None

    adj: dict[Any, list[Any]] = defaultdict(list)
    step_dict = {_get_order(s, i): s for i, s in enumerate(steps)}
    orders = set(step_dict.keys())

    for order, step in step_dict.items():
        deps = _get_dependencies(step)
        for dep in deps:
            adj[dep].append(order)

    # Kahn's algorithm for cycle detection
    in_degree: dict[Any, int] = dict.fromkeys(orders, 0)
    for order, step in step_dict.items():
        deps = _get_dependencies(step)
        for dep in deps:
            if dep in in_degree:
                in_degree[order] += 1

    queue = [o for o, d in in_degree.items() if d == 0]
    visited = 0

    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited != len(orders):
        return "Circular dependency detected in recipe steps"
    return None


__all__ = ["DAGScheduler", "DAGStepResult", "validate_dag"]
