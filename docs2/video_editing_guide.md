# ClipCannon AI Video Editing Guide

Authoritative reference for the ClipCannon AI video editor. All five supported platforms (TikTok, Instagram Reels, YouTube Shorts, Facebook Reels, LinkedIn) use a vertical 9:16 canvas at **1080 x 1920 px**. All measurements are in pixels on this canvas unless stated otherwise.

---

## 1. Platform Safe Zones

Each platform overlays UI elements on top of the video. The "safe zone" is where important content (faces, key text, screen content) will never be obscured.

### 1.1 TikTok

| Property | Value |
|---|---|
| Safe zone | (60, 108) to (960, 1600) -- 900 x 1492 |
| Right danger zone | x > 960 (120px) -- like/comment/share/music buttons |
| Bottom danger zone | y > 1600 (320px) -- username, caption text, music ticker |
| Top danger zone | y < 108 -- status bar, "Following / For You" tabs |

**Overlay map:** Right column (x 960-1080): Heart (~y820), Comment (~y940), Bookmark (~y1060), Share (~y1180), Music disc (~y1350), each ~48px wide. Bottom-left (x 16-700, y 1600-1860): @username, caption (up to 3 lines), music marquee.

### 1.2 Instagram Reels

| Property | Value |
|---|---|
| Safe zone | (60, 108) to (940, 1560) -- 880 x 1452 |
| Right danger zone | x > 940 (140px) -- like/comment/send/save/music |
| Bottom danger zone | y > 1560 (360px) -- username, caption, audio label, hashtags |
| Top danger zone | y < 108 -- "Reels" header, camera icon |

Username and caption start at ~y=1520 and can wrap 4-5 lines, making the bottom danger zone taller than TikTok (360px vs 320px). Right icons are wider (140px vs 120px).

### 1.3 YouTube Shorts

| Property | Value |
|---|---|
| Safe zone | (60, 108) to (940, 1580) -- 880 x 1472 |
| Right danger zone | x > 940 (140px) -- like/dislike/comment/share/remix |
| Bottom danger zone | y > 1580 (340px) -- channel name, title, subscribe button |
| Top danger zone | y < 108 -- search, camera, notification icons |

Subscribe button at bottom-right (~x 780-1040, y 1620-1680). Video title at bottom-left (x 24-750, y 1600-1700).

### 1.4 Facebook Reels

| Property | Value |
|---|---|
| Safe zone | (60, 100) to (960, 1600) -- 900 x 1500 |
| Right danger zone | x > 960 (120px) -- like/comment/share buttons |
| Bottom danger zone | y > 1600 (320px) -- creator name, caption, music |
| Top danger zone | y < 100 -- status bar |

Closely mirrors TikTok layout. Top bar slightly shorter (100px vs 108px).

### 1.5 LinkedIn

| Property | Value |
|---|---|
| Safe zone | (48, 96) to (984, 1620) -- 936 x 1524 |
| Right danger zone | x > 984 (96px) -- like/comment/repost/send |
| Bottom danger zone | y > 1620 (300px) -- author info, description |
| Top danger zone | y < 96 -- navigation bar |

Smaller icons (96px column). Shorter bottom overlay (300px). Use wider internal margins (48px) for a cleaner, professional look.

### 1.6 Universal Safe Zone (all platforms)

Intersection of all safe zones for cross-platform edits:

| Universal safe zone | **(60, 108) to (940, 1560)** -- 880 x 1452 |
|---|---|

---

## 2. Layout Patterns for Screen Recording + Speaker

Five standard layouts. The AI selects layouts based on content type within each segment.

### 2.1 Layout A: 30/70 Vertical Split (Best for Tutorials)

| Region | X | Y | Width | Height |
|--------|---|---|-------|--------|
| Face | 0 | 0 | 1080 | 576 |
| Screen | 0 | 576 | 1080 | 1344 |

