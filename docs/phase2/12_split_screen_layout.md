# Split-Screen & PIP Layouts for Vertical Video

## Problem

When converting 16:9 landscape video (screen recordings, tutorials, demos) to 9:16 vertical, a naive center crop only shows the middle of the frame. This cuts off:
- Screen content being demonstrated
- The speaker (if not centered)
- Any on-screen UI, code, slides, or demonstrations

This is the most common complaint from creators who share their screen while talking.

## Solution: Three Layout Modes

ClipCannon now supports three layout modes for vertical video, selectable via the EDL `crop.layout` field:

### 1. `crop` (default) -- Single Face-Centered Crop
- Standard behavior: crop a vertical slice from the landscape frame
- Centers on the speaker's face using face detection
- Best for: talking-head content, podcasts, interviews

### 2. `split_screen` -- Stacked Speaker + Screen Content
- Splits the output into two regions stacked vertically
- Speaker region (top): cropped from the webcam/face area
- Screen content region (bottom): cropped from the screen share area
- Configurable split ratio (default 35% speaker / 65% screen)
- Optional separator bar between regions
- Best for: tutorials, demos, screen recordings, coding streams

### 3. `pip` -- Picture-in-Picture
- Full-screen shows the screen content
- Small speaker overlay in a corner
- Best for: when screen content needs maximum real estate

## EDL Configuration

### Split-Screen Example
```json
{
  "crop": {
    "mode": "auto",
    "aspect_ratio": "9:16",
    "layout": "split_screen",
    "split_screen": {
      "speaker_position": "top",
      "split_ratio": 0.35,
      "separator_px": 4,
      "separator_color": "#FFFFFF",
      "speaker_region": null,
      "screen_region": null
    }
  }
}
```

### PIP Example
```json
{
  "crop": {
    "mode": "auto",
    "aspect_ratio": "9:16",
    "layout": "pip",
    "pip": {
      "pip_size": 0.25,
      "pip_position": "bottom_right",
      "pip_margin_px": 20,
      "pip_border_px": 3,
      "pip_border_color": "#FFFFFF"
    }
  }
}
```

## Auto-Detection

When `speaker_region` and `screen_region` are null, ClipCannon auto-detects:

1. **Face detection** (MediaPipe/InsightFace) locates the speaker
2. **Quadrant analysis** determines if the face is in a corner PIP overlay or a larger region
3. **Screen region** is computed as the complement of the speaker region

### Detection Heuristics
- Face in bottom-right corner with small area (<20% of frame) → PIP overlay in source
- Face in left/right half with large area → split-screen source (side-by-side)
- No face detected → falls back to bottom-right quadrant guess

### Manual Override
For reliable results, set `speaker_region` and `screen_region` manually:
```json
{
  "speaker_region": {"x": 1600, "y": 840, "width": 320, "height": 240},
  "screen_region": {"x": 0, "y": 0, "width": 1600, "height": 1080}
}
```

## FFmpeg Implementation

### Split-Screen Filter Graph
```
[0:v]split=2[forspeaker][forscreen];
[forspeaker]crop=320:240:1600:840,scale=1080:672,setsar=1[speaker];
[forscreen]crop=1600:1080:0:0,scale=1080:1244,setsar=1[screen];
color=c=0xFFFFFF:s=1080x4:d=99999,setsar=1[bar];
[speaker][bar][screen]vstack=inputs=3[stacked]
```

### PIP Filter Graph
```
[0:v]split=2[forbg][forpip];
[forbg]scale=1080:1920,setsar=1[bg];
[forpip]crop=320:240:1600:840,scale=270:202,setsar=1[pip];
[bg][pip]overlay=x=787:y=1695[composed]
```

## Split Ratios

| Ratio | Speaker (top) | Screen (bottom) | Use Case |
|-------|--------------|-----------------|----------|
| 25/75 | 480px | 1436px | Maximum screen readability (code, small text) |
| 35/65 | 672px | 1244px | Default. Good balance for tutorials |
| 40/60 | 768px | 1148px | Speaker presence more important |
| 50/50 | 960px | 956px | Equal weight (webinars) |

## Implementation Files

| File | Changes |
|------|---------|
| `src/clipcannon/editing/edl.py` | Added `LayoutMode`, `SplitScreenSpec`, `PipSpec` models; extended `CropSpec` |
| `src/clipcannon/editing/smart_crop.py` | Added `SplitScreenLayout`, `PipLayout` dataclasses; `detect_speaker_region()`, `compute_screen_region()`, `compute_split_screen_layout()`, `compute_pip_layout()` |
| `src/clipcannon/rendering/ffmpeg_cmd.py` | Added `_build_split_screen_cmd()`, `_build_split_screen_multi_segment()`, `_build_pip_cmd()`; extended `build_ffmpeg_cmd()` to dispatch on layout |

## Status

**Implemented** on 2026-03-21. All 275 existing tests pass with these changes.
