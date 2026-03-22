# ClipCannon System Refactor: Automated Scene Analysis Pipeline

## Current State: 50 tools, manual coordinate guessing
## Target State: ~30 tools, zero coordinate guessing, unlimited video length

---

## Tool Audit: Keep, Remove, or Consolidate

### KEEP (Core, no changes needed) - 18 tools
| Tool | Why Keep |
|------|---------|
| `project_create` | Essential |
| `project_open` | Essential |
| `project_list` | Essential |
| `project_status` | Essential |
| `project_delete` | Essential |
| `ingest` | Essential - add scene_analysis as new pipeline stage |
| `create_edit` | Essential |
| `modify_edit` | Essential |
| `list_edits` | Essential |
| `render` | Essential |
| `render_status` | Essential |
| `render_batch` | Essential |
| `credits_balance` | Essential |
| `credits_estimate` | Essential |
| `credits_history` | Essential |
| `spending_limit` | Essential |
| `config_get` | Essential |
| `config_list` | Essential |

### KEEP (Valuable features) - 8 tools
| Tool | Why Keep |
|------|---------|
| `auto_trim` | Filler/pause removal - works great |
| `color_adjust` | Color grading - now renders correctly |
| `add_overlay` | Text overlays - now renders correctly |
| `add_motion` | Motion effects - stored in EDL |
| `audio_cleanup` | FFmpeg audio processing |
| `generate_sfx` | DSP sound effects |
| `compose_midi` | MIDI music |
| `generate_metadata` | Platform metadata |

### REMOVE (Replaced by scene_map) - 7 tools
| Tool | Why Remove | Replacement |
|------|-----------|-------------|
| `analyze_frame` | Heuristic region detection → scene_map does this automatically per scene | `get_scene_map` |
| `measure_layout` | Manual face detection per timestamp → scene_map pre-computes for every scene | `get_scene_map` |
| `get_editing_context` | Consolidation of data AI needs → scene_map provides everything | `get_scene_map` |
| `get_storyboard` | AI visual review tool → scene_map gives structured data, storyboard becomes optional debug tool | Keep as internal only |
| `preview_layout` | Manual coordinate validation → unnecessary when coordinates are pre-computed | Validation built into scene_map |
| `get_frame_strip` | Already removed | N/A |
| `get_storyboard_grids` | Already removed | N/A |

### REMOVE (Rarely used or redundant) - 5 tools
| Tool | Why Remove | Replacement |
|------|-----------|-------------|
| `config_set` | Rarely needed by AI | Keep config_get and config_list only |
| `remove_region` | Delogo - niche use | Keep in codebase but don't register as MCP tool |
| `extract_subject` | Background removal - long processing, rarely needed per-edit | Keep in codebase but run manually |
| `replace_background` | Background replacement - depends on extract_subject | Keep in codebase but run manually |
| `inspect_render` | Post-render verification - AI can use get_frame on rendered output | Use get_frame on output path |

### CONSOLIDATE - 12 tools → 4
| Current Tools | New Tool | Why |
|---------------|----------|-----|
| `get_vud_summary` + `get_analytics` + `get_transcript` + `get_segment_detail` + `search_content` + `get_frame` | `get_scene_map` | One call returns EVERYTHING: scenes, transcript, face positions, content regions, pre-computed layouts. AI never needs to make 6 separate calls. |
| `preview_layout` + `preview_clip` | `preview_edit` | Preview a specific segment of an edit at low quality. Uses the pre-computed canvas regions from the scene map. |
| `provenance_verify` + `provenance_query` + `provenance_chain` + `provenance_timeline` | `provenance_check` | One call for all provenance data. |
| `disk_status` + `disk_cleanup` | `disk_manage` | Combined disk management. |

---

## New Tool Architecture: ~30 tools

### Tier 1: Project Lifecycle (5 tools)
```
project_create → project_list → project_open → project_status → project_delete
```

### Tier 2: Analysis (2 tools - replaces 12 current tools)
```
ingest          → Runs full pipeline INCLUDING scene analysis
get_scene_map   → Returns EVERYTHING: scenes, transcript, face/content
                   regions, pre-computed canvas coords, OCR text, layout
                   recommendations. ONE CALL = full video understanding.
```

