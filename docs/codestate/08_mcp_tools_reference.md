# MCP Tools Reference (51 Tools)

## Tool Dispatch

Source: `src/clipcannon/server.py`, `src/clipcannon/tools/__init__.py`

The MCP server registers `list_tools()` -> `ALL_TOOL_DEFINITIONS` and `call_tool(name, arguments)` -> `TOOL_DISPATCHERS[name]`. Results serialize to JSON `TextContent`; tools returning `_image` also get `ImageContent` (base64).

| Module | Dispatch Function | Count |
|---|---|---|
| `tools/project.py` | `dispatch_project_tool` | 5 |
| `tools/__init__.py` | `dispatch_understanding_tool` | 4 |
| `tools/disk.py` | `dispatch_disk_tool` | 2 |
| `tools/config_tools.py` | `dispatch_config_tool` | 3 |
| `tools/billing_tools.py` | `dispatch_billing_tool` | 4 |
| `tools/editing.py` | `dispatch_editing_tool` | 11 |
| `tools/rendering.py` | `dispatch_rendering_tool` | 8 |
| `tools/audio.py` | `dispatch_audio_tool` | 4 |
| `tools/discovery.py` | `dispatch_discovery_tool` | 4 |
| `tools/voice.py` | `dispatch_voice_tool` | 4 |
| `tools/avatar.py` | `dispatch_avatar_tool` | 1 |
| `tools/generate_video.py` | `dispatch_generate_tool` | 1 |

Helper files: `tools/editing_defs.py`, `tools/editing_helpers.py`, `tools/rendering_defs.py`, `tools/discovery_defs.py`, `tools/voice_defs.py`, `tools/avatar_defs.py`, `tools/generate_defs.py`, `tools/storyboard.py`, `tools/understanding_search.py`, `tools/understanding_visual.py`, `tools/video_probe.py`.

Note: `tools/provenance_tools.py` exports an empty `PROVENANCE_TOOL_DEFINITIONS` list. Provenance is accessed via the dashboard API and direct database queries.

---

## Project Tools (5)

`clipcannon_project_create`, `clipcannon_project_open`, `clipcannon_project_list`, `clipcannon_project_status`, `clipcannon_project_delete`

## Understanding Tools (4)

`clipcannon_ingest`, `clipcannon_get_transcript` (paginated, text/words detail), `clipcannon_get_frame` (returns inline base64 JPEG, supports render_id), `clipcannon_search_content`

## Discovery Tools (4)

`clipcannon_find_best_moments`, `clipcannon_find_cut_points`, `clipcannon_get_narrative_flow`, `clipcannon_find_safe_cuts`

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

Deep-merges `changes` into a draft edit. Auto-saves previous version to edit_versions table. Params: `project_id`, `edit_id`, `changes` (object).

### clipcannon_auto_trim

Finds filler words and long pauses in transcript, generates clean segments. Params: `project_id`, `pause_threshold_ms` (default 800), `merge_gap_ms` (default 200), `min_segment_ms` (default 500).

### clipcannon_color_adjust

Color grading (global or per-segment). Params: `project_id`, `edit_id`, `brightness` (-1 to 1), `contrast` (0-3), `saturation` (0-3), `gamma` (0.1-10), `hue_shift` (-180 to 180), optional `segment_id`.

### clipcannon_add_motion

Motion effect on a segment. Params: `project_id`, `edit_id`, `segment_id`, `effect` (zoom_in/out, pan_left/right/up/down, ken_burns), `start_scale`/`end_scale` (0.5-3.0), `easing` (linear/ease_in/ease_out/ease_in_out).

### clipcannon_add_overlay

Visual overlay. Params: `project_id`, `edit_id`, `overlay_type` (lower_third/title_card/logo/watermark/cta), `text`, `subtitle`, `position`, `start_ms`, `end_ms`, `opacity`, `font_size`, `text_color`, `bg_color`, `bg_opacity`, `animation` (none/fade_in/fade_out/slide_up/slide_down), `animation_duration_ms`.

### clipcannon_edit_history

List version history for an edit. Params: `project_id`, `edit_id`. Returns list of versions with version_number, change_description, created_at.

