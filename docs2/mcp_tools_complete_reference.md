# ClipCannon MCP Tools — Complete Reference (39 Tools)

**Updated:** 2026-03-23
**Source:** `src/clipcannon/server.py`, `src/clipcannon/tools/`

---

## Tool Dispatch Architecture

The MCP server registers `list_tools()` → `ALL_TOOL_DEFINITIONS` and `call_tool(name, arguments)` → `TOOL_DISPATCHERS[name]`. Results serialize to JSON `TextContent`; tools returning images also include `ImageContent` (base64).

| Module | Dispatch Function | Count |
|---|---|---|
| `tools/project.py` | `dispatch_project_tool` | 5 |
| `tools/__init__.py` | `dispatch_understanding_tool` | 5 |
| `tools/disk.py` | `dispatch_disk_tool` | 2 |
| `tools/config_tools.py` | `dispatch_config_tool` | 3 |
| `tools/billing_tools.py` | `dispatch_billing_tool` | 4 |
| `tools/editing.py` | `dispatch_editing_tool` | 6 |
| `tools/rendering.py` | `dispatch_rendering_tool` | 7 |
| `tools/audio.py` | `dispatch_audio_tool` | 4 |
| `tools/discovery.py` | `dispatch_discovery_tool` | 3 |
| **Total** | | **39** |

Provenance functions (`provenance_tools.py`) are now internal-only — not exposed via MCP.

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

## 2. Understanding Tools (5)

### clipcannon_ingest

Orchestrates the full analysis pipeline on a project's source video. Runs probe, VFR normalization, audio extraction, source separation, frame extraction, transcription, visual embedding, OCR, quality assessment, shot type classification, semantic embedding, emotion analysis, speaker diarization, reaction detection, acoustic analysis, profanity detection, chronemic computation, highlight scoring, scene analysis, storyboard generation, and finalization. Costs 10 credits.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID (must have source video) |
| `options` | object | No | Optional pipeline overrides (reserved) |

**Returns:** Pipeline result with per-stage status, timing, and any errors. ~5 min for 1hr video on RTX 5090.

### clipcannon_get_transcript

Returns paginated word-level transcript in 15-minute windows. Includes segment text, speaker labels, word-level timestamps, and confidence scores. Use `start_ms`/`end_ms` to navigate; returns `has_more` and `next_start_ms` for pagination.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `start_ms` | integer | No | Start time filter (default 0) |
| `end_ms` | integer | No | End time filter (default start + 900000) |

**Returns:** Transcript segments with word-level timestamps for the requested window

### clipcannon_get_segment_detail

Master query: returns ALL intelligence from every embedder for a time range. 17 data streams: transcript (segments + words), emotion curve (arousal/valence/energy), speakers, reactions, beats, on-screen text (OCR), text change events (slide transitions), pacing, scene quality, scene map (face/webcam/content/canvas regions), silence gaps, highlights (scored), topics, profanity, music sections. Supports point-query mode via `timestamp_ms` (returns 10s window centered on that timestamp with scene_map entry and canvas regions). Optionally pass `layout` to filter canvas regions.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `start_ms` | integer | No | Start time in ms (not needed with timestamp_ms) |
| `end_ms` | integer | No | End time in ms (not needed with timestamp_ms) |
| `timestamp_ms` | integer | No | Point-query: returns 10s window (ts-5000 to ts+5000) with scene_map and canvas regions |
| `layout` | string | No | Layout name to filter canvas regions (only with timestamp_ms) |

**Returns:** Full-resolution multi-stream data for fine-grained editing decisions

### clipcannon_get_frame

Returns a single video frame as an inline base64 JPEG with all temporal metadata showing what every stream knows about that moment (transcript, speaker, emotion, topic, shot type, quality, pacing, beat, on-screen text, profanity).

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
| `search_type` | string | No | `semantic` (default) or `text` |

**Returns:** Ranked transcript segments with similarity scores, timestamps, and context

---

## 3. Disk Tools (2)

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

## 4. Config Tools (3)

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

## 5. Billing Tools (4)

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

## 6. Editing Tools (6)

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
| `segment_id` | integer | No | Apply to specific segment (omit for global) |

**Returns:** Updated color settings confirmation

### clipcannon_add_motion

