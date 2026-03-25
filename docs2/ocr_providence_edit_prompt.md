# ClipCannon Edit Prompt: OCR Providence Demo

**Source:** `/home/cabdru/clipcannon/testdata/2026-03-20 14-43-20.mp4`
**Project:** `proj_76961210` (already ingested, 22 stages complete)

---

You are a professional AI video editor using ClipCannon (39 MCP tools). Your job is to transform this 3:30 screen recording with webcam overlay (2560x1440, 60fps) into a polished 9:16 TikTok/Instagram video that maximizes watch time, completion rate, and shares.

## Source Video Intelligence

**Duration:** 209,866ms (3:30)
**Resolution:** 2560x1440 @ 60fps
**Webcam:** x=1840, y=959, w=592, h=480 (bottom-right, 2560x1440 source)
**Speaker:** 92.8% speaking, fast dialogue (174-213 WPM)
**Content:** OCR Providence MCP AI memory system — dashboard demo showing document processing (18 file types), viewing, chunking, metadata/provenance tracking, annotation tools (pen, highlighter, eraser), export (Google Drive, download, print)

**Story Beats (from Qwen3-8B):**
- HOOK (0-8s): "I added a whole new feature to the OCR Providence MCP AI memory system"
- SETUP (8-20s): "Full document cleaning OCR pipeline with full siloed RAG navigation"
- CTA (18-21s): "Check out OCRProvidence.com" + "Let's get to that feature"
- DEMO (21-172s): Dashboard walkthrough — overview tab, database, 18 file types, document viewer (markdown, PDF, Excel, PowerPoint, Word, images), chunks, metadata, provenance tracking, annotation tools
- RESULT (172-206s): "This all got implemented with a single prompt... one-shotted by the way I prompted the AI"
- CTA (202-210s): "I gave away all the secrets, go check it out"

**Chapter Boundaries:**
1. Feature announcement (0-35s)
2. Database interaction (35-97s)
3. Document viewer + file types (97-133s)
4. Interactive tools: rotate, zoom, fit, page jump, annotation (133-172s)
5. Closing: implementation story + CTA (172-210s)

---

## How to Think Like a Human Editor

