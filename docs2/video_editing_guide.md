# ClipCannon AI Video Editing Guide

This is the authoritative reference document for the ClipCannon AI video editor. Every clip
generated for any of the five supported platforms (TikTok, Instagram Reels, YouTube Shorts,
Facebook Reels, LinkedIn) must conform to the specifications below. All measurements are in
pixels on a 1080x1920 canvas unless stated otherwise.

---

## 1. Platform Safe Zones

All five platforms use a vertical 9:16 canvas at **1080 x 1920 px**. Each platform overlays
its own UI elements (buttons, captions, profile info) on top of the video. The "safe zone" is
the rectangle where important content (faces, key text, screen content) will never be
obscured.

### 1.1 TikTok

| Property | Value |
|---|---|
| Canvas | 1080 x 1920 |
| Safe zone origin | (60, 108) |
| Safe zone size | 900 x 1492 |
| Safe zone end | (960, 1600) |
| Right danger zone | x > 960 (rightmost 120px) -- like/comment/share/music buttons |
| Bottom danger zone | y > 1600 (bottom 320px) -- username, caption text, music ticker |
| Top danger zone | y < 108 (top 108px) -- status bar, "Following / For You" tabs |

**Overlay map (approximate):**
- **Right column (x 960-1080):** Heart (y ~820), Comment (y ~940), Bookmark (y ~1060), Share (y ~1180), Music disc (y ~1350). Each icon ~48px wide.
- **Bottom-left (x 16-700, y 1600-1860):** @username, caption text (up to 3 lines), music name marquee.
- **Top bar (y 0-108):** Status bar icons, "Following | For You" toggle.

### 1.2 Instagram Reels

| Property | Value |
|---|---|
| Canvas | 1080 x 1920 |
| Safe zone origin | (60, 108) |
| Safe zone size | 880 x 1452 |
| Safe zone end | (940, 1560) |
| Right danger zone | x > 940 (rightmost 140px) -- like/comment/send/save/music |
| Bottom danger zone | y > 1560 (bottom 360px) -- username, caption, audio label, hashtags |
| Top danger zone | y < 108 (top 108px) -- "Reels" header, camera icon |

**Key difference from TikTok:** Instagram shows the username and caption at the bottom-left
starting around y=1520, and captions can wrap to 4-5 lines. The bottom danger zone is
therefore taller (360px vs 320px). The right-side icons are also slightly wider (140px
column vs 120px).

### 1.3 YouTube Shorts

| Property | Value |
|---|---|
| Canvas | 1080 x 1920 |
| Safe zone origin | (60, 108) |
| Safe zone size | 880 x 1472 |
| Safe zone end | (940, 1580) |
| Right danger zone | x > 940 (rightmost 140px) -- like/dislike/comment/share/remix |
| Bottom danger zone | y > 1580 (bottom 340px) -- channel name, title, subscribe button |
| Top danger zone | y < 108 (top 108px) -- search, camera, notification icons |

**Key difference:** The Subscribe button appears at the bottom-right (approximately
x 780-1040, y 1620-1680). The video title sits at the bottom-left (x 24-750, y 1600-1700).
Keep critical content above y=1580 and left of x=940.

### 1.4 Facebook Reels

| Property | Value |
|---|---|
| Canvas | 1080 x 1920 |
| Safe zone origin | (60, 100) |
| Safe zone size | 900 x 1500 |
| Safe zone end | (960, 1600) |
| Right danger zone | x > 960 (rightmost 120px) -- like/comment/share buttons |
| Bottom danger zone | y > 1600 (bottom 320px) -- creator name, caption, music |
| Top danger zone | y < 100 (top 100px) -- status bar |

Facebook Reels closely mirrors TikTok in layout. The icon column on the right is the same
width (120px). The bottom overlay is similar (320px). The top bar is slightly shorter (100px
vs 108px).

### 1.5 LinkedIn

| Property | Value |
|---|---|
| Canvas | 1080 x 1920 |
| Safe zone origin | (48, 96) |
| Safe zone size | 936 x 1524 |
| Safe zone end | (984, 1620) |
| Right danger zone | x > 984 (rightmost 96px) -- like/comment/repost/send |
| Bottom danger zone | y > 1620 (bottom 300px) -- author info, description |
| Top danger zone | y < 96 (top 96px) -- navigation bar |

**Key difference:** LinkedIn uses smaller, more understated icons on the right (96px column
vs 120-140px). The bottom overlay is shorter (300px) because LinkedIn shows less metadata
inline. However, the audience is professional, so content should feel more restrained and
polished. Use wider internal margins (48px instead of 60px) to give a cleaner look.

### 1.6 Universal Safe Zone (all platforms)

When generating a single edit that must work across all five platforms, use the intersection
of all safe zones:

| Property | Value |
|---|---|
| Universal safe origin | (60, 108) |
| Universal safe size | 880 x 1452 |
| Universal safe end | (940, 1560) |

This is the most conservative rectangle. All critical content (faces, key text, screen
regions) must fit within **(60, 108) to (940, 1560)** to guarantee visibility on every
platform.

---

## 2. Layout Patterns for Screen Recording + Speaker

These are the five standard layouts. Each edit is composed of segments, and each segment uses
one of these layouts. The AI selects layouts based on content type within each segment.

