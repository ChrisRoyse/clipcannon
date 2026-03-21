"""SHA-256 hashing utilities for ClipCannon provenance tracking.

Provides streaming file hashing (safe for >10GB files), byte/string hashing,
table content hashing, and hash verification. All functions raise
ProvenanceError on failure.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path

from clipcannon.exceptions import ProvenanceError

logger = logging.getLogger(__name__)

# 8KB read buffer for streaming file hashing
_CHUNK_SIZE = 8192


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file using streaming reads.

    Reads the file in 8KB chunks to handle files larger than available
    memory (e.g., 10GB+ source videos).

    Args:
        path: Path to the file to hash.

    Returns:
        Lowercase hex digest string (64 characters).

    Raises:
        ProvenanceError: If the file does not exist, is not a file,
            or cannot be read.
    """
    if not path.exists():
        raise ProvenanceError(
            f"File not found for hashing: {path}",
            details={"path": str(path)},
        )
    if not path.is_file():
        raise ProvenanceError(
            f"Path is not a regular file: {path}",
            details={"path": str(path)},
        )

    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(_CHUNK_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)
    except OSError as exc:
        raise ProvenanceError(
            f"Failed to read file for hashing: {path}: {exc}",
            details={"path": str(path), "error": str(exc)},
        ) from exc

    digest = hasher.hexdigest()
    logger.debug("SHA-256 of %s: %s", path, digest)
    return digest


def sha256_bytes(data: bytes) -> str:
    """Compute SHA-256 hex digest of raw bytes.

    Args:
        data: Bytes to hash.

    Returns:
        Lowercase hex digest string (64 characters).

    Raises:
        ProvenanceError: If hashing fails.
    """
    try:
        digest = hashlib.sha256(data).hexdigest()
    except Exception as exc:
        raise ProvenanceError(
            f"Failed to hash bytes: {exc}",
            details={"data_length": len(data), "error": str(exc)},
        ) from exc

    logger.debug("SHA-256 of %d bytes: %s", len(data), digest)
    return digest


def sha256_string(data: str) -> str:
    """Compute SHA-256 hex digest of a string (UTF-8 encoded).

    Args:
        data: String to hash.

    Returns:
        Lowercase hex digest string (64 characters).

    Raises:
        ProvenanceError: If encoding or hashing fails.
    """
    try:
        digest = hashlib.sha256(data.encode("utf-8")).hexdigest()
    except Exception as exc:
        raise ProvenanceError(
            f"Failed to hash string: {exc}",
            details={"data_length": len(data), "error": str(exc)},
        ) from exc

    logger.debug("SHA-256 of string (%d chars): %s", len(data), digest)
    return digest


def sha256_table_content(
    conn: sqlite3.Connection,
    table_name: str,
    project_id: str,
) -> str:
    """Compute SHA-256 of deterministically serialized table rows.

    Queries all rows for the given project_id, sorts them by all columns,
    and hashes the JSON serialization. This produces a repeatable hash
    for the same data regardless of insertion order.

    Args:
        conn: SQLite connection (must use dict row factory).
        table_name: Name of the table to hash.
        project_id: Project ID to filter rows by.

    Returns:
        Lowercase hex digest string (64 characters).

    Raises:
        ProvenanceError: If the query or hashing fails.
    """
    # Validate table name to prevent SQL injection (alphanumeric + underscore)
    if not table_name.replace("_", "").isalnum():
        raise ProvenanceError(
            f"Invalid table name: {table_name}",
            details={"table_name": table_name},
        )

    try:
        cursor = conn.execute(
            f"SELECT * FROM {table_name} WHERE project_id = ? ORDER BY rowid",  # noqa: S608
            (project_id,),
        )
        rows = cursor.fetchall()
    except sqlite3.Error as exc:
        raise ProvenanceError(
            f"Failed to query table {table_name} for hashing: {exc}",
            details={
                "table_name": table_name,
                "project_id": project_id,
                "error": str(exc),
            },
        ) from exc

    # Convert rows to sorted, deterministic JSON
    try:
        # Each row is a dict (from dict row factory) or a tuple
        if rows and isinstance(rows[0], dict):
            # Sort rows by sorted tuple of all key-value pairs
            sorted_rows = sorted(
                rows,
                key=lambda r: json.dumps(r, sort_keys=True, default=str),
            )
            serialized = json.dumps(sorted_rows, sort_keys=True, default=str)
        else:
            # Fallback for tuple rows
            sorted_rows = sorted(rows)
            serialized = json.dumps(
                [list(r) for r in sorted_rows],
                sort_keys=True,
                default=str,
            )
    except (TypeError, ValueError) as exc:
        raise ProvenanceError(
            f"Failed to serialize table {table_name} for hashing: {exc}",
            details={
                "table_name": table_name,
                "project_id": project_id,
                "row_count": len(rows),
                "error": str(exc),
            },
        ) from exc

    digest = sha256_string(serialized)
    logger.debug(
        "SHA-256 of %s (project=%s, %d rows): %s",
        table_name,
        project_id,
        len(rows),
        digest,
    )
    return digest


def verify_file_hash(path: Path, expected_hash: str) -> bool:
    """Verify that a file matches an expected SHA-256 hash.

    Args:
        path: Path to the file to verify.
        expected_hash: Expected lowercase hex digest string.

    Returns:
        True if the file hash matches, False otherwise.

    Raises:
        ProvenanceError: If the file cannot be read or hashed.
    """
    actual_hash = sha256_file(path)
    matches = actual_hash == expected_hash.lower()

    if not matches:
        logger.warning(
            "Hash mismatch for %s: expected=%s, actual=%s",
            path,
            expected_hash,
            actual_hash,
        )
    else:
        logger.debug("Hash verified for %s", path)

    return matches
