# ClipCannon MCP Tools — Complete Reference (51 Tools)

**Updated:** 2026-03-22
**Source:** `src/clipcannon/server.py`, `src/clipcannon/tools/`

---

## Tool Dispatch Architecture

The MCP server registers `list_tools()` → `ALL_TOOL_DEFINITIONS` and `call_tool(name, arguments)` → `TOOL_DISPATCHERS[name]`. Results serialize to JSON `TextContent`; tools returning images also include `ImageContent` (base64).

| Module | Dispatch Function | Count |
|---|---|---|
| `tools/project.py` | `dispatch_project_tool` | 5 |
| `tools/__init__.py` | `dispatch_understanding_tool` | 7 |
| `tools/provenance_tools.py` | `dispatch_provenance_tool` | 4 |
| `tools/disk.py` | `dispatch_disk_tool` | 2 |
| `tools/config_tools.py` | `dispatch_config_tool` | 3 |
| `tools/billing_tools.py` | `dispatch_billing_tool` | 4 |
| `tools/editing.py` | `dispatch_editing_tool` | 11 |
| `tools/rendering.py` | `dispatch_rendering_tool` | 11 |
| `tools/audio.py` | `dispatch_audio_tool` | 4 |
| **Total** | | **51** |

---

## 1. Project Tools (5)

### clipcannon_project_create

Creates a new project directory and initializes the SQLite database with full schema. Copies or symlinks the source video file into the project.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `source_path` | string | Yes | Absolute path to source video file |
| `name` | string | No | Human-readable project name |

**Returns:** `project_id`, `project_dir`, `db_path`, `source_sha256`

### clipcannon_project_open

Opens an existing project by ID. Validates the project directory and database exist. Returns project metadata from the database.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID to open |

**Returns:** Project metadata (duration, resolution, fps, codec, status)

### clipcannon_project_list

Lists all projects in the ClipCannon projects directory with their status, source file, creation date, and analysis completion state.

**Parameters:** None

**Returns:** Array of project summaries

### clipcannon_project_status

Returns detailed status of a project including pipeline progress, stream completion states, edit count, render count, and disk usage.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |

**Returns:** Comprehensive status with stream_status, edit/render counts, disk usage by tier

### clipcannon_project_delete

Deletes a project directory and all associated data (database, frames, renders, audio). Irreversible.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID to delete |
| `confirm` | boolean | Yes | Must be `true` to confirm deletion |

**Returns:** Confirmation with bytes freed

---

## 2. Understanding Tools (7)

### clipcannon_ingest

Orchestrates the full 21-stage understanding pipeline on a project's source video. Runs probe, VFR normalization, audio extraction, source separation, frame extraction, transcription, visual embedding, OCR, quality assessment, shot type classification, semantic embedding, emotion analysis, speaker diarization, reaction detection, acoustic analysis, profanity detection, chronemic computation, highlight scoring, scene analysis, storyboard generation, and finalization. Costs 10 credits.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID (must have source video) |

**Returns:** Pipeline result with per-stage status, timing, and any errors. ~5 min for 1hr video on RTX 5090.

### clipcannon_get_vud_summary

Returns a compact Video Understanding Document summary (~8K tokens). Includes duration, speakers, topic overview, top highlights, reaction summary, beat info, content rating, average energy, and stream completion status.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID (must be ingested) |

**Returns:** JSON summary — the AI's first perception of the video. Enough to plan editing strategy.

### clipcannon_get_analytics

Returns detailed analytics (~18K tokens): all scene boundaries with shot types, all topics with keywords, all highlights with scores and reasons, all reactions with timestamps. The complete structural map of the video.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `sections` | array | No | Filter to specific sections: `highlights`, `scenes`, `topics`, `reactions` |

**Returns:** Full structural analytics JSON

### clipcannon_get_transcript

Returns paginated word-level transcript (~12K tokens per page). Includes segment text, speaker labels, word-level timestamps, and confidence scores.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `start_ms` | integer | No | Start time filter |
| `end_ms` | integer | No | End time filter |
| `page` | integer | No | Page number (default 1) |