### 2.1 Layout A: 30/70 Vertical Split (Best for Tutorials)

```
+------------------------+  y=0
|                        |
|   FACE (1080 x 576)   |  y=0 to y=576
|   Eyes at y=192        |
|   Headroom: 30-60px    |
+------------------------+  y=576
|                        |
|                        |
|  SCREEN (1080 x 1344)  |  y=576 to y=1920
|                        |
|                        |
|                        |
+------------------------+  y=1920
```

| Region | X | Y | Width | Height |
|--------|---|---|-------|--------|
| Face | 0 | 0 | 1080 | 576 |
| Screen | 0 | 576 | 1080 | 1344 |

**Face crop rules:**
- Tight framing: head + upper shoulders only.
- Eyes positioned at y=192 (upper third of the face region).
- Headroom (top of head to top of frame): 30-60px.
- Face centered horizontally at x=540.
- Face occupies 60-80% of the 1080px width (648-864px).

**Screen crop rules:**
- Crop source to content area only (no browser chrome, no OS taskbar).
- Scale to cover 1080px width; center vertically within the 1344px region.
- If the screen content aspect ratio leaves vertical dead space, use a solid #0D0D0D
  background fill behind it.

**When to use:** The speaker is explaining something while screen content is visible.
This is the default tutorial layout.

### 2.2 Layout B: 40/60 Split (Balanced)

```
+------------------------+  y=0
|                        |
|   FACE (1080 x 768)   |  y=0 to y=768
|   Eyes at y=256        |
|                        |
+------------------------+  y=768
|                        |
|  SCREEN (1080 x 1152)  |  y=768 to y=1920
|                        |
|                        |
+------------------------+  y=1920
```

| Region | X | Y | Width | Height |
|--------|---|---|-------|--------|
| Face | 0 | 0 | 1080 | 768 |
| Screen | 0 | 768 | 1080 | 1152 |

**Face crop rules:**
- Same as Layout A but with more visible torso.
- Eyes at y=256 (upper third of 768px region).
- Headroom: 40-80px.
- Slightly wider framing: head + shoulders + upper chest.

**When to use:** The speaker is emphasizing a point or building rapport while screen content
provides supporting context. Good for "here is what I mean" segments.

### 2.3 Layout C: PIP (Picture-in-Picture)

```
+------------------------+  y=0
|  +------+              |
|  | FACE |              |  PIP at (24, 140), 240x240 circle
|  +------+              |  or 280x350 rounded rect
|                        |
|  SCREEN (full 1080x1920)|
|                        |
|                        |
|                        |
|                        |
+------------------------+  y=1920
```

**Screen region:** Full canvas, 1080 x 1920.

**PIP options:**

| Style | X | Y | Width | Height | Border | Corner Radius |
|-------|---|---|-------|--------|--------|---------------|
| Circle | 24 | 140 | 240 | 240 | 3px white | 120 (full circle) |
| Rounded rectangle | 24 | 140 | 280 | 350 | 3px white | 24 |

**PIP placement constraints:**
- Must stay above y=1440 (keep above bottom danger zone + margin).
- Must stay left of x=900 (keep away from right-side icon column).
- Default position: top-left at (24, 140), safely below the top danger zone.
- Alternative positions: top-right at (816, 140) for circle, (776, 140) for rounded rect.
  Only use top-right if right-side platform icons are not present (rare).

**When to use:** Screen content is the primary focus. The speaker's face provides presence
but is not the main attraction. Best for detailed walkthroughs, code demos, and UI tours.

### 2.4 Layout D: Full-Screen Face (Hook / CTA)

```
+------------------------+  y=0
|                        |
|                        |
|                        |
|        FACE            |  Full 1080 x 1920
|    (tight crop)        |
|   Face = 60-80% width  |
|   Eyes at y=640        |
|                        |
|                        |
+------------------------+  y=1920
```

| Region | X | Y | Width | Height |
|--------|---|---|-------|--------|
| Face | 0 | 0 | 1080 | 1920 |

**Face crop rules:**
- Face occupies 60-80% of frame width (648-864px of face width within the 1080px canvas).
- Eyes on the upper-third line of the full canvas: y=640.
- Minimal headroom: 30-60px from top of head to top of frame.
- For hooks (first 3 seconds): crop even tighter, face at 70-80% width, intense and direct.
- For CTAs (last 3-5 seconds): slightly wider framing, head + shoulders, inviting and open.
- Center face horizontally at x=540.

**When to use:**
- **First 3 seconds of any clip** (the hook). The viewer must see a face immediately.
- **Last 3-5 seconds** (the CTA). Return to face for the closing statement.
- Anytime the speaker is making a key emotional or persuasive point without screen content.

### 2.5 Layout E: Dynamic Switching

This is not a single layout but a strategy of switching between Layouts A-D within a single
clip based on content changes.

**Switching rules:**

| Content Type | Layout |
|---|---|
| Speaker talking directly to camera (no screen content) | D (full-screen face) |
| Speaker talking while showing screen | A (30/70) or B (40/60) |
| Detailed screen walkthrough, speaker narrating | C (PIP) |
| Zooming into specific UI element or code block | Screen zoom, no face |
| Hook (first 3 seconds) | D (full-screen face) |
| CTA (last 3-5 seconds) | D (full-screen face) |

