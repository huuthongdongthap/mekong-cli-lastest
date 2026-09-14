# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Command-fabric NL router — unified intent layer.

Bridges cli.tui.router (single source of truth for RouteEntry / ROUTE_TABLE)
into the command-fabric namespace so catalog consumers can do NL routing
without depending on cli.tui internals.

Exports:
  - route_command(query) -> Optional[str]        — best command match
  - route_commands(query) -> list[str]            — all matches, deduplicated
  - fuzzy_match_commands(query, n) -> list[CommandMatch]
  - match_from_records(query, records) -> list[str]
  - RouteTable                                   — wrapper around ROUTE_TABLE

All matching logic lives in cli.tui.router; this module adds only the
CommandRecord bridge and convenience constructors.  Nothing is copied.
"""

from __future__ import annotations

from typing import List, Optional

from src.cli.tui.router import (
    CommandMatch,
    RouteEntry,
    get_all_commands,
    get_route_table,
)

# ── Re-export RouteEntry so command_fabric consumers never import
#    from src.cli.tui.router directly ────────────────────────────────────
__all__ = [
    "RouteEntry",
    "CommandMatch",
    "RouteTable",
    "match_from_records",
    "route_commands",
    "route_command",
    "fuzzy_match_commands",
    "get_all_commands",
]


class RouteTable:
    """Thin wrapper around the shared ROUTE_TABLE.

    Provides instance methods so callers can inject custom RouteEntry
    lists (e.g. derived from CommandRecords) without touching globals.
    """

    def __init__(self, entries: Optional[List[RouteEntry]] = None) -> None:
        # Build once and freeze — matches are order-dependent, so we
        # deduplicate by command keeping the first occurrence.
        seen: set = set()
        deduped: list = []
        src = entries if entries is not None else get_route_table()
        for entry in src:
            if entry.command in seen:
                continue
            seen.add(entry.command)
            deduped.append(entry)
        self._entries: List[RouteEntry] = deduped

    # ------------------------------------------------------------------ #
    # Public matching API (mirrors cli.tui.router module-level functions   #
    # but scoped to this instance's entries)                               #
    # ------------------------------------------------------------------ #

    def match(self, query: str) -> List[str]:
        """Return all command names matched by *query* (deduplicated, order = priority)."""
        if not query or not query.strip():
            return []
        q = query.lower().strip()
        seen_cmds: set = set()
        results: list = []
        for entry in self._entries:
            if entry.command in seen_cmds:
                continue
            for kw in entry.vi_keywords + entry.en_keywords:
                if _kw_matches(kw, q):
                    results.append(entry.command)
                    seen_cmds.add(entry.command)
                    break
        return results

    def best(self, query: str) -> Optional[str]:
        """Return the single best-matching command, or None.

        Uses specificity tie-breaking: longest matching keyword wins.
        Delegates the shadow-resolution logic to the same algorithm
        used by ask_keyword_router.route_ask (ensures both layers agree).
        """
        matches = self.match(query)
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        # Specificity tie-break: longest first-matching keyword wins.
        longest: Optional[str] = None
        best_len: int = -1
        q = query.lower().strip()
        for entry in self._entries:
            if entry.command not in matches:
                continue
            for kw in entry.vi_keywords + entry.en_keywords:
                needle = kw.lower().strip().rstrip("*")
                if not needle:
                    continue
                if q.startswith(needle + " ") or needle in q:
                    if len(needle) > best_len:
                        best_len = len(needle)
                        longest = entry.command
                    break
        return longest or matches[0]

    def fuzzy(self, query: str, max_results: int = 5) -> List[CommandMatch]:
        """Return scored CommandMatch results for interactive autocomplete."""
        if not query or not query.strip():
            return []
        q = query.lower().strip()
        seen_cmds: set = set()
        results: list = []
        for entry in self._entries:
            if entry.command in seen_cmds:
                continue
            for kw in entry.vi_keywords + entry.en_keywords:
                kw_lower = kw.lower().strip()
                if _kw_matches(kw_lower, q):
                    needle = kw_lower.rstrip("*").rstrip()
                    if not needle:
                        score = 0.5
                    elif q == needle:
                        score = 1.0
                    elif q.startswith(needle + " "):
                        score = 0.8
                    else:
                        score = 0.5
                    results.append(CommandMatch(entry.command, score, kw))
                    seen_cmds.add(entry.command)
                    break
        results.sort(key=_cmd_match_sort_key, reverse=True)
        return results[:max_results]

    @property
    def entries(self) -> List[RouteEntry]:
        return list(self._entries)

    @property
    def commands(self) -> List[str]:
        return [e.command for e in self._entries]

    def __len__(self) -> int:
        return len(self._entries)


# ── Module-level singleton (mirrors cli.tui.router's ROUTE_TABLE) ──────
_default_table = RouteTable()


# ── Convenience APIs (drop-in replacements for cli.tui.router calls) ───

def route_command(query: str) -> Optional[str]:
    """Best command match for *query*. Returns None if no match."""
    return _default_table.best(query)


def route_commands(query: str) -> List[str]:
    """All deduplicated command matches for *query*."""
    return _default_table.match(query)


def fuzzy_match_commands(query: str, max_results: int = 5) -> List[CommandMatch]:
    """Scored autocomplete results for *query*."""
    return _default_table.fuzzy(query, max_results)


def match_from_records(query: str, records: list) -> List[str]:
    """Match *query* against a list of command-fabric CommandRecords.

    Converts each record to a RouteEntry on-the-fly using its name and
    (empty) keyword lists — this is a structural match for records that
    carry their own NL metadata.  For records without keyword fields,
    falls back to name-only matching.
    """
    if not query or not query.strip():
        return []
    q = query.lower().strip()
    seen: set = set()
    results: list = []
    for rec in records:
        cmd = getattr(rec, "name", str(rec))
        if cmd in seen:
            continue
        vi_kw: tuple = ()
        en_kw: tuple = ()
        if hasattr(rec, "vi_keywords"):
            vi_kw = rec.vi_keywords
        if hasattr(rec, "en_keywords"):
            en_kw = rec.en_keywords
        entry = RouteEntry(command=cmd, vi_keywords=vi_kw, en_keywords=en_kw)
        for kw in entry.vi_keywords + entry.en_keywords:
            if _kw_matches(kw, q):
                results.append(cmd)
                seen.add(cmd)
                break
        else:
            # Name-only fallback: check if query mentions the command name
            if cmd in q:
                results.append(cmd)
                seen.add(cmd)
    return results


# ── Private helpers ────────────────────────────────────────────────────

def _kw_matches(pattern: str, text: str) -> bool:
    """Case-insensitive keyword match (same rules as cli.tui.router._matches)."""
    if not text:
        return False
    p = pattern.lower().strip()
    if not p:
        return False
    if p.endswith("*"):
        needle = p[:-1].rstrip()
        if not needle:
            return False
        return needle in text or text.startswith(needle + " ")
    return p in text


def _cmd_match_sort_key(m: CommandMatch) -> tuple:
    return (m.score,)
