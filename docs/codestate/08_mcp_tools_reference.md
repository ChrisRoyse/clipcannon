# 08 - MCP Tools Reference

> Current-state documentation of all 51 MCP tools exposed by the ClipCannon server.

## Tool Dispatch Mechanism

The MCP server is implemented in `src/clipcannon/server.py` using the `mcp` Python library. On startup, `create_server()` registers two handlers with the `Server` instance:

1. **`list_tools()`** -- returns `ALL_TOOL_DEFINITIONS`, the concatenated list of `Tool` objects from all nine tool modules.
2. **`call_tool(name, arguments)`** -- looks up the tool name in `TOOL_DISPATCHERS`, a flat `dict[str, Callable]` mapping every tool name to its module-level dispatch function. If the name is not found, it returns an `UNKNOWN_TOOL` error. If the result contains an `_image` key, an `ImageContent` with base64 data is also returned for inline image viewing.

`TOOL_DISPATCHERS` is built at import time in `src/clipcannon/tools/__init__.py`. It iterates over nine `(definitions_list, dispatch_fn)` pairs and maps each `Tool.name` to the corresponding async dispatch function. The dispatch functions are:

| Module | Dispatch Function | Tool Count |
|--------|-------------------|------------|
| `tools/project.py` | `dispatch_project_tool` | 5 |
| `tools/__init__.py` (understanding) | `dispatch_understanding_tool` | 7 |
| `tools/provenance_tools.py` | `dispatch_provenance_tool` | 4 |
| `tools/disk.py` | `dispatch_disk_tool` | 2 |
| `tools/config_tools.py` | `dispatch_config_tool` | 3 |
| `tools/billing_tools.py` | `dispatch_billing_tool` | 4 |
| `tools/editing.py` | `dispatch_editing_tool` | 11 |
| `tools/rendering.py` | `dispatch_rendering_tool` | 11 |
| `tools/audio.py` | `dispatch_audio_tool` | 4 |

Each dispatch function is a large `if/elif` chain that matches the tool name string and calls the corresponding async handler. All tool results are serialized to JSON via `json.dumps(result, indent=2, default=str)` and returned as a single `TextContent` element, optionally followed by an `ImageContent` for tools that return inline images.

---

## Project Management Tools (5)

*(Unchanged -- `clipcannon_project_create`, `clipcannon_project_open`, `clipcannon_project_list`, `clipcannon_project_status`, `clipcannon_project_delete`)*

---

## Understanding Tools (7)

`clipcannon_ingest`, `clipcannon_get_vud_summary`, `clipcannon_get_analytics`, `clipcannon_get_transcript`, `clipcannon_get_segment_detail`, `clipcannon_get_frame`, `clipcannon_search_content`

The understanding tools provide pipeline execution and data retrieval. `clipcannon_get_frame` returns an inline base64 JPEG image via the `_image` key in the result dict.

---

## Provenance Tools (4)

*(Unchanged -- `clipcannon_provenance_verify`, `clipcannon_provenance_query`, `clipcannon_provenance_chain`, `clipcannon_provenance_timeline`)*

---

## Disk Management Tools (2)

*(Unchanged -- `clipcannon_disk_status`, `clipcannon_disk_cleanup`)*

---

## Configuration Tools (3)

*(Unchanged -- `clipcannon_config_get`, `clipcannon_config_set`, `clipcannon_config_list`)*

---

## Billing Tools (4)

*(Unchanged -- `clipcannon_credits_balance`, `clipcannon_credits_history`, `clipcannon_credits_estimate`, `clipcannon_spending_limit`)*

---

## Editing Tools (11)

### `clipcannon_create_edit`

**Source:** `src/clipcannon/tools/editing.py`

Creates a new edit from an EDL specification with automatic caption generation. Supports per-segment canvas overrides with compositing regions and animated zoom.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `name` | `string` | Yes | Human-readable edit name |
| `target_platform` | `string` | Yes | Target platform enum: tiktok, instagram_reels, youtube_shorts, youtube_standard, youtube_4k, facebook, linkedin |
| `segments` | `array` | Yes | Array of segment objects with `source_start_ms`, `source_end_ms`, optional `speed`, `transition_in`, `transition_out`, `canvas` (per-segment compositing override) |
| `captions` | `object` | No | Caption spec: `enabled`, `style`, `font`, `font_size`, `color` |
| `crop` | `object` | No | Crop spec: `mode`, `aspect_ratio`, `face_tracking`, `layout` |
| `canvas` | `object` | No | Canvas compositing: `enabled`, `canvas_width`, `canvas_height`, `background_color`, `regions[]` |
| `audio` | `object` | No | Audio spec: `source_audio`, `source_volume_db`, `background_music`, `ducking` |
| `metadata` | `object` | No | Metadata spec: `title`, `description`, `hashtags`, `thumbnail_timestamp_ms` |

---

### `clipcannon_modify_edit`