Eye line at y=192. Headroom 30-60px. Tight framing: head + upper shoulders.

**Screen crop:** Content area only (no browser chrome, no OS taskbar). Scale to cover 1080px width; center vertically. Use #0D0D0D fill for vertical dead space.

**When to use:** Speaker explaining something while screen content is visible. Default tutorial layout.

### 2.2 Layout B: 40/60 Split (Balanced)

| Region | X | Y | Width | Height |
|--------|---|---|-------|--------|
| Face | 0 | 0 | 1080 | 768 |
| Screen | 0 | 768 | 1080 | 1152 |

Eye line at y=256. Headroom 40-80px. Wider framing: head + shoulders + upper chest.

**When to use:** Speaker emphasizing a point or building rapport while screen provides context.

### 2.3 Layout C: PIP (Picture-in-Picture)

**Screen region:** Full canvas, 1080 x 1920.

| PIP Style | X | Y | Width | Height | Border | Corner Radius |
|-----------|---|---|-------|--------|--------|---------------|
| Circle | 24 | 140 | 240 | 240 | 3px white | 120 (full circle) |
| Rounded rectangle | 24 | 140 | 280 | 350 | 3px white | 24 |

**PIP placement constraints:**
- Must stay above y=1440 and left of x=900.
- Default: top-left at (24, 140). Alternative: top-right at (816, 140) for circle, (776, 140) for rect -- only if right-side icons are absent.

**When to use:** Screen content is the primary focus. Best for detailed walkthroughs, code demos, UI tours.

### 2.4 Layout D: Full-Screen Face (Hook / CTA)

| Region | X | Y | Width | Height |
|--------|---|---|-------|--------|
| Face | 0 | 0 | 1080 | 1920 |

Eye line at y=640. Headroom 30-60px. Face width 60-80% of canvas (648-864px). For hooks (first 3s): tighter crop, face at 70-80%. For CTAs (last 3-5s): slightly wider, head + shoulders.

**When to use:** First 3 seconds (hook), last 3-5 seconds (CTA), or key emotional/persuasive moments without screen content.

### 2.5 Layout E: Dynamic Switching

Strategy of switching between Layouts A-D based on content changes.

| Content Type | Layout |
|---|---|
| Speaker talking to camera (no screen) | D (full-screen face) |
| Speaker talking while showing screen | A (30/70) or B (40/60) |
| Detailed screen walkthrough, speaker narrating | C (PIP) |
| Zooming into specific UI element or code block | Screen zoom, no face |
| Hook (first 3s) | D |
| CTA (last 3-5s) | D |

**Transition rules:**
- Switch on scene changes or topic shifts.
- Minimum layout duration: 3 seconds. Maximum before change: 8 seconds.
- Use hard cuts (no dissolves or wipes).

---

## 3. Eliminating Dead Space

Dead space signals low production quality. Techniques ranked by visual quality:

| Rank | Technique | Status |
|------|-----------|--------|
| 1 | **Blurred background fill** -- Gaussian blur (r=40-60px) of source frame behind sharp content | Not yet supported |
| 2 | **Cover fit** -- Scale to fill, center-crop. `fit_mode: "cover"`. Loses edge content. | Default when edges are expendable |
| 3 | **Solid dark fill** -- #0D0D0D background. `fit_mode: "contain"`, `background_color: "#0D0D0D"`. | Fallback when edges are critical |
| 4 | **Branded frame template** -- Pre-designed frame with brand assets | Requires template assets; not in default pipeline |
| 5 | **Content stacking** -- Face + screen regions span full 1920px (Layouts A/B) | Default for split layouts |

---

## 4. Face Framing Rules

These rules apply to every layout where the speaker's face is visible. All face crop rules referenced in Layouts A-D (Section 2) are defined here.

### 4.1 Headroom

| Context | Headroom (top of head to top of region) |
|---|---|
| All split/full-screen layouts (A, B, D) | 30-60px (Layout B allows up to 80px) |
| PIP circle | 10-20px |
| PIP rounded rectangle | 15-25px |