**Returns:** Transcript segments with word-level timestamps for the requested time range

### clipcannon_get_segment_detail

Returns all stream data at full resolution for a specific time range (~15K tokens). Includes transcript, emotion curve (per-second), speakers, reactions, beats, on-screen text, pacing, quality, and silence gaps — all for that range.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `start_ms` | integer | Yes | Start timestamp |
| `end_ms` | integer | Yes | End timestamp |

**Returns:** Full-resolution multi-stream data for fine-grained editing decisions

### clipcannon_get_frame

Returns a single video frame as an inline base64 JPEG with all temporal metadata showing what every stream knows about that moment (transcript, speaker, emotion, topic, shot type, quality, pacing, beat, on-screen text).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `timestamp_ms` | integer | Yes | Frame timestamp in milliseconds |

**Returns:** JPEG image + temporal metadata JSON (~1,600 tokens)

### clipcannon_search_content

Semantic search across transcript segments using sqlite-vec vector similarity. Falls back to text search if embeddings are unavailable.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `query` | string | Yes | Search query text |
| `limit` | integer | No | Max results (default 10) |

**Returns:** Ranked transcript segments with similarity scores, timestamps, and context

---

## 3. Provenance Tools (4)

### clipcannon_provenance_verify

Verifies the integrity of the entire provenance hash chain for a project. Checks every record's chain hash against its parent, detects tampering, validates file hashes.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |

**Returns:** Verification result with `integrity` (verified/failed), record count, any broken links

### clipcannon_provenance_query

Queries provenance records by operation type, time range, or record ID. Returns the full provenance record including input/output hashes, model info, parameters, and timing.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `operation` | string | No | Filter by operation type |
| `record_id` | string | No | Specific record ID |

**Returns:** Matching provenance records

### clipcannon_provenance_chain

Returns the full provenance chain as a DAG — every record linked from source video (root) to latest output (leaves). Shows the complete data lineage.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |

**Returns:** DAG of all provenance records with parent-child relationships

### clipcannon_provenance_timeline

Returns provenance records in chronological order, showing the sequence of all transformations applied to the project data over time.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |

**Returns:** Time-ordered list of all provenance events

---

## 4. Disk Tools (2)

### clipcannon_disk_status

Returns disk usage for a project broken down by tier: Sacred (source + renders, never delete), Regenerable (frames, stems, DB — can recreate), Ephemeral (temp files). Also shows total free disk space.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |

**Returns:** Usage by tier in bytes/GB, file counts, free disk space

### clipcannon_disk_cleanup

Frees disk space by deleting files in priority order: ephemeral first, then regenerable (largest first). Never deletes sacred files.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `target_free_gb` | number | No | Target free space in GB |

**Returns:** Bytes freed, files deleted, new free space

---

## 5. Config Tools (3)

### clipcannon_config_get

Returns the value of a specific configuration key using dot-notation (e.g., `processing.whisper_model`, `rendering.use_nvenc`).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `key` | string | Yes | Config key in dot notation |

**Returns:** Current value for the key

### clipcannon_config_set

Sets a configuration value. Validates the key exists and the value type is correct. Persists to config file.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `key` | string | Yes | Config key in dot notation |
| `value` | any | Yes | New value |

**Returns:** Previous value, new value, confirmation

### clipcannon_config_list

Lists all configuration sections and their current values. Returns the full config tree.

**Parameters:** None

**Returns:** Complete configuration with all 7 sections (version, directories, processing, rendering, audio, publishing, gpu)

---

## 6. Billing Tools (4)

### clipcannon_credits_balance

Returns the current credit balance with HMAC verification. Contacts the license server on localhost:3100.

**Parameters:** None

**Returns:** `balance`, `spending_this_month`, `spending_limit`, `verified` (HMAC check passed)

### clipcannon_credits_history

