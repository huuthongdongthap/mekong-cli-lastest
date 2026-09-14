# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.


"""
Mekong CLI - Memory Store (AGI v2)

Canonical memory store: long-term execution memory with YAML persistence +
vector semantic index. Records goal outcomes, enables semantic search, and
supports memory compression.

Vector backend (VectorMemoryStore) provides semantic search alongside YAML.
"""

import base64
import hashlib
import logging
import time
import yaml  # type: ignore[import-untyped]
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .event_bus import EventType, get_event_bus
from .vector_memory_store import MemoryType, VectorMemoryStore

logger = logging.getLogger(__name__)

_VALUE_KEY = "value_b64"
_EXPIRES_KEY = "expires_at"


@dataclass
class MemoryHitResult:
    """Concrete MemoryHit-shaped result (conforming to protocols.MemoryHit)."""

    key: str
    score: float
    data: bytes
    metadata: Dict[str, Any] = field(default_factory=dict)

try:
    from packages.memory.memory_facade import get_memory_facade as _get_facade
    _FACADE_AVAILABLE = True
except ImportError:
    _FACADE_AVAILABLE = False


@dataclass
class MemoryEntry:
    """Single execution memory record."""

    goal: str
    status: str  # "success" | "failed" | "partial" | "rolled_back"
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    error_summary: str = ""
    recipe_used: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    reflection: str = ""  # Post-task reflection from ReflectionEngine