### 4.2 Eye Line

Eyes sit on the upper-third line of the face region.

| Layout | Face region height | Eye line Y |
|---|---|---|
| A (30/70) | 576px | 192px |
| B (40/60) | 768px | 256px |
| D (full screen) | 1920px | 640px |
| C (PIP circle) | 240px | 80px |
| C (PIP rect) | 350px | 117px |

### 4.3 Face Width

Face (ear-to-ear or hair edge to hair edge) should occupy 60-80% of the face region width.

| Layout | Face region width | Target face width |
|---|---|---|
| A, B, D | 1080px | 648-864px |
| C (PIP circle) | 240px | 144-192px |
| C (PIP rect) | 280px | 168-224px |

### 4.4 Horizontal Position

Always center the face horizontally (x=540 for full-width regions). Do NOT use rule-of-thirds horizontal placement -- that convention is for landscape framing and looks awkward in vertical format.

### 4.5 Framing Tightness

| Scenario | Framing | What is visible |
|---|---|---|
| Hook (first 3s) | Close-up | Face only, chin to just above forehead |
| Tutorial narration | Medium close-up | Head + upper chest/shoulders |
| CTA (last 3-5s) | Medium close-up | Head + shoulders, slightly wider than narration |
| PIP | Close-up | Face only, minimal neck |

### 4.6 Webcam Source Extraction (Screen Recording Videos)

When the source is a screen recording with an embedded webcam overlay (OBS, Loom, Zoom):

**THE #1 RULE: Capture the ENTIRE webcam image. Do NOT zoom in on the face.**

The human set up their webcam to show exactly what they want viewers to see -- face, mic, setup, background. The AI displays the webcam as-is.

**Source measurement (MUST do before editing):**
1. Use face detection or pixel analysis to find the exact webcam overlay boundary (x, y, width, height)
2. Use those EXACT dimensions as source_x, source_y, source_width, source_height
3. Do NOT crop a smaller region within the webcam

**Aspect ratio handling:**

| Output Region | Approach |
|---|---|
| Top of 30/70 split (1080x576) | `cover` -- 576px height matches ~590px source naturally |
| Top half (1080x1050) | `cover` -- slightly zoomed but still shows full person |
| PIP (240x240) | `cover` -- square-to-square is ideal |
| Full 9:16 (1080x1920) | **Do NOT use.** Place webcam in top portion; use bottom for screen/captions |

**Key rule:** Output region height should be close to source webcam height (500-600px) for natural display.

**Wrong** (zoomed in): `source_width=350, source_height=400` -- loses mic, shoulders, setup.
**Correct** (full webcam): `source_width=560, source_height=590` -- captures entire overlay.

**Duplicate webcam prevention:** When using Layouts A/B/C/D with a separate face region, crop out the webcam overlay from the screen content region. Identify the overlay (typically 120-320px rectangle/circle in one corner) and exclude it.

### 4.7 Preview Tool Workflow

**ALWAYS preview before rendering.** Use `clipcannon_preview_layout` to generate a composited frame in ~300ms instead of a full render (30-60s).

**Workflow:** Decide coordinates -> preview -> check -> adjust -> repeat -> render.

**Example preview call:**
```json
{
  "project_id": "proj_xxx",
  "timestamp_ms": 10000,
  "background_color": "#0a0a0a",
  "regions": [
    {
      "region_id": "speaker",
      "source_x": 2000, "source_y": 850,
      "source_width": 560, "source_height": 590,
      "output_x": 0, "output_y": 0,
      "output_width": 1080, "output_height": 576,
      "z_index": 2, "fit_mode": "cover"
    },
    {
      "region_id": "screen",
      "source_x": 150, "source_y": 200,
      "source_width": 1400, "source_height": 1000,
      "output_x": 0, "output_y": 576,
      "output_width": 1080, "output_height": 1344,
      "z_index": 1, "fit_mode": "contain"
    }
  ]
}
```

