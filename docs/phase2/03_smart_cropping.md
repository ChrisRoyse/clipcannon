# Smart Cropping

## 1. Overview

ClipCannon ingests landscape (16:9) source video and must produce platform-ready
clips in multiple aspect ratios: 9:16 for TikTok/Reels/Shorts, 1:1 for LinkedIn,
4:5 for Instagram Feed, and others. A naive center crop loses speakers who are
positioned off-center -- which is extremely common in interviews, presentations,
and vlogs. Smart cropping uses face detection to anchor the crop window on the
primary speaker so they remain in frame after the aspect-ratio conversion.

Phase 1 already provides the foundation. The `shot_type` pipeline stage
(SigLIP zero-shot classification in `src/clipcannon/pipeline/shot_type.py`)
classifies every scene key frame into one of five shot types and stores a
`crop_recommendation` per scene. Phase 2 takes those recommendations and
executes the actual crop, using face detection for precise positioning.

### Phase 1 Columns Already in `scenes` Table

| Column | Type | Source |
|--------|------|--------|
| `face_detected` | BOOLEAN | Phase 2 (populated by smart crop) |
| `face_position_x` | REAL | Phase 2 (normalized 0.0-1.0) |
| `face_position_y` | REAL | Phase 2 (normalized 0.0-1.0) |
| `shot_type` | TEXT | Phase 1 shot_type stage |
| `shot_type_confidence` | REAL | Phase 1 shot_type stage |
| `crop_recommendation` | TEXT | Phase 1 shot_type stage |

The `crop_recommendation` values from Phase 1 are:

| Value | Shot Types | Meaning |
|-------|-----------|---------|
| `safe_for_vertical` | extreme_closeup, closeup | Subject fills frame; center crop is safe |
| `needs_reframe` | medium | Subject may be off-center; face detection needed |
| `keep_landscape` | wide, establishing | Wide context; face detection for pan-and-scan |

## 2. Face Detection

### Model Selection

Primary model: **MediaPipe Face Detection** (short-range model).

- Runs on CPU efficiently (< 5ms per frame)
- Pre-trained, no fine-tuning needed
- Returns bounding boxes with confidence scores and facial landmarks
- Apache 2.0 license

Fallback model: **InsightFace ONNX** (RetinaFace variant).

- Used when MediaPipe returns no detections (profile views, partial occlusion)
- Heavier but more robust to non-frontal faces
- ONNX runtime for cross-platform GPU/CPU inference

### Detection Workflow

1. Load the scene key frame image from `scenes.key_frame_path` (one per scene,
   already extracted in Phase 1).
2. Run MediaPipe face detection on the key frame.
3. If no faces detected and `crop_recommendation` is `needs_reframe`, retry
   with InsightFace ONNX as fallback.
4. Store detection results:
   - `face_detected` = True/False
   - `face_position_x` = normalized center X of primary face (0.0-1.0)
   - `face_position_y` = normalized center Y of primary face (0.0-1.0)
5. Return list of all detected face bounding boxes for multi-person handling.

### Face Position Normalization

All face positions are stored as normalized coordinates (0.0-1.0) relative to
the source frame dimensions. This decouples detection from resolution:

```
face_position_x = (face_bbox.x + face_bbox.width / 2) / source_width
face_position_y = (face_bbox.y + face_bbox.height / 2) / source_height
```

### Frame Sampling for Temporal Tracking

For scenes longer than 5 seconds, detect faces on multiple sampled frames (one
per second) to establish a face motion trajectory. This feeds into the
pan-and-scan logic (Section 5). For scenes under 5 seconds, the single key
frame detection is sufficient.

## 3. Crop Strategy by Shot Type

The `shot_type` value from Phase 1 determines the crop strategy. This avoids
running expensive face detection on frames where it is unnecessary (e.g.,
establishing shots of locations).

