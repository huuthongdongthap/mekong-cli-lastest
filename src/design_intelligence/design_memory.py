# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Design memory — approved DesignDNA + rejected patterns via MemoryStore.

Only *approved* designs are persisted for reuse. Unapproved studies stay on
disk under .mekong/design/studies/ but never enter memory, so downstream
agents (Sophia) only ever read DNA a human has explicitly signed off on.

Namespace convention: every entry's `action` is prefixed `design:` and tagged
with `design` plus `approved`/`rejected`, so the shared JSONL store can be
filtered without a second index.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core.memory_store import DEFAULT_MEMORY_PATH, MemoryEntry, MemoryStore
from src.design_intelligence.schemas import DesignDNA

_NAMESPACE = "design"
_AGENT = "design-intelligence"


def _store(path: str | Path = DEFAULT_MEMORY_PATH) -> MemoryStore:
    return MemoryStore(path=path)


def approve_design(
    name: str,
    dna: DesignDNA,
    *,
    audit_summary: str = "",
    path: str | Path = DEFAULT_MEMORY_PATH,
) -> None:
    """Persist an approved DesignDNA under the design: namespace."""
    entry = MemoryEntry(
        agent=_AGENT,
        action=f"{_NAMESPACE}:approve:{name}",
        outcome=audit_summary or "approved",
        tags=[_NAMESPACE, "approved", name],
        context={"dna": json.loads(dna.model_dump_json())},
    )
    _store(path).append(entry)


def reject_pattern(
    name: str,
    reason: str,
    *,
    path: str | Path = DEFAULT_MEMORY_PATH,
) -> None:
    """Persist a rejected design pattern so it is not reused."""
    entry = MemoryEntry(
        agent=_AGENT,
        action=f"{_NAMESPACE}:reject:{name}",
        outcome=reason,
        tags=[_NAMESPACE, "rejected", name],
        context={"reason": reason},
    )
    _store(path).append(entry)


def load_approved(
    name: str,
    *,
    path: str | Path = DEFAULT_MEMORY_PATH,
) -> DesignDNA | None:
    """Return the most recently approved DesignDNA for `name`, if any."""
    hits = _store(path).search(f"{_NAMESPACE}:approve:{name}", limit=1)
    for entry in hits:
        raw = entry.context.get("dna")
        if isinstance(raw, dict):
            try:
                return DesignDNA.model_validate(raw)
            except Exception:  # noqa: BLE001 — corrupt memory must not crash reuse
                return None
    return None


def list_approved(*, path: str | Path = DEFAULT_MEMORY_PATH) -> list[str]:
    """Names of all approved designs, most recent first, deduplicated."""
    seen: list[str] = []
    for entry in _store(path).search(_NAMESPACE, limit=200):
        if "approved" not in entry.tags:
            continue
        for tag in entry.tags:
            if tag not in (_NAMESPACE, "approved") and tag not in seen:
                seen.append(tag)
    return seen


def list_rejected(*, path: str | Path = DEFAULT_MEMORY_PATH) -> list[str]:
    """Names of all rejected patterns, most recent first, deduplicated."""
    seen: list[str] = []
    for entry in _store(path).search(_NAMESPACE, limit=200):
        if "rejected" not in entry.tags:
            continue
        for tag in entry.tags:
            if tag not in (_NAMESPACE, "rejected") and tag not in seen:
                seen.append(tag)
    return seen
