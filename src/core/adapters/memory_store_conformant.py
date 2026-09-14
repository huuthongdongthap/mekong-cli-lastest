# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Conformant adapter: wraps memory_canonical.MemoryStore to satisfy the
``protocols.MemoryStore`` Protocol (src/core/protocols.py).

Protocol → canonical implementation mapping:
- store(key, value, ttl)  → record(MemoryEntry) — value kept as base64 in context
- retrieve(key)           → query(key) — exact-goal match, bytes decoded back
- delete(key)             → filter matching entries + persist (no per-key API upstream)
- search(query, limit)    → semantic_search(query) with substring fallback,
                            results mapped to MemoryHit-shaped dataclasses

The canonical store has no native TTL or per-key delete; TTL is honored by
storing ``expires_at`` in the entry context and filtering on read. This adapter
wraps — it never rewrites — memory_canonical.MemoryStore.
"""

from __future__ import annotations

import base64
import time
from typing import List, Sequence

from src.core.memory_canonical import (
    MemoryEntry,
    MemoryHitResult,
    MemoryStore,
    _EXPIRES_KEY,
    _VALUE_KEY,
)
from src.core.protocols import MemoryHit


class MemoryStoreConformant:
    """Wraps memory_canonical.MemoryStore to satisfy protocols.MemoryStore."""

    def __init__(
        self,
        store: MemoryStore | None = None,
        store_path: str | None = None,
    ) -> None:
        self._store = store if store is not None else MemoryStore(store_path=store_path)

    # --- protocols.MemoryStore interface ---

    def store(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Persist bytes under key via canonical store()."""
        self._store.store(key, value, ttl=ttl)

    def retrieve(self, key: str) -> bytes | None:
        """Return the most recent non-expired value for key, or None."""
        return self._store.retrieve(key)

    def delete(self, key: str) -> bool:
        """Remove all entries matching key. Returns True if anything was removed."""
        return self._store.delete(key)

    def search(self, query: str, limit: int = 10) -> Sequence[MemoryHit]:
        """Semantic search with substring fallback, mapped to MemoryHit shapes."""
        return self._store.search(query, limit=limit)

    # --- Helpers ---

    def _accept(
        self,
        entry: MemoryEntry,
        query: str,
        seen: set[str],
        score: float,
        out: List[MemoryHitResult],
    ) -> bool:
        """Append entry as a hit if it matches and is fresh; returns True if added."""
        if entry.goal in seen or self._is_expired(entry):
            return False
        if query and query.lower() not in entry.goal.lower():
            return False
        seen.add(entry.goal)
        data = self._decode(entry) or b""
        out.append(
            MemoryHitResult(
                key=entry.goal,
                score=score,
                data=data,
                metadata={
                    "status": entry.status,
                    "timestamp": entry.timestamp,
                },
            )
        )
        return True

    @staticmethod
    def _is_expired(entry: MemoryEntry) -> bool:
        expires_at = (entry.context or {}).get(_EXPIRES_KEY)
        return expires_at is not None and time.time() >= float(expires_at)

    @staticmethod
    def _decode(entry: MemoryEntry) -> bytes | None:
        encoded = (entry.context or {}).get(_VALUE_KEY)
        if not encoded:
            return None
        try:
            return base64.b64decode(encoded.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            return None


__all__ = [
    "MemoryHitResult",
    "MemoryStoreConformant",
]
