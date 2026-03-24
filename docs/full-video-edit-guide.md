# ClipCannon Full Video Edit Guide

Complete walkthrough of transforming an 8-minute 4K screen recording with webcam overlay into a polished 9:16 vertical video using ClipCannon's 39 MCP tools.

**Source:** `03222026clipcannonpreview.mp4` — 8:02, 3840x2160, 60fps, 3.6GB
**Output:** 7:14 (434s), 1080x1920, 33 segments, 456 captions, 608MB

---

## Phase 1: Understand the Video

### Step 1: Create Project & Ingest

```
project_create(name, source_video_path)
  → proj_7a5f4d43, 482928ms, 3840x2160, 60fps

ingest(project_id)
  → 22 pipeline stages, all passed
```

Ingest runs the full analysis pipeline: WhisperX transcription, scene detection, face/webcam detection, emotion analysis, beat detection, OCR, topic modeling, and Qwen3-8B narrative analysis.

### Step 2: Pull All Understanding Data (3 calls in parallel)

```
get_editing_context(project_id)
  → narrative analysis, speaker breakdown, data manifest

get_transcript(project_id)
  → 86 segments, full word-level transcript

get_scene_map(project_id, start_ms=0)
  → 63 scenes (first 5 minutes)
get_scene_map(project_id, start_ms=300000)
  → 67 scenes (remaining 3 minutes)
```

### Step 3: Analyze the Story Structure

From the data, identify:

| Element | Finding |
|---------|---------|
| **PROMISE** (0-6s) | "I built the world's first video editor specifically designed for AI agents" |
| **PAYOFF** (344-425s) | Rendered 9:16 demo playing — face moved, captions added, smart cropping, zero human intervention |
| **Chapter 1** (~0-99s) | Technical capabilities, claims |
| **Transition** (~99s) | "AI scales, humans don't" (philosophical) |
| **Chapter 2** (~99-155s) | AI scaling, "everything can be broken down mathematically" |
| **Transition** (~155s) | "Let me show you the video" |
| **Chapter 3** (~155-344s) | Base video demo, Claude Code terminal walkthrough |
| **Transition** (~344s) | "Let's go check out what that rendered video looks like" |
| **Chapter 4** (~344-425s) | Rendered demo video playing in VLC |
| **CTA** (~425-468s) | "This is ClipCannon... world's first... after one day" |

### Step 4: Classify Scene Dominance

For each scene range, determine what the viewer needs to see:

| Time Range | What's Happening | Layout Decision |
|------------|-----------------|-----------------|
| 0-155s | Face talking TO camera, file explorer in background | Face dominant (Layout D/B) |
| 155-210s | Showing base video, navigating | Screen reference (Layout A) |
| 210-344s | Claude Code terminal with MCP commands/JSON | Screen dominant (Layout A, zoom into code) |
| 344-425s | Rendered demo video playing in VLC | Full screen + PIP (Layout C) |
| 425-468s | CTA, direct address | Face dominant (Layout D/B) |

### Step 5: Analyze Key Frames

```
analyze_frame(project_id, timestamp_ms=230000)
  → Terminal content at x=100-2600, y=50-1700

analyze_frame(project_id, timestamp_ms=360000)
  → VLC player area centered around x=1400-2200, y=64-1800
```

Use these coordinates to set screen source regions for different content types.

---

## Phase 2: Plan the Edit

### Step 6: Auto-Trim for Natural Segments

```
auto_trim(project_id, pause_threshold_ms=1000)
  → 44 segments
  → 56 fillers removed, 7 pauses removed
  → 6.62% time saved (32s)
```

Use `pause_threshold_ms=1000` (gentle) to only remove pauses over 1 second. This preserves natural breathing room while cutting dead air.

### Step 7: Find Audio-Safe Cut Points

```
find_safe_cuts(project_id)
  → 51 safe cuts, sorted by safety score (100 = safest)
```

Use these for layout change boundaries, NOT for content removal. Safe cuts are where sentence endings, silence gaps, beat positions, and scene boundaries align.

Key safe cuts used:
- 122784ms (score 100): "scaling potential." → Chapter transition
- 155824ms (score 90): "lens of embedders." → Demo transition
- 166320ms (score 95): "base video first." → Video demo start
- 339888ms (score 75): "insane editor." → Rendered demo transition

