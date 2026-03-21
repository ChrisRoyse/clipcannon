"""Billing MCP tools for ClipCannon.

Provides four MCP tools for credit management:
  - clipcannon_credits_balance: Current balance and spending info
  - clipcannon_credits_history: Transaction history
  - clipcannon_credits_estimate: Cost estimate for an operation
  - clipcannon_spending_limit: Set monthly spending limit

All tools communicate with the local license server via LicenseClient.
"""

from __future__ import annotations

import logging

from mcp.types import Tool

from clipcannon.billing.credits import (
    CREDIT_RATES,
    check_spending_warning,
    estimate_cost,
)
from clipcannon.billing.license_client import LicenseClient

logger = logging.getLogger(__name__)

# Shared license client instance
_license_client: LicenseClient | None = None


def _get_client() -> LicenseClient:
    """Get or create the shared LicenseClient instance.

    Returns:
        The singleton LicenseClient.
    """
    global _license_client  # noqa: PLW0603
    if _license_client is None:
        _license_client = LicenseClient()
    return _license_client


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

BILLING_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_credits_balance",
        description=(
            "Get current credit balance, monthly spending, and spending limit. "
            "Shows warning if approaching the monthly limit."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="clipcannon_credits_history",
        description=(
            "Get transaction history showing charges, refunds, and purchases. "
            "Returns newest transactions first."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of transactions to return (default: 20)",
                    "default": 20,
                },
            },
        },
    ),
    Tool(
        name="clipcannon_credits_estimate",
        description=(
            "Estimate the credit cost for an operation before running it. "
            "Valid operations: analyze (10), render (2), metadata (1), publish (1)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "Operation to estimate cost for",
                    "enum": list(CREDIT_RATES.keys()),
                },
            },
            "required": ["operation"],
        },
    ),
    Tool(
        name="clipcannon_spending_limit",
        description=(
            "Set the monthly spending limit in credits. "
            "Operations that would exceed this limit will be blocked."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "limit_credits": {
                    "type": "integer",
                    "description": "Monthly spending limit in credits (0 = unlimited)",
                },
            },
            "required": ["limit_credits"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def clipcannon_credits_balance() -> dict[str, object]:
    """Get current credit balance and spending information.

    Returns:
        Dict with balance, spending_this_month, spending_limit, and
        optional warning message.
    """
    client = _get_client()
    balance_info = await client.get_balance()

    if balance_info.balance < 0:
        return {
            "error": {
                "code": "LICENSE_SERVER_UNREACHABLE",
                "message": (
                    "Cannot connect to the license server. "
                    "Start it with: clipcannon-license-server"
                ),
                "details": {},
            }
        }

    result: dict[str, object] = {
        "balance": balance_info.balance,
        "spending_this_month": balance_info.spending_this_month,
        "spending_limit": balance_info.spending_limit,
    }

    warning = check_spending_warning(
        balance_info.spending_this_month,
        balance_info.spending_limit,
    )
    if warning:
        result["warning"] = warning

    return result


async def clipcannon_credits_history(limit: int = 20) -> dict[str, object]:
    """Get transaction history.

    Args:
        limit: Maximum number of transactions to return.

    Returns:
        Dict with list of transaction records.
    """
    client = _get_client()
    records = await client.get_history(limit=limit)

    if not records:
        return {
            "transactions": [],
            "total": 0,
            "message": "No transactions found or license server unreachable.",
        }

    return {
        "transactions": [
            {
                "transaction_id": r.transaction_id,
                "operation": r.operation,
                "credits": r.credits,
                "balance_after": r.balance_after,
                "project_id": r.project_id,
                "reason": r.reason,
                "created_at": r.created_at,
            }
            for r in records
        ],
        "total": len(records),
    }


async def clipcannon_credits_estimate(operation: str) -> dict[str, object]:
    """Estimate credit cost for an operation.

    Args:
        operation: The operation name to estimate.

    Returns:
        Dict with operation name and estimated credit cost.
    """
    try:
        cost = estimate_cost(operation)
        return {
            "operation": operation,
            "credits": cost,
            "message": f"Operation '{operation}' costs {cost} credits.",
        }
    except Exception as exc:
        return {
            "error": {
                "code": "UNKNOWN_OPERATION",
                "message": str(exc),
                "details": {
                    "valid_operations": list(CREDIT_RATES.keys()),
                },
            }
        }


async def clipcannon_spending_limit(limit_credits: int) -> dict[str, object]:
    """Set the monthly spending limit.

    Args:
        limit_credits: The new monthly limit in credits.

    Returns:
        Dict with confirmation and new limit value.
    """
    if limit_credits < 0:
        return {
            "error": {
                "code": "INVALID_LIMIT",
                "message": "Spending limit must be non-negative.",
                "details": {},
            }
        }

    client = _get_client()
    try:
        http_client = await client._get_client()
        resp = await http_client.post(
            "/v1/spending_limit",
            json={"limit": limit_credits},
        )
        data = resp.json()
        return data
    except Exception as exc:
        logger.warning("Spending limit request failed: %s", exc)
        return {
            "error": {
                "code": "LICENSE_SERVER_UNREACHABLE",
                "message": (
                    "Cannot connect to the license server. "
                    "Start it with: clipcannon-license-server"
                ),
                "details": {},
            }
        }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

async def dispatch_billing_tool(
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    """Dispatch a billing tool call by name.

    Args:
        name: Tool name.
        arguments: Tool arguments dictionary.

    Returns:
        Tool result dictionary.
    """
    if name == "clipcannon_credits_balance":
        return await clipcannon_credits_balance()
    elif name == "clipcannon_credits_history":
        limit = int(arguments.get("limit", 20))  # type: ignore[arg-type]
        return await clipcannon_credits_history(limit=limit)
    elif name == "clipcannon_credits_estimate":
        return await clipcannon_credits_estimate(str(arguments["operation"]))
    elif name == "clipcannon_spending_limit":
        return await clipcannon_spending_limit(int(arguments["limit_credits"]))  # type: ignore[arg-type]

    return {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": f"Unknown billing tool: {name}",
            "details": {},
        }
    }
