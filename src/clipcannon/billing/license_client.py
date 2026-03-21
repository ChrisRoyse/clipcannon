"""HTTP client for the ClipCannon license server.

Provides an async interface to the local license server running on
port 3100. Used by MCP tools to charge credits, issue refunds, and
query balance/history. Handles connection errors gracefully since
the license server may not be running during development.
"""

from __future__ import annotations

import logging
import uuid

import httpx
from pydantic import BaseModel, Field

from clipcannon.billing.credits import estimate_cost
from clipcannon.billing.hmac_integrity import get_machine_id
from clipcannon.exceptions import BillingError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------

class ChargeResult(BaseModel):
    """Result of a credit charge operation."""

    success: bool
    balance_before: int = 0
    balance_after: int = 0
    transaction_id: str = ""
    timestamp: str = ""
    error: str = ""
    message: str = ""


class RefundResult(BaseModel):
    """Result of a credit refund operation."""

    success: bool
    balance_before: int = 0
    balance_after: int = 0
    transaction_id: str = ""
    timestamp: str = ""
    error: str = ""
    message: str = ""


class BalanceInfo(BaseModel):
    """Current credit balance information."""

    balance: int = 0
    balance_hmac: str = ""
    last_sync_utc: str = ""
    spending_this_month: int = 0
    spending_limit: int = 200


class TransactionRecord(BaseModel):
    """A single transaction history entry."""

    transaction_id: str
    operation: str
    credits: int
    balance_before: int = 0
    balance_after: int = 0
    project_id: str = ""
    reason: str = ""
    created_at: str = ""


# ---------------------------------------------------------------------------
# License client
# ---------------------------------------------------------------------------

class LicenseClient:
    """Async client for the local ClipCannon license server.

    Communicates with the license server HTTP API to manage credit
    balances. All methods handle connection errors gracefully, returning
    failure results instead of raising on network issues.

    Attributes:
        base_url: The license server base URL.
        machine_id: The HMAC-derived machine identifier.
    """

    def __init__(self, base_url: str = "http://localhost:3100") -> None:
        """Initialize the license client.

        Args:
            base_url: The license server base URL (default: http://localhost:3100).
        """
        self.base_url = base_url.rstrip("/")
        self.machine_id = get_machine_id()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client.

        Returns:
            An httpx.AsyncClient configured for the license server.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=5.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client connection."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def charge(
        self,
        operation: str,
        credits: int,
        project_id: str,
        idempotency_key: str | None = None,
    ) -> ChargeResult:
        """Charge credits for an operation.

        Args:
            operation: The operation type (e.g. "analyze").
            credits: Number of credits to charge.
            project_id: The project being charged for.
            idempotency_key: Optional UUID to prevent double charges.

        Returns:
            ChargeResult with success/failure details.
        """
        if idempotency_key is None:
            idempotency_key = str(uuid.uuid4())

        payload = {
            "machine_id": self.machine_id,
            "operation": operation,
            "credits": credits,
            "project_id": project_id,
            "idempotency_key": idempotency_key,
        }

        try:
            client = await self._get_client()
            resp = await client.post("/v1/charge", json=payload)
            data = resp.json()
            return ChargeResult(**data)
        except httpx.ConnectError:
            logger.warning("License server not reachable at %s", self.base_url)
            return ChargeResult(
                success=False,
                error="LICENSE_SERVER_UNREACHABLE",
                message=(
                    f"Cannot connect to license server at {self.base_url}. "
                    "Start it with: clipcannon-license-server"
                ),
            )
        except Exception as exc:
            logger.error("Charge request failed: %s", exc)
            return ChargeResult(
                success=False,
                error="CHARGE_FAILED",
                message=str(exc),
            )

    async def refund(
        self,
        transaction_id: str,
        reason: str,
        project_id: str = "",
    ) -> RefundResult:
        """Refund credits for a failed operation.

        Args:
            transaction_id: The original charge transaction ID.
            reason: Reason for the refund.
            project_id: The project the refund is for.

        Returns:
            RefundResult with success/failure details.
        """
        payload = {
            "machine_id": self.machine_id,
            "transaction_id": transaction_id,
            "reason": reason,
            "project_id": project_id,
        }

        try:
            client = await self._get_client()
            resp = await client.post("/v1/refund", json=payload)
            data = resp.json()
            return RefundResult(**data)
        except httpx.ConnectError:
            logger.warning("License server not reachable at %s", self.base_url)
            return RefundResult(
                success=False,
                error="LICENSE_SERVER_UNREACHABLE",
                message=f"Cannot connect to license server at {self.base_url}.",
            )
        except Exception as exc:
            logger.error("Refund request failed: %s", exc)
            return RefundResult(
                success=False,
                error="REFUND_FAILED",
                message=str(exc),
            )

    async def get_balance(self) -> BalanceInfo:
        """Get the current credit balance.

        Returns:
            BalanceInfo with current balance, HMAC, and spending info.
        """
        try:
            client = await self._get_client()
            resp = await client.get("/v1/balance")
            data = resp.json()
            return BalanceInfo(**data)
        except httpx.ConnectError:
            logger.warning("License server not reachable at %s", self.base_url)
            return BalanceInfo(balance=-1)
        except Exception as exc:
            logger.error("Balance request failed: %s", exc)
            return BalanceInfo(balance=-1)

    async def get_history(self, limit: int = 20) -> list[TransactionRecord]:
        """Get transaction history.

        Args:
            limit: Maximum number of records to return (default: 20).

        Returns:
            List of TransactionRecord entries, newest first.
        """
        try:
            client = await self._get_client()
            resp = await client.get("/v1/history", params={"limit": limit})
            data = resp.json()
            records = data.get("transactions", [])
            return [TransactionRecord(**r) for r in records]
        except httpx.ConnectError:
            logger.warning("License server not reachable at %s", self.base_url)
            return []
        except Exception as exc:
            logger.error("History request failed: %s", exc)
            return []

    async def estimate(self, operation: str) -> int:
        """Estimate the credit cost for an operation.

        This is a local lookup -- no server call needed.

        Args:
            operation: The operation name.

        Returns:
            The estimated credit cost.

        Raises:
            BillingError: If the operation is unknown.
        """
        return estimate_cost(operation)
