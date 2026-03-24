# ClipCannon Iterative Edit-Review-Fix Architecture

**Status:** Plan
**Date:** 2026-03-24
**Context:** AI won't one-shot a video. But with the ability to iterate — render, review, give feedback, adjust specific things, re-render — it can produce excellent results. This document defines the architecture to make iterative editing a first-class capability.

---

## Problem Statement

The current system treats editing as a one-shot operation:
1. AI generates a full EDL with all segments, effects, captions
2. Render produces output
3. If anything is wrong, the AI must reproduce the ENTIRE edit from scratch

This is slow, expensive (2 credits per render), and fragile — the AI may not reproduce the good parts while fixing the bad parts.

## Design Principle

**Edits are living documents.** They can always be modified, versioned, branched, and incrementally re-rendered. The system should be optimized for the common case: "change one thing and re-render" — not the rare case: "build everything from scratch."

---

## Changes Already Implemented (This Session)

### 1. modify_edit Now Works on Any Edit Status
- **File:** `src/clipcannon/tools/editing.py`
- **Change:** Removed the `status == 'draft'` gate. Now only blocks modifications during active `rendering` state.
- **Behavior:** Modifying a rendered edit resets its status to `draft` for re-rendering.
- **Impact:** AI can now render → review → modify → re-render without manual DB resets.

### 2. Audio Mixing Integrated Into Render Pipeline
- **File:** `src/clipcannon/rendering/renderer.py`
- **Change:** Added `_prepare_mixed_audio()` method. After segment concatenation, queries `audio_assets` for the edit's music/SFX, extracts source audio, calls `mix_audio()` with speech-aware ducking, injects mixed audio into the final output.
- **Impact:** Background music and SFX now appear in rendered output.

### 3. Caption Boundary Clamping
- **File:** `src/clipcannon/editing/captions.py`
- **Change:** `_remap_single_chunk()` now clamps output timestamps to segment boundaries. Words past the boundary are dropped. Chunk text is rebuilt from surviving words.
- **Impact:** No more stale/mismatched captions spilling across segment cuts.

### 4. Audio-Aware Scene Detection
- **File:** `src/clipcannon/pipeline/scene_analysis.py`
- **Change:** Removed arbitrary 8-second max scene duration. Added `_snap_boundary_to_audio()` that snaps visual scene boundaries to the nearest silence gap or word boundary within 2s radius.
- **Impact:** Scene boundaries no longer cut mid-speech. Scenes can be any duration the visual content warrants.

---

## Planned Changes (Priority Order)

### P0: Edit Version History

**Goal:** Never lose a working edit. Every modification saves the previous state as a version.

**Schema addition:**
```sql
CREATE TABLE edit_versions (
    version_id TEXT PRIMARY KEY,
    edit_id TEXT NOT NULL,
    parent_version_id TEXT,
    version_number INTEGER NOT NULL,
    edl_json TEXT NOT NULL,
    change_description TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (edit_id) REFERENCES edits(edit_id)
);
CREATE INDEX idx_edit_versions ON edit_versions(edit_id, version_number);
```

**Behavior:**
- `modify_edit` saves current EDL to `edit_versions` before applying changes
- New tool: `clipcannon_edit_history(edit_id)` — list all versions with change descriptions
- New tool: `clipcannon_revert_edit(edit_id, version_number)` — restore a previous version
- The AI's change description is auto-generated from the diff (e.g., "Changed segment 3 speed from 1.15 to 1.0")

**Files to modify:**
- `src/clipcannon/db/schema.py` — add table
- `src/clipcannon/tools/editing.py` — save version in modify_edit
- `src/clipcannon/tools/editing_defs.py` — add new tool definitions
- `src/clipcannon/tools/discovery.py` — add history/revert handlers

---

### P1: Segment Render Cache (Partial Re-Rendering)

**Goal:** When one segment changes, only re-render that segment. Reuse cached segments for everything else.

**How it works:**
1. Each segment gets a content hash derived from: source_range, speed, crop, color, canvas, overlays, motion
2. After rendering a segment, cache it with its hash: `segment_cache/{hash}.mp4`
3. Before rendering, check cache: if hit, skip rendering that segment
4. Only concat + caption burn-in + audio mix runs every time

**Expected speedup:** For a 12-segment edit where 1 segment changed: ~11x faster re-render (render 1 segment instead of 12, concat is near-instant with stream copy).

**Schema addition:**
```sql
CREATE TABLE segment_cache (
    cache_hash TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    segment_spec_json TEXT NOT NULL,
    file_size_bytes INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    last_used_at TEXT DEFAULT (datetime('now'))
);
```

**Files to modify:**
- `src/clipcannon/rendering/renderer.py` — add cache check in `_render_segmented()`
- `src/clipcannon/db/schema.py` — add table