**Transition timing:**
- Switch layouts on scene changes or topic shifts (use scene detection data).
- Minimum duration for any layout: 3 seconds (avoid jarring rapid switches).
- Maximum duration before a layout change: 8 seconds (maintain visual variety).
- Use hard cuts between layouts (no dissolves or wipes -- those look dated on short-form).

---

## 3. Eliminating Dead Space

Dead space (black bars, empty regions, unfilled areas) signals low production quality. The
five techniques below are ranked by visual quality.

### Rank 1: Blurred Background Fill (Most Professional)

Take the source frame, apply a heavy Gaussian blur (radius 40-60px), scale it to cover the
full 1080x1920 canvas, and layer the sharp content on top. This fills all dead space with
contextually relevant color and texture.

**Status:** Not currently supported in ClipCannon rendering pipeline.

### Rank 2: Zoom + Crop to Fill (Cover Fit Mode)

Scale the source content until it covers the target region entirely, then center-crop. This
eliminates all dead space but sacrifices edge content.

**ClipCannon implementation:** Use `fit_mode: "cover"` in the edit spec. The renderer scales
the source so the shorter dimension matches the target, then crops the overflow.

**Trade-off:** Content at the edges of the source frame will be lost. Ensure the important
content (face, active UI area) is centered in the source before applying cover fit.

### Rank 3: Solid Dark Background (#0D0D0D)

