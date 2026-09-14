# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""
Mekong Daemon - Scheduler

Main loop: watch → classify → validate → execute → gate → journal → archive/dlq.
Single-process daemon with graceful shutdown. Security-hardened: all mission
content is sanitized and allowlisted before execution (fail-closed).
"""

import logging
import signal
import time
from pathlib import Path
from typing import Dict, Optional, Set

from .watcher import TaskWatcher
from .classifier import ComplexityClassifier
from .executor import MissionExecutor
from .gate import PostGate
from .journal import LearningJournal
from .dlq import DeadLetterQueue

logger = logging.getLogger(__name__)

# Conservative default allowlist (read-only/emit-only commands; operator extends via config).
_DEFAULT_ALLOWED_COMMANDS: Set[str] = {
    "echo", "ls", "cat", "pwd", "date", "head", "tail", "wc",
}


class DaemonScheduler:
    """Autonomous daemon that watches for missions and executes them.

    Security: content is validated through CommandSanitizer(strict_mode=True)
    and allowlist before execution (fail-closed on import error). Violations
    are moved to DLQ with a reason.  No env-bypass exists.

    Args:
        config: Dict with watch_dir, poll_interval, max_retries, allowed_commands, etc.
    """

    def __init__(self, config: Optional[Dict] = None) -> None:
        cfg = config or {}
        self._watch_dir = cfg.get("watch_dir", "./tasks")
        self._poll_interval = cfg.get("poll_interval_secs", 5)
        self._max_retries = cfg.get("max_retries", 3)
        self._running = False

        # Sanitizer: fail-closed if import fails
        try:
            from src.core.command_sanitizer import CommandSanitizer
            self._sanitizer = CommandSanitizer(strict_mode=True)
        except ImportError:
            logger.critical(
                "CommandSanitizer unavailable — daemon will block ALL missions (fail-closed)"
            )
            self._sanitizer = None

        # Allowlist: config merges with built-in conservative defaults
        self._allowed_commands: Set[str] = set(cfg.get("allowed_commands", set()))
        self._allowed_commands |= _DEFAULT_ALLOWED_COMMANDS

        self.watcher = TaskWatcher(
            watch_dir=self._watch_dir,
            poll_interval=self._poll_interval,
        )
        self.classifier = ComplexityClassifier(cfg.get("complexity"))
        self.executor = MissionExecutor(
            working_dir=cfg.get("working_dir", "."),
            timeout=cfg.get("default_timeout", 1800),
        )
        self.gate = PostGate(
            verify_commands=cfg.get("verify_commands", []),
            working_dir=cfg.get("working_dir", "."),
        )
        self.journal = LearningJournal(cfg.get("journal_path", ".mekong/daemon-journal.jsonl"))
        self.dlq = DeadLetterQueue(cfg.get("dlq_dir", f"{self._watch_dir}/dead-letter"))
        self._retry_counts: Dict[str, int] = {}

    def start(self) -> None:
        """Start the daemon main loop. Blocks until stopped."""
        self._running = True
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        logger.info("Daemon started — watching %s (poll: %ds)", self._watch_dir, self._poll_interval)

        while self._running:
            missions = self.watcher.scan_once()
            for mission_path in missions:
                if not self._running:
                    break
                self._process_mission(mission_path)
            time.sleep(self._poll_interval)

        logger.info("Daemon stopped gracefully")

    def stop(self) -> None:
        """Signal the daemon to stop."""
        self._running = False

    def _handle_signal(self, signum: int, frame) -> None:
        logger.info("Received signal %d — shutting down", signum)
        self.stop()

    def _validate_content(self, content: str, mission_path: Path) -> Optional[str]:
        """Validate content via sanitizer + allowlist. Returns None if OK, else reason."""
        if self._sanitizer is None:
            return "CommandSanitizer unavailable — fail-closed"
        san_result = self._sanitizer.sanitize(content)
        if not san_result.is_safe:
            # Strict-mode suspicious blocks leave blocked_reason empty —
            # always produce a non-empty DLQ reason from blocked_patterns.
            return san_result.blocked_reason or (
                "Blocked by sanitizer patterns: "
                f"{', '.join(san_result.blocked_patterns)}"
            )
        tokens = content.split()
        first_token = tokens[0] if tokens else ""
        if first_token not in self._allowed_commands:
            return (
                f"First command '{first_token}' not in allowlist "
                f"(allowed: {sorted(self._allowed_commands)})"
            )
        return None

    def _process_mission(self, mission_path: Path) -> None:
        """Process a single mission file."""
        name = mission_path.name
        logger.info("Processing mission: %s", name)

        # Reject symlinks (could point outside watch_dir)
        if mission_path.is_symlink():
            logger.warning("Mission is a symlink — blocking: %s", name)
            self.dlq.move_to_dlq(
                mission_path, reason="Symlink rejected",
            )
            return

        try:
            content = mission_path.read_text().strip()
        except Exception as e:
            logger.error("Cannot read mission %s: %s", name, e)
            self.watcher.mark_processed(mission_path)
            return

        # --- Security gate: validate before any execution ---
        block_reason = self._validate_content(content, mission_path)
        if block_reason is not None:
            logger.warning("Mission blocked by security gate: %s (%s)", name, block_reason)
            self.dlq.move_to_dlq(mission_path, reason=block_reason)
            self.journal.record_mission(
                mission=name, complexity="unknown",
                success=False, duration=0.0, error=block_reason,
            )
            return

        classification = self.classifier.classify(content)
        logger.info("Classified: %s → %s (timeout: %ds)", name, classification.level, classification.timeout)

        result = self.executor.run_shell(content, timeout=classification.timeout)

        if result.success and self.gate.check():
            self.journal.record_mission(
                mission=name, complexity=classification.level,
                success=True, duration=result.duration,
            )
            self.watcher.archive(mission_path)
            logger.info("Mission completed: %s (%.1fs)", name, result.duration)
        else:
            retries = self._retry_counts.get(name, 0) + 1
            self._retry_counts[name] = retries

            if retries >= self._max_retries:
                reason = result.error or "Max retries exceeded"
                self.dlq.move_to_dlq(mission_path, reason)
                self.journal.record_mission(
                    mission=name, complexity=classification.level,
                    success=False, duration=result.duration, error=reason,
                )
                del self._retry_counts[name]
                logger.warning("Mission failed → DLQ: %s (%s)", name, reason)
            else:
                logger.info("Mission retry %d/%d: %s", retries, self._max_retries, name)

    def status(self) -> Dict:
        """Return daemon status summary."""
        return {
            "running": self._running,
            "watch_dir": self._watch_dir,
            "pending": len(self.watcher.scan_once()),
            "dead_letters": self.dlq.count,
            "success_rate": self.journal.success_rate(),
        }


__all__ = ["DaemonScheduler"]
