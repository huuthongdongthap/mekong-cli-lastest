"""Tests for memory tier separation layer."""

import time
import unittest

from src.core.memory_separation import MemorySeparation, MemoryTier
from src.core.memory_scope import ScopedMemoryStore
from src.core.protocols import MemorySeparation as MemorySeparationProtocol


class TestMemoryTierEnum(unittest.TestCase):
    """Verify MemoryTier enum values."""

    def test_enum_values(self):
        assert MemoryTier.SESSION.value == "session"
        assert MemoryTier.PERSISTENT.value == "persistent"
        assert MemoryTier.ARCHIVE.value == "archive"

    def test_enum_members(self):
        members = list(MemoryTier)
        assert len(members) == 3


class TestMemorySeparation(unittest.TestCase):
    """Test MemorySeparation with a fresh ScopedMemoryStore backend."""

    def setUp(self):
        self.store = ScopedMemoryStore()
        self.sep = MemorySeparation(store=self.store)

    def test_store_and_retrieve_session(self):
        """Session-tier entry round-trips correctly."""
        self.sep.store("s1", b"session-data", tier=MemoryTier.SESSION)
        result = self.sep.retrieve("s1", tier=MemoryTier.SESSION)
        assert result == b"session-data"

    def test_store_and_retrieve_persistent(self):
        """Persistent-tier entry round-trips correctly."""
        self.sep.store("p1", b"persistent-data", tier=MemoryTier.PERSISTENT)
        result = self.sep.retrieve("p1", tier=MemoryTier.PERSISTENT)
        assert result == b"persistent-data"

    def test_retrieve_nonexistent_returns_none(self):
        """Missing key returns None."""
        result = self.sep.retrieve("no-such-key")
        assert result is None

    def test_store_defaults_to_persistent(self):
        """Default tier is PERSISTENT when not specified."""
        self.sep.store("d1", b"default-data")
        result = self.sep.retrieve("d1", tier=MemoryTier.PERSISTENT)
        assert result == b"default-data"

    def test_delete_removes_entry(self):
        """delete removes an entry and returns True."""
        self.sep.store("del1", b"to-delete")
        assert self.sep.delete("del1") is True
        assert self.sep.retrieve("del1") is None

    def test_delete_nonexistent_returns_false(self):
        """delete returns False for missing key."""
        assert self.sep.delete("ghost-key") is False

    def test_flush_session_deletes_session_entries(self):
        """flush_session removes only SESSION-tier entries."""
        self.sep.store("s1", b"s", tier=MemoryTier.SESSION)
        self.sep.store("s2", b"s2", tier=MemoryTier.SESSION)
        self.sep.store("p1", b"p", tier=MemoryTier.PERSISTENT)

        deleted = self.sep.flush_session()
        assert deleted == 2
        assert self.sep.retrieve("s1", tier=MemoryTier.SESSION) is None
        assert self.sep.retrieve("s2", tier=MemoryTier.SESSION) is None
        assert self.sep.retrieve("p1", tier=MemoryTier.PERSISTENT) == b"p"

    def test_search_by_tier(self):
        """search filters by tier when specified."""
        self.sep.store("alpha", b"aaa", tier=MemoryTier.SESSION)
        self.sep.store("beta", b"bbb", tier=MemoryTier.PERSISTENT)

        session_results = self.sep.search("a", tier=MemoryTier.SESSION)
        assert len(session_results) == 1
        assert session_results[0]["key"] == "alpha"
        assert session_results[0]["tier"] == "session"

        persistent_results = self.sep.search("b", tier=MemoryTier.PERSISTENT)
        assert len(persistent_results) == 1
        assert persistent_results[0]["key"] == "beta"

    def test_search_cross_tier(self):
        """search without tier filter returns matches from all tiers."""
        self.sep.store("s1", b"hello", tier=MemoryTier.SESSION)
        self.sep.store("p1", b"hello", tier=MemoryTier.PERSISTENT)

        results = self.sep.search("hello")
        assert len(results) == 2

    def test_search_limit(self):
        """search respects the limit parameter."""
        for i in range(5):
            self.sep.store(f"k{i}", b"val")
        results = self.sep.search("k", limit=3)
        assert len(results) == 3

    def test_list_by_tier(self):
        """list_by_tier returns only keys from the specified tier."""
        self.sep.store("s1", b"s", tier=MemoryTier.SESSION)
        self.sep.store("p1", b"p", tier=MemoryTier.PERSISTENT)
        self.sep.store("s2", b"s2", tier=MemoryTier.SESSION)

        session_keys = self.sep.list_by_tier(MemoryTier.SESSION)
        assert sorted(session_keys) == ["s1", "s2"]

        persistent_keys = self.sep.list_by_tier(MemoryTier.PERSISTENT)
        assert persistent_keys == ["p1"]

    def test_separation_uses_scoped_memory_store(self):
        """MemorySeparation wraps ScopedMemoryStore without modification."""
        assert isinstance(self.sep._store, ScopedMemoryStore)

    def test_custom_ttl_override(self):
        """Explicit TTL overrides tier default."""
        self.sep.store("ttl1", b"data", tier=MemoryTier.SESSION, ttl=10)
        # Entry is stored; verify it exists with correct key prefix
        keys = self.sep.list_by_tier(MemoryTier.SESSION)
        assert "ttl1" in keys

    def test_multiple_tiers_independent(self):
        """Entries with same user key but different tiers are independent."""
        self.sep.store("k1", b"session-val", tier=MemoryTier.SESSION)
        self.sep.store("k1", b"persistent-val", tier=MemoryTier.PERSISTENT)

        session_val = self.sep.retrieve("k1", tier=MemoryTier.SESSION)
        persistent_val = self.sep.retrieve("k1", tier=MemoryTier.PERSISTENT)

        assert session_val == b"session-val"
        assert persistent_val == b"persistent-val"

    def test_protocol_conformance(self):
        """MemorySeparation satisfies protocols.MemorySeparation."""
        assert isinstance(self.sep, MemorySeparationProtocol)

    def test_prune_expired_removes_expired_entries(self):
        """prune_expired() removes TTL-expired entries and returns count."""
        self.sep.store("fresh", b"fresh-val", tier=MemoryTier.PERSISTENT)
        self.sep.store("expired", b"old-val", tier=MemoryTier.SESSION, ttl=1)

        # Force expiration by backdating created_at on the underlying scoped entry
        for entry in self.store._store.values():
            if "expired" in entry.key:
                entry.created_at = time.time() - 10

        pruned_count = self.sep.prune_expired()
        assert pruned_count == 1
        assert self.sep.retrieve("expired", tier=MemoryTier.SESSION) is None
        assert self.sep.retrieve("fresh", tier=MemoryTier.PERSISTENT) == b"fresh-val"

    def test_prune_expired_when_none_expired_returns_zero(self):
        """prune_expired() returns 0 when no entries are expired."""
        self.sep.store("p1", b"val", tier=MemoryTier.PERSISTENT)
        assert self.sep.prune_expired() == 0

    def test_flush_session_triggers_prune_expired(self):
        """flush_session() clears active session keys AND triggers prune_expired()."""
        self.sep.store("s_active", b"active", tier=MemoryTier.SESSION)
        self.sep.store("p_expired", b"expired-p", tier=MemoryTier.PERSISTENT, ttl=1)

        # Backdate p_expired
        for entry in self.store._store.values():
            if "p_expired" in entry.key:
                entry.created_at = time.time() - 10

        deleted_session = self.sep.flush_session()
        assert deleted_session == 1
        assert self.sep.retrieve("s_active", tier=MemoryTier.SESSION) is None
        # p_expired was pruned during flush_session's call to prune_expired
        assert self.sep.retrieve("p_expired", tier=MemoryTier.PERSISTENT) is None

    def test_prune_expired_without_store_support_returns_zero(self):
        """prune_expired() safely returns 0 if underlying store lacks method."""
        class DummyStore:
            pass

        sep = MemorySeparation(store=DummyStore())
        assert sep.prune_expired() == 0


if __name__ == "__main__":
    unittest.main()
