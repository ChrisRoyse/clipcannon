# ClipCannon AI Video Editing Guide

Supported canvases: **1080x1920** (9:16), **1920x1080** (16:9), **3840x2160** (4K 16:9), **1080x1080** (1:1). All values in pixels. Platforms: TikTok, Instagram Reels, YouTube Shorts, Facebook Reels, LinkedIn.

## Core Directive

**Think like a director. Use every tool. Iterate on previews. Match visuals to what the speaker is saying.**

1. Every cut/layout/zoom is a storytelling decision -- ask "what must the viewer see NOW?"
2. Combine auto-trim, color, motion, overlays, audio cleanup, and layouts -- not just cuts
3. Always preview before rendering: `preview_layout` (~300ms), `preview_clip` (~1s), `inspect_render` after
4. Read the transcript -- the words drive the visuals. "Look at this dashboard" = dashboard dominant. "I built this" = face dominant.
5. **Design for silent viewing first** -- 85% of users watch without sound. Bold captions and visual storytelling must carry the message alone.
6. **Engineer the first 3 seconds obsessively** -- 50% of viewers decide to stay or leave in this window. This is the single highest-leverage edit.

---

## 1. Viral Video Science

### The Retention Curve

Every video follows the same drop-off pattern. Your editing decisions fight this curve:

```
100% |X
     | X
 70% |  X.............. <- 3-second gate (50% leave if hook fails)
     |   \
 50% |    \............ <- 8-second commitment point
     |     \
 30% |      \.......... <- Mid-video plateau (keep flat with pattern interrupts)
     |       \
 10% |        \________ <- End drop (satisfied viewers leave early)
  0% +--+--+--+--+--+--
     0s  3s  8s  30s 60s end
```

**Benchmarks:**
- 70%+ completion rate at 3s = 3x more algorithmic reach (TikTok)
- 85%+ at 3s = viral potential
- Below 60% at 3s = minimal promotion
- Average YouTube video retains only 23.7% of viewers overall
- Short-form (15-30s) can achieve 80%+ retention with proper editing

### Algorithm Signal Priority (All Platforms)

| Rank | Signal | Why It Matters |
|---|---|---|
| 1 | **Watch time / completion %** | 40-50% of algorithm weight on TikTok. THE metric. |
| 2 | **Shares / DM sends** | Instagram: DM shares are THE strongest signal for new audience reach |
| 3 | **Saves** | High-intent signal: viewer plans to return |
| 4 | **Comments** | Active engagement, drives discussion |
| 5 | **Replays / loops** | YouTube Shorts counts each loop as a new view |
| 6 | **Likes** | Weakest signal -- passive, low effort |

**Key insight: Every editing decision should maximize watch time.** Cuts, zooms, text overlays, and layout switches exist to prevent the viewer from swiping away.

### Storytelling: Open the Loop, Close the Loop

**Every video is a story. Every story has a promise and a payoff. NEVER break the promise.**

The viewer stays because they're waiting for something. The hook OPENS a loop (creates a question, makes a promise, starts a journey). The ending CLOSES that loop (answers the question, delivers the promise, completes the journey). If you skip the middle or cut before the payoff, the story is broken and the viewer feels cheated.

```
OPEN LOOP (0-3s)     Create a PROMISE the viewer needs to see fulfilled.
                     "I built the world's first AI video editor" = promise to SHOW it
                     "Watch what happens when..." = promise of a RESULT
                     Bold claim = promise of PROOF

SETUP (3-15s)        Establish WHY the promise matters. Build tension.
                     Show the problem. Show what makes this hard.
                     The viewer should think "okay, prove it"

DELIVER (15s-end-15s) FULFILL THE PROMISE. This is the entire reason the viewer stayed.
                      If you promised to show the AI editing → SHOW THE AI EDITING
                      If you promised a result → SHOW THE RESULT
                      Every scene must advance toward the payoff. No detours.
                      Pattern interrupts every 5-8s to maintain engagement.

CLOSE LOOP (last 10-15s) Complete the story. Answer the question from the hook.
                          "This is ClipCannon. World's first. No human in the loop."
                          = the proof that validates the opening promise
                          CTA: "Follow for more" / "Send this to someone who..."
```

### Story Continuity Rules (CRITICAL)

**Rule 1: Never break a promise.** If the speaker says "let me show you X" — the video MUST show X. If you cut before X is shown, the story is broken.

**Rule 2: Never skip the middle of a story.** If the speaker goes from A → B → C → D, you cannot show A then skip to D. The viewer needs B and C to understand why D matters. If you must shorten, cut entire stories — don't gut the middle out of one story.

**Rule 3: Every cut must advance the narrative.** Ask: "Does this cut move the story forward?" If it moves sideways or backward, it's wrong. Each segment should be closer to the payoff than the previous one.

**Rule 4: Non-contiguous segments MUST be narratively coherent.** When you skip source content between segments, read what's in the gap. If the gap contains setup, explanation, or context that the next segment depends on, you CANNOT skip it. Use `get_narrative_flow` to verify before creating the edit.

**Rule 5: Thought boundaries > sentence boundaries.** A sentence ending is not always a thought ending. "Let me show you the video." is a sentence, but the THOUGHT is "let me show you the video [shows video]." Both parts are needed. Never cut between a setup and its payoff.

### Viewer Dropout Triggers (What Makes People Leave)

| Trigger | What Happens | How to Prevent |
|---|---|---|
| Hook fails | 50% leave in first 3s | Bold statement + face close-up, not logos |
| Broken promise | Viewer feels cheated, leaves angry | Always deliver what you promised |
| No forward momentum | Scene doesn't advance story | Every scene moves toward payoff |
| Monotonous pacing | All cuts same length, viewer zones out | Mix rapid cuts with held moments |
| Mid-thought cut | Jarring audio jump, confusion | Cut at thought boundaries, verify with transcript |
| Skipped context | "Wait, what?" → viewer lost | Never skip setup that explains the next scene |

### Looping Structure (Advanced)

Design the ending to lead back into the first frame. Looping videos push past 100% retention. The last word/image should create curiosity that the first frame satisfies.

### What Makes Content Go Viral

| Theme | Why It Works | ClipCannon Approach |
|---|---|---|
| Educational/How-to | Drives shares ("send to someone who needs this") | Screen-dominant layouts (A/C), zoom to readable text, clear captions |
| Before/After | Visual payoff drives completion | Split layout progression, color grade shift between before/after |
| Bold contrarian take | Creates curiosity gap + comment debate | Face-dominant hook (D), data overlays, strong caption emphasis |
| Step-by-step demo | High save rate, high completion | Dynamic switching (E), number overlays, scene-per-step |
| Storytelling/narrative | Tension holds viewers through mid-section | Face hook, progressive reveals, music builds |

---

## 2. Platform Safe Zones

| Platform | Safe Zone (x1,y1)→(x2,y2) | Right Danger | Bottom Danger | Top Danger |
|---|---|---|---|---|
| TikTok | (60,108)→(960,1600) | x>960 (120px) | y>1600 (320px) | y<108 |
| Instagram | (60,108)→(940,1560) | x>940 (140px) | y>1560 (360px) | y<108 |
| YouTube | (60,108)→(940,1580) | x>940 (140px) | y>1580 (340px) | y<108 |
| Facebook | (60,100)→(960,1600) | x>960 (120px) | y>1600 (320px) | y<100 |
| LinkedIn | (48,96)→(984,1620) | x>984 (96px) | y>1620 (300px) | y<96 |

**Universal safe zone (cross-platform): (60,108)→(940,1560) = 880x1452**

---

## 3. Layouts

### A: 30/70 Split (tutorials)
Face: (0,0,1080,576). Screen: (0,576,1080,1344). Eye line y=192.

### B: 40/60 Split (balanced)
Face: (0,0,1080,768). Screen: (0,768,1080,1152). Eye line y=256.

### C: PIP
Screen: full canvas. PIP circle: (24,140,240,240) r=120. PIP rect: (24,140,280,350) r=24. Border: 3px white. Must stay above y=1440, left of x=900.

### D: Full-Screen Face (hook/CTA)
Face: (0,0,1080,1920). Eye line y=640. Hook: face 70-80% width. CTA: slightly wider.

### E: Dynamic Switching

| Content | Layout |
|---|---|
| Speaker only (no screen) | D |
| Speaker + screen | A or B |
| Screen walkthrough, narrating | C (PIP) |
| Zoom into UI element | Screen zoom, no face |
| Hook (first 3s) | D |
| CTA (last 3-5s) | D |

Transitions: hard cuts only. Min layout: 3s. Max before change: 8s.

### CRITICAL: Layouts Are NOT Static

**Every segment gets its OWN canvas layout.** A video with 20 segments should have 20 individually configured canvas specs, each matching what the speaker is showing/saying at THAT moment.

**NEVER apply one layout to the entire video.** This is the #1 editing failure. A 60-second segment with static Layout A means the viewer stares at the same composition for a full minute — guaranteed retention drop.

