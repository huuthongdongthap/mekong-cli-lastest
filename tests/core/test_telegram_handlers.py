"""Unit tests for src/core/telegram_handlers.py."""
from __future__ import annotations

import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ------------------------------------------------------------------
# Stub the 'telegram' package so the module imports without it installed.
# ------------------------------------------------------------------
def _stub_telegram():
    telegram_mod = types.ModuleType("telegram")
    telegram_mod.Update = MagicMock
    sys.modules.setdefault("telegram", telegram_mod)

    ext_mod = types.ModuleType("telegram.ext")
    ext_mod.ContextTypes = MagicMock
    sys.modules.setdefault("telegram.ext", ext_mod)

_stub_telegram()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_update(chat_id: int = 12345) -> MagicMock:
    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.effective_chat.id = chat_id
    return update


def _make_context(*args: str) -> MagicMock:
    ctx = MagicMock()
    ctx.args = list(args) if args else []
    return ctx


def _make_config(chat_ids: list | None = None) -> MagicMock:
    cfg = MagicMock()
    cfg.chat_ids = chat_ids if chat_ids is not None else []
    return cfg


# ---------------------------------------------------------------------------
# _format_result
# ---------------------------------------------------------------------------

class TestFormatResult:
    def test_none_result(self):
        from src.core.telegram_handlers import _format_result
        assert "failed" in _format_result(None).lower()

    def test_result_without_status(self):
        from src.core.telegram_handlers import _format_result
        out = _format_result("raw string")
        assert "raw string" in out

    def test_success_result(self):
        from src.core.telegram_handlers import _format_result
        result = MagicMock()
        result.status.value = "success"
        result.completed_steps = 3
        result.total_steps = 3
        result.success_rate = 100.0
        result.errors = []
        out = _format_result(result)
        assert "SUCCESS" in out
        assert "3/3" in out

    def test_failure_result_with_errors(self):
        from src.core.telegram_handlers import _format_result
        result = MagicMock()
        result.status.value = "failed"
        result.completed_steps = 1
        result.total_steps = 3
        result.success_rate = 33.0
        result.errors = ["err1", "err2"]
        out = _format_result(result)
        assert "FAILED" in out
        assert "err1" in out

    def test_errors_capped_at_three(self):
        from src.core.telegram_handlers import _format_result
        result = MagicMock()
        result.status.value = "failed"
        result.completed_steps = 0
        result.total_steps = 1
        result.success_rate = 0.0
        result.errors = ["e1", "e2", "e3", "e4", "e5"]
        out = _format_result(result)
        # Only first 3 errors joined
        assert "e4" not in out
        assert "e1" in out


# ---------------------------------------------------------------------------
# cook_handler
# ---------------------------------------------------------------------------

class TestCookHandler:
    @pytest.mark.asyncio
    async def test_no_goal_shows_usage(self):
        from src.core.telegram_handlers import cook_handler
        update = _make_update()
        ctx = _make_context()  # no args
        cfg = _make_config()
        await cook_handler(update, ctx, cfg, MagicMock())
        update.message.reply_text.assert_awaited_once()
        text = update.message.reply_text.call_args[0][0]
        assert "Usage" in text

    @pytest.mark.asyncio
    async def test_valid_goal_queues_task(self):
        from src.core.telegram_handlers import cook_handler
        update = _make_update(chat_id=999)
        ctx = _make_context("Build", "auth", "module")
        cfg = _make_config()
        save_cfg = MagicMock()

        fake_task = {"id": "abc123", "created_at_iso": "2026-01-01T00:00:00Z"}
        with patch("src.core.telegram_handlers.add_task", return_value=fake_task) as mock_add:
            await cook_handler(update, ctx, cfg, save_cfg)

        mock_add.assert_called_once_with(goal="Build auth module", chat_id=999)
        update.message.reply_text.assert_awaited_once()
        text = update.message.reply_text.call_args[0][0]
        assert "abc123" in text

    @pytest.mark.asyncio
    async def test_new_chat_id_appended_to_config(self):
        from src.core.telegram_handlers import cook_handler
        update = _make_update(chat_id=777)
        ctx = _make_context("fix", "it")
        cfg = _make_config(chat_ids=[])
        save_cfg = MagicMock()

        with patch("src.core.telegram_handlers.add_task", return_value={"id": "x", "created_at_iso": ""}):
            await cook_handler(update, ctx, cfg, save_cfg)

        assert 777 in cfg.chat_ids
        save_cfg.assert_called_once()

    @pytest.mark.asyncio
    async def test_existing_chat_id_not_duplicated(self):
        from src.core.telegram_handlers import cook_handler
        update = _make_update(chat_id=111)
        ctx = _make_context("task")
        cfg = _make_config(chat_ids=[111])
        save_cfg = MagicMock()

        with patch("src.core.telegram_handlers.add_task", return_value={"id": "y", "created_at_iso": ""}):
            await cook_handler(update, ctx, cfg, save_cfg)

        assert cfg.chat_ids.count(111) == 1
        save_cfg.assert_not_called()


