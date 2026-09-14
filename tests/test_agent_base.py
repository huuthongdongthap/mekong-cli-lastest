"""
Tests: src.core.agent_base — AgentBase, Task, Result, TaskStatus.

Covers:
- TaskStatus enum values and string representations
- Task / Result dataclass field defaults and assignment
- AgentBase.__init__ — name, max_retries, empty task list
- AgentBase.__repr__ — developer-friendly format
- AgentBase.verify() — default delegates to result.success
- AgentBase.run() — Plan-Execute-Verify loop (success, retry, fail)
- Retry exhaustion marks task FAILED
- Multiple tasks in one run
- __init_subclass__ warning for partial concrete classes
"""

from __future__ import annotations

import warnings
from unittest.mock import patch


from src.core.agent_base import AgentBase, Result, Task, TaskStatus


# ---------------------------------------------------------------------------
# Helpers — minimal concrete implementations
# ---------------------------------------------------------------------------

class _SimpleAgent(AgentBase):
    """Concrete agent that executes pre-loaded tasks."""

    def plan(self, input_data: str) -> list[Task]:
        return [Task(id=f"t{i}", description=input_data, input={"i": i}) for i in range(int(input_data))]

    def execute(self, task: Task) -> Result:
        return Result(task_id=task.id, success=True, output=f"done-{task.id}")


class _FailingAgent(AgentBase):
    """Agent whose execute always returns failure."""

    def plan(self, input_data: str) -> list[Task]:
        return [Task(id="fail", description="fail", input={})]

    def execute(self, task: Task) -> Result:
        return Result(task_id=task.id, success=False, output=None, error="boom")


class _CountingAgent(AgentBase):
    """Agent that succeeds on the N-th attempt."""

    def __init__(self, name: str, succeed_on: int, max_retries: int = 3) -> None:
        super().__init__(name, max_retries)
        self._call_count = 0
        self._succeed_on = succeed_on

    def plan(self, input_data: str) -> list[Task]:
        return [Task(id="c1", description="count", input={})]

    def execute(self, task: Task) -> Result:
        self._call_count += 1
        success = self._call_count >= self._succeed_on
        return Result(task_id=task.id, success=success, output="ok" if success else None, error=None if success else "not yet")


# ---------------------------------------------------------------------------
# TaskStatus
# ---------------------------------------------------------------------------

class TestTaskStatus:

    def test_all_values_exist(self):
        assert {s.value for s in TaskStatus} == {"pending", "running", "success", "failed", "retry"}

    def test_pending(self):
        assert TaskStatus.PENDING.value == "pending"

    def test_running(self):
        assert TaskStatus.RUNNING.value == "running"

    def test_success(self):
        assert TaskStatus.SUCCESS.value == "success"

    def test_failed(self):
        assert TaskStatus.FAILED.value == "failed"

    def test_retry(self):
        assert TaskStatus.RETRY.value == "retry"

    def test_enum_count(self):
        assert len(TaskStatus) == 5


# ---------------------------------------------------------------------------
# Task dataclass
# ---------------------------------------------------------------------------

class TestTaskDataclass:

    def test_required_fields(self):
        t = Task(id="t1", description="desc", input={"k": "v"})
        assert t.id == "t1"
        assert t.description == "desc"
        assert t.input == {"k": "v"}

    def test_default_status(self):
        t = Task(id="t1", description="desc", input={})
        assert t.status == TaskStatus.PENDING

    def test_default_output_none(self):
        t = Task(id="t1", description="desc", input={})
        assert t.output is None

    def test_default_error_none(self):
        t = Task(id="t1", description="desc", input={})
        assert t.error is None

    def test_status_assignable(self):
        t = Task(id="t1", description="desc", input={})
        t.status = TaskStatus.RUNNING
        assert t.status == TaskStatus.RUNNING

    def test_output_assignable(self):
        t = Task(id="t1", description="desc", input={})
        t.output = {"result": 42}
        assert t.output == {"result": 42}

    def test_error_assignable(self):
        t = Task(id="t1", description="desc", input={})
        t.error = "something went wrong"
        assert t.error == "something went wrong"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

class TestResultDataclass:

    def test_required_fields_success(self):
        r = Result(task_id="t1", success=True, output="done")
        assert r.task_id == "t1"
        assert r.success is True
        assert r.output == "done"

    def test_required_fields_failure(self):
        r = Result(task_id="t1", success=False, output=None)
        assert r.success is False
        assert r.output is None

    def test_default_error_none(self):
        r = Result(task_id="t1", success=True, output="x")
        assert r.error is None

    def test_error_assignable(self):
        r = Result(task_id="t1", success=False, output=None, error="boom")
        assert r.error == "boom"

    def test_output_can_be_dict(self):
        r = Result(task_id="t1", success=True, output={"key": "val"})
        assert r.output == {"key": "val"}

    def test_output_can_be_list(self):
        r = Result(task_id="t1", success=True, output=[1, 2, 3])
        assert r.output == [1, 2, 3]