**The rule: break the video into 5-10 second segments, each with its own canvas.** Use `auto_trim` to get the natural segments (filler/pause removal gives you the right granularity), then assign each one a per-segment canvas based on the transcript at that timestamp.

```
Segment 1 (0-5s):    Layout D — "I built the world's first..." (direct address)
Segment 2 (5-12s):   Layout B — "...for AI agents..." (face + code visible)
Segment 3 (12-20s):  Layout A — "it uses 12 embedders..." (screen dominant)
Segment 4 (20-25s):  Layout C — "the AI has full control..." (zoomed into terminal)
Segment 5 (25-30s):  Layout D — "let me show you..." (building anticipation)
Segment 6 (30-38s):  Layout C — screen showing the demo result (zoomed to content)
Segment 7 (38-42s):  Layout A — "it moved my face..." (face + demo side by side)
...
```

---

## 3b. Complete Effects & Capabilities Reference

### Per-Segment Canvas (regions[])

Every segment can have its own canvas with multiple composited regions. Each region specifies a source crop from the original video and an output placement on the 1080x1920 canvas.

```
"canvas": {
    "enabled": true,
    "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",  // or "blur" for gaussian blur fill
    "regions": [
        {
            "region_id": "screen",
            "source_x": 0, "source_y": 70,
            "source_width": 1800, "source_height": 1320,
            "output_x": 0, "output_y": 576,
            "output_width": 1080, "output_height": 1344,
            "z_index": 1,
            "fit_mode": "contain"   // or "cover"
        },
        {
            "region_id": "pip_speaker",
            "source_x": 1840, "source_y": 959,
            "source_width": 592, "source_height": 480,
            "output_x": 24, "output_y": 140,
            "output_width": 240, "output_height": 240,
            "z_index": 2,
            "fit_mode": "cover"
        }
    ]
}
```

**Fit modes:** `contain` (fit within bounds, may letterbox), `cover` (fill bounds, may crop edges). NEVER `stretch`.

**Background:** `#0D0D0D` (dark), `#FFFFFF` (white), any hex, or `blur` (gaussian blur of source frame — eliminates dead space beautifully).

### Per-Segment Animated Zoom (zoom{})

Animated crop that interpolates from a wide view to a tight view (or vice versa) over the segment duration. Use instead of regions[] when you want a smooth zoom effect within a single segment.

```
"canvas": {
    "zoom": {
        "start_x": 0, "start_y": 0, "start_w": 1920, "start_h": 1080,
        "end_x": 400, "end_y": 200, "end_w": 800, "end_h": 450,
        "easing": "ease_in_out"    // linear, ease_in, ease_out, ease_in_out
    }
}
```

| Zoom Effect | start → end | Use Case |
|---|---|---|
| Zoom in to UI element | Full frame → tight crop on button/text | Speaker says "look at this" |
| Zoom out reveal | Tight crop → full frame | Opening reveal, establishing shot |
| Pan across content | Same size, different x/y | Scrolling through a list or code |
| Ken Burns on screenshot | Slight zoom + diagonal drift | Static images, data slides |

### Motion Effects (add_motion)

Applied to an entire segment via `add_motion(segment_id, effect)`. These are simpler than zoom{} — predefined effects with start/end scale and easing.

| Effect | What It Does | Best For |
|---|---|---|
| `zoom_in` | Scale 1.0 → 1.3 (default) | Emphasis, drawing attention, hooks |
| `zoom_out` | Scale 1.3 → 1.0 | Reveals, establishing shots, CTAs |
| `pan_left` | Horizontal pan left | Following content, reading direction |
| `pan_right` | Horizontal pan right | Reverse reading, reveals |
| `pan_up` | Vertical pan up | Scrolling content, lists |
| `pan_down` | Vertical pan down | Scrolling down, reveals |
| `ken_burns` | Zoom + diagonal pan combined | Cinematic movement on stills, screenshots |

**Parameters:** `start_scale` (0.5-3.0), `end_scale` (0.5-3.0), `easing` (linear/ease_in/ease_out/ease_in_out)

**Intensity guide:** Subtle: 1.0→1.1. Moderate: 1.0→1.3. Strong: 1.0→2.0. Use strong sparingly.

### Speed Control

Per-segment playback speed via `speed` parameter in create_edit segments.

| Speed | Effect | Use Case |
|---|---|---|
| `0.5` | Half speed (slow-mo) | Dramatic reveals, emphasis moments |
| `0.8` | Slightly slow | Building tension, important statements |
| `1.0` | Normal | Default speech |
| `1.2` | Slightly fast | Tighten boring sections without cutting |
| `1.5` | Fast | Skip through setup/context quickly |
| `2.0` | Double speed | Time-lapse of process, code scrolling |
| `3.0-4.0` | Very fast | Montage, speed-through long demos |

### Transitions (per-segment)

Applied via `transition_in` / `transition_out` on each segment in create_edit.

| Transition | Effect | Duration | Use Case |
|---|---|---|---|
| `cut` | Hard cut (default) | 0ms | Standard, professional |
| `fade` | Fade to/from black | 200-500ms | Section changes, mood shifts |
| `crossfade` | Dissolve between segments | 300-800ms | Smooth topic transitions |
| `wipe_left` | Wipe from right to left | 200-500ms | Progressive reveals |
| `wipe_right` | Wipe from left to right | 200-500ms | Progressive reveals |
| `wipe_up` | Wipe upward | 200-500ms | Building/ascending energy |
| `wipe_down` | Wipe downward | 200-500ms | Descending energy, conclusions |
| `slide_left` | Slide content left | 200-500ms | Screen content changes |
| `slide_right` | Slide content right | 200-500ms | Screen content changes |
| `dissolve` | Soft dissolve | 300-800ms | Dreamlike, atmospheric |
| `zoom_in` | Zoom transition | 200-400ms | Entering detail, punching in |

```
{"source_start_ms": 5000, "source_end_ms": 12000,
 "transition_in": {"type": "fade", "duration_ms": 300},
 "transition_out": {"type": "crossfade", "duration_ms": 500}}
```

### Overlays

| Type | Purpose | Typical Timing | Animation |
|---|---|---|---|
| `lower_third` | Speaker name + title | First 3-5s | `slide_up` |
| `title_card` | Chapter title, key stat, bold text | 1-3s at topic changes | `slide_up` or `fade_in` |
| `logo` | Brand identity | First 4s or persistent | `fade_in` |
| `watermark` | Attribution (low opacity ~0.3) | Entire video | `none` |
| `cta` | "Follow", "Send to a friend" | Last 5-10s | `fade_in` |

**Positions:** `bottom_left`, `bottom_center`, `bottom_right`, `top_left`, `top_center`, `top_right`, `center`

**Animations:** `none`, `fade_in`, `fade_out`, `slide_up`, `slide_down` (duration: 300-500ms)

**Font sizes:** 8-200px. Hook title_card: 48-72px. Lower_third: 32-36px. CTA: 38-48px.

**Colors:** `text_color` (hex), `bg_color` (hex), `bg_opacity` (0-1). TikTok CTA: `#FF0050` red.

### Color Grading (global or per-segment)

| Parameter | Range | Default | Effect |
|---|---|---|---|
| `brightness` | -1.0 to 1.0 | 0.0 | Lighten/darken |
| `contrast` | 0.0 to 3.0 | 1.0 | Pop/flatten |
| `saturation` | 0.0 to 3.0 | 1.0 | Vivid/desaturated |
| `gamma` | 0.1 to 10.0 | 1.0 | Shadow/highlight balance |
| `hue_shift` | -180 to 180 | 0.0 | Color temperature shift |

**Per-segment color:** Pass `segment_id` to apply different grades per section. Use this for mood shifts — warm for personal statements, cool for technical demos, high-contrast for reveals.

### AI Music Generation

| Tool | Engine | Output | GPU | Use Case |
|---|---|---|---|---|
| `generate_music` | ACE-Step v1 3.5B | 48kHz stereo WAV | Yes | Original background music from text prompt |
| `compose_midi` | MIDIUtil + FluidSynth | MIDI (+ WAV) | No | Theory-correct presets: ambient_pad, upbeat_pop, corporate, dramatic, minimal_piano, intro_jingle |

**Prompt tips for generate_music:** Include genre, BPM, mood, instruments. Example: "upbeat electronic tech demo, 120 BPM, synth pads, positive energy"

### Sound Effects

| SFX Type | Sound | Use Case |
|---|---|---|
| `whoosh` | Sweep 200→8000 Hz | Scene transitions, layout switches |
| `riser` | Rising pitch + crescendo | Build tension before reveal |
| `downer` | Falling pitch + decrescendo | Deflation, disappointment |
| `impact` | Noise burst + fast decay | Text pops, emphasis hits, stat reveals |
| `chime` | Harmonic ring | Notifications, list items, steps |
| `tick` | Sharp click | UI transitions, quick cuts |
| `bass_drop` | Sub sweep 200→40 Hz | Dramatic moments, reveals |
| `shimmer` | Filtered noise, slow attack | Ethereal transitions, before/after |
| `stinger` | Impact + riser combined | Hard scene transitions |