# ---------------------------------------------------------------------------
# spawn_handler
# ---------------------------------------------------------------------------

class TestSpawnHandler:
    @pytest.mark.asyncio
    async def test_insufficient_args_shows_usage(self):
        from src.core.telegram_handlers import spawn_handler
        update = _make_update()
        ctx = _make_context("only-one-arg")
        cfg = _make_config()
        await spawn_handler(update, ctx, cfg, MagicMock())
        text = update.message.reply_text.call_args[0][0]
        assert "Usage" in text

    @pytest.mark.asyncio
    async def test_no_args_shows_usage(self):
        from src.core.telegram_handlers import spawn_handler
        update = _make_update()
        ctx = _make_context()
        cfg = _make_config()
        await spawn_handler(update, ctx, cfg, MagicMock())
        text = update.message.reply_text.call_args[0][0]
        assert "Usage" in text

    @pytest.mark.asyncio
    async def test_valid_spawn_queues_task_with_project(self):
        from src.core.telegram_handlers import spawn_handler
        update = _make_update(chat_id=42)
        ctx = _make_context("agencyos-web", "Add", "sidebar")
        cfg = _make_config()
        save_cfg = MagicMock()

        fake_task = {"id": "spawn1", "created_at_iso": "2026-01-01T00:00:00Z"}
        with patch("src.core.telegram_handlers.add_task", return_value=fake_task) as mock_add:
            await spawn_handler(update, ctx, cfg, save_cfg)

        mock_add.assert_called_once_with(goal="Add sidebar", project="agencyos-web", chat_id=42)
        text = update.message.reply_text.call_args[0][0]
        assert "agencyos-web" in text


# ---------------------------------------------------------------------------
# tasks_handler
# ---------------------------------------------------------------------------

class TestTasksHandler:
    @pytest.mark.asyncio
    async def test_empty_inbox(self):
        from src.core.telegram_handlers import tasks_handler
        update = _make_update()
        with patch("src.core.telegram_handlers._load_inbox", return_value=[]):
            await tasks_handler(update, _make_context())
        text = update.message.reply_text.call_args[0][0]
        assert "empty" in text.lower() or "Inbox" in text

    @pytest.mark.asyncio
    async def test_shows_last_10_tasks(self):
        from src.core.telegram_handlers import tasks_handler
        tasks = [
            {
                "id": f"t{i}",
                "status": "pending",
                "goal": f"Goal {i}",
                "created_at_iso": "2026-01-01T00:00:00Z",
            }
            for i in range(15)
        ]
        update = _make_update()
        with patch("src.core.telegram_handlers._load_inbox", return_value=tasks):
            await tasks_handler(update, _make_context())
        text = update.message.reply_text.call_args[0][0]
        # Last 10 tasks only (indices 5-14)
        assert "t14" in text
        assert "t4" not in text

    @pytest.mark.asyncio
    async def test_status_icons_rendered(self):
        from src.core.telegram_handlers import tasks_handler
        tasks = [
            {"id": "a", "status": "running", "goal": "run", "created_at_iso": ""},
            {"id": "b", "status": "completed", "goal": "done", "created_at_iso": ""},
            {"id": "c", "status": "failed", "goal": "fail", "created_at_iso": ""},
            {"id": "d", "status": "unknown_status", "goal": "huh", "created_at_iso": ""},
        ]
        update = _make_update()
        with patch("src.core.telegram_handlers._load_inbox", return_value=tasks):
            await tasks_handler(update, _make_context())
        text = update.message.reply_text.call_args[0][0]
        assert "🔄" in text  # running
        assert "✅" in text  # completed
        assert "❌" in text  # failed
        assert "❓" in text  # unknown

    @pytest.mark.asyncio
    async def test_project_displayed_when_present(self):
        from src.core.telegram_handlers import tasks_handler
        tasks = [
            {"id": "p1", "status": "pending", "goal": "build", "created_at_iso": "", "project": "myapp"},
        ]
        update = _make_update()
        with patch("src.core.telegram_handlers._load_inbox", return_value=tasks):
            await tasks_handler(update, _make_context())
        text = update.message.reply_text.call_args[0][0]
        assert "myapp" in text


# ---------------------------------------------------------------------------
# sessions_handler
# ---------------------------------------------------------------------------

class TestSessionsHandler:
    @pytest.mark.asyncio
    async def test_no_sessions_message(self):
        from src.core.telegram_handlers import sessions_handler
        update = _make_update()
        mock_spawner = MagicMock()
        mock_spawner.all_sessions = []
        with patch("src.core.telegram_handlers.sessions_handler.__module__"):
            pass
        with patch("src.core.cc_spawner.get_spawner", return_value=mock_spawner, create=True):
            with patch.dict("sys.modules", {"src.core.cc_spawner": MagicMock(get_spawner=lambda: mock_spawner)}):
                await sessions_handler(update, _make_context())
        update.message.reply_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_falls_back_gracefully(self):
        from src.core.telegram_handlers import sessions_handler
        update = _make_update()
        with patch.dict("sys.modules", {"src.core.cc_spawner": None}):
            await sessions_handler(update, _make_context())
        update.message.reply_text.assert_awaited_once()
        text = update.message.reply_text.call_args[0][0]
        assert "No CC CLI" in text or "session" in text.lower()


