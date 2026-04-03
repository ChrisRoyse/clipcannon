# ClipCannon: Optimal AI Editing Workflow

How an AI editor should use ClipCannon's iterative system to produce professional-quality video. This guide assumes the AI has access to all 40+ MCP tools and operates through the edit-review-fix cycle.

---

## Core Mindset

**You will not one-shot a perfect video.** No human editor does either. The system is designed for iteration. Your first edit is a rough cut. User feedback refines it. Each render is cheaper than the last because the segment cache reuses unchanged work. Embrace the cycle:

```
Understand --> Plan --> Rough Cut --> Render --> Review --> Refine --> Re-Render --> Ship
                                       ^                    |
                                       |____________________| (repeat 2-5 times)
```

A human editor spends 30-40% of their time in the rough cut, then 15-20% fine-tuning. Your time should follow the same ratio: invest heavily in understanding the source, produce a solid first draft, then use targeted modifications to polish.

---

## Phase 1: Understand the Source (Do Not Skip)

**Time investment: First. Before any editing decisions.**

### Step 1: Get the full context

```
get_editing_context(project_id)
```

This single call returns: duration, resolution, fps, speaker breakdown, narrative analysis (story beats, open loops, chapter boundaries), transcript preview, pacing data, webcam detection, content rating. Read ALL of it.

### Step 2: Read the transcript

```
get_transcript(project_id, detail="text")
```

**The words drive every visual decision.** Before choosing a single layout, know what the speaker says and when. Mark mentally:
- Where they make claims (face dominant)
- Where they reference the screen (screen dominant)
- Where they list things quickly (fast cuts)
- Where they pause for emphasis (hold the shot)
- Where they make promises ("I'll show you X" -- X MUST appear later)

### Step 3: Get the scene map

```
get_scene_map(project_id, detail="full")
```

This gives you pre-computed canvas regions for every scene in all 4 layouts (A/B/C/D). You do NOT need to manually calculate coordinates. The scene map tells you:
- Where the face is in each scene
- Where the webcam overlay is (stable detection across scenes)
- Where the content area is
- What layout is recommended
- What the speaker says during each scene

### Step 4: Find the story structure

```
get_narrative_flow(project_id, segments=[...proposed cuts...])
```

**ALWAYS call this before create_edit with non-contiguous segments.** It tells you:
- What words are at each cut boundary
- What content is being skipped in gaps
- Whether you're breaking any promise-payoff patterns
- Whether thoughts are complete at cut points

### Step 5: Find safe cut points

```
find_safe_cuts(project_id, min_silence_ms=400)
```

This cross-references silence gaps + sentence endings + beat positions + scene boundaries + text change events. Each cut point includes:
- Safety score (85 = excellent, 55 = acceptable)
- What words come before and after the gap
- Whether the thought is complete
- Which signals converge at that point

**Use these timestamps as your segment boundaries.** Never pick arbitrary timestamps. Every segment start and end should align with a safe cut or a word-level endpoint plus 50ms padding.

---

## Phase 2: Plan the Edit (Think Before Cutting)

### Apply Walter Murch's hierarchy to every decision

| Priority | Question | Weight |
|----------|----------|--------|
| 1 | Does this serve the EMOTION? | 51% |
| 2 | Does this advance the STORY? | 23% |
| 3 | Does it fit the RHYTHM? | 10% |
| 4 | Does it guide the viewer's EYES? | 7% |
| 5 | Does it maintain visual grammar? | 5% |
| 6 | Does it maintain spatial continuity? | 4% |

### Decide segment boundaries using audio intelligence

For each proposed segment boundary:
1. Check `find_safe_cuts` -- is there a safe cut within 2 seconds?
2. Check `find_cut_points(around_ms=target)` -- what's the nearest convergence point?
3. Check `get_transcript(detail="words")` -- does the last word end cleanly? Add 50ms padding after the word's `end_ms`.
4. **Never cut mid-word.** If the nearest safe cut is 500ms away, use it instead of the raw timestamp.

### Choose layouts based on what the speaker is doing NOW

