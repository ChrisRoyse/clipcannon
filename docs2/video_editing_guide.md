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

### Viral Content Structure: Hook-Body-CTA

93% of viral content follows this framework:

```
HOOK (0-3s)     Stop the scroll. Pattern interrupt. Curiosity gap.
                "You're doing X wrong" / shocking stat / bold visual

SETUP (3-8s)    Establish tension or context. Validate the hook.
                Show WHY viewer should care.

BODY (8s-end-5s) Deliver on the promise. Pattern interrupts every 5-8s.
                 Dynamic layout changes. Zoom to emphasize.

CTA (last 3-5s) Specific action. "Send this to..." outperforms "like and subscribe"
```

**Looping structure** (advanced): Design the ending to visually or narratively lead back into the first frame. Looping Shorts push past 100% retention.

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

Use `get_segment_detail` or query `text_change_events` to find where on-screen content changes. These are natural cut points:

```
get_segment_detail(project_id, start_ms=0, end_ms=300000)
→ on_screen_text[].change_from_previous = true  ← these are your scene breaks
```

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

### OCR-Driven Viral Editing Workflow

```
1. ingest (runs OCR + scene_analysis automatically)
2. get_scene_map → for each scene:
   - visible_text tells you what's on screen
   - layout_recommendation tells you best layout
   - canvas_regions gives ready-to-use coordinates
3. get_editing_context → highlights + silence gaps for cut decisions
4. For each scene with visible_text:
   - If text is small → add zoom_in motion effect on that segment
   - If slide_transition → start new segment, consider title_card overlay
   - If text references a key point → add bold_centered caption emphasis
5. create_edit using scene_map canvas_regions directly
6. preview_layout at OCR-identified key frames → verify text readability
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

### TikTok

| Metric | Value |
|---|---|
| Optimal length | 15-35s (sweet spot for completion rate) |
| Hook window | 1-3s (84% of viral TikToks use psychological triggers in first 3s) |
| Completion threshold | 70%+ for viral promotion, 85%+ for explosive reach |
| Visual change cadence | Every 3-5s |
| Music | Energetic 120+ BPM; trending audio gets 3x more reach |
| Avg daily watch time | 95 min globally, 52 min US |
| Engagement rate | 3.70% (up 49% YoY) |
| Algorithm weight | Watch time (~50%), shares (6/10), saves, comments, likes (weakest) |

**Strategy:** Bold hook (Layout D, face close-up), aggressive pacing (3-5s layout changes), trending audio, bold captions for sound-off, CTA in last 3s. A 15-second video watched fully beats a 60-second video watched halfway.

**Auto-trim tuning:** Aggressive -- `pause_threshold_ms=500, merge_gap_ms=200, min_segment_ms=300`

**Color:** `contrast=1.2, saturation=1.15` -- saturated, punchy colors perform best

### Instagram Reels

| Metric | Value |
|---|---|
| Optimal length | 60-90s for max engagement and views |
| Hook window | 2-3s (up to 50% drop in first 3s) |
| 3s hold rate | 60%+ = 5-10x more total reach |
| Visual change cadence | Every 4-6s |
| Music | Trending audio preferred |
| Engagement rate | 1.23% (Reels specifically) |
| #1 algorithm signal | Watch time; DM sends/reach is strongest for NEW audience |

**Strategy:** More polished than TikTok. Cover frame matters. 10-second Reel with 80% retention beats a 60-second Reel at 30%. Design for DM shareability ("send this to your [friend who...]").

**Color:** `contrast=1.1, saturation=1.1` -- slightly elevated, polished look

### YouTube Shorts

| Metric | Value |
|---|---|
| Optimal length | 30-60s (highest view counts) |
| Hook window | 2s |
| Top performer retention | 80-90% completion |
| "Skippable" threshold | Below 50% completion |
| Visual change cadence | Every 4-7s |
| Music | Optional; educational content often better without |
| Key metric | Every loop counts as a new view |

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

## 20. Complete Workflow

```
1. project_create → ingest → wait "ready"
2. get_scene_map (primary intelligence) + get_editing_context + get_vud_summary
3. Analyze OCR data: identify slide transitions, text-heavy scenes, zoom targets
4. auto_trim → clean segments (platform-specific aggressiveness)
5. create_edit:
   - Use scene_map canvas_regions for coordinates
   - Use OCR slide transitions as segment boundaries
   - Hook = first 3s, Layout D, face close-up
   - CTA = last 3-5s, Layout D
   - Dynamic layout switching every 5-8s
6. color_adjust (platform-specific grade)
7. add_motion (zoom on key moments, OCR text regions)
8. add_overlay (title cards from OCR titles, stat overlays, lower third, CTA)
9. audio_cleanup + generate_sfx (whoosh on transitions, impact on text pops)
10. preview_clip + preview_layout at hook, CTA, and key transitions
11. generate_metadata
12. render
13. inspect_render → if issues → modify_edit → re-render
```

---

## 21. Quality Checklist

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