### Step 8: Design 33 Segments with Per-Segment Canvas

**Canvas regions are fully dynamic, not templates.** Each `CanvasRegion` takes arbitrary pixel coordinates — any source rectangle can be placed at any output position with any size. The system supports unlimited regions per segment, keyframe animation, z-index layering, opacity, borders, and corner radius.

For this edit, I used 4 common patterns for editorial consistency, but every segment can (and some do) deviate with unique coordinates. For example, segments 17-18 and 22-23 use a tighter screen crop `(100, 50, 2600, 1500)` to zoom into the terminal code area, while segments 25-29 use `(1000, 0, 1800, 1800)` to frame the VLC player window.

The patterns below are starting points — adjust coordinates per-segment based on `analyze_frame` results for where content actually appears.

**Pattern D (Face 65% + Screen 35%)** — For bold claims, direct address:
```json
{
  "regions": [
    {"region_id": "face", "role": "speaker",
     "source_x": 2718, "source_y": 1474, "source_width": 831, "source_height": 686,
     "output_x": 0, "output_y": 0, "output_width": 1080, "output_height": 1248,
     "fit_mode": "cover"},
    {"region_id": "bg", "role": "screen",
     "source_x": 0, "source_y": 0, "source_width": 2718, "source_height": 1474,
     "output_x": 0, "output_y": 1248, "output_width": 1080, "output_height": 672,
     "fit_mode": "cover"}
  ]
}
```

**Layout B (Face 40% + Screen 60%)** — For talking with screen context:
```json
{
  "regions": [
    {"region_id": "face", "role": "speaker",
     "source_x": 2718, "source_y": 1474, "source_width": 831, "source_height": 686,
     "output_x": 0, "output_y": 0, "output_width": 1080, "output_height": 768,
     "fit_mode": "cover"},
    {"region_id": "screen", "role": "screen",
     "source_x": 0, "source_y": 0, "source_width": 2718, "source_height": 1474,
     "output_x": 0, "output_y": 768, "output_width": 1080, "output_height": 1152,
     "fit_mode": "contain"}
  ]
}
```

**Layout A (Face 30% + Screen 70%)** — For screen-dominant demos:
```json
{
  "regions": [
    {"region_id": "face", "role": "speaker",
     "source_x": 2718, "source_y": 1474, "source_width": 831, "source_height": 686,
     "output_x": 0, "output_y": 0, "output_width": 1080, "output_height": 576,
     "fit_mode": "cover"},
    {"region_id": "screen", "role": "screen",
     "source_x": 0, "source_y": 0, "source_width": 2718, "source_height": 1474,
     "output_x": 0, "output_y": 576, "output_width": 1080, "output_height": 1344,
     "fit_mode": "contain"}
  ]
}
```

**Layout A with Code Zoom** — For terminal sections (tighter screen crop):
Same as Layout A but screen source: `source_x: 100, source_y: 50, source_width: 2600, source_height: 1500`

**Layout C (Full Screen + PIP Face)** — For VLC demo playback:
```json
{
  "regions": [
    {"region_id": "screen", "role": "screen",
     "source_x": 1000, "source_y": 0, "source_width": 1800, "source_height": 1800,
     "output_x": 0, "output_y": 96, "output_width": 1080, "output_height": 1632,
     "fit_mode": "contain"},
    {"region_id": "pip", "role": "speaker",
     "source_x": 2718, "source_y": 1474, "source_width": 831, "source_height": 686,
     "output_x": 740, "output_y": 40, "output_width": 300, "output_height": 248,
     "fit_mode": "cover"}
  ]
}
```

### Complete Segment Map

