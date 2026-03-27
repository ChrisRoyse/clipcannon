# ClipCannon TikTok Conversion Prompt -- Part 1: Strategy & Overview

## MISSION

You are an AI video editor operating ClipCannon via MCP tools. Your job is to convert a 7:57 (476,961ms) screen recording from 16:9 (3840x2160) into a retention-maximized 9:16 (1080x1920) TikTok video. You must keep ALL content -- zero cuts. Every second of the original video stays in the final output. Your job is to ENHANCE the video with dynamic layouts, overlays, sound effects, color grading, motion effects, and bold captions that maximize viewer retention, engagement, and profit.

## PROJECT DETAILS

```
Project ID:          proj_ace4bcb3
Source Video:        03262026voiceclonevideo.mp4
Duration:            476,961ms (7 minutes 57 seconds)
Source Resolution:   3840x2160 (4K 16:9)
Target Resolution:   1080x1920 (9:16 TikTok vertical)
FPS:                 60 -> 30 (TikTok profile)
Codec:               h264
Audio:               AAC stereo
Speaker:             1 speaker (71.5% speaking time)
Webcam Position:     x=2712, y=1448, w=840, h=711 (bottom-right of source)
OCR Regions:         455 detected
Scenes:              62
BPM Detected:        125
Content Rating:      mild
```

## SOURCE VIDEO ANATOMY

The source is a 4K screen recording with the speaker's webcam overlay in the bottom-right corner. The main screen shows code editors, terminal windows, benchmark charts, video players, and file browsers. The speaker narrates over the screen content, demonstrating an AI voice cloning system built in 2 days that achieves 98.9% accuracy.

### Key Regions in Source Frame (3840x2160)

| Region | Coordinates | Content |
|--------|-------------|---------|
| **Screen Content** | (0, 0, 2700, 1440) | Main IDE/terminal/browser area |
| **Webcam Overlay** | (2712, 1448, 840, 711) | Speaker face, bottom-right |
| **Browser Chrome** | (0, 0, 3840, 80) | Tab bar, address bar -- ALWAYS CROP OUT |
| **OS Taskbar** | (0, 2110, 3840, 50) | Bottom taskbar -- ALWAYS CROP OUT |

## HORMOZI CONTENT STRATEGY (Extracted from 1,150 transcripts + "$100M Leads" book)

### The Content Unit Framework

Every piece of content must do three things:
1. **HOOK** -- Give them a reason to stop scrolling (first 3 seconds)
2. **RETAIN** -- Embed unresolved questions to keep them watching (lists, steps, stories)
3. **REWARD** -- Satisfy the reason they started watching (deliver the proof)

### Critical Hormozi Principles Applied to This Video

**1. The First 5 Seconds Are 80% of the Video's Success**
- Hormozi's editor changed ONLY the first 5 seconds of a video: 4,000 views -> 850,000 views (200x increase)
- "If the first 5 seconds is what immediately sorts 80-90% of the traffic, then isn't it crazy that we don't spend more time testing that one piece?"
- APPLICATION: The opening must be a face-dominant Layout D with a bold text overlay. The speaker's first words are powerful: "I built Clip Cannon" -- enhance this with a dramatic zoom-in and impact sound.

**2. Visualize Data, Don't Just Talk About It**
- "From visual effects to visualizing data. Instead of having flames behind me, what does this look like on a chart?"
- APPLICATION: When the speaker shows benchmarks (98.9% accuracy), use zoom effects to make the numbers fill the screen. Add title_card overlays that pop the key stats.

**3. Education > Entertainment for Conversions**
- "Longs drive a lot more conversions than shorts. Business related content brings more business owners."
- "The content is the targeting. The algorithm is so good now."
- APPLICATION: This video educates about voice cloning technology. Keep the educational angle sharp. Don't over-produce with distracting effects. Use effects to ENHANCE comprehension, not distract.

**4. Pre-search > Post-production**
- "An ounce of pre-work is worth a pound of post."
- APPLICATION: The segment plan below is your pre-work. Follow it precisely.