**Rule:** Sync SFX to visual changes. A `whoosh` on every layout switch + `impact` on every stat overlay = professional feel.

### Audio Cleanup

| Operation | What It Does | When to Use |
|---|---|---|
| `noise_reduction` | Spectral gating, removes background noise | Always for recordings with ambient noise |
| `de_hum` | Removes 50/60 Hz electrical hum (3 harmonics) | Office recordings, cheap mics |
| `de_ess` | Reduces harsh sibilance (s/sh sounds) | Close-mic recordings, laptop mics |
| `normalize_loudness` | EBU R128 normalization to -16 LUFS | Always — ensures consistent volume |

### Post-Render Analysis

All pre-render visual tools work on rendered output via `render_id` parameter:

| Tool | With render_id | Use Case |
|---|---|---|
| `get_frame(render_id=X, timestamp_ms=T)` | Extract any frame from rendered video | Verify layout, captions, overlays at specific timestamps |
| `analyze_frame(render_id=X, timestamp_ms=T)` | Detect regions in rendered output | Verify content is visible, check for dead space |
| `preview_clip(render_id=X, start_ms=T)` | Preview rendered video at any point | Quick playback check of transitions |

---

## 4. Dead Space Elimination

| Priority | Technique | Notes |
|---|---|---|
| 1 | Blurred background fill | Gaussian r=40-60px of source frame |
| 2 | Cover fit | `fit_mode:"cover"`, crops edges |
| 3 | Solid dark fill | `fit_mode:"contain"`, `background_color:"#0D0D0D"` |
| 4 | Content stacking | Face+screen span full 1920px (Layouts A/B) |

---

## 5. Face Framing

### Headroom
All layouts: 30-60px (Layout B up to 80px). PIP circle: 10-20px. PIP rect: 15-25px.

### Eye Line = upper-third of face region

| Layout | Eye Y |
|---|---|
| A | 192 |
| B | 256 |
| D | 640 |
| C circle | 80 |
| C rect | 117 |

### Face Width: 60-80% of region width
Full-width: 648-864px. PIP circle: 144-192px. PIP rect: 168-224px.

### Position: Always center horizontally (x=540 for full-width). No rule-of-thirds in vertical.

### Framing Tightness

| Scenario | Framing |
|---|---|
| Hook (first 3s) | Close-up, face only |
| Tutorial narration | Medium close-up, head+shoulders |
| CTA (last 3-5s) | Medium close-up, slightly wider |
| PIP | Close-up, minimal neck |

### Webcam Extraction (screen recordings with embedded webcam)

**Capture the ENTIRE webcam image. Do NOT zoom into face.**

1. Detect exact webcam overlay boundary (x,y,w,h) via face detection
2. Use those EXACT dimensions as source crop -- do NOT subcrop
3. Output region height should match source webcam height (~500-600px)
4. Crop the webcam overlay OUT of the screen content region to prevent duplicates

Wrong: `source_width=350, source_height=400` (zoomed). Correct: `source_width=560, source_height=590` (full overlay).

---

## 6. Visual-Speech Alignment

**The viewer must SEE what the speaker is TALKING ABOUT.**

| Speaker says... | Show... | Layout |
|---|---|---|
| Intro / "I built this" | Face (credibility) | D or 50/50 |
| "Look at this dashboard" | Dashboard, BIG | C or screen-heavy |
| "You can see the file types" | File list, zoomed readable | Zoom into list |
| "Go to [website]" | Website landing page | Full-screen or split |
| Technical explanation (no screen ref) | Face | A (30/70) |
| Closing / CTA | Face (connection) | D |

Rules:
1. Screen reference → screen dominant
2. Personal statement/hook → face dominant
3. Match content changes to speech changes at same moment
4. Zoom so viewer can read specifics
5. Use word-level timestamps from WhisperX for precise switches

---

## 7. Screen Content Rules

### Mandatory Crops (always remove from source)
Browser tab bar (top 40-80px), bookmarks bar (30-40px), address bar (50-60px), OS taskbar (bottom 48px), OS dock (60-80px), OS menu bar (top 25-30px), desktop wallpaper.

### Text Legibility
Min rendered text height: 40px. Min line spacing: 1.3x. Min contrast: 4.5:1 (WCAG AA). If text <40px after scaling, zoom in.

### Zoom-In
Target: active element. Factor: 1.5x-3.0x. Animation: 300-500ms ease-in-out. Hold: 3s+ or until next topic.

### Content-Specific Crops

| Content | Crop Strategy |
|---|---|
| Website | Content area only, use contain |
| Dashboard | Stats cards as one region, lists as another |
| File list | Just the table area |
| Code editor | Just the code, zoom so text 40px+ |

Multiple small readable regions > one tiny full-screen view.

---

## 8. Using OCR & Visual Intelligence for Better Edits

ClipCannon's OCR pipeline, screen layout detection, and scene analysis give you data-driven intelligence about every frame. Use these to make edits that feel professionally produced.

### What the OCR Pipeline Detects

After `ingest`, the OCR stage (PaddleOCR PP-OCRv5 at 1fps) populates two tables:

- **`on_screen_text`**: Every detected text region with timestamp, text content, region position (center_top / center_middle / bottom_third / full_screen), font size (small / medium / large), and confidence score
- **`text_change_events`**: Slide transitions detected when >50% of on-screen text changes between frames. Includes timestamp and new title text.

### How to Use OCR Data for Viral Edits

**1. Auto-detect chapter/section boundaries from slide transitions**

Use `get_scene_map(detail="summary")` to see `screen_content` changes per scene — these are natural cut points. The `screen_content` field shows when on-screen text changed (from OCR text_change_events).

Each `text_change_event` with `type: "slide_transition"` marks where the presenter moved to a new topic/slide. Use these timestamps as segment boundaries in `create_edit` for edits that respect content structure.

**2. Smart zoom targets from OCR regions**

OCR tells you WHERE text appears and HOW BIG it is. Use this to decide zoom:

| OCR Font Size | OCR Region | Action |
|---|---|---|
| small | center_middle | Zoom 2.0-3.0x to that region -- text won't be readable otherwise |
| medium | center_middle | Zoom 1.5x for emphasis, or leave if full-screen layout |
| large | center_top | Title text -- use as overlay text or chapter marker |
| any | bottom_third | Likely UI element or subtitle -- may need to crop out |

**3. Use OCR text as caption/overlay content**

When OCR detects large title text at a slide transition, that text can be used as a `title_card` overlay:

```
add_overlay(overlay_type="title_card", text="{OCR detected title}", start_ms=..., end_ms=..., animation="fade_in")
```

This creates professional chapter markers that match the original content.

**4. Detect when to switch layouts using OCR density**

- Many text regions detected → screen-dominant layout (A, C) with zoom
- Few/no text regions → face-dominant layout (D, B)
- Slide transition → hard cut to new layout

**5. Use `analyze_frame` for per-frame intelligence**

`analyze_frame(project_id, timestamp_ms)` returns:
- `content_regions[]`: bounding boxes of text, UI panels, images, empty areas
- `pip_overlay`: detected webcam PIP position (x, y, width, height, corner, confidence)
- `frame_width`, `frame_height`

Use this to:
- Find the exact webcam overlay coordinates for extraction
- Identify the main content area coordinates for screen crops
- Detect whether a frame has text-heavy or image-heavy content

**6. Use `get_scene_map` for pre-computed edit intelligence**

`get_scene_map(project_id)` returns per-scene:
- Face position, webcam region, content area coordinates
- Pre-computed `canvas_regions` for layouts A/B/C/D (zero manual measurement)
- `visible_text[]` from OCR -- what's on screen during each scene
- `layout_recommendation` -- which layout best fits each scene's content
- `transcript_text` -- what the speaker is saying during each scene

**The scene map is your primary editing intelligence source.** It answers: "What layout should I use, what coordinates, and why?" for every scene.

### OCR-Driven Editing Workflow

```
1. ingest (runs OCR + scene_analysis + narrative_llm automatically)
2. get_editing_context → narrative.chapter_boundaries show topic shifts
3. get_scene_map(detail="summary") → screen_content + speaker_activity per scene
4. find_best_moments(purpose="tutorial_step") → prefers segments near slide transitions
5. For scenes with OCR text:
   - Small text → add zoom_in motion effect
   - Slide transition → start new segment, consider title_card overlay
   - Speaker references screen text → use Layout A/C (screen dominant)
6. create_edit → auto-validates narrative coherence
7. preview_layout at key frames → verify text readability
```

---

## 9. Pacing & Pattern Interrupts

### Cuts Per Minute by Content Type