| # | Source Range (ms) | Layout | Speed | Notes |
|---|-------------------|--------|-------|-------|
| 1 | 0-6190 | D | 1.0 | Hook: "world's first video editor" |
| 2 | 6190-14270 | B | 1.0 | "Claude Code can now edit my videos" |
| 3 | 14270-37570 | D | 1.0 | "TikTok, Instagram, insane, math" |
| 4 | 37830-43250 | D | 1.0 | "see world through embedders" |
| 5 | 44110-66090 | B | 1.0 | "12 embedders, tools, AI full control" |
| 6 | 66330-67010 | B | 1.0 | "everything" bridge |
| 7 | 67310-90430 | D | 1.0 | "create videos, clips, branding" |
| 8 | 90930-108570 | D | 1.0 | "AI scales, humans don't" |
| 9 | 108870-121650 | D | 1.0 | "jump past equal, scaling" |
| 10 | 125920-135168 | D | 1.0 | "everything broken down mathematically" |
| 11 | 136480-155824 | B | 1.0 | "psychological traits, embedders" |
| 12 | 156510-166320 | B | 1.0 | "let me show you" (crossfade 300ms) |
| 13 | 166330-191770 | A | 1.0 | Base video demo |
| 14 | 192670-200970 | A | 1.3 | Navigate video (speed up) |
| 15 | 202150-203810 | A | 1.3 | "what's happening on screen" |
| 16 | 204030-213110 | A | 1.2 | "Claude created TikTok video" |
| 17 | 213930-233460 | A-zoom | 1.0 | MCP commands, scene map |
| 18 | 234500-256450 | A-zoom | 1.0 | Token efficiency discussion |
| 19 | 257250-268750 | D | 1.0 | "world's first, took me a day" |
| 20 | 269590-276930 | D | 1.0 | "not even Adobe, agentic genie" |
| 21 | 277250-290450 | D | 1.0 | "embedding lens, capabilities" |
| 22 | 290890-313550 | A-zoom | 1.2 | Demo: edits, clips, zooms |
| 23 | 314110-338890 | A-zoom | 1.0 | Color, overlays, audio plans |
| 24 | 339330-344830 | B | 1.0 | "let's check rendered video" (crossfade) |
| 25 | 345190-346680 | C | 1.0 | "from that three minute video" |
| 26 | 346920-358120 | C | 1.0 | Rendered video playing |
| 27 | 358760-371960 | C | 1.0 | "AI added captions, moved face" |
| 28 | 377010-386450 | C | 1.0 | "dashboard, showing what you need" |
| 29 | 387570-419840 | C | 1.0 | "AI markdown zoom, choosing, 100% AI" |
| 30 | 420992-425312 | D | 0.85 | "no human in the loop" (CLIMAX, slow-mo) |
| 31 | 427136-431020 | D | 1.0 | "video is amazing, AI can reason" |
| 32 | 431480-465600 | B | 1.0 | "story, ClipCannon, world's first" |
| 33 | 466656-469000 | D | 1.0 | "next week" (fade out 500ms) |

### Speed Strategy

| Speed | When to Use | Why |
|-------|------------|-----|
| 1.0 | Important claims, hook, CTA | Full clarity |
| 1.2 | Scrolling through code/demo | Tighten without losing context |
| 1.3 | Navigating between screens | Cut dead navigation time |
| 0.85 | "No human in the loop" climax | Emphasis via slight slow-motion |

### Transition Strategy

| Transition | When | Duration |
|-----------|------|----------|
| Hard cut | Between same-type layouts | 0ms (default) |
| Crossfade | Chapter boundaries (seg 12, 24) | 300ms |
| Fade to black | End of video (seg 33) | 500ms |

---

## Phase 3: Create the Edit

### Step 9: Create Edit with All Segments

```
create_edit(
  project_id, name, target_platform="youtube_standard",
  canvas={enabled: true, canvas_width: 1080, canvas_height: 1920},
  captions={enabled: true, style: "word_highlight", position: "bottom", font_size: 42},
  segments=[...33 segments with per-segment canvas...]
)
```

**Platform note:** Use `youtube_standard` for full-length videos (no duration limit). The 9:16 canvas is set manually via the canvas spec. TikTok platform enforces 180s max which is too short for a full-story video.

**Result:** 33 segments, 434s total, 456 auto-generated caption chunks.

### Step 10: Apply All Effects (22 parallel calls)

All of the following were called in a single parallel batch:

**Audio Cleanup:**
```
audio_cleanup(project_id, edit_id, operations=["noise_reduction", "normalize_loudness"])
```

**Background Music:**
```
generate_music(
  project_id, edit_id,
  prompt="subtle ambient electronic background, 100 BPM, warm pads, minimal",
  duration_s=300,  # max allowed; loops during render
  volume_db=-24    # barely audible under speech
)
```

**6 Overlays:**

