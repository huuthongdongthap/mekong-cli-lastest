"""Tests for MemoryStoreConformant adapter — wraps canonical store to satisfy
the protocols.MemoryStore Protocol."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.core.adapters.memory_store_conformant import MemoryStoreConformant
from src.core import protocols


@pytest.fixture
def adapter(tmp_path: Path, restore_real_memory_store) -> MemoryStoreConformant:
    """Fresh adapter backed by a temp YAML file (real MemoryStore restored)."""
    return MemoryStoreConformant(store_path=str(tmp_path / "mem.yaml"))


class TestMemoryStoreConformantProtocol:
    """Verify the adapter satisfies the runtime_checkable Protocol."""

    def test_isinstance_protocol(self, adapter: MemoryStoreConformant) -> None:
        assert isinstance(adapter, protocols.MemoryStore)

    def test_protocol_methods_exist(self, adapter: MemoryStoreConformant) -> None:
        for method in ("store", "retrieve", "delete", "search"):
            assert hasattr(adapter, method), f"Missing method: {method}"
            assert callable(getattr(adapter, method)), f"Not callable: {method}"


class TestMemoryStoreConformantRoundTrip:
    """Round-trip store/retrieve/delete/search tests."""

    def test_store_and_retrieve_bytes(self, adapter: MemoryStoreConformant) -> None:
        adapter.store("deploy-app", b'{"version": "1.0", "env": "prod"}')
        retrieved = adapter.retrieve("deploy-app")
        assert retrieved == b'{"version": "1.0", "env": "prod"}'

    def test_retrieve_missing_returns_none(self, adapter: MemoryStoreConformant) -> None:
        assert adapter.retrieve("nonexistent-key") is None

    def test_delete_existing_returns_true(self, adapter: MemoryStoreConformant) -> None:
        adapter.store("key-to-delete", b"value")
        assert adapter.delete("key-to-delete") is True
        assert adapter.retrieve("key-to-delete") is None

    def test_delete_missing_returns_false(self, adapter: MemoryStoreConformant) -> None:
        assert adapter.delete("never-existed") is False

    def test_search_returns_hits(self, adapter: MemoryStoreConformant) -> None:
        adapter.store("deploy-app", b"deploy payload")
        adapter.store("build-api", b"build payload")
        adapter.store("test-integration", b"test payload")

        hits = adapter.search("deploy", limit=5)
        assert len(hits) >= 1
        assert any(h.key == "deploy-app" for h in hits)

    def test_search_limit_respected(self, adapter: MemoryStoreConformant) -> None:
        for i in range(15):
            adapter.store(f"key-{i}", f"value-{i}".encode())
        hits = adapter.search("key", limit=3)
        assert len(hits) == 3

    def test_search_returns_memory_hit_shape(self, adapter: MemoryStoreConformant) -> None:
        adapter.store("my-goal", b"data")
        hits = adapter.search("my-goal", limit=1)
        assert len(hits) == 1
        hit = hits[0]
        assert isinstance(hit.key, str)
        assert isinstance(hit.score, float)
        assert isinstance(hit.data, bytes)
        assert isinstance(hit.metadata, dict)

    def test_ttl_expiration(self, adapter: MemoryStoreConformant) -> None:
        adapter.store("ttl-key", b"ttl-value", ttl=0)
        time.sleep(0.01)
        assert adapter.retrieve("ttl-key") is None

    def test_ttl_not_expired(self, adapter: MemoryStoreConformant) -> None:
        adapter.store("ttl-key", b"ttl-value", ttl=60)
        assert adapter.retrieve("ttl-key") == b"ttl-value"

    def test_delete_then_store_again(self, adapter: MemoryStoreConformant) -> None:
        adapter.store("key", b"v1")
        adapter.delete("key")
        adapter.store("key", b"v2")
        assert adapter.retrieve("key") == b"v2"

    def test_overwrite_same_key(self, adapter: MemoryStoreConformant) -> None:
        adapter.store("key", b"v1")
        adapter.store("key", b"v2")
        assert adapter.retrieve("key") == b"v2"

    def test_search_empty_query_returns_recent(self, adapter: MemoryStoreConformant) -> None:
        adapter.store("a", b"1")
        adapter.store("b", b"2")
        adapter.store("c", b"3")
        hits = adapter.search("", limit=5)
        assert len(hits) >= 3

    def test_metadata_contains_status_and_timestamp(self, adapter: MemoryStoreConformant) -> None:
        adapter.store("meta-key", b"data")
        hits = adapter.search("meta-key", limit=1)
        assert len(hits) == 1
        meta = hits[0].metadata
        assert "status" in meta
        assert "timestamp" in meta
        assert isinstance(meta["timestamp"], float)


class TestMemoryStoreConformantEdgeCases:
    """Edge cases and error conditions."""

    def test_store_binary_bytes(self, adapter: MemoryStoreConformant) -> None:
        adapter.store("key", b"\xff\xfe\xfd")
        assert adapter.retrieve("key") == b"\xff\xfe\xfd"

    def test_search_case_insensitive(self, adapter: MemoryStoreConformant) -> None:
        adapter.store("DeployApp", b"payload")
        hits = adapter.search("deploy", limit=1)
        assert len(hits) >= 1
        assert any("deploy" in h.key.lower() for h in hits)

    def test_persists_across_instances(
        self, tmp_path: Path, restore_real_memory_store
    ) -> None:
        path = str(tmp_path / "persist.yaml")
        adapter1 = MemoryStoreConformant(store_path=path)
        adapter1.store("persistent-key", b"persistent-value")
        adapter2 = MemoryStoreConformant(store_path=path)
        assert adapter2.retrieve("persistent-key") == b"persistent-value"

    def test_empty_store_search_returns_empty(self, adapter: MemoryStoreConformant) -> None:
        assert adapter.search("anything", limit=10) == []

    def test_empty_store_delete_returns_false(self, adapter: MemoryStoreConformant) -> None:
        assert adapter.delete("anything") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