**5. Assume Nothing -- Title Like They Don't Know You**
- "Let the new people in. Fully explain references. Act as though you're always talking to a stranger."
- APPLICATION: The overlays should contextualize claims for newcomers. When the speaker says "98.9%", the overlay should say "VOICE CLONE ACCURACY" so a stranger understands immediately.

**6. Hook Structure: 50 Hooks x 3-5 Meats x 1-3 CTAs**
- Hooks convert across different audiences because they just draw attention
- APPLICATION: The hook overlay should be a universally compelling claim that doesn't require knowing ClipCannon.

**7. Value Per Second -- "No Such Thing As Too Long, Only Too Boring"**
- Pattern interrupts every 5-8 seconds in short-form
- "The same person who gets bored 3 seconds into a 10-second video may binge a 900-page book"
- APPLICATION: Switch layouts, add zooms, pop stats, and fire sound effects at regular intervals. Never let the visual stay static for more than 8 seconds.

**8. Reward = Match or Exceed Expectations**
- "Does it satisfy the reason they watched? Does it make people want to share it?"
- APPLICATION: The video promises "perfect voice cloning" -- it MUST deliver the demo proof. The Jimmy Cracked Corn demo and Hello Ann demo are the rewards. Make them visually prominent.

### Viral Trigger Analysis for This Video

| Trigger | Present? | Enhancement |
|---------|----------|-------------|
| **Bold Contrarian Claim** | YES -- "destroyed entire industries in 2 days" | Face-dominant hook, stat overlay |
| **Proof/Benchmark** | YES -- 98.9% SECS accuracy | Zoom into benchmark chart, stat pop overlay |
| **Live Demo** | YES -- voice clone playback | Full-screen the demo video, impact SFX |
| **Before/After** | YES -- comparison to competitors | Split visual, color shift |
| **Educational** | YES -- explains how voice fingerprinting works | Screen-dominant layouts for technical |
| **Shareability** | HIGH -- "Send this to someone building with AI" | CTA overlay at end |

## NARRATIVE STRUCTURE (from ClipCannon analysis)

```
ACT 1: HOOK & SETUP (0:00 - 1:30)
  Story Beat: "I built an AI that can clone anyone's voice perfectly"
  Open Loop: "I can clone anybody without them being there"
  Layout Strategy: D -> C -> A (face hook -> demo -> split)

ACT 2: PROOF & DEMONSTRATION (1:30 - 5:10)
  Story Beat: Voice clone demos + benchmark reveal
  Retention: Lists (benchmarks), demos (audio playback), bold claims
  Layout Strategy: C -> D -> A -> C (dynamic switching every 5-8s)

ACT 3: METHODOLOGY REVEAL (5:10 - 6:40)
  Story Beat: WHY this test is harder, technical explanation
  Retention: Steps (how the benchmark works), controversy (calling out competitors)
  Layout Strategy: A -> C -> D (screen for data, face for claims)

ACT 4: FINAL PROOF & CLOSE (6:40 - 7:57)
  Story Beat: "Took me 2 days to dumpster your entire industry" + final demo
  Reward: Plays the "Hello Ann" generated video -- the proof of the promise
  Layout Strategy: D -> C -> D (face for bold claim, demo fullscreen, face CTA)
```

## LAYOUT REFERENCE (1080x1920 Output Canvas)

### Layout D: Full-Screen Face (Hooks, Bold Claims, CTAs)
Use when: Speaker makes direct-to-camera bold statements, hooks, closing CTA.
```json
{
  "canvas": {
    "enabled": true,
    "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "face_full",
        "source_x": 2512, "source_y": 1248,
        "source_width": 1100, "source_height": 912,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 1920,
        "z_index": 1, "fit_mode": "cover"
      }
    ]
  }
}
```

### Layout A: 30/70 Split (Tutorials, Screen-Heavy Moments)
Use when: Speaker explains while screen shows important content (benchmarks, code, charts).
```json
{
  "canvas": {
    "enabled": true,
    "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "speaker_top",
        "source_x": 2612, "source_y": 1348,
        "source_width": 940, "source_height": 811,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 576,
        "z_index": 1, "fit_mode": "cover"
      },
      {
        "region_id": "screen_bottom",
        "source_x": 40, "source_y": 80,
        "source_width": 2660, "source_height": 1360,
        "output_x": 0, "output_y": 576,
        "output_width": 1080, "output_height": 1344,
        "z_index": 1, "fit_mode": "contain"
      }
    ]
  }
}
```

