# Per-Segment Canvas/Layout Overrides

## Problem

The current `CanvasSpec` on the EDL is a single, global compositing configuration. Every segment in the clip gets the same layout: same regions, same crop coordinates, same positions. This means the AI cannot express:

- "Segment 1 shows the speaker full-screen, segment 2 shows a split layout, segment 3 zooms into coordinates (300,200,800,600)"
- Animated zoom: gradually narrowing a crop over a segment's duration
- Mixed layouts within a single clip (the most common real-world editing pattern)

The existing `_build_canvas_cmd` only reads `segments[0]` and ignores the rest. The existing `_build_multi_segment_cmd` applies the same `crop_region` to every segment. There is no mechanism for per-segment visual differentiation.

## Solution: Per-Segment Canvas Override

Each `SegmentSpec` gains an optional `canvas` field. When present, it overrides the top-level `CanvasSpec` for that segment only. When absent, the segment falls back to the top-level canvas, then to crop, then to plain scale.

An additional `zoom` field on the segment provides a shorthand for the most common animation: a crop that linearly interpolates from the full source region to a target sub-region over the segment's duration.

## Data Model Changes

### 1. New Model: `SegmentCanvasSpec`

A lightweight per-segment canvas that reuses the existing `CanvasRegion` type but adds a segment-scoped zoom shorthand.

Add to `src/clipcannon/editing/edl.py`:

```python
class ZoomSpec(BaseModel):
    """Animated zoom from a wide view to a tight crop over the segment duration.

    The crop interpolates linearly from (start_x, start_y, start_w, start_h)
    to (end_x, end_y, end_w, end_h) using FFmpeg's time-varying crop
    expressions. After setpts=PTS-STARTPTS, the `t` variable resets to 0,
    so expressions can use `t` directly.
    """

    # Starting crop (typically the full source or a wide region)
    start_x: int = Field(ge=0)
    start_y: int = Field(ge=0)
    start_w: int = Field(ge=1)
    start_h: int = Field(ge=1)

    # Ending crop (the zoom target)
    end_x: int = Field(ge=0)
    end_y: int = Field(ge=0)
    end_w: int = Field(ge=1)
    end_h: int = Field(ge=1)

    # Easing function for the interpolation
    easing: Literal["linear", "ease_in", "ease_out", "ease_in_out"] = "linear"


class SegmentCanvasSpec(BaseModel):
    """Per-segment canvas override.

    When attached to a SegmentSpec, this completely replaces the
    top-level CanvasSpec for that segment. The segment gets its own
    independent filter chain with its own regions and overlays.

    Mutually exclusive with `zoom` -- use regions[] for multi-region
    compositing, use zoom for a single animated crop.
    """

    regions: list[CanvasRegion] = Field(
        default_factory=list,
        description="Regions to composite for this segment. "
        "If non-empty, full canvas compositing is used.",
    )
    background_color: str = Field(
        default="#000000",
        description="Canvas background for this segment.",
    )
    zoom: ZoomSpec | None = Field(
        default=None,
        description="Animated zoom for this segment. "
        "Mutually exclusive with regions[].",
    )
```

### 2. Modified Model: `SegmentSpec`

Add two optional fields to `SegmentSpec`:

```python
class SegmentSpec(BaseModel):
    """A contiguous time range extracted from the source video."""

    segment_id: int = Field(ge=1)
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(ge=0)
    output_start_ms: int = Field(ge=0)
    speed: float = Field(ge=0.25, le=4.0, default=1.0)
    transition_in: TransitionSpec | None = None
    transition_out: TransitionSpec | None = None

    # NEW: Per-segment canvas override
    canvas: SegmentCanvasSpec | None = Field(
        default=None,
        description="Per-segment canvas override. When set, replaces "
        "the top-level CanvasSpec for this segment only.",
    )
```

### 3. No Changes to `CanvasSpec` or `EditDecisionList`