| Content Type | Cuts/Min | Cut Interval | Platform |
|---|---|---|---|
| High-energy short-form | 15-30 | 2-4s | TikTok |
| Tutorial with screen | 8-12 | 5-8s | YouTube Shorts, Instagram |
| Talking head | 4-6 | 10-15s | YouTube, LinkedIn |
| Educational burst sequence | 15-20 burst | 3-5s burst every 2-3 min | YouTube standard |

### Pattern Interrupts (Retention Weapons)

Pattern interrupts increase watch time by up to 85% and boost conversion rates by 32%. They break the viewer's passive state and force re-engagement.

**Visual pattern interrupts to apply in ClipCannon:**

| Interrupt Type | ClipCannon Implementation | When to Use |
|---|---|---|
| Layout switch | Change from A→C→D→B between segments | Every 5-8s in short-form |
| Zoom punch-in | `add_motion(effect="zoom_in", start_scale=1.0, end_scale=1.5)` | On key words/stats |
| Text pop | `add_overlay(type="title_card", animation="slide_up")` | Reinforce spoken numbers/stats |
| Color shift | `color_adjust(saturation=1.3)` on highlight segment | Emotional peak moments |
| Speed change | `speed: 1.5` for boring sections, `speed: 0.8` for dramatic | Keep pacing tight |
| B-roll zoom | Screen-only segment with zoom into detail | When speaker references screen |

**Build-and-Release pacing:**
- Alternate fast-paced segments (2-4s cuts, zoom effects, text pops) with slower informative sections (6-10s, stable layout)
- This mirrors the attention cycle: stimulate → calm → re-engage
- Every 2-3 minutes in longer content, insert a "burst sequence" of 5-10 quick cuts

---

## 10. Platform Strategy (Data-Driven)

### Monetization Quick Reference

| Platform | Min Length to Earn | Revenue per 1M Views | Best Length for Profit |
|---|---|---|---|
| **TikTok** | **60s** (Creator Rewards) | **$200-$1,000** | **90-120s** |
| **YouTube Shorts** | No minimum (but needs YPP) | $30-$100 | 30-60s (funnel to long-form) |
| **YouTube Standard** | 8+ min (mid-roll ads) | $1,000-$10,000+ | 8-15 min |
| **Instagram Reels** | 15s (bonus programs) | Varies (invite-only) | 60-90s |
| **Facebook** | 60s (in-stream ads) | $100-$500 | 60-90s |
| **LinkedIn** | N/A (brand building) | $0 (indirect revenue) | Under 30s |

**Key insight: TikTok videos UNDER 60 seconds earn ZERO platform revenue.** Always target 60-180s for TikTok. For YouTube, Shorts pay 10-50x less than long-form — use Shorts to funnel viewers to 8+ minute videos where the real money is.

### TikTok

| Metric | Value |
|---|---|
| **Monetization minimum** | **60s+ required** for Creator Rewards Program |
| **Monetization sweet spot** | **60-180s** (1-3 min: eligible + high watch time) |
| Viral sweet spot (non-monetized) | 15-35s (highest completion rate) |
| Hook window | 1-3s (84% of viral TikToks use psychological triggers in first 3s) |
| Completion threshold | 70%+ for viral promotion, 85%+ for explosive reach |
| Visual change cadence | Every 3-5s |
| Music | Energetic 120+ BPM; trending audio gets 3x more reach |
| Avg daily watch time | 95 min globally, 52 min US |
| Engagement rate | 3.70% (up 49% YoY) |
| Algorithm weight | Watch time (~50%), shares (6/10), saves, comments, likes (weakest) |
| **CPM (revenue/1K views)** | **$0.20-$1.00** (avg $0.50-$0.70). 1M views = $200-$1000 |
| **Monetization requirements** | 10K followers, 100K views in 30 days, 18+, US/UK/FR/DE/JP/KR/BR |

**MONETIZATION STRATEGY:** Videos MUST be 60+ seconds to earn money. Target 90-120s for the optimal balance of monetization eligibility + completion rate. A 90-second video with 70% completion earns revenue; a 30-second viral video earns nothing from the platform.

**For profit, ALWAYS make TikTok videos 60-180 seconds.** Under 60s = zero platform revenue regardless of views.

**Editing for 60s+ monetization:**
- Hook (0-3s): Layout D face, bold statement
- Setup (3-15s): Layout B, context + screen
- Body (15-60s): Layout A/C alternating, full demo with screen content
- Results (60-90s): Layout C PIP, show the finished product
- CTA (last 5s): Layout D face, specific call to action
- Pattern interrupt every 5-8s to maintain watch time through the full 60s+

**Auto-trim tuning:** Moderate -- `pause_threshold_ms=700, merge_gap_ms=200, min_segment_ms=400` (less aggressive to preserve 60s+ length)

**Color:** `contrast=1.2, saturation=1.15` -- saturated, punchy colors perform best

### Instagram Reels

| Metric | Value |
|---|---|
| Optimal length | 60-90s for max engagement and views |
| **Monetization minimum** | **15s+** (bonus programs), **5K followers** required |
| Hook window | 2-3s (up to 50% drop in first 3s) |
| 3s hold rate | 60%+ = 5-10x more total reach |
| Visual change cadence | Every 4-6s |
| Music | Trending audio preferred |
| Engagement rate | 1.23% (Reels specifically) |
| #1 algorithm signal | Watch time; DM sends/reach is strongest for NEW audience |
| **Revenue model** | Bonus programs (invite-only), brand deals, affiliate links |

**Strategy:** More polished than TikTok. Cover frame matters. 10-second Reel with 80% retention beats a 60-second Reel at 30%. Design for DM shareability ("send this to your [friend who...]").

**Color:** `contrast=1.1, saturation=1.1` -- slightly elevated, polished look

### YouTube Shorts

| Metric | Value |
|---|---|
| Optimal length | 30-60s (highest view counts) |
| **Monetization minimum** | **No min length**, but needs YPP (1K subs + 10M Short views in 90 days) |
| **Revenue share** | **45% to creator** (YouTube keeps 55% of Shorts ad pool) |
| **CPM** | **$0.03-$0.10 per 1K views** ($30-$100 per 1M views) |
| Hook window | 2s |
| Top performer retention | 80-90% completion |
| "Skippable" threshold | Below 50% completion |
| Visual change cadence | Every 4-7s |
| Music | Optional; educational content often better without |
| Key metric | Every loop counts as a new view |
| **YPP Tier 1** | 500 subs + 3M Short views in 90 days (fan funding only) |
| **YPP Tier 2** | 1K subs + 10M Short views in 90 days (full ad revenue) |

**MONETIZATION STRATEGY:** YouTube Shorts pay the least per view ($0.03-$0.10/1K) but have no minimum length. The real money is driving Shorts viewers to long-form content (which pays 10-50x more per view). Every Short should funnel to a longer video.

**Strategy:** Educational content dominates. Title card critical. Subscribe CTA valuable. Design for loops: seamless ending that leads back to start. Median views tripled YoY (86 in 2024 to 268 in 2025).

**Color:** `contrast=1.05, brightness=0.05` -- clean, professional

### YouTube Standard (Long-Form)

| Metric | Value |
|---|---|
| Optimal length | 7-15 minutes |
| Hook window | 8 seconds (viewer decision point) |
| Average retention | 23.7% (strong intros at 65%+ at 30s = 58% higher avg view duration) |
| 55% of viewers | Drop off within first 60 seconds regardless of length |
| Thumbnail CTR avg | 4-6% (7%+ good, 10%+ excellent) |

**Strategy:** Strong intro within 8s. Custom thumbnails with expressive faces (20-30% higher CTR). Pattern interrupts every 2-3 minutes. Chapters aligned to topic changes.

### Facebook

| Metric | Value |
|---|---|
| Optimal length | 15-60s Reels, completion rate matters most |
| Hook window | 2-3s |
| Key behavior | Muted autoplay -- captions are mandatory |
| Engagement rate | 0.15% (declining, but saves/shares are powerful) |
| Algorithm | Every uploaded video auto-classified as Reel since mid-2025 |
| Audience | Older demo (30-55) |
| First 1-2 hours | Critical for initial engagement that drives distribution |

**Strategy:** Captions essential (muted autoplay). 80% value-driven content. Lead with the takeaway, not build-up. Saves and shares > reactions.

**Color:** Standard -- `contrast=1.0, saturation=1.0`

### LinkedIn

| Metric | Value |
|---|---|
| Optimal length | Under 30s = 200% higher completion; under 2 min for engagement |
| Hook window | 3-5s (professional, lead with value) |
| Native video boost | +69% performance, 5x engagement vs other media, 3x vs text |
| Sound-off viewing | 85% -- captions absolutely mandatory |
| Engagement rate | 6.5% median (highest of any platform) |
| Posting sweet spot | 3-8 PM weekdays, peaks Wed-Fri |

**Strategy:** Professional tone. Lead with value/data. Soft CTA. No music or very subtle. Brand/logo visible in first 4s. Short and dense beats long and rambling. Data resonates.