Adds a motion effect (zoom, pan, ken burns) to a specific segment. Stores the motion spec in the EDL for rendering.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit ID |
| `segment_id` | integer | Yes | Target segment |
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
| `start_ms` | integer | Yes | Overlay start time |
| `end_ms` | integer | Yes | Overlay end time |
| `opacity` | number | No | 0.0-1.0 |
| `font_size` | integer | No | Font size in pixels |
| `text_color` | string | No | Hex color |
| `bg_color` | string | No | Background hex color |
| `bg_opacity` | number | No | Background opacity |
| `animation` | string | No | `none`, `fade_in`, `fade_out`, `slide_up`, `slide_down` |
| `animation_duration_ms` | integer | No | Animation duration |

**Returns:** Overlay spec confirmation with overlay_id

---

## 7. Rendering Tools (7)

### clipcannon_render

Renders a draft edit to a platform-optimized video file. Executes the full render pipeline: source validation, profile resolution, caption burn-in, crop computation, FFmpeg execution, thumbnail generation, provenance recording, and DB update. Costs 2 credits (refunded on failure).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit ID (must be draft status) |

**Returns:** `render_id`, `output_path`, `thumbnail_path`, `output_sha256`, `file_size_bytes`, `duration_ms`, `render_duration_ms`

### clipcannon_get_editing_context

Returns the enriched data manifest for a project. Includes a catalog of ALL available data (counts, ranges, scores), speaker breakdown (label + speaking_pct), narrative analysis from Qwen3-8B (story_beats, open_loops, chapter_boundaries, narrative_summary), transcript preview (first 500 words), and which tools to use to query each data type. One call gives enough context to plan edits. **Call this FIRST before any editing work.**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |

**Returns:** Ranked highlights, silence gaps, pacing segments, scene boundaries, speaker breakdown, narrative analysis, transcript preview

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

Generates a single JPEG frame showing how a canvas layout will look. Composites all regions onto a canvas using Pillow. ~300ms, no credits.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `timestamp_ms` | integer | Yes | Source frame timestamp |
| `canvas_width` | integer | No | Canvas width (default 1080) |
| `canvas_height` | integer | No | Canvas height (default 1920) |
| `background_color` | string | No | Background hex color |
| `regions` | array | Yes | Region definitions (source crop + output placement) |

**Returns:** Composite JPEG preview image (base64)

### clipcannon_get_scene_map

Returns a paginated scene map with detail control. Summary mode (~40 tokens/scene): id, start/end, layout, has_face, transcript preview. Full mode (~120 tokens/scene): all fields including canvas_regions for a single layout. Default window is 5 minutes from `start_ms`. Use `has_more` + `next_start_ms` to paginate. Requires ingest.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `start_ms` | integer | No | Window start in ms (default 0) |
| `end_ms` | integer | No | Window end in ms (default start + 300000) |
| `detail` | string | No | `summary` (~40 tok/scene) or `full` (~120 tok/scene) |
| `layout` | string | No | Layout to return canvas regions for: `A`, `B`, `C`, `D` (full mode only) |

**Returns:** Array of scenes with face data, region proposals, transcript, and recommended layout per scene

---

## 8. Audio Tools (4)

The audio engine provides three tiers of music/sound generation plus cleanup:

| Tier | Tool | Engine | GPU | Speed | Output |
|---|---|---|---|---|---|
| 1: AI Music | `generate_music` | ACE-Step v1 3.5B (Hybrid LM + DiT) | Yes (4+ GB VRAM) | ~7s for 10s audio | 48kHz stereo WAV |
| 2: MIDI | `compose_midi` | MIDIUtil + FluidSynth | No | <0.1s | MIDI (+ WAV if FluidSynth) |
| 3: DSP SFX | `generate_sfx` | numpy/scipy math | No | <0.1s | 44.1kHz 16-bit WAV |
| Cleanup | `audio_cleanup` | noisereduce + pyloudnorm | No | ~10s | WAV |

### clipcannon_generate_music

Generates original AI background music from a text prompt using the ACE-Step v1 3.5B diffusion model (Apache 2.0 license — all generated audio is commercially usable). Architecture: Hybrid Language Model (Qwen3-based, 0.6B-4B params) + Diffusion Transformer (3.5B params). Model weights are cached locally at `~/.cache/ace-step/checkpoints/` after first download (~7.8GB) and never re-downloaded.

Outputs 48kHz stereo WAV. Automatically selects `cpu_offload` mode on GPUs with less than 8GB VRAM. The generated music is stored as an audio asset linked to the edit.