**Preview checklist:**
- Webcam showing full person (not zoomed into face)?
- Screen content readable at phone size?
- Title text fully visible?
- No unnecessary black bars?
- Layout matches what speaker is discussing at this timestamp?

**Content-specific crop strategy:**

| Content Type | Recommended Source Crop |
|---|---|
| Website landing page | Crop to content area (exclude margins), use contain |
| Dashboard with stats | Crop stats cards as one region, database list as another |
| File/document list | Crop to just the table area |
| Document viewer | Crop to just the document content |
| Code editor | Crop to just the code, zoom so text is 40px+ |

Use multiple regions to show different parts of the screen separately. Three smaller, readable regions beat one tiny full-screen view.

### 4.8 Visual-Speech Alignment

**The viewer must always SEE what the speaker is TALKING ABOUT.** This is the #1 editorial decision.

| Speaker is saying... | Viewer expects to see... | Layout |
|---|---|---|
| Intro / "I built this thing" | Speaker's face (credibility, hook) | D or 50/50 split |
| "Look at this dashboard" / "check this out" | Dashboard/screen, BIG | C (PIP) or screen-heavy |
| "You can see the 18 file types" | File list, zoomed in so text is readable | Animated zoom into file list |
| "It processes PDFs, Word docs..." | Processing results / file status | Screen content showing results |
| "Go to ocrprovidence.com" | Website landing page | Full-screen website or split with URL |
| Technical explanation (no screen reference) | Speaker face for credibility | A (30/70) split |
| Closing / CTA / "go check it out" | Speaker face (personal connection) | D (full-screen face) |

**Rules:**
1. When the speaker references screen content, that content MUST be the dominant visual.
2. When the speaker makes a personal statement or hook, their face should be dominant.
3. Match content changes to speech changes at the same moment.
4. Zoom into the exact area being discussed so the viewer can read specifics.
5. Use word-level timestamps from WhisperX to time layout switches precisely.

### 4.9 Think Like a Director

Before touching coordinates, answer these questions:
1. **What story am I telling?** Hook, context, demo, proof, CTA.
2. **What does the viewer need to see RIGHT NOW?**
3. **Is the content readable on a phone screen?** If text is too small, zoom in.
4. **Am I matching visuals to speech?**
5. **Would I swipe past this?** The first 2 seconds must grab attention.

**Common mistakes:**
- Showing full-screen face when speaker references screen content
- Showing tiny letterboxed widescreen unreadable on mobile
- Same layout for every segment (no visual variety)
- Dead space with no purpose
- Stretched or distorted images from wrong fit_mode
- Including browser chrome, taskbar, or webcam overlay from source

---

## 5. Screen Content Rules

### 5.1 Mandatory Crops

Always crop out from source screen recordings:

| Element | Typical location | Action |
|---|---|---|
| Browser tab bar | Top 40-80px | Crop |
| Browser bookmarks bar | Below tab bar, 30-40px | Crop |
| Browser address bar | Below tabs, 50-60px | Crop |
| OS taskbar (Windows) | Bottom 48px | Crop |
| OS dock (macOS) | Bottom 60-80px | Crop |
| OS menu bar (macOS) | Top 25-30px | Crop |
| Desktop wallpaper | Behind windows | Crop or cover |

Only the content area of the demonstrated application should be visible.

### 5.2 Text Legibility

| Metric | Minimum value |
|---|---|
| Rendered text height (on 1080px canvas) | 40px |
| Rendered line spacing | 1.3x text height |
| Minimum contrast ratio (WCAG AA) | 4.5:1 |

If source text is smaller than 40px when scaled, apply a zoom-in to the relevant area.

### 5.3 Zoom-In Behavior

