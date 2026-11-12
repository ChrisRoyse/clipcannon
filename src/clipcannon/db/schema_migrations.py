"""Schema versioning, table creation helpers and migrations."""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.schema_sql_core import _CORE_TABLES_SQL, _INDEXES_SQL
from clipcannon.db.schema_sql_ext import (
    _PHASE2_INDEXES_SQL,
    _PHASE2_TABLES_SQL,
    _PHASE3_INDEXES_SQL,
    _PHASE3_TABLES_SQL,
    _PHASE4_INDEXES_SQL,
    _PHASE4_TABLES_SQL,
    _VECTOR_TABLES_SQL,
)
from clipcannon.exceptions import DatabaseError

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SCHEMA_VERSION_2 = 2
SCHEMA_VERSION_3 = 3
SCHEMA_VERSION_4 = 4


def _create_core_tables(conn: sqlite3.Connection) -> None:
    """Create all core tables and indexes.

    Args:
        conn: SQLite connection.
    """
    conn.executescript(_CORE_TABLES_SQL)
    conn.executescript(_INDEXES_SQL)
    logger.debug("Created core tables and indexes.")


def _create_vector_tables(conn: sqlite3.Connection) -> bool:
    """Create sqlite-vec virtual tables.

    Args:
        conn: SQLite connection.

    Returns:
        True if vector tables were created, False if sqlite-vec
        is not available.
    """

    for sql in _VECTOR_TABLES_SQL:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as exc:
            error_msg = str(exc).lower()
            if "no such module" in error_msg:
                logger.warning(
                    "sqlite-vec extension not loaded. "
                    "Vector tables will not be created. "
                    "Vector search features will be unavailable."
                )
                return False
            raise DatabaseError(
                f"Failed to create vector table: {exc}",
                details={"sql": sql[:100], "error": str(exc)},
            ) from exc

    logger.debug("Created %d vector tables.", len(_VECTOR_TABLES_SQL))
    return True


def _record_schema_version(conn: sqlite3.Connection, version: int) -> None:
    """Record the schema version in the database.

    Args:
        conn: SQLite connection.
        version: Schema version number.
    """
    conn.execute(
        "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
        (version,),
    )
    logger.debug("Recorded schema version: %d", version)


def migrate_to_v2(db_path: str | Path) -> bool:
    """Migrate a project database from schema v1 to v2.

    Adds Phase 2 tables (edits, edit_segments, renders, audio_assets)
    and their indexes. This function is idempotent -- safe to call
    multiple times on the same database.

    Args:
        db_path: Path to the project database file.

    Returns:
        True if migration was applied, False if already at v2 or higher.

    Raises:
        DatabaseError: If the migration fails.
    """
    current_version = get_schema_version(db_path)

    if current_version is not None and current_version >= SCHEMA_VERSION_2:
        logger.debug(
            "Database already at schema version %d, skipping v2 migration.",
            current_version,
        )
        return False

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        conn.executescript(_PHASE2_TABLES_SQL)
        conn.executescript(_PHASE2_INDEXES_SQL)
        _record_schema_version(conn, SCHEMA_VERSION_2)
        conn.commit()
        logger.info("Migrated database to schema version %d: %s", SCHEMA_VERSION_2, db_path)
        return True
    except Exception as exc:
        raise DatabaseError(
            f"Failed to migrate database to schema v2: {exc}",
            details={"path": str(db_path), "error": str(exc)},
        ) from exc
    finally:
        conn.close()


def migrate_to_v3(db_path: str | Path) -> bool:
    """Migrate a project database to schema v3.

    Adds Phase 3 tables (voice_profiles) and their indexes.
    This function is idempotent -- safe to call multiple times.

    Args:
        db_path: Path to the project database file.

    Returns:
        True if migration was applied, False if already at v3 or higher.

    Raises:
        DatabaseError: If the migration fails.
    """
    current_version = get_schema_version(db_path)

    if current_version is not None and current_version >= SCHEMA_VERSION_3:
        logger.debug(
            "Database already at schema version %d, skipping v3 migration.",
            current_version,
        )
        return False

    # Ensure v2 is applied first
    if current_version is None or current_version < SCHEMA_VERSION_2:
        migrate_to_v2(db_path)

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        conn.executescript(_PHASE3_TABLES_SQL)
        conn.executescript(_PHASE3_INDEXES_SQL)
        _record_schema_version(conn, SCHEMA_VERSION_3)
        conn.commit()
        logger.info("Migrated database to schema version %d: %s", SCHEMA_VERSION_3, db_path)
        return True
    except Exception as exc:
        raise DatabaseError(
            f"Failed to migrate database to schema v3: {exc}",
            details={"path": str(db_path), "error": str(exc)},
        ) from exc
    finally:
        conn.close()


def migrate_to_v4(db_path: str | Path) -> bool:
    """Migrate a project database to schema v4.

    Adds Phase 4 tables (mouth_frames for MouthMemory lip-sync).
    This function is idempotent -- safe to call multiple times.

    Args:
        db_path: Path to the project database file.

    Returns:
        True if migration was applied, False if already at v4 or higher.

    Raises:
        DatabaseError: If the migration fails.
    """
    current_version = get_schema_version(db_path)

    if current_version is not None and current_version >= SCHEMA_VERSION_4:
        return False

    # Ensure v3 is applied first
    if current_version is None or current_version < SCHEMA_VERSION_3:
        migrate_to_v3(db_path)

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        conn.executescript(_PHASE4_TABLES_SQL)
        conn.executescript(_PHASE4_INDEXES_SQL)
        _record_schema_version(conn, SCHEMA_VERSION_4)
        conn.commit()
        logger.info("Migrated database to schema version %d: %s", SCHEMA_VERSION_4, db_path)
        return True
    except Exception as exc:
        raise DatabaseError(
            f"Failed to migrate database to schema v4: {exc}",
            details={"path": str(db_path), "error": str(exc)},
        ) from exc
    finally:
        conn.close()


def get_schema_version(db_path: str | Path) -> int | None:
    """Read the current schema version from a database.

    Args:
        db_path: Path to the database file.

    Returns:
        Schema version number, or None if not set.
    """
    try:
        conn = get_connection(db_path, enable_vec=False, dict_rows=False)
        result = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        conn.close()
        return result[0] if result and result[0] is not None else None
    except (sqlite3.OperationalError, DatabaseError):
        return None
