"""Core table and index DDL for ClipCannon project databases."""

from __future__ import annotations

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
