# 13 - Editing Engine

> Current-state documentation of the editing subsystem as implemented in `src/clipcannon/editing/`.

## Architecture Overview

The editing engine uses a declarative Edit Decision List (EDL) model to specify how source video should be transformed into platform-optimized clips. The EDL contains segment definitions, caption configuration, crop/layout specifications, canvas compositing regions, motion effects, visual overlays, color grading, audio mixing parameters, and platform-specific metadata.

```
┌─────────────────────────────────────────────────────────────────┐
│             MCP Tool Layer (tools/editing.py)                    │
│  [create_edit] [modify_edit] [list] [gen_metadata]              │
│  [auto_trim] [color_adjust] [add_motion] [add_overlay]         │
│  [extract_subject] [replace_background] [remove_region]        │
└──────────────────┬──────────────────────────────────────────────┘
                   │
┌──────────────────┴──────────────────────────────────────────────┐
│       Helper & Builder Layer (editing_helpers.py)                │
│  [validation] [spec builders] [DB storage]                      │
└──────────────────┬──────────────────────────────────────────────┘
                   │
    ┌──────────────┼──────────────┬─────────────┬─────────────┐
    │              │              │             │             │
    EDL Models     Captions       Smart Crop    Metadata      New Modules
    (edl.py)    (captions.py)  (smart_crop.py) (metadata_gen.py)
                     │                                        │
              Caption Rendering                    ┌──────────┼──────────┐
           (caption_render.py)                     │          │          │
                                              auto_trim  motion   overlays
                                              measure_layout  subject_extraction
```

---

## 1. EDL Models and Validation

**Source:** `src/clipcannon/editing/edl.py`

### Platform Duration Limits

| Platform | Min (s) | Max (s) |
|----------|---------|---------|
| tiktok | 5 | 180 |
| instagram_reels | 5 | 90 |
| youtube_shorts | 5 | 180 |
| youtube_standard | 30 | 600 |
| youtube_4k | 30 | 600 |
| facebook | 5 | 90 |
| linkedin | 10 | 600 |

### Type Enumerations

| Type | Values |
|------|--------|
| `TransitionType` | fade, crossfade, wipe_left, wipe_right, wipe_up, wipe_down, slide_left, slide_right, dissolve, zoom_in, cut |
| `EditStatus` | draft, rendering, rendered, approved, rejected, failed |
| `TargetPlatform` | tiktok, instagram_reels, youtube_shorts, youtube_standard, youtube_4k, facebook, linkedin |
| `CaptionStyle` | bold_centered, word_highlight, subtitle_bar, karaoke |

### Core Models

**`EditDecisionList`** -- top-level model containing:
- `edit_id`, `project_id`, `name`, `created_at`, `status`
- `source_sha256` -- verified against project source to prevent stale edits
- `target_platform`, `target_profile`
- `segments: list[SegmentSpec]` -- ordered source segments (each can have per-segment canvas override and zoom)
- `captions: CaptionSpec` -- caption configuration and chunks
- `crop: CropSpec` -- cropping/layout configuration
- `canvas: CanvasSpec` -- free-form compositing (advanced)
- `audio: AudioSpec` -- audio mixing configuration
- `metadata: MetadataSpec` -- title, description, hashtags
- `render_settings: RenderSettingsSpec` -- encoding preferences

**`SegmentSpec`** -- defines one segment of the edit:
- `segment_id`, `source_start_ms`, `source_end_ms`, `output_start_ms`
- `speed` (0.25-4.0, default 1.0)
- `transition_in`, `transition_out` (optional `TransitionSpec`)
- `canvas` -- optional per-segment canvas override with regions and zoom
- Properties: `source_duration_ms`, `output_duration_ms`

**`CropSpec`** -- cropping and layout mode:
- `mode`: auto (content-aware), manual, none
- `aspect_ratio`: target aspect ratio string
- `face_tracking`: enable face-following crop
- `layout`: crop (default), split_screen, pip
- `split_screen: SplitScreenSpec` -- speaker/screen split configuration
- `pip: PipSpec` -- picture-in-picture configuration

**`CanvasSpec`** -- free-form compositing:
- `enabled`, `canvas_width`, `canvas_height`, `background_color`
- `regions: list[CanvasRegion]` -- each with source crop, output placement, z_index, fit_mode, opacity, border

**`MotionSpec`** -- motion effects:
- `effect`: zoom_in, zoom_out, pan_left, pan_right, pan_up, pan_down, ken_burns
- `start_scale`, `end_scale`: zoom range (0.5-3.0)
- `easing`: linear, ease_in, ease_out, ease_in_out