class MemoryStore:
    """Long-term execution memory with YAML + vector semantic index."""

    MAX_ENTRIES: int = 2000
    VECTOR_DIM: int = 64
    VECTOR_COLLECTION: str = "execution_memory"

    def __init__(self, store_path: Optional[str] = None) -> None:
        """
        Initialize memory store.

        Args:
            store_path: Path to YAML file. Defaults to .mekong/memory.yaml
        """
        self._path = Path(store_path) if store_path else Path(".mekong/memory.yaml")
        self._entries: List[MemoryEntry] = []
        self._load()

        # Initialize vector store for semantic search
        vector_path = str(self._path.parent / "vector_index.json")
        self._vector_store = VectorMemoryStore(persist_path=vector_path)
        try:
            self._vector_store.get_or_create_collection(
                self.VECTOR_COLLECTION, self.VECTOR_DIM,
            )
        except Exception as _exc:
            logger.warning("Vector store collection init failed, semantic search disabled: %s", _exc)

    def record(self, entry: MemoryEntry) -> None:
        """Record an execution outcome and persist."""
        self._entries.append(entry)
        self._evict()
        self._save()
        bus = get_event_bus()
        bus.emit(EventType.MEMORY_RECORDED, asdict(entry))

        # Index in vector store for semantic search
        self._index_entry(entry)

        # Mirror to external vector backend when available
        if _FACADE_AVAILABLE:
            try:
                facade = _get_facade()
                content = (
                    f"goal={entry.goal} status={entry.status} "
                    f"error={entry.error_summary} recipe={entry.recipe_used}"
                )
                facade.add(
                    content,
                    user_id="mekong:memory",
                    metadata={
                        "status": entry.status,
                        "recipe_used": entry.recipe_used,
                        "duration_ms": entry.duration_ms,
                        "timestamp": entry.timestamp,
                    },
                )
            except Exception as _exc:
                logger.debug("External memory facade add failed: %s", _exc)

    def query(self, goal_pattern: str) -> List[MemoryEntry]:
        """
        Find entries matching goal pattern.

        Uses semantic vector search first, falls back to substring match.
        """
        # Try semantic vector search
        semantic_results = self._semantic_search(goal_pattern, top_k=10)
        if semantic_results:
            return semantic_results

        # External facade fallback
        if _FACADE_AVAILABLE:
            try:
                facade = _get_facade()
                hits = facade.search(goal_pattern, user_id="mekong:memory")
                if hits:
                    matched_goals = {
                        h.get("memory", "").split("goal=")[-1].split(" status=")[0]
                        for h in hits
                    }
                    matched = [e for e in self._entries if e.goal in matched_goals]
                    if matched:
                        return matched
            except Exception as _exc:
                logger.debug("External memory facade search failed: %s", _exc)

        # YAML substring fallback
        pattern = goal_pattern.lower()
        return [e for e in self._entries if pattern in e.goal.lower()]

    def semantic_search(
        self, query: str, top_k: int = 5,
    ) -> List[MemoryEntry]:
        """
        Explicit semantic search using vector similarity.

        Args:
            query: Natural language query.
            top_k: Number of results.

        Returns:
            List of matching MemoryEntry objects.
        """
        return self._semantic_search(query, top_k)

    def get_success_rate(self, goal_pattern: str = "") -> float:
        """Calculate success rate (0-100) for entries matching pattern."""
        entries = self.query(goal_pattern) if goal_pattern else self._entries
        if not entries:
            return 0.0
        successes = sum(1 for e in entries if e.status == "success")
        return (successes / len(entries)) * 100

    def get_last_failure(self, goal_pattern: str = "") -> Optional[MemoryEntry]:
        """Get most recent failed entry matching pattern."""
        entries = self.query(goal_pattern) if goal_pattern else self._entries
        failures = [e for e in entries if e.status != "success"]
        return failures[-1] if failures else None

    def suggest_fix(self, goal: str) -> str:
        """Suggest fix based on historical failure patterns."""
        failures = [e for e in self.query(goal) if e.status != "success"]
        if not failures:
            return "No failure history found for this goal."
        recent = failures[-5:]
        errors = [e.error_summary for e in recent if e.error_summary]
        if not errors:
            return f"Goal failed {len(failures)} time(s) but no error details recorded."
        unique_errors = list(dict.fromkeys(errors))
        return f"Common errors ({len(failures)} failures): " + "; ".join(unique_errors[:3])

    def get_similar_successes(self, goal: str, top_k: int = 3) -> List[MemoryEntry]:
        """Find successful executions similar to the given goal."""
        results = self._semantic_search(goal, top_k=top_k * 3)
        successes = [e for e in results if e.status == "success"]
        return successes[:top_k]

    def recent(self, limit: int = 20) -> List[MemoryEntry]:
        """Return most recent entries."""
        return self._entries[-limit:]

    def stats(self) -> Dict[str, Any]:
        """Return aggregate statistics."""
        goal_counts: Dict[str, int] = {}
        for e in self._entries:
            goal_counts[e.goal] = goal_counts.get(e.goal, 0) + 1
        top_goals = sorted(
            goal_counts, key=lambda k: goal_counts[k], reverse=True,
        )[:5]
        recent_failures = sum(
            1 for e in self._entries[-20:] if e.status != "success"
        )

        # Vector store stats
        vector_info: Dict[str, Any] = {}
        try:
            vector_info = self._vector_store.get_collection_info(
                self.VECTOR_COLLECTION,
            )
        except (KeyError, Exception):
            pass

        return {
            "total": len(self._entries),
            "success_rate": self.get_success_rate(),
            "top_goals": top_goals,
            "recent_failures": recent_failures,
            "vector_entries": vector_info.get("count", 0),
            "memory_types": vector_info.get("memory_types", {}),
        }

    def compress_old_memories(
        self, days_threshold: int = 7, keep_recent: int = 100,
    ) -> int:
        """
        Compress old memories by summarizing them.

        Entries older than days_threshold are grouped by goal and
        replaced with a summary entry.

        Args:
            days_threshold: Age in days after which to compress.
            keep_recent: Always keep this many recent entries.

        Returns:
            Number of entries compressed.
        """
        if len(self._entries) <= keep_recent:
            return 0

        cutoff = time.time() - (days_threshold * 86400)
        old_entries = [
            e for e in self._entries[:-keep_recent]
            if e.timestamp < cutoff
        ]

        if not old_entries:
            return 0

        # Group by goal
        goal_groups: Dict[str, List[MemoryEntry]] = {}
        for entry in old_entries:
            goal_groups.setdefault(entry.goal, []).append(entry)

        # Create summary entries
        compressed_count = 0
        for goal, entries in goal_groups.items():
            if len(entries) < 3:
                continue  # Not worth compressing

            successes = sum(1 for e in entries if e.status == "success")
            failures = len(entries) - successes
            errors = [e.error_summary for e in entries if e.error_summary]
            unique_errors = list(dict.fromkeys(errors))[:3]

            summary = MemoryEntry(
                goal=goal,
                status="success" if successes > failures else "failed",
                timestamp=entries[-1].timestamp,
                duration_ms=sum(e.duration_ms for e in entries) / len(entries),
                error_summary=(
                    f"[compressed {len(entries)} runs: "
                    f"{successes} ok, {failures} fail] "
                    + "; ".join(unique_errors)
                ),
                context={
                    "compressed": True,
                    "original_count": len(entries),
                    "success_rate": successes / len(entries),
                },
            )

            # Remove old entries and add summary
            for entry in entries:
                if entry in self._entries:
                    self._entries.remove(entry)
                    compressed_count += 1

            self._entries.append(summary)

        if compressed_count > 0:
            self._entries.sort(key=lambda e: e.timestamp)
            self._save()

        return compressed_count

    def clear(self) -> None:
        """Remove all entries and delete persistence files."""
        self._entries.clear()
        if self._path.exists():
            self._path.unlink()
        # Clear vector store
        try:
            self._vector_store.delete_collection(self.VECTOR_COLLECTION)
            self._vector_store.create_collection(
                self.VECTOR_COLLECTION, self.VECTOR_DIM,
            )
        except (KeyError, Exception):
            pass

    # ─── protocols.MemoryStore conformance ─────────────────────────────────

    def store(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Store bytes value under key conforming to protocols.MemoryStore.

        Bytes are base64-encoded into the entry context so arbitrary binary
        (non-UTF8) round-trips bit-exact. When ``ttl`` is given, an
        ``expires_at`` timestamp (seconds) is stored alongside; ``retrieve()``
        treats entries past that instant as absent.
        """
        context: Dict[str, Any] = {
            _VALUE_KEY: base64.b64encode(value).decode("ascii"),
        }
        if ttl is not None:
            context[_EXPIRES_KEY] = time.time() + ttl
        self.record(MemoryEntry(goal=key, status="success", context=context))

    def retrieve(self, key: str) -> bytes | None:
        """Return the most recent non-expired value for key, or None.

        Iterates query() results newest-first, skipping entries whose goal does
        not exactly match or whose TTL has elapsed, then decodes the base64
        value.
        """
        for entry in reversed(self.query(key)):
            if entry.goal != key or self._is_entry_expired(entry):
                continue
            decoded = self._decode_entry_value(entry)
            if decoded is not None:
                return decoded
        return None

    def delete(self, key: str) -> bool:
        """Remove all entries matching key. Returns True if anything was removed."""
        kept = []
        removed_entries = []
        for e in self._entries:
            if e.goal == key:
                removed_entries.append(e)
            else:
                kept.append(e)

        if not removed_entries:
            return False

        self._entries = kept
        self._save()

        # Clean up points from vector store
        for e in removed_entries:
            try:
                entry_id = hashlib.md5(
                    f"{e.goal}:{e.timestamp}".encode(),
                ).hexdigest()
                self._vector_store.delete_point(self.VECTOR_COLLECTION, entry_id)
            except Exception:
                pass

        return True

    def search(self, query: str, limit: int = 10) -> Sequence[MemoryHitResult]:
        """Semantic search with substring fallback, mapped to MemoryHit shapes.

        Conforms to protocols.MemoryStore. Results are de-duplicated by goal and
        capped at ``limit``.
        """
        hits: List[MemoryHitResult] = []
        seen: set[str] = set()

        # 1) Vector semantic search (canonical path).
        for entry in self.semantic_search(query, top_k=limit):
            self._accept_hit(entry, query, seen, score=1.0, out=hits)

        # 2) Substring fallback against stored goals.
        needle = query.lower()
        for entry in self._entries:
            if len(hits) >= limit:
                break
            if needle and needle not in entry.goal.lower():
                continue
            self._accept_hit(entry, query, seen, score=0.5, out=hits)

        return hits[:limit]

    def _is_entry_expired(self, entry: MemoryEntry) -> bool:
        """True if the entry has an expires_at timestamp that has elapsed."""
        expires_at = (entry.context or {}).get(_EXPIRES_KEY)
        return expires_at is not None and time.time() >= float(expires_at)

    def _decode_entry_value(self, entry: MemoryEntry) -> bytes | None:
        """Decode the base64-stored value from an entry's context, or None."""
        encoded = (entry.context or {}).get(_VALUE_KEY)
        if not encoded:
            return None
        try:
            return base64.b64decode(encoded.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            return None

    def _accept_hit(
        self,
        entry: MemoryEntry,
        query: str,
        seen: set[str],
        score: float,
        out: List[MemoryHitResult],
    ) -> bool:
        """Append entry as a hit if it matches and is fresh; True if added."""
        if entry.goal in seen or self._is_entry_expired(entry):
            return False
        if query and query.lower() not in entry.goal.lower():
            return False
        seen.add(entry.goal)
        out.append(
            MemoryHitResult(
                key=entry.goal,
                score=score,
                data=self._decode_entry_value(entry) or b"",
                metadata={
                    "status": entry.status,
                    "timestamp": entry.timestamp,
                },
            )
        )
        return True

    # --- Internal methods ---

    def _index_entry(self, entry: MemoryEntry) -> None:
        """Index a memory entry in the vector store."""
        try:
            text = f"{entry.goal} {entry.status} {entry.error_summary}"
            vector = VectorMemoryStore.text_to_hash_vector(
                text, self.VECTOR_DIM,
            )
            entry_id = hashlib.md5(
                f"{entry.goal}:{entry.timestamp}".encode(),
            ).hexdigest()

            mem_type = MemoryType.EPISODIC
            if entry.recipe_used:
                mem_type = MemoryType.PROCEDURAL

            self._vector_store.upsert(
                self.VECTOR_COLLECTION,
                id=entry_id,
                vector=vector,
                payload={
                    "goal": entry.goal,
                    "status": entry.status,
                    "timestamp": entry.timestamp,
                    "error_summary": entry.error_summary,
                    "recipe_used": entry.recipe_used,
                },
                memory_type=mem_type,
            )
        except Exception:
            pass  # Vector indexing failure never breaks YAML persistence

    def _semantic_search(
        self, query: str, top_k: int = 5,
    ) -> List[MemoryEntry]:
        """Search entries using vector similarity."""
        try:
            query_vector = VectorMemoryStore.text_to_hash_vector(
                query, self.VECTOR_DIM,
            )
            results = self._vector_store.search(
                self.VECTOR_COLLECTION, query_vector, top_k=top_k,
            )
            if not results:
                return []

            matched_entries: List[MemoryEntry] = []
            for vec_entry, score in results:
                if score < 0.3:
                    continue
                goal = vec_entry.payload.get("goal", "")
                for entry in self._entries:
                    if entry.goal == goal:
                        matched_entries.append(entry)
                        break

            return matched_entries
        except (KeyError, Exception):
            return []

    def _load(self) -> None:
        """Load entries from YAML file."""
        if not self._path.exists():
            return
        try:
            data = yaml.safe_load(self._path.read_text()) or []
            self._entries = [MemoryEntry(**item) for item in data]
        except Exception:
            self._entries = []

    def _save(self) -> None:
        """Persist entries to YAML file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(e) for e in self._entries]
        self._path.write_text(yaml.dump(data, default_flow_style=False))

    def _evict(self) -> None:
        """Remove oldest entries when exceeding MAX_ENTRIES (FIFO)."""
        if len(self._entries) > self.MAX_ENTRIES:
            self._entries = self._entries[-self.MAX_ENTRIES:]


__all__ = [
    "MemoryEntry",
    "MemoryHitResult",
    "MemoryStore",
]
