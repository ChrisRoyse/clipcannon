# ClipCannon AI Video Editing Guide

Canvas: **1080x1920** (9:16). All values in pixels. Platforms: TikTok, Instagram Reels, YouTube Shorts, Facebook Reels, LinkedIn.

## Core Directive

**Think like a director. Use every tool. Iterate on previews. Match visuals to what the speaker is saying.**

1. Every cut/layout/zoom is a storytelling decision — ask "what must the viewer see NOW?"
2. Combine auto-trim, color, motion, overlays, audio cleanup, and layouts — not just cuts
3. Always preview before rendering: `preview_layout` (~300ms), `preview_clip` (~1s), `inspect_render` after
4. Read the transcript — the words drive the visuals. "Look at this dashboard" = dashboard dominant. "I built this" = face dominant.

---

## 1. Platform Safe Zones

| Platform | Safe Zone (x1,y1)→(x2,y2) | Right Danger | Bottom Danger | Top Danger |
|---|---|---|---|---|
| TikTok | (60,108)→(960,1600) | x>960 (120px) | y>1600 (320px) | y<108 |
| Instagram | (60,108)→(940,1560) | x>940 (140px) | y>1560 (360px) | y<108 |
| YouTube | (60,108)→(940,1580) | x>940 (140px) | y>1580 (340px) | y<108 |
| Facebook | (60,100)→(960,1600) | x>960 (120px) | y>1600 (320px) | y<100 |
| LinkedIn | (48,96)→(984,1620) | x>984 (96px) | y>1620 (300px) | y<96 |

**Universal safe zone (cross-platform): (60,108)→(940,1560) = 880x1452**

---

## 2. Layouts

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

## 3. Dead Space Elimination

| Priority | Technique | Notes |
|---|---|---|
| 1 | Blurred background fill | Gaussian r=40-60px of source frame |
| 2 | Cover fit | `fit_mode:"cover"`, crops edges |
| 3 | Solid dark fill | `fit_mode:"contain"`, `background_color:"#0D0D0D"` |
| 4 | Content stacking | Face+screen span full 1920px (Layouts A/B) |

---

## 4. Face Framing

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
2. Use those EXACT dimensions as source crop — do NOT subcrop
3. Output region height should match source webcam height (~500-600px)
4. Crop the webcam overlay OUT of the screen content region to prevent duplicates

Wrong: `source_width=350, source_height=400` (zoomed). Correct: `source_width=560, source_height=590` (full overlay).

---

## 5. Visual-Speech Alignment

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

## 6. Screen Content Rules

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

## 7. Platform Strategy

| Platform | Duration | Hook | Pacing | Music | Notes |
|---|---|---|---|---|---|
| TikTok | 15-60s | 1-3s | 3-5s changes | Energetic 120+ BPM | Text overlays for sound-off. Bold hook. |
| Instagram | 15-90s | 2-3s | 4-6s changes | Trending audio | More polished than TikTok. Cover frame matters. |
| YouTube | 30-60s | 2s | 4-7s changes | Optional | Educational. Title critical. Subscribe CTA valuable. |
| Facebook | 15-60s | 2-3s | 4-6s changes | Optional | **Captions essential** (muted autoplay). Older demo (30-55). |
| LinkedIn | 30-120s | 3-5s | 6-10s changes | None/subtle | Professional tone. Lead with value. Data resonates. Soft CTA. |

---

## 8. Captions

| Platform | Style | Size | Y Pos | Weight | Stroke | Background |
|---|---|---|---|---|---|---|
| TikTok | bold_centered | 48-52px | 1440 | 800 | 3px black | None |
| Instagram | bold_centered | 44-48px | 1400 | 800 | 3px black | None |
| YouTube | subtitle_bar | 32-36px | 1530 | 600 | None | #000 @60% |
| Facebook | bold_centered | 40-44px | 1420 | 700 | 3px black | None |
| LinkedIn | subtitle_bar | 28-32px | 1570 | 500 | None | #1A1A1A @80% |

**Bold centered:** font=Inter/Montserrat, color=#FFF, stroke=3px #000, max_width=860px, centered x=540, max 2 lines. Optional word highlight: #FFD700 or #00E5FF (TikTok).

**Subtitle bar:** font=Inter/Roboto, color=#FFF, bg padded 8-10px v / 16-20px h, radius=6px, max_width=960px, max 2 lines.

---

## 9. Video Structure Templates

### TikTok / Instagram (15-60s)
```
0-3s    D   HOOK (face, bold opening)
3-8s    A/B CONTEXT (split, speaker+screen)
8-15s   C/A DEMO (screen-dominant, zoom-ins)
15-25s  E   DETAILS (dynamic, change every 3-5s)
25-30s  D   CTA (face, call to action)
```

### YouTube Shorts (30-60s)
```
0-2s    D   HOOK
2-10s   A/B SETUP (credibility)
10-40s  E   WALKTHROUGH (dynamic, PIP, every 5-7s)
40-55s  A/B KEY TAKEAWAY
55-60s  D   CTA (subscribe)
```

### LinkedIn (30-120s)
```
0-5s    A/B PROFESSIONAL HOOK (lead with value)
5-30s   C/A DEMO (screen-dominant, every 6-10s)
30-60s  B/D VALUE EXPLANATION
60-90s  C   RESULTS/PROOF (metrics)
90-120s D/B CLOSING (soft CTA)
```

