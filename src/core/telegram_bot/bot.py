# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Telegram bot — main MekongBot class: setup, start, stop, notify."""

from __future__ import annotations

import contextlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml  # type: ignore[import-untyped]

from .handlers import BotHandlers

if TYPE_CHECKING:
    from telegram.ext import Application

    from src.core.orchestrator import OrchestrationResult

logger = logging.getLogger(__name__)


@dataclass
class BotConfig:
    """Telegram bot configuration."""

    token: str = ""
    chat_ids: list[int] = field(default_factory=list)
    enabled: bool = True


class MekongBot(BotHandlers):
    """Telegram bot — relay commands to Mekong CLI for CC CLI coordination."""

    CONFIG_PATH = ".mekong/telegram.yaml"

    def __init__(self, token: str | None = None) -> None:
        """Initialize MekongBot with a Telegram bot token.

        Args:
            token: Telegram Bot API token. Falls back to MEKONG_TELEGRAM_TOKEN env var.

        """
        self.token = token or os.environ.get("MEKONG_TELEGRAM_TOKEN", "")
        self.config = self._load_config()
        self._running = False
        self._application: Application | None = None

    async def start(self) -> None:
        """Start the Telegram bot polling loop."""
        if not self.token:
            return

        try:
            from telegram.ext import (
                ApplicationBuilder,
                CallbackQueryHandler,
                CommandHandler,
                MessageHandler,
                filters,
            )
        except ImportError:
            return

        self._application = ApplicationBuilder().token(self.token).build()

        # Task relay commands
        self._application.add_handler(CommandHandler("cook", self.cook_handler))
        self._application.add_handler(CommandHandler("spawn", self.spawn_handler))
        self._application.add_handler(CommandHandler("tasks", self.tasks_handler))
        self._application.add_handler(CommandHandler("sessions", self.sessions_handler))

        # Original commands
        self._application.add_handler(CommandHandler("cmd", self.cmd_handler))
        self._application.add_handler(CommandHandler("status", self.status_handler))
        self._application.add_handler(CommandHandler("schedule", self.schedule_handler))
        self._application.add_handler(CommandHandler("swarm", self.swarm_handler))
        self._application.add_handler(CommandHandler("memory", self.memory_handler))
        self._application.add_handler(CommandHandler("help", self.help_handler))
        self._application.add_handler(CommandHandler("start", self.help_handler))

        # AGI commands
        self._application.add_handler(CommandHandler("agi", self.agi_handler))

        # HEARTBEAT & Jidoka commands
        self._application.add_handler(CommandHandler("heartbeat", self.heartbeat_handler))
        self._application.add_handler(CommandHandler("alerts", self.alerts_handler))
        self._application.add_handler(CommandHandler("health", self.health_handler))

        # NLP: catch ALL non-command text messages
        self._application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.nlp_message_handler),
        )

        self._application.add_handler(CallbackQueryHandler(self._callback_handler))

        self._running = True
        await self._application.initialize()
        await self._application.start()
        await self._application.updater.start_polling()

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False
        if self._application:
            try:
                await self._application.updater.stop()
                await self._application.stop()
                await self._application.shutdown()
            except Exception as e:
                logger.error("Failed to stop application: %s", e)

    def is_running(self) -> bool:
        """Whether the Telegram bot polling loop is currently active."""
        return self._running

    async def send_notification(self, chat_id: int, message: str) -> None:
        """Send a push notification to a specific chat."""
        if not self._application or not self._running:
            return
        with contextlib.suppress(Exception):
            await self._application.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown",
            )

    def _execute_goal(self, goal: str) -> OrchestrationResult:
        """Execute goal via orchestrator (runs in thread)."""
        from src.providers.llm.client import get_client
        from src.core.orchestrator import RecipeOrchestrator

        llm_client = get_client()
        orchestrator = RecipeOrchestrator(
            llm_client=llm_client if llm_client.is_available else None,
        )
        return orchestrator.run_from_goal(goal)

    def _load_config(self) -> BotConfig:
        """Load bot config from .mekong/telegram.yaml."""
        path = Path(self.CONFIG_PATH)
        if not path.exists():
            return BotConfig(token=self.token)
        try:
            data = yaml.safe_load(path.read_text()) or {}
            return BotConfig(
                token=self.token,
                chat_ids=data.get("chat_ids", []),
                enabled=data.get("enabled", True),
            )
        except Exception as e:
            logger.debug("Failed to load bot config: %s", e)
            return BotConfig(token=self.token)

    def _save_config(self) -> None:
        """Save bot config to .mekong/telegram.yaml."""
        path = Path(self.CONFIG_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "chat_ids": self.config.chat_ids,
            "enabled": self.config.enabled,
        }
        path.write_text(yaml.dump(data, default_flow_style=False))

    def _format_result(self, result: OrchestrationResult | None) -> str:
        """Format OrchestrationResult for Telegram message (instance wrapper)."""
        from .formatters import format_result
        return format_result(result)

    def _build_keyboard(self):  # type: ignore[return]
        """Build inline keyboard for quick actions (instance wrapper)."""
        from .formatters import build_keyboard
        return build_keyboard()


__all__ = [
    "BotConfig",
    "MekongBot",
]