Fill the target region with near-black (#0D0D0D, not pure #000000) and center the content
within it. The slight off-black avoids the harsh look of pure black and reduces banding on
mobile screens.

**ClipCannon implementation:** Use `fit_mode: "contain"` with `background_color: "#0D0D0D"`.

### Rank 4: Branded Frame Template

Pre-designed frame with brand colors, logo, and decorative elements. Content is placed within
a designated area of the frame.

**Status:** Requires pre-built template assets. Not currently in the default pipeline.

### Rank 5: Content Stacking

Fill the entire canvas by stacking multiple content elements: face region at the top, screen
region below, text/captions in remaining gaps. This is what Layouts A and B achieve.

**ClipCannon implementation:** This is the default approach when using split layouts. No dead
space exists because the face and screen regions together span the full 1920px height.

### ClipCannon Default Strategy

Use **Rank 2 (cover fit)** whenever the source content can tolerate edge cropping. Fall back
to **Rank 3 (dark background)** when edge content is critical and cannot be cropped. Use
**Rank 5 (content stacking)** via split layouts whenever both face and screen are available.

---

## 4. Face Framing Rules

These rules apply to every layout where the speaker's face is visible.

### 4.1 Headroom

| Context | Headroom (top of head to top of face region) |
|---|---|
| Vertical video (all layouts) | 30-60px |
| Full-screen face (Layout D) | 30-60px |
| PIP circle | 10-20px |
| PIP rounded rectangle | 15-25px |

Excessive headroom wastes space and makes the speaker look small. Vertical video demands
tight framing.

### 4.2 Eye Line

The speaker's eyes should sit on the upper-third line of the face region.

| Layout | Face region height | Eye line Y (within face region) |
|---|---|---|
| A (30/70) | 576px | 192px |
| B (40/60) | 768px | 256px |
| D (full screen) | 1920px | 640px |
| C (PIP circle 240px) | 240px | 80px |
| C (PIP rect 350px) | 350px | 117px |

### 4.3 Face Width

The face (measured from ear to ear, or outer edge of hair to outer edge of hair) should
occupy 60-80% of the face region width.

| Layout | Face region width | Target face width |
|---|---|---|
| A, B, D | 1080px | 648-864px |
| C (PIP circle) | 240px | 144-192px |
| C (PIP rect) | 280px | 168-224px |

### 4.4 Horizontal Position

- **Always center the face horizontally** in its region. Vertical short-form video is viewed
  on phones held in portrait; the center of the frame is where attention naturally falls.
- Do NOT use rule-of-thirds horizontal placement. That convention is for landscape/cinematic
  framing and looks awkward in vertical format.
- Face center X should be at the midpoint of the face region width (x=540 for full-width
  regions).

### 4.5 Framing Tightness

| Scenario | Framing | What is visible |
|---|---|---|
| Hook (first 3s) | Close-up | Face only, chin to just above forehead |
| Tutorial narration | Medium close-up | Head + upper chest/shoulders |
| CTA (last 3-5s) | Medium close-up | Head + shoulders, slightly wider than narration |
| PIP | Close-up | Face only, minimal neck |

### 4.6 Webcam Source Extraction (Screen Recording Videos)

When the source video is a screen recording with an embedded webcam overlay (e.g., OBS,
Loom, Zoom), special rules apply:

**Source webcam measurement (MUST do before editing):**
1. Use face detection or pixel analysis to find the exact webcam region (x, y, width, height)
2. Find the face centroid within the webcam region
3. Note: the face is often NOT centered in the webcam frame -- measure, don't assume

**Aspect ratio problem:**
The webcam overlay is typically near-square (e.g., 560x590px). A 9:16 output is very tall
and narrow. Using `cover` fit mode on a square source to fill a 9:16 region causes extreme
zoom-in because it scales to match the taller dimension, cropping the width severely.

**Rules for webcam-to-vertical conversion:**

| Output Region | Recommended Approach |
|---|---|
| Full-screen face (1080x1920) | **Do NOT use.** A square webcam cannot fill 9:16 without extreme zoom. Use face in top 50-60% with dark/content background below. |
| Top region of split (1080x576) | **Use `cover` mode.** The 576px height is close to the ~590px source height, so minimal zoom. |
| PIP circle/square (240x240) | **Use `cover` mode.** Square-to-square works perfectly. |
| Medium region (1080x1000) | **Use `cover` mode.** Acceptable zoom, shows face + mic + upper body. |

**The key rule:** Never try to fill the full 1920px height with a square webcam source.
Instead, place the webcam in a region whose height is close to the source webcam height
(500-600px), and fill the remaining canvas with screen content, dark background, or captions.

**Face centering compensation:**
If the speaker is positioned off-center in the webcam frame (e.g., face centroid at x=240
in a 560px wide webcam), adjust the source crop origin to center on the face:
- Face center X in source = webcam_x + face_centroid_x
- Source crop X = face_center_x - (desired_crop_width / 2)
- Clamp to webcam bounds

### 4.7 Visual-Speech Alignment (Most Important Rule)

**The viewer must always SEE what the speaker is TALKING ABOUT.**

This is the #1 editorial decision the AI must make. The AI has the transcript
(what's being said) and the frames (what's on screen). For every segment, the
AI must ask: "What does the viewer expect to see right now based on what
they're hearing?"

**Decision matrix:**

| Speaker is saying... | Viewer expects to see... | Layout to use |
|---|---|---|
| "I built this thing" / intro statement | The speaker's face (credibility, hook) | Full-screen face or 50/50 split |
| "Look at this dashboard" / "check this out" | The dashboard/screen content, BIG | Screen-dominant (PIP or 70/30 screen-heavy) |
| "You can see the 18 file types" | The file list, zoomed in so text is readable | Animated zoom into the file list area |
| "It processes PDFs, Word docs..." | The processing results / file status | Screen content showing those results |
| "Go to ocrprovidence.com" | The website landing page | Full-screen website or split with URL visible |
| Technical explanation (no screen reference) | Speaker face for credibility | 30/70 split (face top, screen bottom for context) |
| Closing / CTA / "go check it out" | Speaker face (personal connection) | Full-screen face or face-dominant split |

**Rules:**

1. **When the speaker references screen content, the screen content MUST be
   the dominant visual.** Don't show a full-screen face when the speaker says
   "look at this" -- the viewer is frustrated because they can't see "this."

2. **When the speaker is making a personal statement or hook, their face
   should be dominant.** Don't show a full-screen dashboard when the speaker
   says "I built something incredible" -- the viewer needs the emotional
   connection of seeing the speaker.

3. **Match content changes to speech changes.** When the speaker transitions
   from talking about the website to talking about the dashboard, the visual
   layout should change at the same moment.

4. **Zoom into what matters.** When the speaker says "you can see the stats --
   154 MCP tools, 100% local", the AI should zoom into that exact area of the
   screen so the viewer can read those numbers.

5. **Use the transcript timestamps to time layout switches.** The AI knows
   EXACTLY when the speaker says each word (word-level timestamps from
   WhisperX). Layout changes should align with the start of the relevant
   speech, not happen randomly.

**How to implement:**
- Read the transcript for each segment
- Identify what the speaker is referencing (screen content vs. personal statement)
- Choose the layout that shows what the viewer needs to see
- Time the cut to when the speaker starts talking about the new topic
- For screen references: zoom into the specific area being discussed

---

### 4.8 Think Like a Director, Not an Engineer

**You are a video editor, not a pixel coordinate tweaker.** Before touching any
numbers, answer these questions:

1. **What story am I telling?** -- What is the narrative arc of this clip? Hook,
   context, demo, proof, CTA.
2. **What does the VIEWER need to see RIGHT NOW?** -- Not what's technically in
   the source frame. What information does the viewer need at this exact second
   to follow along?
3. **Is the content READABLE on a phone screen?** -- If text in the screen
   content is too small to read at phone size, ZOOM IN to just the relevant
   portion. Don't show the whole screen with tiny unreadable text.
4. **Am I matching visuals to speech?** -- When the speaker says "look at this
   dashboard", the dashboard should be filling the screen. Not your face.
5. **Would I swipe past this?** -- If the first 2 seconds don't grab attention,
   no one sees the rest. The hook must be compelling.

**Common mistakes to avoid:**
- Showing full-screen face when the speaker is referencing screen content
- Showing tiny letterboxed widescreen that's unreadable on mobile
- Using the same layout for every segment (no visual variety)
- Dead space / black bars with no purpose
- Stretched or distorted images from wrong fit_mode
- Including browser chrome, taskbar, or webcam overlay from the source

**The right mental model:**
For each segment, imagine you're the viewer scrolling TikTok. You stop on this
video. What would make you keep watching? The answer is: seeing something
interesting that you can actually read/understand, hearing something that makes
you curious, and visual variety that keeps your attention.

**Content cropping strategy:**
Don't show the whole 1920px-wide screen. Instead:
- Identify the SPECIFIC UI element being discussed in the transcript
- Crop to JUST that element (e.g., just the stats cards, just the file table)
- Scale that crop to fill the 1080px output width
- Use `cover` for narrow content crops, `contain` for wide full-screen views

---

## 5. Screen Content Rules

### 5.1 Mandatory Crops

The following elements from the source screen recording must ALWAYS be cropped out:

| Element | Typical location in source | Action |
|---|---|---|
| Browser tab bar | Top 40-80px | Crop |
| Browser bookmarks bar | Below tab bar, 30-40px | Crop |
| Browser address bar | Below tabs, 50-60px | Crop |
| OS taskbar (Windows) | Bottom 48px | Crop |
| OS dock (macOS) | Bottom 60-80px | Crop |
| OS menu bar (macOS) | Top 25-30px | Crop |
| Desktop wallpaper | Behind windows | Crop or cover |

**Rule:** Only the content area of the application being demonstrated should be visible.
Calculate the content area by detecting the innermost content boundaries of the active window
and cropping to those bounds.

### 5.2 Text Legibility

On a 1080px-wide canvas viewed on a 6-inch phone screen, text must be large enough to read
without squinting.

| Metric | Minimum value |
|---|---|
| Rendered text height (on 1080px canvas) | 40px |
| Rendered line spacing | 1.3x text height |
| Minimum contrast ratio (WCAG AA) | 4.5:1 |

If the source screen recording contains text smaller than 40px when scaled to fit the screen
region, the AI must apply a **zoom-in** to the relevant area.

### 5.3 Zoom-In Behavior

When zooming into a specific area of the screen content:

| Property | Value |
|---|---|
| Zoom target | Center on the active element (cursor position, highlighted text, clicked button) |
| Zoom factor | 1.5x-3.0x depending on source text size |
| Zoom animation duration | 300-500ms ease-in-out |
| Hold duration | At least 3 seconds, or until the speaker moves to the next topic |
| Zoom-out animation duration | 300-500ms ease-in-out |

Use animated zoom (not jump cuts) to guide viewer attention smoothly.

### 5.4 Webcam Overlay in Screen Recording

Many source recordings include a webcam overlay (PIP) baked into the screen capture. This
creates a problem: if we also add our own face region (Layouts A/B/C), the face appears
twice.

**Rule:** When a webcam overlay is detected in the source screen recording, crop it out.
Identify the overlay region (typically a rectangle or circle in one corner of the screen,
120-320px wide) and exclude it from the screen content crop. If the overlay is in the
bottom-right, crop the screen content to exclude that corner.

---

## 6. Per-Platform Content Strategy

### 6.1 TikTok

| Property | Value |
|---|---|
| Duration sweet spot | 15-60 seconds |
| Hook window | First 1-3 seconds |
| Pacing | Fast: visual change every 3-5 seconds |
| Caption style | Bold, centered, impossible to ignore |
| Caption size | 48-52px |
| Caption position | Centered at y ~ 75% of canvas (y=1440) |
| Caption color | White with 3px black stroke (outline) |
| Music | Energetic, 120+ BPM; TikTok algorithm rewards trending audio |
| End screen | CTA in last 3 seconds, face close-up |
| Aspect ratio | 9:16 (1080x1920) strictly |

**Content rules:**
- Open with a bold, surprising, or curiosity-driven statement (hook).
- Cut to the demonstration immediately after the hook -- no long intros.
- Every 3-5 seconds, change something: layout switch, zoom, new caption, new scene.
- Use text overlays to reinforce key points (viewers often watch without sound initially).
- End with a clear, concise CTA: "follow for more," "link in bio," "try it yourself."

### 6.2 Instagram Reels

| Property | Value |
|---|---|
| Duration sweet spot | 15-90 seconds |
| Hook window | First 2-3 seconds |
| Pacing | Moderate-fast: visual change every 4-6 seconds |
| Caption style | Bold, centered |
| Caption size | 44-48px |
| Caption position | Centered at y ~ 73% of canvas (y=1400) |
| Caption color | White with 3px black stroke |
| Music | Trending audio clips, curated aesthetic |
| Hashtags | 20-30 relevant hashtags in the post description (not burned in) |
| Aspect ratio | 9:16 (1080x1920) |

**Content rules:**
- Similar to TikTok but with a slightly more polished, curated aesthetic.
- Instagram audiences appreciate visual consistency (color grading, brand colors).
- Pacing can be slightly slower than TikTok; viewers are more patient.
- Hashtags are critical for discovery but go in the description, not on screen.
- Cover frame matters: Instagram lets users choose a cover image for the Reel.

### 6.3 YouTube Shorts

| Property | Value |
|---|---|
| Duration sweet spot | 30-60 seconds |
| Hook window | First 2 seconds |
| Pacing | Moderate: visual change every 4-7 seconds |
| Caption style | Subtitle bar (bottom of screen) |
| Caption size | 32-36px |
| Caption position | Bottom bar, y=1500-1560 |
| Caption color | White on semi-transparent black bar |
| Music | Optional; less emphasis than TikTok |
| Title | Critical for discovery; write a compelling short title |
| Subscribe CTA | Relevant; viewers can subscribe directly from Shorts |
| Aspect ratio | 9:16 (1080x1920) |

**Content rules:**
- Can be more educational and detailed than TikTok.
- Viewers are slightly more willing to watch longer content.
- Title is very important (appears at the bottom of the Short).
- Open with a hook but can take an extra second to set up context.
- Subscribe CTA is valuable because YouTube Shorts drive channel subscriptions.

### 6.4 Facebook Reels

| Property | Value |
|---|---|
| Duration sweet spot | 15-60 seconds |
| Hook window | First 2-3 seconds |
| Pacing | Moderate: visual change every 4-6 seconds |
| Caption style | Bold, centered |
| Caption size | 40-44px |
| Caption position | Centered at y ~ 74% of canvas (y=1420) |
| Caption color | White with 3px black stroke |
| Music | Optional; less trending-audio-driven than TikTok |
| Autoplay | Muted by default |
| Audience | Slightly older demographic (30-55) |
| Aspect ratio | 9:16 (1080x1920) |

**Content rules:**
- **Captions are essential.** Facebook autoplay is muted; without captions, you lose most
  viewers immediately.
- Less aggressive editing than TikTok; the audience is less accustomed to rapid-fire cuts.
- Content that educates or informs performs better than pure entertainment.
- Slightly longer setups are acceptable; the audience has more patience.

### 6.5 LinkedIn

| Property | Value |
|---|---|
| Duration sweet spot | 30-120 seconds |
| Hook window | First 3-5 seconds |
| Pacing | Slow-moderate: visual change every 6-10 seconds |
| Caption style | Subtitle bar (bottom, professional) |
| Caption size | 28-32px |
| Caption position | Bottom bar, y=1540-1600 |
| Caption color | White on semi-transparent dark bar (#1A1A1A at 80% opacity) |
| Music | None, or very subtle ambient (no trending tracks) |
| Tone | Professional, authoritative, value-driven |
| Audience | Professionals, decision-makers, B2B |
| Aspect ratio | 9:16 (1080x1920) |

**Content rules:**
- **Professional tone is mandatory.** No memes, no TikTok trends, no aggressive pacing.
- Lead with value: "Here is how to..." or "I discovered that..." or "This saved our team..."
- Slower pacing allows the viewer to absorb information.
- Data, metrics, and results resonate strongly (show numbers, graphs, dashboards).
- Subtle, understated captions (subtitle bar style, not bold centered).
- No trendy music. Silence or very quiet ambient background is appropriate.
- Soft CTA: "What do you think?" or "Drop a comment" rather than "FOLLOW ME."

---

## 7. Caption Styles by Platform

### 7.1 Quick Reference Table

| Platform | Style | Font Size | Position (Y center) | Font Weight | Stroke | Background |
|----------|-------|-----------|---------------------|-------------|--------|------------|
| TikTok | bold_centered | 48-52px | y=1440 (75%) | 800 (Extra Bold) | 3px black | None |
| Instagram | bold_centered | 44-48px | y=1400 (73%) | 800 (Extra Bold) | 3px black | None |
| YouTube | subtitle_bar | 32-36px | y=1530 (80%) | 600 (Semi Bold) | None | #000000 at 60% opacity, 8px padding |
| Facebook | bold_centered | 40-44px | y=1420 (74%) | 700 (Bold) | 3px black | None |
| LinkedIn | subtitle_bar | 28-32px | y=1570 (82%) | 500 (Medium) | None | #1A1A1A at 80% opacity, 10px padding |

### 7.2 Bold Centered Style (TikTok, Instagram, Facebook)

```
Properties:
  font_family: "Inter", "Montserrat", or system sans-serif
  font_weight: 700-800
  font_size: see table above
  text_align: center
  color: #FFFFFF
  stroke_color: #000000
  stroke_width: 3px
  shadow: none (stroke provides contrast)
  max_width: 860px (leaves 110px margin on each side)
  position_x: 540 (centered)
  position_y: see table above
  line_height: 1.3
  max_lines: 2 (split longer text across timed segments)
  word_highlight: optional (highlight current word in accent color)
```

**Word-by-word highlight (optional, TikTok preferred):**
- Display the full caption line.
- As each word is spoken, highlight it in an accent color (#FFD700 gold or #00E5FF cyan).
- This creates a karaoke effect that boosts engagement and watch time.

### 7.3 Subtitle Bar Style (YouTube, LinkedIn)

```
Properties:
  font_family: "Inter", "Roboto", or system sans-serif
  font_weight: 500-600
  font_size: see table above
  text_align: center
  color: #FFFFFF
  background_color: #000000 (YouTube) or #1A1A1A (LinkedIn)
  background_opacity: 60% (YouTube) or 80% (LinkedIn)
  background_padding: 8-10px vertical, 16-20px horizontal
  background_corner_radius: 6px
  max_width: 960px
  position_x: 540 (centered)
  position_y: see table above
  line_height: 1.4
  max_lines: 2
```

### 7.4 Caption Placement and Platform UI Avoidance

Captions must not overlap with platform UI elements. Verify:

| Platform | Caption Y range (top of text to bottom of text) | Must be above |
|---|---|---|
| TikTok | y=1390 to y=1490 | y=1600 (bottom danger zone) |
| Instagram | y=1350 to y=1450 | y=1560 (bottom danger zone) |
| YouTube | y=1490 to y=1570 | y=1580 (bottom danger zone) |
| Facebook | y=1370 to y=1470 | y=1600 (bottom danger zone) |
| LinkedIn | y=1530 to y=1610 | y=1620 (bottom danger zone) |

All caption positions in this guide have been designed to sit safely above the platform UI
danger zones.

---

## 8. Video Structure Templates

These templates define the segment-by-segment structure for each platform. The AI should use
these as a starting framework, adjusting based on actual content analysis.

### 8.1 TikTok / Instagram Reels (15-60 seconds)

```
TIME        LAYOUT    PURPOSE         NOTES
---------------------------------------------------------------------------
0-3s        D         HOOK            Full-screen face, bold opening statement
                                      Caption: single punchy line, 52px bold
                                      Goal: stop the scroll

3-8s        A or B    CONTEXT         Split layout, speaker explaining + screen visible
                                      Caption: what the viewer will learn
                                      Transition: hard cut from D to A/B

8-15s       C or A    DEMO            Screen-dominant (PIP) or 30/70 split
                                      Show the actual screen content
                                      Use zoom-ins on key UI elements

15-25s      E         DETAILS         Dynamic switching: zoom-ins, layout switches
                                      Change visual every 3-5 seconds
                                      Maintain energy and information density

25-30s      D         CTA             Back to full-screen face
                                      Clear call to action: follow, link, try it
                                      Caption: CTA text, 48px bold
```

For clips shorter than 30 seconds, compress the middle sections. The hook (0-3s) and CTA
(last 3s) are non-negotiable.

### 8.2 YouTube Shorts (30-60 seconds)

```
TIME        LAYOUT    PURPOSE         NOTES
---------------------------------------------------------------------------
0-2s        D         HOOK            Face or bold text overlay
                                      Slightly less aggressive than TikTok
                                      Caption: clear, concise hook line

2-10s       A or B    SETUP           Explain what you will show
                                      Speaker + screen context
                                      Establish credibility quickly

10-40s      E         WALKTHROUGH     Dynamic layout switching
                                      PIP for screen-heavy segments
                                      Zoom-ins on important details
                                      Layout change every 5-7 seconds
                                      Subtitle-bar captions throughout

40-55s      A or B    KEY TAKEAWAY    Return to split layout
                                      Summarize the main point
                                      Speaker + key result on screen

55-60s      D         CTA             Face, subscribe mention
                                      Caption: subscribe / check description
```

### 8.3 LinkedIn (30-120 seconds)

```
TIME        LAYOUT    PURPOSE         NOTES
---------------------------------------------------------------------------
0-5s        A or B    PROFESSIONAL    Split layout with clear statement
              HOOK                    No gimmicks, lead with value
                                      Caption: subtitle bar, concise

5-30s       C or A    DEMONSTRATION   Screen-dominant with professional captions
                                      Show the actual tool/process/result
                                      Zoom into data or metrics
                                      Pacing: visual change every 6-10s

30-60s      B or D    VALUE           Split layout or face for credibility
              EXPLANATION             Explain why this matters
                                      Connect to business outcomes

60-90s      C         RESULTS/PROOF   Zoom into metrics, dashboards, data
                                      Let the numbers speak
                                      Subtitle-bar captions with key figures

90-120s     D or B    CLOSING         Face for soft CTA
                                      "Thoughts?" or "What has worked for you?"
                                      Professional, inviting tone
```

For LinkedIn clips shorter than 60 seconds, compress to: Hook (0-5s) + Demo (5-40s) +
Closing (40-60s).

---

## 9. Source Video Analysis Checklist

Before generating any edit, the AI must perform these analysis steps on the source video.
Each step produces data that informs layout selection and crop parameters.

### 9.1 Face Detection

| Check | Action |
|---|---|
| Detect face bounding box in every scene | Store (x, y, width, height) per scene |
| Calculate face center coordinates | Used for centering in crop |
| Measure face width relative to frame | Determines crop tightness |
| Detect eye positions | Used for eye-line placement |
| Check for multiple faces | Flag for review; default to primary speaker |
| Track face movement across frames | Detect if speaker moves significantly |

### 9.2 Screen Content Analysis

| Check | Action |
|---|---|
| Identify screen recording boundaries | Detect where the screen capture starts/ends in the source |
| Detect browser chrome (tabs, address bar) | Map the pixel region to exclude |
| Detect OS taskbar/dock | Map the pixel region to exclude |
| Detect webcam overlay in screen recording | Map the overlay region to exclude |
| Calculate content area bounds | The usable screen content after all exclusions |
| Measure minimum text size in content area | Determine if zoom-ins are needed |
| Identify cursor position over time | Used for zoom-in targeting |

### 9.3 Timeline Mapping

| Check | Action |
|---|---|
| Scene detection | Identify scene boundaries (visual change points) |
| Content type per scene | Classify: face-only, screen-only, face+screen, transition |
| Transcript alignment | Map words to timestamps |
| Identify hook moments | First sentence, surprising statements, questions |
| Identify key points | Main teaching moments, reveals, demonstrations |
| Identify CTA moments | Closing statements, calls to action |
| Highlights data | Check for engagement highlights from analytics or AI scoring |

### 9.4 Layout Planning

Based on the above analysis, assign a layout to each segment:

```
For each segment:
  IF content_type == "face_only":
    layout = D (full-screen face)
  ELIF content_type == "screen_only":
    layout = C (PIP) if face_available else screen_zoom
  ELIF content_type == "face_and_screen":
    IF face_is_primary_focus:
      layout = B (40/60 balanced)
    ELSE:
      layout = A (30/70 tutorial)

  IF segment_index == 0:
    layout = D (hook)
  IF segment_index == last:
    layout = D (CTA)
```

---

## 10. Quality Checklist

Before rendering any clip, verify every item below. A failed check must be corrected before
the render proceeds.

### 10.1 Geometry and Framing

- [ ] **No stretching or distortion.** All content uses `cover` or `contain` fit modes,
  never `stretch`. Aspect ratios are preserved.
- [ ] **Face is centered horizontally** in its region (within 20px of center).
- [ ] **Eyes are on the upper-third line** of the face region (within 30px).
- [ ] **Headroom is 30-60px** (not excessive, not clipped).
- [ ] **Face width is 60-80%** of the face region width.

### 10.2 Content Integrity

- [ ] **No duplicate webcam.** If using Layouts A/B/C/D with a separate face region, the
  webcam overlay in the source screen recording is cropped out.
- [ ] **No browser chrome visible.** Tab bar, bookmarks bar, address bar are all cropped.
- [ ] **No OS taskbar/dock visible.** Bottom taskbar and top menu bar are cropped.
- [ ] **All text is readable.** Minimum 40px rendered height on the 1080px canvas.

### 10.3 Platform Compliance

- [ ] **Captions do not overlap with platform UI.** Caption Y position is above the platform
  bottom danger zone.
- [ ] **Critical content is within the safe zone.** Face, key text, and active screen content
  are all within the safe zone rectangle for the target platform.
- [ ] **Right-side margin is clear.** No critical content in the right danger zone (where
  like/comment/share buttons appear).

### 10.4 Dead Space

- [ ] **No unintentional black bars** or empty regions.
- [ ] **No unfilled gaps** between face and screen regions in split layouts.
- [ ] **Background fill is #0D0D0D** (not pure black) when dark fill is used.

### 10.5 Pacing and Structure

- [ ] **Hook in first 3 seconds.** The opening segment uses Layout D (full-screen face) or
  a bold text overlay.
- [ ] **CTA in last 3-5 seconds.** The closing segment returns to Layout D with a clear
  call to action.
- [ ] **Visual variety.** Layout or visual change occurs every 3-8 seconds (platform
  dependent).
- [ ] **No single layout held for more than 8 seconds** without a visual change (zoom,
  caption change, or layout switch).

### 10.6 Audio and Captions

- [ ] **Captions are present** for all spoken content.
- [ ] **Caption style matches the target platform** (bold_centered vs subtitle_bar).
- [ ] **Caption timing is accurate** (within 100ms of speech).
- [ ] **No caption line exceeds 2 lines** of text at the specified font size.
- [ ] **Caption text fits within max_width** (860px for bold_centered, 960px for
  subtitle_bar).

---

## Appendix A: Pixel Reference Quick Sheet

This is a fast-lookup table for the most commonly needed measurements.

| Measurement | Value |
|---|---|
| Canvas width | 1080px |
| Canvas height | 1920px |
| Canvas center X | 540px |
| Canvas center Y | 960px |
| Upper-third line (full canvas) | 640px |
| Lower-third line (full canvas) | 1280px |
| Universal safe zone (all platforms) | (60, 108) to (940, 1560) |
| Layout A face region | 0, 0, 1080, 576 |
| Layout A screen region | 0, 576, 1080, 1344 |
| Layout B face region | 0, 0, 1080, 768 |
| Layout B screen region | 0, 768, 1080, 1152 |
| Layout C PIP circle | 24, 140, 240, 240 |
| Layout C PIP rectangle | 24, 140, 280, 350 |
| PIP max Y | 1440 (must stay above) |
| PIP max X | 900 (must stay left of) |
| Minimum text height | 40px |
| Dark background color | #0D0D0D |
| Caption max width (bold) | 860px |
| Caption max width (subtitle bar) | 960px |
| Face width target | 60-80% of region width |
| Headroom target | 30-60px |

## Appendix B: Fit Mode Reference

| Mode | Behavior | Dead space? | Content loss? |
|---|---|---|---|
| `cover` | Scale to fill, crop overflow | No | Yes (edges) |
| `contain` | Scale to fit, letterbox/pillarbox remainder | Yes (needs fill) | No |
| `stretch` | Scale both axes independently | No | No, but distorted -- NEVER USE |

## Appendix C: Color Reference

| Usage | Color | Notes |
|---|---|---|
| Dark background fill | #0D0D0D | Near-black, avoids banding |
| Caption text | #FFFFFF | Pure white |
| Caption stroke | #000000 | Pure black, 3px width |
| Subtitle bar background (YouTube) | #000000 at 60% | Semi-transparent |
| Subtitle bar background (LinkedIn) | #1A1A1A at 80% | Slightly lighter, more professional |
| Word highlight (TikTok) | #FFD700 or #00E5FF | Gold or cyan accent |
| PIP border | #FFFFFF | 3px solid white |