| Type | Text | Timing | Position | Animation |
|------|------|--------|----------|-----------|
| lower_third | "ClipCannon / World's First AI Video Editor" | 1-6s | bottom_left | slide_up |
| title_card | "12 AI Embedders" | 44-46s | center | fade_in, 48px |
| title_card | "AI Scales. Humans Don't." | 104-107s | center | fade_in, 52px |
| title_card | "World's First AI Agent Video Editing Software" | 258-261s | center | fade_in, 44px |
| title_card | "100% AI. No Human In The Loop." | 393-396s | center | fade_in, 48px |
| cta | "Send this to a developer who needs this" | 426-434s | bottom_center | fade_in, #FF0050 |

**5 Motion Effects:**

| Segment | Effect | Scale | Easing | Why |
|---------|--------|-------|--------|-----|
| 1 (hook) | zoom_in | 1.0→1.15 | ease_out | Draw viewer in |
| 4 (embedders) | zoom_in | 1.0→1.1 | ease_out | Subtle emphasis |
| 8 (AI scales) | zoom_in | 1.0→1.15 | ease_out | Key claim emphasis |
| 10 (math) | zoom_in | 1.0→1.1 | ease_out | Vision statement |
| 30 (climax) | zoom_in | 1.0→1.15 | ease_out | "No human" climax |

**5 Color Grades:**

| Segment | Contrast | Saturation | Mood |
|---------|----------|------------|------|
| 1 (hook) | 1.15 | 1.2 | Warm, inviting |
| 8 (AI scales) | 1.25 | 1.2 | Punchy, bold |
| 10 (math) | 1.25 | 1.2 | Punchy, bold |
| 30 (climax) | 1.25 | 1.2 | Punchy, bold |
| 33 (CTA) | 1.15 | 1.2 | Warm (matches hook) |

**4 Sound Effects:**
```
generate_sfx: whoosh (400ms), impact (300ms), riser (800ms), chime (500ms)
```

---

## Phase 4: Render & Verify

### Step 11: Render

```
render(project_id, edit_id)
  → render_1c9d2028e12e, 434s, 608MB, ~15 min render time
```

### Step 12: Frame Inspection (10 checkpoints)

```
get_frame(project_id, render_id, timestamp_ms) at:
  2s, 6.5s, 45s, 104s, 183s, 333s, 350s, 393s, 430s, 433.5s
```

| Checkpoint | What to Verify | Result |
|-----------|----------------|--------|
| 2s (Hook) | Face visible, caption readable, lower third showing | PASS |
| 6.5s (Layout switch) | Clean D→B transition | PASS |
| 45s (12 embedders) | Title card centered and readable | PASS |
| 104s (AI scales) | Face dominant with zoom, caption synced | PASS |
| 183s (Demo start) | Screen content (dashboard) visible 70% | PASS |
| 333s (VLC demo) | PIP face + demo video in main area | PASS |
| 350s (Moved face) | Demo shows repositioned face + site | PASS |
| 393s (Climax) | Face dominant, zoom, punchy color | PASS |
| 430s (CTA) | Face visible, red CTA text at bottom | PASS |
| 433.5s (Last frame) | Fade starting, matches hook energy | PASS |

---

## Phase 5: Sync Bug Discovery & Fix

### The Problem

After reviewing the v1 render, captions progressively drifted ahead of audio. The drift worsened over the video's 7+ minute runtime, becoming clearly visible by the 4-minute mark (~200-350ms ahead).

### Root Cause Investigation

Two compounding issues were identified:

**Issue 1: Integer Truncation in Caption Timestamps (70% of drift)**

In `captions.py:324-338`, `_remap_single_chunk()` used `int()` to truncate fractional milliseconds when dividing by non-integer speeds (1.3, 1.2, 0.85):

```python
# BEFORE (broken):
offset_in_output = int(offset_in_source / seg.speed)  # loses 0.1-0.7ms per word
```

Over 456 caption chunks across 33 segments, this compounded to 200-400ms of drift.

Similarly, `edl.py:200` truncated segment durations:
```python
# BEFORE:
return int(self.source_duration_ms / self.speed)
```

And `editing_helpers.py:184` accumulated these truncated values:
```python
# BEFORE:
output_cursor_ms = 0  # integer accumulator
output_cursor_ms += seg.output_duration_ms  # compounds truncation
```

**Issue 2: AAC Codec Frame Padding (30% of drift)**

