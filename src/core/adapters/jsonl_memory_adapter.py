# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Conformant adapter: wraps the append-only JSONL ``MemoryStore`` to satisfy
the canonical ``protocols.MemoryStore`` Protocol.

The JSONL store is a CLI action-history audit log (action/agent/outcome/tags).
It is a *separate concern* from the YAML+vector execution-memory store, so it
gets its own thin adapter that maps the 4-method protocol onto the richer
JSONL surface:

- ``store(key, value, ttl)``   → ``append(MemoryEntry(agent="mekong",
  action=key, outcome=value.decode(), tags=["ttl:"+str(ttl)] if ttl else []))``
- ``retrieve(key)``            → newest ``search(key, limit=1)`` hit whose
  action equals ``key``; the stored bytes are the UTF-8 ``outcome``.
- ``delete(key)``              → JSONL has no per-key delete; the file is
  rewritten with all non-matching lines preserved (True if anything removed).
- ``search(query, limit)``     → JSONL substring search over
  action/outcome/tags/agent, mapped to ``MemoryHit``-shaped results.

MED-1 resolution: ``ttl`` is coerced via ``str(ttl)`` before tag concat, so
passing an ``int`` never ``TypeError``-s on ``"ttl:" + ttl``. The ``design:``
namespace is preserved verbatim in the ``action`` field — callers that write
``action="design:approve:<name>"`` get it back unchanged on read, so Sophia's
reads keep working.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence

from src.core.memory_store import DEFAULT_MEMORY_PATH, MemoryEntry, MemoryStore
from src.core.protocols import MemoryHit

logger = logging.getLogger(__name__)

_AGENT = "mekong"
_TTL_TAG = "ttl:"


@dataclass
class _JsonlHit:
    """Concrete MemoryHit-shaped result (the Protocol is not instantiable)."""

    key: str
    score: float
    data: bytes
    metadata: Dict[str, Any] = field(default_factory=dict)


class JsonlMemoryAdapter:
    """Wraps ``memory_store.MemoryStore`` (JSONL) to satisfy ``protocols.MemoryStore``.

    The default no-arg constructor builds the underlying JSONL store at its
    default path; callers may pass an explicit ``store`` or ``path``.
    """

    def __init__(
        self,
        store: MemoryStore | None = None,
        path: str | Path = DEFAULT_MEMORY_PATH,
    ) -> None:
        self._store = (
            store if store is not None else MemoryStore(path=Path(path))
        )

    @property
    def path(self) -> Path:
        """Expose the underlying store's path for callers/tests."""
        return self._store._path

    # --- protocols.MemoryStore interface ---

    def store(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Append an action record. ``value`` is stored as the UTF-8 outcome.

        MED-1: ``ttl`` is stringified before tag concatenation so an int TTL
        cannot raise ``TypeError`` on ``"ttl:" + ttl``.
        """
        outcome = value.decode("utf-8", errors="replace")
        tags: List[str] = []
        if ttl is not None:
            tags.append(_TTL_TAG + str(ttl))
        entry = MemoryEntry(agent=_AGENT, action=key, outcome=outcome, tags=tags)
        self._store.append(entry)

    def retrieve(self, key: str) -> bytes | None:
        """Return the newest stored bytes for ``key`` (exact action match)."""
        for hit in self._store.search(key, limit=200):
            if hit.action == key:
                return hit.outcome.encode("utf-8")
        return None

    def delete(self, key: str) -> bool:
        """Drop every line whose action equals ``key`` by rewriting the file.

        JSONL has no native per-key delete, so this reads the file, keeps the
        non-matching lines in original order, and truncates+rewrites. Returns
        True if at least one line was removed.
        """
        try:
            lines = self._store._path.read_text(encoding="utf-8").splitlines()  # noqa: SLF001
        except OSError as exc:
            logger.debug("jsonl delete read failed: %s", exc)
            return False
        kept: List[str] = []
        removed = 0
        loads = __import__("json").loads
        for line in lines:
            if not line.strip():
                kept.append(line)
                continue
            # Parse to inspect ``action``; malformed lines are preserved.
            try:
                action = loads(line).get("action", "")
            except Exception:  # noqa: BLE001 — keep lines we cannot parse
                kept.append(line)
                continue
            if action == key:
                removed += 1
            else:
                kept.append(line)
        if removed == 0:
            return False
        with self._store._path.open("w", encoding="utf-8") as f:  # noqa: SLF001
            for line in kept:
                f.write(line + "\n")
        return True

    def search(self, query: str, limit: int = 10) -> Sequence[MemoryHit]:
        """Substring search over the JSONL store, mapped to MemoryHit shapes.

        Matches against action/outcome/tags/agent (the JSONL store's native
        search). Results are returned newest-first, capped at ``limit``.
        """
        entries = self._store.search(query, limit=limit)
        hits: List[MemoryHit] = []
        for entry in entries:
            hits.append(
                _JsonlHit(
                    key=entry.action,
                    score=1.0,
                    data=entry.outcome.encode("utf-8"),
                    metadata={
                        "agent": entry.agent,
                        "tags": entry.tags,
                        "context": entry.context,
                        "timestamp": entry.timestamp,
                    },
                )
            )
        return hits


__all__ = ["_JsonlHit", "JsonlMemoryAdapter"]
