# 08 - MCP Tools Reference

> Current-state documentation of all 37 MCP tools exposed by the ClipCannon server.

## Tool Dispatch Mechanism

The MCP server is implemented in `src/clipcannon/server.py` using the `mcp` Python library. On startup, `create_server()` registers two handlers with the `Server` instance:

1. **`list_tools()`** -- returns `ALL_TOOL_DEFINITIONS`, the concatenated list of `Tool` objects from all nine tool modules.
2. **`call_tool(name, arguments)`** -- looks up the tool name in `TOOL_DISPATCHERS`, a flat `dict[str, Callable]` mapping every tool name to its module-level dispatch function. If the name is not found, it returns an `UNKNOWN_TOOL` error.

`TOOL_DISPATCHERS` is built at import time in `src/clipcannon/tools/__init__.py`. It iterates over nine `(definitions_list, dispatch_fn)` pairs and maps each `Tool.name` to the corresponding async dispatch function. The dispatch functions are:

| Module | Dispatch Function | Tool Count |
|--------|-------------------|------------|
| `tools/project.py` | `dispatch_project_tool` | 5 |
| `tools/__init__.py` (understanding) | `dispatch_understanding_tool` | 9 |
| `tools/provenance_tools.py` | `dispatch_provenance_tool` | 4 |
| `tools/disk.py` | `dispatch_disk_tool` | 2 |
| `tools/config_tools.py` | `dispatch_config_tool` | 3 |
| `tools/billing_tools.py` | `dispatch_billing_tool` | 4 |
| `tools/editing.py` | `dispatch_editing_tool` | 4 |
| `tools/rendering.py` | `dispatch_rendering_tool` | 3 |
| `tools/audio.py` | `dispatch_audio_tool` | 3 |

Each dispatch function is a large `if/elif` chain that matches the tool name string and calls the corresponding async handler. All tool results are serialized to JSON via `json.dumps(result, indent=2, default=str)` and returned as a single `TextContent` element.

---

## Project Management Tools (5)

*(Unchanged from Phase 1 -- `clipcannon_project_create`, `clipcannon_project_open`, `clipcannon_project_list`, `clipcannon_project_status`, `clipcannon_project_delete`)*

---

## Understanding Tools (9)

*(Unchanged from Phase 1 -- `clipcannon_ingest`, `clipcannon_get_vud_summary`, `clipcannon_get_analytics`, `clipcannon_get_transcript`, `clipcannon_get_segment_detail`, `clipcannon_get_frame`, `clipcannon_get_frame_strip`, `clipcannon_get_storyboard`, `clipcannon_search_content`)*

---

## Provenance Tools (4)

*(Unchanged from Phase 1 -- `clipcannon_provenance_verify`, `clipcannon_provenance_query`, `clipcannon_provenance_chain`, `clipcannon_provenance_timeline`)*

---

## Disk Management Tools (2)

*(Unchanged from Phase 1 -- `clipcannon_disk_status`, `clipcannon_disk_cleanup`)*

---

## Configuration Tools (3)

*(Unchanged from Phase 1 -- `clipcannon_config_get`, `clipcannon_config_set`, `clipcannon_config_list`)*

---

## Billing Tools (4)

*(Unchanged from Phase 1 -- `clipcannon_credits_balance`, `clipcannon_credits_history`, `clipcannon_credits_estimate`, `clipcannon_spending_limit`)*

---

## Editing Tools (4) -- Phase 2

### `clipcannon_create_edit`

**Source:** `src/clipcannon/tools/editing.py`

Creates a new edit from an EDL specification with automatic caption generation.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `name` | `string` | Yes | Human-readable edit name |
| `target_platform` | `string` | Yes | Target platform enum: tiktok, instagram_reels, youtube_shorts, youtube_standard, youtube_4k, facebook, linkedin |
| `segments` | `array` | Yes | Array of segment objects with `source_start_ms`, `source_end_ms`, optional `speed` (0.25-4.0), `transition_in`, `transition_out` |
| `captions` | `object` | No | Caption spec: `enabled`, `style` (bold_centered/word_highlight/subtitle_bar/karaoke), `font`, `font_size`, `color` |
| `crop` | `object` | No | Crop spec: `mode` (auto/manual/none), `aspect_ratio`, `face_tracking`, `layout` (crop/split_screen/pip) |
| `audio` | `object` | No | Audio spec: `source_audio`, `source_volume_db`, `background_music`, `ducking` |
| `metadata` | `object` | No | Metadata spec: `title`, `description`, `hashtags`, `thumbnail_timestamp_ms` |