FFmpeg's AAC encoder pads each audio segment's final frame with silence (~23ms per segment). Across 33 segments, this adds ~760ms of accumulated audio shift. Known FFmpeg bug (Trac #4676, unresolved).

### Fixes Applied

**File 1: `captions.py` — Lines 324, 329, 336, 338**
```python
# AFTER (fixed):
offset_in_output = round(offset_in_source / seg.speed)
output_dur = round(chunk_source_dur / seg.speed)
w_out_start = seg.output_start_ms + round(w_offset / seg.speed)
w_out_end = w_out_start + round(w_dur / seg.speed)
```

**File 2: `edl.py` — Line 200**
```python
# AFTER:
return round(self.source_duration_ms / self.speed)
```

**File 3: `editing_helpers.py` — Lines 184-218**
```python
# AFTER: Float accumulator with overlap clamping
output_cursor_f: float = 0.0  # precise float accumulation

for idx, raw in enumerate(raw_segments, start=1):
    output_start = round(output_cursor_f)
    if specs:
        prev_end = specs[-1].output_start_ms + specs[-1].output_duration_ms
        if output_start < prev_end:
            output_start = prev_end  # clamp to prevent 1ms rounding overlaps

    seg = SegmentSpec(output_start_ms=output_start, ...)
    output_cursor_f += (source_end - source_start) / speed
```

**File 4: `ffmpeg_cmd.py` — Lines 308-368**

Combined two setpts passes into one expression:
```python
# AFTER: single PTS expression
if seg.speed != 1.0:
    pts_expr = f"(PTS-STARTPTS)/{seg.speed}"
else:
    pts_expr = "PTS-STARTPTS"
vchain = f"[0:v]trim=...,setpts={pts_expr}..."
```

Added audio resync filter after concat:
```python
# AFTER: force audio to resync with video PTS
if len(segments) > 1:
    sync_filter = f"[{final_audio}]aresample=async=1:first_pts=0[async_a]"
    filter_parts.append(sync_filter)
    final_audio = "async_a"
```

### Verification

- 294 tests pass after all fixes
- v2 render produced with corrected caption timestamps and audio sync
- MCP server requires restart between code changes and re-render

---

## Webcam Coordinates

The source video has a webcam overlay at a fixed position:
```
x=2718, y=1474, w=831, h=686  (in 3840x2160 source)
```

These coordinates came from the `get_scene_map` response's `webcam` field. Use these for ALL face crops — do NOT use face detection bounding boxes, which move frame-to-frame and cause jitter.

---

## Tool Call Summary

| Phase | Tools Used | Calls |
|-------|-----------|-------|
| Understand | project_create, ingest, get_editing_context, get_transcript, get_scene_map (x2), analyze_frame (x2) | 8 |
| Plan | auto_trim, find_safe_cuts | 2 |
| Build | create_edit | 1 |
| Effects | audio_cleanup, generate_music, add_overlay (x6), add_motion (x5), generate_sfx (x4), color_adjust (x5) | 22 |
| Render | render | 1 |
| Verify | get_frame (x10) | 10 |
| **Total** | | **44** |

---

## Key Decisions & Rationale

1. **Keep FULL story** — No content removed for length. auto_trim only removes fillers/pauses (6.6% saved). Every segment of narration preserved.

2. **33 segments, not fewer** — Each segment gets its own canvas. Static layouts are boring. 33 gives enough variety without being chaotic.

3. **Face dominant for claims, screen dominant for demos** — Match the layout to what the viewer needs to see RIGHT NOW. If the speaker is making a bold claim, face should fill the frame. If they're showing code, screen should dominate.

4. **Speed changes for navigation only** — 1.2-1.3x for "dead" navigation time (clicking, scrolling). Never speed up important speech. 0.85x slow-mo ONLY for the single climax moment.

5. **Music at -24dB** — If you can hear the music over speech, it's too loud. Background music adds atmosphere, not distraction.

6. **youtube_standard platform** — TikTok enforces 180s max. For full-length 9:16 content, use youtube_standard with manual canvas dimensions.

7. **Crossfade only at chapter boundaries** — Overusing transitions looks amateur. Hard cuts (default) are professional. Crossfades mark major topic changes.

8. **Warm color for hook/CTA, punchy for claims** — Creates a visual loop (warm→neutral→punchy→neutral→warm) that subconsciously connects the opening and closing.