Hook and CTA are non-negotiable on all platforms.

---

## 10. Auto-Trim

Removes 20 filler words (um, uh, like, basically, literally, actually, you know, i mean, right, okay, so, well, yeah, etc.) and silence gaps.

| Param | Default | Description |
|---|---|---|
| `pause_threshold_ms` | 800 | Pauses longer → removed |
| `merge_gap_ms` | 200 | Segments closer → merged |
| `min_segment_ms` | 500 | Segments shorter → dropped |

Tuning: **Aggressive** (TikTok): 500/200/300. **Gentle** (LinkedIn): 1200/200/1000.

Flow: `auto_trim` → segments[] → `create_edit(segments=segments)`

---

## 11. Color Grading

| Param | Range | Default |
|---|---|---|
| `brightness` | -1.0 to 1.0 | 0.0 |
| `contrast` | 0.0 to 3.0 | 1.0 |
| `saturation` | 0.0 to 3.0 | 1.0 |
| `gamma` | 0.1 to 10.0 | 1.0 |
| `hue_shift` | -180 to 180 | 0.0 |

Omit `segment_id` for global. Include for per-segment override.

| Platform | Grade |
|---|---|
| TikTok | contrast=1.2, saturation=1.15 |
| Instagram | contrast=1.1, saturation=1.1 |
| YouTube | contrast=1.05, brightness=0.05 |
| LinkedIn | contrast=1.0, saturation=0.95 |

---

## 12. Motion Effects

| Effect | Use |
|---|---|
| `zoom_in` | Emphasis, attention |
| `zoom_out` | Reveals, establishing |
| `pan_left/right` | Following content |
| `pan_up/down` | Scrolling content |
| `ken_burns` | Cinematic, still images |

Params: `start_scale` (0.5-3.0, default 1.0), `end_scale` (0.5-3.0, default 1.3), `easing` (linear/ease_in/ease_out/ease_in_out).

Guidelines: Subtle=1.0→1.1. Moderate=1.0→1.3. Strong=1.0→2.0 (sparingly). Ken Burns best for stills/screenshots.

Pipeline order: motion → color → captions → overlays.

---

## 13. Overlays

| Type | Use |
|---|---|
| `lower_third` | Speaker ID (name+subtitle) |
| `title_card` | Chapter titles, intro |
| `logo` | Brand identity |
| `watermark` | Attribution (opacity ~0.3) |
| `cta` | "Subscribe", "Learn More" |

Key params: `text`, `position` (bottom_left/center/right, top_left/center/right, center), `start_ms`, `end_ms`, `font_size` (8-200, default 36), `text_color` (#FFF), `bg_color` (#000), `bg_opacity` (0.7), `animation` (none/fade_in/fade_out/slide_up/slide_down), `animation_duration_ms` (500).

Lower thirds: 3-5s duration, fade in 500ms, keep within platform safe zone.

---

## 14. Audio Cleanup

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

---

## 15. Preview & Inspection

**preview_layout**: Single composited frame, ~300ms. Use to validate crop/layout before render.

**preview_clip**: 540x960, 1Mbps, ultrafast, max 5s, 0 credits, ~500-1000ms. Use at key timestamps (hook, CTA, transitions).

**inspect_render**: Post-render. Checks file size, duration, resolution, codec, audio presence. Extracts frames at 0%, 25%, 50%, 75%, end.

Workflow: decide coords → preview_layout → adjust → repeat → render → inspect_render → fix if needed.

---

## 16. Complete Workflow

```
1. project_create → ingest → wait "ready"
2. get_editing_context + get_vud_summary + analyze_frame
3. auto_trim → clean segments
4. create_edit (segments from auto_trim or manual)
5. color_adjust + add_motion + add_overlay
6. audio_cleanup
7. preview_clip + preview_layout at key points
8. generate_metadata
9. render
10. inspect_render → if issues → modify_edit → re-render
```

---

## 17. Quality Checklist

- No stretching (cover or contain, NEVER stretch)
- Face centered horizontally (±20px of center)
- Eyes on upper-third line (±30px)
- Headroom 30-60px, face width 60-80%
- No duplicate webcam in output
- No browser chrome / OS taskbar visible
- All text ≥40px rendered height
- Captions above platform danger zone, within safe zone
- No unintentional black bars; dark fill = #0D0D0D
- Hook in first 3s (Layout D), CTA in last 3-5s (Layout D)
- Visual change every 3-8s (platform dependent)
- Captions on all spoken content, accurate within 100ms, max 2 lines

---

## Quick Reference

| Measurement | Value |
|---|---|
| Canvas | 1080x1920, center (540,960) |
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
| `stretch` | **NEVER USE** | — | Distorted |

| Color Use | Value |
|---|---|
| Dark fill | #0D0D0D |
| Caption text | #FFFFFF |
| Caption stroke | #000000 3px |
| Subtitle bg (YouTube) | #000000 @60% |
| Subtitle bg (LinkedIn) | #1A1A1A @80% |
| Word highlight | #FFD700 or #00E5FF |
| PIP border | #FFFFFF 3px |
