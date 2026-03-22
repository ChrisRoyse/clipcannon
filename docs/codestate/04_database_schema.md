# Database Schema and Connection Management

Current state of the ClipCannon database layer as implemented in
`src/clipcannon/db/`. Every ClipCannon project gets its own SQLite database
at `~/.clipcannon/projects/{project_id}/analysis.db`.

**Source files covered:**

- `src/clipcannon/db/connection.py` -- connection factory, pragmas, sqlite-vec loading
- `src/clipcannon/db/schema.py` -- table DDL, vector tables, indexes, project init, Phase 2 migration

---

## 1. Connection Management

`get_connection(db_path, enable_vec=True, dict_rows=True)` is the single
entry point for opening a database. It creates parent directories if missing,
opens the connection, optionally sets a dict row factory, enables extension
loading, applies pragmas, and optionally loads sqlite-vec.

### 1.1 Pragmas

Every connection executes these five pragmas in order:

| Pragma | Value | Purpose |
|--------|-------|---------|
| `journal_mode` | `WAL` | Write-Ahead Logging for concurrent reads during writes |
| `synchronous` | `NORMAL` | Reduced fsync frequency (safe with WAL) |
| `cache_size` | `-64000` | 64 MB page cache (negative = KiB) |
| `foreign_keys` | `ON` | Enforce foreign key constraints |
| `temp_store` | `MEMORY` | Temporary tables and indexes stored in RAM |

### 1.2 sqlite-vec Extension

When `enable_vec=True`, the connection attempts to load `sqlite_vec` via
`sqlite_vec.load(conn)`. Three outcomes are possible:

1. **Loaded** -- the `sqlite-vec` Python package is installed and the
   extension loads. Vector virtual tables are available.
2. **ImportError** -- the package is not installed. A warning is logged.
   Vector search features are unavailable but the connection is usable.
3. **Other exception** -- the package exists but loading fails. A
   `DatabaseError` is raised.

### 1.3 Row Factory

When `dict_rows=True` (the default), a custom `_dict_row_factory` is set.
It reads `cursor.description` and returns every row as a `dict[str, object]`
mapping column names to values.

---

## 2. Schema Version Tracking

The `schema_version` table records which schema version is applied.

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

The current schema version constant is **`SCHEMA_VERSION = 2`** (upgraded from 1 by Phase 2 migration).

`create_project_db` writes version 1 via `INSERT OR REPLACE` after core
tables are created. `migrate_to_v2()` upgrades to version 2 by adding
Phase 2 tables. `get_schema_version(db_path)` reads it back
with `SELECT MAX(version) FROM schema_version`.

---

## 3. Core Tables

There are 26 core tables (including `schema_version` and `provenance`),
organized below by domain.

### 3.1 Project Metadata

#### `project`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `project_id` | TEXT | PRIMARY KEY | Unique project identifier |
| `name` | TEXT | NOT NULL | Human-readable project name |
| `source_path` | TEXT | NOT NULL | Path to the original source video |
| `source_sha256` | TEXT | NOT NULL | SHA-256 hash of the source file |
| `source_cfr_path` | TEXT | | Path to the constant-frame-rate normalized copy |
| `duration_ms` | INTEGER | NOT NULL | Source video duration in milliseconds |
| `resolution` | TEXT | NOT NULL | Resolution string (e.g., "1920x1080") |
| `fps` | REAL | NOT NULL | Frames per second |
| `codec` | TEXT | NOT NULL | Video codec (e.g., "h264") |
| `audio_codec` | TEXT | | Audio codec (e.g., "aac") |
| `audio_channels` | INTEGER | | Number of audio channels |
| `file_size_bytes` | INTEGER | | Source file size in bytes |
| `vfr_detected` | BOOLEAN | DEFAULT FALSE | Whether variable frame rate was detected |
| `vfr_normalized` | BOOLEAN | DEFAULT FALSE | Whether VFR was normalized to CFR |
| `status` | TEXT | NOT NULL DEFAULT 'created' | Project status |
| `created_at` | TEXT | NOT NULL DEFAULT datetime('now') | Creation timestamp |
| `updated_at` | TEXT | NOT NULL DEFAULT datetime('now') | Last update timestamp |

