# 08 - MCP Tools Reference

> Current-state documentation of all 27 MCP tools exposed by the ClipCannon server.

## Tool Dispatch Mechanism

The MCP server is implemented in `src/clipcannon/server.py` using the `mcp` Python library. On startup, `create_server()` registers two handlers with the `Server` instance:

1. **`list_tools()`** -- returns `ALL_TOOL_DEFINITIONS`, the concatenated list of `Tool` objects from all six tool modules.
2. **`call_tool(name, arguments)`** -- looks up the tool name in `TOOL_DISPATCHERS`, a flat `dict[str, Callable]` mapping every tool name to its module-level dispatch function. If the name is not found, it returns an `UNKNOWN_TOOL` error.

`TOOL_DISPATCHERS` is built at import time in `src/clipcannon/tools/__init__.py`. It iterates over six `(definitions_list, dispatch_fn)` pairs and maps each `Tool.name` to the corresponding async dispatch function. The dispatch functions are:

| Module | Dispatch Function | Tool Count |
|--------|-------------------|------------|
| `tools/project.py` | `dispatch_project_tool` | 5 |
| `tools/__init__.py` (understanding) | `dispatch_understanding_tool` | 9 |
| `tools/provenance_tools.py` | `dispatch_provenance_tool` | 4 |
| `tools/disk.py` | `dispatch_disk_tool` | 2 |
| `tools/config_tools.py` | `dispatch_config_tool` | 3 |
| `tools/billing_tools.py` | `dispatch_billing_tool` | 4 |

Each dispatch function is a large `if/elif` chain that matches the tool name string and calls the corresponding async handler, casting arguments from the generic `dict[str, object]` to typed parameters.

All tool results are serialized to JSON via `json.dumps(result, indent=2, default=str)` and returned as a single `TextContent` element. Errors are caught at the `call_tool` level and wrapped in a standardized error envelope: `{"error": {"code": "...", "message": "...", "details": {...}}}`.

The server runs over stdio transport by default (`asyncio.run(run_stdio())`). Logging uses a `JsonFormatter` writing structured JSON to stderr so it does not interfere with the MCP stdio protocol on stdout.

---

## Project Management Tools (5)

### `clipcannon_project_create`

**Source:** `src/clipcannon/tools/project.py`

Creates a new project from a source video file. Validates the file format, extracts metadata via ffprobe, computes a SHA-256 hash of the source, creates the project directory structure and SQLite database, copies the source video into the project, initializes `stream_status` rows for all pipeline streams, and records an initial provenance entry.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | `string` | Yes | Human-readable project name |
| `source_video_path` | `string` | Yes | Absolute path to source video (mp4/mov/mkv/webm/avi/ts/mts) |

**Response fields:** `project_id`, `name`, `source_path`, `source_sha256`, `duration_ms`, `resolution`, `fps`, `codec`, `audio_codec`, `audio_channels`, `file_size_bytes`, `vfr_detected`, `status`, `project_dir`.

**Key behaviors:**
- Generates a project ID in the format `proj_{8 hex chars}` using `secrets.token_hex(4)`.
- Validates the file extension against `SUPPORTED_FORMATS`: mp4, mov, mkv, webm, avi, ts, mts.
- Uses `shutil.copy2` to copy the source into `{project_dir}/source/`.
- Returns `INVALID_PARAMETER` error if the file does not exist or has an unsupported format.

---

### `clipcannon_project_open`

**Source:** `src/clipcannon/tools/project.py`

Opens an existing project and returns its current state by reading the `project` table.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |

**Response fields:** All columns from the `project` table (`project_id`, `name`, `source_path`, `source_sha256`, `duration_ms`, `resolution`, `fps`, `codec`, `audio_codec`, `audio_channels`, `file_size_bytes`, `vfr_detected`, `status`, `created_at`, `updated_at`).

**Key behaviors:**
- Returns `PROJECT_NOT_FOUND` if the database file does not exist or the project row is missing.

---

### `clipcannon_project_list`

**Source:** `src/clipcannon/tools/project.py`

Lists all projects, optionally filtered by status.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `status_filter` | `string` | No | Filter: `all`, `created`, `analyzing`, `ready`, `error`. Default: `all`. |

**Response fields:** `projects` (array of project summary dicts), `total` (count).

