"""ClipCannon license server — FastAPI HTTP service on port 3100.

Manages credit balances in a local SQLite database with HMAC-SHA256
integrity verification on every read and write. Supports idempotent
charges, refunds, balance queries, and transaction history.

The server initializes with 100 credits in dev mode for testing.

Usage:
    uvicorn license_server.server:app --port 3100
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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
            now = datetime.now(timezone.utc).isoformat()
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
# Request/Response models
# ---------------------------------------------------------------------------

class ChargeRequest(BaseModel):
    """Credit charge request body."""

    machine_id: str
    operation: str
    credits: int
    project_id: str = ""
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()))


class RefundRequest(BaseModel):
    """Credit refund request body."""

    machine_id: str
    transaction_id: str
    reason: str = ""
    project_id: str = ""


class AddCreditsRequest(BaseModel):
    """Manual credit addition for dev/testing."""

    credits: int
    reason: str = "manual_add"


class SpendingLimitRequest(BaseModel):
    """Update the monthly spending limit."""

    limit: int


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
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE balance SET
           balance = ?,
           balance_hmac = ?,
           spending_this_month = spending_this_month + ?,
           updated_at = ?
           WHERE id = 1""",
        (new_balance, new_hmac, spending_delta, now),
    )


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize the database on startup."""
    _init_db()
    logger.info("License server started on port 3100")
    yield
    logger.info("License server shutting down")


app = FastAPI(
    title="ClipCannon License Server",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(BillingError)
async def billing_error_handler(request: Request, exc: BillingError) -> JSONResponse:
    """Convert BillingError to a structured JSON response."""
    code = exc.details.get("code", "BILLING_ERROR") if exc.details else "BILLING_ERROR"
    status = 403 if code == "BALANCE_TAMPERED" else 400
    return JSONResponse(
        status_code=status,
        content={
            "success": False,
            "error": code,
            "message": exc.message,
            "details": exc.details or {},
        },
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint.

    Returns:
        Status and server version.
    """
    return {"status": "healthy", "version": "1.0.0", "service": "clipcannon-license-server"}


@app.post("/v1/charge")
async def charge_credits(req: ChargeRequest) -> dict[str, object]:
    """Charge credits for an operation.

    Supports idempotency keys to prevent double charges. If the same
    idempotency_key is reused, the original transaction result is returned.

    Args:
        req: ChargeRequest with operation details.

    Returns:
        Charge result with balance before/after and transaction ID.
    """
    conn = _get_db()
    try:
        # Check idempotency
        existing = conn.execute(
            "SELECT transaction_id, balance_before, balance_after, created_at "
            "FROM transactions WHERE idempotency_key = ?",
            (req.idempotency_key,),
        ).fetchone()

        if existing is not None:
            logger.info("Idempotent replay for key=%s", req.idempotency_key)
            return {
                "success": True,
                "balance_before": existing["balance_before"],
                "balance_after": existing["balance_after"],
                "transaction_id": existing["transaction_id"],
                "timestamp": existing["created_at"],
                "idempotent_replay": True,
            }

        # Read and verify current balance
        bal = _read_balance(conn)
        current_balance: int = bal["balance"]  # type: ignore[assignment]
        machine_id: str = bal["machine_id"]  # type: ignore[assignment]
        spending: int = bal["spending_this_month"]  # type: ignore[assignment]
        limit: int = bal["spending_limit"]  # type: ignore[assignment]

        # Check sufficient credits
        if current_balance < req.credits:
            return {
                "success": False,
                "error": "INSUFFICIENT_CREDITS",
                "balance": current_balance,
                "required": req.credits,
                "message": (
                    f"Need {req.credits} credits but only {current_balance} available. "
                    "Purchase more at the dashboard."
                ),
            }

        # Check spending limit
        if (spending + req.credits) > limit:
            return {
                "success": False,
                "error": "SPENDING_LIMIT_EXCEEDED",
                "spending_this_month": spending,
                "spending_limit": limit,
                "required": req.credits,
                "message": (
                    f"This charge would exceed your monthly spending limit "
                    f"({spending + req.credits}/{limit} credits)."
                ),
            }

        # Execute charge
        new_balance = current_balance - req.credits
        txn_id = f"txn_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        _write_balance(conn, new_balance, machine_id, spending_delta=req.credits)

        conn.execute(
            """INSERT INTO transactions
               (transaction_id, machine_id, operation, credits,
                balance_before, balance_after, project_id,
                idempotency_key, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                txn_id,
                machine_id,
                req.operation,
                -req.credits,
                current_balance,
                new_balance,
                req.project_id,
                req.idempotency_key,
                now,
            ),
        )
        conn.commit()

        logger.info(
            "Charged %d credits: %s, balance %d -> %d (txn=%s)",
            req.credits,
            req.operation,
            current_balance,
            new_balance,
            txn_id,
        )

        return {
            "success": True,
            "balance_before": current_balance,
            "balance_after": new_balance,
            "transaction_id": txn_id,
            "timestamp": now,
        }

    finally:
        conn.close()


@app.post("/v1/refund")
async def refund_credits(req: RefundRequest) -> dict[str, object]:
    """Refund credits for a failed operation.

    Looks up the original transaction, creates a refund transaction,
    and restores the credited amount to the balance.

    Args:
        req: RefundRequest with transaction and reason details.

    Returns:
        Refund result with balance before/after.
    """
    conn = _get_db()
    try:
        # Look up original transaction
        orig = conn.execute(
            "SELECT credits, operation FROM transactions WHERE transaction_id = ?",
            (req.transaction_id,),
        ).fetchone()

        if orig is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "success": False,
                    "error": "TRANSACTION_NOT_FOUND",
                    "message": f"Transaction {req.transaction_id} not found.",
                },
            )

        # Credits in DB are negative for charges; refund is the absolute value
        refund_amount = abs(orig["credits"])

        # Read and verify current balance
        bal = _read_balance(conn)
        current_balance: int = bal["balance"]  # type: ignore[assignment]
        machine_id: str = bal["machine_id"]  # type: ignore[assignment]

        new_balance = current_balance + refund_amount
        txn_id = f"txn_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        # Reduce spending_this_month (spending_delta is negative for refund)
        _write_balance(conn, new_balance, machine_id, spending_delta=-refund_amount)

        conn.execute(
            """INSERT INTO transactions
               (transaction_id, machine_id, operation, credits,
                balance_before, balance_after, project_id,
                reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                txn_id,
                machine_id,
                f"refund:{orig['operation']}",
                refund_amount,
                current_balance,
                new_balance,
                req.project_id,
                req.reason,
                now,
            ),
        )
        conn.commit()

        logger.info(
            "Refunded %d credits for txn=%s, balance %d -> %d",
            refund_amount,
            req.transaction_id,
            current_balance,
            new_balance,
        )

        return {
            "success": True,
            "balance_before": current_balance,
            "balance_after": new_balance,
            "transaction_id": txn_id,
            "refunded_transaction": req.transaction_id,
            "credits_refunded": refund_amount,
            "timestamp": now,
        }

    finally:
        conn.close()


