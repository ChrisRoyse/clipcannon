# 14 - Rendering Engine

> Current-state documentation of the rendering subsystem as implemented in `src/clipcannon/rendering/`.

## Architecture Overview

The rendering engine converts Edit Decision Lists (EDLs) into platform-ready video files through an async FFmpeg-based pipeline. The process involves: source validation (SHA-256 verification), caption rendering (ASS format), smart crop computation, FFmpeg filter graph construction with per-segment canvas compositing and animated zoom, concurrent execution, thumbnail generation, and provenance recording.

```
EDL Input
    │
    ├── Source validation (SHA-256 check, generation loss prevention)
    ├── Profile resolution (7 platform profiles)
    ├── Caption write (ASS subtitle file)
    ├── Crop computation (face tracking, split-screen, PIP, canvas)
    │
    ▼
FFmpeg Execution (async subprocess)
    │
    ├── Segment trimming + concatenation
    ├── Transition effects (xfade)
    ├── Speed adjustment
    ├── Per-segment canvas compositing (regions, z-index, fit_mode)
    ├── Animated zoom (start_scale -> end_scale with easing)
    ├── Caption burn-in (ASS subtitles)
    ├── Color grading (brightness, contrast, saturation, gamma, hue)
    ├── Blur background / region removal (delogo)
    ├── Crop/scale to target resolution
    ├── Platform-specific encoding (NVENC or software fallback)
    │
    ▼
Output
    ├── Rendered video file
    ├── JPEG thumbnail
    ├── Provenance record
    └── Database update (renders table)
```

---

## 1. RenderEngine

**Source:** `src/clipcannon/rendering/renderer.py`

### RenderResult Dataclass

| Field | Type | Description |
|-------|------|-------------|
| `render_id` | `str` | Unique render identifier |
| `success` | `bool` | Whether render completed successfully |
| `output_path` | `str \| None` | Path to rendered video |
| `thumbnail_path` | `str \| None` | Path to thumbnail image |
| `output_sha256` | `str \| None` | SHA-256 of rendered file |
| `file_size_bytes` | `int` | Rendered file size |
| `duration_ms` | `int` | Output video duration |
| `render_duration_ms` | `int` | Wall-clock render time |
| `error_message` | `str \| None` | Error description if failed |
| `provenance_record_id` | `str \| None` | Provenance record ID |

### Render Pipeline

`async RenderEngine.render(edl, project_dir, db_path) -> RenderResult`:

1. **Source validation** (`_resolve_source`): Verifies source SHA-256 matches EDL. Rejects renders from `/renders/` directories to prevent generation loss.
2. **Profile resolution** (`_resolve_profile`): Looks up encoding profile by name.
3. **Caption write** (`_write_captions`): Generates ASS subtitle file from caption chunks.
4. **Crop computation** (`_compute_crop`): Calculates crop region from EDL spec and scene data.
5. **FFmpeg execution** (`_execute_ffmpeg`): Builds and runs FFmpeg command asynchronously.
6. **Thumbnail generation** (`_generate_thumb`): Extracts JPEG frame at specified timestamp.
7. **Provenance recording** (`_record_provenance`): Links rendered file to source in provenance chain.
8. **Database update** (`_update_db`): Updates renders table with completion metadata.

---

## 2. FFmpeg Command Building

**Source:** `src/clipcannon/rendering/ffmpeg_cmd.py`

### Layout Dispatch

`build_ffmpeg_cmd(edl, profile, captions_path, crop_region)` dispatches to the appropriate builder:

| Priority | Layout | Builder |
|----------|--------|---------|
| 1 | Canvas (free-form compositing) | `_build_canvas_cmd` |
| 2 | Split screen (speaker + content) | `_build_split_screen_cmd` |
| 3 | PIP (picture-in-picture) | `_build_pip_cmd` |
| 4 | Standard (single source, crop) | `_build_single_segment_cmd` or `_build_multi_segment_cmd` |

### Per-Segment Canvas Compositing

Each segment in the EDL can have its own `canvas` override with independent regions, enabling different layouts for different scenes. The canvas builder processes each segment's regions with:
- Independent source crop per region
- Output placement with z-index ordering
- `fit_mode` scaling (cover, contain, stretch)
- Opacity and border options
- Animated zoom (interpolates between `start_scale` and `end_scale` using the specified easing function)

### Blur Background

When `crop.background_type == "blur"`, the renderer applies gaussian blur to the background and composites the cropped subject on top, filling the full canvas without black bars.

### Region Removal

When `remove_regions` are specified in the EDL, FFmpeg `delogo` filters are applied before crop/scale to interpolate over the specified rectangular areas (used for removing browser chrome, taskbars, watermarks).

### Single Segment

`_build_single_segment_cmd`: Trim, crop, scale, speed adjust, subtitles, encoding for a single contiguous source segment.

