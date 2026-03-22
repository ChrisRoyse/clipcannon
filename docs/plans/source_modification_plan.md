# Source Modification Implementation Plan

## Problem
ClipCannon can only crop, reposition, and reframe existing source pixels. It cannot add new content, remove existing content, or modify what's in the source frame. This limits video editing to below human-level capability.

## What Source Modification Enables

### Tier 1: Text & Graphics (FFmpeg-only, no ML models)

**1. Animated Text Overlays** - Replace/add text at any position with perfect sizing for any aspect ratio
- FFmpeg `drawtext` filter with `enable='between(t,start,end)'` for timed display
- Alpha fading: `alpha='if(between(t,1,1.3),(t-1)/0.3,if(between(t,3.7,4),1-(t-3.7)/0.3,1))'`
- Dynamic positioning: slide-in from left (`x='if(lt(t,1),-tw+t*tw,0)'`), from bottom, etc.
- Font size animation: `fontsize='if(lt(t,0.5),48*t/0.5,48)'` for scale-in effect
- **Use case**: Re-render "ocrprovenance.com" text at perfect vertical format size instead of cropping the wide source text

**2. Text/Logo Removal** - Remove existing text/logos from source before recompositing
- FFmpeg `delogo` filter: `delogo=x=XX:y=YY:w=WW:h=HH:band=10` blurs a rectangular region using surrounding pixels
- Chain with drawtext to replace: `delogo` -> `drawtext` in single filter_complex
- **Use case**: Remove browser chrome, desktop taskbar, watermarks from screen recordings

**3. Solid Color Panels** - Add colored rectangles behind text for readability
- FFmpeg `drawbox` filter: `drawbox=x=0:y=h-200:w=iw:h=200:color=black@0.7:t=fill`
- Semi-transparent backgrounds for lower thirds
- **Use case**: Add dark bar behind captions/lower thirds for readability over light backgrounds

**4. Image Overlays** - Composite PNG/SVG images with alpha transparency
- FFmpeg `overlay` filter with alpha channel support
- Position any image at any coordinates with timing control
- **Use case**: Brand logos, subscribe buttons, arrow graphics, emoji reactions

### Tier 2: Background Modification (ML models, local GPU)

**5. Background Removal (rembg)** - Remove background from speaker, keep only the person
- Python `rembg` library with U2-Net or BRIA-RMBG models (local GPU)
- Frame-by-frame: extract frames -> rembg removes bg -> get alpha mask -> composite
- Alpha matting parameters: foreground_threshold, background_threshold, erode_size
- Output: RGBA frames or separate alpha mask video
- **Use case**: Extract speaker from webcam and composite over ANY background

**6. Background Blur** - Blur the background behind the speaker
- Process: rembg generates mask -> apply Gaussian blur to background only -> composite sharp subject over blurred bg
- FFmpeg: `split[fg][bg]; [bg]gblur=sigma=30[blurred]; [fg][mask]alphamerge[subject]; [blurred][subject]overlay`
- **Use case**: Professional depth-of-field look for webcam footage

**7. Background Replacement** - Replace background entirely
- Same as removal but composite over a new background (solid color, gradient, image, or video)
- **Use case**: Place speaker in front of any background without green screen

### Tier 3: Advanced Compositing

**8. Multi-Source Compositing** - Combine footage from multiple videos
- FFmpeg supports multiple `-i` inputs in filter_complex
- **Use case**: Cut in B-roll footage, reaction videos, side-by-side comparisons

**9. Animated Transitions Between Layouts** - Smooth movement between compositions
- FFmpeg expression-based animation: `overlay=x='lerp(x1,x2,(t-start)/(end-start))'`
- **Use case**: Speaker region smoothly slides from center to corner when screen content appears

**10. Dynamic Zoom/Pan on Source** - Animated crop windows following content
- FFmpeg `zoompan` filter with expression-based coordinates
- Already implemented in motion.py but not wired into canvas pipeline
- **Use case**: Follow cursor movement in screen recordings, zoom into specific UI elements

## Implementation Architecture

### Phase 1: Wire Existing Features into Canvas Pipeline
**Priority: HIGHEST - unblocks everything**

The overlay, color, and motion filters already generate correct FFmpeg filter strings but they aren't applied in the canvas compositing code path (`_build_segment_canvas_chain` in ffmpeg_cmd.py).

**Fix**: After compositing all canvas regions, apply these additional filters:
1. Color grading: append `eq=brightness:contrast:saturation,hue=h=shift` to the composed output
2. Overlays: append `drawtext` and `drawbox` filters after composition
3. Motion: integrate `zoompan` into the per-region crop/scale chain

**Files to modify**:
- `src/clipcannon/rendering/ffmpeg_cmd.py` - `_build_segment_canvas_chain()` function
- No new modules needed

### Phase 2: Animated Text Overlays (FFmpeg drawtext)
**Priority: HIGH - solves the text-too-wide-for-vertical problem**

**New capability**: `clipcannon_add_text` tool that renders text directly onto the video at specified coordinates, size, color, with animation timing. Unlike overlays that are stored in EDL but not rendered, this generates FFmpeg drawtext filters that ARE applied during rendering.