The top-level `CanvasSpec` remains as-is. It serves as the default for any segment that does not have its own `canvas` override. The resolution priority is:

```
segment.canvas (if present)
  -> top-level edl.canvas (if enabled)
    -> top-level edl.crop (standard crop/scale)
```

### 4. Exact Import/Export Additions

```python
# In edl.py, add to existing imports/exports:
# New classes: ZoomSpec, SegmentCanvasSpec
# Modified class: SegmentSpec (new field: canvas)
```

## Rendering Pipeline Changes

### Overview: Per-Segment Filter Chain Dispatch

The key architectural change is in `_build_multi_segment_cmd` (and the new `_build_per_segment_canvas_cmd`). Instead of applying a single crop to all segments, each segment gets its own filter chain based on its layout configuration.

### Decision Logic

In `build_ffmpeg_cmd`, the dispatch logic changes:

```python
def build_ffmpeg_cmd(...) -> list[str]:
    # Check if ANY segment has a per-segment canvas override
    has_per_segment_canvas = any(
        seg.canvas is not None for seg in segments
    )

    # If per-segment canvas is used, OR top-level canvas is enabled,
    # route to the per-segment-aware canvas builder
    if has_per_segment_canvas or (canvas is not None and canvas.enabled and canvas.regions):
        return _build_per_segment_canvas_cmd(
            source_path, output_path, segments,
            profile, canvas, ass_path, encoding_args,
        )

    # ... existing dispatch for split_screen, pip, crop ...
```

### New Function: `_build_per_segment_canvas_cmd`

This is the main new function in `ffmpeg_cmd.py`. It builds an independent filter chain per segment, then concatenates them.

```python
def _build_per_segment_canvas_cmd(
    source_path: Path,
    output_path: Path,
    segments: list[SegmentSpec],
    profile: EncodingProfile,
    top_level_canvas: CanvasSpec | None,
    ass_path: Path | None,
    encoding_args: list[str],
) -> list[str]:
```

For each segment, it resolves which canvas to use:

```python
for i, seg in enumerate(segments):
    if seg.canvas is not None and seg.canvas.zoom is not None:
        # Animated zoom path
        _build_segment_zoom_chain(filters, seg, i, profile, cw, ch)
    elif seg.canvas is not None and seg.canvas.regions:
        # Per-segment region compositing
        _build_segment_canvas_chain(filters, seg, i, profile, cw, ch, seg.canvas)
    elif top_level_canvas is not None and top_level_canvas.enabled:
        # Fall back to top-level canvas
        _build_segment_canvas_chain(filters, seg, i, profile, cw, ch, top_level_canvas)
    else:
        # Fall back to plain scale (no crop, no canvas)
        _build_segment_plain_chain(filters, seg, i, profile)
```

### Per-Segment Filter Chain: Region Compositing

For a segment with regions, the filter chain is self-contained:

