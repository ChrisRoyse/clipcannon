"""Credit rate system for ClipCannon billing.

Defines credit costs per operation and provides estimation and spending
limit validation. Phase 1 only uses the "analyze" operation at 10 credits.
Future phases will add render, metadata, and publish operations.
"""

from __future__ import annotations

import logging

from clipcannon.exceptions import BillingError

logger = logging.getLogger(__name__)

# Credit costs per operation.
# Phase 1: only "analyze" is active (10 credits per video analysis).
# Phase 2+: render (2), metadata (1), publish (1).
CREDIT_RATES: dict[str, int] = {
    "analyze": 10,
    "render": 2,
    "metadata": 1,
    "publish": 1,
}

# Credit packages available for purchase via Stripe.
CREDIT_PACKAGES: dict[str, dict[str, int]] = {
    "starter": {"credits": 50, "price_cents": 500},
    "creator": {"credits": 250, "price_cents": 2000},
    "pro": {"credits": 1000, "price_cents": 6000},
    "studio": {"credits": 5000, "price_cents": 20000},
}


def estimate_cost(operation: str) -> int:
    """Estimate the credit cost for a given operation.

    Args:
        operation: The operation name (e.g. "analyze", "render").

    Returns:
        The credit cost as a positive integer.

    Raises:
        BillingError: If the operation is not recognized.
    """
    if operation not in CREDIT_RATES:
        raise BillingError(
            f"Unknown billing operation: {operation}",
            details={
                "code": "UNKNOWN_OPERATION",
                "operation": operation,
                "valid_operations": list(CREDIT_RATES.keys()),
            },
        )
    return CREDIT_RATES[operation]


def validate_spending_limit(
    current_spending: int,
    new_charge: int,
    limit: int,
) -> bool:
    """Check whether a new charge would exceed the monthly spending limit.

    Args:
        current_spending: Credits already spent this month.
        new_charge: Credits the new operation would cost.
        limit: The monthly spending limit in credits.

    Returns:
        True if the charge is within the limit, False if it would exceed it.
    """
    return (current_spending + new_charge) <= limit


def check_spending_warning(current_spending: int, limit: int) -> str | None:
    """Check if spending is approaching the monthly limit.

    Returns a warning message at 80% of the limit, None otherwise.

    Args:
        current_spending: Credits already spent this month.
        limit: The monthly spending limit in credits.

    Returns:
        A warning string if at or above 80% of limit, None otherwise.
    """
    if limit <= 0:
        return None
    ratio = current_spending / limit
    if ratio >= 1.0:
        return f"Monthly spending limit reached ({current_spending}/{limit} credits)."
    if ratio >= 0.8:
        return (
            f"Warning: approaching monthly limit "
            f"({current_spending}/{limit} credits, {ratio:.0%} used)."
        )
    return None
