"""Database schema for ClipCannon project databases.

Defines all tables from Phase1_Architecture.md Section 2.2, including
core tables, vector tables (sqlite-vec), and indexes. Provides functions
to create a fresh project database and initialize the project directory
structure.
"""

# Implementation lives in the schema_* sibling modules; this facade keeps the
# original import path and its full name surface.

from __future__ import annotations

import logging
import sqlite3  # noqa: F401
from pathlib import Path  # noqa: F401

from clipcannon.db.connection import get_connection  # noqa: F401
from clipcannon.db.schema_migrations import (  # noqa: F401
    SCHEMA_VERSION,
    SCHEMA_VERSION_2,
    SCHEMA_VERSION_3,
    SCHEMA_VERSION_4,
    _create_core_tables,
    _create_vector_tables,
    _record_schema_version,
    get_schema_version,
    migrate_to_v2,
    migrate_to_v3,
    migrate_to_v4,
)
from clipcannon.db.schema_project import (  # noqa: F401
    PROJECT_SUBDIRS,
    create_project_db,
    init_project_directory,
)
from clipcannon.db.schema_sql_core import _CORE_TABLES_SQL, _INDEXES_SQL  # noqa: F401
from clipcannon.db.schema_sql_ext import (  # noqa: F401
    _PHASE2_INDEXES_SQL,
    _PHASE2_TABLES_SQL,
    _PHASE3_INDEXES_SQL,
    _PHASE3_TABLES_SQL,
    _PHASE4_INDEXES_SQL,
    _PHASE4_TABLES_SQL,
    _VECTOR_TABLES_SQL,
)
from clipcannon.exceptions import DatabaseError  # noqa: F401

logger = logging.getLogger(__name__)

# All stream names tracked by stream_status
PIPELINE_STREAMS: list[str] = [
    "source_separation",
    "visual",
    "ocr",
    "quality",
    "shot_type",
    "transcription",
    "semantic",
    "emotion",
    "speaker",
    "reactions",
    "acoustic",
    "beats",
    "chronemic",
    "storyboards",
    "profanity",
    "highlights",
]