**Source:** `src/clipcannon/tools/editing.py`

Modifies a draft edit via deep merge of changes.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |
| `changes` | `object` | Yes | Fields to update: `name`, `segments`, `captions`, `crop`, `audio`, `metadata`, `render_settings` |

---

### `clipcannon_list_edits`

**Source:** `src/clipcannon/tools/editing.py`

Lists edits for a project with optional status filtering.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `status_filter` | `string` | No | Filter: all, draft, rendering, rendered, approved, rejected, failed. Default: all. |

---

### `clipcannon_generate_metadata`

**Source:** `src/clipcannon/tools/editing.py`

Generates platform-specific metadata from VUD data for an edit.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |
| `target_platform` | `string` | No | Override platform (defaults to edit's target_platform) |

---

### `clipcannon_auto_trim`

**Source:** `src/clipcannon/tools/editing.py`

Analyzes transcript to find filler words (um, uh, like, basically, literally, you know, I mean, etc.) and long pauses, then generates optimized segments that remove them. Returns segments ready for `clipcannon_create_edit`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `pause_threshold_ms` | `integer` | No | Minimum pause duration to remove (default: 800ms) |
| `merge_gap_ms` | `integer` | No | Merge segments separated by less than this (default: 200ms) |
| `min_segment_ms` | `integer` | No | Drop segments shorter than this (default: 500ms) |

---

### `clipcannon_color_adjust`

**Source:** `src/clipcannon/tools/editing.py`

Applies color grading to an edit. Can be applied globally or per-segment.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |
| `brightness` | `number` | No | Brightness (-1.0 to 1.0, default 0.0) |
| `contrast` | `number` | No | Contrast (0.0 to 3.0, default 1.0) |
| `saturation` | `number` | No | Saturation (0.0 to 3.0, default 1.0) |
| `gamma` | `number` | No | Gamma (0.1 to 10.0, default 1.0) |
| `hue_shift` | `number` | No | Hue shift (-180 to 180 degrees, default 0.0) |
| `segment_id` | `integer` | No | Apply to specific segment (omit for global) |

---

### `clipcannon_add_motion`

**Source:** `src/clipcannon/tools/editing.py`

Adds motion effect to an edit segment.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |
| `segment_id` | `integer` | Yes | Segment to apply motion to |
| `effect` | `string` | Yes | Effect: zoom_in, zoom_out, pan_left, pan_right, pan_up, pan_down, ken_burns |
| `start_scale` | `number` | No | Starting zoom scale (0.5-3.0, default 1.0) |
| `end_scale` | `number` | No | Ending zoom scale (0.5-3.0, default 1.3) |
| `easing` | `string` | No | Easing: linear, ease_in, ease_out, ease_in_out (default linear) |

---

### `clipcannon_add_overlay`

**Source:** `src/clipcannon/tools/editing.py`

Adds a visual overlay to an edit.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |
| `overlay_type` | `string` | Yes | Type: lower_third, title_card, logo, watermark, cta |
| `text` | `string` | Yes | Main text content |
| `subtitle` | `string` | No | Subtitle text (lower_third only) |
| `position` | `string` | No | Position: bottom_left, bottom_center, bottom_right, top_left, top_center, top_right, center |
| `start_ms` | `integer` | Yes | Overlay start time (ms) |
| `end_ms` | `integer` | Yes | Overlay end time (ms) |
| `opacity` | `number` | No | Opacity (0-1, default 1.0) |
| `font_size` | `integer` | No | Font size (8-200, default 36) |
| `text_color` | `string` | No | Text color hex (default #FFFFFF) |
| `bg_color` | `string` | No | Background color hex (default #000000) |
| `bg_opacity` | `number` | No | Background opacity (0-1, default 0.7) |
| `animation` | `string` | No | Animation: none, fade_in, fade_out, slide_up, slide_down |
| `animation_duration_ms` | `integer` | No | Animation duration (ms, default 500) |

---

### `clipcannon_extract_subject`

**Source:** `src/clipcannon/tools/editing.py`

Extracts the subject (person/speaker) from video frames using AI background removal (rembg). Generates alpha mask frames.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `model` | `string` | No | rembg model: u2net, u2net_human_seg (default), isnet-general-use |

---

### `clipcannon_replace_background`

**Source:** `src/clipcannon/tools/editing.py`

Replaces the video background. Requires `extract_subject` to be run first.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |
| `background_type` | `string` | Yes | Background type: blur, color |
| `background_value` | `string` | No | For blur: sigma value (default 40). For color: hex color (e.g. '#1a1a2e') |

---

### `clipcannon_remove_region`

**Source:** `src/clipcannon/tools/editing.py`

Removes a rectangular region from the source video using FFmpeg delogo filter. Use to remove browser chrome, taskbars, watermarks, or logos.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |
| `x` | `integer` | Yes | Left edge of region to remove (px in source) |
| `y` | `integer` | Yes | Top edge of region to remove (px in source) |
| `width` | `integer` | Yes | Width of region (px) |
| `height` | `integer` | Yes | Height of region (px) |
| `description` | `string` | No | What is being removed (e.g., 'browser chrome') |

---

## Rendering Tools (11)

### `clipcannon_render`

**Source:** `src/clipcannon/tools/rendering.py`

Renders a single edit to a platform-optimized video file. Charges 2 credits.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |

---

### `clipcannon_render_status`

**Source:** `src/clipcannon/tools/rendering.py`

Checks the status of a render.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `render_id` | `string` | Yes | Render identifier |

---

### `clipcannon_render_batch`

**Source:** `src/clipcannon/tools/rendering.py`

Renders multiple edits concurrently (max 3 parallel). Charges 2 credits per edit.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_ids` | `array[string]` | Yes | Edit identifiers to render (min 1) |

---

### `clipcannon_get_editing_context`

**Source:** `src/clipcannon/tools/rendering.py`

Gets ALL data needed for editing decisions in one call: transcript, highlights (ranked), silence gaps (natural cut points), pacing, and scene boundaries. Use this FIRST before creating any edit.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |

---

### `clipcannon_analyze_frame`

**Source:** `src/clipcannon/tools/rendering.py`

Analyzes a frame for content regions and webcam PIP overlay. Returns bounding boxes of detected content regions and PIP webcam position. ~125ms per frame. No credits charged.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `timestamp_ms` | `integer` | Yes | Source video timestamp to analyze (ms) |

---

### `clipcannon_preview_clip`

**Source:** `src/clipcannon/tools/rendering.py`

Renders a short (2-5 second) low-quality 540p preview of an edit at a specific time range. No credits charged.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `start_ms` | `integer` | Yes | Start time in source video (ms) |
| `duration_ms` | `integer` | No | Preview duration (ms, max 5000, default 3000) |

---

### `clipcannon_inspect_render`

**Source:** `src/clipcannon/tools/rendering.py`

Inspects a rendered video output. Extracts frames at 5 key timestamps (start, 25%, 50%, 75%, end), probes metadata, and runs quality checks. Returns inline frame images, metadata comparison, and pass/fail results.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `render_id` | `string` | Yes | Render identifier to inspect |

---

### `clipcannon_preview_layout`

**Source:** `src/clipcannon/tools/rendering.py`

Generates a single preview frame showing what a canvas layout looks like at a specific timestamp. Returns a JPEG image path in ~300ms. No credits charged.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `timestamp_ms` | `integer` | Yes | Source video timestamp to preview (ms) |
| `canvas_width` | `integer` | No | Output canvas width (default 1080) |
| `canvas_height` | `integer` | No | Output canvas height (default 1920) |
| `background_color` | `string` | No | Canvas background hex color (default #000000) |
| `regions` | `array` | Yes | Canvas regions with source/output coordinates, z_index, fit_mode |

---

### `clipcannon_measure_layout`

**Source:** `src/clipcannon/tools/rendering.py`

Measures exact layout coordinates using face detection. Runs face detection on a frame and computes mathematically precise source crop and output placement coordinates. Returns ready-to-use canvas regions for create_edit.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `timestamp_ms` | `integer` | Yes | Source timestamp to analyze (ms) |
| `layout` | `string` | No | Layout type: A (30/70 split), B (40/60 split), C (PIP), D (full-screen face). Default: A. |

---

### `clipcannon_get_storyboard`

**Source:** `src/clipcannon/tools/rendering.py`

Gets a contact sheet of ALL video frames in one image. Shows every frame at 2fps as thumbnails with timestamp labels in a grid. Each row = 10 seconds. Returns the ENTIRE video in one inline image (~9K tokens) plus the full transcript with timestamps.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `start_s` | `integer` | No | Start time in seconds (shows 5 seconds of frames from this point; omit for full overview) |
| `end_s` | `integer` | No | End time in seconds (defaults to start_s + 5) |

---

### `clipcannon_get_scene_map`

**Source:** `src/clipcannon/tools/rendering.py`

Gets the complete scene map for a project. Returns EVERYTHING needed for editing in ONE call: every scene with boundaries, face positions, webcam region, content area coordinates, pre-computed canvas regions for layouts A/B/C/D, transcript aligned per scene, and layout recommendations. The AI uses canvas_regions directly in create_edit -- zero manual coordinate measurement needed. Requires ingest to have been run first.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |

---

## Audio Generation Tools (4)

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

---

### `clipcannon_audio_cleanup`

**Source:** `src/clipcannon/tools/audio.py`

Cleans up source audio with noise reduction, normalization, silence trimming, and EQ adjustment.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | `string` | Yes | Project identifier |
| `edit_id` | `string` | Yes | Edit identifier |
| `operations` | `array[string]` | No | Cleanup operations to apply (from SUPPORTED_CLEANUP_OPS) |
