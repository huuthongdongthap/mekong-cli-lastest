"""Tests for JsonlMemoryAdapter — wraps the append-only JSONL MemoryStore to
satisfy the canonical ``protocols.MemoryStore`` Protocol (Super Command #7,
Phase 4).

The JSONL store is the CLI action-history audit log. This adapter maps the
4-method protocol onto the richer JSONL surface while preserving the
``design:`` namespace that Sophia reads (MED-1 resolution).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.adapters.jsonl_memory_adapter import JsonlMemoryAdapter
from src.core import protocols


@pytest.fixture
def adapter(tmp_path: Path) -> JsonlMemoryAdapter:
    """Fresh adapter backed by a temp JSONL file."""
    return JsonlMemoryAdapter(path=tmp_path / "memory.jsonl")


class TestJsonlMemoryAdapterProtocol:
    """Verify the adapter satisfies the runtime_checkable Protocol."""

    def test_isinstance_protocol(self, adapter: JsonlMemoryAdapter) -> None:
        assert isinstance(adapter, protocols.MemoryStore)

    def test_protocol_methods_exist(self, adapter: JsonlMemoryAdapter) -> None:
        for method in ("store", "retrieve", "delete", "search"):
            assert hasattr(adapter, method), f"Missing method: {method}"
            assert callable(getattr(adapter, method)), f"Not callable: {method}"


class TestJsonlMemoryAdapterRoundTrip:
    """Round-trip store/retrieve/delete/search tests."""

    def test_store_and_retrieve_bytes(self, adapter: JsonlMemoryAdapter) -> None:
        adapter.store("deploy-app", b'{"version": "1.0"}')
        assert adapter.retrieve("deploy-app") == b'{"version": "1.0"}'

    def test_retrieve_missing_returns_none(self, adapter: JsonlMemoryAdapter) -> None:
        assert adapter.retrieve("nonexistent-key") is None

    def test_delete_existing_returns_true(self, adapter: JsonlMemoryAdapter) -> None:
        adapter.store("key-to-delete", b"value")
        assert adapter.delete("key-to-delete") is True
        assert adapter.retrieve("key-to-delete") is None

    def test_delete_missing_returns_false(self, adapter: JsonlMemoryAdapter) -> None:
        assert adapter.delete("never-stored") is False

    def test_search_finds_stored_key(self, adapter: JsonlMemoryAdapter) -> None:
        adapter.store("billing-run", b"ok")
        hits = adapter.search("billing-run", limit=5)
        assert len(hits) == 1
        assert hits[0].key == "billing-run"
        assert hits[0].data == b"ok"

    def test_search_empty_query_returns_empty(self, adapter: JsonlMemoryAdapter) -> None:
        adapter.store("k", b"v")
        assert adapter.search("", limit=5) == []


class TestJsonlMemoryAdapterTtl:
    """MED-1: ttl must be string-safe (int TTL cannot TypeError on tag concat)."""

    def test_int_ttl_does_not_raise(self, adapter: JsonlMemoryAdapter) -> None:
        # The naive ``"ttl:" + ttl`` would TypeError on int; str(ttl) fixes it.
        adapter.store("session-key", b"v", ttl=3600)
        assert adapter.retrieve("session-key") == b"v"

    def test_string_ttl_does_not_raise(self, adapter: JsonlMemoryAdapter) -> None:
        adapter.store("session-key", b"v", ttl="3600")
        assert adapter.retrieve("session-key") == b"v"

    def test_none_ttl_no_tag(self, adapter: JsonlMemoryAdapter) -> None:
        adapter.store("no-ttl", b"v")
        hits = adapter.search("no-ttl", limit=5)
        assert hits[0].metadata.get("tags") == []


class TestJsonlMemoryAdapterDesignNamespace:
    """The ``design:`` namespace MUST be preserved verbatim (Sophia contract)."""

    def test_design_approve_prefix_preserved(self, adapter: JsonlMemoryAdapter) -> None:
        adapter.store("design:approve:good-dashboard", b"approved")
        hits = adapter.search("design:approve", limit=10)
        assert len(hits) == 1
        assert hits[0].key == "design:approve:good-dashboard"
        assert adapter.retrieve("design:approve:good-dashboard") == b"approved"

    def test_design_reject_prefix_preserved(self, adapter: JsonlMemoryAdapter) -> None:
        adapter.store("design:reject:slop-landing", b"too many gradients")
        hits = adapter.search("design:reject", limit=10)
        assert hits[0].key == "design:reject:slop-landing"

    def test_design_prefix_searchable(self, adapter: JsonlMemoryAdapter) -> None:
        adapter.store("design:approve:a", b"1")
        adapter.store("design:approve:b", b"2")
        adapter.store("other:noise", b"x")
        hits = adapter.search("design:approve", limit=20)
        keys = {h.key for h in hits}
        assert keys == {"design:approve:a", "design:approve:b"}


class TestJsonlMemoryAdapterDelete:
    """Delete rewrites the JSONL file, preserving non-matching lines in order."""

    def test_delete_preserves_order(self, adapter: JsonlMemoryAdapter) -> None:
        adapter.store("keep-1", b"a")
        adapter.store("drop", b"b")
        adapter.store("keep-2", b"c")
        assert adapter.delete("drop") is True
        hits = adapter.search("keep", limit=10)
        keys = [h.key for h in hits]
        # Newest-first ordering from the underlying search.
        assert "keep-1" in keys
        assert "keep-2" in keys
        assert "drop" not in keys

    def test_delete_malformed_lines_preserved(self, tmp_path: Path) -> None:
        path = tmp_path / "memory.jsonl"
        path.write_text(
            '{"timestamp":"t","agent":"a","action":"keep","outcome":"ok","tags":[],"context":{}}\n'
            "this-is-not-json\n"
        )
        adapter = JsonlMemoryAdapter(path=path)
        # Nothing to delete, but the malformed line must survive the rewrite.
        assert adapter.delete("absent") is False
        lines = path.read_text().splitlines()
        assert "this-is-not-json" in lines