**Prompt engineering tips:** Include genre, BPM, mood, and instruments for best results. Examples:
- `"upbeat corporate pop, 120 BPM, electronic synths, positive energy"`
- `"gentle ambient pad, 70 BPM, warm piano, atmospheric"`
- `"dramatic cinematic orchestral, 90 BPM, strings and brass, intense"`
- `"lo-fi hip hop beats, 85 BPM, jazzy piano, vinyl crackle, chill"`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit to attach music to |
| `prompt` | string | Yes | Text description of desired music (genre, BPM, mood, instruments) |
| `duration_s` | number | Yes | Duration in seconds (max 300, generates ~1 min per ~7s on RTX 5090) |
| `seed` | integer | No | Random seed for reproducibility (same seed + same prompt = same output) |
| `volume_db` | number | No | Volume in dB (default -18) |

**Returns:** `audio_asset_id`, `file_path`, `duration_ms`, `sample_rate` (48000), `seed`, `model_used` ("ACE-Step-v1-3.5B"), `prompt`

**Performance:** ~7s for 10s of audio on RTX 5090. Scales roughly linearly with duration. Model loads in ~3s on first call, cached in GPU memory for subsequent calls within the same session.

### clipcannon_compose_midi

Composes MIDI from presets with theory-correct chord progressions, renders to WAV via FluidSynth (if installed). Multi-track: chords, melody, optional bass, optional drums (channel 9). No GPU required. Falls back to MIDI-only output if FluidSynth is unavailable.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit to attach music to |
| `preset` | string | Yes | `ambient_pad`, `upbeat_pop`, `corporate`, `dramatic`, `minimal_piano`, `intro_jingle` |
| `duration_s` | number | Yes | Duration in seconds (max 600) |
| `tempo_bpm` | integer | No | Override BPM (uses preset default if omitted) |
| `key` | string | No | Musical key (default from preset) |

**Returns:** `audio_asset_id`, `midi_path`, `duration_ms`, `tempo_bpm`, `key`, `preset`

| Preset | BPM | Key | Drums | Progression | Use Case |
|---|---|---|---|---|---|
| ambient_pad | 70 | C | No | Cmaj7-Am7-Fmaj7-G7 | Background atmosphere |
| upbeat_pop | 128 | C | Yes | C-G-Am-F | Energetic content |
| corporate | 100 | C | No | C-F-Am-G | Professional/business |
| dramatic | 90 | A | Yes | Am-F-C-G | Tension/reveal moments |
| minimal_piano | 80 | C | No | C-G-Am-F | Calm narration |
| intro_jingle | 120 | C | Yes | C-F-G-C | Short branded intros |

### clipcannon_generate_sfx

Generates programmatic DSP sound effects using numpy/scipy. Pure math — no GPU, no models, no downloads. <100ms per effect. Output: 44.1kHz 16-bit WAV. Use these for transitions, emphasis hits, and UI-style accents.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit to attach SFX to |
| `sfx_type` | string | Yes | Effect type (see table below) |
| `duration_ms` | integer | No | Duration (default 500ms) |
| `params` | object | No | Type-specific parameters |

| SFX Type | Algorithm | Typical Use |
|---|---|---|
| `whoosh` | Log chirp 200->8000 Hz + exp decay | Scene transitions, swipes |
| `riser` | Linear chirp 100->4000 Hz + crescendo | Build tension before reveal |
| `downer` | Linear chirp 4000->100 Hz + decrescendo | Deflation, disappointment |
| `impact` | White noise burst + fast decay | Emphasis, scene changes |
| `chime` | 3 harmonic sines (880 Hz) + decay | Notifications, highlights |
| `tick` | 1000 Hz sine + sharp attack/decay | UI-style transitions |
| `bass_drop` | 200->40 Hz sweep + sub-harmonic | Dramatic moments |
| `shimmer` | HP filtered noise + slow attack/decay | Ethereal atmosphere |
| `stinger` | Impact (first half) + riser (second half) | Hard scene transitions |

**Returns:** `audio_asset_id`, `file_path`, `duration_ms`, `sample_rate` (44100), `sfx_type`

### clipcannon_audio_cleanup

Cleans up source audio with selectable operations. Each operation is independently toggleable.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `edit_id` | string | Yes | Edit ID |
| `operations` | array | Yes | Operations to apply (at least one required) |
| `hum_frequency` | integer | No | 50 (EU) or 60 (US) Hz for de_hum (default 50) |