```python
def _build_segment_canvas_chain(
    filters: list[str],
    seg: SegmentSpec,
    idx: int,
    profile: EncodingProfile,
    cw: int, ch: int,
    canvas: SegmentCanvasSpec | CanvasSpec,
) -> str:
    """Build filter chain for one segment with canvas regions.

    Returns the output video label for this segment.
    """
    start_s = seg.source_start_ms / 1000.0
    end_s = seg.source_end_ms / 1000.0
    bg_hex = canvas.background_color.lstrip("#")

    # Determine regions list based on type
    if isinstance(canvas, SegmentCanvasSpec):
        regions = sorted(canvas.regions, key=lambda r: r.z_index)
    else:
        regions = sorted(canvas.regions, key=lambda r: r.z_index)

    n_regions = len(regions)
    seg_dur_s = (end_s - start_s) / seg.speed

    # 1. Trim source video for this segment
    filters.append(
        f"[0:v]trim=start={start_s:.3f}:end={end_s:.3f},"
        f"setpts=PTS-STARTPTS[seg{idx}_src]"
    )

    # 2. Create per-segment background canvas
    filters.append(
        f"color=c=0x{bg_hex}:s={cw}x{ch}:d={seg_dur_s + 1:.1f}"
        f":r={profile.fps},setsar=1[seg{idx}_bg]"
    )

    # 3. Split trimmed source into N copies
    if n_regions == 1:
        filters.append(f"[seg{idx}_src]null[seg{idx}_r0_src]")
    else:
        split_outputs = "".join(f"[seg{idx}_r{j}_src]" for j in range(n_regions))
        filters.append(f"[seg{idx}_src]split={n_regions}{split_outputs}")

    # 4. Crop and scale each region
    for j, region in enumerate(regions):
        filters.append(
            f"[seg{idx}_r{j}_src]"
            f"crop={region.source_width}:{region.source_height}"
            f":{region.source_x}:{region.source_y},"
            f"scale={region.output_width}:{region.output_height},"
            f"setsar=1"
            f"[seg{idx}_r{j}]"
        )

    # 5. Overlay each region onto canvas
    current = f"seg{idx}_bg"
    for j, region in enumerate(regions):
        out = f"seg{idx}_c{j}" if j < n_regions - 1 else f"v{idx}"
        filters.append(
            f"[{current}][seg{idx}_r{j}]"
            f"overlay=x={region.output_x}:y={region.output_y}"
            f":shortest=1[{out}]"
        )
        current = out

    return f"v{idx}"
```

### Per-Segment Filter Chain: Animated Zoom

For a segment with a `ZoomSpec`, we use FFmpeg's time-varying `crop` expressions. After `setpts=PTS-STARTPTS`, the `t` variable resets to 0 for each segment, so we can use it directly for interpolation.

```python
def _build_segment_zoom_chain(
    filters: list[str],
    seg: SegmentSpec,
    idx: int,
    profile: EncodingProfile,
    cw: int, ch: int,
) -> str:
    """Build filter chain for one segment with animated zoom.

    Uses FFmpeg's time-varying crop expressions to interpolate
    from the start crop to the end crop over the segment duration.
    """
    start_s = seg.source_start_ms / 1000.0
    end_s = seg.source_end_ms / 1000.0
    zoom = seg.canvas.zoom
    seg_dur_s = (end_s - start_s) / seg.speed

    # Trim and reset PTS so t starts at 0
    filters.append(
        f"[0:v]trim=start={start_s:.3f}:end={end_s:.3f},"
        f"setpts=PTS-STARTPTS[seg{idx}_src]"
    )

    # Build time-varying crop expression
    # Linear interpolation: value = start + (end - start) * (t / duration)
    # Clamp t to [0, duration] to prevent overshoot
    d = f"{seg_dur_s:.3f}"

    # For linear easing:
    # progress = min(t / duration, 1)
    progress = f"min(t/{d}\\,1)"

    # For ease_in_out (smoothstep):
    # progress = 3*p^2 - 2*p^3  where p = min(t/d, 1)
    if zoom.easing == "ease_in":
        progress = f"pow(min(t/{d}\\,1)\\,2)"
    elif zoom.easing == "ease_out":
        p = f"min(t/{d}\\,1)"
        progress = f"(2*{p}-pow({p}\\,2))"
    elif zoom.easing == "ease_in_out":
        p = f"min(t/{d}\\,1)"
        progress = f"(3*pow({p}\\,2)-2*pow({p}\\,3))"

    def lerp(start_val: int, end_val: int) -> str:
        delta = end_val - start_val
        if delta == 0:
            return str(start_val)
        return f"({start_val}+{delta}*{progress})"

    crop_w = lerp(zoom.start_w, zoom.end_w)
    crop_h = lerp(zoom.start_h, zoom.end_h)
    crop_x = lerp(zoom.start_x, zoom.end_x)
    crop_y = lerp(zoom.start_y, zoom.end_y)

    # Animated crop -> scale to output size
    filters.append(
        f"[seg{idx}_src]"
        f"crop=w='{crop_w}':h='{crop_h}':x='{crop_x}':y='{crop_y}',"
        f"scale={cw}:{ch},setsar=1"
        f"[v{idx}]"
    )

    return f"v{idx}"
```

