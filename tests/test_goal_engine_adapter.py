# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for GoalEngineAdapter — conformance + delegation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.core.protocols import Plan, PlanStatus, Step
from src.core.adapters.goal_engine_adapter import GoalEngineAdapter, GoalEngineResult
from src.mekongcli.core.goal_engine.models import GoalStatus


@dataclass
class StubFailureInfo:
    """Concrete FailureInfo-shaped object (the Protocol is not instantiable)."""

    step: str
    error: str
    output: Any
    retries: int = 0


class StubGoalStore:
    """Stub store exposing the task-read surface the adapter uses."""

    def __init__(self) -> None:
        self.tasks_by_goal: dict[str, list[Any]] = {}

    def get_tasks(self, goal_id: str) -> list[Any]:
        return self.tasks_by_goal.get(goal_id, [])


class StubGoalEngineService:
    """Minimal stub of the live GoalEngine service for delegation tests."""

    def __init__(self) -> None:
        self.created_goals: list[dict[str, Any]] = []
        self.run_calls: list[tuple[str, dict[str, Any]]] = []
        self.store = StubGoalStore()
        self._goal_counter = 0

    def create_goal(self, title: str) -> Any:
        self._goal_counter += 1
        goal_id = f"goal_{self._goal_counter}"
        goal = MagicMock()
        goal.id = goal_id
        goal.title = title
        goal.status = GoalStatus.PLANNED
        goal.created_at = 1234567890.0
        self.created_goals.append({"id": goal_id, "title": title})
        return goal

    def run_goal(
        self,
        goal_id: str,
        verification_profile: str = "standard",
        execute_commands: bool = False,
    ) -> Any:
        self.run_calls.append((goal_id, {"profile": verification_profile, "execute": execute_commands}))
        completed = MagicMock()
        completed.id = goal_id
        completed.status = GoalStatus.SATISFIED
        return completed


class TestGoalEngineAdapterConformance:
    """Protocol conformance tests."""

    def test_isinstance_protocol(self) -> None:
        from src.core import protocols
        adapter = GoalEngineAdapter(service=StubGoalEngineService())
        assert isinstance(adapter, protocols.GoalEngine)

    def test_has_required_methods(self) -> None:
        adapter = GoalEngineAdapter(service=StubGoalEngineService())
        assert hasattr(adapter, "decompose")
        assert hasattr(adapter, "adapt")
        assert hasattr(adapter, "commit")
        assert callable(adapter.decompose)
        assert callable(adapter.adapt)
        assert callable(adapter.commit)


class TestGoalEngineAdapterDelegation:
    """Delegation tests with stub service — verify adapter calls through."""

    def test_decompose_calls_create_goal(self, tmp_path: Path) -> None:
        stub = StubGoalEngineService()
        adapter = GoalEngineAdapter(service=stub)

        plan = adapter.decompose("Build a web app")

        assert len(stub.created_goals) == 1
        assert stub.created_goals[0]["title"] == "Build a web app"
        assert isinstance(plan, Plan)
        assert plan.goal == "Build a web app"
        assert plan.id == "goal_1"

    def test_decompose_returns_plan_with_steps(self, tmp_path: Path) -> None:
        stub = StubGoalEngineService()
        adapter = GoalEngineAdapter(service=stub)

        plan = adapter.decompose("Test goal")

        assert isinstance(plan.steps, list)
        # Service returns at least architect task in stub
        # Real service would have 7 tasks; stub has empty task list from store
        # but plan structure should be correct

    def test_adapt_creates_new_goal_with_failure_context(self, tmp_path: Path) -> None:
        stub = StubGoalEngineService()
        adapter = GoalEngineAdapter(service=stub)

        original_plan = Plan(
            id="plan_1",
            goal="Original goal",
            steps=[Step(id="s1", description="Step 1")],
            status=PlanStatus.PENDING,
            metadata={},
        )
        failure = StubFailureInfo(step="s1", error="connection timeout", output="failed", retries=2)

        adapted = adapter.adapt(original_plan, failure)

        assert len(stub.created_goals) == 1  # one new goal created
        assert "Retry:" in adapted.goal
        assert "connection timeout" in adapted.goal
        assert "retries so far: 2" in adapted.goal.lower()
        assert adapted.id != original_plan.id
        assert adapted.metadata.get("adapted_from") == "plan_1"
        assert adapted.metadata.get("failure", {}).get("step") == "s1"

    def test_commit_runs_goal_and_returns_result(self, tmp_path: Path) -> None:
        stub = StubGoalEngineService()
        adapter = GoalEngineAdapter(service=stub)

        plan = Plan(
            id="goal_1",
            goal="Test goal",
            steps=[Step(id="s1", description="Step 1")],
            status=PlanStatus.PENDING,
            metadata={"svc_goal_id": "goal_1"},
        )

        result = adapter.commit(plan)

        assert len(stub.run_calls) == 1
        assert stub.run_calls[0][0] == "goal_1"
        assert stub.run_calls[0][1]["profile"] == "standard"
        assert stub.run_calls[0][1]["execute"] is False

        assert isinstance(result, GoalEngineResult)
        assert result.success is True
        assert result.error is None
        assert result.output is not None
        assert result.output.get("goal_status") == "satisfied"

    def test_commit_creates_goal_if_no_svc_goal_id(self, tmp_path: Path) -> None:
        stub = StubGoalEngineService()
        adapter = GoalEngineAdapter(service=stub)

        plan = Plan(
            id="plan_new",
            goal="New goal without svc id",
            steps=[Step(id="s1", description="Step 1")],
            status=PlanStatus.PENDING,
            metadata={},  # no svc_goal_id
        )

        result = adapter.commit(plan)

        assert len(stub.created_goals) == 1
        assert len(stub.run_calls) == 1
        assert result.success is True