| Operation | Description |
|---|---|
| `noise_reduction` | Gentle spectral gating to remove background noise |
| `de_hum` | Remove 50/60 Hz electrical hum |
| `de_ess` | Reduce sibilance in speech |
| `normalize_loudness` | EBU R128 loudness normalization |

**Returns:** `asset_id`, `file_path`, `duration_ms`, `operations_applied`

---

## 9. Discovery Tools (3)

### clipcannon_find_best_moments

Find the best video segments for a specific purpose. Queries highlights, aligns to natural cut points (silence gaps) with convergence quality scoring (silence_gap, sentence_end, scene_boundary signals). Includes transcript, canvas regions, story_beat (from narrative analysis), and moment_character label (passionate_claim / excited_demo / engaged_explanation / screen_walkthrough / calm_narration). Purpose-aware scoring: `hook` prefers early segments with faces, `cta` prefers late segments, `tutorial_step` prefers text-change events. No credits charged.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `purpose` | string | Yes | `hook`, `highlight`, `cta`, `tutorial_step` |
| `target_duration_s` | integer | No | Target clip duration in seconds (default 30, range 5-180) |
| `count` | integer | No | Number of moments to return (default 5, max 10) |

**Returns:** Ranked moments with score, time range, transcript, canvas regions, story beat, moment character, cut-point quality

### clipcannon_find_cut_points

Find natural edit boundaries near a timestamp with cross-stream convergence scoring. Searches silence gaps, beat hits, scene boundaries, and sentence endings within a configurable range. Returns cut points scored by signal convergence: `perfect` when 3+ signals align (silence + beat + sentence), `excellent` for 2 signals, `good` for single signals. No credits charged.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `around_ms` | integer | Yes | Center timestamp to search around (ms) |
| `search_range_ms` | integer | No | Search window radius in ms (default 5000) |

**Returns:** Cut points with quality label (perfect/excellent/good), converging signal types, and exact timestamps

### clipcannon_get_narrative_flow

Analyze narrative coherence of proposed edit segments BEFORE creating an edit. Takes proposed source time ranges and shows what the speaker says at each segment boundary, what content is being skipped in gaps between segments, and warns about broken promise-payoff patterns. **ALWAYS call this before `create_edit` when using non-contiguous segments.** No credits charged.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | Yes | Project ID |
| `segments` | array | Yes | Proposed segment time ranges: `[{start_ms, end_ms}, ...]` |

**Returns:** Per-segment boundary text, gap analysis, narrative coherence warnings

---

## Credit Costs

| Operation | Credits | Tool |
|---|---|---|
| Full pipeline analysis | 10 | `clipcannon_ingest` |
| Render (per edit) | 2 | `clipcannon_render` |
| Preview clip | 0 | `clipcannon_preview_clip` |
| Preview layout | 0 | `clipcannon_preview_layout` |
| Analyze frame | 0 | `clipcannon_analyze_frame` |
| Discovery tools | 0 | `find_best_moments`, `find_cut_points`, `get_narrative_flow` |
| All other tools | 0 | Read-only or configuration |

Failed renders are automatically refunded.

---

## Consolidated Tools (removed from MCP, internal only)

The following tools were removed from MCP registration during the Phase 2 consolidation. Their implementations remain available for internal use by other tools.

| Former Tool | Reason | Replacement |
|---|---|---|
| `clipcannon_get_vud_summary` | Subsumed | `get_editing_context` returns superset |
| `clipcannon_get_analytics` | Subsumed | `get_segment_detail` returns all streams |
| `clipcannon_list_edits` | Internal | Used by rendering pipeline internally |
| `clipcannon_generate_metadata` | Internal | Used by rendering pipeline internally |
| `clipcannon_render_status` | Internal | Used by render pipeline internally |
| `clipcannon_render_batch` | Internal | Use `render` per-edit instead |
| `clipcannon_measure_layout` | Subsumed | `get_scene_map` returns pre-computed layouts |
| `clipcannon_get_storyboard` | Subsumed | `get_frame` + `get_scene_map` cover same need |
| `clipcannon_extract_subject` | Internal | Background removal runs during render |
| `clipcannon_replace_background` | Internal | Set via `create_edit` canvas config |
| `clipcannon_remove_region` | Internal | Set via `create_edit` EDL removals |
| `clipcannon_provenance_*` (4) | Internal | Provenance recorded automatically by pipeline |
