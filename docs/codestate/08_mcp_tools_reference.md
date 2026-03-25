# MCP Tools Reference (51 Tools)

## Tool Dispatch

Source: `src/clipcannon/server.py`, `src/clipcannon/tools/__init__.py`

The MCP server registers `list_tools()` -> `ALL_TOOL_DEFINITIONS` and `call_tool(name, arguments)` -> `TOOL_DISPATCHERS[name]`. Results serialize to JSON `TextContent`; tools returning `_image` also get `ImageContent` (base64).

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

Helper files: `tools/editing_defs.py` (tool schemas), `tools/editing_helpers.py` (validation, DB ops), `tools/rendering_defs.py` (tool schemas), `tools/storyboard.py` (storyboard logic), `tools/understanding_search.py` (search logic), `tools/understanding_visual.py` (frame/segment logic), `tools/video_probe.py` (ffprobe wrapper).

---

## Project Tools (5)

`clipcannon_project_create`, `clipcannon_project_open`, `clipcannon_project_list`, `clipcannon_project_status`, `clipcannon_project_delete`

## Understanding Tools (7)

`clipcannon_ingest`, `clipcannon_get_vud_summary`, `clipcannon_get_analytics`, `clipcannon_get_transcript`, `clipcannon_get_segment_detail`, `clipcannon_get_frame` (returns inline base64 JPEG), `clipcannon_search_content`

## Provenance Tools (4)

`clipcannon_provenance_verify`, `clipcannon_provenance_query`, `clipcannon_provenance_chain`, `clipcannon_provenance_timeline`

## Disk Tools (2)

`clipcannon_disk_status`, `clipcannon_disk_cleanup`

## Config Tools (3)

`clipcannon_config_get`, `clipcannon_config_set`, `clipcannon_config_list`

## Billing Tools (4)

`clipcannon_credits_balance`, `clipcannon_credits_history`, `clipcannon_credits_estimate`, `clipcannon_spending_limit`

---

## Editing Tools (11)

### clipcannon_create_edit

Creates edit from EDL spec with auto-captions. Supports per-segment canvas overrides with compositing regions and animated zoom.

| Parameter | Type | Req | Description |
|---|---|---|---|
| `project_id` | string | Y | Project ID |
| `name` | string | Y | Edit name |
| `target_platform` | string | Y | tiktok, instagram_reels, youtube_shorts, youtube_standard, youtube_4k, facebook, linkedin |
| `segments` | array | Y | Segment objects: `source_start_ms`, `source_end_ms`, optional `speed`, `transition_in/out`, `canvas` |
| `captions` | object | N | `enabled`, `style`, `font`, `font_size`, `color` |
| `crop` | object | N | `mode`, `aspect_ratio`, `face_tracking`, `layout` |
| `canvas` | object | N | `enabled`, `canvas_width/height`, `background_color`, `regions[]` |
| `audio` | object | N | `source_audio`, `source_volume_db`, `background_music`, `ducking` |
| `metadata` | object | N | `title`, `description`, `hashtags`, `thumbnail_timestamp_ms` |

### clipcannon_modify_edit

Deep-merges `changes` into a draft edit. Params: `project_id`, `edit_id`, `changes` (object with `name`, `segments`, `captions`, `crop`, `audio`, `metadata`, `render_settings`).

### clipcannon_list_edits

Lists edits for a project. Params: `project_id`, optional `status_filter` (all/draft/rendering/rendered/approved/rejected/failed).

### clipcannon_generate_metadata

Generates platform-specific metadata from VUD data. Params: `project_id`, `edit_id`, optional `target_platform`.

### clipcannon_auto_trim

Finds filler words and long pauses in transcript, generates clean segments. Params: `project_id`, `pause_threshold_ms` (default 800), `merge_gap_ms` (default 200), `min_segment_ms` (default 500).

### clipcannon_color_adjust

Color grading (global or per-segment). Params: `project_id`, `edit_id`, `brightness` (-1 to 1), `contrast` (0-3), `saturation` (0-3), `gamma` (0.1-10), `hue_shift` (-180 to 180), optional `segment_id`.

### clipcannon_add_motion

