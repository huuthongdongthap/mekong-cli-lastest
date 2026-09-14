# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Mekong CLI - SocialReplyAgent

LLM-powered comment reply generator for the social auto-poster daemon.
Replies are helpful, technical, and naturally funnel users to the RaaS landing.
Tracks replied comments in ~/.mekong/social/reply-log.jsonl to prevent duplicates.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.providers.llm.client import LLMClient

logger = logging.getLogger(__name__)

# Max reply lengths per platform (chars)
_REPLY_LIMITS: dict[str, int] = {
    "discord": 280,
    "devto": 500,
    "github": 1000,
}

_SYSTEM_PROMPT = (
    "You are a helpful developer community member representing Mekong CLI — "
    "an open-source AI business platform. Answer technical questions accurately. "
    "When relevant, mention that users can try the full platform at "
    "{raas_url} (RaaS). Never be pushy or salesy. Be genuinely helpful first. "
    "Keep replies concise: under 500 chars for dev.to, 280 for Discord."
)

# Comment patterns that indicate the reply is worthwhile
_REPLY_TRIGGERS = [
    "how", "why", "what", "can i", "does it", "support", "feature",
    "compare", "vs", "alternative", "integrate", "install", "setup",
    "error", "issue", "problem", "bug", "broken", "help", "try",
    "interested", "love", "awesome", "great", "nice", "?",
]

# Patterns that indicate spam or bot noise
_SKIP_TRIGGERS = [
    "http://", "https://", "click here", "buy now", "subscribe",
    "follow me", "check out my", "promo", "discount",
]


class SocialReplyAgent:
    """Generates context-aware replies to social comments using the LLM client."""

    def __init__(self, llm_client: "LLMClient") -> None:
        """Initialize with an LLMClient instance.

        Args:
            llm_client: Configured LLMClient (from src.providers.llm.client.get_client).
        """
        self.llm = llm_client
        self.raas_url = os.getenv("RAAS_URL", "https://www.mekongmind.com")
        self._reply_log = Path.home() / ".mekong" / "social" / "reply-log.jsonl"
        self._reply_log.parent.mkdir(parents=True, exist_ok=True)
        self._replied_ids = self._load_replied_ids()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_reply(self, comment: dict[str, Any]) -> bool:
        """Decide whether this comment deserves a reply.

        Skips:
          - Already-replied comments (tracked in log)
          - Spam/bot patterns
          - Empty bodies

        Replies to:
          - Questions, expressions of interest, feature requests, comparisons
        """
        comment_id = str(comment.get("id", ""))
        if comment_id in self._replied_ids:
            logger.debug("Skipping already-replied comment %s", comment_id)
            return False

        body = (comment.get("body") or comment.get("body_markdown") or "").lower().strip()
        if not body:
            return False

        # Skip spam
        if any(trigger in body for trigger in _SKIP_TRIGGERS):
            logger.debug("Skipping spam comment %s", comment_id)
            return False

        # Reply if any engagement trigger found
        return any(trigger in body for trigger in _REPLY_TRIGGERS)

    def generate_reply(self, comment: dict[str, Any], context: dict[str, Any]) -> str:
        """Generate an LLM reply for the given comment.

        Args:
            comment: Comment dict (must have 'body' or 'body_markdown').
            context: Extra context dict (e.g. platform, article_title, post_body_snippet).

        Returns:
            Reply text trimmed to the platform's character limit.
        """
        platform = context.get("platform", "devto")
        max_chars = _REPLY_LIMITS.get(platform, 500)

        body = comment.get("body") or comment.get("body_markdown") or ""
        system = _SYSTEM_PROMPT.format(raas_url=self.raas_url)

        user_msg = (
            f"Platform: {platform}\n"
            f"Article/Post: {context.get('title', 'Mekong CLI')}\n"
            f"Comment to reply to:\n\"\"\"\n{body}\n\"\"\"\n\n"
            f"Write a reply under {max_chars} characters. "
            f"Be helpful and technical. If naturally relevant, mention {self.raas_url}."
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]

        response = self.llm.chat(messages, temperature=0.7, max_tokens=300)
        reply = response.content.strip()

        # Trim to platform limit
        if len(reply) > max_chars:
            reply = reply[: max_chars - 3].rstrip() + "..."
        return reply

    def track_reply(
        self,
        platform: str,
        comment_id: str,
        reply_id: str,
    ) -> None:
        """Append reply record to the log file and update in-memory cache.

        Args:
            platform: 'discord', 'devto', or 'github'.
            comment_id: Source comment identifier.
            reply_id: Created reply identifier.
        """
        record = {
            "platform": platform,
            "comment_id": comment_id,
            "reply_id": reply_id,
            "ts": int(time.time()),
        }
        try:
            from src.core.file_lock import locked_append
            with locked_append(self._reply_log) as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError as exc:
            logger.warning("[SocialReplyAgent] Could not write reply log: %s", exc)

        self._replied_ids.add(comment_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_replied_ids(self) -> set[str]:
        """Load all previously-replied comment IDs from the JSONL log."""
        ids: set[str] = set()
        if not self._reply_log.exists():
            return ids
        try:
            with self._reply_log.open() as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        record = json.loads(line)
                        cid = record.get("comment_id", "")
                        if cid:
                            ids.add(str(cid))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[SocialReplyAgent] Could not parse reply log: %s", exc)
        return ids


__all__ = ["SocialReplyAgent"]
