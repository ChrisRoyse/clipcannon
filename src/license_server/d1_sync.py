"""Cloudflare D1 sync module for ClipCannon license server.

Phase 1 operates in LOCAL-ONLY mode. The local SQLite database is the
source of truth during development. No actual Cloudflare D1 connection
is made. The interface is designed so that real D1 integration can be
added in Phase 2 by implementing the sync functions.

In production (Phase 2+), the sync flow will be:
  - On charge/refund: local write -> async push to D1
  - On startup: pull from D1 to initialize local cache
  - Periodic: pull from D1 every 5 minutes for external changes
  - Conflict: D1 is source of truth, replay unsynced local txns
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Set via environment variable when real D1 is configured.
D1_API_URL = os.environ.get("CLIPCANNON_D1_API_URL", "")
D1_API_TOKEN = os.environ.get("CLIPCANNON_D1_API_TOKEN", "")


def is_d1_configured() -> bool:
    """Check whether Cloudflare D1 credentials are configured.

    Returns:
        True if both D1_API_URL and D1_API_TOKEN are set.
    """
    return bool(D1_API_URL) and bool(D1_API_TOKEN)


def sync_push() -> str:
    """Push local transactions to Cloudflare D1.

    In Phase 1 (local-only mode), this is a no-op that logs a skip message.
    In Phase 2+, this will POST unsynced transactions to the D1 API.

    Returns:
        A status message string.
    """
    if not is_d1_configured():
        msg = (
            "D1 sync skipped (local-only mode)."
            " Set CLIPCANNON_D1_API_URL and"
            " CLIPCANNON_D1_API_TOKEN to enable."
        )
        logger.info(msg)
        return msg

    # Phase 2 implementation placeholder:
    # 1. Read unsynced transactions (synced_to_d1 = FALSE)
    # 2. POST batch to D1 API
    # 3. Mark transactions as synced
    # 4. Log to sync_log table
    logger.info("D1 sync push would execute here (not implemented in Phase 1)")
    return "D1 sync push not yet implemented."


def sync_pull() -> str:
    """Pull balance updates from Cloudflare D1.

    In Phase 1 (local-only mode), this is a no-op that logs a skip message.
    In Phase 2+, this will GET the canonical balance from D1 and update
    the local SQLite cache, handling conflicts per the spec.

    Returns:
        A status message string.
    """
    if not is_d1_configured():
        msg = (
            "D1 sync skipped (local-only mode)."
            " Set CLIPCANNON_D1_API_URL and"
            " CLIPCANNON_D1_API_TOKEN to enable."
        )
        logger.info(msg)
        return msg

    # Phase 2 implementation placeholder:
    # 1. GET /balance from D1
    # 2. Compare with local balance
    # 3. If D1 > local: user purchased credits, apply D1 balance
    # 4. If D1 < local: local has unsynced charges, push them
    # 5. Re-sign local balance with HMAC
    # 6. Log to sync_log table
    logger.info("D1 sync pull would execute here (not implemented in Phase 1)")
    return "D1 sync pull not yet implemented."


def log_sync_event(
    direction: str,
    d1_balance: int | None,
    local_balance: int | None,
    status: str,
    error_message: str = "",
) -> None:
    """Log a sync event to the sync_log table.

    This will be used by the real D1 sync implementation in Phase 2+.
    For Phase 1, it simply logs to the Python logger.

    Args:
        direction: Sync direction ('push' or 'pull').
        d1_balance: The D1 balance at time of sync, or None.
        local_balance: The local balance at time of sync, or None.
        status: Sync status ('success', 'failed', 'conflict').
        error_message: Error details if status is 'failed'.
    """
    logger.info(
        "Sync event: direction=%s, d1=%s, local=%s, status=%s, error=%s",
        direction,
        d1_balance,
        local_balance,
        status,
        error_message or "(none)",
    )
