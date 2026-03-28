"""Voice agent database schema definitions.

Three tables: conversations, turns, metrics.
init_db() is idempotent -- safe to call multiple times.
"""
import logging
from pathlib import Path

from voiceagent.db.connection import get_connection
from voiceagent.errors import DatabaseError

logger = logging.getLogger(__name__)

CONVERSATIONS_DDL = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    voice_profile TEXT NOT NULL DEFAULT 'boris',
    turn_count INTEGER NOT NULL DEFAULT 0
);
"""

TURNS_DDL = """
CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    text TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    asr_ms REAL,
    llm_ttft_ms REAL,
    tts_ttfb_ms REAL,
    total_ms REAL
);
"""

METRICS_DDL = """
CREATE TABLE IF NOT EXISTS metrics (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    metadata TEXT
);
"""


def init_db(db_path: str | Path) -> None:
    """Create all tables if they do not exist. Idempotent.

    Args:
        db_path: Path to SQLite database file. Parent dirs created automatically.

    Raises:
        DatabaseError: If schema creation fails.
    """
    conn = get_connection(db_path)
    try:
        conn.executescript(CONVERSATIONS_DDL + TURNS_DDL + METRICS_DDL)
        conn.commit()
        logger.info("Database initialized at %s", db_path)
    except Exception as e:
        raise DatabaseError(f"Failed to initialize database at {db_path}: {e}") from e
    finally:
        conn.close()