| Property | Value |
|---|---|
| Zoom target | Center on active element (cursor, highlighted text, clicked button) |
| Zoom factor | 1.5x-3.0x depending on source text size |
| Animation duration (in and out) | 300-500ms ease-in-out |
| Hold duration | At least 3 seconds, or until speaker moves to next topic |

Use animated zoom (not jump cuts) to guide viewer attention.

---

## 6. Per-Platform Content Strategy

### 6.1 TikTok

| Property | Value |
|---|---|
| Duration | 15-60 seconds |
| Hook window | First 1-3 seconds |
| Pacing | Fast: visual change every 3-5 seconds |
| Music | Energetic, 120+ BPM; algorithm rewards trending audio |
| End screen | CTA in last 3s, face close-up |

Open with a bold/surprising/curiosity-driven hook. Cut to demo immediately. Change something every 3-5s (layout switch, zoom, caption, scene). Use text overlays for sound-off viewers. End with clear CTA.

### 6.2 Instagram Reels

| Property | Value |
|---|---|
| Duration | 15-90 seconds |
| Hook window | First 2-3 seconds |
| Pacing | Moderate-fast: visual change every 4-6 seconds |
| Music | Trending audio clips, curated aesthetic |
| Hashtags | 20-30 in description (not burned in) |

Similar to TikTok but more polished. Audiences appreciate visual consistency (color grading, brand colors). Pacing slightly slower. Cover frame selection matters.

### 6.3 YouTube Shorts

| Property | Value |
|---|---|
| Duration | 30-60 seconds |
| Hook window | First 2 seconds |
| Pacing | Moderate: visual change every 4-7 seconds |
| Music | Optional; less emphasis than TikTok |
| Title | Critical for discovery |

More educational and detailed than TikTok. Title is very important. Subscribe CTA is valuable (Shorts drive channel subscriptions).

### 6.4 Facebook Reels

| Property | Value |
|---|---|
| Duration | 15-60 seconds |
| Hook window | First 2-3 seconds |
| Pacing | Moderate: visual change every 4-6 seconds |
| Music | Optional |
| Autoplay | Muted by default |
| Audience | Slightly older demographic (30-55) |

**Captions are essential** -- muted autoplay means no captions = lost viewers. Less aggressive editing. Educational/informational content performs best.

### 6.5 LinkedIn

| Property | Value |
|---|---|
| Duration | 30-120 seconds |
| Hook window | First 3-5 seconds |
| Pacing | Slow-moderate: visual change every 6-10 seconds |
| Music | None, or very subtle ambient |
| Tone | Professional, authoritative, value-driven |
| Audience | Professionals, decision-makers, B2B |

Professional tone mandatory. Lead with value. Data/metrics/results resonate strongly. Soft CTA ("What do you think?" not "FOLLOW ME").

---

## 7. Caption Styles by Platform

### 7.1 Quick Reference

| Platform | Style | Font Size | Y Position | Weight | Stroke | Background |
|----------|-------|-----------|------------|--------|--------|------------|
| TikTok | bold_centered | 48-52px | y=1440 (75%) | 800 | 3px black | None |
| Instagram | bold_centered | 44-48px | y=1400 (73%) | 800 | 3px black | None |
| YouTube | subtitle_bar | 32-36px | y=1530 (80%) | 600 | None | #000000 @ 60%, 8px pad |
| Facebook | bold_centered | 40-44px | y=1420 (74%) | 700 | 3px black | None |
| LinkedIn | subtitle_bar | 28-32px | y=1570 (82%) | 500 | None | #1A1A1A @ 80%, 10px pad |

### 7.2 Bold Centered Style (TikTok, Instagram, Facebook)

```
font_family: "Inter", "Montserrat", or system sans-serif
font_weight: 700-800
text_align: center
color: #FFFFFF
stroke: 3px #000000
max_width: 860px (110px margin each side)
position_x: 540 (centered)
line_height: 1.3
max_lines: 2
```

