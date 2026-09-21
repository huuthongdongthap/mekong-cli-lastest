# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tenant storage and management for RaaS multi-tenant isolation.

This module is the canonical synchronous tenant store for the RaaS layer.
It backs the FastAPI auth dependency (:func:`src.raas.auth.get_tenant_context`),
the checkout / revenue / dashboard routers, and the RaaS test suite — all of
which call ``TenantStore`` synchronously.

.. deprecated::
    New code should use :mod:`src.models.particle` (``ParticleRepository``)
    for particle-level economic events.  ``TenantStore`` remains the
    authoritative source of tenant identity and API keys and is **not**
    scheduled for removal; the deprecation marker is retained for historical
    accuracy only.

Storage:
    SQLite at ``~/.mekong/raas/tenants.db`` by default.  The path can be
    overridden via the ``db_path`` constructor argument, which makes the
    store trivially testable without touching the real user database.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# Re-export Tenant from the particle module so callers that import
# ``Tenant`` from here continue to work after the Phase 8 consolidation.
from src.models.particle import Tenant  # noqa: F401  (re-export)

logger = logging.getLogger(__name__)

_DB_PATH = Path(os.environ.get("MEKONG_RAAS_DB") or Path.home() / ".mekong" / "raas" / "tenants.db")

_DDL = """
CREATE TABLE IF NOT EXISTS tenants (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    api_key_hash TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL,
    is_active    INTEGER NOT NULL DEFAULT 1
);
"""


@dataclass
class _TenantRow:
    """Internal row projection used by :class:`TenantStore`."""

    id: str
    name: str
    api_key_hash: str
    created_at: str
    is_active: int


class TenantStore:
    """Synchronous SQLite-backed tenant store.

    The synchronous API is intentional: the RaaS auth dependency runs inside
    a FastAPI request handler and must not spawn an event loop per request.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Initialise the store.

        Args:
            db_path: SQLite database path. Defaults to
                ``~/.mekong/raas/tenants.db``.  Pass a ``tmp_path`` in tests
                to isolate them from the real user database.
        """
        self.db_path = Path(db_path) if db_path else _DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialise(self) -> None:
        """Create the tenants table if it does not exist."""
        try:
            with self._connect() as conn:
                conn.execute(_DDL)
                conn.commit()
        except sqlite3.Error as exc:
            raise RuntimeError(f"Failed to initialise tenant DB: {exc}") from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_tenant(self, name: str) -> Tenant:
        """Create a new tenant and return it with the plaintext API key.

        The plaintext key is **only** returned here; subsequent look-ups
        return an empty string for ``api_key``.

        Args:
            name: Human-readable label for the tenant.

        Returns:
            Tenant with ``api_key`` set to the new ``mk_``-prefixed key.

        Raises:
            RuntimeError: If the DB write fails.
        """
        tenant_id = str(uuid.uuid4())
        raw_key = "mk_" + uuid.uuid4().hex
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        created_at = datetime.now(timezone.utc).isoformat()

        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO tenants (id, name, api_key_hash, created_at, "
                    "is_active) VALUES (?, ?, ?, ?, 1)",
                    (tenant_id, name, key_hash, created_at),
                )
                conn.commit()
        except sqlite3.Error as exc:
            raise RuntimeError(f"Failed to create tenant '{name}': {exc}") from exc

        return Tenant(
            id=tenant_id,
            name=name,
            api_key=raw_key,
            created_at=created_at,
            is_active=True,
        )

    def get_by_api_key(self, key: str) -> Optional[Tenant]:
        """Return the :class:`Tenant` whose hashed key matches *key*.

        Args:
            key: Plaintext ``mk_``-prefixed API key supplied by the caller.

        Returns:
            Matching :class:`Tenant` or ``None`` if not found.

        Raises:
            RuntimeError: If the DB query fails.
        """
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM tenants WHERE api_key_hash = ?", (key_hash,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise RuntimeError(f"Failed to look up API key: {exc}") from exc

        if row is None:
            return None
        return _row_to_tenant(row)

    def find_by_email(self, email: str) -> Optional[Tenant]:
        """Find a tenant by name (used as email lookup).

        Args:
            email: Tenant name/email to search for.

        Returns:
            Matching :class:`Tenant` or ``None`` if not found.

        Raises:
            RuntimeError: If the DB query fails.
        """
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM tenants WHERE name = ?", (email,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise RuntimeError(f"Failed to look up tenant by email: {exc}") from exc

        return _row_to_tenant(row) if row else None

    def list_tenants(self) -> List[Tenant]:
        """Return all active tenants ordered by creation date.

        Returns:
            List of :class:`Tenant` objects (``api_key`` is empty string).

        Raises:
            RuntimeError: If the DB query fails.
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM tenants WHERE is_active = 1 "
                    "ORDER BY created_at ASC"
                ).fetchall()
        except sqlite3.Error as exc:
            raise RuntimeError(f"Failed to list tenants: {exc}") from exc

        return [_row_to_tenant(r) for r in rows]

    def deactivate_tenant(self, tenant_id: str) -> bool:
        """Soft-delete a tenant by marking it inactive.

        Args:
            tenant_id: UUID4 string of the tenant to deactivate.

        Returns:
            ``True`` if a row was updated, ``False`` if *tenant_id* was not
            found.

        Raises:
            RuntimeError: If the DB update fails.
        """
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE tenants SET is_active = 0 WHERE id = ?",
                    (tenant_id,),
                )
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as exc:
            raise RuntimeError(
                f"Failed to deactivate tenant '{tenant_id}': {exc}"
            ) from exc

    def tenant_exists(self, tenant_id: str) -> bool:
        """Check whether a tenant id exists.

        Args:
            tenant_id: Tenant UUID string.

        Returns:
            True if the tenant exists, False otherwise.
        """
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM tenants WHERE id = ? LIMIT 1",
                    (tenant_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise RuntimeError(f"Failed to check tenant existence: {exc}") from exc
        return row is not None


def _row_to_tenant(row: sqlite3.Row) -> Tenant:
    """Map a SQLite row to a :class:`Tenant` dataclass instance."""
    return Tenant(
        id=row["id"],
        name=row["name"],
        api_key="",  # plaintext key is never stored; only returned at creation
        created_at=row["created_at"],
        is_active=bool(row["is_active"]),
    )


__all__ = ["Tenant", "TenantStore"]