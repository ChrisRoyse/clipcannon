# ClipCannon Tool Consolidation Plan

> Reduce 55 tools to ~30 by merging tools that are always called together, enriching existing tools with cross-modal intelligence, and integrating Qwen3-8B validation into the editing workflow.

## Problem

The AI currently makes 8-15 tool calls to create one video edit. Many calls return partial data that the AI must manually cross-reference. This causes:
- Token waste from repeated project_id validation and DB connections
- Narrative disconnection because cross-modal insights require manual combination
- Tool selection confusion with 55 tools (models struggle past ~30 tools)

## Principle: One Intent = One Tool Call

Every tool should map to ONE editing intent, and return EVERYTHING needed to act on that intent in a single response.

---

## Phase 1: Merge Tools That Are Always Called Together

### 1.1 Merge understanding tools into `get_editing_context`

**Current**: 3 separate calls to understand a video
```
get_editing_context  → data manifest (counts, tool references)
get_vud_summary      → speakers, topics, highlights, beats, safety
get_transcript       → paginated transcript text
```

**Proposed**: `get_editing_context` returns ALL of this in one call:
```json
{
  "video": { "duration_ms", "resolution", "fps", "status" },
  "data_manifest": { ... counts and availability ... },
  "speakers": [ ... ],
  "topics": [ ... ],
  "content_rating": "clean",
  "beats": { "bpm": 139, "detected": true },
  "narrative": {
    "story_beats": [ ... from Qwen3-8B ... ],
    "open_loops": [ ... ],
    "chapter_boundaries": [ ... ],
    "summary": "..."
  },
  "transcript_preview": "first 500 words of transcript...",
  "query_tools": { ... how to dig deeper ... }
}
```

**Eliminates**: `get_vud_summary` becomes redundant (its data is IN get_editing_context). `get_transcript` stays for full paginated access but the preview covers most editing needs.

**Saves**: 2 tool calls per editing session.

### 1.2 Merge `get_scene_at` into `get_segment_detail`

**Current**: 2 separate calls to understand a timestamp
```
get_scene_at(timestamp)     → canvas regions, face, webcam, content
get_segment_detail(start, end) → 17 data streams for time range
```

**Proposed**: `get_segment_detail` already returns scene_map data. Add the `get_scene_at` convenience (single-timestamp with layout filter) as a parameter:
```
get_segment_detail(project_id, start_ms, end_ms)  — range query (existing)
get_segment_detail(project_id, timestamp_ms=X, layout="D")  — point query (new)
```

When `timestamp_ms` is provided instead of start/end, return the single scene with canvas regions for the requested layout, plus the 5s window of surrounding data (transcript, emotion, etc.).

**Eliminates**: `get_scene_at` as a separate tool.

### 1.3 Merge `find_cut_points` into `find_best_moments`

**Current**: 2 separate calls for segment planning
```
find_best_moments(purpose) → scored clip candidates with canvas regions
find_cut_points(around_ms) → convergence-scored edit boundaries
```

**Proposed**: `find_best_moments` already returns `cut_points.clean_start_ms` and `clean_end_ms`. Enrich these cut points with the convergence scoring:
```json
{
  "cut_points": {
    "clean_start_ms": 449700,
    "clean_end_ms": 482917,
    "start_quality": "excellent",
    "start_signals": ["beat_hit", "silence_gap"],
    "end_quality": "perfect",
    "end_signals": ["beat_hit", "scene_boundary", "sentence_end"]
  }
}
```

`find_cut_points` stays as a standalone tool for manual boundary exploration, but the AI no longer needs to call it separately after `find_best_moments` — the convergence data is already there.

**Saves**: 1-3 tool calls per editing session (one per segment boundary).

### 1.4 Integrate `get_narrative_flow` into `create_edit`

**Current**: AI must remember to call `get_narrative_flow` before `create_edit`
```
get_narrative_flow(segments)  → warnings about gaps and broken promises
create_edit(segments)         → builds the edit
```

**Proposed**: `create_edit` automatically runs narrative validation and includes warnings in its response:
```json
{
  "edit_id": "edit_abc123",
  "status": "draft",
  "segment_count": 8,
  "narrative_warnings": [
    "Gap 2: 65s skipped between segments 2-3 (189 words). Contains the 12-embedder explanation.",
    "Segment 5: thought_complete=false, last sentence ends mid-thought."
  ],
  "narrative_coherence": "low"  // from Qwen3-8B if available
}
```

The AI sees the warnings immediately and can call `modify_edit` to fix them. No separate validation step needed.