**Word-by-word highlight (optional, TikTok preferred):** Highlight current word in #FFD700 gold or #00E5FF cyan for a karaoke effect.

### 7.3 Subtitle Bar Style (YouTube, LinkedIn)

```
font_family: "Inter", "Roboto", or system sans-serif
font_weight: 500-600
text_align: center
color: #FFFFFF
background: #000000 @ 60% (YouTube) or #1A1A1A @ 80% (LinkedIn)
background_padding: 8-10px vertical, 16-20px horizontal
background_corner_radius: 6px
max_width: 960px
position_x: 540 (centered)
line_height: 1.4
max_lines: 2
```

### 7.4 Caption Safe Placement

Captions must not overlap platform UI. All positions in this guide sit safely above danger zones:

| Platform | Caption Y range | Must be above |
|---|---|---|
| TikTok | y=1390-1490 | y=1600 |
| Instagram | y=1350-1450 | y=1560 |
| YouTube | y=1490-1570 | y=1580 |
| Facebook | y=1370-1470 | y=1600 |
| LinkedIn | y=1530-1610 | y=1620 |

---

## 8. Video Structure Templates

Starting frameworks for segment-by-segment structure. Adjust based on content analysis.

### 8.1 TikTok / Instagram Reels (15-60s)

```
TIME        LAYOUT    PURPOSE
0-3s        D         HOOK -- full-screen face, bold opening, stop the scroll
3-8s        A/B       CONTEXT -- split, speaker + screen, what viewer will learn
8-15s       C/A       DEMO -- screen-dominant, zoom-ins on key UI elements
15-25s      E         DETAILS -- dynamic switching, change visual every 3-5s
25-30s      D         CTA -- full-screen face, clear call to action
```

For clips <30s, compress middle sections. Hook (0-3s) and CTA (last 3s) are non-negotiable.

### 8.2 YouTube Shorts (30-60s)

```
TIME        LAYOUT    PURPOSE
0-2s        D         HOOK -- face or bold text, slightly less aggressive
2-10s       A/B       SETUP -- explain what you will show, establish credibility
10-40s      E         WALKTHROUGH -- dynamic switching, PIP for screen, change every 5-7s
40-55s      A/B       KEY TAKEAWAY -- summarize, speaker + key result
55-60s      D         CTA -- face, subscribe mention
```

### 8.3 LinkedIn (30-120s)

```
TIME        LAYOUT    PURPOSE
0-5s        A/B       PROFESSIONAL HOOK -- lead with value, no gimmicks
5-30s       C/A       DEMONSTRATION -- screen-dominant, zoom into data, change every 6-10s
30-60s      B/D       VALUE EXPLANATION -- why this matters, business outcomes
60-90s      C         RESULTS/PROOF -- metrics, dashboards, let numbers speak
90-120s     D/B       CLOSING -- soft CTA, "Thoughts?" / "What has worked for you?"
```

For clips <60s: Hook (0-5s) + Demo (5-40s) + Closing (40-60s).

---

## 9. Source Video Analysis Checklist

Before generating any edit, perform these analysis steps.

### 9.1 Face Detection

- Detect face bounding box per scene (x, y, width, height)
- Calculate face center coordinates for centering in crop
- Measure face width relative to frame for crop tightness
- Detect eye positions for eye-line placement
- Check for multiple faces (flag for review; default to primary speaker)
- Track face movement across frames

### 9.2 Screen Content Analysis

- Identify screen recording boundaries in source
- Detect and map browser chrome, OS taskbar/dock, webcam overlay regions to exclude
- Calculate content area bounds after all exclusions
- Measure minimum text size (determine if zoom-ins needed)
- Track cursor position over time for zoom-in targeting

### 9.3 Timeline Mapping

- Scene detection (visual change points)
- Classify content type per scene: face-only, screen-only, face+screen, transition
- Map transcript words to timestamps
- Identify hook moments (first sentence, surprising statements, questions)
- Identify key teaching/demo moments
- Identify CTA moments (closing statements)
- Check for engagement highlights from analytics or AI scoring