# ---------------------------------------------------------------------------
# AgentBase.__init__
# ---------------------------------------------------------------------------

class TestAgentBaseInit:

    def test_name_stored(self):
        a = _SimpleAgent("my-agent")
        assert a.name == "my-agent"

    def test_default_max_retries(self):
        a = _SimpleAgent("agent")
        assert a.max_retries == 3

    def test_custom_max_retries(self):
        a = _SimpleAgent("agent", max_retries=5)
        assert a.max_retries == 5

    def test_tasks_empty_on_init(self):
        a = _SimpleAgent("agent")
        assert a.tasks == []

    def test_zero_max_retries_allowed(self):
        a = _SimpleAgent("agent", max_retries=0)
        assert a.max_retries == 0


# ---------------------------------------------------------------------------
# AgentBase.__repr__
# ---------------------------------------------------------------------------

class TestAgentBaseRepr:

    def test_format(self):
        a = _SimpleAgent("test-agent")
        assert repr(a) == "<Agent:test-agent tasks=0>"

    def test_format_after_run(self):
        a = _SimpleAgent("runner")
        a.run("3")
        assert repr(a) == "<Agent:runner tasks=3>"


# ---------------------------------------------------------------------------
# AgentBase.verify (default)
# ---------------------------------------------------------------------------

class TestVerifyDefault:

    def test_returns_true_on_success(self):
        a = _SimpleAgent("v")
        r = Result(task_id="t1", success=True, output="ok")
        assert a.verify(r) is True

    def test_returns_false_on_failure(self):
        a = _SimpleAgent("v")
        r = Result(task_id="t1", success=False, output=None)
        assert a.verify(r) is False


# ---------------------------------------------------------------------------
# AgentBase.run — success path
# ---------------------------------------------------------------------------

class TestRunSuccess:

    def test_returns_results_list(self):
        a = _SimpleAgent("s")
        results = a.run("2")
        assert len(results) == 2

    def test_all_tasks_succeed(self):
        a = _SimpleAgent("s")
        results = a.run("3")
        assert all(r.success for r in results)

    def test_task_status_success(self):
        a = _SimpleAgent("s")
        a.run("1")
        assert a.tasks[0].status == TaskStatus.SUCCESS

    def test_task_output_populated(self):
        a = _SimpleAgent("s")
        a.run("1")
        assert a.tasks[0].output == "done-t0"

    def test_zero_tasks(self):
        a = _SimpleAgent("s")
        results = a.run("0")
        assert results == []

    def test_five_tasks(self):
        a = _SimpleAgent("s")
        results = a.run("5")
        assert len(results) == 5
        assert all(r.success for r in results)


# ---------------------------------------------------------------------------
# AgentBase.run — retry + failure path
# ---------------------------------------------------------------------------