**Response fields:** `edit_id`, `status`, `message`, `edl` (full EDL JSON), `created_at`.

**Key behaviors:**
- Generates edit ID as `edit_{8 hex chars}` via `secrets.token_hex(4)`.
- Validates project exists and is in `ready` status.
- Auto-assigns `segment_id` and `output_start_ms` to segments.
- Auto-generates caption chunks from transcript words via `fetch_words_for_segments` + `chunk_transcript_words` + `remap_timestamps`.
- Validates EDL against source SHA-256, segment ordering, duration limits, and platform constraints.
- Stores EDL JSON, segments, and edit metadata in database.
- Creates `edits/{edit_id}/` working directory.

---

### `clipcannon_modify_edit`

**Source:** `src/clipcannon/tools/editing.py`

Modifies a draft edit via deep merge of changes.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |
| `changes` | `object` | Yes | Fields to update: `name`, `segments`, `captions`, `crop`, `audio`, `metadata`, `render_settings` |

**Response fields:** `edit_id`, `updated_fields` (list), `segments_changed` (bool), `message`.

**Key behaviors:**
- Only draft edits can be modified. Non-draft edits return `INVALID_STATE` error.
- Applies changes via deep merge using `apply_changes()`.
- If segments changed, regenerates caption chunks automatically.
- Re-validates the complete EDL after modification.
- Updates `edl_json` and related columns in database.

---

### `clipcannon_list_edits`

**Source:** `src/clipcannon/tools/editing.py`

Lists edits for a project with optional status filtering.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `status_filter` | `string` | No | Filter: all, draft, rendering, rendered, approved, rejected, failed. Default: all. |

**Response fields:** `edits` (array of edit summaries with `edit_id`, `name`, `status`, `platform`, `duration_ms`, `segment_count`).

---

### `clipcannon_generate_metadata`

**Source:** `src/clipcannon/tools/editing.py`