**Key behaviors:**
- Scans all directories under the projects base directory that start with `proj_` and contain `analysis.db`.
- Each project summary includes `project_id`, `name`, `status`, `duration_ms`, `resolution`, `created_at`.

---

### `clipcannon_project_status`

**Source:** `src/clipcannon/tools/project.py`

Returns detailed project status including pipeline stream progress and disk usage breakdown.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |

**Response fields:**
- `project`: full project row from the database.
- `pipeline`: `total_streams`, `completed`, `failed`, `running`, `pending`, `progress_pct`, `streams` (array of stream status objects with `stream_name`, `status`, `started_at`, `completed_at`, `duration_ms`, `error_message`).
- `disk_usage`: `total_bytes`, `subdirs` (per-subdirectory byte count).

**Key behaviors:**
- Reads the `stream_status` table to calculate pipeline progress percentage.
- Computes disk usage by walking the project directory tree.

---

### `clipcannon_project_delete`

**Source:** `src/clipcannon/tools/project.py`

Deletes a project directory. By default, preserves the original source video.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `keep_source` | `boolean` | No | Preserve source video. Default: `true`. |

**Response fields:** `project_id`, `deleted`, `keep_source`, `freed_bytes`, `freed_mb`.

**Key behaviors:**
- When `keep_source` is true, deletes everything in the project directory except the `source/` subdirectory.
- When `keep_source` is false, removes the entire project directory with `shutil.rmtree`.
- Calculates and reports the total bytes freed.

---

## Understanding Tools (9)

### `clipcannon_ingest`

**Source:** `src/clipcannon/tools/understanding.py`

Runs the full analysis pipeline on a project that is in `created` status.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `options` | `object` | No | Optional pipeline overrides (reserved for future use) |

**Response fields:** `project_id`, `status`, `pipeline_success`, `total_duration_ms`, `stages_completed`, `stages_failed`, `failed_required`, `failed_optional`.

**Key behaviors:**
- Validates that the project status is `created`. Returns `INVALID_STATE` if not.
- Sets project status to `analyzing` before running.
- Imports and builds the pipeline from `clipcannon.pipeline.registry.build_pipeline`.
- On pipeline failure, sets project status to `error`.
- Reports final status as `ready` if `result.success` is true.

---

### `clipcannon_get_vud_summary`

**Source:** `src/clipcannon/tools/understanding.py`

Returns a compact Video Understanding Document summary (~8K tokens) for a project in `ready` or `analyzing` status.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |

**Response fields:** `project_id`, `name`, `duration_ms`, `resolution`, `fps`, `status`, `speakers` (count + details), `topics` (count + preview of first 5), `top_highlights` (top 5 by score), `reactions` (count by type), `beats` (summary or null), `content_safety` (profanity count, density, rating or null), `avg_energy`, `stream_status` (total/completed/failed/skipped), `failed_streams`, `provenance_records`.

**Key behaviors:**
- Queries `speakers`, `topics`, `highlights`, `reactions`, `beats`, `content_safety`, `emotion_curve`, `stream_status`, and `provenance` tables.
- Topic preview is limited to the first 5 by `start_ms`.
- Top highlights are sorted by `score DESC LIMIT 5`.

---

### `clipcannon_get_analytics`

**Source:** `src/clipcannon/tools/understanding.py`

Returns detailed analytics for selected sections (~18K tokens total).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `sections` | `array[string]` | No | Sections to include. Default: all. Options: `highlights`, `scenes`, `topics`, `reactions`, `beats`, `pacing`, `silence_gaps`. |

**Response fields:** `project_id`, `sections`, plus one key per requested section containing the full data arrays.

**Key behaviors:**
- Validates section names against the valid set. Returns `INVALID_PARAMETER` for unknown sections.
- `scenes` section is paginated at 100 rows (`_MAX_SCENES_PER_PAGE`). Returns `total`, `page_size`, `data`, `has_more`.
- `beats` section returns both `summary` (single row from `beats` table) and `sections` (array from `beat_sections` table).

---

### `clipcannon_get_transcript`

**Source:** `src/clipcannon/tools/understanding.py`

Returns transcript segments with word-level timestamps, paginated in 15-minute windows.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `start_ms` | `integer` | No | Start time in milliseconds. Default: `0`. |
| `end_ms` | `integer` | No | End time in milliseconds. Default: `start_ms + 900000` (15 minutes). |