### clipcannon_revert_edit

Revert to a previous version. Params: `project_id`, `edit_id`, `version_number`. Saves current state as new version before reverting.

### clipcannon_apply_feedback

Apply natural language feedback to an edit. Params: `project_id`, `edit_id`, `feedback` (string). Parses feedback text into EDL changes.

### clipcannon_branch_edit

Fork an edit into a platform-specific variant. Params: `project_id`, `edit_id`, `branch_name`, `target_platform`.

### clipcannon_list_branches

List all branches of an edit. Params: `project_id`, `edit_id`.

---

## Rendering Tools (8)

### clipcannon_render

Renders edit to platform-optimized video. 2 credits. Params: `project_id`, `edit_id`.

### clipcannon_get_editing_context

All editing data in one call: transcript, ranked highlights, silence gaps, pacing, scene boundaries, narrative analysis. Use FIRST before creating edits. Params: `project_id`.

### clipcannon_analyze_frame

Detect content regions and webcam PIP overlay in a frame. ~125ms, no credits. Params: `project_id`, `timestamp_ms`.

### clipcannon_preview_clip

Short 2-5s 540p preview. No credits. Params: `project_id`, `start_ms`, `duration_ms` (max 5000, default 3000).

### clipcannon_inspect_render

Inspect rendered output: extract frames at 5 timestamps (0/25/50/75/100%), probe metadata, quality checks. Params: `project_id`, `render_id`.

### clipcannon_preview_layout

Single JPEG frame showing canvas layout. ~300ms, no credits. Params: `project_id`, `timestamp_ms`, `canvas_width/height`, `background_color`, `regions[]`.

### clipcannon_get_scene_map

Scene map with time-window pagination: scene boundaries, face positions, webcam/content regions, pre-computed canvas regions for layouts A/B/C/D, per-scene transcript, layout recommendations. Params: `project_id`, optional time window and detail parameters.

### clipcannon_preview_segment

Low-quality preview of a specific segment. No credits. Params: `project_id`, `edit_id`, `segment_id`.

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

---

## Discovery Tools (4)

### clipcannon_find_best_moments

Find key moments with purpose-aware scoring. Params: `project_id`, `purpose` (hook/highlight/cta/tutorial_step), `count`, `min_duration_ms`.

### clipcannon_find_cut_points

Find natural edit boundaries with convergence scoring. Params: `project_id`, `start_ms`, `end_ms`, `types` (silence/beat/scene/sentence).

### clipcannon_get_narrative_flow

Analyze narrative coherence of proposed segments. Params: `project_id`, `segments[]` (array of start_ms/end_ms pairs).

### clipcannon_find_safe_cuts

Find audio-safe cut points across entire video. Params: `project_id`.

---

## Voice Tools (4)

### clipcannon_prepare_voice_data

Extract vocal stems, split at silence, match transcript, produce train/val manifests. Params: `project_ids[]`, `speaker_label`, `output_dir`, `min_clip_duration_ms` (default 1000), `max_clip_duration_ms` (default 12000).

### clipcannon_voice_profiles

Manage voice profiles. Params: `action` (list/get/create/delete/update), `name`, `model_path`, `training_status`, `training_hours`, `sample_rate`.

### clipcannon_speak

TTS in cloned voice with iterative verification. Params: `project_id`, `text`, `voice_name`, `speed` (0.5-2.0), `max_attempts` (default 5).

### clipcannon_speak_optimized

SECS-optimized TTS with best-of-N selection. Params: `project_id`, `text`, `voice_name`, `n_candidates` (default 8).

---

## Avatar Tools (1)

### clipcannon_lip_sync

Lip-sync talking-head video via LatentSync 1.6. Params: `project_id`, `audio_path`, `driver_video_path`, `inference_steps` (default 20), `seed`.

---

## Video Generation Tools (1)

### clipcannon_generate_video

End-to-end video from text script: voice synthesis + lip-sync. Params: `script`, `project_id`, `driver_video_path`, `voice_name`, `speed`, `max_voice_attempts`, `lip_sync_steps`, `seed`.
