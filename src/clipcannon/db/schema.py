"""Database schema for ClipCannon project databases.

Defines all tables from Phase1_Architecture.md Section 2.2, including
core tables, vector tables (sqlite-vec), and indexes. Provides functions
to create a fresh project database and initialize the project directory
structure.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from clipcannon.db.connection import get_connection
from clipcannon.exceptions import DatabaseError

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SCHEMA_VERSION_2 = 2

# ============================================================
# CORE TABLE DEFINITIONS
# ============================================================
_CORE_TABLES_SQL = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- PROJECT METADATA
CREATE TABLE IF NOT EXISTS project (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_cfr_path TEXT,
    duration_ms INTEGER NOT NULL,
    resolution TEXT NOT NULL,
    fps REAL NOT NULL,
    codec TEXT NOT NULL,
    audio_codec TEXT,
    audio_channels INTEGER,
    file_size_bytes INTEGER,
    vfr_detected BOOLEAN DEFAULT FALSE,
    vfr_normalized BOOLEAN DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- TRANSCRIPT SEGMENTS (WhisperX forced-aligned)
CREATE TABLE IF NOT EXISTS transcript_segments (
    segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    text TEXT NOT NULL,
    speaker_id INTEGER,
    language TEXT DEFAULT 'en',
    word_count INTEGER,
    sentiment TEXT,
    sentiment_score REAL,
    FOREIGN KEY (project_id) REFERENCES project(project_id),
    FOREIGN KEY (speaker_id) REFERENCES speakers(speaker_id)
);

-- TRANSCRIPT WORDS
CREATE TABLE IF NOT EXISTS transcript_words (
    word_id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    confidence REAL,
    speaker_id INTEGER,
    FOREIGN KEY (segment_id) REFERENCES transcript_segments(segment_id)
);

-- SCENES (from SigLIP cosine similarity)
CREATE TABLE IF NOT EXISTS scenes (
    scene_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    key_frame_path TEXT NOT NULL,
    key_frame_timestamp_ms INTEGER NOT NULL,
    visual_similarity_avg REAL,
    dominant_colors TEXT,
    face_detected BOOLEAN DEFAULT FALSE,
    face_position_x REAL,
    face_position_y REAL,
    shot_type TEXT,
    shot_type_confidence REAL,
    crop_recommendation TEXT,
    quality_avg REAL,
    quality_min REAL,
    quality_classification TEXT,
    quality_issues TEXT,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- SPEAKERS (from WavLM clustering)
CREATE TABLE IF NOT EXISTS speakers (
    speaker_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    label TEXT NOT NULL,
    total_speaking_ms INTEGER,
    speaking_pct REAL,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- EMOTION CURVE (from Wav2Vec2 on vocal stem)
CREATE TABLE IF NOT EXISTS emotion_curve (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    arousal REAL NOT NULL,
    valence REAL NOT NULL,
    energy REAL NOT NULL,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- TOPICS (from Nomic Embed clustering)
CREATE TABLE IF NOT EXISTS topics (
    topic_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    label TEXT NOT NULL,
    keywords TEXT,
    coherence_score REAL,
    semantic_density REAL,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- HIGHLIGHTS (multi-signal scored)
CREATE TABLE IF NOT EXISTS highlights (
    highlight_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    type TEXT NOT NULL,
    score REAL NOT NULL,
    reason TEXT NOT NULL,
    emotion_score REAL,
    reaction_score REAL,
    semantic_score REAL,
    narrative_score REAL,
    visual_score REAL,
    quality_score REAL,
    speaker_score REAL,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- REACTIONS (from SenseVoice on vocal stem)
CREATE TABLE IF NOT EXISTS reactions (
    reaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    type TEXT NOT NULL,
    confidence REAL,
    duration_ms INTEGER,
    intensity TEXT,
    context_transcript TEXT,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- SILENCE GAPS (from acoustic analysis)
CREATE TABLE IF NOT EXISTS silence_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    type TEXT,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- ACOUSTIC FEATURES
CREATE TABLE IF NOT EXISTS acoustic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    avg_volume_db REAL,
    dynamic_range_db REAL,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- MUSIC SECTIONS
CREATE TABLE IF NOT EXISTS music_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    type TEXT,
    confidence REAL,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- BEATS (from Beat This! on music stem)
CREATE TABLE IF NOT EXISTS beats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    has_music BOOLEAN DEFAULT FALSE,
    source TEXT,
    tempo_bpm REAL,
    tempo_confidence REAL,
    beat_positions_ms TEXT,
    downbeat_positions_ms TEXT,
    beat_count INTEGER,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- BEAT SECTIONS
CREATE TABLE IF NOT EXISTS beat_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    tempo_bpm REAL,
    time_signature TEXT,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- ON-SCREEN TEXT (from PaddleOCR)
CREATE TABLE IF NOT EXISTS on_screen_text (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    texts TEXT NOT NULL,
    type TEXT,
    change_from_previous BOOLEAN,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- TEXT CHANGE EVENTS
CREATE TABLE IF NOT EXISTS text_change_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    type TEXT,
    new_title TEXT,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- PROFANITY EVENTS
CREATE TABLE IF NOT EXISTS profanity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    word TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    severity TEXT,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- CONTENT SAFETY
CREATE TABLE IF NOT EXISTS content_safety (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    profanity_count INTEGER DEFAULT 0,
    profanity_density REAL DEFAULT 0,
    content_rating TEXT DEFAULT 'unknown',
    nsfw_frame_count INTEGER DEFAULT 0,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- PACING / CHRONEMIC (derived)
CREATE TABLE IF NOT EXISTS pacing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    words_per_minute REAL,
    pause_ratio REAL,
    speaker_changes INTEGER,
    label TEXT,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- STORYBOARD GRIDS
CREATE TABLE IF NOT EXISTS storyboard_grids (
    grid_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    grid_number INTEGER NOT NULL,
    grid_path TEXT NOT NULL,
    cell_timestamps_ms TEXT NOT NULL,
    cell_metadata TEXT,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- STREAM STATUS (pipeline completion tracking)
CREATE TABLE IF NOT EXISTS stream_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    stream_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    duration_ms INTEGER,
    FOREIGN KEY (project_id) REFERENCES project(project_id),
    UNIQUE(project_id, stream_name)
);

-- PROVENANCE HASH CHAIN
CREATE TABLE IF NOT EXISTS provenance (
    record_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    operation TEXT NOT NULL,
    stage TEXT NOT NULL,
    description TEXT,
    input_file_path TEXT,
    input_sha256 TEXT,
    input_size_bytes INTEGER,
    parent_record_id TEXT,
    output_file_path TEXT,
    output_sha256 TEXT,
    output_size_bytes INTEGER,
    output_record_count INTEGER,
    model_name TEXT,
    model_version TEXT,
    model_quantization TEXT,
    model_parameters TEXT,
    execution_duration_ms INTEGER,
    execution_gpu_device TEXT,
    execution_vram_peak_mb REAL,
    chain_hash TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES project(project_id),
    FOREIGN KEY (parent_record_id) REFERENCES provenance(record_id)
);
"""