### Per-Segment Filter Chain: Plain Scale Fallback

```python
def _build_segment_plain_chain(
    filters: list[str],
    seg: SegmentSpec,
    idx: int,
    profile: EncodingProfile,
) -> str:
    """Build filter chain for a segment with no canvas: trim + scale."""
    start_s = seg.source_start_ms / 1000.0
    end_s = seg.source_end_ms / 1000.0

    filters.append(
        f"[0:v]trim=start={start_s:.3f}:end={end_s:.3f},"
        f"setpts=PTS-STARTPTS,"
        f"scale={profile.width}:{profile.height}"
        f"[v{idx}]"
    )
    return f"v{idx}"
```

### Concatenation and Audio

After building per-segment video chains, audio is handled identically to the existing `_build_multi_segment_cmd`:

```python
# Audio chains (unchanged from existing multi-segment)
for i, seg in enumerate(segments):
    start_s = seg.source_start_ms / 1000.0
    end_s = seg.source_end_ms / 1000.0
    achain = (
        f"[0:a]atrim=start={start_s:.3f}:end={end_s:.3f},"
        f"asetpts=PTS-STARTPTS"
    )
    if seg.speed != 1.0:
        achain += f",atempo={seg.speed}"
    alabel = f"a{i}"
    achain += f"[{alabel}]"
    filter_parts.append(achain)
    audio_labels.append(alabel)

# Concat all segments
final_video, final_audio = _build_concat_filters(
    filter_parts, video_labels, audio_labels,
)
```

## FFmpeg Filter Graph Examples

### Example 1: Three Segments with Different Layouts

Segment 1: Speaker full-screen (single region crop of face area)
Segment 2: Split layout (two regions: speaker top, screen bottom)
Segment 3: Animated zoom into code editor at (300,200,800,600)

Source: 1920x1080, output: 1080x1920 (9:16 vertical)

```
# --- Segment 0: Full-screen speaker (region crop) ---
[0:v]trim=start=10.000:end=18.000,setpts=PTS-STARTPTS[seg0_src];
color=c=0x000000:s=1080x1920:d=9.0:r=30,setsar=1[seg0_bg];
[seg0_src]null[seg0_r0_src];
[seg0_r0_src]crop=600:1080:660:0,scale=1080:1920,setsar=1[seg0_r0];
[seg0_bg][seg0_r0]overlay=x=0:y=0:shortest=1[v0];

# --- Segment 1: Split layout (speaker top + screen bottom) ---
[0:v]trim=start=25.000:end=40.000,setpts=PTS-STARTPTS[seg1_src];
color=c=0x000000:s=1080x1920:d=16.0:r=30,setsar=1[seg1_bg];
[seg1_src]split=2[seg1_r0_src][seg1_r1_src];
[seg1_r0_src]crop=480:360:1440:720,scale=1080:672,setsar=1[seg1_r0];
[seg1_r1_src]crop=1440:1080:0:0,scale=1080:1244,setsar=1[seg1_r1];
[seg1_bg][seg1_r0]overlay=x=0:y=0:shortest=1[seg1_c0];
[seg1_c0][seg1_r1]overlay=x=0:y=676:shortest=1[v1];

# --- Segment 2: Animated zoom into code area ---
[0:v]trim=start=55.000:end=65.000,setpts=PTS-STARTPTS[seg2_src];
[seg2_src]crop=w='(1920+(-1120)*min(t/10.000\,1))':h='(1080+(-480)*min(t/10.000\,1))':x='(0+(300)*min(t/10.000\,1))':y='(0+(200)*min(t/10.000\,1))',scale=1080:1920,setsar=1[v2];

# --- Audio chains ---
[0:a]atrim=start=10.000:end=18.000,asetpts=PTS-STARTPTS[a0];
[0:a]atrim=start=25.000:end=40.000,asetpts=PTS-STARTPTS[a1];
[0:a]atrim=start=55.000:end=65.000,asetpts=PTS-STARTPTS[a2];

# --- Concatenate ---
[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[outv][outa]
```

