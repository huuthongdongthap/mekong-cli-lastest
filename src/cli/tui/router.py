# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""NL router stubs for tests - kept in sync with cli/tui/router.py."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class RouteEntry:
    """One entry in the route table."""
    command: str
    vi_keywords: Tuple[str, ...] = field(default_factory=tuple)
    en_keywords: Tuple[str, ...] = field(default_factory=tuple)
    description: str = ""


@dataclass
class CommandMatch:
    """A match result from fuzzy matching."""
    command: str
    score: float
    matched_keyword: str = ""


ROUTE_TABLE: List[RouteEntry] = [
    # "fix" is routed to "debug": the standalone `fix` subcommand no longer
    # exists in the CLI (it is a slash-only stub that dispatches to `mekong fix`,
    # which itself is unregistered).  `debug` is the live, tested command for
    # bug/repair work, so repair keywords route there instead.
    # debug, plan, cook — leaf commands (dispatchable with a question argument).
    RouteEntry(command="debug", vi_keywords=("sửa lỗi*", "sửa bug*", "sửa", "lỗi*"), en_keywords=("fix*", "debug*", "bug*", "broken*"), description="Debug command (repair/fix)"),
    RouteEntry(command="cook", vi_keywords=("code*", "viết code*", "code giao diện", "lập trình*"), en_keywords=("code*", "implement*", "develop*", "build*", "write code*"), description="Cook command"),
    # plan and deploy are Typer *groups* — they require a subcommand
    # (e.g. `plan from-init`, `deploy new`) and cannot be dispatched with a bare
    # question argument.  ask_cmd detects groups and falls back to the LLM planner.
    RouteEntry(command="plan", vi_keywords=("lập kế hoạch*", "lên kế hoạch*", "tạo kế hoạch*", "kế hoạch*", "plan*"), en_keywords=("plan*", "create plan*", "build plan*"), description="Plan command (group)"),
    RouteEntry(command="deploy", vi_keywords=("triển khai*", "đưa lên production*", "deploy*"), en_keywords=("deploy*", "push to prod*", "go live*"), description="Deploy command (group)"),
]


def _matches(pattern: str, text: str) -> bool:
    if not text:
        return False
    p = pattern.lower().strip()
    t = text.lower().strip()
    if not p:
        return False
    if p.endswith("*"):
        needle = p[:-1].strip()
        if not needle:
            return False
        return t.startswith(needle)
    return p in t


def fuzzy_match(text: str, max_results: int = 5) -> List[CommandMatch]:
    """Score *text* against every keyword in ROUTE_TABLE.

    Scoring tiers:
      1.0 — exact match (text == needle)
      0.8 — phrase prefix (text starts with needle + " ")
      0.5 — substring (needle in text)

    Returns up to max_results matches, sorted descending by score.
    """
    if not text or not text.strip():
        return []
    q = text.lower().strip()
    seen: set = set()
    results: List[CommandMatch] = []
    for entry in ROUTE_TABLE:
        if entry.command in seen:
            continue
        for kw in entry.vi_keywords + entry.en_keywords:
            needle = kw.lower().strip().rstrip("*").strip()
            if not needle:
                continue
            if q == needle:
                score = 1.0
            elif q.startswith(needle + " "):
                score = 0.8
            elif needle in q:
                score = 0.5
            else:
                continue
            results.append(CommandMatch(entry.command, score, kw))
            seen.add(entry.command)
            break
    results.sort(key=lambda m: m.score, reverse=True)
    return results[:max_results]


def get_route_table() -> List[RouteEntry]:
    return ROUTE_TABLE


def get_all_commands() -> List[str]:
    return [e.command for e in ROUTE_TABLE]


def match_routes(query: str) -> List[str]:
    matches: List[str] = []
    for entry in ROUTE_TABLE:
        for kw in entry.vi_keywords + entry.en_keywords:
            if _matches(kw, query):
                matches.append(entry.command)
                break
    return matches


def route_ask(input_text: str) -> Optional[str]:
    matches = match_routes(input_text)
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    # Multiple matches — pick the one whose first keyword is longest
    best = None
    best_len = -1
    for cmd in matches:
        for entry in ROUTE_TABLE:
            if entry.command == cmd:
                # Use combined keywords, get the first one
                all_kws = entry.vi_keywords + entry.en_keywords
                first_kw = all_kws[0] if all_kws else ""
                kw_len = len(first_kw.rstrip("*"))
                if kw_len > best_len:
                    best = cmd
                    best_len = kw_len
                break
    return best