# ============================================================
# INDEX DEFINITIONS
# ============================================================
_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_segments_time
    ON transcript_segments(project_id, start_ms, end_ms);

CREATE INDEX IF NOT EXISTS idx_words_time
    ON transcript_words(start_ms, end_ms);

CREATE INDEX IF NOT EXISTS idx_words_segment
    ON transcript_words(segment_id);

CREATE INDEX IF NOT EXISTS idx_scenes_time
    ON scenes(project_id, start_ms, end_ms);

CREATE INDEX IF NOT EXISTS idx_emotion_time
    ON emotion_curve(project_id, start_ms);

CREATE INDEX IF NOT EXISTS idx_highlights_score
    ON highlights(project_id, score DESC);

CREATE INDEX IF NOT EXISTS idx_reactions_time
    ON reactions(project_id, start_ms);

CREATE INDEX IF NOT EXISTS idx_provenance_project
    ON provenance(project_id, timestamp_utc);

CREATE INDEX IF NOT EXISTS idx_provenance_chain
    ON provenance(project_id, operation);
"""

# ============================================================
# VECTOR TABLE DEFINITIONS (sqlite-vec)
# ============================================================
_VECTOR_TABLES_SQL = [
    """CREATE VIRTUAL TABLE IF NOT EXISTS vec_frames USING vec0(
        frame_id INTEGER PRIMARY KEY,
        project_id TEXT,
        timestamp_ms INTEGER,
        frame_path TEXT,
        visual_embedding float[1152]
    )""",
    """CREATE VIRTUAL TABLE IF NOT EXISTS vec_semantic USING vec0(
        segment_id INTEGER PRIMARY KEY,
        project_id TEXT,
        timestamp_ms INTEGER,
        transcript_text TEXT,
        semantic_embedding float[768]
    )""",
    """CREATE VIRTUAL TABLE IF NOT EXISTS vec_emotion USING vec0(
        id INTEGER PRIMARY KEY,
        project_id TEXT,
        start_ms INTEGER,
        end_ms INTEGER,
        emotion_embedding float[1024]
    )""",
    """CREATE VIRTUAL TABLE IF NOT EXISTS vec_speakers USING vec0(
        id INTEGER PRIMARY KEY,
        project_id TEXT,
        segment_text TEXT,
        timestamp_ms INTEGER,
        speaker_id INTEGER,
        speaker_embedding float[512]
    )""",
]

# ============================================================
# PHASE 2 TABLE DEFINITIONS (Schema Version 2)
# ============================================================
_PHASE2_TABLES_SQL = """
-- EDITS (edit decision lists)
CREATE TABLE IF NOT EXISTS edits (
    edit_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    target_platform TEXT NOT NULL,
    target_profile TEXT NOT NULL,
    edl_json TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    total_duration_ms INTEGER,
    segment_count INTEGER,
    captions_enabled BOOLEAN DEFAULT TRUE,
    crop_mode TEXT DEFAULT 'auto',
    thumbnail_timestamp_ms INTEGER,
    metadata_title TEXT,
    metadata_description TEXT,
    metadata_hashtags TEXT,
    rejection_feedback TEXT,
    render_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- EDIT SEGMENTS (timeline entries within an edit)
CREATE TABLE IF NOT EXISTS edit_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edit_id TEXT NOT NULL,
    segment_order INTEGER NOT NULL,
    source_start_ms INTEGER NOT NULL,
    source_end_ms INTEGER NOT NULL,
    output_start_ms INTEGER NOT NULL,
    speed REAL DEFAULT 1.0,
    transition_in_type TEXT,
    transition_in_duration_ms INTEGER,
    transition_out_type TEXT,
    transition_out_duration_ms INTEGER,
    FOREIGN KEY (edit_id) REFERENCES edits(edit_id)
);