### Example 2: Zoom-Only Segment (Ken Burns Effect)

A single segment that zooms from the full 1920x1080 frame down to a 800x600 region at (300,200):

```
[0:v]trim=start=0.000:end=5.000,setpts=PTS-STARTPTS[seg0_src];
[seg0_src]crop=w='(1920+(-1120)*min(t/5.000\,1))':h='(1080+(-480)*min(t/5.000\,1))':x='(0+(300)*min(t/5.000\,1))':y='(0+(200)*min(t/5.000\,1))',scale=1080:1920,setsar=1[v0]
```

The crop expression breaks down:
- `w` starts at 1920, ends at 800: `1920 + (800-1920) * progress = 1920 + (-1120) * progress`
- `h` starts at 1080, ends at 600: `1080 + (600-1080) * progress = 1080 + (-480) * progress`
- `x` starts at 0, ends at 300: `0 + 300 * progress`
- `y` starts at 0, ends at 200: `0 + 200 * progress`
- `progress = min(t / 5.0, 1)` clamps to prevent overshoot

### Example 3: Mixed -- One Segment Uses Top-Level Canvas, One Overrides

EDL has a top-level canvas with a split layout. Segment 1 uses it. Segment 2 overrides with a full-screen face crop.

```
# --- Segment 0: Uses top-level canvas (split layout) ---
[0:v]trim=start=0.000:end=10.000,setpts=PTS-STARTPTS[seg0_src];
color=c=0x1A1A1A:s=1080x1920:d=11.0:r=30,setsar=1[seg0_bg];
[seg0_src]split=2[seg0_r0_src][seg0_r1_src];
[seg0_r0_src]crop=480:360:1440:720,scale=1080:672,setsar=1[seg0_r0];
[seg0_r1_src]crop=1440:1080:0:0,scale=1080:1244,setsar=1[seg0_r1];
[seg0_bg][seg0_r0]overlay=x=0:y=0:shortest=1[seg0_c0];
[seg0_c0][seg0_r1]overlay=x=0:y=676:shortest=1[v0];

# --- Segment 1: Per-segment override (full-screen face) ---
[0:v]trim=start=15.000:end=22.000,setpts=PTS-STARTPTS[seg1_src];
color=c=0x000000:s=1080x1920:d=8.0:r=30,setsar=1[seg1_bg];
[seg1_src]null[seg1_r0_src];
[seg1_r0_src]crop=600:1080:660:0,scale=1080:1920,setsar=1[seg1_r0];
[seg1_bg][seg1_r0]overlay=x=0:y=0:shortest=1[v1];

# --- Audio + Concat ---
[0:a]atrim=start=0.000:end=10.000,asetpts=PTS-STARTPTS[a0];
[0:a]atrim=start=15.000:end=22.000,asetpts=PTS-STARTPTS[a1];
[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]
```

## File Changes Summary

### `src/clipcannon/editing/edl.py`

| Change | Details |
|--------|---------|
| Add `ZoomSpec` class | 10 fields: start/end x/y/w/h + easing |
| Add `SegmentCanvasSpec` class | Fields: `regions: list[CanvasRegion]`, `background_color: str`, `zoom: ZoomSpec \| None` |
| Add `canvas` field to `SegmentSpec` | Type: `SegmentCanvasSpec \| None`, default `None` |

### `src/clipcannon/rendering/ffmpeg_cmd.py`