| Shot Type | crop_recommendation | Crop Strategy | Face Detection | Notes |
|-----------|-------------------|---------------|----------------|-------|
| `extreme_closeup` | `safe_for_vertical` | Center crop | Skip | Face fills frame; any crop is safe |
| `closeup` | `safe_for_vertical` | Face-centered crop | Run | Center on detected face for precision |
| `medium` | `needs_reframe` | Face-centered with context | Run (required) | Include upper body; face must be in safe area |
| `wide` | `keep_landscape` | Pan-and-scan or center | Run (optional) | Track primary speaker if identifiable |
| `establishing` | `keep_landscape` | Center crop | Skip | No faces to track; scenic content |

### Decision Tree

```
scene.shot_type?
  |
  +-- extreme_closeup --> center crop (no detection)
  |
  +-- closeup --> detect face
  |     |-- face found --> center crop on face
  |     +-- no face   --> center crop (fallback)
  |
  +-- medium --> detect face
  |     |-- face found --> face-centered crop with safe area margin
  |     +-- no face   --> center crop with 60% width bias
  |
  +-- wide --> detect face (optional)
  |     |-- face found --> pan-and-scan to face
  |     |-- no face   --> center crop
  |     +-- multiple  --> fit bounding box around all faces
  |
  +-- establishing --> center crop (no detection)
```

## 4. Crop Calculation

### Aspect Ratio Math

Given a source frame of `W x H` (typically 1920x1080 for 16:9), the crop
window dimensions are calculated to match the target aspect ratio while
maximizing the use of the source height (no vertical cropping when possible).

```
target_aspect = target_w / target_h

If target is taller than source (e.g., 9:16 from 16:9):
    crop_h = H                           # use full source height
    crop_w = round(H * target_aspect)    # width from aspect ratio

If target is wider than source aspect:
    crop_w = W                           # use full source width
    crop_h = round(W / target_aspect)    # height from aspect ratio
```

### 16:9 to 9:16 (Vertical)

- Source: 1920 x 1080
- Target aspect: 9/16 = 0.5625
- Crop window: `round(1080 * 0.5625)` x 1080 = **607 x 1080**
- Crop x position = `face_center_x_px - (crop_w / 2)`
- Clamp to `[0, source_w - crop_w]` = `[0, 1313]`
- Safe area: face center must fall within 15% of crop center (85% safe region)

```python
crop_w = round(source_h * (9 / 16))       # 607
face_cx = face_position_x * source_w       # e.g., 0.6 * 1920 = 1152
crop_x = int(face_cx - crop_w / 2)         # 1152 - 303 = 849
crop_x = max(0, min(crop_x, source_w - crop_w))  # clamp to [0, 1313]
```

### 16:9 to 1:1 (Square)

- Source: 1920 x 1080
- Target aspect: 1/1 = 1.0
- Crop window: 1080 x 1080
- Crop x position: center on face horizontally
- Clamp to `[0, 840]`

### 16:9 to 4:5

- Source: 1920 x 1080
- Target aspect: 4/5 = 0.8
- Crop window: `round(1080 * 0.8)` x 1080 = **864 x 1080**
- Crop x position: center on face horizontally
- Clamp to `[0, 1056]`

### Safe Area Enforcement

The "safe area" prevents faces from being too close to the crop edge, which
looks visually awkward and risks cutting off the face on devices with rounded
screen corners or platform UI overlays.

```python
SAFE_AREA_PCT = 0.85  # face must be within central 85% of crop width

safe_margin = crop_w * (1 - SAFE_AREA_PCT) / 2  # 7.5% on each side
face_in_crop_x = face_cx - crop_x

if face_in_crop_x < safe_margin:
    crop_x = max(0, int(face_cx - safe_margin))
elif face_in_crop_x > crop_w - safe_margin:
    crop_x = min(source_w - crop_w, int(face_cx - crop_w + safe_margin))
```

## 5. Dynamic Pan-and-Scan

### When Pan-and-Scan Activates

Pan-and-scan applies when the face position shifts significantly between
consecutive scenes, or when a scene contains face movement (detected via
multi-frame sampling). Static crops with jump cuts between positions look
jarring; smooth panning looks professional.

