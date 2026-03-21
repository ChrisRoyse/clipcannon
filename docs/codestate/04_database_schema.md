# Database Schema and Connection Management

Current state of the ClipCannon database layer as implemented in
`src/clipcannon/db/`. Every ClipCannon project gets its own SQLite database
at `~/.clipcannon/projects/{project_id}/analysis.db`.

**Source files covered:**

- `src/clipcannon/db/connection.py` -- connection factory, pragmas, sqlite-vec loading
- `src/clipcannon/db/schema.py` -- table DDL, vector tables, indexes, project init
- `src/clipcannon/db/queries.py` -- parameterized query helpers, transactions

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

The current schema version constant is **`SCHEMA_VERSION = 1`**.

`create_project_db` writes this version via `INSERT OR REPLACE` after all
tables and indexes are created. `get_schema_version(db_path)` reads it back
with `SELECT MAX(version) FROM schema_version`.

---

## 3. Core Tables

There are 22 core tables (including `schema_version` and `provenance`),
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

WhisperX forced-aligned transcript segments.

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

Word-level timestamps and confidence scores.

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

Scene boundaries detected from SigLIP cosine similarity.

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

On-screen text detected by PaddleOCR.

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

Events where on-screen text changes.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `timestamp_ms` | INTEGER | NOT NULL | Timestamp of the text change |
| `type` | TEXT | | Type of change |
| `new_title` | TEXT | | New text content after change |

#### `storyboard_grids`

Storyboard grid images composed from key frames.

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

Speaker identities from WavLM clustering.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `speaker_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `label` | TEXT | NOT NULL | Speaker label (e.g., "Speaker 1") |
| `total_speaking_ms` | INTEGER | | Total speaking duration in ms |
| `speaking_pct` | REAL | | Percentage of total audio |

#### `emotion_curve`

Emotion time series from Wav2Vec2 on the vocal stem.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `start_ms` | INTEGER | NOT NULL | Window start time |
| `end_ms` | INTEGER | NOT NULL | Window end time |
| `arousal` | REAL | NOT NULL | Arousal score |
| `valence` | REAL | NOT NULL | Valence score |
| `energy` | REAL | NOT NULL | Energy score |

#### `reactions`

Vocal reactions detected by SenseVoice on the vocal stem.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `reaction_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `start_ms` | INTEGER | NOT NULL | Reaction start time |
| `end_ms` | INTEGER | NOT NULL | Reaction end time |
| `type` | TEXT | NOT NULL | Reaction type (e.g., "laughter") |
| `confidence` | REAL | | Detection confidence |
| `duration_ms` | INTEGER | | Reaction duration |
| `intensity` | TEXT | | Intensity level |
| `context_transcript` | TEXT | | Surrounding transcript text |

#### `silence_gaps`

Silence gaps from acoustic analysis.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `start_ms` | INTEGER | NOT NULL | Gap start time |
| `end_ms` | INTEGER | NOT NULL | Gap end time |
| `duration_ms` | INTEGER | NOT NULL | Gap duration |
| `type` | TEXT | | Gap type classification |

#### `acoustic`

Global acoustic features for the project.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `avg_volume_db` | REAL | | Average volume in dB |
| `dynamic_range_db` | REAL | | Dynamic range in dB |

#### `music_sections`

Detected music sections.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `start_ms` | INTEGER | NOT NULL | Section start time |
| `end_ms` | INTEGER | NOT NULL | Section end time |
| `type` | TEXT | | Music section type |
| `confidence` | REAL | | Detection confidence |

#### `beats`

Beat analysis from "Beat This!" on the music stem.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `has_music` | BOOLEAN | DEFAULT FALSE | Whether music was detected |
| `source` | TEXT | | Beat detection source |
| `tempo_bpm` | REAL | | Detected tempo in BPM |
| `tempo_confidence` | REAL | | Confidence of tempo detection |
| `beat_positions_ms` | TEXT | | JSON array of beat timestamps |
| `downbeat_positions_ms` | TEXT | | JSON array of downbeat timestamps |
| `beat_count` | INTEGER | | Total number of beats detected |

#### `beat_sections`

Time-segmented beat analysis sections.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `start_ms` | INTEGER | NOT NULL | Section start time |
| `end_ms` | INTEGER | NOT NULL | Section end time |
| `tempo_bpm` | REAL | | Tempo for this section |
| `time_signature` | TEXT | | Time signature (e.g., "4/4") |

### 3.5 Derived / Scoring Tables

#### `topics`