| Speaker Activity | Layout | Why |
|-----------------|--------|-----|
| Direct address ("I built this...") | D (face dominant) | Credibility requires eye contact |
| Screen reference ("look at this dashboard") | A or C (screen dominant) | Viewer needs to see what speaker points at |
| Quick listing ("rotate, zoom, fit, adjust") | C (PIP + full screen) | Screen is the star, speaker narrates |
| Bold claim / reveal ("this was one-shotted") | D + zoom_in | Emphasis moment, face sells conviction |
| Technical explanation (no screen ref) | B (40/60 balanced) | Balance between face and context |
| CTA ("go check it out") | D | Connection, trust, call to action |

### Design the pacing curve

```
Hook (0-3s):     HIGH energy -- face close-up, bold text, zoom
Setup (3-15s):   MEDIUM energy -- balanced layout, context
Body (15-60s+):  VARIABLE -- alternate fast cuts (2-4s) with held moments (6-8s)
Climax (70-80%): PEAK energy -- face dominant, slow-mo, punchy color
CTA (last 5s):   WARM -- face, matching the hook for loop potential
```

Every 5-8 seconds in the body, create a pattern interrupt: layout switch, zoom, text overlay, color shift, or speed change. Monotonous pacing kills retention.

---

## Phase 3: Build the Rough Cut

### Create the edit with all decisions in one call

```
create_edit(
    project_id, name, target_platform,
    segments=[...],  // all segments with per-segment canvas
    captions={enabled: true, style: "word_highlight"},
)
```

Then apply effects in parallel:
```
// All in one message:
add_motion(segment_id=1, effect="zoom_in", ...)    // hook zoom
color_adjust(segment_id=1, saturation=1.2, ...)     // warm hook
add_overlay(type="lower_third", ...)                 // speaker name
add_overlay(type="title_card", ...)                  // key stats
audio_cleanup(operations=["noise_reduction", "normalize_loudness"])
generate_music(prompt="...", duration_s=90, volume_db=-22)
```

### Preview before rendering

```
preview_layout(project_id, timestamp_ms, regions=[...])  // ~300ms per frame
preview_segment(project_id, edit_id, segment_index=1)     // ~2-3s per segment
```

Check the hook frame, a mid-point frame, and the CTA frame. If any layout looks wrong, modify BEFORE spending a render credit.

---

## Phase 4: Render and Review

```
render(project_id, edit_id, captions=true)
```

Then verify at critical timestamps:
```
get_frame(render_id=X, timestamp_ms=2000)   // Hook: face visible? Text readable?
get_frame(render_id=X, timestamp_ms=30000)  // Mid: engaging? Layout switching?
get_frame(render_id=X, timestamp_ms=60000)  // Monetization line (TikTok 60s)
get_frame(render_id=X, timestamp_ms=T-3000) // CTA: face visible? CTA overlay?
```

Also run `inspect_render` for automated quality checks at 5 key frames.

---

## Phase 5: Iterate (The Power Move)

This is where ClipCannon's iterative system shines. You have multiple tools for refinement:

### Option A: `modify_edit` -- Surgical precision

When you know exactly what to change:

```
modify_edit(project_id, edit_id, changes={
    "segments": [...updated segment list...],
})
```

The system:
1. **Saves the current state** as a version (auto, you can always revert)
2. **Applies your changes**
3. **Returns a render_hint** telling you exactly what needs re-rendering
4. **Resets status to draft** for re-rendering

The render_hint tells the renderer which segments to re-render vs reuse from cache. If you only changed one segment's color, only that segment re-renders. The other 11 are cached.

### Option B: `apply_feedback` -- Natural language

When the user gives verbal feedback:

```
apply_feedback(project_id, edit_id, feedback="the cut at 0:15 is too abrupt")
```

The system parses the intent and applies the right EDL change:
- "too abrupt" -> adds crossfade transition
- "too fast" -> reduces speed
- "music too loud" -> lowers volume
- "text bigger" -> increases caption font size
- "zoom in on the dashboard" -> adds zoom_in motion

This is for quick adjustments. For complex changes, use `modify_edit` directly.

### Option C: `revert_edit` -- Undo mistakes

If a change made things worse:

```
edit_history(project_id, edit_id)  // see all versions
revert_edit(project_id, edit_id, version_number=3)  // go back
```