Returns transaction history (newest first). Shows charges, refunds, and purchases with timestamps.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `limit` | integer | No | Max records (default 50) |
| `offset` | integer | No | Pagination offset |

**Returns:** Array of transactions with operation, credits, balance_before/after, project_id

### clipcannon_credits_estimate

Estimates the credit cost for a planned operation without actually charging. Uses local rate lookup.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `operation` | string | Yes | Operation type: `analyze`, `render`, `metadata`, `publish` |

**Returns:** Estimated credits, current balance, whether sufficient

### clipcannon_spending_limit

Views or updates the monthly spending limit. Limit of 0 means unlimited. Warning at 80%, hard stop at 100%.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `limit` | integer | No | New monthly limit (omit to view current) |

**Returns:** Current/updated limit, spending this month, percentage used

---

## 7. Editing Tools (11)

### clipcannon_create_edit

Creates a new edit from an EDL specification. Accepts segments with time ranges, transitions, speed changes, and per-segment canvas overrides. Optionally generates auto-captions from transcript. Stores the EDL in the project database with status `draft`.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `name` | string | Yes | Edit name |
| `target_platform` | string | Yes | `tiktok`, `instagram_reels`, `youtube_shorts`, `youtube_standard`, `youtube_4k`, `facebook`, `linkedin` |
| `segments` | array | Yes | Segment objects: `source_start_ms`, `source_end_ms`, optional `speed`, `transition_in/out`, `canvas` |
| `captions` | object | No | `enabled`, `style` (bold_centered/word_highlight/subtitle_bar/karaoke), `font`, `font_size`, `color` |
| `crop` | object | No | `mode` (auto/manual/none), `aspect_ratio`, `face_tracking`, `layout` (crop/split_screen/pip) |
| `canvas` | object | No | `enabled`, `canvas_width/height`, `background_color`, `regions[]` with source crop + output placement |
| `audio` | object | No | `source_audio`, `source_volume_db`, `background_music`, `ducking` settings |
| `metadata` | object | No | `title`, `description`, `hashtags`, `thumbnail_timestamp_ms` |

**Returns:** `edit_id`, `name`, `status`, `total_duration_ms`, `segment_count`

### clipcannon_modify_edit

Deep-merges changes into an existing draft edit. Only draft edits can be modified. Supports partial updates to any EDL field.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit ID to modify |
| `changes` | object | Yes | Partial EDL: `name`, `segments`, `captions`, `crop`, `audio`, `metadata`, `render_settings` |

**Returns:** Updated edit summary

### clipcannon_list_edits

Lists all edits for a project with optional status filtering.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `status_filter` | string | No | Filter: `all`, `draft`, `rendering`, `rendered`, `approved`, `rejected`, `failed` |

**Returns:** Array of edit summaries with edit_id, name, status, platform, duration, segment count, render_id

### clipcannon_generate_metadata