**Response fields:** `project_id`, `start_ms`, `end_ms`, `total_duration_ms`, `segment_count`, `segments` (each with nested `words` array), `has_more`, `next_start_ms`.

**Key behaviors:**
- Each segment includes `segment_id`, `start_ms`, `end_ms`, `text`, `speaker_id`, `language`, `word_count`.
- Each word includes `word`, `start_ms`, `end_ms`, `confidence`, `speaker_id`.
- `has_more` is true if segments exist beyond the current `end_ms`.
- `next_start_ms` is set to `end_ms` when `has_more` is true, null otherwise.

---

### `clipcannon_get_segment_detail`

**Source:** `src/clipcannon/tools/understanding_visual.py`

Returns ALL stream data for a given time range (~15K tokens).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `start_ms` | `integer` | Yes | Start time in ms |
| `end_ms` | `integer` | Yes | End time in ms |

**Response fields:** `project_id`, `start_ms`, `end_ms`, `transcript`, `emotion_curve`, `speakers`, `reactions`, `beat_sections`, `on_screen_text`, `pacing`, `scenes_quality`, `silence_gaps`.

**Key behaviors:**
- Returns `INVALID_PARAMETER` if `end_ms <= start_ms`.
- Queries 8 tables with overlapping range: `transcript_segments`, `emotion_curve`, `reactions`, `beat_sections`, `on_screen_text`, `pacing`, `scenes`, `silence_gaps`.
- Resolves speaker details (label, total_speaking_ms, speaking_pct) for all speaker_ids found in transcript segments.

---

### `clipcannon_get_frame`

**Source:** `src/clipcannon/tools/understanding_visual.py`

Returns the nearest extracted frame to a given timestamp, along with rich moment context.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `timestamp_ms` | `integer` | Yes | Target timestamp in milliseconds |

**Response fields:** `project_id`, `requested_ms`, `actual_ms`, `frame_path`, `at_this_moment`.

The `at_this_moment` context object includes: `transcript`, `speaker_id`, `speaker_label`, `emotion` (arousal/valence/energy), `topic`, `shot_type`, `shot_type_confidence`, `quality`, `quality_classification`, `pacing` (words_per_minute/pause_ratio/label), `on_screen_text`, `profanity` (word/severity).

**Key behaviors:**
- Frame files are named `frame_{number:06d}.jpg` at 500ms intervals (2 fps).
- Searches up to 10 frames in each direction from the target to find the nearest match.
- Returns `FRAME_NOT_FOUND` if no frame exists within range.

---

### `clipcannon_get_frame_strip`

**Source:** `src/clipcannon/tools/understanding_visual.py`

Builds a composite grid image of evenly-spaced frames from a time range.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `start_ms` | `integer` | Yes | Start time in ms |
| `end_ms` | `integer` | Yes | End time in ms |
| `count` | `integer` | No | Number of frames. Default: `9`. Max: `16`. Min: `1`. |

**Response fields:** `project_id`, `start_ms`, `end_ms`, `grid_path` (path to composited JPEG or null on error), `grid_error` (present if composition failed), `cell_count`, `cells` (array with `timestamp_ms`, `frame_path`, `transcript`, `speaker_id`).

**Key behaviors:**
- Clamps count to range [1, 16].
- Composes a JPEG grid at 348x348 pixels per cell, 3 columns, using Pillow (`PIL.Image`).
- Grid output is saved to `{project_dir}/storyboards/strip_{start_ms}_{end_ms}.jpg`.
- If grid composition fails (e.g., Pillow not installed), returns per-cell data with `grid_path: null` and `grid_error`.

---

### `clipcannon_get_storyboard`

**Source:** `src/clipcannon/tools/understanding_visual.py`

Returns pre-built storyboard grids from the database, either by batch number or by time range.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `batch` | `integer` | No | Batch number (1-indexed, 12 grids per batch). Default: `1`. |
| `start_ms` | `integer` | No | Start time filter (ms). Overrides batch if both start_ms and end_ms are provided. |
| `end_ms` | `integer` | No | End time filter (ms). |

**Response fields:** `project_id`, `batch` (or null if time-range mode), `time_range` (or null if batch mode), `total_grids`, `total_batches`, `grid_count`, `grids` (array with `grid_id`, `grid_number`, `grid_path`, `cell_timestamps_ms`, `cell_metadata`).