### Tier 3: Editing (7 tools)
```
auto_trim       → Remove fillers/pauses → returns clean segments
create_edit     → Create edit from segments (uses scene_map canvas regions)
modify_edit     → Update draft edit
list_edits      → List edits
color_adjust    → Apply color grading
add_overlay     → Add text overlays
add_motion      → Add motion effects
```

### Tier 4: Audio (3 tools)
```
audio_cleanup   → FFmpeg noise/hum/loudness
generate_sfx    → DSP sound effects
compose_midi    → MIDI composition
```

### Tier 5: Rendering (4 tools)
```
render          → Full quality render
render_batch    → Batch render
render_status   → Check render status
preview_edit    → Low-quality preview of specific edit segment
```

### Tier 6: Metadata & System (7 tools)
```
generate_metadata  → Platform titles/descriptions
credits_balance    → Credit balance
credits_estimate   → Cost estimate
credits_history    → Transaction history
spending_limit     → Set limit
config_get         → Get config
config_list        → List config
```

### TOTAL: ~28 tools (down from 50)

---

## The `get_scene_map` Tool: Heart of the System

This single tool replaces 12 current tools by returning EVERYTHING the AI needs in one call:

```json
{
  "project_id": "proj_xxx",
  "source": {
    "duration_ms": 7200000,
    "resolution": "2560x1440",
    "fps": 60
  },
  "webcam": {
    "detected": true,
    "corner": "bottom_right",
    "region": {"x": 1580, "y": 530, "w": 980, "h": 910},
    "consistent": true
  },
  "scenes": [
    {
      "id": 1,
      "start_ms": 0,
      "end_ms": 8310,
      "transcript": "I added a whole new feature...",
      "face": {"x": 1972, "y": 1057, "w": 306, "h": 306, "conf": 0.95},
      "content": {
        "region": {"x": 300, "y": 160, "w": 1050, "h": 600},
        "type": "website",
        "text": ["Your Documents Deserve a Vault", "ocrprovenance.com"]
      },
      "layout": "A",
      "canvas": {
        "A": {"speaker": {...}, "screen": {...}},
        "B": {"speaker": {...}, "screen": {...}},
        "C": {"screen": {...}, "pip": {...}},
        "D": {"speaker_full": {...}}
      }
    }
  ],
  "highlights": [...],
  "pacing": [...],
  "filler_words": [...],
  "silence_gaps": [...]
}
```

The AI reads this ONCE and has complete understanding of the entire video.

---

## Scene Analysis Pipeline (runs during `ingest`)

### New Pipeline Stage: `scene_analysis`

Added to the DAG after `frame_extract`. Runs automatically as part of `ingest`.

**Dependencies**: frame_extract, transcribe (for transcript alignment)

**Processing per frame (2fps):**

1. **SSIM scene detection** (OpenCV, CPU)
   - Compare each frame to previous using `cv2.matchTemplate` or SSIM
   - If similarity < 0.85 → new scene boundary
   - Output: list of (start_ms, end_ms) scene ranges

2. **Face detection per scene** (MediaPipe, CPU)
   - Run BlazeFace on the middle frame of each scene
   - Quadrant search for small faces (webcam overlays)
   - Output: face_bbox per scene

3. **Webcam detection** (heuristic, CPU)
   - If face is consistently in the same corner across scenes → it's a webcam overlay
   - Compute stable webcam bounding box (expanded from face to include shoulders)
   - Output: webcam_region (same for all scenes)

4. **Content region detection** (OpenCV frame differencing, CPU)
   - For each scene, compute `abs(frame_mid - frame_start)`
   - Find bounding box of pixels that changed significantly
   - Exclude: webcam region, browser chrome (top 160px), taskbar (bottom 50px)
   - Output: content_region per scene

5. **Content classification** (heuristic + OCR, GPU for OCR)
   - Run OCR on the content region of each scene's middle frame
   - Classify based on detected text: website, dashboard, document, code, terminal, presentation
   - Output: content_type, visible_text per scene