---

### P2: Change Impact Classification

**Goal:** `modify_edit` returns what needs re-rendering so the render can do minimal work.

**Classification matrix:**

| Change Type | Segments to Re-render | Caption Re-burn | Audio Re-mix |
|---|---|---|---|
| Caption text/style | None | Yes | No |
| Color grading (global) | All | Yes | No |
| Color grading (1 segment) | That segment only | Yes | No |
| Segment timing/speed | Changed segments | Yes | Yes |
| Audio volume/music | None | No | Yes |
| Overlay add/modify | Affected segments | No | No |
| Canvas/crop change | Affected segments | Yes | No |

**Implementation:** `modify_edit` returns a `render_hint` field:
```json
{
  "render_hint": {
    "segments_invalidated": [3],
    "captions_invalidated": true,
    "audio_invalidated": false
  }
}
```

The renderer uses this to skip unnecessary work.

**Files to modify:**
- `src/clipcannon/tools/editing.py` — compute render_hint from diff
- `src/clipcannon/rendering/renderer.py` — accept render_hint parameter

---

### P3: Feedback Intent Parser

**Goal:** New tool `clipcannon_apply_feedback` that translates natural language feedback into precise EDL changes.

**Examples:**
| Feedback | Parsed Intent | EDL Operation |
|---|---|---|
| "the cut at 0:15 is too abrupt" | transition_fix @ 15000ms | Add `crossfade 300ms` transition_in on segment at 15s |
| "too fast in the middle" | speed_adjust @ 40-60s | Reduce speed to 0.9x on segments in that range |
| "make the text bigger" | caption_resize | Increase caption font_size |
| "the speaker is too small in the intro" | canvas_resize @ 0-8s | Increase speaker region output dimensions |
| "remove the part where they stumble" | segment_trim @ detected_filler | Remove/shorten segment containing the specified content |
| "the music is too loud" | audio_adjust | Lower music volume_db by 3-6dB |
| "zoom in when they show the dashboard" | motion_add @ content_match | Add zoom_in motion to segment containing "dashboard" |

**Implementation approach:**
- Parse feedback text into structured intent using pattern matching + transcript search
- Map intent to specific `modify_edit` changes
- Apply via existing modify_edit pipeline (gets version history for free)

**New file:** `src/clipcannon/tools/feedback.py`

---

### P4: Edit Branching for Platform Variants

**Goal:** Fork an edit into platform-specific variants that share the same base but diverge on platform-specific settings.

**Use case:** Start with a TikTok edit, branch to Instagram Reels (different duration limits, different aspect ratio handling), YouTube Shorts (different caption style). Each branch can be independently refined.

**Schema addition:**
```sql
ALTER TABLE edits ADD COLUMN parent_edit_id TEXT;
ALTER TABLE edits ADD COLUMN branch_name TEXT DEFAULT 'main';
```

**New tools:**
- `clipcannon_branch_edit(edit_id, branch_name, target_platform)` — clone edit with platform adjustments
- `clipcannon_list_branches(edit_id)` — show all branches

---

### P5: Targeted Preview

**Goal:** Preview a specific segment or timestamp range at low quality before committing to a full render.

**Current state:** `preview_clip` exists but only previews from the source video, not from an edit. Need to extend it to render a single segment from an edit at 540p for quick validation.

**New tool:** `clipcannon_preview_segment(project_id, edit_id, segment_id)` — renders one segment at 540p in ~2-3 seconds, returns a viewable frame or short clip.

---

## Architecture Summary

```
User Feedback
    │
    ▼
clipcannon_apply_feedback  ──►  Parse intent
    │                                │
    ▼                                ▼
clipcannon_modify_edit  ◄──  Structured changes
    │
    ├── Save version (edit_versions table)
    ├── Apply changes to EDL
    ├── Compute render_hint (what changed)
    ├── Reset status to draft
    │
    ▼
clipcannon_render
    │
    ├── Check segment_cache (reuse unchanged segments)
    ├── Render only invalidated segments
    ├── Concat (stream copy, fast)
    ├── Burn captions (if changed)
    ├── Mix audio (if changed)
    │
    ▼
User Reviews Output
    │
    ├── Satisfied → Done
    └── Not satisfied → Back to feedback
```

## Key Principle: The Edit is the Source of Truth

The EDL JSON is the complete, declarative specification of the video. Renders are disposable — they can always be regenerated from the EDL + source video. This means:

1. **Never fear modifying an edit** — the version history protects you
2. **Never fear re-rendering** — the segment cache makes it fast
3. **Never fear experimenting** — branches let you try alternatives without losing the original
4. **The AI's job is to refine the EDL** — not to produce perfect output on the first try

This is how professional editors work: iterate, iterate, iterate. The system should make each iteration as fast and low-risk as possible.
