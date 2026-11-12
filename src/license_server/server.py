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
import sqlite3 as sqlite3
import uuid as uuid
from contextlib import asynccontextmanager
from datetime import UTC as UTC
from datetime import datetime as datetime
from pathlib import Path as Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel as BaseModel
from pydantic import Field as Field

from clipcannon.billing.hmac_integrity import get_machine_id as get_machine_id
from clipcannon.billing.hmac_integrity import sign_balance as sign_balance
from clipcannon.billing.hmac_integrity import verify_balance_or_raise as verify_balance_or_raise
from clipcannon.exceptions import BillingError
from license_server.billing_routes import add_credits_dev, charge_credits, refund_credits
from license_server.db import _SCHEMA_SQL as _SCHEMA_SQL
from license_server.db import DB_DIR as DB_DIR
from license_server.db import DB_PATH as DB_PATH
from license_server.db import DEFAULT_SPENDING_LIMIT as DEFAULT_SPENDING_LIMIT
from license_server.db import DEV_INITIAL_CREDITS as DEV_INITIAL_CREDITS
from license_server.db import _get_db, _init_db, _read_balance
from license_server.db import _write_balance as _write_balance
from license_server.models import AddCreditsRequest as AddCreditsRequest
from license_server.models import ChargeRequest as ChargeRequest
from license_server.models import RefundRequest as RefundRequest
from license_server.models import SpendingLimitRequest  # noqa: TC001 - FastAPI needs it

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

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


app.post("/v1/charge")(charge_credits)
app.post("/v1/refund")(refund_credits)


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


app.post("/v1/add_credits")(add_credits_dev)


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