| Change | Details |
|--------|---------|
| Add `_build_per_segment_canvas_cmd()` | Top-level orchestrator: iterates segments, dispatches to per-segment chain builders, handles audio + concat |
| Add `_build_segment_canvas_chain()` | Builds trim -> split -> crop/scale -> overlay chain for one segment with regions |
| Add `_build_segment_zoom_chain()` | Builds trim -> animated crop -> scale chain for one segment with zoom |
| Add `_build_segment_plain_chain()` | Builds trim -> scale chain for one segment with no canvas |
| Modify `build_ffmpeg_cmd()` | Add `has_per_segment_canvas` check; route to `_build_per_segment_canvas_cmd` when any segment has a canvas override |
| Retire `_build_canvas_cmd()` | Absorbed into `_build_per_segment_canvas_cmd` (single-segment canvas is just a special case) |

### `src/clipcannon/tools/editing_helpers.py`

| Change | Details |
|--------|---------|
| Modify `build_segments()` | Parse optional `canvas` dict from each raw segment; construct `SegmentCanvasSpec` if present |
| Add `build_segment_canvas()` | New helper: raw dict -> `SegmentCanvasSpec`, handles regions[] and zoom parsing |

### `src/clipcannon/rendering/renderer.py`

| Change | Details |
|--------|---------|
| Modify `render()` | Pass segments (with their per-segment canvas data) through to `build_ffmpeg_cmd` unchanged -- no renderer changes needed since the data flows through `SegmentSpec` |

**Note**: `renderer.py` requires zero changes. The per-segment canvas data is already part of the `SegmentSpec` objects that are passed to `build_ffmpeg_cmd`. The renderer does not need to know about per-segment layouts; it delegates entirely to the command builder.

### `src/clipcannon/tools/editing_defs.py`

| Change | Details |
|--------|---------|
| Extend `segments` schema | Add `canvas` property to each segment item schema: `{ "type": "object", "description": "Per-segment canvas override..." }` |

## How the AI Calls `create_edit` with Per-Segment Layouts

### Scenario 1: Full-Screen Speaker, Then Split, Then Zoom

```json
{
  "project_id": "proj_abc123",
  "name": "Tutorial Highlight with Zoom",
  "target_platform": "tiktok",
  "segments": [
    {
      "source_start_ms": 10000,
      "source_end_ms": 18000,
      "canvas": {
        "regions": [
          {
            "region_id": "speaker_full",
            "source_x": 660, "source_y": 0,
            "source_width": 600, "source_height": 1080,
            "output_x": 0, "output_y": 0,
            "output_width": 1080, "output_height": 1920,
            "z_index": 0
          }
        ]
      }
    },
    {
      "source_start_ms": 25000,
      "source_end_ms": 40000,
      "canvas": {
        "regions": [
          {
            "region_id": "speaker",
            "source_x": 1440, "source_y": 720,
            "source_width": 480, "source_height": 360,
            "output_x": 0, "output_y": 0,
            "output_width": 1080, "output_height": 672,
            "z_index": 0
          },
          {
            "region_id": "screen",
            "source_x": 0, "source_y": 0,
            "source_width": 1440, "source_height": 1080,
            "output_x": 0, "output_y": 676,
            "output_width": 1080, "output_height": 1244,
            "z_index": 0
          }
        ]
      }
    },
    {
      "source_start_ms": 55000,
      "source_end_ms": 65000,
      "canvas": {
        "zoom": {
          "start_x": 0, "start_y": 0,
          "start_w": 1920, "start_h": 1080,
          "end_x": 300, "end_y": 200,
          "end_w": 800, "end_h": 600,
          "easing": "ease_in_out"
        }
      }
    }
  ]
}
```

### Scenario 2: Some Segments Use Top-Level Canvas, One Overrides

