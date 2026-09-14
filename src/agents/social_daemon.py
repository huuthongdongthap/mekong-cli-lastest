# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Mekong CLI - SocialDaemon

Publishes content + polls comments + auto-replies via LLM.
Runs on M1 Max via PM2/launchd. See scripts/social-daemon.sh.
"""

from __future__ import annotations

import json
import logging
import signal
import time
from pathlib import Path
from typing import Any

from src.providers.llm.client import get_client
from .social_poster_agent import SocialPosterAgent
from .social_reply_agent import SocialReplyAgent
from .social_daemon_helpers import parse_frontmatter, build_arg_parser

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

STATE_PATH = Path.home() / ".mekong" / "social" / "daemon-state.json"


class SocialDaemon:
    """Main daemon: poll + reply loop, and content publishing."""

    def __init__(self) -> None:
        self.poster = SocialPosterAgent()
        self.replier = SocialReplyAgent(get_client())
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._running = True
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        signal.signal(signal.SIGINT, self._handle_sigterm)

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        """Load daemon state (last-checked timestamps, monitored items)."""
        if STATE_PATH.exists():
            try:
                return json.loads(STATE_PATH.read_text())
            except (OSError, json.JSONDecodeError):
                pass
        return {"devto": {}, "github": {}, "last_run": 0}

    def _save_state(self, state: dict[str, Any]) -> None:
        try:
            STATE_PATH.write_text(json.dumps(state, indent=2))
        except OSError as exc:
            logger.warning("Could not save daemon state: %s", exc)

    # ------------------------------------------------------------------
    # Publish content
    # ------------------------------------------------------------------

    def publish_content(self, content_path: str, platforms: list[str]) -> dict[str, str]:
        """Read a markdown file and post it to the specified platforms.

        Supports YAML front-matter with: title, tags, gh_repo, gh_category_id.

        Returns:
            Dict mapping platform → URL (or 'posted' / '' on Discord).
        """
        path = Path(content_path)
        if not path.exists():
            logger.error("Content file not found: %s", content_path)
            return {}

        raw = path.read_text(encoding="utf-8")
        title, tags, body, meta = parse_frontmatter(raw)
        urls: dict[str, str] = {}

        if "discord" in platforms:
            msg = f"**{title}**\n\n{body[:1800]}"
            ok = self.poster.post_to_discord(msg)
            urls["discord"] = "posted" if ok else ""
            logger.info("[daemon] Discord: %s", urls["discord"])

        if "devto" in platforms:
            result = self.poster.post_to_devto(title, body, tags)
            urls["devto"] = result.get("url", "")
            logger.info("[daemon] dev.to: %s", urls["devto"])

        if "github" in platforms:
            gh_repo = meta.get("gh_repo", "")
            gh_cat = meta.get("gh_category_id", "")
            if gh_repo and gh_cat:
                result = self.poster.create_gh_discussion(gh_repo, gh_cat, title, body)
                urls["github"] = result.get("url", "")
                logger.info("[daemon] GitHub Discussions: %s", urls["github"])
            else:
                logger.warning("[daemon] gh_repo / gh_category_id missing in front-matter")

        return urls

    # ------------------------------------------------------------------
    # Poll + reply
    # ------------------------------------------------------------------

    def poll_and_reply(self) -> None:
        """Fetch new comments across all monitored items and reply where appropriate."""
        state = self._load_state()
        self._poll_devto(state)
        self._poll_github(state)
        state["last_run"] = int(time.time())
        self._save_state(state)

    def _poll_devto(self, state: dict[str, Any]) -> None:  # noqa: C901
        """Poll dev.to articles for new comments and auto-reply."""
        for article_id_str, info in state.get("devto", {}).items():
            article_id = int(article_id_str)
            comments = self.poster.get_devto_comments(article_id)
            last_seen: set[str] = set(info.get("seen_ids", []))
            ctx = {"platform": "devto", "title": info.get("title", "")}
            for c in comments:
                cid = str(c.get("id"))
                if cid not in last_seen and self.replier.should_reply(c):
                    r = self.poster.reply_devto_comment(article_id, int(c["id"]),
                                                        self.replier.generate_reply(c, ctx))
                    if r.get("id"):
                        self.replier.track_reply("devto", cid, str(r["id"]))
                last_seen.add(cid)
            info["seen_ids"] = list(last_seen)

    def _poll_github(self, state: dict[str, Any]) -> None:
        """Poll GitHub Discussions for new comments and auto-reply."""
        for _key, info in state.get("github", {}).items():
            repo, number, disc_id = info.get("repo", ""), int(info.get("number", 0)), info.get("id", "")
            if not repo or not number:
                continue
            comments = self.poster.get_gh_discussion_comments(repo, number)
            last_seen: set[str] = set(info.get("seen_ids", []))
            ctx = {"platform": "github", "title": info.get("title", "")}
            for c in comments:
                cid = str(c.get("id"))
                if cid not in last_seen and self.replier.should_reply(c):
                    r = self.poster.reply_gh_discussion(repo, disc_id,
                                                        self.replier.generate_reply(c, ctx))
                    if r.get("id"):
                        self.replier.track_reply("github", cid, str(r["id"]))
                last_seen.add(cid)
            info["seen_ids"] = list(last_seen)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_loop(self, interval_minutes: int = 60) -> None:
        """Main daemon loop — poll every `interval_minutes`."""
        logger.info("[daemon] Starting (interval=%dm)", interval_minutes)
        interval_secs = interval_minutes * 60

        while self._running:
            try:
                self.poll_and_reply()
            except Exception:
                logger.exception("[daemon] Unhandled error in poll_and_reply")

            # Sleep in 1-second chunks to stay responsive to SIGTERM
            for _ in range(interval_secs):
                if not self._running:
                    break
                time.sleep(1)

        logger.info("[daemon] Graceful shutdown complete.")

    def _handle_sigterm(self, signum: int, frame: Any) -> None:  # noqa: ARG002
        logger.info("[daemon] Signal %d — shutting down.", signum)
        self._running = False


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main() -> None:
    args = build_arg_parser().parse_args()
    daemon = SocialDaemon()

    if args.publish:
        urls = daemon.publish_content(args.publish, args.platforms)
        for platform, url in urls.items():
            print(f"{platform}: {url}")
    else:
        daemon.run_loop(interval_minutes=args.interval)


if __name__ == "__main__":
    main()