**Key behaviors:**
- Reads from the `storyboard_grids` table.
- In batch mode: 12 grids per batch with SQL LIMIT/OFFSET.
- In time-range mode: filters grids whose `cell_timestamps_ms` JSON array overlaps the requested range.
- Parses `cell_timestamps_ms` and `cell_metadata` from stored JSON strings.

---

### `clipcannon_search_content`

**Source:** `src/clipcannon/tools/understanding_search.py`

Searches video content by semantic similarity or text match across transcript segments.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `query` | `string` | Yes | Search query |
| `limit` | `integer` | No | Max results. Default: `10`. |
| `search_type` | `string` | No | `semantic` or `text`. Default: `semantic`. |

**Response fields:** `project_id`, `query`, `search_type` (actual type used), `result_count`, `results` (array with `segment_id`, `timestamp_ms`, `text`, `similarity`, `speaker_id`).

**Key behaviors:**
- **Semantic search:** Uses `nomic-ai/nomic-embed-text-v1.5` via `sentence_transformers.SentenceTransformer`. Encodes the query with `search_query:` prefix, normalizes the embedding, and runs KNN search against the `vec_semantic` virtual table (sqlite-vec). Similarity is computed as `1.0 - distance`.
- **Text search:** SQL LIKE query with `%query%` pattern against `transcript_segments.text`.
- Falls back from semantic to text search if the vector model or sqlite-vec is unavailable. The `search_type` field in the response reflects which method was actually used.

---

## Provenance Tools (4)

### `clipcannon_provenance_verify`

**Source:** `src/clipcannon/tools/provenance_tools.py`

Verifies the integrity of the provenance hash chain for a project by recomputing all hashes and comparing them against stored values.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |

**Response fields:** `project_id`, `verified` (boolean), `total_records`, `broken_at` (record ID where chain breaks or null), `issue` (description of the problem or null).

**Key behaviors:**
- Delegates to `clipcannon.provenance.verify_chain`.
- Returns `PROJECT_NOT_FOUND` if the database does not exist.

---

### `clipcannon_provenance_query`

**Source:** `src/clipcannon/tools/provenance_tools.py`

Queries provenance records with optional filtering by operation or stage.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `operation` | `string` | No | Filter by operation name (e.g., `probe`, `transcription`) |
| `stage` | `string` | No | Filter by stage name (e.g., `ffprobe`, `whisperx`) |

**Response fields:** `project_id`, `records` (array of provenance record dicts via `model_dump()`), `total`, `filters` (echo of applied filters).

---

### `clipcannon_provenance_chain`

**Source:** `src/clipcannon/tools/provenance_tools.py`

Walks the provenance chain from genesis to a specific record, showing full processing lineage.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `record_id` | `string` | No | Target record ID to trace back from. Omit for the full chain. |

**Response fields:** `project_id`, `target_record_id` (if specified), `chain` (array of provenance records ordered genesis-first), `total`.

**Key behaviors:**
- When `record_id` is omitted, returns all provenance records for the project (equivalent to a full timeline).
- When `record_id` is provided, calls `get_chain_from_genesis` to walk the parent chain.

---

### `clipcannon_provenance_timeline`

**Source:** `src/clipcannon/tools/provenance_tools.py`

Returns a chronological timeline summary of all provenance events.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |

**Response fields:** `project_id`, `timeline` (array of simplified entries), `total_records`, `total_duration_ms`.

Each timeline entry includes: `record_id`, `timestamp`, `operation`, `stage`, `description`, and conditionally `duration_ms`, `model`, `input`, `output`.

---

## Disk Management Tools (2)

### `clipcannon_disk_status`

**Source:** `src/clipcannon/tools/disk.py`

Inspects disk usage for a project, classified into three storage tiers.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |

**Response fields:** `project_id`, `tiers` (object with `sacred`, `regenerable`, `ephemeral` -- each containing `bytes`, `mb`, `count`, `files`), `total_bytes`, `total_mb`, `system_free_bytes`, `system_free_gb`.

**Storage tier classification:**
- **Sacred** (never auto-deleted): `analysis.db`, `analysis.db-wal`, `analysis.db-shm`, everything in `source/`.
- **Regenerable** (can be recreated by re-running pipeline): everything in `stems/`, `frames/`, `storyboards/`, plus `source_cfr.mp4`.
- **Ephemeral** (safe to delete anytime): all other files (logs, temp files, etc.).

