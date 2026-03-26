# Editing Engine

Source: `src/clipcannon/editing/`

## Architecture

```
MCP Tools (tools/editing.py) -- 11 tools
    |
Helpers (editing_helpers.py) -- validation, spec builders, DB storage
    |
    +-- EDL Models (edl.py)
    +-- Captions (captions.py, caption_render.py)
    +-- Smart Crop (smart_crop.py)
    +-- Metadata (metadata_gen.py)
    +-- Auto Trim (auto_trim.py)
    +-- Motion (motion.py)
    +-- Overlays (overlays.py)
    +-- Subject Extraction (subject_extraction.py)
    +-- Measure Layout (measure_layout.py)
```

---

## 1. EDL Models (`edl.py`)

### Platform Duration Limits

| Platform | Min (s) | Max (s) |
|---|---|---|
| tiktok | 5 | 180 |
| instagram_reels | 5 | 90 |
| youtube_shorts | 5 | 180 |
| youtube_standard | 30 | 600 |
| youtube_4k | 30 | 600 |
| facebook | 5 | 90 |
| linkedin | 10 | 600 |

### Enumerations

- **TransitionType**: fade, crossfade, wipe_left/right/up/down, slide_left/right, dissolve, zoom_in, cut
- **EditStatus**: draft, rendering, rendered, approved, rejected, failed
- **TargetPlatform**: tiktok, instagram_reels, youtube_shorts, youtube_standard, youtube_4k, facebook, linkedin
- **CaptionStyle**: bold_centered, word_highlight, subtitle_bar, karaoke

### Core Models

**EditDecisionList**: `edit_id`, `project_id`, `name`, `created_at`, `status`, `source_sha256`, `target_platform`, `target_profile`, `segments[]`, `captions`, `crop`, `canvas`, `audio`, `metadata`, `render_settings`

**SegmentSpec**: `segment_id`, `source_start_ms`, `source_end_ms`, `output_start_ms`, `speed` (0.25-4.0), `transition_in/out`, `canvas` (per-segment override with regions + zoom). Properties: `source_duration_ms`, `output_duration_ms`.

**CropSpec**: `mode` (auto/manual/none), `aspect_ratio`, `face_tracking`, `layout` (crop/split_screen/pip), `split_screen: SplitScreenSpec`, `pip: PipSpec`

**CanvasSpec**: `enabled`, `canvas_width/height`, `background_color`, `regions[]` (source crop, output placement, z_index, fit_mode, opacity, border)

**MotionSpec**: `effect` (zoom_in/out, pan_left/right/up/down, ken_burns), `start_scale/end_scale` (0.5-3.0), `easing`

**OverlaySpec**: `overlay_type` (lower_third/title_card/logo/watermark/cta), `text`, `subtitle`, `position`, `start_ms/end_ms`, `opacity`, `font_size`, `text_color/bg_color/bg_opacity`, `animation`, `animation_duration_ms`

**ColorSpec**: `brightness` (-1 to 1), `contrast` (0-3), `saturation` (0-3), `gamma` (0.1-10), `hue_shift` (-180 to 180)

**AudioSpec**: `source_audio`, `source_volume_db`, `background_music`, `sound_effects`, `ducking: DuckingSpec`

### Validation

`validate_edl(edl, project_db_path)` checks: source SHA-256 match, segment ordering (non-overlapping), total duration within platform limits, speed range, transition durations.

`compute_total_duration(segments)` accounts for speed changes and transition overlaps.

---

## 2. Captions (`captions.py`)

`chunk_transcript_words(words, max_words=3, min_display_ms=500, max_display_ms=3000)`:
- Breaks at sentence punctuation, commas, and max 3 words/chunk
- Adapts to speech rate: fast (>200 WPM) reduces max_words, slow (<80 WPM) increases
- Merges chunks separated by gaps < 200ms

`remap_timestamps(chunks, segments)` converts source to output timeline (segment offsets + speed).

`fetch_words_for_segments(db_path, project_id, segments)` queries `transcript_words` for segment time ranges.

## 3. Caption Rendering (`caption_render.py`)

`generate_ass_file(chunks, style, resolution_w=1080, resolution_h=1920)` produces ASS files with Script Info, V4+ Styles, Events sections.

Styles: `bold_centered` (white bold center-bottom), `word_highlight` (current word highlighted), `subtitle_bar` (semi-transparent bg), `karaoke` (word-by-word fill).

`generate_drawtext_filters(chunks, style)` generates FFmpeg drawtext as ASS fallback.

---

