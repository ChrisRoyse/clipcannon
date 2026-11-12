"""License database: configuration, schema, connection and balance I/O.

Split out of ``license_server.server`` (pure move). ``DB_DIR`` and
``DB_PATH`` live here and ``_get_db`` reads them from this module, so a
caller that redirects the database must patch ``license_server.db``.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from clipcannon.billing.hmac_integrity import (
    get_machine_id,
    sign_balance,
    verify_balance_or_raise,
)
from clipcannon.exceptions import BillingError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_DIR = Path.home() / ".clipcannon"
DB_PATH = DB_DIR / "license.db"
DEV_INITIAL_CREDITS = 100
DEFAULT_SPENDING_LIMIT = 200


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS balance (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    machine_id TEXT NOT NULL,
    balance INTEGER NOT NULL DEFAULT 0,
    balance_hmac TEXT NOT NULL,
    last_sync_utc TEXT,
    spending_this_month INTEGER DEFAULT 0,
    spending_limit INTEGER DEFAULT 200,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    credits INTEGER NOT NULL,
    balance_before INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    project_id TEXT,
    idempotency_key TEXT UNIQUE,
    reason TEXT,
    synced_to_d1 BOOLEAN DEFAULT FALSE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_transactions_time
    ON transactions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_project
    ON transactions(project_id);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL,
    d1_balance INTEGER,
    local_balance INTEGER,
    status TEXT,
    error_message TEXT,
    synced_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _get_db() -> sqlite3.Connection:
    """Open a connection to the license database.

    Returns:
        A sqlite3 Connection with row_factory set to sqlite3.Row.
    """
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db() -> None:
    """Initialize the database schema and seed dev balance."""
    conn = _get_db()
    try:
        conn.executescript(_SCHEMA_SQL)

        # Check if balance row exists
        row = conn.execute("SELECT id FROM balance WHERE id = 1").fetchone()
        if row is None:
            machine_id = get_machine_id()
            hmac_sig = sign_balance(DEV_INITIAL_CREDITS, machine_id)
            now = datetime.now(UTC).isoformat()
            conn.execute(
                """INSERT INTO balance
                   (id, machine_id, balance, balance_hmac, last_sync_utc,
                    spending_this_month, spending_limit, updated_at)
                   VALUES (1, ?, ?, ?, ?, 0, ?, ?)""",
                (
                    machine_id,
                    DEV_INITIAL_CREDITS,
                    hmac_sig,
                    now,
                    DEFAULT_SPENDING_LIMIT,
                    now,
                ),
            )
            conn.commit()
            logger.info(
                "Initialized dev balance: %d credits, machine_id=%s",
                DEV_INITIAL_CREDITS,
                machine_id[:8] + "...",
            )
        else:
            logger.info("License database already initialized.")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Balance helpers
# ---------------------------------------------------------------------------


def _read_balance(conn: sqlite3.Connection) -> dict[str, int | str]:
    """Read and verify the current balance.

    Args:
        conn: Database connection.

    Returns:
        Dict with balance row data.

    Raises:
        BillingError: If HMAC verification fails (tamper detected).
    """
    row = conn.execute(
        "SELECT machine_id, balance, balance_hmac, last_sync_utc, "
        "spending_this_month, spending_limit, updated_at "
        "FROM balance WHERE id = 1"
    ).fetchone()

    if row is None:
        raise BillingError(
            "Balance record not found. Database may be corrupted.",
            details={"code": "BALANCE_NOT_FOUND"},
        )

    verify_balance_or_raise(
        balance=row["balance"],
        expected_hmac=row["balance_hmac"],
        machine_id=row["machine_id"],
    )

    return dict(row)


def _write_balance(
    conn: sqlite3.Connection,
    new_balance: int,
    machine_id: str,
    spending_delta: int = 0,
) -> None:
    """Write a new balance with HMAC signing.

    Args:
        conn: Database connection.
        new_balance: The new credit balance.
        machine_id: Machine identifier for HMAC derivation.
        spending_delta: Credits to add to spending_this_month (positive).
    """
    new_hmac = sign_balance(new_balance, machine_id)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """UPDATE balance SET
           balance = ?,
           balance_hmac = ?,
           spending_this_month = spending_this_month + ?,
           updated_at = ?
           WHERE id = 1""",
        (new_balance, new_hmac, spending_delta, now),
    )