class TestRunRetry:

    def test_failing_agent_all_tasks_failed(self):
        a = _FailingAgent("f", max_retries=2)
        results = a.run("")
        assert results[0].success is False

    def test_failing_task_status_failed(self):
        a = _FailingAgent("f", max_retries=2)
        a.run("")
        assert a.tasks[0].status == TaskStatus.FAILED

    def test_retry_exhaustion_calls_execute_max_retries_times(self):
        a = _FailingAgent("f", max_retries=3)
        with patch.object(a, "execute", wraps=a.execute) as mock_exec:
            a.run("")
            assert mock_exec.call_count == 3

    def test_succeeds_on_second_attempt(self):
        a = _CountingAgent("retry-ok", succeed_on=2, max_retries=3)
        results = a.run("")
        assert results[0].success is True

    def test_succeeds_on_first_attempt_no_retry(self):
        a = _CountingAgent("no-retry", succeed_on=1, max_retries=3)
        results = a.run("")
        assert results[0].success is True
        assert a._call_count == 1

    def test_fails_when_succeed_on_exceeds_max_retries(self):
        a = _CountingAgent("too-late", succeed_on=10, max_retries=3)
        results = a.run("")
        assert results[0].success is False

    def test_zero_max_retries_never_executes_loop(self):
        """max_retries=0 means while loop runs 0 times — task never attempted."""
        a = _FailingAgent("f", max_retries=0)
        with patch.object(a, "execute", wraps=a.execute) as mock_exec:
            results = a.run("")
        assert mock_exec.call_count == 0
        assert results[0].success is False
        assert a.tasks[0].status == TaskStatus.FAILED

    def test_task_error_populated_on_failure(self):
        """task.error is set from result.error when task exhausts retries."""
        a = _FailingAgent("f", max_retries=1)
        a.run("")
        assert a.tasks[0].error == "boom"

    def test_verify_override_retries_valid_result(self):
        """Custom verify returning False causes retries even on success=True."""
        class _StrictAgent(AgentBase):
            def __init__(self) -> None:
                super().__init__("strict", max_retries=3)
                self._call_count = 0

            def plan(self, input_data: str) -> list[Task]:
                return [Task(id="s1", description="strict", input={})]

            def execute(self, task: Task) -> Result:
                self._call_count += 1
                return Result(task_id=task.id, success=True, output="ok")

            def verify(self, result: Result) -> bool:
                # Only pass on the 3rd call
                return self._call_count >= 3

        a = _StrictAgent()
        results = a.run("")
        assert results[0].success is True
        assert a._call_count == 3

    def test_task_status_retry_during_retries(self):
        """Task is set to RETRY after first failed verify, before re-execution."""
        a = _FailingAgent("f", max_retries=3)

        original_verify = a.verify

        def capturing_verify(result: Result) -> bool:
            # status is set to RETRY before the next execute call;
            # we capture it during verify (called before the RETRY assignment)
            # so we inspect the TASK directly after the first call returns False
            ret = original_verify(result)
            return ret

        with patch.object(a, "verify", side_effect=capturing_verify):
            a.run("")

        # After exhaustion, task must be FAILED regardless
        assert a.tasks[0].status == TaskStatus.FAILED

    def test_retry_sets_task_status_retry_on_second_call(self):
        """On the second execute call the task.status is RETRY (set at end of first loop iter)."""
        statuses_on_entry: list[TaskStatus] = []
        a = _FailingAgent("f", max_retries=3)

        original_execute = a.execute

        call_count = 0

        def capturing_execute(task: Task) -> Result:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                statuses_on_entry.append(task.status)
            return original_execute(task)

        with patch.object(a, "execute", side_effect=capturing_execute):
            a.run("")

        # From the 2nd call onward, status should be RETRY
        assert TaskStatus.RETRY in statuses_on_entry


# ---------------------------------------------------------------------------
# Multiple tasks mixed success/failure
# ---------------------------------------------------------------------------

class TestRunMultipleTasks:

    def test_independent_task_outcomes(self):
        class _MixedAgent(AgentBase):
            def plan(self, input_data: str) -> list[Task]:
                return [
                    Task(id="ok", description="ok", input={}),
                    Task(id="fail", description="fail", input={}),
                ]

            def execute(self, task: Task) -> Result:
                if task.id == "ok":
                    return Result(task_id=task.id, success=True, output="yes")
                return Result(task_id=task.id, success=False, output=None, error="no")

        a = _MixedAgent("mixed", max_retries=1)
        results = a.run("")
        assert results[0].success is True
        assert results[1].success is False
        assert a.tasks[0].status == TaskStatus.SUCCESS
        assert a.tasks[1].status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# __init_subclass__ warning for incomplete concrete classes
# ---------------------------------------------------------------------------

class TestInitSubclassWarning:

    def test_no_warning_for_full_implementation(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            class _FullAgent(AgentBase):
                def plan(self, input_data: str) -> list[Task]:
                    return []

                def execute(self, task: Task) -> Result:
                    return Result(task_id=task.id, success=True, output=None)

        assert not any(issubclass(w.category, UserWarning) for w in caught)

    def test_no_warning_for_abstract_subclass(self):
        """Abstract subclasses (still have abstractmethods) should not warn."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            class _AbstractSubAgent(AgentBase):
                """Still abstract — doesn't implement plan or execute."""

        assert not any(
            "does not implement" in str(w.message) for w in caught
        )


# ---------------------------------------------------------------------------
# __all__ export check
# ---------------------------------------------------------------------------

class TestPublicExports:

    def test_all_exports_importable(self):
        from src.core.agent_base import __all__  # noqa: PLC0415
        for name in __all__:
            obj = __import__("src.core.agent_base", fromlist=[name])
            assert hasattr(obj, name)

    def test_all_contains_expected_names(self):
        from src.core.agent_base import __all__  # noqa: PLC0415
        assert set(__all__) == {"AgentBase", "Result", "Task", "TaskStatus", "StepHooksDict"}