### Multi-Segment with Transitions

`_build_multi_segment_cmd`: Concatenates multiple segments with xfade transitions between them.

**Transition mapping** (FFmpeg xfade filter names):

| EDL Transition | FFmpeg xfade |
|----------------|-------------|
| fade | fade |
| crossfade | fade |
| dissolve | dissolve |
| wipe_left | wipeleft |
| wipe_right | wiperight |
| slide_left | slideleft |
| slide_right | slideright |
| zoom_in | smoothup |

### Split Screen

`_build_split_screen_cmd`: Two source crops (speaker region + screen region) stacked vertically with optional separator bar. Used when `crop.layout == "split_screen"`.

### Picture-in-Picture

`_build_pip_cmd`: Background crop fills output canvas, small PIP overlay positioned at specified corner. Used when `crop.layout == "pip"`.

### Canvas Compositing

`_build_canvas_cmd`: Free-form compositing with arbitrary z-indexed regions, each with independent source crop, output position, opacity, fit_mode, and border. Used when `canvas.enabled == True`.

### Encoding Arguments

`build_encoding_args(profile)` generates codec, bitrate, and audio parameters:
- Video: codec, bitrate, maxrate, bufsize
- Audio: codec, bitrate, sample rate
- Container: movflags for progressive download

---

## 3. Encoding Profiles

**Source:** `src/clipcannon/rendering/profiles.py`

### Predefined Profiles

| Profile | Resolution | FPS | Video Codec | Bitrate | Aspect |
|---------|-----------|-----|------------|---------|--------|
| `tiktok_vertical` | 1080x1920 | 30 | h264_nvenc | 8M | 9:16 |
| `instagram_reels` | 1080x1920 | 30 | h264_nvenc | 8M | 9:16 |
| `youtube_shorts` | 1080x1920 | 30 | h264_nvenc | 8M | 9:16 |
| `youtube_standard` | 1920x1080 | 30 | h264_nvenc | 12M | 16:9 |
| `youtube_4k` | 3840x2160 | 30 | hevc_nvenc | 35M | 16:9 |
| `facebook` | 1200x628 | 30 | h264_nvenc | 6M | ~2:1 |
| `linkedin` | 1200x628 | 30 | h264_nvenc | 6M | ~2:1 |

### Software Fallback

`get_software_fallback(profile)` replaces GPU codecs with CPU equivalents:
- `h264_nvenc` -> `libx264`
- `hevc_nvenc` -> `libx265`

---

## 4. Batch Rendering

**Source:** `src/clipcannon/rendering/batch.py`

`async render_batch(edl_list, project_dir, db_path, config, max_concurrent=3) -> list[RenderResult]`

- Uses `asyncio.Semaphore(max_concurrent)` to cap concurrent FFmpeg processes (default 3).
- Returns results in same order as input EDL list.
- Individual failures do not stop the batch; all edits are attempted.

---

## 5. Thumbnail Generation

**Source:** `src/clipcannon/rendering/thumbnail.py`

`async generate_thumbnail(source_path, timestamp_ms, output_path, width, height, crop_region=None) -> Path`

- Extracts single JPEG frame at specified timestamp via FFmpeg.
- Optional crop filter applied before scaling.
- Quality: `-q:v 2` (~95% JPEG quality).

---

## 6. Render Inspection

**Source:** `src/clipcannon/rendering/inspector.py`

Inspects rendered video output by:
1. Extracting frames at 5 key timestamps (start, 25%, 50%, 75%, end)
2. Probing output metadata via ffprobe (resolution, duration, codec, bitrate)
3. Comparing output metadata against the encoding profile spec
4. Running quality checks (resolution match, duration match, codec match)
5. Returning inline base64 frame images plus pass/fail results

---

## 7. Preview Generation

**Source:** `src/clipcannon/rendering/preview.py`

Two preview modes:

### Preview Clip
Renders a short (2-5 second) 540p preview at fast encoding settings. No credits charged. Used for quick validation before committing to a full render.

### Preview Layout
Generates a single JPEG frame showing a canvas layout at a specific timestamp. Composites all regions onto a 1080x1920 canvas using Pillow. Returns in ~300ms. Used to validate region coordinates before rendering.

---

## 8. Credit Charging

All render operations charge 2 credits via the `LicenseClient`:

- `clipcannon_render`: 2 credits for single render
- `clipcannon_render_batch`: 2 credits per edit in the batch

On render failure, credits are refunded. The render tool handles the charge/refund lifecycle within the dispatch function.

---

## 9. Generation Loss Prevention

The renderer rejects source files located in `/renders/` directories. This prevents re-rendering from already-rendered output, which would cause cascading quality degradation. The check is performed in `_resolve_source()` before any FFmpeg execution.
