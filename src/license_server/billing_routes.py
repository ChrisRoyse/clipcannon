"""Credit-moving endpoints of the license server: charge, refund, add credits.

Split out of ``license_server.server`` (pure move). The handlers are plain
coroutines here; ``license_server.server`` registers them on the FastAPI
app at their original paths and in their original order.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException

from license_server.db import _get_db, _read_balance, _write_balance
from license_server.models import (  # noqa: TC001 - FastAPI resolves body types at runtime
    AddCreditsRequest,
    ChargeRequest,
    RefundRequest,
)

logger = logging.getLogger(__name__)


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
        now = datetime.now(UTC).isoformat()

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
        now = datetime.now(UTC).isoformat()

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
        now = datetime.now(UTC).isoformat()

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