```json
{
  "project_id": "proj_abc123",
  "name": "Mixed Layout Demo",
  "target_platform": "instagram_reels",
  "canvas": {
    "enabled": true,
    "canvas_width": 1080,
    "canvas_height": 1920,
    "background_color": "#1A1A1A",
    "regions": [
      {
        "region_id": "speaker",
        "source_x": 1440, "source_y": 720,
        "source_width": 480, "source_height": 360,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 672,
        "z_index": 0
      },
      {
        "region_id": "screen",
        "source_x": 0, "source_y": 0,
        "source_width": 1440, "source_height": 1080,
        "output_x": 0, "output_y": 676,
        "output_width": 1080, "output_height": 1244,
        "z_index": 0
      }
    ]
  },
  "segments": [
    {
      "source_start_ms": 0,
      "source_end_ms": 10000
    },
    {
      "source_start_ms": 15000,
      "source_end_ms": 22000,
      "canvas": {
        "regions": [
          {
            "region_id": "face_closeup",
            "source_x": 660, "source_y": 0,
            "source_width": 600, "source_height": 1080,
            "output_x": 0, "output_y": 0,
            "output_width": 1080, "output_height": 1920,
            "z_index": 0
          }
        ]
      }
    },
    {
      "source_start_ms": 30000,
      "source_end_ms": 45000
    }
  ]
}
```

Segments 1 and 3 have no `canvas` field, so they inherit the top-level split layout. Segment 2 overrides with a full-screen face closeup.

### Scenario 3: Pure Zoom Clip (No Regions)

```json
{
  "project_id": "proj_abc123",
  "name": "Code Zoom-In",
  "target_platform": "youtube_shorts",
  "segments": [
    {
      "source_start_ms": 120000,
      "source_end_ms": 135000,
      "canvas": {
        "zoom": {
          "start_x": 0, "start_y": 0,
          "start_w": 1920, "start_h": 1080,
          "end_x": 400, "end_y": 100,
          "end_w": 960, "end_h": 540,
          "easing": "ease_out"
        }
      }
    }
  ]
}
```

## Parsing Changes in `editing_helpers.py`

### Modified `build_segments`

```python
def build_segments(
    raw_segments: list[dict[str, object]],
) -> list[SegmentSpec]:
    specs: list[SegmentSpec] = []
    output_cursor_ms = 0

    for idx, raw in enumerate(raw_segments, start=1):
        source_start = int(raw["source_start_ms"])
        source_end = int(raw["source_end_ms"])
        speed = float(raw.get("speed", 1.0))

        transition_in = build_transition(raw.get("transition_in"))
        transition_out = build_transition(raw.get("transition_out"))

        # NEW: Parse per-segment canvas override
        seg_canvas = build_segment_canvas(raw.get("canvas"))

        seg = SegmentSpec(
            segment_id=idx,
            source_start_ms=source_start,
            source_end_ms=source_end,
            output_start_ms=output_cursor_ms,
            speed=speed,
            transition_in=transition_in,
            transition_out=transition_out,
            canvas=seg_canvas,  # NEW
        )
        specs.append(seg)
        output_cursor_ms += seg.output_duration_ms

    return specs
```

### New `build_segment_canvas`

```python
def build_segment_canvas(
    raw: dict[str, object] | None,
) -> SegmentCanvasSpec | None:
    """Build SegmentCanvasSpec from raw dict input.

    Args:
        raw: Raw per-segment canvas dict, or None.

    Returns:
        SegmentCanvasSpec or None.
    """
    if raw is None:
        return None

    zoom_raw = raw.get("zoom")
    zoom = None
    if isinstance(zoom_raw, dict):
        zoom = ZoomSpec(
            start_x=int(zoom_raw["start_x"]),
            start_y=int(zoom_raw["start_y"]),
            start_w=int(zoom_raw["start_w"]),
            start_h=int(zoom_raw["start_h"]),
            end_x=int(zoom_raw["end_x"]),
            end_y=int(zoom_raw["end_y"]),
            end_w=int(zoom_raw["end_w"]),
            end_h=int(zoom_raw["end_h"]),
            easing=zoom_raw.get("easing", "linear"),
        )

    regions_raw = raw.get("regions", [])
    regions = []
    if isinstance(regions_raw, list):
        for r in regions_raw:
            if isinstance(r, dict):
                regions.append(CanvasRegion(**r))

    if not regions and zoom is None:
        return None

    return SegmentCanvasSpec(
        regions=regions,
        background_color=str(raw.get("background_color", "#000000")),
        zoom=zoom,
    )
```