### 3.2 Transcript Tables

#### `transcript_segments`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `segment_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `start_ms` | INTEGER | NOT NULL | Segment start time in ms |
| `end_ms` | INTEGER | NOT NULL | Segment end time in ms |
| `text` | TEXT | NOT NULL | Transcript text for this segment |
| `speaker_id` | INTEGER | FK -> speakers | Assigned speaker, if diarized |
| `language` | TEXT | DEFAULT 'en' | Detected language code |
| `word_count` | INTEGER | | Number of words in the segment |

#### `transcript_words`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `word_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `segment_id` | INTEGER | NOT NULL, FK -> transcript_segments | Parent segment |
| `word` | TEXT | NOT NULL | The word |
| `start_ms` | INTEGER | NOT NULL | Word start time in ms |
| `end_ms` | INTEGER | NOT NULL | Word end time in ms |
| `confidence` | REAL | | Recognition confidence (0.0-1.0) |
| `speaker_id` | INTEGER | | Speaker who said this word |

### 3.3 Visual Analysis Tables

#### `scenes`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `scene_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `start_ms` | INTEGER | NOT NULL | Scene start time in ms |
| `end_ms` | INTEGER | NOT NULL | Scene end time in ms |
| `key_frame_path` | TEXT | NOT NULL | Path to the representative key frame |
| `key_frame_timestamp_ms` | INTEGER | NOT NULL | Timestamp of the key frame |
| `visual_similarity_avg` | REAL | | Average visual similarity within the scene |
| `dominant_colors` | TEXT | | JSON-encoded dominant color data |
| `face_detected` | BOOLEAN | DEFAULT FALSE | Whether a face was detected |
| `face_position_x` | REAL | | Horizontal face position (normalized) |
| `face_position_y` | REAL | | Vertical face position (normalized) |
| `shot_type` | TEXT | | Shot type classification |
| `shot_type_confidence` | REAL | | Confidence of shot type classification |
| `crop_recommendation` | TEXT | | Suggested crop region |
| `quality_avg` | REAL | | Average quality score |
| `quality_min` | REAL | | Minimum quality score in the scene |
| `quality_classification` | TEXT | | Quality classification label |
| `quality_issues` | TEXT | | Detected quality issues (JSON) |

#### `on_screen_text`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `start_ms` | INTEGER | NOT NULL | Text appearance start time |
| `end_ms` | INTEGER | NOT NULL | Text appearance end time |
| `texts` | TEXT | NOT NULL | Detected text content |
| `type` | TEXT | | Text type classification |
| `change_from_previous` | BOOLEAN | | Whether this differs from prior text |

#### `text_change_events`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `timestamp_ms` | INTEGER | NOT NULL | Timestamp of the text change |
| `type` | TEXT | | Type of change |
| `new_title` | TEXT | | New text content after change |

#### `storyboard_grids`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `grid_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `grid_number` | INTEGER | NOT NULL | Sequential grid number |
| `grid_path` | TEXT | NOT NULL | Path to the grid image file |
| `cell_timestamps_ms` | TEXT | NOT NULL | JSON array of cell timestamps |
| `cell_metadata` | TEXT | | JSON metadata for each cell |

### 3.4 Audio Analysis Tables

#### `speakers`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `speaker_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `label` | TEXT | NOT NULL | Speaker label (e.g., "Speaker 1") |
| `total_speaking_ms` | INTEGER | | Total speaking duration in ms |
| `speaking_pct` | REAL | | Percentage of total audio |

#### `emotion_curve`, `reactions`, `silence_gaps`, `acoustic`, `music_sections`, `beats`, `beat_sections`

*(Unchanged from Phase 1 -- see previous schema version for full column details)*

### 3.5 Derived / Scoring Tables

#### `topics`, `highlights`, `pacing`

*(Unchanged from Phase 1)*

### 3.6 Content Safety Tables

#### `profanity_events`, `content_safety`

*(Unchanged from Phase 1)*

