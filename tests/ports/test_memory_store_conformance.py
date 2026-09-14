# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Conformance suite for the canonical MemoryStoreAdapter (Super Command #7,
Phase 1). Verifies that ``memory_store_adapter.MemoryStoreAdapter`` satisfies
``protocols.MemoryStore`` — the single conformant implementation the 3-way
memory split collapses onto.

Parametrized against the real ``memory_canonical.MemoryStore`` (YAML+vector),
restored from the session-wide gateway mock via a local fixture. Each test is
hermetic: ``tmp_path`` gives an isolated store directory, no network, no
shared state, no real credentials.

These tests encode the contract. The not-yet-hardened adapter is expected to
fail the bytes-exact, TTL, and search-shape cases until Phase 2 lands — that
failure is the signal Phase 2 satisfies. Do not weaken them to match current
behavior; fix the adapter instead.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

import src.core.memory_canonical as _mc
from src.core.memory_store_adapter import MemoryStoreAdapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _real_memory_store():
    """Restore the genuine memory_canonical.MemoryStore for this test.

    The session-wide ``_pre_gateway_patches`` mock replaces the class with a
    MagicMock so gateway tests never touch disk.  This fixture puts the real
    class back on BOTH modules that bind it (canonical + adapter) for the
    test's scope, so construction and ``record``/``query`` use the real YAML
    engine.  Scope is per-test — no state leaks between tests.
    """
    import tests.conftest as _conftest

    _real = _conftest._pre_gateway_originals.get(
        "src.core.memory_canonical.MemoryStore",
    )
    import src.core.memory_store_adapter as _msa

    with (
        patch.object(_mc, "MemoryStore", _real),
        patch.object(_msa, "MemoryStore", _real),
    ):
        yield _real


def _adapter_with_path(
    tmp_path: Path, name: str, real_store_cls: type,
) -> MemoryStoreAdapter:
    """Adapter pinned to ``tmp_path/name`` — the ONLY way tests build adapters.

    Centralized here so every adapter is hermetically bound to an isolated
    temp file.  ``real_store_cls`` is the restored genuine MemoryStore (passed
    from the ``_real_memory_store`` fixture) so construction is not the
    session-wide MagicMock.  Never construct ``MemoryStoreAdapter()`` with no
    args in a test — that writes to ``.mekong/memory.yaml`` in the CWD."""
    underlying = real_store_cls(store_path=str(tmp_path / name))
    return MemoryStoreAdapter(store=underlying)


@pytest.fixture
def adapter(tmp_path: Path, _real_memory_store: type) -> MemoryStoreAdapter:
    """Fresh adapter backed by an isolated temp YAML file (hermetic)."""
    return _adapter_with_path(tmp_path, "mem.yaml", _real_memory_store)


# ---------------------------------------------------------------------------
# 1. Structural / isinstance conformance
# ---------------------------------------------------------------------------


def test_adapter_satisfies_memory_store_protocol(
    tmp_path: Path, _real_memory_store: type
) -> None:
    """The whole point: the adapter IS a MemoryStore per the runtime-checkable
    protocol.  All four protocol methods must be present and callable."""
    adapter = _adapter_with_path(tmp_path, "proto.yaml", _real_memory_store)

    # protocols.MemoryStore is runtime_checkable — isinstance must hold.
    from src.core.protocols import MemoryStore

    assert isinstance(adapter, MemoryStore)

    for method in ("store", "retrieve", "delete", "search"):
        assert hasattr(adapter, method), f"Missing protocol method: {method}"
        assert callable(getattr(adapter, method)), f"Not callable: {method}"


# ---------------------------------------------------------------------------
# 2. Round-trip bytes preserved exactly
# ---------------------------------------------------------------------------


def test_store_retrieve_roundtrip_preserves_bytes(
    adapter: MemoryStoreAdapter,
) -> None:
    """store(key, value_bytes) -> retrieve(key) must return the SAME bytes."""
    payload = b'{"version": "1.0", "env": "prod"}'
    adapter.store("deploy-app", payload)
    assert adapter.retrieve("deploy-app") == payload