### 9.4 Layout Planning

```
For each segment:
  IF face_only:           layout = D
  ELIF screen_only:       layout = C (PIP) if face_available else screen_zoom
  ELIF face_and_screen:
    IF face_is_primary:   layout = B (40/60)
    ELSE:                 layout = A (30/70)

  IF first segment:       layout = D (hook)
  IF last segment:        layout = D (CTA)
```

---

## 10. Quality Checklist

Verify every item before rendering. Failed checks must be corrected.

### 10.1 Geometry and Framing

- [ ] No stretching or distortion (use `cover` or `contain`, never `stretch`)
- [ ] Face centered horizontally (within 20px of center)
- [ ] Eyes on upper-third line (within 30px)
- [ ] Headroom 30-60px
- [ ] Face width 60-80% of region width

### 10.2 Content Integrity

- [ ] No duplicate webcam (source overlay cropped out when using separate face region)
- [ ] No browser chrome visible (tab bar, bookmarks, address bar)
- [ ] No OS taskbar/dock visible
- [ ] All text readable (minimum 40px rendered height)

### 10.3 Platform Compliance

- [ ] Captions above platform bottom danger zone
- [ ] Critical content within safe zone for target platform
- [ ] Right-side margin clear of critical content

### 10.4 Dead Space

- [ ] No unintentional black bars or empty regions
- [ ] No unfilled gaps between regions in split layouts
- [ ] Background fill is #0D0D0D (not pure black) when dark fill is used

### 10.5 Pacing and Structure

- [ ] Hook in first 3 seconds (Layout D or bold text overlay)
- [ ] CTA in last 3-5 seconds (Layout D)
- [ ] Visual change every 3-8 seconds (platform dependent)
- [ ] No single layout held >8 seconds without a visual change

### 10.6 Audio and Captions

- [ ] Captions present for all spoken content
- [ ] Caption style matches target platform (bold_centered vs subtitle_bar)
- [ ] Caption timing accurate (within 100ms of speech)
- [ ] No caption line exceeds 2 lines at specified font size
- [ ] Caption text fits within max_width (860px bold, 960px subtitle bar)

---

## Appendix A: Pixel Reference Quick Sheet

| Measurement | Value |
|---|---|
| Canvas | 1080 x 1920, center at (540, 960) |
| Upper/lower third lines | y=640, y=1280 |
| Universal safe zone | (60, 108) to (940, 1560) |
| Layout A: face / screen | (0,0,1080,576) / (0,576,1080,1344) |
| Layout B: face / screen | (0,0,1080,768) / (0,768,1080,1152) |
| Layout C: PIP circle / rect | (24,140,240,240) / (24,140,280,350) |
| PIP bounds | max Y=1440, max X=900 |
| Min text height | 40px |
| Dark background | #0D0D0D |
| Caption max width | 860px (bold), 960px (subtitle bar) |
| Face width | 60-80% of region width |
| Headroom | 30-60px |

## Appendix B: Fit Mode Reference

| Mode | Behavior | Dead space? | Content loss? |
|---|---|---|---|
| `cover` | Scale to fill, crop overflow | No | Yes (edges) |
| `contain` | Scale to fit, letterbox remainder | Yes (needs fill) | No |
| `stretch` | Scale axes independently | No | No, but distorted -- **NEVER USE** |

## Appendix C: Color Reference

| Usage | Color |
|---|---|
| Dark background fill | #0D0D0D |
| Caption text | #FFFFFF |
| Caption stroke (bold style) | #000000, 3px |
| Subtitle bar bg (YouTube) | #000000 @ 60% |
| Subtitle bar bg (LinkedIn) | #1A1A1A @ 80% |
| Word highlight (TikTok) | #FFD700 or #00E5FF |
| PIP border | #FFFFFF, 3px solid |
