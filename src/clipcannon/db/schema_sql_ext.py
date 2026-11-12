"""Vector-table and phase 2-4 migration DDL for project databases."""

from __future__ import annotations

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
    parent_edit_id TEXT,
    branch_name TEXT DEFAULT 'main',
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

-- EDIT VERSIONS (version history for iterative editing)
CREATE TABLE IF NOT EXISTS edit_versions (
    version_id TEXT PRIMARY KEY,
    edit_id TEXT NOT NULL,
    parent_version_id TEXT,
    version_number INTEGER NOT NULL,
    edl_json TEXT NOT NULL,
    change_description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (edit_id) REFERENCES edits(edit_id)
);

-- SEGMENT CACHE (partial re-rendering)
CREATE TABLE IF NOT EXISTS segment_cache (
    cache_hash TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    segment_spec_json TEXT NOT NULL,
    file_size_bytes INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT NOT NULL DEFAULT (datetime('now')),
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
CREATE INDEX IF NOT EXISTS idx_edit_versions_edit ON edit_versions(edit_id, version_number);
CREATE INDEX IF NOT EXISTS idx_segment_cache_project ON segment_cache(project_id);
"""

# ============================================================
# PHASE 3 TABLE DEFINITIONS (Schema Version 3)
# ============================================================
_PHASE3_TABLES_SQL = """
-- VOICE PROFILES (voice cloning / AI avatar)
CREATE TABLE IF NOT EXISTS voice_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    model_path TEXT NOT NULL,
    training_hours REAL DEFAULT 0,
    training_projects TEXT DEFAULT '[]',
    sample_rate INTEGER DEFAULT 24000,
    reference_embedding BLOB,
    verification_threshold REAL DEFAULT 0.80,
    training_status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_PHASE3_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_voice_profiles_name ON voice_profiles(name);
"""

# ============================================================
# PHASE 4 TABLE DEFINITIONS (Schema Version 4 -- MouthMemory)
# ============================================================
_PHASE4_TABLES_SQL = """
-- MOUTH FRAMES (MouthMemory lip-sync retrieval atlas)
CREATE TABLE IF NOT EXISTS mouth_frames (
    frame_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    face_crop_path TEXT,
    mouth_crop_path TEXT,
    landmarks_json TEXT,
    head_yaw REAL DEFAULT 0,
    head_pitch REAL DEFAULT 0,
    head_roll REAL DEFAULT 0,
    viseme TEXT DEFAULT 'SIL',
    phoneme TEXT DEFAULT 'SIL',
    word TEXT DEFAULT '',
    word_position TEXT DEFAULT '',
    prev_viseme TEXT DEFAULT 'SIL',
    next_viseme TEXT DEFAULT 'SIL',
    mouth_openness REAL DEFAULT 0,
    mouth_width REAL DEFAULT 0.5,
    energy REAL DEFAULT 0,
    f0 REAL DEFAULT 0,
    emotion_label TEXT DEFAULT 'neutral',
    speaker_id INTEGER,
    quality_score REAL DEFAULT 0.5,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);
"""

_PHASE4_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_mouth_viseme
    ON mouth_frames(project_id, viseme, quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_mouth_time
    ON mouth_frames(project_id, timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_mouth_speaker
    ON mouth_frames(project_id, speaker_id, viseme);
"""