**`OverlaySpec`** -- visual overlays:
- `overlay_type`: lower_third, title_card, logo, watermark, cta
- `text`, `subtitle`, `position`, `start_ms`, `end_ms`
- `opacity`, `font_size`, `text_color`, `bg_color`, `bg_opacity`
- `animation`, `animation_duration_ms`

**`ColorSpec`** -- color grading:
- `brightness` (-1 to 1), `contrast` (0-3), `saturation` (0-3)
- `gamma` (0.1-10), `hue_shift` (-180 to 180)

**`AudioSpec`** -- audio mixing parameters:
- `source_audio`, `source_volume_db`
- `background_music`, `sound_effects`, `ducking: DuckingSpec`

### Validation

`validate_edl(edl, project_db_path) -> list[str]` checks:
- Source SHA-256 matches project database
- Segments ordered by `output_start_ms` and non-overlapping
- Total duration within platform limits
- Speed range (0.25-4.0)
- Transition durations within segment bounds

`compute_total_duration(segments) -> int` calculates total output duration accounting for speed changes and transition overlaps.

---

## 2. Caption Generation

**Source:** `src/clipcannon/editing/captions.py`

### Chunking Rules

`chunk_transcript_words(words, max_words=3, min_display_ms=500, max_display_ms=3000)`:

1. Breaks at sentence punctuation (`.`, `?`, `!`, `;`, `:`)
2. Breaks at commas
3. Enforces max 3 words per chunk
4. Enforces minimum 500ms display duration
5. Splits chunks exceeding 3000ms
6. Adapts to speech rate: fast speech (>200 WPM) reduces max_words, slow speech (<80 WPM) increases
7. Merges chunks separated by gaps < 200ms

### Timestamp Remapping

`remap_timestamps(chunks, segments)` converts source-timeline timestamps to output-timeline timestamps, accounting for segment offsets and speed changes.

### Word Fetching

`fetch_words_for_segments(db_path, project_id, segments)` queries `transcript_words` table for words overlapping any segment's time range.

---

## 3. Caption Rendering

**Source:** `src/clipcannon/editing/caption_render.py`

### ASS Subtitle Generation

`generate_ass_file(chunks, style, resolution_w=1080, resolution_h=1920)` produces complete ASS subtitle files with:
- `[Script Info]` section with resolution metadata
- `[V4+ Styles]` section with font, color, alignment
- `[Events]` section with timed dialogue lines

### Preset Styles

| Style | Description |
|-------|-------------|
| `bold_centered` | White bold text, center-bottom aligned |
| `word_highlight` | Current word highlighted, others dimmed |
| `subtitle_bar` | Text on semi-transparent background bar |
| `karaoke` | Sequential word-by-word color fill |

### FFmpeg Drawtext Fallback

`generate_drawtext_filters(chunks, style)` generates FFmpeg drawtext filter strings as a fallback when ASS rendering is unavailable.

---

## 4. Smart Cropping

**Source:** `src/clipcannon/editing/smart_crop.py`

### Platform Aspect Ratios

| Platform | Aspect Ratio |
|----------|-------------|
| tiktok, instagram_reels, youtube_shorts, facebook | 9:16 |
| youtube_standard, youtube_4k | 16:9 |
| linkedin | 1:1 |

### Face Detection

`detect_faces(frame_path) -> list[FaceDetection]`:
- **Primary**: MediaPipe Face Detection
- **Fallback**: InsightFace
- Returns faces sorted by area (largest first)

### Crop Computation

`compute_crop_region(source_w, source_h, target_aspect, face_position_x=0.5, face_position_y=0.5, safe_area_pct=0.85)`:
- Calculates crop window centered on face position
- Enforces 85% safe area (face kept within 85% of crop bounds)
- Clamps crop to source dimensions

### Fit Mode Scaling

The smart crop module supports `fit_mode` options for canvas compositing regions:
- `cover`: fill the output region, cropping excess (default)
- `contain`: fit entirely within the output region, letterboxing if needed
- `stretch`: stretch to fill without maintaining aspect ratio

### Scene-Aware Cropping

`get_crop_for_scene(scene_data, source_w, source_h, target_aspect)`:
- Uses `shot_type` and `crop_recommendation` from scene analysis
- `safe_for_vertical` shot types: center crop on face
- `needs_reframe`: offset crop toward face position
- `keep_landscape`: center crop (no face tracking)

### Position Smoothing

`smooth_crop_positions(crop_regions, alpha=0.3)`:
- EMA (Exponential Moving Average) smoothing of crop X positions across scenes
- Prevents jarring horizontal jumps in vertical crops

### Layout Modes

