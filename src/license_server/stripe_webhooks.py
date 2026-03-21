"""Stripe webhook handler for ClipCannon license server.

Handles Stripe checkout.session.completed events to add purchased
credits to the user's balance. In Phase 1, includes a manual credit
add endpoint for testing without a real Stripe integration.

The webhook signature is verified when STRIPE_WEBHOOK_SECRET is set
in the environment. Without it, the endpoint accepts unsigned payloads
(dev mode only).
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import logging
import os
import sqlite3
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, Request

from clipcannon.billing.hmac_integrity import sign_balance

logger = logging.getLogger(__name__)

router = APIRouter()

# Credit packages matching Stripe product metadata.
PACKAGES: dict[str, int] = {
    "starter": 50,
    "creator": 250,
    "pro": 1000,
    "studio": 5000,
}

STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")


def _verify_stripe_signature(
    payload: bytes,
    signature: str,
    secret: str,
) -> bool:
    """Verify a Stripe webhook signature.

    Uses the Stripe-Signature header format: t=timestamp,v1=signature.
    Computes HMAC-SHA256 of timestamp.payload using the webhook secret.

    Args:
        payload: Raw request body bytes.
        signature: The Stripe-Signature header value.
        secret: The STRIPE_WEBHOOK_SECRET.

    Returns:
        True if the signature is valid, False otherwise.
    """
    try:
        parts = dict(item.split("=", 1) for item in signature.split(",") if "=" in item)
        timestamp = parts.get("t", "")
        sig_v1 = parts.get("v1", "")
        if not timestamp or not sig_v1:
            return False

        signed_payload = f"{timestamp}.".encode() + payload
        expected = hmac_mod.new(
            secret.encode(),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac_mod.compare_digest(expected, sig_v1)
    except Exception:
        logger.exception("Failed to verify Stripe signature")
        return False


def _get_db_path() -> str:
    """Get the license database path.

    Returns:
        Absolute path to the license.db file.
    """
    from pathlib import Path

    return str(Path.home() / ".clipcannon" / "license.db")


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
) -> dict[str, str]:
    """Handle Stripe webhook events.

    Processes checkout.session.completed events to add purchased
    credits. Verifies the webhook signature if STRIPE_WEBHOOK_SECRET
    is configured.

    Args:
        request: The incoming HTTP request.
        stripe_signature: The Stripe-Signature header.

    Returns:
        Acknowledgement response.

    Raises:
        HTTPException: If signature verification fails or event is invalid.
    """
    body = await request.body()

    # Verify signature if secret is configured
    if STRIPE_WEBHOOK_SECRET:
        if not _verify_stripe_signature(body, stripe_signature, STRIPE_WEBHOOK_SECRET):
            logger.warning("Invalid Stripe webhook signature")
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        logger.debug("Stripe signature verification skipped (no secret configured)")

    try:
        event = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    event_type = event.get("type", "")
    logger.info("Received Stripe event: %s", event_type)

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(event)
    else:
        logger.info("Ignoring Stripe event type: %s", event_type)

    return {"status": "ok"}


async def _handle_checkout_completed(event: dict[str, object]) -> None:
    """Handle a checkout.session.completed Stripe event.

    Extracts the package name and machine_id from session metadata,
    looks up the credit amount, and adds credits to the balance.

    Args:
        event: The parsed Stripe event dictionary.

    Raises:
        HTTPException: If required metadata is missing or package is unknown.
    """
    session = event.get("data", {}).get("object", {})  # type: ignore[union-attr]
    metadata = session.get("metadata", {}) if isinstance(session, dict) else {}  # type: ignore[union-attr]

    package = metadata.get("package", "") if isinstance(metadata, dict) else ""
    machine_id = metadata.get("machine_id", "") if isinstance(metadata, dict) else ""

    if not package or not machine_id:
        logger.error("Missing package or machine_id in checkout metadata")
        raise HTTPException(
            status_code=400,
            detail="Missing package or machine_id in session metadata.",
        )

    credits_to_add = PACKAGES.get(str(package))
    if credits_to_add is None:
        logger.error("Unknown package: %s", package)
        raise HTTPException(
            status_code=400,
            detail=f"Unknown package: {package}",
        )

    # Add credits to local balance
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT balance, machine_id FROM balance WHERE id = 1").fetchone()

        if row is None:
            logger.error("Balance record not found during Stripe webhook")
            raise HTTPException(status_code=500, detail="Balance record not found.")

        current_balance: int = row["balance"]
        db_machine_id: str = row["machine_id"]
        new_balance = current_balance + credits_to_add
        new_hmac = sign_balance(new_balance, db_machine_id)
        now = datetime.now(UTC).isoformat()
        txn_id = f"txn_{uuid.uuid4().hex[:12]}"

        conn.execute(
            """UPDATE balance SET
               balance = ?, balance_hmac = ?, updated_at = ?
               WHERE id = 1""",
            (new_balance, new_hmac, now),
        )

        conn.execute(
            """INSERT INTO transactions
               (transaction_id, machine_id, operation, credits,
                balance_before, balance_after, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                txn_id,
                db_machine_id,
                "stripe_purchase",
                credits_to_add,
                current_balance,
                new_balance,
                f"package:{package}",
                now,
            ),
        )
        conn.commit()

        logger.info(
            "Stripe purchase: +%d credits (%s), balance %d -> %d",
            credits_to_add,
            package,
            current_balance,
            new_balance,
        )

    finally:
        conn.close()
