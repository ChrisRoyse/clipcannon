# Automated Video Editing Pipeline Plan

## The Problem
The AI (Claude) manually measures pixel coordinates for every segment, guessing screen content positions. This fails because:
1. Screen content changes every second as the speaker navigates/scrolls
2. Manual pixel measurement doesn't scale beyond 1-minute videos
3. A 2-hour video would require thousands of manual coordinate measurements
4. Human-level editing requires matching visual changes to speech in real-time

## The Solution: Automated Analysis Pipeline

Instead of the AI manually measuring coordinates per-segment, we need a **pre-processing pipeline** that automatically analyzes every frame and produces a structured "scene map" the AI can use directly. The AI's job becomes editorial (choosing WHAT to show) rather than technical (measuring WHERE things are).

## Architecture

```
Source Video (2 hours, 16:9)
    │
    ▼
┌─────────────────────────────────┐
│  AUTOMATED ANALYSIS PIPELINE    │
│  (runs once, ~5min per hour)    │
├─────────────────────────────────┤
│                                 │
│  1. Scene Detection             │  PySceneDetect → scene boundaries
│  2. Face Detection Per Scene    │  MediaPipe → face bbox per scene
│  3. Webcam Region Detection     │  Heuristic → webcam overlay bounds
│  4. Content Region Detection    │  Frame differencing → where content changes
│  5. Layout Classification       │  Rules → which layout fits each scene
│  6. Screen Content OCR          │  EasyOCR → what text is visible
│                                 │
├─────────────────────────────────┤
│                                 │
│  OUTPUT: scene_map.json         │
│                                 │
│  For EVERY scene:               │
│  - start_ms, end_ms             │
│  - face_bbox (x,y,w,h)         │
│  - webcam_region (x,y,w,h)     │
│  - content_region (x,y,w,h)    │  ← Main content area, auto-measured
│  - layout_recommendation        │  ← A, B, C, or D
│  - canvas_regions []            │  ← Ready-to-use coordinates
│  - visible_text                 │  ← OCR of what's on screen
│  - content_type                 │  ← website, dashboard, document, code
│                                 │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  AI EDITORIAL DECISIONS         │
│  (Claude uses scene_map)        │
├─────────────────────────────────┤
│                                 │
│  - Select best scenes for clip  │  Based on transcript + highlights
│  - Choose layout per scene      │  From pre-computed recommendations
│  - Use canvas_regions directly  │  No manual coordinate measurement
│  - Add overlays, color, etc.    │  Creative decisions only
│                                 │
└─────────────────────────────────┘
    │
    ▼
  Rendered TikTok/Reel/Short
```

## What the AI Gets (scene_map example)

```json
{
  "scenes": [
    {
      "scene_id": 1,
      "start_ms": 0,
      "end_ms": 8310,
      "duration_ms": 8310,
      "transcript": "I added a whole new feature to the OCR Providence MCP AI memory system.",
      "face": {"x": 1972, "y": 1057, "w": 306, "h": 306, "confidence": 0.95},
      "webcam_region": {"x": 1580, "y": 530, "w": 980, "h": 910},
      "content_region": {"x": 300, "y": 160, "w": 1050, "h": 600},
      "content_type": "website",
      "visible_text": ["Your Documents Deserve a Vault", "ocrprovenance.com", "153 AI-powered tools"],
      "layout_recommendation": "A",
      "canvas_regions_A": [
        {"region_id": "speaker", "source_x": 1200, "source_y": 650, "source_width": 1360, "source_height": 790, "output_x": 0, "output_y": 0, "output_width": 1080, "output_height": 576, "z_index": 2, "fit_mode": "cover"},
        {"region_id": "screen", "source_x": 300, "source_y": 160, "source_width": 1050, "source_height": 600, "output_x": 0, "output_y": 576, "output_width": 1080, "output_height": 1344, "z_index": 1, "fit_mode": "cover"}
      ],
      "canvas_regions_D": [
        {"region_id": "speaker_full", "source_x": 1580, "source_y": 530, "source_width": 980, "source_height": 910, "output_x": 0, "output_y": 0, "output_width": 1080, "output_height": 1920, "z_index": 1, "fit_mode": "cover"}
      ]
    }
  ]
}
```

**The AI never measures coordinates.** It just picks scenes and uses pre-computed canvas_regions.

## Implementation: New Pipeline Stage + MCP Tool

### Stage: `clipcannon_analyze_scenes` (new pipeline stage)

Runs after frame extraction. Processes every extracted frame to build the scene map.

**Algorithm per frame:**

1. **Scene boundary detection**: Compare frame N to frame N-1 using structural similarity (SSIM). If SSIM < 0.85, it's a new scene.

2. **Face detection**: Run MediaPipe on each scene's representative frame. Store face bbox.