6. **Canvas pre-computation** (math, CPU)
   - For each scene, compute canvas_regions for layouts A, B, C, D
   - Uses face_bbox and content_region from steps 2-4
   - Uses measure_layout math (already implemented)
   - Output: ready-to-use canvas_regions per scene per layout

7. **Store in `scene_map` table**

### Performance

| Step | Per Frame | 420 Frames | 7200 Frames (1hr) |
|------|-----------|-----------|-------------------|
| SSIM | ~5ms | 2.1s | 36s |
| Face (per scene, not per frame) | ~50ms | ~5s (100 scenes) | ~50s (1000 scenes) |
| Frame diff | ~10ms | 4.2s | 72s |
| OCR (per scene) | ~200ms | ~20s | ~200s |
| Canvas math | ~1ms | 0.4s | 7s |
| **Total** | | **~32s** | **~6 min** |

---

## Technology: All Local, All Free

| Component | Library | License | GPU | Install |
|-----------|---------|---------|-----|---------|
| SSIM/Frame diff | OpenCV | BSD | No | Already installed |
| Face detection | MediaPipe | Apache-2.0 | CPU | Already installed |
| OCR | EasyOCR | Apache-2.0 | Optional | Already in pipeline |
| Scene detection | OpenCV SSIM | BSD | No | Already installed |
| Canvas math | Python | N/A | No | Already implemented |
| FFmpeg | FFmpeg | LGPL | NVENC | Already installed |

**Zero new dependencies.** Everything uses libraries already in the project.

---

## Migration: What Gets Deleted

### Files to DELETE
- `src/clipcannon/tools/storyboard.py` → functionality absorbed into scene_analysis
- `src/clipcannon/editing/measure_layout.py` → math moved into scene_map builder

### Files to CREATE
- `src/clipcannon/pipeline/scene_analysis.py` → New pipeline stage
- `src/clipcannon/editing/scene_map.py` → Scene map builder + layout pre-computation

### Files to MODIFY
- `src/clipcannon/pipeline/registry.py` → Register scene_analysis stage
- `src/clipcannon/db/schema.py` → Add scene_map table
- `src/clipcannon/tools/__init__.py` → Remove deprecated tools, add scene tools
- `src/clipcannon/tools/rendering.py` → Remove analyze_frame, measure_layout, get_storyboard, preview_layout. Add get_scene_map.
- `src/clipcannon/tools/editing.py` → Remove extract_subject, replace_background from MCP registration (keep code)

---

## AI Workflow: Before vs After

### BEFORE (current, 10+ tool calls, manual coordinates)
```
1. get_storyboard → see thumbnails (~6K tokens)
2. get_storyboard(start_s=50) → zoom in (~5K tokens)
3. get_frame(52000) → see full res frame
4. measure_layout(52000, "A") → get face coords
5. preview_layout(...manual coords...) → check layout
6. create_edit(...manual canvas regions...) → create
7. color_adjust → add color
8. add_overlay → add text
9. render → render
10. inspect_render → check output
11. REPEAT 5-10 times because coords were wrong
```

### AFTER (refactored, 3-5 tool calls, zero manual coordinates)
```
1. get_scene_map → EVERYTHING in one call
2. auto_trim → clean segments
3. create_edit(segments with scene_map canvas_regions) → create
4. render → render (correct on first try)
```

---

## Implementation Order

1. **Create scene_analysis.py** - SSIM scene detection + face detection + content region detection
2. **Create scene_map.py** - Build scene map with pre-computed canvas regions
3. **Add scene_map table** to schema.py
4. **Register scene_analysis** in pipeline registry (runs after frame_extract + transcribe)
5. **Create get_scene_map tool** - Returns complete scene map
6. **Remove deprecated tools** from MCP registration
7. **Test with real video** - Verify scene map is accurate
8. **Create edit using scene map** - Verify rendered output is correct

## Constitution Compliance

- All processing LOCAL (SEC-01) ✓
- Source files NEVER modified (SEC-02) ✓
- FFmpeg only renderer (ARCH-30) ✓
- Scene map stored in project DB (ARCH-01) ✓
- All libraries already installed or free/open-source ✓
- No API calls, no cloud services ✓