Generates platform-specific metadata from VUD data for an edit.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |
| `target_platform` | `string` | No | Override platform (defaults to edit's target_platform) |

**Response fields:** `title`, `description`, `hashtags` (array), `thumbnail_timestamp_ms`.

**Key behaviors:**
- Fetches topics, highlights, and transcript for the edit's time range.
- Generates platform-appropriate title with tone prefix (casual for TikTok, professional for LinkedIn, SEO for YouTube).
- Builds hashtags from topic keywords, respecting platform hashtag count limits.
- Selects thumbnail timestamp at midpoint of highest-scoring highlight.
- Updates the edit's metadata in the database.

---

## Rendering Tools (3) -- Phase 2

### `clipcannon_render`

**Source:** `src/clipcannon/tools/rendering.py`

Renders a single edit to a platform-optimized video file.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |

**Response fields:** `render_id`, `status`, `output_path`, `file_size_bytes`, `duration_ms`, `render_duration_ms`, `thumbnail_path`, `output_sha256`, `credits_charged`, `elapsed_ms`.

**Key behaviors:**
- Charges 2 credits via `LicenseClient` before rendering.
- Updates edit status: draft -> rendering -> rendered (or failed).
- Validates source SHA-256 against EDL to prevent rendering from modified sources.
- Rejects renders from `/renders/` directories to prevent generation loss.
- Writes ASS subtitle file for caption burn-in.
- Computes crop region from EDL spec and scene data.
- Executes FFmpeg asynchronously with the appropriate encoding profile.
- Generates JPEG thumbnail at the specified timestamp.
- Records provenance entry linking rendered file to source.
- On failure, refunds the 2 credits and sets edit status to failed.

---

### `clipcannon_render_status`

**Source:** `src/clipcannon/tools/rendering.py`

Checks the status of a render.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `render_id` | `string` | Yes | Render identifier |

**Response fields:** `render_id`, `edit_id`, `status`, `profile`, `output_path`, `output_sha256`, `file_size_bytes`, `duration_ms`, `resolution`, `codec`, `thumbnail_path`, `render_duration_ms`, `error_message`, `created_at`, `completed_at`.

---

### `clipcannon_render_batch`

**Source:** `src/clipcannon/tools/rendering.py`

Renders multiple edits concurrently.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_ids` | `array[string]` | Yes | Edit identifiers to render (min 1) |

**Response fields:** `project_id`, `total`, `succeeded`, `failed`, `credits_charged`, `renders` (array of per-edit results), `load_errors` (array), `elapsed_ms`.

**Key behaviors:**
- Charges 2 credits per edit (total = 2 * count).
- Loads and validates all EDLs before rendering.
- Executes renders concurrently with `asyncio.Semaphore(max_concurrent=3)`.
- Individual render failures do not stop the batch; continues processing remaining edits.

---

## Audio Generation Tools (3) -- Phase 2

### `clipcannon_generate_music`

**Source:** `src/clipcannon/tools/audio.py`

Generates AI music from a text prompt using ACE-Step v1.5 diffusion model.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |
| `prompt` | `string` | Yes | Text description of desired music |
| `duration_s` | `number` | Yes | Duration in seconds (max 300) |
| `seed` | `integer` | No | Random seed for reproducibility |
| `volume_db` | `number` | No | Volume adjustment in dB. Default: -18. |

**Response fields:** `asset_id`, `file_path`, `duration_ms`, `seed`, `model_used`, `elapsed_s`.

**Key behaviors:**
- Requires GPU with 4+ GB VRAM. Uses `cpu_offload` if <8 GB VRAM.
- Generates random seed if not provided.
- Stores audio asset record in `audio_assets` table with `model_used="ace-step-v15-turbo-rl"`.
- Output is WAV at 44100 Hz in `{project_dir}/edits/{edit_id}/audio/`.

---

### `clipcannon_compose_midi`

**Source:** `src/clipcannon/tools/audio.py`

Composes MIDI from presets and renders to WAV via FluidSynth.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |
| `preset` | `string` | Yes | Preset enum: ambient_pad, upbeat_pop, corporate, dramatic, minimal_piano, intro_jingle |
| `duration_s` | `number` | Yes | Duration in seconds (max 600) |
| `tempo_bpm` | `integer` | No | Override preset tempo |
| `key` | `string` | No | Override preset key (e.g., "C", "Dm") |

**Response fields:** `asset_id`, `file_path`, `midi_path`, `duration_ms`, `preset`, `tempo_bpm`, `key`, `elapsed_s`, optional `note` (if FluidSynth unavailable, MIDI-only fallback).

**Key behaviors:**
- Two-step: compose MIDI via MIDIUtil, then render to WAV via FluidSynth.
- Falls back to MIDI-only if FluidSynth is not installed (returns `.mid` file with a note).
- Stores asset with `model_used="midiutil"` or `"midiutil+fluidsynth"`.

---

### `clipcannon_generate_sfx`

**Source:** `src/clipcannon/tools/audio.py`

Generates programmatic DSP sound effects.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |
| `sfx_type` | `string` | Yes | SFX type enum: whoosh, riser, downer, impact, chime, tick, bass_drop, shimmer, stinger |
| `duration_ms` | `integer` | No | Duration in milliseconds (1-30000). Default: 500. |
| `params` | `object` | No | Type-specific parameters (e.g., `frequency`, `decay_rate`) |

**Response fields:** `asset_id`, `file_path`, `duration_ms`, `sfx_type`, `elapsed_s`.

**Key behaviors:**
- Pure DSP synthesis using numpy and scipy -- no ML model, no GPU required.
- All outputs are WAV at 44100 Hz with zero-crossing fades.
- Stores asset with `model_used="dsp"`.