Triggers:
- Face position delta between adjacent scenes > 15% of frame width
- Face moves more than 10% of frame width within a single scene
- Shot type transitions from `wide` to `closeup` (or vice versa)

### Pan Implementation

The crop x-position is interpolated over a transition duration:

```python
TRANSITION_MS = 500          # pan duration in milliseconds
EASE_FUNCTION = "ease_in_out"  # cubic ease-in-out

# Keyframes for FFmpeg crop filter
keyframe_start = CropKeyframe(time_ms=scene_start_ms, x=prev_crop_x)
keyframe_end   = CropKeyframe(time_ms=scene_start_ms + TRANSITION_MS, x=new_crop_x)
```

### Ease-In-Out Interpolation

```python
def ease_in_out(t: float) -> float:
    """Cubic ease-in-out: t in [0, 1] -> [0, 1]."""
    if t < 0.5:
        return 4 * t * t * t
    return 1 - (-2 * t + 2) ** 3 / 2
```

### FFmpeg Expression-Based Panning

The pan is encoded as an FFmpeg `crop` filter expression that evaluates the
crop x-position as a function of time:

```
crop=607:1080:'if(between(t,T0,T1),
  lerp(X0,X1,(t-T0)/(T1-T0)),
  if(lt(t,T0),X0,X1))':0
```

Where `T0` and `T1` are the transition start/end times in seconds, and `X0`/`X1`
are the start/end crop positions. The actual expression uses the cubic easing
approximation via nested `if` and polynomial expressions.

## 6. Multi-Person Handling

### Priority Rules

When multiple faces are detected in a frame, a single "target face" must be
selected for the crop anchor. Priority order:

1. **Active speaker** -- if speaker diarization data is available from Phase 1
   (`speakers` table + `transcript_segments.speaker_id`), match the speaking
   segments to face positions. The face associated with the current speaker
   gets priority.

2. **Largest face** -- the face with the largest bounding box area is closest
   to the camera and most likely the primary subject.

3. **Center of all faces** -- compute the centroid of all detected face
   centers and crop to that point. This keeps all faces visible when possible.

### Two-Person Interview Mode

For scenes where exactly two faces are detected with similar bounding box sizes
(ratio < 1.5x), the system enters interview mode:

- **If speaker diarization is available**: alternate the crop target between
  speakers based on `transcript_segments.speaker_id` timing. Insert 500ms
  pan transitions between speakers.

- **If no diarization**: use the centroid of both faces. For vertical (9:16)
  crops where both faces cannot fit, prefer the larger face but flag the scene
  for human review.

- **If target is 1:1 or 4:5**: the wider crop may fit both faces. Calculate
  the bounding box that contains both faces with 10% padding and check if it
  fits within the crop window.

```python
def fits_both_faces(face_a: FaceBox, face_b: FaceBox, crop_w: int) -> bool:
    """Check if both faces fit within the crop width."""
    left = min(face_a.x, face_b.x)
    right = max(face_a.x + face_a.w, face_b.x + face_b.w)
    span = right - left
    padded_span = span * 1.1  # 10% padding
    return padded_span <= crop_w
```

## 7. FFmpeg Crop Filter Integration

### Static Crop (Single Position)

For scenes with a stable face position and no transitions:

```
crop=crop_w:crop_h:crop_x:0, scale=target_w:target_h
```

Example for 9:16 from 1920x1080 with face at x=1152:

```
crop=607:1080:849:0, scale=1080:1920
```

### Animated Crop (Pan-and-Scan)

For scenes with transitions, the crop x-position is expressed as a time-varying
function. The `typed-ffmpeg` library (Phase 2 dependency) builds these filter
graphs with type safety:

```python
import typed_ffmpeg as ffmpeg

(
    ffmpeg.input("source.mp4")
    .filter(
        "crop",
        w=607,
        h=1080,
        x="if(between(t,2.0,2.5), 400+(849-400)*(t-2.0)/0.5, if(lt(t,2.0),400,849))",
        y=0,
    )
    .filter("scale", w=1080, h=1920)
    .output("output.mp4")
)
```

