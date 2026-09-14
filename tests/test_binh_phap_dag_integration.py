"""Track D D6: Integration tests for Binh Phap DAG.

Read-only — no implementation files modified.

Covers acceptance criteria:
 (a) schema versioning  - v1 auto-upgrades to current, missing schema upgrades
 (b) atomic write       - .tmp sibling removed after os.replace
 (c) legacy upgrade     - old fields map to current schema correctly
 (d) full DAG e2e       - 3-node DAG executes in dependency order
 (e) recovery flows     - retry / fallback / escalate / abort
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.core.binh_phap.dag import DagDefinition, ChapterNode
from src.core.binh_phap.executor import (
    ExecutionResult,
    ExecutionState,
    Executor,
    _SCHEMA_VERSION,
    _RETRY_POLICY_DEFAULT,
)
from src.core.binh_phap.recovery import (
    register,
)


@pytest.fixture()
def tmp_state(tmp_path: Path) -> Path:
    return tmp_path / "state.json"


@pytest.fixture()
def simple_dag() -> DagDefinition:
    """3-node linear DAG: 1 -> 2 -> 3."""
    chapters = {
        1: ChapterNode(1, "Alpha", "agent-a", ["cmd-a"], "rule-a"),
        2: ChapterNode(2, "Beta", "agent-b", ["cmd-b"], "rule-b"),
        3: ChapterNode(3, "Gamma", "agent-c", ["cmd-c"], "rule-c"),
    }
    edges = {1: [], 2: [1], 3: [2]}
    return DagDefinition(chapters=chapters, edges=edges, human_only=frozenset())


@pytest.fixture()
def fallback_dag() -> DagDefinition:
    """DAG where ch8 on timeout falls back to [1, 7]."""
    ch1 = ChapterNode(1, "Init", "init", ["setup"], "rule-init")
    ch7 = ChapterNode(7, "Debug", "dbg-agent", ["dbg"], "rule-debug")
    ch8 = ChapterNode(8, "Ops", "ops-agent", ["op"], "rule-ops")
    chapters = {1: ch1, 7: ch7, 8: ch8}
    edges = {1: [], 7: [1], 8: [7, 1]}
    return DagDefinition(chapters=chapters, edges=edges, human_only=frozenset())


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ===================================================================
# (a) Tests: schema versioning
# ===================================================================


class TestSchemaVersioning:
    def test_legacy_schema_version_is_upgraded(self, simple_dag: DagDefinition, tmp_path: Path) -> None:
        sp = tmp_path / "v1_state.json"
        _write_state(sp, {
            "schema_version": "legacy-v1",
            "run_id": "RUN_LEGACY_V1",
            "completed": [1],
            "failed": {"2": "timeout on fetch"},
            "current": 2,
            "retry_policy": {"max_consecutive_failures": 2, "backoff_base_seconds": 1},
            "started_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:03+00:00",
            "results": {
                "1": {
                    "chapter": 1,
                    "status": "success",
                    "started_at": None,
                    "finished_at": None,
                    "error": None,
                    "fallback_chapters": [],
                },
                "2": {
                    "chapter": 2,
                    "status": "failed",
                    "started_at": None,
                    "finished_at": None,
                    "error": "timeout on fetch",
                    "fallback_chapters": [],
                },
            },
        })
        st = ExecutionState.load(sp)
        # D2: legacy schema_version is promoted to current
        assert st.schema_version == _SCHEMA_VERSION
        # backwards-compat: legacy run_id preserved
        assert st.run_id == "RUN_LEGACY_V1"
        # progress records preserved
        assert 1 in st.completed
        assert st.failed.get(2) == "timeout on fetch"
        assert 1 in st.results and st.results[1].status == "success"
        assert 2 in st.results and st.results[2].error == "timeout on fetch"

    def test_missing_schema_version_is_treated_as_legacy(self, simple_dag: DagDefinition, tmp_path: Path) -> None:
        sp = tmp_path / "no_ver_state.json"
        _write_state(sp, {
            "run_id": "r2",
            "completed": [],
            "failed": {},
            "current": None,
            "retry_policy": {"max_consecutive_failures": 3, "backoff_base_seconds": 5},
            "started_at": None,
            "updated_at": None,
            "results": {},
        })
        st = ExecutionState.load(sp)
        # Absent schema_version is considered legacy -> upgraded
        assert st.schema_version == _SCHEMA_VERSION

    def test_corrupted_state_file_is_handled_safely(self, simple_dag: DagDefinition, tmp_path: Path) -> None:
        sp = tmp_path / "corrupted_state.json"
        sp.write_text("NOT_JSON_AT_ALL", encoding="utf-8")
        st = ExecutionState.load(sp)
        assert st.completed == frozenset()
        # current impl returns empty run_id for existing-corrupted file;
        # key invariant is safe load + current schema_version
        assert st.schema_version == _SCHEMA_VERSION


# ===================================================================
# (b) Tests: atomic write
# ===================================================================


class TestAtomicWrite:
    def test_save_after_full_run_produces_valid_json(self, simple_dag: DagDefinition, tmp_path: Path) -> None:
        sp = tmp_path / "atomic_state.json"
        ex = Executor(dag=simple_dag, state_path=sp)
        ex.run()
        assert sp.exists()
        payload = json.loads(sp.read_text(encoding="utf-8"))
        assert payload["schema_version"] == _SCHEMA_VERSION
        assert payload["run_id"] == ex.state.run_id
        assert 1 in payload["completed"]

    def test_tmp_sibling_is_removed_after_save(self, simple_dag: DagDefinition, tmp_path: Path) -> None:
        """os.replace renames .tmp to final path atomically — no leftover."""
        sp = tmp_path / "no_tmp.json"
        tmp_candidate = sp.with_suffix(".tmp")
        ex = Executor(dag=simple_dag, state_path=sp)
        ex.run()
        assert sp.exists()
        assert not tmp_candidate.exists(), "State save leaked tmp file -- atomic rename incomplete"

    def test_full_run_is_idempotent(self, simple_dag: DagDefinition, tmp_path: Path) -> None:
        """Re-running the same DAG does not duplicate or corrupt state."""
        sp = tmp_path / "idempotent.json"
        ex = Executor(dag=simple_dag, state_path=sp)
        ex.run()
        first_read = sp.read_text(encoding="utf-8")
        ex2 = Executor(dag=simple_dag, state_path=sp)
        ex2.run()
        second_read = sp.read_text(encoding="utf-8")
        assert first_read == second_read


# ===================================================================
# (c) Tests: legacy upgrade field mapping
# ===================================================================


class TestLegacyUpgrade:
    def test_legacy_completed_and_failed_map(self, tmp_path: Path) -> None:
        sp = tmp_path / "legacy_fields.json"
        _write_state(sp, {
            "schema_version": "0.9",
            "run_id": "old",
            "completed": [3],
            "failed": {"5": "disk full"},
            "current": 4,
            "retry_policy": {"max_consecutive_failures": 5},
            "started_at": "2025-01-01T00:00:00+00:00",
            "updated_at": None,
            "results": {},
        })
        st = ExecutionState.load(sp)
        assert 3 in st.completed
        assert st.failed[5] == "disk full"
        assert st.retry_policy["max_consecutive_failures"] == 5

    def test_legacy_missing_retry_policy_uses_default(self, tmp_path: Path) -> None:
        sp = tmp_path / "legacy_no_retry.json"
        _write_state(sp, {
            "schema_version": "alpha",
            "run_id": "x",
            "completed": [],
            "failed": {},
            "current": None,
            "started_at": None,
            "updated_at": None,
            "results": {},
        })
        st = ExecutionState.load(sp)
        assert st.retry_policy == _RETRY_POLICY_DEFAULT

    def test_legacy_results_all_fields_round_trip(self, tmp_path: Path) -> None:
        sp = tmp_path / "legacy_results.json"
        _write_state(sp, {
            "schema_version": "legacy",
            "run_id": "run99",
            "completed": [11],
            "failed": {},
            "current": None,
            "retry_policy": {},
            "started_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:01+00:00",
            "results": {
                "11": {
                    "chapter": 11,
                    "status": "success",
                    "started_at": "s",
                    "finished_at": "f",
                    "error": None,
                    "fallback_chapters": [1, 2],
                },
                "12": {
                    "chapter": 12,
                    "status": "failed",
                    "started_at": None,
                    "finished_at": None,
                    "error": "boom",
                },
            },
        })
        st = ExecutionState.load(sp)
        r11 = st.results[11]
        r12 = st.results[12]
        assert r11.status == "success"
        assert r11.started_at == "s" and r11.finished_at == "f"
        assert r11.error is None and r11.fallback_chapters == [1, 2]
        assert r12.status == "failed"
        assert r12.error == "boom" and r12.started_at is None


# ===================================================================
# (d) Tests: full DAG end-to-end
# ===================================================================


class TestFullDagEndToEnd:
    @staticmethod
    def _three_node_dag() -> DagDefinition:
        n1 = ChapterNode(1, "Alpha", "agent-a", ["a"], "rule-a")
        n2 = ChapterNode(2, "Beta", "agent-b", ["b"], "rule-b")
        n3 = ChapterNode(3, "Gamma", "agent-c", ["c"], "rule-c")
        return DagDefinition(
            chapters={1: n1, 2: n2, 3: n3},
            edges={1: [], 2: [1], 3: [2]},
            human_only=frozenset(),
        )

    def test_all_nodes_executed(self, tmp_path: Path) -> None:
        dag = self._three_node_dag()
        calls: list[int] = []

        def fake(self2: Any, ch: int) -> ExecutionResult:
            calls.append(ch)
            return ExecutionResult(chapter=ch, status="success")

        ex = Executor(dag=dag, state_path=tmp_path / "state.json")
        with patch.object(Executor, "_execute_chapter", fake):
            ex.run()
        assert set(calls) == {1, 2, 3}
        assert len(ex.state.completed) == 3

    def test_execution_order_matches_dependencies(self, tmp_path: Path) -> None:
        dag = self._three_node_dag()
        calls: list[int] = []

        def fake(self2: Any, ch: int) -> ExecutionResult:
            calls.append(ch)
            return ExecutionResult(chapter=ch, status="success")

        ex = Executor(dag=dag, state_path=tmp_path / "state.json")
        with patch.object(Executor, "_execute_chapter", fake):
            ex.run()
        assert calls.index(1) < calls.index(2) < calls.index(3), (
            f"expected 1->2->3 got {calls}"
        )

    def test_node_1_is_first(self, tmp_path: Path) -> None:
        dag = self._three_node_dag()
        calls: list[int] = []

        def fake(self2: Any, ch: int) -> ExecutionResult:
            calls.append(ch)
            return ExecutionResult(chapter=ch, status="success")

        ex = Executor(dag=dag, state_path=tmp_path / "state.json")
        with patch.object(Executor, "_execute_chapter", fake):
            ex.run()
        assert calls[0] == 1
        assert 2 in calls and 3 in calls

    def test_resume_from_partial_state(self, tmp_path: Path) -> None:
        """ch1 already completed -> executor resumes at ch2."""
        dag = self._three_node_dag()
        sp = tmp_path / "resume_partial.json"
        ex = Executor(dag=dag, state_path=sp)
        ex.state.mark(ExecutionResult(chapter=1, status="success"))
        ex.state.save()
        calls: list[int] = []

        def fake(self2: Any, ch: int) -> ExecutionResult:
            calls.append(ch)
            return ExecutionResult(chapter=ch, status="success")

        with patch.object(Executor, "_execute_chapter", fake):
            ex2 = Executor(dag=dag, state_path=sp)
            ex2.run()
        # ch1 already complete -> only 2 and 3 should run
        assert calls == [2, 3]


# ===================================================================
# (e) Tests: recovery from failure at node 2
# ===================================================================


def _install_ch2_strategy(
    pattern: str,
    action: str,
    max_attempts: int = 3,
    fallback_chapters: list[int] | None = None,
) -> None:
    from src.core.binh_phap import recovery as rec
    register(
        "ch2:" + pattern,
        rec.RecoveryStrategy(
            failure_pattern=pattern,
            max_attempts=max_attempts,
            action=action,
            fallback_chapters=fallback_chapters or [],
            human_ok=False,
        ),
    )


class TestRecoveryFlowAtNode2:
    def test_retry_on_transient_timeout(self, simple_dag: DagDefinition, tmp_path: Path) -> None:
        """ch2 'timeout' -> retries 2x then succeeds."""
        sp = tmp_path / "retry_flow.json"
        _install_ch2_strategy("timeout", "retry", max_attempts=3)
        calls: list[int] = []

        def fake(self2: Any, ch: int) -> ExecutionResult:
            calls.append(ch)
            if ch == 1:
                return ExecutionResult(chapter=ch, status="success")
            if ch != 2:
                return ExecutionResult(chapter=ch, status="success")
            attempts = sum(1 for c in calls if c == 2)
            status = "success" if attempts >= 2 else "failed"
            return ExecutionResult(
                chapter=ch,
                status=status,
                error="timeout" if status == "failed" else "",
            )

        ex = Executor(dag=simple_dag, state_path=sp)
        with patch.object(Executor, "_execute_chapter", fake):
            ex.run()
        ch2_calls = sum(1 for c in calls if c == 2)
        assert ch2_calls >= 2, f"ch2 invoked {ch2_calls} times, expected >= 2"
        assert 3 in calls

    def test_fallback_after_retry_exhausted(self, fallback_dag: DagDefinition, tmp_path: Path) -> None:
        """ch8 fails after retries -> fallback chain to [1, 7]."""
        sp = tmp_path / "fallback_flow.json"
        from src.core.binh_phap import recovery as rec
        register(
            "ch8:fatal",
            rec.RecoveryStrategy(
                failure_pattern="timeout",
                max_attempts=3,
                action="fallback",
                fallback_chapters=[1, 7],
                human_ok=False,
            ),
        )
        calls: list[int] = []

        def fake(self2: Any, ch: int) -> ExecutionResult:
            calls.append(ch)
            if ch == 8:
                return ExecutionResult(chapter=8, status="failed", error="timeout")
            return ExecutionResult(chapter=ch, status="success")

        ex = Executor(dag=fallback_dag, state_path=sp)
        # Pre-complete fallbacks so they don't loop
        ex.state.mark(ExecutionResult(chapter=1, status="success"))
        ex.state.mark(ExecutionResult(chapter=7, status="success"))
        ex.state.save()
        with patch.object(Executor, "_execute_chapter", fake):
            ex.run()
        assert 8 in calls
        assert 1 in calls or 7 in calls

    def test_escalate_halts_retry_loop(self, simple_dag: DagDefinition, tmp_path: Path) -> None:
        """auth error -> escalate, no retry loop."""
        sp = tmp_path / "escalate_flow.json"
        _install_ch2_strategy("auth|quota|forbidden", "escalate", max_attempts=1)
        calls: list[int] = []

        def fake(self2: Any, ch: int) -> ExecutionResult:
            calls.append(ch)
            if ch == 2:
                return ExecutionResult(chapter=ch, status="failed", error="auth token expired")
            return ExecutionResult(chapter=ch, status="success")

        ex = Executor(dag=simple_dag, state_path=sp)
        with patch.object(Executor, "_execute_chapter", fake):
            ex.run()
        assert 1 in calls and 2 in calls
        assert ex.state.failed[2] == "auth token expired"
        # escalate -> no retry loop; ch2 invoked exactly once
        assert sum(1 for c in calls if c == 2) == 1

    def test_abort_stops_pipeline(self, simple_dag: DagDefinition, tmp_path: Path) -> None:
        """abort -> node 3 never runs."""
        sp = tmp_path / "abort_flow.json"
        _install_ch2_strategy("fail|boom", "abort", max_attempts=1)
        calls: list[int] = []

        def fake(self2: Any, ch: int) -> ExecutionResult:
            calls.append(ch)
            if ch == 2:
                return ExecutionResult(chapter=ch, status="failed", error="boom")
            return ExecutionResult(chapter=ch, status="success")

        ex = Executor(dag=simple_dag, state_path=sp)
        with patch.object(Executor, "_execute_chapter", fake):
            ex.run()
        assert calls == [1, 2]
        assert 3 not in calls, "Abort at ch2 must prevent ch3 from running"


# ===================================================================
# CLI-facing DAG utilities
# ===================================================================


class TestCliUtilities:
    def test_status_report_after_full_run(self, simple_dag: DagDefinition, tmp_path: Path) -> None:
        sp = tmp_path / "status_report.json"
        ex = Executor(dag=simple_dag, state_path=sp)
        ex.run()
        report = ex.status_report()
        assert report["completed_count"] == 3
        assert report["failed_count"] == 0
        assert any(r["status"] == "success" for r in report["chapters"])

    def test_resume_continues_from_last_completed(self, simple_dag: DagDefinition, tmp_path: Path) -> None:
        sp = tmp_path / "resume_status.json"
        ex = Executor(dag=simple_dag, state_path=sp)
        ex.state.mark(ExecutionResult(chapter=1, status="success"))
        ex.state.save()
        calls: list[int] = []

        def fake(self2: Any, ch: int) -> ExecutionResult:
            calls.append(ch)
            return ExecutionResult(chapter=ch, status="success")

        with patch.object(Executor, "_execute_chapter", fake):
            ex.resume()
        assert calls == [2, 3]
