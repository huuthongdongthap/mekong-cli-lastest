# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Memory tier separation layer.

Separates short-term (session) vs long-term (persistent) storage by
wrapping ScopedMemoryStore with tier-based TTL defaults and lifecycle
management. Uses a ``tier::`` key prefix to tag entries without modifying
the underlying ScopedMemoryEntry dataclass.
"""

import logging
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MemoryTier(str, Enum):
    """Memory tier for separation of short-term vs long-term storage."""

    SESSION = "session"  # Ephemeral, cleared after goal
    PERSISTENT = "persistent"  # Survives across goals
    ARCHIVE = "archive"  # Cold storage (not implemented yet)


# Default TTL values in seconds per tier
_TIER_TTL: dict[MemoryTier, int] = {
    MemoryTier.SESSION: 3600,  # 1 hour
    MemoryTier.PERSISTENT: 86400 * 30,  # 30 days
    MemoryTier.ARCHIVE: 86400 * 365,  # 1 year
}

_TIER_PREFIX = "tier::"
_MEKONG_APP_ID = "mekong"


class MemorySeparation:
    """Memory separation layer using ScopedMemoryStore as backend.

    Wraps ScopedMemoryStore to provide tier-based storage with automatic
    TTL defaults and session flushing. Entries are keyed as
    ``tier::{tier}::{user_key}`` so tier membership can be determined
    from the key alone.
    """

    def __init__(self, store: Any = None) -> None:
        if store is None:
            from src.core.memory_scope import ScopedMemoryStore

            self._store = ScopedMemoryStore()
        else:
            self._store = store

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _composite_key(tier: MemoryTier, key: str) -> str:
        """Build the prefixed composite key stored in ScopedMemoryStore."""
        return f"{_TIER_PREFIX}{tier.value}::{key}"

    @staticmethod
    def _parse_tier_from_key(composite: str) -> tuple[Optional[MemoryTier], str]:
        """Extract tier and original user key from a composite key.

        Returns (None, raw_key) if the key does not carry a tier prefix.
        """
        if not composite.startswith(_TIER_PREFIX):
            return None, composite
        inner = composite[len(_TIER_PREFIX):]
        parts = inner.split("::", 1)
        if len(parts) == 2:
            tier_val, user_key = parts
            try:
                return MemoryTier(tier_val), user_key
            except ValueError:
                return None, composite
        return None, composite

    @staticmethod
    def _mekong_scope():
        """Return a MemoryScope scoped to the mekong app."""
        from src.core.memory_scope import MemoryScope

        return MemoryScope(app_id=_MEKONG_APP_ID)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(
        self,
        key: str,
        value: bytes,
        tier: MemoryTier = MemoryTier.PERSISTENT,
        ttl: Optional[int] = None,
    ) -> None:
        """Store a value with tier-based TTL."""
        from src.core.memory_scope import ScopedMemoryEntry

        effective_ttl = ttl if ttl is not None else _TIER_TTL[tier]

        entry = ScopedMemoryEntry(
            key=self._composite_key(tier, key),
            value=value,
            scope=self._mekong_scope(),
            ttl=effective_ttl,
        )
        self._store.store(entry)

    def store_raw(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Store a value on the canonical backend without tier tagging.

        AUTONOMY_GAPS #8 — every write must land in the canonical owner
        (ScopedMemoryStore). Callers that previously fell back to a second
        backend route here instead, so there is exactly one write path.
        """
        from src.core.memory_scope import ScopedMemoryEntry

        entry = ScopedMemoryEntry(
            key=key,
            value=value,
            scope=self._mekong_scope(),
            ttl=ttl,
        )
        self._store.store(entry)

    def retrieve(
        self, key: str, tier: MemoryTier = MemoryTier.PERSISTENT
    ) -> Optional[bytes]:
        """Retrieve a value by key within a tier."""
        scope = self._mekong_scope()
        composite = self._composite_key(tier, key)
        entry = self._store.retrieve(composite, scope)
        if entry is not None:
            return entry.value
        return None

    def delete(self, key: str) -> bool:
        """Delete a value across all tiers.

        Scans all entries to find the one matching the user key.
        Returns True if found and deleted.
        """
        scope = self._mekong_scope()
        for entry in self._store.query(scope):
            _, user_key = self._parse_tier_from_key(entry.key)
            if user_key == key:
                return self._store.delete(entry.key, scope)
        return False

    def search(
        self, query: str, limit: int = 10, tier: Optional[MemoryTier] = None
    ) -> list[dict[str, Any]]:
        """Search entries by query string."""
        scope = self._mekong_scope()
        results: list[dict[str, Any]] = []
        for entry in self._store.query(scope):
            entry_tier, user_key = self._parse_tier_from_key(entry.key)
            if tier is not None and entry_tier != tier:
                continue
            key_match = query.lower() in user_key.lower()
            val_match = False
            if isinstance(entry.value, bytes):
                val_match = query.lower() in entry.value.decode(
                    "utf-8", errors="ignore"
                ).lower()
            elif isinstance(entry.value, str):
                val_match = query.lower() in entry.value.lower()
            if key_match or val_match:
                results.append(
                    {
                        "key": user_key,
                        "value": entry.value,
                        "tier": entry_tier.value if entry_tier else "persistent",
                        "timestamp": entry.created_at,
                    }
                )
                if len(results) >= limit:
                    break
        return results

    def flush_session(self) -> int:
        """Delete all SESSION-tier entries and prune expired entries. Returns count deleted."""
        scope = self._mekong_scope()
        deleted = 0
        for entry in self._store.query(scope):
            entry_tier, _ = self._parse_tier_from_key(entry.key)
            if entry_tier == MemoryTier.SESSION:
                self._store.delete(entry.key, scope)
                deleted += 1
        self.prune_expired()
        return deleted

    def prune_expired(self) -> int:
        """Remove all TTL-expired entries from the underlying store.

        Returns count of removed entries.
        """
        if hasattr(self._store, "prune_expired"):
            return int(self._store.prune_expired())
        return 0

    def list_by_tier(self, tier: MemoryTier) -> list[str]:
        """List all user keys for a given tier."""
        scope = self._mekong_scope()
        keys: list[str] = []
        for entry in self._store.query(scope):
            entry_tier, user_key = self._parse_tier_from_key(entry.key)
            if entry_tier == tier:
                keys.append(user_key)
        return keys


__all__ = [
    "MemorySeparation",
    "MemoryTier",
]