**Implementation**:
- Extend `_build_segment_canvas_chain()` to append drawtext filters after region composition
- Read overlay specs from EDL and generate timed drawtext expressions
- Support: fade_in, fade_out, slide_up, slide_down, scale_in animations via FFmpeg expressions

**Files**:
- `src/clipcannon/rendering/ffmpeg_cmd.py` - add `_apply_overlay_filters()` function
- `src/clipcannon/editing/overlays.py` - already has the filter generation logic

### Phase 3: Text/Logo Removal (FFmpeg delogo)
**Priority: MEDIUM**

**New tool**: `clipcannon_remove_region` - masks out a rectangular area from the source
- Uses FFmpeg `delogo` filter to blur/interpolate over specified region
- Applied per-segment in the filter chain before any crop/scale
- Chainable: remove browser chrome, then crop to content area

**Files**:
- `src/clipcannon/editing/edl.py` - add `RemovalSpec` model (list of regions to remove)
- `src/clipcannon/rendering/ffmpeg_cmd.py` - add delogo to filter chain

### Phase 4: Background Removal & Replacement (rembg + GPU)
**Priority: HIGH - enables professional-quality speaker isolation**

**New tools**:
- `clipcannon_extract_subject` - runs rembg on frames, generates alpha mask video
- `clipcannon_replace_background` - composites subject over new background

**Implementation**:
1. Install `rembg[gpu]` with ONNX Runtime GPU
2. Extract frames at 2fps (already done by pipeline)
3. Run rembg on each frame to generate alpha mask
4. Create mask video from alpha frames via FFmpeg
5. Use `alphamerge` + `overlay` in filter_complex to composite

**Files**:
- `src/clipcannon/editing/subject_extraction.py` - new module: rembg processing
- `src/clipcannon/tools/editing.py` - new tool handlers
- `src/clipcannon/rendering/ffmpeg_cmd.py` - add alpha compositing to filter chain

### Phase 5: Image Overlays (PNG with alpha)
**Priority: MEDIUM**

**Enhancement to existing overlay tool**: Support `image_path` parameter
- FFmpeg: `-i logo.png` as second input, `overlay=x:y:enable='between(t,start,end)'`
- Requires multi-input FFmpeg command (currently only single source input)

**Files**:
- `src/clipcannon/rendering/ffmpeg_cmd.py` - support multiple `-i` inputs
- `src/clipcannon/tools/editing.py` - validate image_path exists

## Execution Order

1. **Phase 1** (Wire existing features) - 1 day - Unblocks overlays, color, motion in renders
2. **Phase 2** (Animated text) - 1 day - Solves text-for-vertical problem
3. **Phase 4** (Background removal) - 2 days - Biggest impact for speaker isolation
4. **Phase 3** (Logo removal) - 0.5 day - Simple FFmpeg filter addition
5. **Phase 5** (Image overlays) - 1 day - Multi-input FFmpeg support

## Dependencies

- **Phase 1**: No new dependencies
- **Phase 2**: No new dependencies (FFmpeg drawtext is built-in)
- **Phase 3**: No new dependencies (FFmpeg delogo is built-in)
- **Phase 4**: `rembg[gpu]`, `onnxruntime-gpu` (local GPU inference, no API calls)
- **Phase 5**: No new dependencies

## Source File Protection

**CRITICAL: The original source video is SACRED and NEVER modified.**

All "source modification" features work by producing NEW output files. The pipeline:

```
source/original.mp4 (READ-ONLY, Sacred tier)
    │
    ├── FFmpeg reads source as input (-i)
    ├── Applies ALL filters in memory (crop, scale, drawtext, delogo, overlay, etc.)
    ├── Writes NEW file to renders/ directory
    │
    └── renders/render_XXXX/output.mp4 (NEW file, source untouched)
```

For background removal (rembg), intermediate files go to a temp processing directory:

```
source/original.mp4 (READ-ONLY)
    │
    ├── frames/ (already extracted at 2fps, READ-ONLY after extraction)
    ├── processing/masks/ (NEW alpha mask frames from rembg)
    ├── processing/mask_video.mp4 (NEW mask video assembled from masks)
    │
    └── FFmpeg composites: source + mask -> renders/output.mp4 (NEW)
```

**Enforcement:**
- RenderEngine verifies source SHA-256 before every render (unchanged = safe)
- Source files live in `source/` directory (Sacred tier - never auto-deleted)
- All intermediate files go to `processing/` or `edits/` directories
- Provenance chain records input hash -> output hash for audit trail
- If source SHA-256 doesn't match EDL's `source_sha256`, render is REFUSED

## Constitution Compliance

- All processing is LOCAL - no video data leaves the machine (SEC-01)
- Source video files are NEVER modified - new rendered output only (ARCH-02, SEC-02)
- FFmpeg is the ONLY renderer (ARCH-30)
- Single-pass rendering where possible (ARCH-33)
- GPU models loaded on-demand (ARCH-52)
- Provenance hash chain tracks every transformation (SEC-12)