### 3.7 Pipeline Tracking Tables

#### `stream_status`, `provenance`

*(Unchanged from Phase 1)*

### 3.8 Phase 2: Editing Tables

#### `edits`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `edit_id` | TEXT | PRIMARY KEY | Unique edit identifier |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `name` | TEXT | NOT NULL | Human-readable edit name |
| `status` | TEXT | NOT NULL DEFAULT 'draft' | Edit status (draft/rendering/rendered/approved/rejected/failed) |
| `target_platform` | TEXT | NOT NULL | Target platform (tiktok, instagram_reels, etc.) |
| `target_profile` | TEXT | | Render profile name |
| `edl_json` | TEXT | NOT NULL | Full EDL serialized as JSON |
| `captions_enabled` | BOOLEAN | DEFAULT TRUE | Whether captions are enabled |
| `crop_mode` | TEXT | DEFAULT 'auto' | Crop mode (auto/manual/none) |
| `total_duration_ms` | INTEGER | | Computed total output duration |
| `segment_count` | INTEGER | | Number of segments in the edit |
| `thumbnail_timestamp_ms` | INTEGER | | Thumbnail extraction timestamp |
| `render_id` | TEXT | | FK to renders table |
| `created_at` | TEXT | NOT NULL DEFAULT datetime('now') | Creation timestamp |
| `updated_at` | TEXT | NOT NULL DEFAULT datetime('now') | Last update timestamp |

#### `edit_segments`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `edit_id` | TEXT | NOT NULL, FK -> edits | Owning edit |
| `segment_order` | INTEGER | NOT NULL | Segment position in timeline |
| `source_start_ms` | INTEGER | NOT NULL | Source start time in ms |
| `source_end_ms` | INTEGER | NOT NULL | Source end time in ms |
| `speed` | REAL | NOT NULL DEFAULT 1.0 | Playback speed (0.25-4.0) |
| `transition_in_type` | TEXT | | Incoming transition type |
| `transition_in_duration_ms` | INTEGER | | Incoming transition duration |
| `transition_out_type` | TEXT | | Outgoing transition type |
| `transition_out_duration_ms` | INTEGER | | Outgoing transition duration |

### 3.9 Phase 2: Render Tables

#### `renders`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `render_id` | TEXT | PRIMARY KEY | Unique render identifier |
| `edit_id` | TEXT | NOT NULL, FK -> edits | Source edit |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `status` | TEXT | NOT NULL DEFAULT 'pending' | Render status (pending/rendering/rendered/failed) |
| `profile` | TEXT | | Encoding profile used |
| `output_path` | TEXT | | Path to rendered video file |
| `output_sha256` | TEXT | | SHA-256 of rendered file |
| `file_size_bytes` | INTEGER | | Rendered file size |
| `duration_ms` | INTEGER | | Output video duration |
| `resolution_width` | INTEGER | | Output width in pixels |
| `resolution_height` | INTEGER | | Output height in pixels |
| `codec` | TEXT | | Video codec used |
| `bitrate_kbps` | INTEGER | | Video bitrate |
| `thumbnail_path` | TEXT | | Path to thumbnail image |
| `thumbnail_timestamp_ms` | INTEGER | | Thumbnail timestamp |
| `render_duration_ms` | INTEGER | | Render wall-clock time |
| `render_job_id` | TEXT | | External render job ID |
| `error_message` | TEXT | | Error description if failed |
| `started_at` | TEXT | | Render start timestamp |
| `completed_at` | TEXT | | Render completion timestamp |
| `created_at` | TEXT | NOT NULL DEFAULT datetime('now') | Creation timestamp |

### 3.10 Phase 2: Audio Assets Table

