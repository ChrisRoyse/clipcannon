"""Query helpers for ClipCannon project databases.

Provides parameterized query execution, batch inserts, and transaction
management to prevent SQL injection and simplify database operations.

All query functions accept a sqlite3.Connection and return properly
typed results using the dict row factory configured by get_connection().
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING

from clipcannon.exceptions import DatabaseError

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


def fetch_one(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[object, ...] | dict[str, object] | None = None,
) -> dict[str, object] | None:
    """Execute a query and return the first row.

    Args:
        conn: SQLite connection.
        sql: Parameterized SQL query string.
        params: Query parameters (tuple for ? placeholders, dict for :name).

    Returns:
        First row as a dictionary, or None if no rows match.

    Raises:
        DatabaseError: If query execution fails.
    """
    try:
        cursor = conn.execute(sql, params or ())
        row = cursor.fetchone()
        return row  # type: ignore[return-value]
    except sqlite3.Error as exc:
        raise DatabaseError(
            f"Query failed: {exc}",
            details={"sql": sql[:200], "error": str(exc)},
        ) from exc


def fetch_all(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[object, ...] | dict[str, object] | None = None,
) -> list[dict[str, object]]:
    """Execute a query and return all rows.

    Args:
        conn: SQLite connection.
        sql: Parameterized SQL query string.
        params: Query parameters.

    Returns:
        List of rows as dictionaries.

    Raises:
        DatabaseError: If query execution fails.
    """
    try:
        cursor = conn.execute(sql, params or ())
        return cursor.fetchall()  # type: ignore[return-value]
    except sqlite3.Error as exc:
        raise DatabaseError(
            f"Query failed: {exc}",
            details={"sql": sql[:200], "error": str(exc)},
        ) from exc


def execute(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[object, ...] | dict[str, object] | None = None,
) -> int:
    """Execute a statement and return the number of affected rows.

    Args:
        conn: SQLite connection.
        sql: Parameterized SQL statement.
        params: Statement parameters.

    Returns:
        Number of rows affected.

    Raises:
        DatabaseError: If execution fails.
    """
    try:
        cursor = conn.execute(sql, params or ())
        return cursor.rowcount
    except sqlite3.Error as exc:
        raise DatabaseError(
            f"Execute failed: {exc}",
            details={"sql": sql[:200], "error": str(exc)},
        ) from exc


def execute_returning_id(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[object, ...] | dict[str, object] | None = None,
) -> int:
    """Execute an INSERT and return the last inserted row ID.

    Args:
        conn: SQLite connection.
        sql: Parameterized INSERT statement.
        params: Statement parameters.

    Returns:
        The lastrowid of the inserted row.

    Raises:
        DatabaseError: If execution fails.
    """
    try:
        cursor = conn.execute(sql, params or ())
        if cursor.lastrowid is None:
            raise DatabaseError(
                "INSERT did not return a row ID",
                details={"sql": sql[:200]},
            )
        return cursor.lastrowid
    except sqlite3.Error as exc:
        raise DatabaseError(
            f"Execute failed: {exc}",
            details={"sql": sql[:200], "error": str(exc)},
        ) from exc


def batch_insert(
    conn: sqlite3.Connection,
    table: str,
    columns: list[str],
    rows: list[tuple[object, ...]],
    chunk_size: int = 500,
) -> int:
    """Insert multiple rows in batches using parameterized queries.

    Args:
        conn: SQLite connection.
        table: Target table name.
        columns: List of column names.
        rows: List of row tuples matching the column order.
        chunk_size: Number of rows per batch (default 500).

    Returns:
        Total number of rows inserted.

    Raises:
        DatabaseError: If any batch insert fails.
    """
    if not rows:
        return 0

    col_str = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))
    sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})"  # noqa: S608

    total_inserted = 0

    try:
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start : start + chunk_size]
            conn.executemany(sql, chunk)
            total_inserted += len(chunk)

        logger.debug(
            "Batch inserted %d rows into %s (%d chunks)",
            total_inserted,
            table,
            (len(rows) + chunk_size - 1) // chunk_size,
        )
    except sqlite3.Error as exc:
        raise DatabaseError(
            f"Batch insert into {table} failed: {exc}",
            details={"table": table, "rows_attempted": len(rows), "error": str(exc)},
        ) from exc

    return total_inserted


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for explicit transaction boundaries.

    Commits on success, rolls back on exception. Use this when you need
    to group multiple operations into a single atomic unit.

    Args:
        conn: SQLite connection.

    Yields:
        The connection within a BEGIN/COMMIT block.

    Raises:
        DatabaseError: If the transaction fails and cannot be rolled back.
    """
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
            logger.debug("Transaction rolled back.")
        except sqlite3.Error as rollback_exc:
            logger.error("Rollback failed: %s", rollback_exc)

        if isinstance(exc, DatabaseError):
            raise
        raise DatabaseError(
            f"Transaction failed: {exc}",
            details={"error": str(exc)},
        ) from exc


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check whether a table exists in the database.

    Args:
        conn: SQLite connection.
        table_name: Name of the table to check.

    Returns:
        True if the table exists, False otherwise.
    """
    result = fetch_one(
        conn,
        "SELECT count(*) as cnt FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    if result is None:
        return False
    count = result.get("cnt", 0) if isinstance(result, dict) else 0
    return bool(count)


def count_rows(
    conn: sqlite3.Connection, table: str, where: str = "", params: tuple[object, ...] = ()
) -> int:
    """Count rows in a table with optional WHERE clause.

    Args:
        conn: SQLite connection.
        table: Table name.
        where: Optional WHERE clause (without the WHERE keyword).
        params: Parameters for the WHERE clause.

    Returns:
        Number of matching rows.
    """
    sql = f"SELECT count(*) as cnt FROM {table}"  # noqa: S608
    if where:
        sql += f" WHERE {where}"

    result = fetch_one(conn, sql, params)
    if result is None:
        return 0
    return int(result.get("cnt", 0)) if isinstance(result, dict) else 0
