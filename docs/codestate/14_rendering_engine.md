# 14 - Rendering Engine

> Current-state documentation of the Phase 2 rendering subsystem as implemented in `src/clipcannon/rendering/`.

## Architecture Overview

The rendering engine converts Edit Decision Lists (EDLs) into platform-ready video files through an async FFmpeg-based pipeline. The process involves: source validation (SHA-256 verification), caption rendering (ASS format), smart crop computation, FFmpeg filter graph construction, concurrent execution, thumbnail generation, and provenance recording.

```
EDL Input
    │
    ├── Source validation (SHA-256 check, generation loss prevention)
    ├── Profile resolution (7 platform profiles)
    ├── Caption write (ASS subtitle file)
    ├── Crop computation (face tracking, split-screen, PIP)
    │
    ▼
FFmpeg Execution (async subprocess)
    │
    ├── Segment trimming + concatenation
    ├── Transition effects (xfade)
    ├── Speed adjustment
    ├── Caption burn-in (ASS subtitles)
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

`_build_canvas_cmd`: Free-form compositing with arbitrary z-indexed regions, each with independent source crop, output position, opacity, and border. Used when `canvas.enabled == True`.

### Encoding Arguments

`build_encoding_args(profile)` generates codec, bitrate, and audio parameters:
- Video: codec, bitrate, maxrate, bufsize
- Audio: codec, bitrate, sample rate
- Container: movflags for progressive download

---

## 3. Encoding Profiles

**Source:** `src/clipcannon/rendering/profiles.py`

### EncodingProfile Dataclass

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Profile identifier |
| `width` | `int` | Output width in pixels |
| `height` | `int` | Output height in pixels |
| `aspect_ratio` | `str` | Target aspect ratio |
| `fps` | `int` | Output frame rate |
| `video_codec` | `str` | Video codec (e.g., `h264_nvenc`) |
| `video_bitrate` | `str` | Bitrate (e.g., `"8M"`) |
| `max_bitrate` | `str` | Max bitrate for VBR |
| `bufsize` | `str` | Rate control buffer size |
| `audio_codec` | `str` | Audio codec |
| `audio_bitrate` | `str` | Audio bitrate |
| `audio_sample_rate` | `int` | Audio sample rate |
| `max_duration_ms` | `int` | Maximum allowed duration |
| `min_duration_ms` | `int` | Minimum allowed duration |
| `movflags` | `str` | Container flags |

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

Used when NVENC is unavailable or fails.

---

## 4. Batch Rendering

**Source:** `src/clipcannon/rendering/batch.py`

`async render_batch(edl_list, project_dir, db_path, config, max_concurrent=3) -> list[RenderResult]`

- Uses `asyncio.Semaphore(max_concurrent)` to cap concurrent FFmpeg processes (default 3).
- Returns results in same order as input EDL list.
- Individual failures do not stop the batch; all edits are attempted.
- Logs aggregate success/failure counts.

---

## 5. Thumbnail Generation

**Source:** `src/clipcannon/rendering/thumbnail.py`

`async generate_thumbnail(source_path, timestamp_ms, output_path, width, height, crop_region=None) -> Path`

- Extracts single JPEG frame at specified timestamp via FFmpeg.
- Optional crop filter applied before scaling.
- Quality: `-q:v 2` (~95% JPEG quality).
- Returns path to generated thumbnail file.

---

## 6. Credit Charging

All render operations charge 2 credits via the `LicenseClient`:

- `clipcannon_render`: 2 credits for single render
- `clipcannon_render_batch`: 2 credits per edit in the batch

On render failure, credits are refunded. The render tool handles the charge/refund lifecycle within the dispatch function.

---

## 7. Generation Loss Prevention

The renderer rejects source files located in `/renders/` directories. This prevents re-rendering from already-rendered output, which would cause cascading quality degradation. The check is performed in `_resolve_source()` before any FFmpeg execution.