Topic clusters from Nomic Embed clustering.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `topic_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `start_ms` | INTEGER | NOT NULL | Topic span start time |
| `end_ms` | INTEGER | NOT NULL | Topic span end time |
| `label` | TEXT | NOT NULL | Topic label |
| `keywords` | TEXT | | Associated keywords |
| `coherence_score` | REAL | | Topic coherence score |
| `semantic_density` | REAL | | Semantic density within the topic |

#### `highlights`

Multi-signal scored highlight candidates.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `highlight_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `start_ms` | INTEGER | NOT NULL | Highlight start time |
| `end_ms` | INTEGER | NOT NULL | Highlight end time |
| `type` | TEXT | NOT NULL | Highlight type |
| `score` | REAL | NOT NULL | Overall highlight score |
| `reason` | TEXT | NOT NULL | Human-readable reason for scoring |
| `emotion_score` | REAL | | Emotion signal contribution |
| `reaction_score` | REAL | | Reaction signal contribution |
| `semantic_score` | REAL | | Semantic signal contribution |
| `narrative_score` | REAL | | Narrative signal contribution |
| `visual_score` | REAL | | Visual signal contribution |
| `quality_score` | REAL | | Quality signal contribution |
| `speaker_score` | REAL | | Speaker signal contribution |

#### `pacing`

Pacing / chronemic analysis (derived from transcript and speaker data).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `start_ms` | INTEGER | NOT NULL | Window start time |
| `end_ms` | INTEGER | NOT NULL | Window end time |
| `words_per_minute` | REAL | | Speaking rate |
| `pause_ratio` | REAL | | Ratio of pause time to speech time |
| `speaker_changes` | INTEGER | | Number of speaker transitions in window |
| `label` | TEXT | | Pacing classification label |

### 3.6 Content Safety Tables

#### `profanity_events`

Individual profanity occurrences.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `word` | TEXT | NOT NULL | The profane word |
| `start_ms` | INTEGER | NOT NULL | Word start time |
| `end_ms` | INTEGER | NOT NULL | Word end time |
| `severity` | TEXT | | Severity classification |

#### `content_safety`

Project-level content safety summary.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `profanity_count` | INTEGER | DEFAULT 0 | Total profanity count |
| `profanity_density` | REAL | DEFAULT 0 | Profanity per minute |
| `content_rating` | TEXT | DEFAULT 'unknown' | Computed content rating |
| `nsfw_frame_count` | INTEGER | DEFAULT 0 | Number of NSFW frames detected |

### 3.7 Pipeline Tracking Tables

#### `stream_status`

Tracks completion state of each pipeline stream per project.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Auto-incrementing ID |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `stream_name` | TEXT | NOT NULL | Pipeline stream name |
| `status` | TEXT | NOT NULL DEFAULT 'pending' | Stream status |
| `error_message` | TEXT | | Error message if stream failed |
| `started_at` | TEXT | | ISO timestamp when stream started |
| `completed_at` | TEXT | | ISO timestamp when stream completed |
| `duration_ms` | INTEGER | | Stream execution duration |

Unique constraint: `UNIQUE(project_id, stream_name)`.

#### `provenance`

Hash-chained provenance records. Documented fully in
[05_provenance_system.md](05_provenance_system.md).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `record_id` | TEXT | PRIMARY KEY | Provenance record ID (e.g., "prov_001") |
| `project_id` | TEXT | NOT NULL, FK -> project | Owning project |
| `timestamp_utc` | TEXT | NOT NULL | ISO-8601 UTC timestamp |
| `operation` | TEXT | NOT NULL | Pipeline operation name |
| `stage` | TEXT | NOT NULL | Pipeline stage name |
| `description` | TEXT | | Human-readable description |
| `input_file_path` | TEXT | | Input file path |
| `input_sha256` | TEXT | | SHA-256 of the input |
| `input_size_bytes` | INTEGER | | Input size in bytes |
| `parent_record_id` | TEXT | FK -> provenance(record_id) | Parent provenance record |
| `output_file_path` | TEXT | | Output file path |
| `output_sha256` | TEXT | | SHA-256 of the output |
| `output_size_bytes` | INTEGER | | Output size in bytes |
| `output_record_count` | INTEGER | | Number of output records |
| `model_name` | TEXT | | ML model name |
| `model_version` | TEXT | | ML model version |
| `model_quantization` | TEXT | | Quantization level |
| `model_parameters` | TEXT | | JSON-encoded model parameters |
| `execution_duration_ms` | INTEGER | | Execution time in ms |
| `execution_gpu_device` | TEXT | | GPU device identifier |
| `execution_vram_peak_mb` | REAL | | Peak VRAM usage in MB |
| `chain_hash` | TEXT | NOT NULL | Tamper-evident chain hash |

---

## 4. Vector Tables (sqlite-vec)