Generates platform-specific metadata (title, description, hashtags, thumbnail timestamp) from VUD data. Uses platform-specific tone and constraints (e.g., TikTok = casual 150 chars, LinkedIn = professional 200 chars).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit ID |
| `target_platform` | string | No | Override platform (defaults to edit's platform) |

**Returns:** Generated title, description, hashtags, thumbnail_timestamp_ms

### clipcannon_auto_trim

Analyzes the transcript to find filler words (um, uh, like, basically, literally, you know, I mean) and silence gaps exceeding a threshold. Returns clean segments with filler removed, ready to use in `create_edit`.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `pause_threshold_ms` | integer | No | Min silence gap to cut (default 800ms) |
| `merge_gap_ms` | integer | No | Merge segments closer than this (default 200ms) |
| `min_segment_ms` | integer | No | Drop segments shorter than this (default 500ms) |

**Returns:** Array of clean segments, filler words found, silence gaps removed

### clipcannon_color_adjust

Applies color grading to an edit — either globally or to a specific segment. Stores color spec in the EDL.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit ID |
| `brightness` | number | No | -1.0 to 1.0 |
| `contrast` | number | No | 0.0 to 3.0 |
| `saturation` | number | No | 0.0 to 3.0 |
| `gamma` | number | No | 0.1 to 10.0 |
| `hue_shift` | number | No | -180 to 180 degrees |
| `segment_id` | string | No | Apply to specific segment (omit for global) |

**Returns:** Updated color settings confirmation

### clipcannon_add_motion

Adds a motion effect (zoom, pan, ken burns) to a specific segment. Stores the motion spec in the EDL for rendering.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit ID |
| `segment_id` | string | Yes | Target segment |
| `effect` | string | Yes | `zoom_in`, `zoom_out`, `pan_left`, `pan_right`, `pan_up`, `pan_down`, `ken_burns` |
| `start_scale` | number | No | Starting zoom (0.5-3.0) |
| `end_scale` | number | No | Ending zoom (0.5-3.0) |
| `easing` | string | No | `linear`, `ease_in`, `ease_out`, `ease_in_out` |

**Returns:** Motion spec confirmation

### clipcannon_add_overlay

Adds a visual overlay to an edit. Supports lower thirds, title cards, logos, watermarks, and CTAs with animation.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit ID |
| `overlay_type` | string | Yes | `lower_third`, `title_card`, `logo`, `watermark`, `cta` |
| `text` | string | Yes | Primary text |
| `subtitle` | string | No | Secondary text |
| `position` | string | No | Placement position |
| `start_ms` | integer | No | Overlay start time |
| `end_ms` | integer | No | Overlay end time |
| `opacity` | number | No | 0.0-1.0 |
| `font_size` | integer | No | Font size in pixels |
| `text_color` | string | No | Hex color |
| `bg_color` | string | No | Background hex color |
| `bg_opacity` | number | No | Background opacity |
| `animation` | string | No | `none`, `fade_in`, `fade_out`, `slide_up`, `slide_down` |
| `animation_duration_ms` | integer | No | Animation duration |

**Returns:** Overlay spec confirmation with overlay_id

### clipcannon_extract_subject

AI-powered background removal using rembg. Extracts the subject from video frames and saves alpha masks for compositing.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `model` | string | No | `u2net` (general), `u2net_human_seg` (humans, default), `isnet-general-use` (general v2) |

**Returns:** Mask output path, model used, frame count processed

### clipcannon_replace_background

Replaces the video background using previously extracted subject masks. Requires `extract_subject` to have been run first.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit ID |
| `background_type` | string | Yes | `blur` or `color` |
| `background_value` | string | No | Blur strength or hex color value |

**Returns:** Background replacement settings confirmation

### clipcannon_remove_region

Removes a rectangular region from the video using FFmpeg's delogo filter. Useful for removing watermarks, logos, or UI elements.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit ID |
| `x` | integer | Yes | Region X position |
| `y` | integer | Yes | Region Y position |
| `width` | integer | Yes | Region width |
| `height` | integer | Yes | Region height |
| `description` | string | No | What is being removed (for provenance) |

**Returns:** Region removal confirmation

---

## 8. Rendering Tools (11)

### clipcannon_render

Renders a draft edit to a platform-optimized video file. Executes the full render pipeline: source validation, profile resolution, caption writing, crop computation, FFmpeg execution, thumbnail generation, provenance recording, and DB update. Costs 2 credits (refunded on failure).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit ID (must be draft status) |

**Returns:** `render_id`, `output_path`, `thumbnail_path`, `output_sha256`, `file_size_bytes`, `duration_ms`, `render_duration_ms`

### clipcannon_render_status

Checks the status of a render job.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `render_id` | string | Yes | Render ID |

**Returns:** Status (rendering/rendered/failed), output path, file size, duration, error message if failed

### clipcannon_render_batch

Renders multiple edits concurrently (max 3 parallel via asyncio.Semaphore). Costs 2 credits per edit. Individual failures don't stop the batch.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_ids` | array | Yes | Array of edit IDs to render |

**Returns:** Array of render results (one per edit), total success/failure counts

### clipcannon_get_editing_context

Returns all editing-relevant data in a single call: transcript highlights, silence gaps, pacing analysis, scene boundaries with shot types. Designed to be called FIRST before creating any edits — gives the AI everything needed to plan cuts.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |

**Returns:** Ranked highlights, silence gaps, pacing segments, scene boundaries — all in one response

### clipcannon_analyze_frame

Detects content regions and webcam PIP overlay in a single frame. Identifies where the "main content" (screen share, slides) and "speaker" (webcam) regions are. ~125ms per frame, no credits.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `timestamp_ms` | integer | Yes | Frame timestamp |

**Returns:** Detected regions (content area, webcam area) with bounding boxes and confidence

### clipcannon_preview_clip

Generates a short 2-5 second preview at 540p with fast encoding. No credits charged. Useful for verifying timing and content before full render.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `start_ms` | integer | Yes | Preview start time |
| `duration_ms` | integer | No | Duration (max 5000ms, default 3000ms) |

**Returns:** Preview file path, duration

### clipcannon_inspect_render

Inspects a rendered output by extracting frames at 5 key timestamps (0%, 25%, 50%, 75%, 100%), probing metadata via ffprobe, comparing against the encoding profile spec, and running quality checks. Returns inline base64 frames + pass/fail results.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `render_id` | string | Yes | Render ID to inspect |

**Returns:** 5 sample frames (base64), metadata comparison, quality check pass/fail

### clipcannon_preview_layout

Generates a single JPEG frame showing how a canvas layout will look. Composites all regions onto a 1080x1920 canvas using Pillow. ~300ms, no credits.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `timestamp_ms` | integer | Yes | Source frame timestamp |
| `canvas_width` | integer | No | Canvas width (default 1080) |
| `canvas_height` | integer | No | Canvas height (default 1920) |
| `background_color` | string | No | Background hex color |
| `regions` | array | No | Region definitions (source crop + output placement) |

**Returns:** Composite JPEG preview image (base64)

### clipcannon_measure_layout

Runs face detection on a frame and computes precise canvas regions for 4 predefined layouts on a 1080x1920 canvas. Returns ready-to-use `canvas.regions[]` arrays for `clipcannon_create_edit`.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `timestamp_ms` | integer | Yes | Frame to analyze |
| `layout` | string | Yes | `A` (30/70 split), `B` (40/60 split), `C` (PIP), `D` (full-face) |

**Returns:** Face position, computed regions array, layout description

| Layout | Speaker Region | Content Region |
|---|---|---|
| A | 576px (30%) bottom | 1344px (70%) top |
| B | 768px (40%) bottom | 1152px (60%) top |
| C | 240px circle overlay | Full screen background |
| D | Full screen face crop | N/A |

### clipcannon_get_storyboard

Generates a contact sheet of video frames at 2fps with timestamp labels. Each row covers ~10 seconds. Returns an inline image (~9K tokens) plus the full transcript for the visible time range.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `start_s` | number | No | Start time in seconds (for windowed view) |
| `end_s` | number | No | End time in seconds (for 5s window) |

**Returns:** Contact sheet image (base64) + transcript text

### clipcannon_get_scene_map

Returns a complete scene map for the entire video: scene boundaries, face positions per scene, webcam/content region detection, pre-computed canvas regions for all 4 layouts (A/B/C/D), per-scene transcript snippets, and layout recommendations. Zero manual measurement needed. Requires ingest.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |

**Returns:** Array of scenes with face data, region proposals, transcript, and recommended layout per scene

---

## 9. Audio Tools (4)

### clipcannon_generate_music

Generates AI music using ACE-Step v1.5 turbo-rl diffusion model. Outputs 44.1kHz stereo WAV. Requires GPU with 4+ GB VRAM. The generated music is stored as an audio asset linked to the edit.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit to attach music to |
| `prompt` | string | Yes | Text description of desired music (e.g., "upbeat corporate pop, 120 BPM") |
| `duration_s` | number | Yes | Duration in seconds (max 300) |
| `seed` | integer | No | Random seed for reproducibility |
| `volume_db` | number | No | Volume in dB (default -18) |

**Returns:** `file_path`, `duration_ms`, `sample_rate`, `seed`, `model_used`, `prompt`

### clipcannon_compose_midi

Composes MIDI from presets with theory-correct chord progressions, renders to WAV via FluidSynth. Multi-track: chords, melody, optional bass, optional drums (channel 9). No GPU required.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit to attach music to |
| `preset` | string | Yes | `ambient_pad`, `upbeat_pop`, `corporate`, `dramatic`, `minimal_piano`, `intro_jingle` |
| `duration_s` | number | Yes | Duration in seconds (max 600) |
| `tempo_bpm` | integer | No | Override BPM (uses preset default if omitted) |
| `key` | string | No | Musical key (default from preset) |

**Returns:** `midi_path`, `duration_ms`, `tempo_bpm`, `key`, `preset`

| Preset | BPM | Key | Drums | Progression |
|---|---|---|---|---|
| ambient_pad | 70 | C | No | Cmaj7-Am7-Fmaj7-G7 |
| upbeat_pop | 128 | C | Yes | C-G-Am-F |
| corporate | 100 | C | No | C-F-Am-G |
| dramatic | 90 | A | Yes | Am-F-C-G |
| minimal_piano | 80 | C | No | C-G-Am-F |
| intro_jingle | 120 | C | Yes | C-F-G-C |

### clipcannon_generate_sfx

Generates programmatic DSP sound effects using numpy/scipy. Pure math — no GPU, no models, <100ms per effect. Output: 44.1kHz 16-bit WAV.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit to attach SFX to |
| `sfx_type` | string | Yes | Effect type (see table below) |
| `duration_ms` | integer | No | Duration (default 500ms) |
| `params` | object | No | Type-specific parameters |

| SFX Type | Algorithm | Typical Use |
|---|---|---|
| `whoosh` | Log chirp 200→8000 Hz + exp decay | Transitions |
| `riser` | Linear chirp 100→4000 Hz + crescendo | Build tension before reveal |
| `downer` | Linear chirp 4000→100 Hz + decrescendo | Deflation, disappointment |
| `impact` | White noise burst + fast decay | Emphasis, scene changes |
| `chime` | 3 harmonic sines (880 Hz) + decay | Notifications, highlights |
| `tick` | 1000 Hz sine + sharp attack/decay | UI-style transitions |
| `bass_drop` | 200→40 Hz sweep + sub-harmonic | Dramatic moments |
| `shimmer` | HP filtered noise + slow attack/decay | Ethereal atmosphere |
| `stinger` | Impact (first half) + riser (second half) | Scene transitions |

**Returns:** `file_path`, `duration_ms`, `sample_rate`, `sfx_type`

### clipcannon_audio_cleanup

Cleans up source audio with selectable operations. Each operation is independently toggleable.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit ID |
| `operations` | array | No | Operations to apply (default: all) |

| Operation | Description |
|---|---|
| `noise_reduction` | Spectral gating to remove background noise |
| `normalize` | Peak normalize to -1 dBFS |
| `silence_trim` | Remove leading/trailing silence |
| `eq_adjust` | Low/high cut for speech clarity |

**Returns:** `file_path`, `duration_ms`, `sample_rate`, `operations_applied`

---

## Credit Costs

| Operation | Credits | Tool |
|---|---|---|
| Full pipeline analysis | 10 | `clipcannon_ingest` |
| Render (per edit) | 2 | `clipcannon_render`, `clipcannon_render_batch` |
| Metadata generation | 1 | `clipcannon_generate_metadata` |
| Preview clip | 0 | `clipcannon_preview_clip` |
| Preview layout | 0 | `clipcannon_preview_layout` |
| Analyze frame | 0 | `clipcannon_analyze_frame` |
| All other tools | 0 | Read-only or configuration |

Failed renders are automatically refunded.