class TestGoalEngineAdapterErrorHandling:
    """Error path tests."""

    def test_commit_returns_failure_on_exception(self, tmp_path: Path) -> None:
        stub = StubGoalEngineService()

        def failing_run_goal(goal_id: str, **kwargs: Any) -> Any:
            raise RuntimeError("service unavailable")

        stub.run_goal = failing_run_goal
        adapter = GoalEngineAdapter(service=stub)

        plan = Plan(
            id="goal_1",
            goal="Test goal",
            steps=[],
            status=PlanStatus.PENDING,
            metadata={"svc_goal_id": "goal_1"},
        )

        result = adapter.commit(plan)

        assert isinstance(result, GoalEngineResult)
        assert result.success is False
        assert "service unavailable" in result.error
        assert result.metadata.get("svc_goal_id") == "goal_1"


class TestGoalEngineResultShape:
    """Result dataclass shape tests."""

    def test_result_has_protocol_fields(self) -> None:
        result = GoalEngineResult(success=True, output={"data": "test"}, error=None)
        assert result.success is True
        assert result.output == {"data": "test"}
        assert result.error is None
        assert result.metadata == {}

    def test_result_metadata_default_empty(self) -> None:
        result = GoalEngineResult(success=False, error="failed")
        assert result.metadata == {}

    def test_result_can_carry_metadata(self) -> None:
        result = GoalEngineResult(
            success=True,
            output="ok",
            metadata={"plan_id": "p1", "custom": "value"},
        )
        assert result.metadata["plan_id"] == "p1"
        assert result.metadata["custom"] == "value"


class TestGoalEngineAdapterValidation:
    """Input validation tests."""

    def test_missing_store_raises_loud(self) -> None:
        class NoStoreService:
            pass

        with pytest.raises(ValueError, match="requires a store"):
            GoalEngineAdapter(service=NoStoreService())


class TestGoalEngineAdapterIntegration:
    """Integration tests against the real live service (temp store)."""

    def test_decompose_with_real_service(self, tmp_path: Path) -> None:
        from src.mekongcli.core.goal_engine.store import SQLiteGoalStore
        store = SQLiteGoalStore(tmp_path / "goals.sqlite3")
        adapter = GoalEngineAdapter(store=store, cwd=tmp_path)

        plan = adapter.decompose("Ship the quarterly report")

        assert plan.id.startswith("goal_")
        assert plan.goal == "Ship the quarterly report"
        assert len(plan.steps) == 7  # live planner emits 7 role tasks
        roles = {step.params["role"] for step in plan.steps}
        assert "architect" in roles
        assert "reviewer" in roles

    def test_commit_with_real_service_satisfies(self, tmp_path: Path) -> None:
        from src.mekongcli.core.goal_engine.store import SQLiteGoalStore
        store = SQLiteGoalStore(tmp_path / "goals.sqlite3")
        # "none" profile: deterministic verification for the empty temp cwd
        adapter = GoalEngineAdapter(store=store, cwd=tmp_path, verification_profile="none")

        plan = adapter.decompose("Ship the quarterly report")
        result = adapter.commit(plan)

        assert result.success is True
        assert result.error is None
        assert result.output["goal_status"] == "satisfied"
        assert len(result.output["tasks"]) == 7

    def test_commit_with_real_service_blocked_reports_failure(self, tmp_path: Path) -> None:
        from src.mekongcli.core.goal_engine.store import SQLiteGoalStore
        store = SQLiteGoalStore(tmp_path / "goals.sqlite3")
        # "standard" profile runs real gates against the empty temp cwd → blocked
        adapter = GoalEngineAdapter(store=store, cwd=tmp_path, verification_profile="standard")

        plan = adapter.decompose("Ship the quarterly report")
        result = adapter.commit(plan)

        assert result.success is False
        assert result.error is not None
        assert result.output["goal_status"] == "blocked"


class TestMakeGoalEngineAdapter:
    """Factory function tests."""

    def test_factory_returns_adapter(self, tmp_path: Path) -> None:
        from src.core.adapters.goal_engine_adapter import make_goal_engine_adapter
        adapter = make_goal_engine_adapter(cwd=tmp_path)
        assert isinstance(adapter, GoalEngineAdapter)

    def test_factory_accepts_store(self, tmp_path: Path) -> None:
        from src.mekongcli.core.goal_engine.store import SQLiteGoalStore
        from src.core.adapters.goal_engine_adapter import make_goal_engine_adapter
        store = SQLiteGoalStore(tmp_path / "goals.sqlite3")
        adapter = make_goal_engine_adapter(store=store, cwd=tmp_path)
        assert isinstance(adapter, GoalEngineAdapter)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])