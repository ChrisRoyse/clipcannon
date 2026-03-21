"""Database management for ClipCannon.

Provides SQLite connection management with WAL mode, sqlite-vec
extension loading, schema creation, and query helpers.
"""

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, execute, fetch_all, fetch_one
from clipcannon.db.schema import create_project_db, init_project_directory

__all__ = [
    "batch_insert",
    "create_project_db",
    "execute",
    "fetch_all",
    "fetch_one",
    "get_connection",
    "init_project_directory",
]
