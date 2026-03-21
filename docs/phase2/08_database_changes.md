# Database Schema Changes (v2)

## 1. Overview
Phase 2 adds tables for edits, renders, and audio assets. Schema version bumps from 1 to 2.

## 2. New Tables

### edits
```sql
CREATE TABLE edits (
    edit_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',  -- draft, rendering, rendered, approved, rejected
    target_platform TEXT NOT NULL,
    target_profile TEXT NOT NULL,
    edl_json TEXT NOT NULL,  -- Full EDL as JSON blob
    source_sha256 TEXT NOT NULL,  -- Must match project source hash
    total_duration_ms INTEGER,
    segment_count INTEGER,
    captions_enabled BOOLEAN DEFAULT TRUE,
    crop_mode TEXT DEFAULT 'auto',
    thumbnail_timestamp_ms INTEGER,
    metadata_title TEXT,
    metadata_description TEXT,
    metadata_hashtags TEXT,  -- JSON array
    rejection_feedback TEXT,
    render_id TEXT,  -- FK to renders table
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

CREATE INDEX idx_edits_project ON edits(project_id, status);
CREATE INDEX idx_edits_status ON edits(status);
```

### edit_segments
```sql
CREATE TABLE edit_segments (
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

CREATE INDEX idx_edit_segments ON edit_segments(edit_id, segment_order);
```

### renders
```sql
CREATE TABLE renders (
    render_id TEXT PRIMARY KEY,
    edit_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, rendering, completed, failed
    profile TEXT NOT NULL,
    output_path TEXT,
    output_sha256 TEXT,
    file_size_bytes INTEGER,
    duration_ms INTEGER,
    resolution TEXT,
    codec TEXT,
    thumbnail_path TEXT,
    render_duration_ms INTEGER,  -- How long rendering took
    error_message TEXT,
    provenance_record_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    FOREIGN KEY (edit_id) REFERENCES edits(edit_id),
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

CREATE INDEX idx_renders_edit ON renders(edit_id);
CREATE INDEX idx_renders_status ON renders(status);
```

### audio_assets
```sql
CREATE TABLE audio_assets (
    asset_id TEXT PRIMARY KEY,
    edit_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    type TEXT NOT NULL,  -- music_ace_step, music_midi, sfx_whoosh, sfx_impact, etc.
    file_path TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    sample_rate INTEGER DEFAULT 44100,
    model_used TEXT,
    generation_params TEXT,  -- JSON
    seed INTEGER,
    volume_db REAL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (edit_id) REFERENCES edits(edit_id),
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

CREATE INDEX idx_audio_assets_edit ON audio_assets(edit_id);
```

## 3. Schema Migration
- Check current schema_version (1 = Phase 1)
- Run Phase 2 DDL if version < 2
- Insert schema_version = 2
- Backward compatible: Phase 1 projects work without Phase 2 tables being populated

## 4. Project Directory Changes
Phase 2 adds these directories under each project:
```
{project_id}/
    edits/
        {edit_id}/
            audio/          # Generated audio assets
            captions/       # Generated .ass files
            animations/     # Rendered animation frames (Phase 3)
    renders/
        {render_id}/
            output.mp4      # Sacred tier
            thumbnail.jpg   # Sacred tier
```
