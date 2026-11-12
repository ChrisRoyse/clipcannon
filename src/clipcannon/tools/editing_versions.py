"""Editing helpers: edit version history and branch column migrations."""

from __future__ import annotations

import logging
import secrets
import sqlite3 as _sqlite3
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_one

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.editing.edl import EditDecisionList

logger = logging.getLogger(__name__)


# ============================================================
# EDIT VERSION MANAGEMENT
# ============================================================
_EDIT_VERSIONS_DDL = """
CREATE TABLE IF NOT EXISTS edit_versions (
    version_id TEXT PRIMARY KEY,
    edit_id TEXT NOT NULL,
    parent_version_id TEXT,
    version_number INTEGER NOT NULL,
    edl_json TEXT NOT NULL,
    change_description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (edit_id) REFERENCES edits(edit_id)
);
CREATE INDEX IF NOT EXISTS idx_edit_versions_edit
    ON edit_versions(edit_id, version_number);
"""


def ensure_branch_columns(conn: _sqlite3.Connection) -> None:
    """Ensure parent_edit_id and branch_name columns exist on the edits table.

    Handles migration for existing databases that were created before
    edit branching was added.

    Args:
        conn: SQLite connection.
    """
    try:
        conn.execute("SELECT parent_edit_id FROM edits LIMIT 1")
    except _sqlite3.OperationalError:
        conn.execute("ALTER TABLE edits ADD COLUMN parent_edit_id TEXT")
        logger.info("Added parent_edit_id column to edits table (migration).")

    try:
        conn.execute("SELECT branch_name FROM edits LIMIT 1")
    except _sqlite3.OperationalError:
        conn.execute("ALTER TABLE edits ADD COLUMN branch_name TEXT DEFAULT 'main'")
        logger.info("Added branch_name column to edits table (migration).")


def ensure_edit_versions_table(conn: _sqlite3.Connection) -> None:
    """Ensure the edit_versions table exists, creating it if needed.

    This handles migration for existing databases that were created
    before version history was added.

    Args:
        conn: SQLite connection.
    """
    try:
        conn.execute("SELECT 1 FROM edit_versions LIMIT 1")
    except _sqlite3.OperationalError:
        conn.executescript(_EDIT_VERSIONS_DDL)
        logger.info("Created edit_versions table (migration).")


def generate_change_description(
    current_edl: EditDecisionList,
    changes: dict[str, object],
) -> str:
    """Auto-generate a human-readable change description from a diff.

    Compares the changes dict keys against the current EDL to produce
    a summary like "Changed name, updated 3 segments".

    Args:
        current_edl: The current EDL before changes.
        changes: The incoming changes dict.

    Returns:
        Human-readable change description string.
    """
    parts: list[str] = []

    if "name" in changes:
        old_name = current_edl.name
        new_name = str(changes["name"])
        if old_name != new_name:
            parts.append(f"Changed name from '{old_name}' to '{new_name}'")
        else:
            parts.append("Name unchanged")

    if "segments" in changes:
        raw_segs = changes["segments"]
        if isinstance(raw_segs, list):
            old_count = len(current_edl.segments)
            new_count = len(raw_segs)
            if new_count != old_count:
                parts.append(f"Updated segments ({old_count} -> {new_count})")
            else:
                parts.append(f"Updated {new_count} segments")
        else:
            parts.append("Modified segments")

    if "captions" in changes:
        parts.append("Updated captions")

    if "crop" in changes:
        parts.append("Updated crop settings")

    if "audio" in changes:
        parts.append("Updated audio settings")

    if "metadata" in changes:
        parts.append("Updated metadata")

    if "render_settings" in changes:
        parts.append("Updated render settings")

    if not parts:
        parts.append("Modification (no recognized fields)")

    return ", ".join(parts)


def save_edit_version(
    db: Path,
    edit_id: str,
    edl_json: str,
    changes: dict[str, object],
    current_edl: EditDecisionList,
) -> str:
    """Save the current EDL state as a version before modification.

    Computes the next version_number, generates a change description,
    and inserts a row into edit_versions.

    Args:
        db: Path to the project database.
        edit_id: Edit identifier.
        edl_json: Current EDL JSON string to save.
        changes: The incoming changes dict (for description generation).
        current_edl: The current EDL model (for description generation).

    Returns:
        The version_id of the saved version.
    """
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        ensure_edit_versions_table(conn)

        max_row = fetch_one(
            conn,
            "SELECT MAX(version_number) as max_ver FROM edit_versions "
            "WHERE edit_id = ?",
            (edit_id,),
        )
        next_ver = (
            int(max_row["max_ver"]) + 1
            if max_row and max_row["max_ver"] is not None
            else 1
        )

        version_id = f"ver_{secrets.token_hex(6)}"
        change_desc = generate_change_description(current_edl, changes)

        # Find parent version (the latest version, if any)
        parent_row = fetch_one(
            conn,
            "SELECT version_id FROM edit_versions "
            "WHERE edit_id = ? ORDER BY version_number DESC LIMIT 1",
            (edit_id,),
        )
        parent_id = str(parent_row["version_id"]) if parent_row else None

        execute(
            conn,
            """INSERT INTO edit_versions (
                version_id, edit_id, parent_version_id, version_number,
                edl_json, change_description
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (version_id, edit_id, parent_id, next_ver, edl_json, change_desc),
        )
        conn.commit()

        logger.info(
            "Saved edit version %s (v%d) for edit %s: %s",
            version_id, next_ver, edit_id, change_desc,
        )
        return version_id
    finally:
        conn.close()