Every modification is auto-versioned. The revert itself creates a new version, so you can even undo the undo.

### Option D: `branch_edit` -- Platform variants

Once the TikTok version is good, create variants:

```
branch_edit(project_id, edit_id, "instagram", "instagram_reels")
branch_edit(project_id, edit_id, "youtube", "youtube_shorts")
```

Each branch is independent. Modify the Instagram version's pacing without touching TikTok. The segment cache is shared -- segments that are identical across branches don't re-render.

### Re-render with cache benefits

```
render(project_id, edit_id, captions=true)
```

The second render is faster because:
- Unchanged segments are served from the segment cache (content-hash matched)
- Only modified segments actually render through FFmpeg
- Concat is always fast (stream copy)
- Caption burn-in and audio mixing always run (they're cheap)

---

## The Complete Decision Tree

```
User says: "Edit this video for TikTok"
  |
  v
UNDERSTAND (5 tools, ~10s)
  get_editing_context -> narrative, speakers, pacing
  get_transcript -> word-level content
  get_scene_map -> visual intelligence per scene
  find_safe_cuts -> audio-safe boundaries
  auto_trim -> filler/pause removal
  |
  v
PLAN (mental, 0 tools)
  Map story arc: hook -> setup -> demo -> reveal -> CTA
  Choose segment boundaries from safe cuts
  Assign layout per segment based on transcript
  Plan effects: zoom on hook, title_cards on stats, warm/cool color shifts
  |
  v
BUILD (2-8 tools, one message)
  create_edit (all segments + canvas)
  add_motion, color_adjust, add_overlay (in parallel)
  audio_cleanup + generate_music (in parallel)
  |
  v
PREVIEW (1-3 tools, ~1s each)
  preview_segment at hook, mid, end
  preview_layout at critical frames
  Fix any issues via modify_edit BEFORE rendering
  |
  v
RENDER (1 tool, ~90s)
  render with captions
  get_frame at checkpoints
  inspect_render for quality
  |
  v
User reviews...
  |
  +-- "Looks great!" -> Done. Branch for other platforms if needed.
  |
  +-- "The cut at 0:15 is jarring" -> apply_feedback("cut at 0:15 too abrupt")
  |                                    -> re-render (only affected segment re-renders)
  |
  +-- "Music is too loud" -> apply_feedback("music too loud")
  |                          -> re-render (only audio re-mixes, no segment re-render)
  |
  +-- "The intro is too slow" -> modify_edit(changes={segments: [...]})
  |                               -> re-render
  |
  +-- "Actually go back to how it was before" -> revert_edit(version_number=1)
  |                                              -> re-render
  |
  +-- "Now make an Instagram version" -> branch_edit("instagram", "instagram_reels")
                                         -> modify branch for platform
                                         -> render branch
```

---

## What Makes a Great AI Edit (The Checklist)

Before presenting any render to the user, verify:

### The Silent Test
Watch (look at frames) without considering audio. Can you follow the story from visuals + captions alone? If not, captions or layouts need work.

### The Radio Test
Read the transcript for the edit's segments. Does the audio alone tell a coherent story? If not, you've broken the narrative.

### The 3-Second Test
Look at the frame at 2s. Would you keep watching? If the hook doesn't grab in 3 seconds, 50% of viewers leave.

### The Rhythm Test
Count the seconds between visual changes (layout switches, zooms, overlays). If any gap exceeds 8 seconds with the same layout, add a pattern interrupt.

### The Promise Test
Did the speaker promise to show something? Is it visible in the edit? `get_narrative_flow` checks this automatically. Never break a promise.

### The Monetization Test (TikTok)
Is the video 60+ seconds? If not, it earns zero platform revenue regardless of views.

### The Word Boundary Test
At every segment boundary, is the last word fully spoken? Check with `get_transcript(detail="words")`. The word's `end_ms` plus 50ms should be before the segment's `source_end_ms`.

---

## Common Mistakes and How the System Prevents Them

| Mistake | How ClipCannon Prevents It |
|---------|---------------------------|
| Cutting mid-word | `find_safe_cuts` provides audio-safe boundaries; caption clamping drops partial words |
| Stale captions after a cut | Caption boundary clamping drops words that spill past segment ends |
| No background music in output | `_prepare_mixed_audio` auto-mixes music assets during render |
| Scene boundaries mid-speech | `_snap_boundary_to_audio` snaps visual scenes to silence gaps |
| Losing a good edit after a bad change | Auto-versioning saves every state; `revert_edit` restores any version |
| Full re-render for a tiny change | Segment cache skips unchanged segments; `render_hint` classifies impact |
| Static layout for the entire video | Per-segment canvas requires a layout decision for each segment |
| Breaking the narrative | `get_narrative_flow` warns about broken promises and skipped context |

---

## Tool Quick Reference (Workflow Order)

### Understand
| Tool | Purpose | When |
|------|---------|------|
| `get_editing_context` | Full project intelligence | First call, always |
| `get_transcript` | Word-level speech data | Before any cuts |
| `get_scene_map` | Visual layout intelligence | Before choosing layouts |
| `find_safe_cuts` | Audio-safe boundaries | Before choosing segment boundaries |
| `find_cut_points` | Convergence near a timestamp | When fine-tuning a specific cut |
| `find_best_moments` | Scored highlights for hook/CTA | When selecting key moments |
| `search_content` | Semantic search in transcript | When looking for specific content |
| `get_narrative_flow` | Validate segment coherence | Before create_edit with gaps |

### Build
| Tool | Purpose | When |
|------|---------|------|
| `create_edit` | Build the EDL | Once per edit |
| `auto_trim` | Generate filler-free segments | As a starting point |
| `add_motion` | Zoom/pan effects | After create_edit |
| `color_adjust` | Color grading | After create_edit |
| `add_overlay` | Text, titles, CTA | After create_edit |
| `audio_cleanup` | Noise reduction, normalization | After create_edit |
| `generate_music` | AI background music | After create_edit |
| `generate_sfx` | Sound effects | After create_edit |

### Verify
| Tool | Purpose | When |
|------|---------|------|
| `preview_layout` | Check canvas composition | Before render |
| `preview_segment` | Render 1 segment at 540p | Before full render |
| `get_frame` | Extract any frame (source or render) | After render |
| `analyze_frame` | Detect content regions | Before or after render |
| `inspect_render` | 5-point quality check | After render |

### Iterate
| Tool | Purpose | When |
|------|---------|------|
| `modify_edit` | Surgical EDL changes | When you know what to change |
| `apply_feedback` | Natural language adjustments | When user gives verbal feedback |
| `edit_history` | List all versions | Before reverting |
| `revert_edit` | Restore a previous version | When a change made things worse |
| `branch_edit` | Fork for another platform | After main edit is solid |
| `list_branches` | See all platform variants | When managing branches |

### Render
| Tool | Purpose | When |
|------|---------|------|
| `render` | Full render with captions + music | When edit is ready |

---

## The Human Editor's Invisible Skills (Made Explicit)

These are things human editors do unconsciously that you must do deliberately:

1. **Read the transcript BEFORE making layout decisions.** The words drive the visuals. "Look at this" = screen dominant. "I built this" = face dominant.

2. **Simulate a first-time viewer.** After planning, mentally "watch" the sequence. Does each cut make sense without having seen the full source?

3. **Check rhythm.** Count seconds between visual changes. Vary the rhythm: fast-fast-slow-fast creates energy. Same-same-same creates boredom.

4. **Match energy to content.** Rapid annotation demo = fast cuts. Provenance explanation = held shots. Don't use the same pacing for both.

5. **Save the best for last.** If the speaker has a "mic drop" moment, everything before it should build toward that reveal. The edit should feel like it's going somewhere.

6. **Less is more.** If the speaker shows 18 file types, showing 3-4 proves the point. The verbal LIST is more impressive than showing each one. Suggest > expose.

7. **The "Leave Them Wanting More" principle.** Cut away 1 second before you think you should. A viewer reaching for more is a viewer who stays.

8. **Emotion > Information.** A technically complete edit that feels boring is worse than a slightly incomplete edit that feels exciting. When in doubt, sacrifice completeness for energy.