**Key behaviors:**
- Lists individual files per tier, capped at 50 files per tier.
- Reports system-wide free space via `shutil.disk_usage`.

---

### `clipcannon_disk_cleanup`

**Source:** `src/clipcannon/tools/disk.py`

Frees disk space by deleting project files in priority order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `target_free_gb` | `number` | No | Stop cleanup once this many GB are free on disk. Omit to clean all non-sacred files. |

**Response fields:** `project_id`, `deleted_files` (array with `path`, `size_bytes`, `tier`), `total_deleted`, `freed_bytes`, `freed_mb`, `system_free_gb_after`.

**Key behaviors:**
- Deletion order: ephemeral files first, then regenerable files sorted largest-first.
- Sacred files are never deleted.
- If `target_free_gb` is set, stops as soon as system free space reaches the target.
- Cleans up empty directories after file deletion.

---

## Configuration Tools (3)

### `clipcannon_config_get`

**Source:** `src/clipcannon/tools/config_tools.py`

Reads a configuration value by dot-notation key path.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `key` | `string` | Yes | Dot-separated config key (e.g., `processing.whisper_model`, `gpu.device`) |

**Response fields:** `key`, `value`.

---

### `clipcannon_config_set`

**Source:** `src/clipcannon/tools/config_tools.py`

Sets a configuration value and persists it to disk.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `key` | `string` | Yes | Dot-separated config key path |
| `value` | `any` | Yes | New value (type must match config schema) |

**Response fields:** `key`, `old_value`, `new_value`, `saved` (boolean).

**Key behaviors:**
- Validates the value against the config schema. Returns `INVALID_PARAMETER` on type mismatch.
- Calls `config.save()` to persist changes to disk after setting.

---

### `clipcannon_config_list`

**Source:** `src/clipcannon/tools/config_tools.py`

Lists all configuration values.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| (none) | | | |

**Response fields:** `config` (complete configuration dictionary), `config_path` (filesystem path to the config file).

---

## Billing Tools (4)

### `clipcannon_credits_balance`

**Source:** `src/clipcannon/tools/billing_tools.py`

Returns current credit balance, monthly spending, and spending limit.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| (none) | | | |

**Response fields:** `balance`, `spending_this_month`, `spending_limit`, and optionally `warning` (string present when spending is at or above 80% of the limit).

**Key behaviors:**
- Communicates with the license server via `LicenseClient.get_balance()`.
- If the license server is unreachable (balance returned as -1), returns a `LICENSE_SERVER_UNREACHABLE` error.
- Warning thresholds: 80% triggers a warning message, 100% triggers a limit-reached message.

---

### `clipcannon_credits_history`

**Source:** `src/clipcannon/tools/billing_tools.py`

Returns transaction history, newest first.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | `integer` | No | Maximum number of transactions to return. Default: `20`. |

**Response fields:** `transactions` (array with `transaction_id`, `operation`, `credits`, `balance_after`, `project_id`, `reason`, `created_at`), `total`.

**Key behaviors:**
- Returns an empty list with a message if the license server is unreachable.

---

### `clipcannon_credits_estimate`

**Source:** `src/clipcannon/tools/billing_tools.py`

Estimates the credit cost for an operation before running it.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `operation` | `string` | Yes | Operation to estimate. Enum: `analyze`, `render`, `metadata`, `publish`. |

**Response fields:** `operation`, `credits`, `message`.

**Key behaviors:**
- Lookup is local (no server call). Uses the `CREDIT_RATES` dictionary.
- Returns `UNKNOWN_OPERATION` error with the list of valid operations if the operation is not recognized.

---

### `clipcannon_spending_limit`

**Source:** `src/clipcannon/tools/billing_tools.py`

Sets the monthly spending limit in credits.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit_credits` | `integer` | Yes | Monthly spending limit in credits. `0` means unlimited. |

**Response fields:** `success`, `spending_limit`, `message`.

**Key behaviors:**
- Returns `INVALID_LIMIT` error if the value is negative.
- Sends a POST to `/v1/spending_limit` on the license server.
- Returns `LICENSE_SERVER_UNREACHABLE` if the server is down.
