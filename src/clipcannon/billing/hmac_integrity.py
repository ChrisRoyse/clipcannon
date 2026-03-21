"""HMAC-SHA256 balance integrity verification for ClipCannon.

Provides machine-derived HMAC signing and verification for credit balances.
On tamper detection, raises BillingError with BALANCE_TAMPERED code and logs
the full context of the tampering attempt before raising.

The machine ID is deterministic: same hardware always produces the same ID.
The HMAC key is derived from the machine ID, making signed balances
non-transferable between machines.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import logging
import platform
import uuid

from clipcannon.exceptions import BillingError

logger = logging.getLogger(__name__)


def get_machine_id() -> str:
    """Derive a deterministic machine ID from hardware characteristics.

    Combines platform hostname, MAC address, and CPU architecture into
    a SHA-256 hash truncated to 32 hex characters. The same physical
    machine always produces the same ID.

    Returns:
        A 32-character hex string uniquely identifying this machine.
    """
    raw = f"{platform.node()}|{uuid.getnode()}|{platform.machine()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def derive_hmac_key(machine_id: str) -> bytes:
    """Derive an HMAC signing key from a machine ID.

    Uses a versioned salt prefix to allow key rotation in future versions
    without breaking existing installations during the same version.

    Args:
        machine_id: The 32-char hex machine identifier.

    Returns:
        A 32-byte HMAC key derived from the machine ID.
    """
    return hashlib.sha256(f"clipcannon-v1|{machine_id}".encode()).digest()


def sign_balance(balance: int, machine_id: str) -> str:
    """Sign a credit balance value with the machine-derived HMAC key.

    Args:
        balance: The credit balance integer to sign.
        machine_id: The machine identifier used to derive the HMAC key.

    Returns:
        A hex-encoded HMAC-SHA256 signature string.
    """
    key = derive_hmac_key(machine_id)
    payload = f"balance:{balance}".encode()
    return hmac_mod.new(key, payload, hashlib.sha256).hexdigest()


def verify_balance(balance: int, expected_hmac: str, machine_id: str) -> bool:
    """Verify that a balance has not been tampered with.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        balance: The credit balance integer to verify.
        expected_hmac: The HMAC signature stored alongside the balance.
        machine_id: The machine identifier used to derive the HMAC key.

    Returns:
        True if the HMAC matches, False if tampered.
    """
    actual = sign_balance(balance, machine_id)
    return hmac_mod.compare_digest(actual, expected_hmac)


def verify_balance_or_raise(
    balance: int,
    expected_hmac: str,
    machine_id: str,
) -> None:
    """Verify balance integrity and raise on tamper detection.

    Logs the full tampering context before raising BillingError so that
    forensic information is preserved even if the caller catches and
    suppresses the exception.

    Args:
        balance: The credit balance integer to verify.
        expected_hmac: The HMAC signature stored alongside the balance.
        machine_id: The machine identifier used to derive the HMAC key.

    Raises:
        BillingError: If the HMAC does not match (code=BALANCE_TAMPERED).
    """
    if not verify_balance(balance, expected_hmac, machine_id):
        actual_hmac = sign_balance(balance, machine_id)
        logger.critical(
            "BALANCE TAMPERED: balance=%d, stored_hmac=%s, expected_hmac=%s, machine_id=%s",
            balance,
            expected_hmac,
            actual_hmac,
            machine_id,
        )
        raise BillingError(
            "Credit balance integrity check failed. The balance file has been tampered with.",
            details={
                "code": "BALANCE_TAMPERED",
                "balance": balance,
                "stored_hmac": expected_hmac[:8] + "...",
                "machine_id": machine_id[:8] + "...",
            },
        )