## Validation Additions

Add to `validate_edl()` in `edl.py`:

```python
# --- Per-segment canvas validation ---
for seg in segments:
    if seg.canvas is not None:
        sc = seg.canvas
        if sc.regions and sc.zoom is not None:
            errors.append(
                f"Segment {seg.segment_id}: canvas cannot have both "
                f"regions[] and zoom -- they are mutually exclusive"
            )
        if sc.zoom is not None:
            z = sc.zoom
            if z.end_w > z.start_w or z.end_h > z.start_h:
                # Zoom out (widening crop) is valid but unusual -- warn
                pass
            if z.start_w <= 0 or z.start_h <= 0:
                errors.append(
                    f"Segment {seg.segment_id}: zoom start dimensions "
                    f"must be positive"
                )
```

## Database Schema Impact

No schema changes required. The `edits` table stores the full EDL as a JSON blob in the `edl_json` column. The per-segment canvas data is serialized/deserialized as part of the `SegmentSpec` Pydantic model. The `edit_segments` table stores flat segment metadata (start/end/speed/transitions) and does not need per-segment canvas columns since the authoritative data is in the EDL JSON.

## Performance Considerations

1. **Filter graph complexity**: Each segment with regions produces O(N) split + crop + overlay filters. For 3 segments with 2 regions each, that is 18 filter nodes plus concat -- well within FFmpeg's limits.

2. **Animated crop expressions**: FFmpeg evaluates crop expressions per-frame. The arithmetic (`min`, `pow`, multiplication) is trivially cheap compared to the actual pixel operations.

3. **Memory**: Each `split=N` creates N full copies of the segment's decoded frames. For segments with many regions (>4), memory usage can be significant. The practical limit is ~6 regions per segment before memory pressure on a 16GB system.

4. **Concat vs. single-pass**: The concat approach (trim per segment, then concat) is the only way to have independent filter chains per segment. There is no way to switch filter graphs mid-stream in a single FFmpeg pass.

## Testing Strategy

### Unit Tests (`tests/test_per_segment_canvas.py`)

1. **Model validation**: `SegmentSpec` with `canvas` set, `ZoomSpec` field constraints, mutual exclusion of `regions` and `zoom`
2. **Filter chain generation**: Call `_build_per_segment_canvas_cmd` with known inputs, assert filter_complex string contains expected patterns
3. **Zoom expression correctness**: Verify the crop expression for linear, ease_in, ease_out, ease_in_out
4. **Fallback chain**: Segment without canvas falls back to top-level canvas, then to plain scale
5. **Parsing**: `build_segment_canvas` with various raw dicts, including None, empty, zoom-only, regions-only

### Integration Tests

1. **Render a 3-segment clip** where each segment has a different layout (requires a test source video)
2. **Render a zoom segment** and verify the output file exists and has the correct duration
3. **Mixed fallback** render: two segments use top-level canvas, one overrides

## Implementation Order

1. Add `ZoomSpec`, `SegmentCanvasSpec` models to `edl.py`
2. Add `canvas` field to `SegmentSpec`
3. Add `build_segment_canvas()` to `editing_helpers.py`
4. Modify `build_segments()` to call it
5. Add per-segment chain builders to `ffmpeg_cmd.py`
6. Add `_build_per_segment_canvas_cmd()` orchestrator
7. Modify `build_ffmpeg_cmd()` dispatch
8. Update tool schema in `editing_defs.py`
9. Add validation rules to `validate_edl()`
10. Write unit tests
11. Write integration tests

## Status

**Designed** on 2026-03-21. Ready for implementation.