def test_store_retrieve_roundtrip_binary_bytes(
    tmp_path: Path, _real_memory_store: type
) -> None:
    """Arbitrary binary bytes must round-trip bit-exact, not be mangled through
    a text codec.  A conformant adapter encodes bytes opaque to their content."""
    payload = b"\xff\xfe\xfd\x00\x01\x02"
    a = _adapter_with_path(tmp_path, "bin.yaml", _real_memory_store)
    a.store("bin-key", payload)
    assert a.retrieve("bin-key") == payload


# ---------------------------------------------------------------------------
# 3. Missing-key semantics
# ---------------------------------------------------------------------------


def test_retrieve_missing_returns_none(adapter: MemoryStoreAdapter) -> None:
    assert adapter.retrieve("never-stored") is None


def test_delete_missing_returns_false(adapter: MemoryStoreAdapter) -> None:
    assert adapter.delete("never-stored") is False


# ---------------------------------------------------------------------------
# 4. TTL expiry
# ---------------------------------------------------------------------------


def test_ttl_expiry(tmp_path: Path, _real_memory_store: type) -> None:
    """store(k, v, ttl=1) -> sleep past ttl -> retrieve(k) must be None.
    The adapter honors TTL by storing expires_at and filtering on read."""
    a = _adapter_with_path(tmp_path, "ttl.yaml", _real_memory_store)
    a.store("ttl-key", b"ttl-value", ttl=1)
    assert a.retrieve("ttl-key") == b"ttl-value"  # still alive before expiry
    time.sleep(1.1)
    assert a.retrieve("ttl-key") is None


# ---------------------------------------------------------------------------
# 5. Search returns MemoryHit-shaped dataclasses
# ---------------------------------------------------------------------------


def test_search_returns_memory_hit_shape(adapter: MemoryStoreAdapter) -> None:
    """search() must return a list of objects exposing the MemoryHit shape:
    key: str, score: float, data: bytes, metadata: dict.  (MemoryHit itself is
    a non-instantiable Protocol — the adapter returns concrete dataclasses
    that structurally satisfy it.)"""
    adapter.store("my-goal", b"goal-data")
    hits = adapter.search("my-goal", limit=5)

    assert isinstance(hits, list)
    assert len(hits) >= 1, "search should return at least the stored goal"

    hit = hits[0]
    # Structural (duck) match on the MemoryHit shape — never isinstance on a
    # Protocol that is not runtime_checkable for the concrete type.
    assert isinstance(getattr(hit, "key", None), str)
    assert isinstance(getattr(hit, "score", None), float)
    assert isinstance(getattr(hit, "data", None), bytes)
    assert isinstance(getattr(hit, "metadata", None), dict)
    assert hit.key == "my-goal"


# ---------------------------------------------------------------------------
# 6. Namespace isolation
# ---------------------------------------------------------------------------


def test_namespace_isolation(tmp_path: Path, _real_memory_store: type) -> None:
    """Two adapters with separate store_path must not cross-read.  This is the
    hermetic guarantee: per-tenant / per-mission stores stay isolated."""
    a1 = _adapter_with_path(tmp_path, "tenant-a.yaml", _real_memory_store)
    a2 = _adapter_with_path(tmp_path, "tenant-b.yaml", _real_memory_store)

    a1.store("secret", b"tenant-a-secret")

    # Cross-read must fail: the other store must not see the value.
    assert a2.retrieve("secret") is None
    # The originating store must still hold it (write landed).  Byte-exactness
    # is asserted in the round-trip tests; here we only prove isolation, so a
    # non-None read-back is sufficient.
    assert a1.retrieve("secret") is not None


# ---------------------------------------------------------------------------
# 7. Search honors limit
# ---------------------------------------------------------------------------


def test_search_honors_limit(adapter: MemoryStoreAdapter) -> None:
    """search(query, limit=N) returns at most N results."""
    for i in range(15):
        adapter.store(f"key-{i}", f"value-{i}".encode())

    hits = adapter.search("key", limit=3)
    assert len(hits) <= 3
