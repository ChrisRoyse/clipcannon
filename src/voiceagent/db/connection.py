"""Database connection factory."""
import logging
import sqlite3
from pathlib import Path

from voiceagent.errors import DatabaseError

logger = logging.getLogger(__name__)


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode, FK enforcement, and Row factory.

    Args:
        db_path: Path to SQLite database file. Parent dirs created automatically.

    Returns:
        sqlite3.Connection configured for the voice agent.

    Raises:
        DatabaseError: If connection fails.
    """
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        raise DatabaseError(f"Failed to connect to {path}: {e}") from e