### Layout B: 40/60 Split (Balanced Face+Screen)
Use when: Both speaker and screen are equally important.
```json
{
  "canvas": {
    "enabled": true,
    "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "speaker_top",
        "source_x": 2612, "source_y": 1348,
        "source_width": 940, "source_height": 811,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 768,
        "z_index": 1, "fit_mode": "cover"
      },
      {
        "region_id": "screen_bottom",
        "source_x": 40, "source_y": 80,
        "source_width": 2660, "source_height": 1360,
        "output_x": 0, "output_y": 768,
        "output_width": 1080, "output_height": 1152,
        "z_index": 1, "fit_mode": "contain"
      }
    ]
  }
}
```

### Layout C: PIP (Screen Dominant, Small Face)
Use when: Screen content is the focus (demos playing, benchmark charts, code).
```json
{
  "canvas": {
    "enabled": true,
    "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "screen_full",
        "source_x": 0, "source_y": 80,
        "source_width": 3840, "source_height": 2030,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 1920,
        "z_index": 1, "fit_mode": "contain"
      },
      {
        "region_id": "pip_speaker",
        "source_x": 2712, "source_y": 1448,
        "source_width": 840, "source_height": 711,
        "output_x": 24, "output_y": 140,
        "output_width": 240, "output_height": 240,
        "z_index": 2, "fit_mode": "cover"
      }
    ]
  }
}
```

### Layout C-Zoom: Screen Zoom (Zoomed Into Specific Content)
Use when: Need to zoom into benchmarks, specific text, or data.
Adjust source_x/source_y/source_width/source_height to crop the target area.

## CAPTION CONFIGURATION

```json
{
  "captions": {
    "enabled": true,
    "style": "bold_centered",
    "font_size": 56,
    "color": "#FFFFFF"
  }
}
```

Captions are auto-generated from the transcript word timestamps. Bold centered white text, positioned in the lower-third safe zone. These are critical -- 85% of TikTok viewers watch without sound.

## EXECUTION ORDER

The AI agent must execute these ClipCannon tools in this exact order:

```
1. clipcannon_project_open(project_id="proj_ace4bcb3")
2. clipcannon_create_edit(...)        -- Create the edit with all segments, per-segment canvas, captions
3. clipcannon_add_overlay(...)        -- Add each overlay (title cards, lower thirds, CTAs) one at a time
4. clipcannon_add_motion(...)         -- Add motion effects to specific segments
5. clipcannon_color_adjust(...)       -- Apply color grading (global first, then per-segment)
6. clipcannon_generate_sfx(...)       -- Generate each sound effect
7. clipcannon_compose_midi(...)       -- Generate background music
8. clipcannon_preview_layout(...)     -- Preview key frames to verify layouts
9. clipcannon_preview_clip(...)       -- Preview first 5 seconds
10. clipcannon_render(...)            -- Final render
11. clipcannon_inspect_render(...)    -- Quality check
```

## FILES IN THIS PROMPT SET

| File | Content |
|------|---------|
| `tiktok_conversion_prompt_01_strategy.md` | THIS FILE -- Strategy, Hormozi principles, layouts, overview |
| `tiktok_conversion_prompt_02_segments_act1_act2.md` | Segments 1-28: Act 1 (0:00-1:30) + Act 2 (1:30-5:10) |
| `tiktok_conversion_prompt_03_segments_act3_act4.md` | Segments 29-45: Act 3 (5:10-6:40) + Act 4 (6:40-7:57) |
| `tiktok_conversion_prompt_04_effects_and_execution.md` | Complete overlay timeline, SFX list, music spec, color grading, render settings, QA checklist |

---

**PROCEED TO PART 2 FOR THE SEGMENT-BY-SEGMENT BREAKDOWN.**
