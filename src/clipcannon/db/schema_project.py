"""Project database creation and project directory initialisation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from clipcannon.config import projects_dir as _cfg_projects_dir
from clipcannon.db.connection import get_connection
from clipcannon.db.schema_migrations import (
    SCHEMA_VERSION,
    _create_core_tables,
    _create_vector_tables,
    _record_schema_version,
    migrate_to_v2,
    migrate_to_v3,
    migrate_to_v4,
    migrate_to_v5,
)
from clipcannon.exceptions import DatabaseError

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Project subdirectories created for each project
PROJECT_SUBDIRS: list[str] = [
    "source",
    "stems",
    "frames",
    "storyboards",
    "edits",
    "renders",
]


def create_project_db(project_id: str, base_dir: Path | None = None) -> Path:
    """Create a fresh project database with the full schema.

    Creates the analysis.db file at the standard project location
    with all core tables, indexes, and vector tables (if sqlite-vec
    is available).

    Args:
        project_id: Unique project identifier.
        base_dir: Override base directory (default: ~/.clipcannon/projects).

    Returns:
        Path to the created database file.

    Raises:
        DatabaseError: If schema creation fails.
    """
    if base_dir is None:
        base_dir = _cfg_projects_dir()

    project_dir = base_dir / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "analysis.db"

    conn = get_connection(db_path, enable_vec=True, dict_rows=False)

    try:
        _create_core_tables(conn)
        vec_created = _create_vector_tables(conn)
        _record_schema_version(conn, SCHEMA_VERSION)
        conn.commit()

        table_count = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()
        count = table_count[0] if table_count else 0

        logger.info(
            "Created project database: %s (%d tables, vectors=%s)",
            db_path,
            count,
            vec_created,
        )
    except DatabaseError:
        raise
    except Exception as exc:
        raise DatabaseError(
            f"Failed to create project database: {exc}",
            details={"project_id": project_id, "path": str(db_path)},
        ) from exc
    finally:
        conn.close()

    # Apply v2 migration (Phase 2 tables)
    migrate_to_v2(db_path)

    # Apply v3 migration (Phase 3 tables)
    migrate_to_v3(db_path)

    # Apply v4 migration (MouthMemory tables)
    migrate_to_v4(db_path)

    # Apply v5 migration (per-instrument quality and reaction columns)
    migrate_to_v5(db_path)

    return db_path


def init_project_directory(project_id: str, base_dir: Path | None = None) -> Path:
    """Initialize the full project directory structure.

    Creates the project directory with source/, stems/, frames/,
    and storyboards/ subdirectories, plus the analysis.db database.

    Args:
        project_id: Unique project identifier.
        base_dir: Override base directory (default: ~/.clipcannon/projects).

    Returns:
        Path to the project directory.

    Raises:
        DatabaseError: If database creation fails.
    """
    if base_dir is None:
        base_dir = _cfg_projects_dir()

    project_dir = base_dir / project_id

    for subdir in PROJECT_SUBDIRS:
        (project_dir / subdir).mkdir(parents=True, exist_ok=True)

    logger.info("Created project directory structure: %s", project_dir)

    # Create the database
    create_project_db(project_id, base_dir)

    return project_dir