**Auto-trim tuning:** Gentle -- `pause_threshold_ms=1200, merge_gap_ms=200, min_segment_ms=1000`

**Color:** `contrast=1.0, saturation=0.95` -- desaturated, controlled, professional

---

## 11. Hook Engineering (First 3 Seconds)

The hook is the highest-leverage edit. 65% longer watch times and 41% higher completion rates when the 3-second hook lands.

### Hook Types That Work

| Hook Type | Example | Layout | Caption Style |
|---|---|---|---|
| Bold statement | "This one feature saved me 40 hours" | D (face close-up) | Large bold text overlay |
| Question | "Why do 90% of developers get this wrong?" | D | Question as title_card |
| Pattern interrupt | Unexpected visual, fast zoom, camera shake | D → rapid cut | Bold centered, word highlight |
| Shocking stat | "Only 3% of videos get this right" | D with stat overlay | Number as overlay, face behind |
| "You're doing X wrong" | "You're reading docs wrong -- here's why" | D (face, slight lean in) | Bold centered |
| Before/After tease | Show the end result first | Screen dominant | "Here's how" overlay |

### Hook Implementation in ClipCannon

```
1. First segment: 0-3000ms, Layout D (full-face), speed=1.0
2. add_motion(segment_id=0, effect="zoom_in", start_scale=1.0, end_scale=1.15, easing="ease_out")
3. add_overlay(type="title_card", text="Hook text here", start_ms=200, end_ms=2800,
   font_size=52, animation="slide_up", animation_duration_ms=300)
4. Bold caption with word_highlight style for TikTok
```

### Anti-Patterns (Kill Retention)

- Logos/intros before the hook (viewers leave immediately)
- "Hey guys, so today I wanted to talk about..." (filler opening)
- Starting with context instead of payoff (save setup for 3-8s)
- Slow fade-in (use hard cut into action)

---

## 12. Captions

| Platform | Style | Size | Y Pos | Weight | Stroke | Background |
|---|---|---|---|---|---|---|
| TikTok | bold_centered | 48-52px | 1440 | 800 | 3px black | None |
| Instagram | bold_centered | 44-48px | 1400 | 800 | 3px black | None |
| YouTube | subtitle_bar | 32-36px | 1530 | 600 | None | #000 @60% |
| Facebook | bold_centered | 40-44px | 1420 | 700 | 3px black | None |
| LinkedIn | subtitle_bar | 28-32px | 1570 | 500 | None | #1A1A1A @80% |

**Bold centered:** font=Inter/Montserrat, color=#FFF, stroke=3px #000, max_width=860px, centered x=540, max 2 lines. Optional word highlight: #FFD700 or #00E5FF (TikTok).

**Subtitle bar:** font=Inter/Roboto, color=#FFF, bg padded 8-10px v / 16-20px h, radius=6px, max_width=960px, max 2 lines.