-- RENDERS (output render jobs)
CREATE TABLE IF NOT EXISTS renders (
    render_id TEXT PRIMARY KEY,
    edit_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    profile TEXT NOT NULL,
    output_path TEXT,
    output_sha256 TEXT,
    file_size_bytes INTEGER,
    duration_ms INTEGER,
    resolution TEXT,
    codec TEXT,
    thumbnail_path TEXT,
    render_duration_ms INTEGER,
    error_message TEXT,
    provenance_record_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    FOREIGN KEY (edit_id) REFERENCES edits(edit_id),
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- AUDIO ASSETS (generated music, SFX, etc.)
CREATE TABLE IF NOT EXISTS audio_assets (
    asset_id TEXT PRIMARY KEY,
    edit_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    sample_rate INTEGER DEFAULT 44100,
    model_used TEXT,
    generation_params TEXT,
    seed INTEGER,
    volume_db REAL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (edit_id) REFERENCES edits(edit_id),
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);
"""

_PHASE2_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_edits_project ON edits(project_id, status);
CREATE INDEX IF NOT EXISTS idx_edits_status ON edits(status);
CREATE INDEX IF NOT EXISTS idx_edit_segments ON edit_segments(edit_id, segment_order);
CREATE INDEX IF NOT EXISTS idx_renders_edit ON renders(edit_id);
CREATE INDEX IF NOT EXISTS idx_renders_status ON renders(status);
CREATE INDEX IF NOT EXISTS idx_audio_assets_edit ON audio_assets(edit_id);
"""

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

# Project subdirectories created for each project
PROJECT_SUBDIRS: list[str] = [
    "source",
    "stems",
    "frames",
    "storyboards",
    "edits",
    "renders",
]


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
        base_dir = Path.home() / ".clipcannon" / "projects"

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
        base_dir = Path.home() / ".clipcannon" / "projects"

    project_dir = base_dir / project_id

    for subdir in PROJECT_SUBDIRS:
        (project_dir / subdir).mkdir(parents=True, exist_ok=True)

    logger.info("Created project directory structure: %s", project_dir)

    # Create the database
    create_project_db(project_id, base_dir)

    return project_dir


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
