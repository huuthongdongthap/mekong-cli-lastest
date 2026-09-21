# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Credit system for RaaS tenant billing.

Manages credit balances and transactions using SQLite with
atomic operations to prevent race conditions.
"""

import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("MEKONG_RAAS_DB") or Path.home() / ".mekong" / "raas" / "tenants.db")

MISSION_COSTS: dict[str, int] = {
    "simple": 1,
    "standard": 3,
    "complex": 5,
}


@dataclass
class CreditAccount:
    """Represents a tenant's credit account."""

    tenant_id: str
    balance: int
    total_earned: int
    total_spent: int


@dataclass
class CreditTransaction:
    """Represents a single credit transaction (debit or credit)."""

    id: str
    tenant_id: str
    amount: int  # positive = credit, negative = debit
    reason: str
    timestamp: str  # ISO 8601
    idempotency_key: str | None = None


class CreditStore:
    """SQLite-backed credit store with atomic operations.

    Uses WAL mode and EXCLUSIVE transactions to ensure balance
    consistency under concurrent access.
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        """Initialize the store, creating DB directory and tables if needed."""
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Return a configured SQLite connection with WAL mode and busy timeout."""
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create tables if they do not already exist."""
        try:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS credit_accounts (
                        tenant_id TEXT PRIMARY KEY,
                        balance INTEGER NOT NULL DEFAULT 0,
                        total_earned INTEGER NOT NULL DEFAULT 0,
                        total_spent INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS credit_transactions (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        amount INTEGER NOT NULL,
                        reason TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        idempotency_key TEXT
                    );
                    """
                )
                # Migration: add idempotency_key column when upgrading from
                # older schema (column already present after CREATE TABLE above
                # on fresh DBs, so ignore "duplicate column" error).
                try:
                    conn.execute(
                        "ALTER TABLE credit_transactions "
                        "ADD COLUMN idempotency_key TEXT"
                    )
                except sqlite3.OperationalError:
                    pass  # Column already exists
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "idx_credit_transactions_idempotency_key "
                    "ON credit_transactions(idempotency_key) "
                    "WHERE idempotency_key IS NOT NULL"
                )
        except sqlite3.Error as exc:
            raise RuntimeError(f"CreditStore: failed to initialize DB: {exc}") from exc

    @staticmethod
    def _now_iso() -> str:
        """Return current UTC time as ISO 8601 string."""
        return datetime.now(timezone.utc).isoformat()

    def _record_transaction(
        self,
        conn: sqlite3.Connection,
        tenant_id: str,
        amount: int,
        reason: str,
        idempotency_key: str | None = None,
    ) -> None:
        """Insert a transaction row (must be called within an open connection)."""
        conn.execute(
            "INSERT INTO credit_transactions "
            "(id, tenant_id, amount, reason, timestamp, idempotency_key) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                tenant_id,
                amount,
                reason,
                self._now_iso(),
                idempotency_key,
            ),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_balance(self, tenant_id: str) -> int:
        """Return the current credit balance for a tenant.

        Returns 0 if the tenant has no account.
        """
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT balance FROM credit_accounts WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchone()
                return int(row["balance"]) if row else 0
        except sqlite3.Error as exc:
            raise RuntimeError(f"CreditStore.get_balance failed: {exc}") from exc

    def get_transaction(self, idempotency_key: str) -> CreditTransaction | None:
        """Return the transaction for a given idempotency key, or None."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT id, tenant_id, amount, reason, timestamp, idempotency_key "
                    "FROM credit_transactions WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if row is None:
                    return None
                return CreditTransaction(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    amount=row["amount"],
                    reason=row["reason"],
                    timestamp=row["timestamp"],
                    idempotency_key=row["idempotency_key"],
                )
        except sqlite3.Error as exc:
            raise RuntimeError(f"CreditStore.get_transaction failed: {exc}") from exc

    def add_credits(
        self,
        tenant_id: str,
        amount: int,
        reason: str,
        idempotency_key: str | None = None,
    ) -> int:
        """Add credits to a tenant account. Returns new balance.

        If idempotency_key is provided and a transaction with that key already
        exists, the existing balance is returned without adding credits again.
        This makes webhook retries safe (Stripe/NOWPayments may re-deliver).
        """
        if amount <= 0:
            raise ValueError("Credit amount must be positive")

        try:
            conn = self._connect()
            try:
                conn.execute("BEGIN EXCLUSIVE")

                # Idempotency guard: skip if already processed
                if idempotency_key is not None:
                    existing = conn.execute(
                        "SELECT id FROM credit_transactions WHERE idempotency_key = ?",
                        (idempotency_key,),
                    ).fetchone()
                    if existing:
                        row = conn.execute(
                            "SELECT balance FROM credit_accounts WHERE tenant_id = ?",
                            (tenant_id,),
                        ).fetchone()
                        conn.execute("COMMIT")
                        return int(row["balance"]) if row else 0

                row = conn.execute(
                    "SELECT balance FROM credit_accounts WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchone()

                current = int(row["balance"]) if row else 0
                new_balance = current + amount

                if row:
                    conn.execute(
                        "UPDATE credit_accounts "
                        "SET balance = ?, total_earned = total_earned + ? "
                        "WHERE tenant_id = ?",
                        (new_balance, amount, tenant_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO credit_accounts "
                        "(tenant_id, balance, total_earned, total_spent) "
                        "VALUES (?, ?, ?, 0)",
                        (tenant_id, new_balance, amount),
                    )

                self._record_transaction(conn, tenant_id, amount, reason)
                conn.execute("COMMIT")
                return new_balance
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise RuntimeError(f"CreditStore.add_credits failed: {exc}") from exc

    def deduct(
        self,
        tenant_id: str,
        amount: int,
        reason: str,
        idempotency_key: str | None = None,
    ) -> bool:
        """Atomically deduct credits from a tenant account.

        Uses BEGIN EXCLUSIVE TRANSACTION to prevent double-spend.
        If idempotency_key is provided, a duplicate key prevents re-deduction.

        Args:
            tenant_id: Target tenant identifier.
            amount: Positive integer number of credits to deduct.
            reason: Human-readable reason for the deduction.
            idempotency_key: Optional unique key to prevent duplicate deductions.

        Returns:
            True if deduction succeeded or was already processed,
            False if insufficient balance.
        """
        if amount <= 0:
            raise ValueError("Deduction amount must be positive")

        try:
            conn = self._connect()
            try:
                conn.execute("BEGIN EXCLUSIVE")

                # Idempotency guard: check inside the same exclusive transaction
                if idempotency_key is not None:
                    existing = conn.execute(
                        "SELECT id FROM credit_transactions WHERE idempotency_key = ?",
                        (idempotency_key,),
                    ).fetchone()
                    if existing is not None:
                        # Already processed — idempotent re-entry, no balance change
                        conn.execute("ROLLBACK")
                        return True

                row = conn.execute(
                    "SELECT balance FROM credit_accounts WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchone()

                current = int(row["balance"]) if row else 0
                if current < amount:
                    conn.execute("ROLLBACK")
                    return False

                new_balance = current - amount
                if row:
                    conn.execute(
                        "UPDATE credit_accounts "
                        "SET balance = ?, total_spent = total_spent + ? "
                        "WHERE tenant_id = ?",
                        (new_balance, amount, tenant_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO credit_accounts "
                        "(tenant_id, balance, total_earned, total_spent) "
                        "VALUES (?, ?, 0, ?)",
                        (tenant_id, new_balance, amount),
                    )

                self._record_transaction(
                    conn, tenant_id, -amount, reason, idempotency_key
                )
                conn.execute("COMMIT")
                return True
            except sqlite3.Error:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise RuntimeError(f"CreditStore.deduct failed: {exc}") from exc

    def add(self, tenant_id: str, amount: int, reason: str) -> int:
        """Add credits to a tenant account, creating it if necessary.

        Args:
            tenant_id: Target tenant identifier.
            amount: Positive integer number of credits to add.
            reason: Human-readable reason for the addition.

        Returns:
            New balance after the addition.
        """
        if amount <= 0:
            raise ValueError("Credit amount must be positive")

        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO credit_accounts (tenant_id, balance, total_earned, total_spent)
                    VALUES (?, ?, ?, 0)
                    ON CONFLICT(tenant_id) DO UPDATE SET
                        balance = balance + excluded.balance,
                        total_earned = total_earned + excluded.total_earned
                    """,
                    (tenant_id, amount, amount),
                )
                self._record_transaction(conn, tenant_id, amount, reason)
                row = conn.execute(
                    "SELECT balance FROM credit_accounts WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchone()
                return int(row["balance"])
        except sqlite3.Error as exc:
            raise RuntimeError(f"CreditStore.add failed: {exc}") from exc

    def get_history(
        self, tenant_id: str, limit: int = 50
    ) -> list[CreditTransaction]:
        """Return recent transactions for a tenant, newest first.

        Args:
            tenant_id: Target tenant identifier.
            limit: Maximum number of transactions to return.

        Returns:
            List of CreditTransaction objects ordered by timestamp descending.
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT id, tenant_id, amount, reason, timestamp, idempotency_key "
                    "FROM credit_transactions "
                    "WHERE tenant_id = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (tenant_id, limit),
                ).fetchall()
                return [
                    CreditTransaction(
                        id=row["id"],
                        tenant_id=row["tenant_id"],
                        amount=row["amount"],
                        reason=row["reason"],
                        timestamp=row["timestamp"],
                        idempotency_key=row["idempotency_key"],
                    )
                    for row in rows
                ]
        except sqlite3.Error as exc:
            raise RuntimeError(f"CreditStore.get_history failed: {exc}") from exc