**Viral caption strategies:**
- Kinetic typography (moving text) improves comprehension and stops scrolling
- Bold text overlays at the start are a cornerstone of 2025-2026 engagement
- "Send this to..." text prompts drive shares (the #2 algorithm signal)
- Keep 12-24 characters per line for mobile readability
- Sans-serif fonts only (Arial, Helvetica, Roboto, Montserrat)

---

## 13. Video Structure Templates

### TikTok / Instagram (15-60s)
```
0-3s    D   HOOK (face, bold opening, pattern interrupt)
3-8s    A/B CONTEXT (split, speaker+screen, validate hook)
8-15s   C/A DEMO (screen-dominant, zoom-ins to OCR text regions)
15-25s  E   DETAILS (dynamic 3-5s changes, use OCR slide transitions as cut points)
25-30s  D   CTA (face, "send this to someone who...", specific action)
```

### YouTube Shorts (30-60s)
```
0-2s    D   HOOK (bold statement or question)
2-10s   A/B SETUP (credibility, why should viewer care)
10-40s  E   WALKTHROUGH (dynamic, PIP, every 5-7s, zoom on OCR text)
40-55s  A/B KEY TAKEAWAY (face+screen, data emphasis)
55-60s  D   CTA (subscribe, loop back to hook frame for replay)
```

### LinkedIn (30-120s)
```
0-5s    A/B PROFESSIONAL HOOK (lead with value/data, brand visible)
5-30s   C/A DEMO (screen-dominant, every 6-10s, zoom on metrics)
30-60s  B/D VALUE EXPLANATION (face dominant, data overlays)
60-90s  C   RESULTS/PROOF (metrics, screenshots, zoom to numbers)
90-120s D/B CLOSING (soft CTA, professional tone)
```

Hook and CTA are non-negotiable on all platforms.

---

## 14. Auto-Trim

Removes 20 filler words (um, uh, like, basically, literally, actually, you know, i mean, right, okay, so, well, yeah, etc.) and silence gaps.

| Param | Default | Description |
|---|---|---|
| `pause_threshold_ms` | 800 | Pauses longer → removed |
| `merge_gap_ms` | 200 | Segments closer → merged |
| `min_segment_ms` | 500 | Segments shorter → dropped |

| Platform | Style | Settings |
|---|---|---|
| TikTok | Aggressive | 500/200/300 |
| Instagram | Moderate | 700/200/400 |
| YouTube Shorts | Moderate | 800/200/500 |
| YouTube Standard | Gentle | 1000/200/800 |
| Facebook | Moderate | 700/200/400 |
| LinkedIn | Gentle | 1200/200/1000 |

Flow: `auto_trim` → segments[] → `create_edit(segments=segments)`

---

## 15. Color Grading

| Param | Range | Default |
|---|---|---|
| `brightness` | -1.0 to 1.0 | 0.0 |
| `contrast` | 0.0 to 3.0 | 1.0 |
| `saturation` | 0.0 to 3.0 | 1.0 |
| `gamma` | 0.1 to 10.0 | 1.0 |
| `hue_shift` | -180 to 180 | 0.0 |

Omit `segment_id` for global. Include for per-segment override.

| Platform | Grade | Reasoning |
|---|---|---|
| TikTok | contrast=1.2, saturation=1.15 | Punchy, saturated = more stops |
| Instagram | contrast=1.1, saturation=1.1 | Polished, slightly elevated |
| YouTube | contrast=1.05, brightness=0.05 | Clean, professional |
| Facebook | contrast=1.0, saturation=1.0 | Standard, broad audience |
| LinkedIn | contrast=1.0, saturation=0.95 | Desaturated = professional trust |

**Color pacing tip:** Vary color temperature/saturation across scenes to create visual progression. Static color throughout causes viewer fatigue.

---

## 16. Motion Effects

| Effect | Use | Viral Application |
|---|---|---|
| `zoom_in` | Emphasis, attention | Punch-in on key words/stats -- #1 viral technique |
| `zoom_out` | Reveals, establishing | Opening shots, before/after reveals |
| `pan_left/right` | Following content | Scrolling UI, lists, code |
| `pan_up/down` | Scrolling content | Long pages, feeds |
| `ken_burns` | Cinematic, still images | Screenshots, data slides |

Params: `start_scale` (0.5-3.0, default 1.0), `end_scale` (0.5-3.0, default 1.3), `easing` (linear/ease_in/ease_out/ease_in_out).

Guidelines: Subtle=1.0→1.1. Moderate=1.0→1.3. Strong=1.0→2.0 (sparingly). Ken Burns best for stills/screenshots.

**Rule: Every effect must serve a purpose.** Minimalist, purposeful editing outperforms flashy effects. Over-the-top transitions hurt retention.

Pipeline order: motion → color → captions → overlays.

---

## 17. Overlays

| Type | Use | Viral Application |
|---|---|---|
| `lower_third` | Speaker ID (name+subtitle) | Credibility signal, first 5s |
| `title_card` | Chapter titles, intro | From OCR slide transitions, section markers |
| `logo` | Brand identity | First 4s (LinkedIn: +69% performance) |
| `watermark` | Attribution (opacity ~0.3) | Consistent brand |
| `cta` | "Subscribe", "Send to a friend" | Last 3-5s, specific action |

Key params: `text`, `position` (bottom_left/center/right, top_left/center/right, center), `start_ms`, `end_ms`, `font_size` (8-200, default 36), `text_color` (#FFF), `bg_color` (#000), `bg_opacity` (0.7), `animation` (none/fade_in/fade_out/slide_up/slide_down), `animation_duration_ms` (500).

Lower thirds: 3-5s duration, fade in 500ms, keep within platform safe zone.

**Stat overlay strategy:** When the speaker mentions a number or percentage, add it as a large title_card overlay (font_size=72, 1-2s duration, slide_up animation). Numbers as visual text are the most shared content element.

---

## 18. Audio Strategy

### Audio Cleanup

| Operation | Filter | Use |
|---|---|---|
| `noise_reduction` | anlmdn | Background noise |
| `de_hum` | bandreject 3 harmonics | Electrical hum (50/60Hz) |
| `de_ess` | highpass+lowpass | Harsh sibilance |
| `normalize_loudness` | loudnorm EBU R128 | Normalize to -16 LUFS |

Order: noise_reduction → de_hum → de_ess → normalize_loudness.

Audio source priority: vocals.wav > audio_original.wav > audio_16k.wav > any .wav in stems/

| Scenario | Operations |
|---|---|
| Office recording | noise_reduction, de_hum |
| Laptop mic | de_ess, normalize_loudness |
| Good mic, quiet room | normalize_loudness |
| Noisy environment | noise_reduction, normalize_loudness |

### Sound Effects for Retention

Sound design elements that boost retention:

| SFX Type | When to Use | Viral Application |
|---|---|---|
| `whoosh` | Scene transitions, layout switches | Signals visual change, prevents passive watching |
| `impact` | Text pop-ins, stat reveals | Punctuates key moments |
| `riser` | Building to reveal or key point | Creates anticipation before payoff |
| `chime` | Notifications, list items | Marks steps in tutorials |
| `shimmer` | Reveals, before/after transitions | Adds polish to transformation content |

**Rule:** Sync SFX to visual transitions. A whoosh on a layout switch + text pop with impact sound = professional feel that holds attention.

### Music Strategy by Platform

| Platform | Music Approach |
|---|---|
| TikTok | Trending audio (3x reach). Energetic 120+ BPM. Act fast -- trends last 1-3 weeks. |
| Instagram | Trending audio preferred. Match energy to content mood. |
| YouTube Shorts | Optional. Educational often better without. |
| YouTube Standard | Background music at -18dB with speech ducking. |
| Facebook | Optional. Captions matter more than audio. |
| LinkedIn | None or very subtle ambient. Professional tone. |

---

## 19. Preview & Inspection

**preview_layout**: Single composited frame, ~300ms. Use to validate crop/layout before render.

**preview_clip**: 540x960, 1Mbps, ultrafast, max 5s, 0 credits, ~500-1000ms. Use at key timestamps (hook, CTA, transitions).

**inspect_render**: Post-render. Checks file size, duration, resolution, codec, audio presence. Extracts frames at 0%, 25%, 50%, 75%, end.

Workflow: decide coords → preview_layout → adjust → repeat → render → inspect_render → fix if needed.

---

## 20. Complete Workflow (39 MCP Tools)

### Available Tools

| Category | Tools | Token Cost |
|---|---|---|
| **Understand** | `get_editing_context`, `get_transcript`, `get_scene_map`, `search_content`, `analyze_frame`, `get_frame` | 2K-10K |
| **Discover** | `find_safe_cuts`, `find_best_moments`, `find_cut_points`, `get_narrative_flow` | 1K-5K |
| **Edit** | `create_edit`, `modify_edit`, `auto_trim`, `color_adjust`, `add_motion`, `add_overlay` | <100 each |
| **Preview** | `preview_layout`, `preview_clip` | 2K-3K (images) |
| **Render** | `render`, `inspect_render` | <300 |
| **Audio** | `audio_cleanup`, `generate_music`, `compose_midi`, `generate_sfx` | <100 each |
| **Project** | `project_create/open/list/status/delete`, `ingest` | <300 |
| **System** | `config_get/set/list`, `disk_status/cleanup`, `credits_balance/history/estimate/spending_limit` | <50 each |

**Token budget for full workflow on 8-minute video: ~20K tokens.**

### Workflow

```
1. CREATE + INGEST
   project_create → ingest → wait "ready"

2. UNDERSTAND THE VIDEO (3 calls, ~15K tokens total):
   a) get_editing_context → Qwen3-8B narrative analysis
      (story_beats, open_loops, chapters, speakers, transcript preview)
      Read the story_beats. Identify: PROMISE and PAYOFF.

   b) get_transcript → full transcript TEXT
      Default mode returns text only (no word timestamps). ~700 tokens/min.
      READ THIS. Understand what the speaker says, in what order.

   c) get_scene_map(detail="summary") → L-Storyboard for every scene
      Each scene includes: transcript_preview, screen_content (from OCR),
      speaker_activity (direct_address/screen_reference/narrating),
      energy, layout recommendation, face detection.
      This is the PRIMARY editing intelligence. ~80 tokens/scene.
      For a 2-hour video: ~40K tokens for ALL scenes.

   After these 3 calls you know:
   - The full story arc (narrative)
   - Every word spoken (transcript)
   - What's on screen at every moment (scene_map)
   - Where the speaker is looking/doing (speaker_activity)
   - The emotional energy curve (energy per scene)

3. FIND SAFE CUTS (1 call, ~1K-5K tokens):
   find_safe_cuts(project_id) → audio-safe cut points

   Each cut shows exact words before/after the gap.
   READ the words — they tell you what the transition sounds like.

   RULE: ONLY use cut_before_ms / cut_after_ms as segment boundaries.
   No manually picked timestamps. No transcript timestamps.

4. PLAN SEGMENTS (use scene_map + transcript + safe cuts):

   For FULL-LENGTH (keeping most content):
     - auto_trim → natural 5-15s segments with fillers removed
     - For EACH segment: read its scene_map entry
     - speaker_activity tells you the layout:
         "direct_address" → Layout D or B (face dominant)
         "screen_reference" → Layout A or C (screen dominant)
         "narrating" → Layout B (balanced)
     - screen_content tells you what to crop to
     - Apply motion effects, zoom, speed per segment
     - Target: 15-30+ segments for 3-8 min video

   For SHORT CUTS (condensing to 60-180s):
     - Use safe cuts to select audio-safe boundaries
     - Map to story_beats: hook → setup → demo → result → cta
     - Break into 5-10s segments, each with own canvas
     - Verify with get_narrative_flow (no BROKEN_PROMISE warnings)

   Layout rules:
     - NEVER same layout for >8 seconds
     - Progression: D → B → A → C → D
     - Use ALL effects: zoom, speed, transitions, overlays, SFX
     - Every segment gets motion (even subtle 1.0→1.05)

5. VERIFY NARRATIVE (required for non-contiguous edits):
   get_narrative_flow(segments) → fix all BROKEN_PROMISE warnings

6. VERIFY VISUALS (1 call per key segment):
   preview_layout(timestamp_ms, regions) → look at frame
   Use webcam region (not face bbox) for speaker crops.

7. BUILD:
   create_edit with per-segment canvas for each segment
   Then: color_adjust + add_motion + add_overlay per segment
   Add SFX on transitions, overlays on stat mentions

8. RENDER + INSPECT:
   render → get_frame(render_id, timestamps) → verify output
   If wrong → fix → re-render
```

### How find_safe_cuts Works

The tool queries every silence gap in the video, then for each gap:

1. **Word context**: Finds the exact 3 words before and 3 words after the gap from `transcript_words` (word-level timestamps from WhisperX)
2. **Thought completeness**: Checks if the transcript segment at the gap ends with `.!?` or the verbal period "right"
3. **Beat alignment**: Checks if a beat position (from librosa) falls within 500ms — cuts on beats feel professional
4. **Scene boundary**: Checks if a visual scene change (from scene_map) aligns within 500ms
5. **Text change**: Checks if an OCR slide transition happened within 1000ms
6. **Emotion energy**: Reads the Wav2Vec2 emotion curve at that timestamp
7. **Promise detection**: Scans the last 2 sentences for promise keywords ("you can see", "let me show", etc.) — if found, warns that cutting here breaks a promise

The safety score (0-100) combines all signals. Higher = safer to cut.

The `cut_before_ms` and `cut_after_ms` values include 50ms audio padding to avoid clipping consonant tails and intake breaths. If a beat aligns, the cut snaps to the beat for rhythmic editing.

### Point Queries

Use `get_scene_map(detail="full", layout="D")` for canvas regions per scene.
Use `get_frame(timestamp_ms=X)` to visually inspect any specific moment.

---

## 21. Common Editing Mistakes (NEVER Do These)

These are real failures from production edits. Each one degraded the output video. Learn from them.

### Mistake 1: Cutting mid-sentence / mid-thought

**What happened**: Segments were cut at arbitrary timestamps (6190ms, 14349ms) that fell in the middle of sentences. The speaker says "I built the world's first video editor specifically designed—" and it cuts. The viewer never hears the complete thought.

**Rule**: ALWAYS use `find_safe_cuts` to get audio-safe cut points. NEVER set `source_end_ms` or `source_start_ms` to any timestamp that didn't come from `cut_before_ms` / `cut_after_ms` in the safe cuts response. Each safe cut shows the exact words before and after — read them to verify the audio transition makes sense.

**How to verify**: For every segment boundary, confirm it matches a `cut_before_ms` or `cut_after_ms` from `find_safe_cuts`. If it doesn't, the cut is unsafe and will clip audio.

### Mistake 2: Video way too short — not using available duration

**What happened**: Created a 46-second TikTok from an 8-minute video when the user said "under 3 minutes." Left 134 seconds of allowed duration unused. The video felt rushed and incomplete because it skipped the entire middle of the story.

**Rule**: Use the transcript to map the full narrative arc BEFORE choosing segments. Identify: introduction, setup, demonstration, results, closing. Include ALL narrative beats — don't skip from intro to closing. If the platform allows 3 minutes, use 2-2.5 minutes minimum. Fill the time with the story, not silence.

**Narrative arc template**:
```
Hook (0-5s):    Bold statement, face close-up. Viewer decides to stay.
Setup (5-20s):  Context. WHY should viewer care? What problem is solved?
Demo (20-90s):  Show the thing. Screen content. This is the meat.
Results (90-120s): What was the outcome? Show the finished product.
CTA (last 5s):  Face close-up. Specific call to action.
```

### Mistake 3: Skipping the preview loop

**What happened**: Went straight from `get_scene_map(timestamp_ms=X)` coordinates to `create_edit` to `render` without previewing. The hook frame had terminal JSON text bleeding into the face close-up. This was only discovered after a full render that took 2 minutes and crashed WSL.

**Rule**: ALWAYS preview EVERY segment before creating the edit.
```
For each segment:
  1. preview_layout(timestamp_ms, regions) → look at the image
  2. If text/artifacts visible → adjust source_x/y/w/h → re-preview
  3. Only proceed when the preview is clean
```
This takes ~300ms per preview. A 4-segment edit takes 1.2 seconds to verify. A bad render takes 2 minutes and may crash the system.

### Mistake 4: Jarring layout jumps (face size inconsistency)

**What happened**: The face went from 1080px wide (full screen) → 240px (tiny PIP box) between consecutive segments. The viewer's focus was on a large face, then suddenly it's a tiny corner box. This is disorienting.

**Rule**: Use smooth layout progression, never jump more than one layout level:
```
SMOOTH:  D (full face) → B (40/60) → A (30/70) → C (PIP) → D (face CTA)
JARRING: D (full face) → C (PIP)  ← NEVER do this
JARRING: D (full face) → A (30/70) → D (full face) → C (PIP)  ← inconsistent
```

Each layout transition should feel like a gentle "zoom out" (D→B→A→C) or "zoom in" (C→A→B→D). The viewer's eye should track the face as it smoothly changes size.

### Mistake 5: Using generic scene_map regions instead of per-timestamp analysis

**What happened**: Used pre-computed canvas_regions from `get_scene_map(timestamp_ms=X)` which represent the general scene (8-second average). But at the specific timestamp, the webcam overlay overlapped with terminal text, making the face crop include code artifacts.

**Rule**: For face-dominant layouts (D, B, A speaker region), ALWAYS verify the source crop coordinates with `preview_layout` at the EXACT start timestamp of the segment. The webcam overlay position shifts slightly between frames, and surrounding content changes constantly in screen recordings.

### Mistake 6: Not reading the full transcript before editing

**What happened**: Selected segments based on highlight scores and timestamps without reading what the speaker actually says at those times. The result: segments that look good on paper (high emotion score, visual reference detected) but don't tell a coherent story when played in sequence.

**Rule**: Before creating any edit, call `get_transcript(project_id, start_ms=0)` and read the full transcript. Identify the story structure. Mark the key moments where the speaker makes complete statements. THEN choose segments that preserve complete thoughts and tell the story in order.

### Mistake 7: Zooming into face instead of capturing full webcam overlay

**What happened**: For face-dominant layouts (D, B, A speaker region), used the **face bounding box** (482x482px — just the face) instead of the **webcam overlay region** (831x686px — head, shoulders, and chair). The result: every face segment was an extreme close-up showing only forehead-to-chin. The viewer couldn't see the speaker's body language, microphone, chair, or natural framing. This happened across ALL THREE versions (v1, v2, v3) despite the guide explicitly saying in bold: **"Capture the ENTIRE webcam image. Do NOT zoom into face."**

**Root cause**: The scene_map stores BOTH `face` coordinates (tight bounding box around the face) and `webcam` coordinates (the full webcam overlay area). I used `face` when I should have used `webcam`. The face data is for DETECTION — knowing WHERE the face is. The webcam data is for CROPPING — the actual source region to use in canvas regions.

**Rule**: ALWAYS use the `webcam` region from scene_map for speaker source crop, NEVER the `face` region. The face region is for detection only.

```
WRONG:  source_x=2925, source_y=1563, source_width=482, source_height=482  (face bbox — zoomed)
RIGHT:  source_x=2718, source_y=1474, source_width=831, source_height=686  (webcam overlay — full)
```

In `get_scene_map(timestamp_ms=X)` point query response:
- `scene.face` = detection data (where the face IS). Use for knowing IF a face exists.
- `scene.webcam` = crop data (what to SHOW). Use for canvas region source coordinates.

For Layout D (full-screen speaker): use webcam region as source, output to full 1080x1920 canvas.
For Layout A/B (split): use webcam region as source, output to speaker strip.
For Layout C (PIP): use webcam region as source, output to PIP box.

### Mistake 8: Using PIP layout when speaker is talking directly to camera

**What happened**: At 1:18 the speaker is making a direct statement to camera ("let me show you the video that was created from the base video") but I put them in a tiny 280x232 PIP in the top-left corner instead of keeping them as the dominant visual. The PIP layout is for when screen content is the star and the speaker is narrating. When the speaker is making a direct statement, they should be Layout D (full) or Layout B (40/60 split).

**Rule**: Choose layout based on WHAT THE SPEAKER IS DOING, not what section of the video you're in:
- Speaker making direct statement to camera → **Layout D** (full webcam)
- Speaker explaining while showing screen → **Layout B** (40/60 split)
- Speaker narrating over screen walkthrough → **Layout A** (30/70 split)
- Screen content is the star, speaker just commenting → **Layout C** (PIP)

Read the transcript for each segment. If the speaker says "I", "you", "we", "let me" — they're addressing the viewer directly. Use Layout D or B. If they say "you can see here", "this shows", "look at" — they're referencing screen content. Use Layout A or C.

### Mistake 9: Cutting at sentence boundaries but not thought boundaries

**What happened**: Used `find_cut_points` sentence_end signals to find grammatically correct cut points. But a sentence ending is not always a thought ending. "Let me show you the video." is a complete sentence, but cutting right after it means the viewer never sees the video being shown. The THOUGHT is "let me show you the video [shows video]" — both parts are needed.

**Rule**: Use `find_safe_cuts` which checks both sentence completeness AND promise keywords. If a cut has `warning: "PROMISE_OPEN: speaker says 'let me show'"`, do NOT use that cut — it will break the viewer's expectation. After selecting cuts, read the `words_before` and `words_after` — if the words after are the continuation of the words before, the cut is in the wrong place.

**Thought-completion patterns to watch for:**
- "Let me show you..." → MUST include the showing
- "Here's what happened..." → MUST include what happened
- "The reason is..." → MUST include the reason
- "You can see..." → MUST include what they see
- "So what [X] did was..." → MUST include what X did
- Any setup/payoff pair — never cut between setup and payoff

**Verification**: For each segment, read the last sentence AND the first sentence of the NEXT segment in your source. If the next sentence completes an idea from the last sentence, extend the segment to include it.

### Mistake 10: Ignoring Qwen3 BROKEN_PROMISE warnings from get_narrative_flow

**What happened**: Called `get_narrative_flow` to validate proposed segments. Qwen3 returned BROKEN_PROMISE warnings like "speaker says 'you can see' but the continuation is in this gap" and LARGE_GAP warnings. Ignored all of them and created the edit anyway. The resulting video had jarring jumps where the speaker promises to show something, then the video cuts to a completely different topic. The viewer feels cheated.

**Root cause**: Treated `get_narrative_flow` as a checkbox tool ("I called it") instead of reading and acting on the response. The BROKEN_PROMISE warnings are the LLM telling you the edit will confuse viewers. They are NOT informational — they are errors that must be fixed before proceeding.

**Rule**: When `get_narrative_flow` returns warnings:
- **BROKEN_PROMISE**: MUST fix. Extend the segment to include the continuation, or remove the segment entirely. A broken promise is worse than a missing segment.
- **LARGE_GAP**: Review the skipped content. If it contains setup/context needed by the next segment, include it. If it's genuinely skippable (technical details, tangents), acceptable.
- **thought_complete: false**: Check the last sentence. If it ends mid-idea, extend to the next natural pause.

**Workflow**: Call `get_narrative_flow` → read ALL warnings → fix segments → call `get_narrative_flow` again → repeat until no BROKEN_PROMISE warnings remain.

### Mistake 11: Using same layout (PIP) for every segment

**What happened**: Applied Layout C (PIP with small speaker overlay) to ALL segments. The hook was a tiny face in a corner instead of a full-face close-up. The CTA was the same tiny face. There was no visual variety — the viewer's eye had nothing new to track, causing the "monotonous pacing" dropout trigger.

**Rule**: Every TikTok/Short needs layout progression. Follow the template:
```
D (hook) → B (setup) → A (demo) → C (screen-heavy) → A (features) → B (transition) → D (CTA)
```
The layout should match the speaker's ACTIVITY at that moment (see Mistake 8). Visual change every 5-8 seconds is the #1 retention weapon.

### Mistake 12: Audio clipping at word boundaries — cutting at transcript segment timestamps

**What happened**: Used transcript segment timestamps (e.g., segment ends at 8330ms) as cut points. But transcript timestamps mark when the speech content ends, not when the audio waveform ends. Consonants like "m" in "system." have a tail that extends 50-100ms past the transcript timestamp. Cutting exactly at 8330ms clips the final consonant, making it sound like "syste-".

Similarly, starting the next segment at the transcript start time (8390ms) clips the intake breath before "This". The viewer hears "-is is full document..." instead of "This is full document...".

**Rule**: Add audio padding at every cut point:
- **Segment start**: Subtract 50-100ms from the first word's start_ms. This captures the intake breath.
- **Segment end**: Add 100-150ms after the last word's end_ms. This captures consonant tails and natural room tone.
- **Contiguous segments**: When two segments are from adjacent source material (gap < 200ms), merge them into one segment. The concat will introduce a micro-gap; keeping them as one segment avoids it.

**Solution**: Use `find_safe_cuts` which handles all of this automatically. It finds silence gaps (natural pauses where there IS no audio to clip), adds 50ms padding, and snaps to beat positions. The returned `cut_before_ms` and `cut_after_ms` values are safe to use directly — no manual padding needed.

```
WRONG:  source_end_ms = 8330   (transcript segment end — clips "system." tail)
WRONG:  source_end_ms = 8400   (manual padding — still guessing)
RIGHT:  source_end_ms = 39406  (from find_safe_cuts.cut_before_ms — silence gap + padding)
```

The key insight: don't cut between words. Cut during silence gaps where there IS no audio. `find_safe_cuts` only returns cuts at silence gaps, so every cut is inherently audio-safe.

### Mistake 13: Treating tool calls as a checklist instead of thinking like an editor

**What happened**: Used all 39 tools in sequence, checked them off, and declared victory. But the resulting video was incoherent because no creative judgment was applied. The tools were used to PROVE they work, not to MAKE a good video. find_best_moments returned scored candidates — used them. get_narrative_flow returned warnings — ignored them. The edit was optimized for tool coverage, not viewer experience.

**Root cause**: An AI video editor must think like a human editor: (1) watch/read the full content, (2) understand the story arc, (3) choose segments that tell THAT story, (4) verify the narrative makes sense, (5) iterate until it's right. The tools exist to support this creative process, not to replace it.

**Rule**: Before touching any editing tool, answer these questions:
1. What is the PROMISE of this video? (What will the viewer learn/see?)
2. What is the PAYOFF? (Where in the source is the promise fulfilled?)
3. What is the STORY ARC? (Hook → Setup → Demo → Result → CTA)
4. Which segments from the transcript tell this specific story?
5. Does each segment END at a complete thought?
6. Does the next segment START coherently after the gap?

Only after answering all 6 should you call `create_edit`. Then `get_narrative_flow` to verify. Then fix. Then render.

---

### Mistake 14: Using few large segments with static layouts instead of many small dynamic ones

**What happened**: Created 4 segments for a 3-minute TikTok — each segment was 30-70 seconds long with ONE static canvas layout. The speaker changes topic, references different screen content, shifts between direct address and screen walkthrough — but the layout never changes. The result looks like a cheap screencast, not a professional edit. Dead space everywhere because the single crop can't track moving content.

**Root cause**: Treating segments as "story sections" (hook, demo, CTA) instead of "editing units." A human editor cuts every 3-8 seconds. Each cut is an opportunity to reframe, zoom, switch layout, add emphasis. With 4 segments, there are only 3 cuts in the entire video. With 30 segments, there are 29 opportunities for visual change.

**Rule**: Use `auto_trim` to get natural segments (typically 15-35 segments for a 3-8 minute video). Each segment gets its OWN per-segment canvas matching the speaker's activity at that moment. Apply motion effects, zoom, and speed changes per segment. The result should have a visual change every 5-8 seconds — layout switches, zoom punches, speed changes, overlays appearing/disappearing.

**What to do with each segment:**
1. Read the transcript for that segment
2. If speaker addresses camera directly → Layout D (face)
3. If speaker references screen content → Layout A/C with screen crop matching WHAT they're referencing
4. Apply zoom_in on emphasis moments, ken_burns on screenshots
5. Add whoosh SFX on layout transitions, impact SFX on stat reveals
6. Speed up boring transitions (1.2-1.5x), slow down reveals (0.8x)

### Mistake 15: Not using the full range of video editing effects

**What happened**: Only used canvas regions, color grading, and two motion effects (zoom_in on hook, zoom_out on CTA). Ignored: transitions between segments, per-segment speed control, per-segment color shifts, animated zoom (zoom{}), SFX synced to visual changes, overlays on stat mentions, ken_burns on static screenshots. The system has the equivalent of every video editing tool in existence — and I used 5% of it.

**Rule**: For every segment, consider ALL of these:
- Canvas regions (per-segment layout)
- Animated zoom (zoom{} for smooth crop animation within a segment)
- Motion effects (zoom_in/out, pan, ken_burns)
- Speed control (0.5x-4.0x per segment)
- Transitions (fade, crossfade, wipe, slide, dissolve between segments)
- Color grading (per-segment mood shifts — warm/cool/high-contrast)
- Overlays (title_card on topic changes, stats on number mentions)
- SFX (whoosh on transitions, impact on reveals, riser before payoffs)
- Music (AI-generated background at -18dB with speech ducking)

A professional edit uses ALL of these in combination. A basic edit uses 2-3.

---

## 22. Quality Checklist

- No stretching (cover or contain, NEVER stretch)
- Face centered horizontally (±20px of center)
- Eyes on upper-third line (±30px)
- Headroom 30-60px, face width 60-80%
- No duplicate webcam in output
- No browser chrome / OS taskbar visible
- All text ≥40px rendered height (use OCR font_size data to verify)
- Captions above platform danger zone, within safe zone
- No unintentional black bars; dark fill = #0D0D0D
- Hook in first 3s (Layout D), CTA in last 3-5s (Layout D)
- Visual change every 3-8s (platform dependent)
- Captions on all spoken content, accurate within 100ms, max 2 lines
- **Pattern interrupt every 5-8s in short-form** (layout switch, zoom, text pop, or color shift)
- **OCR text regions readable** at ≥40px after scaling (zoom if not)
- **Sound effects synced** to visual transitions
- **Silent viewing test**: Does the video make sense with captions only, no audio?

---

## Quick Reference

| Measurement | Value |
|---|---|
| Canvas (9:16) | 1080x1920, center (540,960) |
| Canvas (16:9) | 1920x1080, center (960,540) |
| Canvas (4K 16:9) | 3840x2160, center (1920,1080) |
| Canvas (1:1) | 1080x1080, center (540,540) |
| Third lines | y=640, y=1280 |
| Universal safe zone | (60,108)→(940,1560) |
| Layout A face/screen | (0,0,1080,576) / (0,576,1080,1344) |
| Layout B face/screen | (0,0,1080,768) / (0,768,1080,1152) |
| Layout C PIP circle/rect | (24,140,240,240) / (24,140,280,350) |
| PIP bounds | max Y=1440, max X=900 |
| Min text | 40px |
| Dark bg | #0D0D0D |
| Caption max width | 860px (bold), 960px (subtitle bar) |

| Fit Mode | Behavior | Dead Space | Content Loss |
|---|---|---|---|
| `cover` | Fill, crop overflow | No | Yes (edges) |
| `contain` | Fit, letterbox | Yes (fill needed) | No |
| `stretch` | **NEVER USE** | -- | Distorted |

| Color Use | Value |
|---|---|
| Dark fill | #0D0D0D |
| Caption text | #FFFFFF |
| Caption stroke | #000000 3px |
| Subtitle bg (YouTube) | #000000 @60% |
| Subtitle bg (LinkedIn) | #1A1A1A @80% |
| Word highlight | #FFD700 or #00E5FF |
| PIP border | #FFFFFF 3px |

### Platform Quick Stats

| Platform | Optimal Length | Hook Window | Completion Target | Engagement Rate |
|---|---|---|---|---|
| TikTok | 15-35s | 1-3s | 70%+ | 3.70% |
| Instagram | 60-90s | 2-3s | 60%+ at 3s | 1.23% |
| YouTube Shorts | 30-60s | 2s | 80-90% | -- |
| YouTube Standard | 7-15min | 8s | 65%+ at 30s | -- |
| Facebook | 15-60s | 2-3s | completion rate | 0.15% |
| LinkedIn | <30s or <2min | 3-5s | 200% better <30s | 6.5% |