Motion effect on a segment. Params: `project_id`, `edit_id`, `segment_id`, `effect` (zoom_in/out, pan_left/right/up/down, ken_burns), `start_scale`/`end_scale` (0.5-3.0), `easing` (linear/ease_in/ease_out/ease_in_out).

### clipcannon_add_overlay

Visual overlay. Params: `project_id`, `edit_id`, `overlay_type` (lower_third/title_card/logo/watermark/cta), `text`, `subtitle`, `position`, `start_ms`, `end_ms`, `opacity`, `font_size`, `text_color`, `bg_color`, `bg_opacity`, `animation` (none/fade_in/fade_out/slide_up/slide_down), `animation_duration_ms`.

### clipcannon_extract_subject

AI background removal via rembg. Params: `project_id`, `model` (u2net/u2net_human_seg/isnet-general-use).

### clipcannon_replace_background

Replace video background (requires extract_subject first). Params: `project_id`, `edit_id`, `background_type` (blur/color), `background_value`.

### clipcannon_remove_region

Remove rectangular region via FFmpeg delogo filter. Params: `project_id`, `edit_id`, `x`, `y`, `width`, `height`, `description`.

---

## Rendering Tools (11)

### clipcannon_render

Renders edit to platform-optimized video. 2 credits. Params: `project_id`, `edit_id`.

### clipcannon_render_status

Check render status. Params: `project_id`, `render_id`.

### clipcannon_render_batch

Render multiple edits (max 3 parallel). 2 credits/edit. Params: `project_id`, `edit_ids[]`.

### clipcannon_get_editing_context

All editing data in one call: transcript, ranked highlights, silence gaps, pacing, scene boundaries. Use FIRST before creating edits. Params: `project_id`.

### clipcannon_analyze_frame

Detect content regions and webcam PIP overlay in a frame. ~125ms, no credits. Params: `project_id`, `timestamp_ms`.

### clipcannon_preview_clip

Short 2-5s 540p preview. No credits. Params: `project_id`, `start_ms`, `duration_ms` (max 5000, default 3000).

### clipcannon_inspect_render

Inspect rendered output: extract frames at 5 timestamps (0/25/50/75/100%), probe metadata, quality checks. Params: `project_id`, `render_id`.

### clipcannon_preview_layout

Single JPEG frame showing canvas layout. ~300ms, no credits. Params: `project_id`, `timestamp_ms`, `canvas_width/height`, `background_color`, `regions[]`.

### clipcannon_measure_layout

Face detection + precise canvas region computation for layouts A-D. Returns ready-to-use regions for create_edit. Params: `project_id`, `timestamp_ms`, `layout` (A=30/70, B=40/60, C=PIP, D=full-face).

### clipcannon_get_storyboard

Contact sheet of all video frames at 2fps with timestamp labels. Each row = 10s. Returns inline image (~9K tokens) + full transcript. Params: `project_id`, optional `start_s`/`end_s` for 5s window.

### clipcannon_get_scene_map

Complete scene map: scene boundaries, face positions, webcam/content regions, pre-computed canvas regions for layouts A/B/C/D, per-scene transcript, layout recommendations. Zero manual measurement needed. Requires ingest. Params: `project_id`.

---

## Audio Tools (4)

### clipcannon_generate_music

AI music via ACE-Step v1.5 diffusion. Params: `project_id`, `edit_id`, `prompt`, `duration_s` (max 300), `seed`, `volume_db` (default -18).

### clipcannon_compose_midi

MIDI from presets, rendered to WAV via FluidSynth. Params: `project_id`, `edit_id`, `preset` (ambient_pad/upbeat_pop/corporate/dramatic/minimal_piano/intro_jingle), `duration_s` (max 600), `tempo_bpm`, `key`.

### clipcannon_generate_sfx

Programmatic DSP sound effects. Params: `project_id`, `edit_id`, `sfx_type` (whoosh/riser/downer/impact/chime/tick/bass_drop/shimmer/stinger), `duration_ms` (default 500), `params`.

### clipcannon_audio_cleanup

Source audio cleanup. Params: `project_id`, `edit_id`, `operations[]` (noise_reduction/normalize/silence_trim/eq_adjust).
