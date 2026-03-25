"""Credit management routes for the ClipCannon dashboard.

Provides endpoints to check credit balance, view transaction history,
add credits in dev mode, and list available credit packages.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query

from clipcannon.billing import CREDIT_PACKAGES, CREDIT_RATES, LicenseClient
from clipcannon.dashboard.auth import is_dev_mode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/credits", tags=["credits"])

# Singleton license client (reused across requests)
_license_client: LicenseClient | None = None


def _get_license_client() -> LicenseClient:
    """Get or create the license client singleton.

    Returns:
        LicenseClient instance.
    """
    global _license_client  # noqa: PLW0603
    if _license_client is None:
        base_url = os.environ.get("CLIPCANNON_LICENSE_URL", "http://localhost:3100")
        _license_client = LicenseClient(base_url=base_url)
    return _license_client


@router.get("/balance")
async def get_balance() -> dict[str, object]:
    """Get the current credit balance.

    Queries the license server for balance information. Returns a
    fallback balance when the server is unreachable.

    Returns:
        Dictionary with balance, HMAC, and spending info.
    """
    client = _get_license_client()

    try:
        balance_info = await client.get_balance()
        return {
            "balance": balance_info.balance,
            "balance_hmac": balance_info.balance_hmac,
            "last_sync_utc": balance_info.last_sync_utc,
            "spending_this_month": balance_info.spending_this_month,
            "spending_limit": balance_info.spending_limit,
            "server_reachable": balance_info.balance >= 0,
        }
    except Exception as exc:
        logger.error("License server unreachable: %s", exc)
        return {
            "server_reachable": False,
            "error": f"LICENSE_SERVER_UNREACHABLE: {exc}",
        }


@router.get("/history")
async def get_history(
    limit: int = Query(default=20, ge=1, le=100, description="Max records to return"),
) -> dict[str, object]:
    """Get credit transaction history.

    Args:
        limit: Maximum number of transactions to return (1-100).

    Returns:
        Dictionary with transaction list and metadata.
    """
    client = _get_license_client()

    try:
        transactions = await client.get_history(limit=limit)
        return {
            "transactions": [t.model_dump() for t in transactions],
            "count": len(transactions),
            "limit": limit,
        }
    except Exception as exc:
        logger.warning("Failed to get history: %s", exc)
        return {
            "transactions": [],
            "count": 0,
            "limit": limit,
            "error": str(exc),
        }


@router.post("/add")
async def add_credits(
    amount: int = Query(default=100, ge=1, le=10000, description="Credits to add"),
) -> dict[str, object]:
    """Add credits in development mode.

    This endpoint is only available when CLIPCANNON_DEV_MODE is enabled.
    It simulates adding credits by calling the license server refund endpoint.

    Args:
        amount: Number of credits to add (1-10000).

    Returns:
        Dictionary with result of the credit addition.
    """
    if not is_dev_mode():
        return {
            "success": False,
            "error": "DEV_MODE_ONLY",
            "message": "Adding credits directly is only available in dev mode.",
        }

    client = _get_license_client()

    try:
        # Use a refund-style call to add credits in dev mode
        result = await client.refund(
            transaction_id=f"dev-add-{uuid.uuid4().hex[:8]}",
            reason=f"Dev mode credit addition: {amount} credits",
            project_id="dev-dashboard",
        )

        return {
            "success": result.success,
            "amount": amount,
            "balance_after": result.balance_after,
            "timestamp": datetime.now(UTC).isoformat(),
            "message": f"Added {amount} credits in dev mode." if result.success else result.error,
        }
    except Exception as exc:
        logger.warning("Failed to add credits: %s", exc)
        return {
            "success": False,
            "amount": amount,
            "error": str(exc),
            "message": ("License server unreachable. Start it with: clipcannon-license-server"),
        }


@router.get("/packages")
async def get_packages() -> dict[str, object]:
    """List available credit packages with prices.

    Returns:
        Dictionary with available packages and credit rates.
    """
    packages = [
        {
            "name": name,
            "credits": info["credits"],
            "price_cents": info["price_cents"],
            "price_display": f"${info['price_cents'] / 100:.2f}",
            "per_credit_cents": round(info["price_cents"] / info["credits"], 2),
        }
        for name, info in CREDIT_PACKAGES.items()
    ]

    return {
        "packages": packages,
        "credit_rates": CREDIT_RATES,
    }
