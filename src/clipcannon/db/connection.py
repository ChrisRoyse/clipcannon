"""SQLite connection manager for ClipCannon.

Every connection is configured with WAL journal mode, performance pragmas,
and optionally loads the sqlite-vec extension for vector search.

Usage:
    conn = get_connection("/path/to/analysis.db")
    with conn:
        conn.execute("INSERT INTO ...")
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from clipcannon.exceptions import DatabaseError

logger = logging.getLogger(__name__)

# Pragmas applied to every connection per PRD Section 2.1
_PRAGMAS: list[str] = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA cache_size=-64000",
    "PRAGMA foreign_keys=ON",
    "PRAGMA temp_store=MEMORY",
]


def _load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """Attempt to load the sqlite-vec extension.

    Args:
        conn: SQLite connection to load the extension into.

    Returns:
        True if the extension was loaded successfully, False otherwise.

    Raises:
        DatabaseError: If the extension file exists but fails to load.
    """
    try:
        import sqlite_vec  # type: ignore[import-untyped]

        sqlite_vec.load(conn)
        logger.debug("sqlite-vec extension loaded successfully.")
        return True
    except ImportError:
        logger.warning(
            "sqlite-vec Python package not installed. "
            "Vector search features will be unavailable. "
            "Install with: pip install sqlite-vec"
        )
        return False
    except Exception as exc:
        raise DatabaseError(
            f"sqlite-vec extension failed to load: {exc}. "
            "Ensure sqlite-vec is installed correctly: pip install sqlite-vec",
            details={"error": str(exc)},
        ) from exc


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Apply performance pragmas to a connection.

    Args:
        conn: SQLite connection to configure.
    """
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    logger.debug("Applied %d pragmas to connection.", len(_PRAGMAS))


def _dict_row_factory(cursor: sqlite3.Cursor, row: tuple[object, ...]) -> dict[str, object]:
    """Row factory that returns rows as dictionaries.

    Args:
        cursor: The cursor that produced the row.
        row: Raw row tuple.

    Returns:
        Dictionary mapping column names to values.
    """
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row, strict=False))


def get_connection(
    db_path: str | Path,
    enable_vec: bool = True,
    dict_rows: bool = True,
) -> sqlite3.Connection:
    """Create and configure a SQLite connection.

    Sets WAL journal mode, performance pragmas, and optionally loads
    the sqlite-vec extension for vector search.

    Args:
        db_path: Path to the SQLite database file.
        enable_vec: Whether to load the sqlite-vec extension.
        dict_rows: Whether to use dict row factory for results.

    Returns:
        Configured sqlite3.Connection.

    Raises:
        DatabaseError: If the connection cannot be established.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(path))
    except sqlite3.Error as exc:
        raise DatabaseError(
            f"Failed to connect to database at {path}: {exc}",
            details={"path": str(path)},
        ) from exc

    if dict_rows:
        conn.row_factory = _dict_row_factory  # type: ignore[assignment]

    # Enable extension loading before loading sqlite-vec
    try:
        conn.enable_load_extension(True)
    except sqlite3.OperationalError:
        logger.debug("Extension loading not supported in this SQLite build.")

    _apply_pragmas(conn)

    if enable_vec:
        _load_sqlite_vec(conn)

    logger.info("Connected to database: %s", path)
    return conn
