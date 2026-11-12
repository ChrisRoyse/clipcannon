"""Request bodies of the license server API.

Split out of ``license_server.server`` (pure move).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

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
