"""Billing and credit management for ClipCannon.

Provides HMAC-SHA256 balance integrity, credit rate definitions,
and an async client for the license server HTTP API.
"""

from clipcannon.billing.credits import (
    CREDIT_PACKAGES,
    CREDIT_RATES,
    check_spending_warning,
    estimate_cost,
    validate_spending_limit,
)
from clipcannon.billing.hmac_integrity import (
    get_machine_id,
    sign_balance,
    verify_balance,
    verify_balance_or_raise,
)
from clipcannon.billing.license_client import (
    BalanceInfo,
    ChargeResult,
    LicenseClient,
    RefundResult,
    TransactionRecord,
)

__all__ = [
    "BalanceInfo",
    "CREDIT_PACKAGES",
    "CREDIT_RATES",
    "ChargeResult",
    "LicenseClient",
    "RefundResult",
    "TransactionRecord",
    "check_spending_warning",
    "estimate_cost",
    "get_machine_id",
    "sign_balance",
    "validate_spending_limit",
    "verify_balance",
    "verify_balance_or_raise",
]