## 4. Smart Crop (`smart_crop.py`)

**Platform aspect ratios**: tiktok/instagram_reels/youtube_shorts/facebook = 9:16, youtube_standard/youtube_4k = 16:9, linkedin = 1:1.

**Face detection**: `detect_faces(frame_path)` -> MediaPipe primary, InsightFace fallback. Returns faces sorted by area.

**Crop computation**: `compute_crop_region(source_w, source_h, target_aspect, face_position_x=0.5, face_position_y=0.5, safe_area_pct=0.85)` -- centers on face, 85% safe area, clamps to source.

**Fit modes**: cover (fill+crop, default), contain (fit+letterbox), stretch (fill, no aspect ratio).

**Scene-aware**: `get_crop_for_scene(scene_data, ...)` uses `shot_type` and `crop_recommendation` from scene analysis. `safe_for_vertical` -> center on face. `needs_reframe` -> offset to face. `keep_landscape` -> center crop.

**Smoothing**: `smooth_crop_positions(crop_regions, alpha=0.3)` -- EMA across scenes to prevent horizontal jumps.

**Split screen**: `compute_split_screen_layout` -- speaker (bottom) + screen (top) with configurable ratio and separator.

**PIP**: `compute_pip_layout` -- background fills canvas, small speaker overlay at configurable corner with size/margin/border.

---

## 5. Metadata Generation (`metadata_gen.py`)

Platform constraints:

| Platform | Title Max | Desc Max | Hashtags | Tone |
|---|---|---|---|---|
| tiktok | 150 | 2200 | 3-5 | casual |
| instagram_reels | 2200 | 2200 | 5-30 | casual |
| youtube_shorts | 100 | 5000 | 3-5 | seo |
| youtube_standard | 100 | 5000 | 5-15 | seo |
| youtube_4k | 100 | 5000 | 5-15 | seo |
| facebook | 250 | 63206 | 3-5 | casual |
| linkedin | 200 | 3000 | 3-5 | professional |

`generate_metadata(project_id, edit_id, target_platform, db_path, edl_json)`: extracts time range from segments -> fetches topics/highlights/transcript -> generates title (tone prefix) + description (opening/summary/context/CTA) + hashtags + thumbnail timestamp (midpoint of top highlight).

---

## 6. Auto Trim (`auto_trim.py`)

Detects filler words (um, uh, like, basically, literally, you know, I mean, etc.) and silence gaps > threshold. Merges segments < `merge_gap_ms`, drops segments < `min_segment_ms`. Returns segments array for `create_edit`.

## 7. Motion Effects (`motion.py`)

Stores `MotionSpec` in EDL. Effects: zoom_in/out, pan_left/right/up/down, ken_burns. Params: start/end_scale (0.5-3.0), easing (linear/ease_in/ease_out/ease_in_out).

## 8. Visual Overlays (`overlays.py`)

Stores `OverlaySpec` in EDL. Types: lower_third, title_card, logo, watermark, cta. Animations: fade_in/out, slide_up/down, none.

## 9. Subject Extraction (`subject_extraction.py`)

AI background removal via rembg. Models: u2net (general), u2net_human_seg (humans, default), isnet-general-use (general v2). Outputs alpha masks to `{project_dir}/masks/`.

## 10. Layout Measurement (`measure_layout.py`)

Face detection + precise canvas region computation on 1080x1920 canvas:

| Layout | Description | Speaker | Screen |
|---|---|---|---|
| A | 30/70 split | 576px | 1344px |
| B | 40/60 split | 768px | 1152px |
| C | PIP | 240px circle | Full screen |
| D | Full-screen face | Full screen | N/A |

Returns ready-to-use `canvas.regions[]` for `clipcannon_create_edit`.

## 11. Iterative Editing

### Version Control (`edit_versions` table)

Every `modify_edit` call auto-saves the current EDL to the `edit_versions` table before applying changes. `edit_history` retrieves the full version chain. `revert_edit` restores a previous version (saving current state first).

### Branching (`parent_edit_id`, `branch_name` columns)

`branch_edit` creates a new edit linked to the parent via `parent_edit_id`, with a configurable `branch_name` and `target_platform`. `list_branches` returns all edits sharing the same parent.

### Feedback Application

`apply_feedback` parses natural language feedback into structured EDL changes (e.g., "make it shorter" -> trim segments, "cut the intro" -> remove first segment).

### Segment Cache (`segment_cache` table)

Rendered segments are cached by content hash. When an edit is modified but some segments are unchanged, the cache avoids re-rendering those segments.