@app.get("/v1/balance")
async def get_balance() -> dict[str, object]:
    """Get the current credit balance with HMAC verification.

    Returns:
        Balance info including HMAC, sync time, and spending stats.
    """
    conn = _get_db()
    try:
        bal = _read_balance(conn)
        return {
            "balance": bal["balance"],
            "balance_hmac": bal["balance_hmac"],
            "last_sync_utc": bal["last_sync_utc"] or "",
            "spending_this_month": bal["spending_this_month"],
            "spending_limit": bal["spending_limit"],
        }
    finally:
        conn.close()


@app.get("/v1/history")
async def get_history(limit: int = 20, offset: int = 0) -> dict[str, object]:
    """Get transaction history, newest first.

    Args:
        limit: Maximum number of records to return.
        offset: Number of records to skip for pagination.

    Returns:
        Transaction list with total count.
    """
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT transaction_id, operation, credits, balance_before, "
            "balance_after, project_id, reason, created_at "
            "FROM transactions ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()

        total = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

        transactions = [dict(r) for r in rows]
        return {
            "transactions": transactions,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        conn.close()


@app.post("/v1/sync")
async def force_sync() -> dict[str, str]:
    """Force sync with Cloudflare D1 (stub for Phase 1).

    Returns:
        Sync status message.
    """
    from license_server.d1_sync import sync_push

    result = sync_push()
    return {"status": "ok", "message": result}


@app.post("/v1/add_credits")
async def add_credits_dev(req: AddCreditsRequest) -> dict[str, object]:
    """Manually add credits for dev/testing purposes.

    This endpoint is for development only. In production, credits are
    added exclusively via Stripe webhook.

    Args:
        req: AddCreditsRequest with credits and reason.

    Returns:
        Updated balance info.
    """
    conn = _get_db()
    try:
        bal = _read_balance(conn)
        current_balance: int = bal["balance"]  # type: ignore[assignment]
        machine_id: str = bal["machine_id"]  # type: ignore[assignment]

        new_balance = current_balance + req.credits
        txn_id = f"txn_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        _write_balance(conn, new_balance, machine_id, spending_delta=0)

        conn.execute(
            """INSERT INTO transactions
               (transaction_id, machine_id, operation, credits,
                balance_before, balance_after, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                txn_id,
                machine_id,
                "credit_add",
                req.credits,
                current_balance,
                new_balance,
                req.reason,
                now,
            ),
        )
        conn.commit()

        logger.info(
            "Dev credit add: +%d credits, balance %d -> %d",
            req.credits,
            current_balance,
            new_balance,
        )

        return {
            "success": True,
            "balance_before": current_balance,
            "balance_after": new_balance,
            "credits_added": req.credits,
            "transaction_id": txn_id,
            "timestamp": now,
        }
    finally:
        conn.close()


@app.post("/v1/spending_limit")
async def set_spending_limit(req: SpendingLimitRequest) -> dict[str, object]:
    """Update the monthly spending limit.

    Args:
        req: SpendingLimitRequest with the new limit.

    Returns:
        Updated spending limit info.
    """
    if req.limit < 0:
        raise HTTPException(status_code=400, detail="Spending limit must be non-negative.")

    conn = _get_db()
    try:
        conn.execute(
            "UPDATE balance SET spending_limit = ? WHERE id = 1",
            (req.limit,),
        )
        conn.commit()

        return {
            "success": True,
            "spending_limit": req.limit,
            "message": f"Monthly spending limit set to {req.limit} credits.",
        }
    finally:
        conn.close()


def main() -> None:
    """Run the license server with uvicorn."""
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    _init_db()
    uvicorn.run(app, host="0.0.0.0", port=3100)


if __name__ == "__main__":
    main()