**Split Screen** (`compute_split_screen_layout`):
- Detects speaker region (webcam/face area) and screen region (content area)
- Configurable split ratio and separator
- Speaker positioned at bottom, screen at top (for vertical output)

**Picture-in-Picture** (`compute_pip_layout`):
- Background fills main content area
- Small PIP overlay shows speaker face
- Configurable position (bottom-right, bottom-left, top-right, top-left), size, margin, border

---

## 5. Metadata Generation

**Source:** `src/clipcannon/editing/metadata_gen.py`

### Platform-Specific Constraints

| Platform | Title Max | Desc Max | Hashtags | Tone |
|----------|-----------|----------|----------|------|
| tiktok | 150 | 2200 | 3-5 | casual |
| instagram_reels | 2200 | 2200 | 5-30 | casual |
| youtube_shorts | 100 | 5000 | 3-5 | seo |
| youtube_standard | 100 | 5000 | 5-15 | seo |
| youtube_4k | 100 | 5000 | 5-15 | seo |
| facebook | 250 | 63206 | 3-5 | casual |
| linkedin | 200 | 3000 | 3-5 | professional |

### Generation Flow

`generate_metadata(project_id, edit_id, target_platform, db_path, edl_json) -> MetadataResult`:

1. Extracts time range from EDL segments
2. Fetches topics, highlights, and transcript for that range
3. Extracts keywords from topic labels and highlight reasons
4. Generates title with tone-appropriate prefix (casual/professional/SEO)
5. Generates multi-paragraph description (opening, summary, context, CTA)
6. Builds hashtag list from keywords (respecting platform limits)
7. Selects thumbnail timestamp at midpoint of highest-scoring highlight

---

## 6. Auto Trim

**Source:** `src/clipcannon/editing/auto_trim.py`

Analyzes transcript to automatically remove filler words and long pauses, producing clean segments ready for `clipcannon_create_edit`.

### Filler Word Detection

Detects and removes: um, uh, like, basically, literally, you know, I mean, sort of, kind of, right, okay, and similar filler patterns.

### Pause Detection

Identifies silence gaps exceeding a configurable threshold (default 800ms) and generates segment boundaries that skip them.

### Segment Optimization

- Merges segments separated by less than `merge_gap_ms` (default 200ms)
- Drops segments shorter than `min_segment_ms` (default 500ms)
- Returns segments array compatible with `create_edit`

---

## 7. Motion Effects

**Source:** `src/clipcannon/editing/motion.py`

Applies motion effects to edit segments by storing `MotionSpec` in the EDL.

### Supported Effects

| Effect | Description |
|--------|-------------|
| `zoom_in` | Gradually zoom into the frame |
| `zoom_out` | Gradually zoom out from the frame |
| `pan_left` | Horizontal pan left across the frame |
| `pan_right` | Horizontal pan right across the frame |
| `pan_up` | Vertical pan upward |
| `pan_down` | Vertical pan downward |
| `ken_burns` | Combined zoom with diagonal pan for cinematic movement |

### Parameters

- `start_scale` / `end_scale`: zoom range (0.5-3.0)
- `easing`: linear, ease_in, ease_out, ease_in_out

---

## 8. Visual Overlays

**Source:** `src/clipcannon/editing/overlays.py`

Adds visual overlays to edits by storing `OverlaySpec` in the EDL.

### Overlay Types

| Type | Description |
|------|-------------|
| `lower_third` | Speaker name and title bar at bottom |
| `title_card` | Full-screen text overlay |
| `logo` | Logo image overlay |
| `watermark` | Semi-transparent watermark |
| `cta` | Call-to-action button/text |

### Animation Options

fade_in, fade_out, slide_up, slide_down, none

---

## 9. Subject Extraction

**Source:** `src/clipcannon/editing/subject_extraction.py`

AI-powered background removal using rembg.

### Models

| Model | Best For |
|-------|----------|
| `u2net` | General subjects |
| `u2net_human_seg` | Human subjects (default) |
| `isnet-general-use` | General subjects v2 |

### Output

Generates alpha mask frames in `{project_dir}/masks/` for use with background replacement.

---

## 10. Layout Measurement

**Source:** `src/clipcannon/editing/measure_layout.py`

Computes mathematically precise canvas regions by running face detection on a frame and calculating source crop + output placement coordinates for 4 layout types on a 1080x1920 canvas.

### Layout Types

| Layout | Description | Speaker Height | Screen Height |
|--------|-------------|---------------|--------------|
| A | 30/70 split | 576px | 1344px |
| B | 40/60 split | 768px | 1152px |
| C | PIP | 240px circle | Full screen |
| D | Full-screen face | Full screen | N/A |

Returns ready-to-use `canvas.regions[]` for `clipcannon_create_edit`.