#### `audio_assets`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `asset_id` | TEXT | PRIMARY KEY | Unique asset identifier |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `edit_id` | TEXT | FK -> edits | Associated edit (nullable) |
| `asset_type` | TEXT | NOT NULL | Asset type (music/sfx/voiceover) |
| `file_path` | TEXT | NOT NULL | Path to audio file |
| `duration_ms` | INTEGER | NOT NULL | Audio duration in ms |
| `sample_rate` | INTEGER | | Audio sample rate (Hz) |
| `model_used` | TEXT | | Model that generated the audio |
| `generation_params_json` | TEXT | | JSON-encoded generation parameters |
| `seed` | INTEGER | | Random seed for reproducibility |
| `volume_db` | REAL | DEFAULT 0 | Volume adjustment in dB |
| `created_at` | TEXT | NOT NULL DEFAULT datetime('now') | Creation timestamp |

---

## 4. Vector Tables (sqlite-vec)

Four virtual tables use the `vec0` module from the `sqlite-vec` extension.
*(Unchanged from Phase 1 -- `vec_frames` float[1152], `vec_semantic` float[768], `vec_emotion` float[1024], `vec_speakers` float[512])*

---

## 5. Indexes

Phase 1 indexes (9) plus Phase 2 additions:

| Index Name | Table | Columns | Notes |
|------------|-------|---------|-------|
| `idx_segments_time` | `transcript_segments` | `project_id, start_ms, end_ms` | Time-range queries on segments |
| `idx_words_time` | `transcript_words` | `start_ms, end_ms` | Time-range queries on words |
| `idx_words_segment` | `transcript_words` | `segment_id` | Join to parent segment |
| `idx_scenes_time` | `scenes` | `project_id, start_ms, end_ms` | Time-range queries on scenes |
| `idx_emotion_time` | `emotion_curve` | `project_id, start_ms` | Time-range queries on emotion |
| `idx_highlights_score` | `highlights` | `project_id, score DESC` | Top-N highlight retrieval |
| `idx_reactions_time` | `reactions` | `project_id, start_ms` | Time-range queries on reactions |
| `idx_provenance_project` | `provenance` | `project_id, timestamp_utc` | Provenance timeline queries |
| `idx_provenance_chain` | `provenance` | `project_id, operation` | Provenance chain lookups |
| `idx_edits_project` | `edits` | `project_id, status` | Phase 2: Edit listing by status |
| `idx_edit_segments_edit` | `edit_segments` | `edit_id, segment_order` | Phase 2: Ordered segment lookup |
| `idx_renders_edit` | `renders` | `edit_id` | Phase 2: Render lookup by edit |
| `idx_audio_assets_edit` | `audio_assets` | `edit_id` | Phase 2: Audio asset lookup |

---

## 6. Pipeline Streams

The `PIPELINE_STREAMS` constant defines the 16 stream names tracked in
`stream_status`:

```
source_separation, visual, ocr, quality, shot_type, transcription,
semantic, emotion, speaker, reactions, acoustic, beats, chronemic,
storyboards, profanity, highlights
```

---

## 7. Project Directory Structure

`init_project_directory(project_id)` creates the following tree under
`~/.clipcannon/projects/{project_id}/`:

```
{project_id}/
  source/        -- original and CFR-normalized source files
  stems/         -- separated audio stems (vocal, music, etc.)
  frames/        -- extracted key frames
  storyboards/   -- generated storyboard grid images
  edits/         -- Phase 2: edit working directories
  renders/       -- Phase 2: rendered output files
  analysis.db    -- the SQLite database described in this document
```

---

## 8. Query Helper Functions

*(Unchanged from Phase 1 -- `fetch_one`, `fetch_all`, `execute`, `execute_returning_id`, `batch_insert`, `table_exists`, `count_rows`, `transaction`)*

---

## 9. Schema Migration

### `migrate_to_v2(db_path)`

Handles upgrading existing Phase 1 databases to Phase 2 schema:

1. Opens a connection with `enable_vec=False`.
2. Checks current schema version via `get_schema_version()`.
3. If version is already >= 2, returns immediately (idempotent).
4. Creates four new tables: `edits`, `edit_segments`, `renders`, `audio_assets`.
5. Creates four new indexes: `idx_edits_project`, `idx_edit_segments_edit`, `idx_renders_edit`, `idx_audio_assets_edit`.
6. Updates `schema_version` to 2.
7. Commits and closes.

New projects created via `create_project_db` include all Phase 2 tables from the start.