### Filter Chain Order

The crop filter sits in the rendering pipeline filter chain in this order:

1. **Decode** -- source video input
2. **Trim** -- select the segment time range (from EDL)
3. **Crop** -- smart crop to target aspect ratio (this module)
4. **Scale** -- resize to target output resolution
5. **Overlay** -- captions/subtitles (from caption generation module)
6. **Encode** -- NVENC H.264/H.265 output

## 8. Implementation

### File: `src/clipcannon/editing/smart_crop.py`

#### Data Models

```python
from pydantic import BaseModel, Field


class FaceBox(BaseModel):
    """Bounding box for a detected face."""
    x: int                           # left edge in pixels
    y: int                           # top edge in pixels
    w: int                           # width in pixels
    h: int                           # height in pixels
    confidence: float = Field(ge=0, le=1)


class CropRegion(BaseModel):
    """Calculated crop window for a scene."""
    x: int                           # crop left edge in source pixels
    y: int                           # crop top edge in source pixels (usually 0)
    width: int                       # crop window width
    height: int                      # crop window height
    face_centered: bool              # True if crop was anchored on a face
    confidence: float = Field(ge=0, le=1)  # face detection confidence (0 if no face)


class CropKeyframe(BaseModel):
    """A crop position at a specific time, for animated pan-and-scan."""
    time_ms: int                     # absolute time in source video
    x: int                           # crop x position at this time
    y: int = 0                       # crop y position (usually 0)
    easing: str = "ease_in_out"      # interpolation to next keyframe
```

#### Public Functions

```python
def detect_faces(frame_path: str | Path) -> list[FaceBox]:
    """Detect faces in a single frame image.

    Uses MediaPipe Face Detection (short-range model) as primary detector.
    Falls back to InsightFace ONNX if MediaPipe returns no detections.

    Args:
        frame_path: Path to the frame image file.

    Returns:
        List of FaceBox instances sorted by area (largest first).
    """
    ...


def calculate_crop_region(
    source_w: int,
    source_h: int,
    target_aspect: tuple[int, int],
    face_boxes: list[FaceBox],
    shot_type: str,
) -> CropRegion:
    """Calculate the optimal crop region for a scene.

    Args:
        source_w: Source frame width in pixels.
        source_h: Source frame height in pixels.
        target_aspect: Target aspect ratio as (w, h), e.g., (9, 16).
        face_boxes: Detected faces (may be empty).
        shot_type: Shot type from Phase 1 classification.

    Returns:
        CropRegion with calculated position and dimensions.
    """
    ...


def smooth_crop_transitions(
    crop_regions: list[tuple[int, CropRegion]],
    transition_ms: int = 500,
    threshold_pct: float = 0.15,
) -> list[CropKeyframe]:
    """Generate animated keyframes for smooth pan-and-scan transitions.

    Examines consecutive crop regions and inserts transition keyframes
    when the crop position shifts by more than threshold_pct of the
    source width.

    Args:
        crop_regions: List of (scene_start_ms, CropRegion) tuples,
            ordered by time.
        transition_ms: Duration of each pan transition in milliseconds.
        threshold_pct: Minimum position delta (as fraction of source width)
            to trigger a transition instead of a hard cut.

    Returns:
        List of CropKeyframe instances for the entire video.
    """
    ...


def generate_crop_filter(
    crop_keyframes: list[CropKeyframe],
    source_w: int,
    source_h: int,
    target_w: int,
    target_h: int,
) -> str:
    """Generate an FFmpeg crop+scale filter expression from keyframes.

    Produces a filter string suitable for passing to FFmpeg's -vf flag
    or to typed-ffmpeg's filter builder.

    Args:
        crop_keyframes: Ordered list of crop keyframes.
        source_w: Source frame width.
        source_h: Source frame height.
        target_w: Output frame width.
        target_h: Output frame height.

    Returns:
        FFmpeg filter expression string, e.g.,
        "crop=607:1080:849:0,scale=1080:1920"
    """
    ...
```

