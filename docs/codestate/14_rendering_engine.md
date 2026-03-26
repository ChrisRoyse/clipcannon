# Rendering Engine

Source: `src/clipcannon/rendering/`

## Pipeline Overview

```
EDL -> Source validation (SHA-256, generation loss check)
    -> Profile resolution (7 profiles)
    -> Caption write (ASS)
    -> Crop computation (face tracking, split-screen, PIP, canvas)
    -> FFmpeg execution (async subprocess)
        - Segment trim + concat, transitions (xfade), speed
        - Per-segment canvas compositing (regions, z-index, fit_mode)
        - Animated zoom (start_scale -> end_scale + easing)
        - Caption burn-in, color grading, blur bg, delogo
        - Crop/scale to target, platform encoding (NVENC or software)
    -> Thumbnail (JPEG), provenance record, DB update
```

---

## 1. RenderEngine (`renderer.py`)

### RenderResult

`render_id`, `success`, `output_path`, `thumbnail_path`, `output_sha256`, `file_size_bytes`, `duration_ms`, `render_duration_ms`, `error_message`, `provenance_record_id`

### render(edl, project_dir, db_path) -> RenderResult

1. `_resolve_source`: verify SHA-256 match, reject `/renders/` sources (generation loss prevention)
2. `_resolve_profile`: lookup encoding profile
3. `_write_captions`: generate ASS subtitle file
4. `_compute_crop`: calculate crop from EDL + scene data
5. `_execute_ffmpeg`: build and run async
6. `_generate_thumb`: JPEG at specified timestamp
7. `_record_provenance`: link rendered file to source
8. `_update_db`: update renders table

---

## 2. FFmpeg Command Building (`ffmpeg_cmd.py`)

### Layout Dispatch

| Priority | Condition | Builder |
|---|---|---|
| 1 | `canvas.enabled` | `_build_canvas_cmd` |
| 2 | `crop.layout == "split_screen"` | `_build_split_screen_cmd` |
| 3 | `crop.layout == "pip"` | `_build_pip_cmd` |
| 4 | Single segment | `_build_single_segment_cmd` |
| 4 | Multiple segments | `_build_multi_segment_cmd` |

**Per-segment canvas**: Each segment can have independent regions with source crop, output placement, z-index, fit_mode (cover/contain/stretch), opacity, border, animated zoom.

**Blur background**: `crop.background_type == "blur"` -> gaussian blur background + composited subject (no black bars).

**Region removal**: `remove_regions` -> FFmpeg `delogo` filters before crop/scale.

**Transitions** (EDL -> FFmpeg xfade):

| EDL | xfade |
|---|---|
| fade/crossfade | fade |
| dissolve | dissolve |
| wipe_left/right | wipeleft/wiperight |
| slide_left/right | slideleft/slideright |
| zoom_in | smoothup |

**Split screen**: Speaker + screen stacked vertically with optional separator.

**PIP**: Background fills canvas, small overlay at specified corner.

**Encoding args**: `build_encoding_args(profile)` -> codec, bitrate, maxrate, bufsize, audio codec/bitrate/sample rate, movflags.

---

## 3. Encoding Profiles (`profiles.py`)

| Profile | Resolution | FPS | Codec | Bitrate | Aspect |
|---|---|---|---|---|---|
| tiktok_vertical | 1080x1920 | 30 | h264_nvenc | 8M | 9:16 |
| instagram_reels | 1080x1920 | 30 | h264_nvenc | 8M | 9:16 |
| youtube_shorts | 1080x1920 | 30 | h264_nvenc | 8M | 9:16 |
| youtube_standard | 1920x1080 | 30 | h264_nvenc | 12M | 16:9 |
| youtube_4k | 3840x2160 | 30 | hevc_nvenc | 35M | 16:9 |
| facebook | 1200x628 | 30 | h264_nvenc | 6M | ~2:1 |
| linkedin | 1200x628 | 30 | h264_nvenc | 6M | ~2:1 |

Software fallback: `h264_nvenc` -> `libx264`, `hevc_nvenc` -> `libx265`.

---

## 4. Thumbnail (`thumbnail.py`)

`generate_thumbnail(source_path, timestamp_ms, output_path, width, height, crop_region=None)`: JPEG at `-q:v 2` (~95% quality) with optional crop.

## 5. Render Inspection (`inspector.py`)

Extracts frames at 5 key timestamps (0/25/50/75/100%), probes metadata via ffprobe, compares against profile spec, runs quality checks, returns inline base64 frames + pass/fail.

## 6. Preview (`preview.py`)

**Preview clip**: 2-5s 540p fast encode. No credits.

**Preview layout**: Single JPEG frame compositing all regions onto 1080x1920 canvas via Pillow. ~300ms.

**Preview segment**: Low-quality preview of a specific segment within an edit. No credits.

## 7. Credits

`clipcannon_render`: 2 credits. Refunded on failure.
