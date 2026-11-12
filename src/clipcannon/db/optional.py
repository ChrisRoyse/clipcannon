"""Narrow tolerance for optional analysis tables (#68).

Several read paths consult tables written by optional pipeline stages. A
project where that stage never ran has no such table (or an older schema
without the column); that absence is a fact about the project and may be
skipped. Every other database error (locked, corrupt, malformed SQL, I/O) is a
failure and must propagate, never be read as "no data".
"""

from __future__ import annotations

import sqlite3

_ABSENT = ("no such table", "no such column")


def require_missing_table(exc: BaseException) -> None:
    """Return if ``exc`` only says an optional table/column is absent; else re-raise it."""
    if isinstance(exc, sqlite3.OperationalError) and any(m in str(exc) for m in _ABSENT):
        return
    raise exc