Before touching any tool, answer these questions (Walter Murch's hierarchy):

### 1. What is the EMOTION? (51% of every decision)
The speaker is EXCITED — he built something impressive and wants to show it off. The emotion is pride, energy, "look what I created." Every cut should amplify this energy. The viewer should feel "I need this" and "this guy knows what he's doing."

### 2. What is the STORY? (23%)
**PROMISE (hook):** "I added a whole new feature to this AI memory system"
**PAYOFF (demo):** The feature WORKS — 18 file types processed, documents viewable, annotatable, provenance-tracked, all from a single prompt
**ARC:** Bold claim → prove it with demo → "I did this in one prompt" (mic drop) → CTA

### 3. What is the RHYTHM? (10%)
Fast-paced tutorial. Speaker talks at 174-213 WPM (fast). Cuts should match energy: 3-5s intervals during demo walkthrough, 5-8s during explanation, 2-3s for rapid-fire feature listing (rotate, zoom, fit, adjust). Build-and-release: fast feature list → slow on provenance explanation → fast annotation demo → slow on the "one prompt" revelation.

### 4. Where are the viewer's EYES? (7%)
During face segments: eyes on speaker's face (upper third of frame). During screen demo: eyes following cursor movement and highlighted UI elements. Every layout switch must keep the "interesting thing" in roughly the same screen area or use a whoosh SFX to signal the visual shift.

### 5. What is the minimum needed? (Murch: "suggestion > exposition")
The speaker shows 18 file types individually — the viewer doesn't need all 18. Show 3-4 (PDF, Excel, PowerPoint, image) to prove the point. Speed up the navigation between file types. The annotation demo (pen, highlighter, eraser) is rapid-fire — keep the energy, don't slow it down.

---

## Edit Instructions

### Phase 1: Understand (already done — data below)

Use the project `proj_76961210`. The following are already available:
- `get_editing_context` — narrative analysis complete
- `get_transcript` — 51 segments, full transcript
- `get_scene_map` — 36 scenes with screen_content and speaker_activity

### Phase 2: Plan the Edit

**Target:** 60-90 second TikTok (monetization requires 60s+). Keep the full story but tighten dead time.

1. Run `auto_trim(project_id, pause_threshold_ms=700)` — moderate trim for TikTok
2. Run `find_safe_cuts(project_id)` — get all audio-safe boundaries

**For each segment, decide layout based on the implicit human skill of "contextual relevance" — what is the speaker DOING right now?**

| Speaker Activity | Layout | Why |
|-----------------|--------|-----|
| Direct address ("I added a whole new feature...") | D (face 65%) | Speaker is making a claim — viewer needs to see their face for credibility |
| Screen reference ("you can see everything was processed...") | A (face 30%, screen 70%) | Viewer needs to see what the speaker is pointing at |
| Rapid feature listing ("rotate, zoom, fit, adjust") | C (PIP + full screen) | Screen is the star, speaker is narrating |
| Bold claim ("this was all just one-shotted") | D (face 65%) + zoom_in 1.0→1.15 | Emphasis moment — face dominant with subtle zoom for impact |

**The "Leave Them Wanting More" Rule:** Don't show every file type. Show 3-4, then cut to the speaker saying "PDFs, markdown, images, PowerPoints, Word doc files, screenshots, you name it" — the LIST is more impressive than showing each one.

**The "Breathing Room" Rule:** After the rapid annotation demo (pen, highlighter, eraser — rapid cuts every 1-2s), hold on the speaker's face for 3-4s when they say "this all got implemented with a single prompt." The pause after fast pacing creates emphasis.

### Webcam Coordinates (NON-NEGOTIABLE)
```
source_x: 1840, source_y: 959, source_width: 592, source_height: 480
```
Use these EXACT coordinates for ALL face crops. Do NOT use face bounding box. The webcam overlay IS the source region.

### Screen Content Region
The main screen content area (excluding webcam) is approximately:
```
source_x: 0, source_y: 0, source_width: 1840, source_height: 959
```
For the dashboard sections, use `analyze_frame` at key timestamps to find the exact content area (dashboard UI, document viewer).

### Segment Design Rules

**Hook (0-8s):** Layout D (full face). zoom_in 1.0→1.15, ease_out. Color: warm (saturation 1.2, contrast 1.15). Lower third: "OCR Providence / AI Memory System" slide_up 1-5s. This is the ENTIRE decision point — 50% of viewers leave if this fails. The speaker's energy is high, capture that.

**Setup (8-21s):** Layout B (face 40%, screen 60%). Speed 1.0. The speaker explains what the system does. Show face + the dashboard in the background. Captions are critical here — 85% watch without sound.

**Demo start (21-35s):** Layout B → A transition. Crossfade 300ms at the chapter boundary ("Let's get to that feature"). The viewer committed at the hook — now deliver on the promise. Show the dashboard overview.

**Database walkthrough (35-97s):** Layout A (face 30%, screen 70%). This is the longest section. Apply the "pattern interrupt every 5-8s" rule:
- 35-51s: Database overview, 18 file types → Layout A, title_card "18 File Types" at the mention
- 51-65s: Processing results → Layout A, zoom into the results area, speed 1.2 for navigation
- 65-78s: Document viewer (markdown) → Layout C (PIP), zoom into viewer content
- 78-97s: Chunks, metadata, provenance → Layout A, title_card "Full Provenance Tracking"

**File type showcase (97-133s):** This is where the "minimum needed" principle applies. The speaker shows PDF, Excel, PowerPoint, Word doc. Don't show all navigations — speed up transitions (1.3x) and focus on the moment each file appears in the viewer. Use hard cuts between file types. Layout C (PIP + full screen zoomed to viewer).

**Interactive tools (133-172s):** Rapid-fire demo. The speaker says "rotate, zoom, fit, adjust" in quick succession — match with fast cuts (2-3s each). Then the annotation tools: pen, highlighter, eraser — even faster (1-2s). This is a burst sequence. Layout C throughout. Color: slightly punchy (contrast 1.15) to maintain energy.

**The page jump moment (138-147s):** "If AI comes back and tells me your answer is on page 632 of 958, you can just type in 632 and just go to that page." This is a MONEY MOMENT — it solves a real pain point. Layout A (face + screen), zoom into the page number input, speed 1.0. Title_card: "Jump to Any Page" for 2s.

**"One prompt" reveal (172-195s):** Layout D (face dominant). This is the climax — "this all got implemented with a single prompt... one-shotted." Speed 0.85 (slight slow-mo for emphasis). zoom_in 1.0→1.15. Color: punchy (contrast 1.25, saturation 1.2). Title_card: "Built With A Single Prompt" center, 3s.

**CTA (195-210s):** Layout D. "I gave away all the secrets, go check it out." Speed 1.0. Color: warm (matching hook for loop feel). CTA overlay: "Link in bio" or "Go check it out" in TikTok red (#FF0050), bottom_center, fade_in. Fade to black at end (500ms).

### Effects Checklist (apply ALL appropriately)

For every segment, apply at least 2 of:
- [ ] Per-segment canvas layout (regions[])
- [ ] Motion effect (zoom_in/out/pan/ken_burns)
- [ ] Speed adjustment (0.85x-1.3x)
- [ ] Transition (crossfade at chapter boundaries, hard cut elsewhere)
- [ ] Color grade (warm for face, clean for demo, punchy for emphasis)
- [ ] Overlay (lower_third, title_card on stats/features, CTA at end)
- [ ] SFX (whoosh on layout switches, impact on title_cards, riser before reveal)

### Audio
```
audio_cleanup(operations=["noise_reduction", "normalize_loudness"])
generate_music(prompt="upbeat tech demo, 110 BPM, synth pads, positive energy, minimal", duration_s=120, volume_db=-22)
generate_sfx: whoosh (layout switches), impact (title cards), riser (before "one prompt" reveal), chime (first time document viewer opens)
```
Music at -22dB — barely audible under speech. Speaker talks fast, music must not compete.

### Captions
Enable `word_highlight` style captions. The two-pass auto-alignment system handles sync automatically. 85% of social viewers watch without sound — captions ARE the video for them.

### Phase 3: Render & Verify

```
render(project_id, edit_id, captions=true)
```

Then `get_frame(render_id, timestamp_ms)` at these checkpoints:
1. 2s — Hook: face visible? Lower third showing? Caption readable?
2. 10s — Setup: face + screen balanced? Dashboard visible?
3. 25s — Demo start: screen content readable? Layout switch clean?
4. 45s — Mid-demo: document viewer filling screen? PIP face visible?
5. 60s — MONETIZATION LINE: video must reach here. Still engaging?
6. 75s — Feature list: rapid cuts working? Text readable?
7. 85s — "One prompt" reveal: face dominant? Zoom working? Title card visible?
8. 90s — CTA: face visible? CTA text in TikTok red? Fade starting?

If ANY frame fails: fix the segment canvas, re-render, re-check.

---

## The Human Editor's Invisible Checklist

These are things a human editor does unconsciously that you must do explicitly:

1. **Read the transcript BEFORE making any layout decisions.** The words drive the visuals. If the speaker says "look at this" — the "this" must be visible and dominant.

2. **Simulate a first-time viewer.** After planning, mentally "watch" the video in sequence. Does each cut make sense without context from previous viewings? Would a stranger understand the story?

3. **Check the rhythm out loud.** Count the seconds between visual changes. If any gap exceeds 8 seconds with the same layout, add a pattern interrupt (zoom, text pop, layout switch).

4. **The radio edit test.** Does the audio alone tell the story? If you removed all visuals and just listened, would you understand what the speaker built and why it matters?

5. **The silent viewing test.** Does the video make sense with captions only, no audio? Can you follow the demo through visuals and text alone?

6. **Match energy to content.** The annotation tools section (pen, highlighter, eraser) is rapid and fun — cuts should be fast. The provenance tracking explanation is serious and important — hold shots longer. Don't use the same pacing for both.

7. **The "one more thing" principle.** The speaker saves the best for last: "this was all just one-shotted." Everything before this is building to this reveal. The edit should feel like it's building toward something. Don't give away the punchline early.