**Eliminates**: The need to remember to call `get_narrative_flow` (it's automatic).

---

## Phase 2: Enrich Existing Tools with Cross-Modal Intelligence

### 2.1 Enrich `get_segment_detail` with moment characterization

**Current**: Returns 17 raw data streams. AI must manually interpret "energy=0.36 + wpm=175 + sentiment=POSITIVE" as "passionate moment."

**Proposed**: Add a `moment_character` field that pre-computes the cross-modal label:
```json
{
  "moment_character": {
    "mood": "passionate",
    "intensity": "high",
    "speaker_intent": "direct_address",  // from face_size + transcript keywords
    "screen_relevance": "speaker_references_screen",  // from OCR + transcript match
    "recommended_layout": "D",  // derived from mood + intent + screen_relevance
    "editing_notes": "High energy bold claim. Use as hook or CTA. Layout D with zoom_in effect."
  }
}
```

These labels are computed from the existing cross-modal rules:
- `mood`: energy + pacing + sentiment → passionate/calm/dramatic/excited
- `speaker_intent`: face_size + transcript keywords → direct_address/narrating/demonstrating
- `screen_relevance`: OCR visible + transcript "show"/"see"/"look" → screen dominant or not
- `recommended_layout`: derived from the above

### 2.2 Enrich `find_best_moments` with narrative context

**Current**: Returns moments with score + transcript + canvas but no narrative context.

**Proposed**: Include the Qwen3-8B story beat that covers this moment:
```json
{
  "rank": 1,
  "start_ms": 450000,
  "score": 3.42,
  "story_beat": {
    "type": "result",
    "summary": "Announces the successful completion of the project"
  },
  "moment_character": "passionate_claim",
  "open_loop_status": "closing"  // this moment CLOSES the main loop
}
```

Now the AI knows this moment is the RESULT beat that CLOSES the open loop. It would never put this at the beginning of a video.

### 2.3 Enrich `get_editing_context` manifest with Qwen3-8B narrative

**Current**: Manifest shows data counts. AI must call separate tools to understand the story.

**Proposed**: The manifest includes the narrative summary and chapter structure:
```json
{
  "narrative": {
    "summary": "Creator unveils AI video editor, explains embedder-based approach, demonstrates 16:9→9:16 conversion, shows rendered output, claims world's first.",
    "chapters": [
      {"label": "Hook", "start_ms": 0, "end_ms": 13410},
      {"label": "Setup - Platform support", "start_ms": 14270, "end_ms": 28618},
      {"label": "Philosophy - AI scaling", "start_ms": 87550, "end_ms": 120000},
      {"label": "Demo - Original video", "start_ms": 153600, "end_ms": 186730},
      {"label": "Demo - AI editing process", "start_ms": 209810, "end_ms": 340000},
      {"label": "Demo - Rendered output", "start_ms": 340750, "end_ms": 414530},
      {"label": "Closing - World's first", "start_ms": 449700, "end_ms": 467650}
    ],
    "open_loop": "World's first AI video editor → opened at 0:00, closed at 7:30"
  }
}
```

The AI reads this ONE response and immediately knows the entire video structure, where to find each type of content, and how the story flows. No additional discovery calls needed for simple edits.

---

## Phase 3: Integrate Qwen3-8B Validation into Edit Workflow

### 3.1 Auto-validate in `create_edit`

When `create_edit` is called with non-contiguous segments:
1. Extract transcript for each segment
2. Run Qwen3-8B: "Does this edit tell a coherent story? Rate 1-10."
3. Include the rating and issues in the response
4. If coherence < 5, include specific suggestions

This costs ~10s (one Qwen3-8B call) but prevents bad renders that take 2-4 minutes.

### 3.2 Auto-suggest in `find_best_moments`

When returning moments, also return a "suggested_edit_order" that respects the narrative arc:
```json
{
  "suggested_edit_order": [1, 3, 5, 2, 4],  // reordered for story flow
  "suggested_segments": [
    {"start_ms": 370, "end_ms": 28618, "beat": "hook+setup"},
    {"start_ms": 153600, "end_ms": 186730, "beat": "demo_intro"},
    {"start_ms": 340750, "end_ms": 414530, "beat": "demo_result"},
    {"start_ms": 449700, "end_ms": 467650, "beat": "cta"}
  ]
}
```

The AI can use this directly in `create_edit` — the segments are pre-ordered for narrative coherence.

---

## Proposed Tool Map (55 → ~30)

### Core Tools (keep, enrich)
| Tool | Enhancement |
|---|---|
| `get_editing_context` | Absorbs vud_summary + narrative + chapters |
| `get_segment_detail` | Absorbs get_scene_at + adds moment_character |
| `get_scene_map` | Keep as-is (paginated browsing) |
| `get_transcript` | Keep as-is (full paginated access) |
| `find_best_moments` | Absorbs cut point convergence + narrative context |
| `find_cut_points` | Keep for manual exploration |
| `get_narrative_flow` | Keep but auto-called by create_edit |
| `search_content` | Keep as-is |
| `analyze_frame` | Keep as-is |
| `get_frame` | Keep as-is |
| `preview_layout` | Keep as-is |
| `preview_clip` | Keep as-is |

### Editing Tools (keep, consolidate)
| Tool | Enhancement |
|---|---|
| `create_edit` | Auto-validates narrative, includes warnings |
| `modify_edit` | Keep as-is |
| `color_adjust` | Keep as-is |
| `add_motion` | Keep as-is |
| `add_overlay` | Keep as-is |
| `auto_trim` | Keep as-is |
| `render` | Keep as-is |
| `inspect_render` | Keep as-is |

### Project/System Tools (keep as-is)
| Tool | Notes |
|---|---|
| `project_create/open/list/status/delete` | 5 tools, keep |
| `ingest` | Keep |
| `credits_balance/history/estimate/spending_limit` | 4 tools, keep |
| `config_get/set/list` | 3 tools, keep |
| `disk_status/cleanup` | 2 tools, keep |

### Audio Tools (keep, rarely used)
| Tool | Notes |
|---|---|
| `audio_cleanup` | Keep |
| `generate_music/compose_midi/generate_sfx` | Keep (Phase 2 features) |

### Tools to Deprecate
| Tool | Reason | Data Available Via |
|---|---|---|
| `get_vud_summary` | Absorbed into `get_editing_context` | get_editing_context |
| `get_scene_at` | Absorbed into `get_segment_detail` | get_segment_detail(timestamp_ms=X) |
| `get_analytics` | Overlaps with get_editing_context + get_segment_detail | Both |
| `get_storyboard` | Rarely used, high token cost | get_frame for specific frames |
| `render_batch` | Never used in practice | render × N |
| `render_status` | Renders complete synchronously | inspect_render |
| `list_edits` | Rarely needed | project_status |
| `generate_metadata` | Could be auto-generated in create_edit | create_edit |
| `measure_layout` | Overlaps with get_scene_at/preview_layout | get_segment_detail |
| `extract_subject` | Never used | — |
| `replace_background` | Never used | — |
| `remove_region` | Never used | — |
| `provenance_verify/query/chain/timeline` | 4 tools, system-internal only | — |

### Final Count: ~30 tools (down from 55)

---

## Implementation Priority

| Phase | Change | Effort | Impact |
|---|---|---|---|
| **1a** | Merge vud_summary + narrative into get_editing_context | Small | Eliminates 2 tool calls per session |
| **1b** | Add convergence scoring to find_best_moments cut_points | Small | Eliminates 1-3 tool calls per session |
| **1c** | Auto-validate narrative in create_edit | Medium | Prevents ALL narrative issues |
| **2a** | Add moment_character to get_segment_detail | Medium | AI understands mood/intent without manual interpretation |
| **2b** | Add story_beat context to find_best_moments | Small | AI knows where each moment fits in the narrative |
| **2c** | Add timestamp_ms mode to get_segment_detail | Small | Eliminates get_scene_at |
| **3** | Deprecate redundant tools | Small | Reduces tool confusion |

---

## Example: Editing Session Before vs After

### Before (current: 12+ tool calls)
```
1. get_editing_context          → data manifest
2. get_vud_summary              → speakers, topics
3. get_transcript               → read the story
4. find_best_moments(hook)      → hook candidates
5. find_best_moments(highlight) → body candidates
6. find_best_moments(cta)       → closing candidates
7. find_cut_points(boundary1)   → clean cuts
8. find_cut_points(boundary2)   → clean cuts
9. get_scene_at(timestamp1)     → layout data
10. preview_layout(timestamp1)  → verify visually
11. get_narrative_flow(segments) → check coherence
12. create_edit(segments)        → build
13. color_adjust + overlays      → polish
14. render                       → output
```

### After (consolidated: 6-8 tool calls)
```
1. get_editing_context           → EVERYTHING: manifest + narrative + chapters + speakers + transcript preview
2. find_best_moments(hook)       → candidates WITH convergence cuts + story beat context + moment character
3. find_best_moments(highlight)  → same enriched format
4. get_segment_detail(ts=X)      → scene data + moment character + layout recommendation (replaces get_scene_at)
5. preview_layout(timestamp)     → verify visually (still needed)
6. create_edit(segments)         → builds edit + AUTO-VALIDATES narrative + returns warnings
7. color_adjust + overlays       → polish
8. render                        → output
```

**6 fewer tool calls, zero narrative issues, richer data per call.**
