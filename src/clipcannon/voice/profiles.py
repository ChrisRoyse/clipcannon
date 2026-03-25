"""Voice profile CRUD operations for ClipCannon.

Manages voice profiles stored in a central voice_profiles table.
Each profile tracks model path, training status, and thresholds.
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
from pathlib import Path

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one

logger = logging.getLogger(__name__)

_VOICE_PROFILES_DDL = """
CREATE TABLE IF NOT EXISTS voice_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    model_path TEXT NOT NULL,
    training_hours REAL DEFAULT 0,
    training_projects TEXT DEFAULT '[]',
    sample_rate INTEGER DEFAULT 24000,
    reference_embedding BLOB,
    verification_threshold REAL DEFAULT 0.80,
    training_status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_voice_profiles_name ON voice_profiles(name);
"""

_ALLOWED_UPDATE_FIELDS = {
    "model_path", "training_hours", "training_projects",
    "sample_rate", "reference_embedding", "verification_threshold",
    "training_status",
}


def ensure_voice_profiles_table(conn: sqlite3.Connection) -> None:
    """Ensure voice_profiles table exists, creating if needed."""
    try:
        conn.execute("SELECT 1 FROM voice_profiles LIMIT 1")
    except sqlite3.OperationalError:
        conn.executescript(_VOICE_PROFILES_DDL)
        logger.info("Created voice_profiles table (migration).")


def create_voice_profile(
    db_path: str | Path, name: str, model_path: str, sample_rate: int = 24000,
) -> str:
    """Create a new voice profile. Returns the generated profile_id."""
    profile_id = f"vp_{secrets.token_hex(6)}"
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        ensure_voice_profiles_table(conn)
        execute(
            conn,
            "INSERT INTO voice_profiles (profile_id, name, model_path, sample_rate) "
            "VALUES (?, ?, ?, ?)",
            (profile_id, name, model_path, sample_rate),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("Created voice profile: %s (%s)", name, profile_id)
    return profile_id


def get_voice_profile(db_path: str | Path, name: str) -> dict[str, object] | None:
    """Retrieve a voice profile by name. Returns None if not found."""
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        ensure_voice_profiles_table(conn)
        return fetch_one(conn, "SELECT * FROM voice_profiles WHERE name = ?", (name,))
    finally:
        conn.close()


def list_voice_profiles(db_path: str | Path) -> list[dict[str, object]]:
    """List all voice profiles ordered by creation time."""
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        ensure_voice_profiles_table(conn)
        return fetch_all(conn, "SELECT * FROM voice_profiles ORDER BY created_at DESC")
    finally:
        conn.close()


def update_voice_profile(db_path: str | Path, name: str, **kwargs: object) -> None:
    """Update fields on an existing voice profile.

    Raises:
        ValueError: If profile not found or no valid fields provided.
    """
    updates = {k: v for k, v in kwargs.items() if k in _ALLOWED_UPDATE_FIELDS}
    if not updates:
        raise ValueError(f"No valid fields to update. Allowed: {sorted(_ALLOWED_UPDATE_FIELDS)}")

    set_clause = ", ".join(f"{k} = ?" for k in updates) + ", updated_at = datetime('now')"
    values = list(updates.values()) + [name]

    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        ensure_voice_profiles_table(conn)
        affected = execute(
            conn,
            f"UPDATE voice_profiles SET {set_clause} WHERE name = ?",
            tuple(values),
        )
        if affected == 0:
            raise ValueError(f"Voice profile not found: {name}")
        conn.commit()
    finally:
        conn.close()
    logger.info("Updated voice profile %s: %s", name, list(updates.keys()))


def delete_voice_profile(db_path: str | Path, name: str) -> None:
    """Delete a voice profile by name. Raises ValueError if not found."""
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        ensure_voice_profiles_table(conn)
        affected = execute(
            conn, "DELETE FROM voice_profiles WHERE name = ?", (name,),
        )
        if affected == 0:
            raise ValueError(f"Voice profile not found: {name}")
        conn.commit()
    finally:
        conn.close()
    logger.info("Deleted voice profile: %s", name)