# ---------------------------------------------------------------------------
# status_handler
# ---------------------------------------------------------------------------

class TestStatusHandler:
    @pytest.mark.asyncio
    async def test_status_message_contains_stats(self):
        from src.core.telegram_handlers import status_handler
        update = _make_update()

        mock_store = MagicMock()
        mock_store.stats.return_value = {
            "total": 10,
            "success_rate": 90.0,
            "recent_failures": 1,
        }
        mock_pending = [MagicMock(), MagicMock()]

        # MemoryStore / get_pending_tasks are imported inside status_handler body
        with patch("src.core.memory_canonical.MemoryStore", return_value=mock_store):
            with patch("src.core.telegram_handlers.get_pending_tasks", return_value=mock_pending):
                with patch.dict("sys.modules", {"src.core.cc_spawner": None}):
                    await status_handler(update, _make_context())

        text = update.message.reply_text.call_args[0][0]
        assert "90.0" in text
        assert "10" in text
        assert "2 pending" in text


# ---------------------------------------------------------------------------
# schedule_handler
# ---------------------------------------------------------------------------

class TestScheduleHandler:
    @pytest.mark.asyncio
    async def test_no_jobs(self):
        from src.core.telegram_handlers import schedule_handler
        update = _make_update()
        mock_sched = MagicMock()
        mock_sched.list_jobs.return_value = []
        # Scheduler is imported inside the handler body
        with patch("src.core.scheduler.Scheduler", return_value=mock_sched):
            await schedule_handler(update, _make_context())
        text = update.message.reply_text.call_args[0][0]
        assert "No scheduled" in text

    @pytest.mark.asyncio
    async def test_jobs_listed(self):
        from src.core.telegram_handlers import schedule_handler
        update = _make_update()
        job = MagicMock()
        job.name = "daily_report"
        job.goal = "Generate daily report"
        job.job_type = "cron"
        mock_sched = MagicMock()
        mock_sched.list_jobs.return_value = [job]
        with patch("src.core.scheduler.Scheduler", return_value=mock_sched):
            await schedule_handler(update, _make_context())
        text = update.message.reply_text.call_args[0][0]
        assert "daily_report" in text


# ---------------------------------------------------------------------------
# memory_handler
# ---------------------------------------------------------------------------

class TestMemoryHandler:
    @pytest.mark.asyncio
    async def test_no_entries(self):
        from src.core.telegram_handlers import memory_handler
        update = _make_update()
        mock_store = MagicMock()
        mock_store.recent.return_value = []
        # MemoryStore imported inside handler body
        with patch("src.core.memory_canonical.MemoryStore", return_value=mock_store):
            await memory_handler(update, _make_context())
        text = update.message.reply_text.call_args[0][0]
        assert "No memory" in text

    @pytest.mark.asyncio
    async def test_entries_displayed_with_icon(self):
        from src.core.telegram_handlers import memory_handler
        update = _make_update()
        entry = MagicMock()
        entry.status = "success"
        entry.goal = "Build auth"
        mock_store = MagicMock()
        mock_store.recent.return_value = [entry]
        with patch("src.core.memory_canonical.MemoryStore", return_value=mock_store):
            await memory_handler(update, _make_context())
        text = update.message.reply_text.call_args[0][0]
        assert "✅" in text
        assert "Build auth" in text


# ---------------------------------------------------------------------------
# cmd_handler
# ---------------------------------------------------------------------------

class TestCmdHandler:
    @pytest.mark.asyncio
    async def test_no_goal_shows_usage(self):
        from src.core.telegram_handlers import cmd_handler
        update = _make_update()
        ctx = _make_context()
        await cmd_handler(update, ctx)
        text = update.message.reply_text.call_args[0][0]
        assert "Usage" in text

    @pytest.mark.asyncio
    async def test_valid_goal_runs_orchestrator(self):
        from src.core.telegram_handlers import cmd_handler
        update = _make_update()
        ctx = _make_context("do", "something")

        mock_client = MagicMock()
        mock_client.is_available = True
        mock_result = MagicMock()
        mock_result.status.value = "success"
        mock_result.completed_steps = 1
        mock_result.total_steps = 1
        mock_result.success_rate = 100.0
        mock_result.errors = []
        mock_orchestrator = MagicMock()
        mock_orchestrator.run_from_goal.return_value = mock_result

        # get_client / RecipeOrchestrator are imported inside the handler body
        with patch("src.providers.llm.client.get_client", return_value=mock_client):
            with patch("src.core.orchestrator.RecipeOrchestrator", return_value=mock_orchestrator):
                await cmd_handler(update, ctx)

        assert update.message.reply_text.await_count == 2  # "Executing..." + result
        final_text = update.message.reply_text.call_args_list[1][0][0]
        assert "SUCCESS" in final_text