### Integration with Rendering Pipeline

The smart crop module is called by the rendering pipeline
(`src/clipcannon/rendering/renderer.py`) during the filter graph construction
phase. The renderer:

1. Reads the EDL segment to get the scene reference and target platform.
2. Looks up `shot_type`, `face_detected`, `face_position_x`, `face_position_y`
   from the `scenes` table.
3. Calls `calculate_crop_region()` with the appropriate target aspect ratio.
4. If multiple consecutive segments have different crop positions, calls
   `smooth_crop_transitions()` to generate keyframes.
5. Calls `generate_crop_filter()` to get the FFmpeg filter expression.
6. Inserts the filter into the typed-ffmpeg filter chain.

### Integration with Face Detection Pipeline

Face detection runs as a pre-render step, not as a pipeline stage. It is
triggered when a render is requested for a non-16:9 target:

1. For each scene in the EDL, check if `face_detected` is already populated.
2. If not, run `detect_faces()` on the key frame.
3. Update `scenes.face_detected`, `scenes.face_position_x`,
   `scenes.face_position_y` in the database.
4. Proceed with crop calculation.

This lazy evaluation avoids running face detection for projects that only
target 16:9 output (YouTube Standard).

## 9. Platform Crop Profiles

Each target platform has a fixed crop profile. These are defined in the
rendering profiles module (`src/clipcannon/rendering/profiles.py`) and
consumed by the smart crop module.

| Platform | Aspect Ratio | Output Resolution | Crop from 1920x1080 | Crop Strategy |
|----------|-------------|-------------------|---------------------|---------------|
| TikTok | 9:16 | 1080x1920 | 607x1080 | Face-centered vertical |
| Instagram Reels | 9:16 | 1080x1920 | 607x1080 | Face-centered vertical |
| Instagram Feed | 4:5 | 1080x1350 | 864x1080 | Face-centered |
| YouTube Shorts | 9:16 | 1080x1920 | 607x1080 | Face-centered vertical |
| YouTube Standard | 16:9 | 1920x1080 | No crop | Pass-through (or letterbox) |
| Facebook Reels | 9:16 | 1080x1920 | 607x1080 | Face-centered vertical |
| LinkedIn | 1:1 | 1080x1080 | 1080x1080 | Face-centered square |
| X (Twitter) | 16:9 | 1280x720 | No crop | Scale only |
| Pinterest | 2:3 | 1000x1500 | 720x1080 | Face-centered vertical |

### Profile Data Structure

```python
class CropProfile(BaseModel):
    """Crop profile for a target platform."""
    platform: str                     # e.g., "tiktok"
    aspect_w: int                     # aspect ratio width component
    aspect_h: int                     # aspect ratio height component
    output_w: int                     # output resolution width
    output_h: int                     # output resolution height
    needs_crop: bool                  # False for 16:9 targets
    face_detection_required: bool     # False for pass-through
    max_duration_s: int | None        # platform max (e.g., 180 for TikTok)


CROP_PROFILES: dict[str, CropProfile] = {
    "tiktok": CropProfile(
        platform="tiktok",
        aspect_w=9, aspect_h=16,
        output_w=1080, output_h=1920,
        needs_crop=True, face_detection_required=True,
        max_duration_s=180,
    ),
    "instagram_reels": CropProfile(
        platform="instagram_reels",
        aspect_w=9, aspect_h=16,
        output_w=1080, output_h=1920,
        needs_crop=True, face_detection_required=True,
        max_duration_s=90,
    ),
    "instagram_feed": CropProfile(
        platform="instagram_feed",
        aspect_w=4, aspect_h=5,
        output_w=1080, output_h=1350,
        needs_crop=True, face_detection_required=True,
        max_duration_s=60,
    ),
    "youtube_shorts": CropProfile(
        platform="youtube_shorts",
        aspect_w=9, aspect_h=16,
        output_w=1080, output_h=1920,
        needs_crop=True, face_detection_required=True,
        max_duration_s=60,
    ),
    "youtube_standard": CropProfile(
        platform="youtube_standard",
        aspect_w=16, aspect_h=9,
        output_w=1920, output_h=1080,
        needs_crop=False, face_detection_required=False,
        max_duration_s=None,
    ),
    "facebook_reels": CropProfile(
        platform="facebook_reels",
        aspect_w=9, aspect_h=16,
        output_w=1080, output_h=1920,
        needs_crop=True, face_detection_required=True,
        max_duration_s=90,
    ),
    "linkedin": CropProfile(
        platform="linkedin",
        aspect_w=1, aspect_h=1,
        output_w=1080, output_h=1080,
        needs_crop=True, face_detection_required=True,
        max_duration_s=600,
    ),
}
```