Four virtual tables use the `vec0` module from the `sqlite-vec` extension.
Each stores a float embedding alongside metadata columns. Vector tables are
created only when the sqlite-vec extension loads successfully; if it is
unavailable, vector search features are silently disabled.

### `vec_frames` -- Visual Frame Embeddings (1152 dimensions)

| Column | Type | Description |
|--------|------|-------------|
| `frame_id` | INTEGER PRIMARY KEY | Frame identifier |
| `project_id` | TEXT | Owning project |
| `timestamp_ms` | INTEGER | Frame timestamp in ms |
| `frame_path` | TEXT | Path to the frame image |
| `visual_embedding` | float[1152] | SigLIP visual embedding |

### `vec_semantic` -- Semantic Transcript Embeddings (768 dimensions)

| Column | Type | Description |
|--------|------|-------------|
| `segment_id` | INTEGER PRIMARY KEY | Transcript segment identifier |
| `project_id` | TEXT | Owning project |
| `timestamp_ms` | INTEGER | Segment timestamp in ms |
| `transcript_text` | TEXT | Transcript text for the segment |
| `semantic_embedding` | float[768] | Nomic Embed semantic embedding |

### `vec_emotion` -- Emotion Embeddings (1024 dimensions)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Record identifier |
| `project_id` | TEXT | Owning project |
| `start_ms` | INTEGER | Window start time |
| `end_ms` | INTEGER | Window end time |
| `emotion_embedding` | float[1024] | Wav2Vec2 emotion embedding |

### `vec_speakers` -- Speaker Embeddings (512 dimensions)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Record identifier |
| `project_id` | TEXT | Owning project |
| `segment_text` | TEXT | Associated transcript text |
| `timestamp_ms` | INTEGER | Segment timestamp in ms |
| `speaker_id` | INTEGER | Speaker identifier |
| `speaker_embedding` | float[512] | WavLM speaker embedding |

---

## 5. Indexes

Nine indexes are created for query performance:

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
| `idx_provenance_chain` | `provenance` | `project_id, operation` | Provenance chain lookups by operation |

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
  analysis.db    -- the SQLite database described in this document
```

---

## 8. Query Helper Functions

`src/clipcannon/db/queries.py` provides six functions and one context
manager. All raise `DatabaseError` on failure.

### `fetch_one(conn, sql, params) -> dict | None`

Executes a parameterized query and returns the first row as a dictionary,
or `None` if no rows match.

### `fetch_all(conn, sql, params) -> list[dict]`

Executes a parameterized query and returns all rows as a list of
dictionaries.

### `execute(conn, sql, params) -> int`

Executes a parameterized statement (INSERT, UPDATE, DELETE) and returns
`cursor.rowcount`.

### `execute_returning_id(conn, sql, params) -> int`

Executes an INSERT and returns `cursor.lastrowid`. Raises `DatabaseError`
if `lastrowid` is `None`.

### `batch_insert(conn, table, columns, rows, chunk_size=500) -> int`

Inserts multiple rows using `executemany` in chunks of 500 (configurable).
Builds a parameterized `INSERT INTO {table} ({columns}) VALUES (?, ?, ...)`
statement. Returns the total number of rows inserted.

### `table_exists(conn, table_name) -> bool`

Checks `sqlite_master` for a table with the given name. Returns `True` or
`False`.

### `count_rows(conn, table, where="", params=()) -> int`

Runs `SELECT count(*) FROM {table}` with an optional `WHERE` clause.
Returns the integer count.

### `transaction(conn)` -- context manager

Wraps a block in explicit `BEGIN` / `COMMIT`. Rolls back on any exception.
If the rollback itself fails, the rollback error is logged and the original
exception is re-raised as a `DatabaseError`.

```python
from clipcannon.db.queries import transaction

with transaction(conn) as txn:
    txn.execute("INSERT INTO ...")
    txn.execute("UPDATE ...")
# auto-committed here, or rolled back on exception
```

---

## 9. Database Creation Flow

`create_project_db(project_id, base_dir=None)` orchestrates the full
creation sequence:

1. Resolves the database path: `{base_dir}/{project_id}/analysis.db`
   (defaults to `~/.clipcannon/projects/`).
2. Creates parent directories.
3. Opens a connection with `enable_vec=True, dict_rows=False`.
4. Calls `_create_core_tables(conn)` -- runs the core DDL and index DDL
   via `executescript`.
5. Calls `_create_vector_tables(conn)` -- executes each `CREATE VIRTUAL
   TABLE` statement individually. Returns `False` if the `vec0` module
   is not available.
6. Calls `_record_schema_version(conn, SCHEMA_VERSION)` -- writes version 1.
7. Commits and closes.

Returns the `Path` to the created database file.