3. **Webcam region detection**:
   - If face is detected in a corner (bottom-right, top-right, etc.), that's the webcam
   - The webcam region = bounding box around the face expanded to include shoulders/mic
   - Consistent across scenes (webcam doesn't move)

4. **Content region detection**:
   - Content area = everything EXCEPT: browser chrome (top 160px), taskbar (bottom 50px), webcam overlay, OS dock
   - For each scene, compare consecutive frames to find WHERE content is changing (scrolling, clicking)
   - The changing region = the active content area
   - Use frame differencing: `abs(frame_N - frame_N-1)` → find bounding box of changed pixels

5. **Layout recommendation**:
   - If face is large (>20% of frame) and no screen content → Layout D (full face)
   - If screen content has text/UI visible → Layout A (30/70 split)
   - If screen content is code/document → Layout A with zoomed content crop
   - First 3 seconds → always Layout D (hook)
   - Last 3-5 seconds → always Layout D (CTA)

6. **Pre-compute canvas_regions** for each layout type (A, B, C, D) using the detected face and content positions. The AI just picks which one to use.

### MCP Tool: `clipcannon_get_scene_map`

Returns the complete scene map for the project. One call gives the AI everything it needs:
- Every scene with boundaries
- Pre-computed canvas regions for every layout type
- Transcript aligned to scenes
- Content type classification
- Visible text (OCR)

### MCP Tool: `clipcannon_auto_edit`

Given a target platform and duration, automatically selects the best scenes based on:
- Highlight scores
- Transcript keyword relevance
- Content variety (don't repeat same screen)
- Pacing rules (visual change every 3-8 seconds)

Returns a ready-to-render EDL with canvas regions already filled in.

## Technology Stack

All LOCAL processing, no API calls:

| Component | Library | Purpose | GPU? |
|-----------|---------|---------|------|
| Scene detection | PySceneDetect or SSIM | Find scene boundaries | No |
| Face detection | MediaPipe BlazeFace | Face bounding boxes | CPU |
| Content detection | OpenCV frame differencing | Active content areas | No |
| OCR | EasyOCR (already installed) | Read visible text | GPU |
| Layout rules | Python logic | Recommend layouts | No |
| Canvas computation | measure_layout.py (existing) | Compute coordinates | No |

## Scaling Analysis

| Video Length | Frames (2fps) | Analysis Time (est.) | Scene Map Size |
|-------------|---------------|---------------------|----------------|
| 1 minute | 120 | ~15 seconds | ~5 KB |
| 10 minutes | 1,200 | ~2 minutes | ~50 KB |
| 1 hour | 7,200 | ~10 minutes | ~300 KB |
| 2 hours | 14,400 | ~20 minutes | ~600 KB |

Analysis runs ONCE per video. After that, the AI can create unlimited edits from the scene map without re-analyzing.

## What Changes for the AI

**Before (current, broken):**
1. Look at storyboard thumbnail (blurry)
2. Guess screen content position
3. Manually specify source_x, source_y, source_w, source_h
4. Render → wrong content shown → iterate
5. Repeat 5-10 times per segment

**After (automated):**
1. Call `clipcannon_get_scene_map` → get all scenes with pre-computed coordinates
2. Call `clipcannon_auto_trim` → get segments without fillers
3. Pick scenes that match transcript topics
4. Use `canvas_regions_A` directly from scene map (no manual measurement)
5. Add overlays, color → render → correct on first try

## Implementation Priority

1. **Scene boundary detection** (frame SSIM comparison) - stops the "screen changed mid-segment" problem
2. **Content region detection** (frame differencing) - stops the "wrong area cropped" problem
3. **Pre-computed canvas regions** per scene - stops the "manual coordinate measurement" problem
4. **Scene map MCP tool** - gives AI everything in one call
5. **Auto-edit tool** - fully automated clip creation

## Files to Create

- `src/clipcannon/pipeline/scene_analysis.py` - Scene detection + content region analysis
- `src/clipcannon/editing/scene_map.py` - Scene map builder, layout recommender, canvas pre-computation
- `src/clipcannon/tools/scene_tools.py` - MCP tools for get_scene_map and auto_edit
- `src/clipcannon/tools/scene_defs.py` - Tool definitions

## Database Changes

New table: `scene_map`
```sql
CREATE TABLE scene_map (
    scene_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    face_x INTEGER, face_y INTEGER, face_w INTEGER, face_h INTEGER,
    face_confidence REAL,
    webcam_x INTEGER, webcam_y INTEGER, webcam_w INTEGER, webcam_h INTEGER,
    content_x INTEGER, content_y INTEGER, content_w INTEGER, content_h INTEGER,
    content_type TEXT,
    visible_text TEXT,  -- JSON array of detected text
    layout_recommendation TEXT,
    canvas_regions_json TEXT,  -- Pre-computed canvas regions for all layout types
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);
```