## 10. Testing Strategy

### Unit Tests

Located in `tests/test_smart_crop.py`.

**Crop calculation tests** (no ML dependencies):

- `test_crop_region_9_16_face_centered` -- face at center, crop should center.
- `test_crop_region_9_16_face_left_edge` -- face near left edge, crop clamped
  to x=0.
- `test_crop_region_9_16_face_right_edge` -- face near right edge, crop clamped
  to max x.
- `test_crop_region_1_1_center` -- square crop centered on face.
- `test_crop_region_4_5` -- 4:5 crop centered on face.
- `test_crop_region_no_face_center_fallback` -- no faces detected, falls back
  to center crop.
- `test_crop_region_establishing_ignores_faces` -- establishing shot uses
  center crop regardless of face data.
- `test_safe_area_enforcement` -- face near edge triggers safe area adjustment.

**Multi-person tests**:

- `test_multi_face_largest_priority` -- largest face selected when no speaker
  diarization.
- `test_multi_face_centroid` -- centroid calculation for 3+ faces.
- `test_two_person_fits_square` -- two faces fit in 1:1 crop.
- `test_two_person_no_fit_vertical` -- two faces do not fit in 9:16, largest
  face selected.

**Transition tests**:

- `test_smooth_transition_generated` -- large position delta produces keyframes.
- `test_no_transition_small_delta` -- small position delta produces no
  transition.
- `test_transition_clamp` -- transition keyframes respect source bounds.
- `test_ease_in_out_values` -- easing function returns correct values at 0,
  0.25, 0.5, 0.75, 1.0.

**FFmpeg filter tests**:

- `test_static_crop_filter_string` -- single keyframe produces simple crop
  expression.
- `test_animated_crop_filter_string` -- multiple keyframes produce
  expression-based crop.

### Integration Tests

- `test_face_detection_jpeg` -- run MediaPipe on a synthetic test image with a
  drawn face circle. Verify bounding box is returned.
- `test_face_detection_no_face` -- run on a blank image. Verify empty result.
- `test_crop_filter_renders` -- generate a crop filter string and run it through
  FFmpeg on a test video to verify it produces valid output.

### Visual Inspection

For manual QA during development:

- Generate crop region visualizations: overlay the crop rectangle on the source
  key frame and save as a PNG. Compare face position to crop boundaries.
- Render a 5-second test clip at each target aspect ratio and visually confirm
  the speaker remains in frame.

### Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| No faces detected | Center crop (default) |
| Face at extreme left/right edge | Crop clamped to source bounds; face may be at edge of crop |
| Face larger than crop window | Center crop on face center; face will be partially cropped (acceptable for extreme closeups) |
| Very small face in wide shot | Use face position but do not zoom; crop may not visually center on face |
| Non-16:9 source video | Recalculate crop window dimensions from actual source aspect ratio |
| Portrait (9:16) source | No crop needed for vertical targets; crop horizontally for 16:9/1:1 |
| Multiple faces, all same size | Use centroid of all face centers |
| Face detection model not installed | Log warning, fall back to center crop, mark scene for human review |
