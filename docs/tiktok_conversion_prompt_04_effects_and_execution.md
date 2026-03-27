# ClipCannon TikTok Conversion Prompt -- Part 4: Effects, Music, Rendering & Execution

## CONTEXT REMINDER

- **Project**: `proj_ace4bcb3` at `~/.clipcannon/projects/proj_ace4bcb3/`
- **Working Directory**: `/home/cabdru/clipcannon/`
- **Source Video**: `~/.clipcannon/projects/proj_ace4bcb3/source/03262026voiceclonevideo.mp4`
- **Source**: 3840x2160, 60fps, h264, 476961ms (7:57)
- **Webcam**: Bottom-right at (x=2712, y=1448, w=840, h=711)
- **Target**: 1080x1920 TikTok, ALL content preserved, zero cuts
- **MCP Connection**: Tools prefixed `clipcannon_` via MCP protocol

---

## CRITICAL LAYOUT RULE: TRACK THE SPEAKER'S TOPIC AT ALL TIMES

**THE #1 RULE OF THIS EDIT: The bottom 70% of the video MUST show what the speaker is currently talking about. No exceptions. 100% accuracy required.**

The speaker's webcam/face occupies the top 30% (576px of 1920px). The bottom 70% (1344px) shows the screen content that matches what the speaker is discussing at that exact moment. This is a 30/70 split (Layout A) as the DEFAULT layout for the majority of the video.

When the speaker references specific screen content (benchmarks, code, terminal, video player, file browser), the bottom region MUST show that content. Use `get_scene_map` and the transcript to verify alignment. The screen content changes as the speaker navigates -- each segment's `source_x`, `source_y`, `source_width`, `source_height` for the screen region must be adjusted to crop to the RELEVANT part of the screen at that timestamp.

**When to deviate from Layout A (30/70)**:
- **Layout D (full face)**: ONLY during the hook (0-6s), pure direct-address bold claims with NO screen reference, and the final CTA
- **Layout C (PIP)**: ONLY when a demo video is playing on screen and needs maximum visibility

**For ALL other moments**: Layout A. Speaker top 30%, screen content bottom 70%. The screen content region MUST be cropped to show what the speaker is referencing.

### How to Get the Right Screen Crop Coordinates

1. Use `clipcannon_get_scene_map(project_id="proj_ace4bcb3", detail="full")` to get pre-computed canvas regions per scene
2. Use `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=X)` to visually inspect what's on screen at any timestamp
3. Use `clipcannon_analyze_frame(project_id="proj_ace4bcb3", timestamp_ms=X)` to detect content regions (bounding boxes of text, UI panels)
4. Cross-reference with the transcript -- if the speaker says "look at these benchmarks", find the timestamp, inspect the frame, and crop the screen region to show the benchmark chart

### Scene-by-Scene Screen Content Map (from OCR + scene_map analysis)

| Time Range | Speaker Topic | Screen Content | Recommended Screen Crop |
|------------|---------------|----------------|------------------------|
| 0-28s | Introduction, "built ClipCannon" | Desktop/IDE | Full screen or face-only |
| 28-53s | "Took this intro video" | File browser, video files (docs2 folder) | source_x=200, source_y=100, source_w=2400, source_h=1200 |
| 39-44s | Showing the video file | Video player with ocrprovenance.com | source_x=400, source_y=200, source_w=2000, source_h=1100 |
| 53-70s | "Removed audio, added voice" | Code editor (01_system_overview.md) | source_x=100, source_y=80, source_w=2600, source_h=1400 |
| 70-85s | "Compare my voice" | VLC video player | source_x=300, source_y=150, source_w=2200, source_h=1200 |
| 85-92s | "Setting up lip sync" | Terminal/IDE | source_x=100, source_y=80, source_w=2600, source_h=1400 |
| 92-130s | Avatar setup, webcam capture | Terminal with code output | source_x=100, source_y=80, source_w=2600, source_h=1400 |
| 130-156s | Voice clone demo playing | Video player (0:00/0:14 visible) | source_x=300, source_y=200, source_w=2400, source_h=1300 |
| 157-163s | "Comparison to rest of world" | Benchmark text (0.9893 visible) | source_x=200, source_y=100, source_w=2500, source_h=1400 |
| 163-306s | Benchmarks, philosophy, industry claims | Benchmark comparison chart | source_x=100, source_y=80, source_w=2600, source_h=1400 |
| 307-336s | "Secret about benchmarks" | Benchmark data (85.6% visible) | source_x=200, source_y=100, source_w=2400, source_h=1300 |
| 336-407s | Methodology, competitor comparison | Benchmark chart (85.6%, VALL-E) | source_x=100, source_y=80, source_w=2600, source_h=1400 |
| 407-454s | "VALL-E 2 (Microsoft)" comparison | Comparison chart (VALL-E 2 visible) | source_x=200, source_y=100, source_w=2500, source_h=1400 |
| 454-477s | "Hello Ann" demo video plays | VLC playing hello_anne.mp4 | source_x=300, source_y=200, source_w=2200, source_h=1200 |

**USE `get_frame` TO VERIFY EVERY SCREEN CROP BEFORE FINALIZING.** Do NOT guess. Inspect the actual frame at the midpoint of each segment and adjust coordinates to center on the most relevant content.

---

## COMPLETE OVERLAY TIMELINE

Execute each overlay via `clipcannon_add_overlay()` AFTER creating the edit.

| # | Type | Start ms | End ms | Text | Font Size | Color | BG Opacity | Animation | Duration ms |
|---|------|----------|--------|------|-----------|-------|------------|-----------|-------------|
| 1 | title_card | 500 | 4500 | I CLONED ANY VOICE WITH 98.9% ACCURACY | 48 | #FFFFFF | 0.7 | slide_up | 4000 |
| 2 | title_card | 11000 | 13500 | CLONE MYSELF | 64 | #FF0050 | 0.6 | slide_up | 2500 |
| 3 | title_card | 16000 | 19000 | BUILT IN 2 DAYS | 52 | #00FF88 | 0.5 | fade_in | 3000 |
| 4 | lower_third | 30000 | 35000 | LIVE DEMO: Voice Clone Process | 32 | #FFFFFF | 0.6 | slide_up | 5000 |
| 5 | title_card | 58000 | 62000 | STEP 1: Replace Audio with AI Voice | 36 | #FFFFFF | 0.5 | fade_in | 4000 |
| 6 | title_card | 72000 | 76000 | CAN YOU TELL THE DIFFERENCE? | 48 | #FFD700 | 0.6 | slide_up | 4000 |
| 7 | title_card | 106000 | 109500 | JUST PROMPT THE AI. THAT'S IT. | 44 | #FF0050 | 0.6 | slide_up | 3500 |
| 8 | title_card | 110000 | 114000 | CLONE ANYBODY. PERFECTLY. | 56 | #FFFFFF | 0.6 | slide_up | 4000 |
| 9 | title_card | 125000 | 129000 | VOICE FINGERPRINTING + SECS | 40 | #00CCFF | 0.5 | fade_in | 4000 |
| 10 | title_card | 140000 | 143000 | GG. CLONE COMPLETE. | 56 | #00FF88 | 0.6 | slide_up | 3000 |
| 11 | title_card | 149000 | 154000 | AI-GENERATED VOICE DEMO | 32 | #FFD700 | 0.5 | fade_in | 5000 |
| 12 | title_card | 164000 | 168000 | DESTROYED ENTIRE INDUSTRIES | 52 | #FF0050 | 0.6 | slide_up | 4000 |
| 13 | title_card | 175000 | 178500 | HOW IS HE DOING IT? | 48 | #FFD700 | 0.5 | slide_up | 3500 |
| 14 | title_card | 192000 | 197000 | YOU DON'T NEED TO KNOW HOW | 44 | #FFFFFF | 0.5 | fade_in | 5000 |
| 15 | title_card | 195000 | 200000 | YOU NEED TO KNOW WHAT AI NEEDS | 36 | #00FF88 | 0.5 | fade_in | 5000 |
| 16 | title_card | 214000 | 219000 | 98.9% ACCURACY | 72 | #00FF88 | 0.6 | slide_up | 5000 |
| 17 | title_card | 219000 | 223000 | CLOSEST COMPETITOR: 10% LESS | 36 | #FF4444 | 0.5 | fade_in | 4000 |
| 18 | title_card | 235000 | 240000 | FIRST NATURAL-SOUNDING VOICE CLONE | 40 | #FFD700 | 0.5 | slide_up | 5000 |
| 19 | title_card | 245000 | 249000 | BUILT IN 2 DAYS AS A SIDE FEATURE | 36 | #00CCFF | 0.5 | fade_in | 4000 |
| 20 | title_card | 260000 | 264000 | 4-HOUR LIVESTREAM (ONLY 300 VIEWS) | 36 | #FF0050 | 0.5 | slide_up | 4000 |
| 21 | title_card | 268000 | 272000 | ALL THE SECRETS ARE IN THERE | 44 | #FFD700 | 0.5 | fade_in | 4000 |
| 22 | lower_third | 278000 | 282000 | Voice Fingerprinting via Embedders | 32 | #FFFFFF | 0.5 | slide_up | 4000 |
| 23 | title_card | 296000 | 300000 | BEYOND ANYTHING HUMANS CAN DETECT | 44 | #FF0050 | 0.6 | slide_up | 4000 |
| 24 | title_card | 310000 | 314000 | A SECRET ABOUT THESE BENCHMARKS... | 44 | #FFD700 | 0.5 | fade_in | 4000 |
| 25 | title_card | 327000 | 330000 | MY TEST IS HARDER | 52 | #FF0050 | 0.6 | slide_up | 3000 |
| 26 | title_card | 335000 | 339000 | NOVEL WORDS = HARDER TEST | 36 | #00CCFF | 0.5 | fade_in | 4000 |
| 27 | title_card | 345000 | 348000 | ZERO DATA OVERLAP | 40 | #00FF88 | 0.5 | slide_up | 3000 |
| 28 | title_card | 355000 | 359000 | MAKE AI SAY ANYTHING | 44 | #FFD700 | 0.5 | slide_up | 4000 |
| 29 | title_card | 386000 | 391000 | 2 DAYS TO DUMPSTER YOUR INDUSTRY | 52 | #FF0050 | 0.7 | slide_up | 5000 |
| 30 | lower_third | 405000 | 410000 | vs VALL-E 2 (Microsoft) | 32 | #FF4444 | 0.5 | slide_up | 5000 |
| 31 | title_card | 412000 | 416000 | REAL VOICE, NOT SYNTHETIC | 40 | #00FF88 | 0.5 | fade_in | 4000 |
| 32 | title_card | 430000 | 435000 | MAKE PEOPLE SAY THINGS THEY'VE NEVER SAID | 44 | #FFFFFF | 0.6 | slide_up | 5000 |
| 33 | title_card | 435000 | 439000 | NO OTHER AI CAN DO THIS | 40 | #FF0050 | 0.6 | fade_in | 4000 |
| 34 | title_card | 440000 | 446000 | 98.9% SECS ACCURACY | 72 | #00FF88 | 0.7 | slide_up | 6000 |
| 35 | title_card | 446000 | 451000 | INDISTINGUISHABLE BY HUMANS | 40 | #FFD700 | 0.5 | fade_in | 5000 |
| 36 | title_card | 455000 | 459000 | FINAL DEMO: AI-GENERATED VOICE | 40 | #FFD700 | 0.5 | slide_up | 4000 |
| 37 | title_card | 460000 | 465000 | WORDS HE NEVER SAID IN TRAINING | 32 | #00CCFF | 0.5 | fade_in | 5000 |
| 38 | cta | 470000 | 476961 | FOLLOW FOR MORE AI BUILDS | 48 | #FF0050 | 0.7 | fade_in | 6961 |
| 39 | cta | 472000 | 476961 | SEND THIS TO SOMEONE BUILDING WITH AI | 32 | #FFFFFF | 0.5 | fade_in | 4961 |

**Total overlays: 39** (28 title cards + 3 lower thirds + 2 CTAs + 6 combined stat pops)

---

## COMPLETE SOUND EFFECTS TIMELINE

Generate each SFX via `clipcannon_generate_sfx()`, then reference in the edit's audio spec.

| # | Type | Timestamp ms | Duration ms | Purpose |
|---|------|-------------|-------------|---------|
| 1 | impact | 0 | 500 | Opening attention grab |
| 2 | whoosh | 500 | 400 | Title card entrance |
| 3 | impact | 11000 | 500 | "CLONE" word hit |
| 4 | whoosh | 14760 | 400 | Layout switch to B |
| 5 | chime | 16000 | 600 | "2 days" stat pop |
| 6 | riser | 25180 | 2500 | Tension before demo |
| 7 | whoosh | 28020 | 400 | Layout switch to C |
| 8 | tick | 35000 | 200 | File click |
| 9 | tick | 39000 | 200 | Navigation click |
| 10 | whoosh | 53780 | 400 | Layout switch to A |
| 11 | whoosh | 69680 | 400 | Layout switch to B |
| 12 | chime | 82000 | 600 | "How beautiful" |
| 13 | whoosh | 92630 | 400 | Layout switch to C |
| 14 | impact | 106000 | 500 | Bold claim |
| 15 | whoosh | 109540 | 400 | Layout switch to D |
| 16 | bass_drop | 110000 | 800 | "Clone anybody" drama |
| 17 | whoosh | 122700 | 400 | Layout switch to B |
| 18 | chime | 125000 | 600 | Tech term intro |
| 19 | impact | 140000 | 500 | "GG Clone Complete" |
| 20 | shimmer | 143000 | 1500 | Demo plays |
| 21 | chime | 154000 | 600 | "Beautiful" |
| 22 | whoosh | 157320 | 400 | Layout switch |
| 23 | bass_drop | 164000 | 800 | "Destroyed industries" |
| 24 | impact | 175000 | 500 | "How is he doing it" |
| 25 | chime | 192000 | 600 | Philosophy moment |
| 26 | whoosh | 201140 | 400 | Layout switch |
| 27 | impact | 214000 | 500 | 98.9% reveal |
| 28 | bass_drop | 219000 | 800 | Competitor comparison |
| 29 | whoosh | 223620 | 400 | Layout switch |
| 30 | chime | 235000 | 600 | "First natural" |
| 31 | impact | 245000 | 500 | "Side feature" |
| 32 | whoosh | 258410 | 400 | Layout switch |
| 33 | impact | 268000 | 500 | "Secrets" |
| 34 | whoosh | 275780 | 400 | Layout switch |
| 35 | whoosh | 293440 | 400 | Layout switch |
| 36 | bass_drop | 296000 | 800 | "Beyond human" |
| 37 | whoosh | 307900 | 400 | Layout switch |
| 38 | riser | 310000 | 3000 | Building to secret |
| 39 | whoosh | 315320 | 400 | Layout switch |
| 40 | impact | 327000 | 500 | "Harder" |
| 41 | whoosh | 330330 | 400 | Layout switch |
| 42 | chime | 335000 | 600 | "Novel words" |
| 43 | impact | 345000 | 500 | "Zero overlap" |
| 44 | whoosh | 349920 | 400 | Layout switch |
| 45 | chime | 355000 | 600 | "Say anything" |
| 46 | whoosh | 372480 | 400 | Layout switch |
| 47 | bass_drop | 386000 | 800 | "DUMPSTER" -- loudest SFX |
| 48 | impact | 392000 | 500 | Follow-up hit |
| 49 | whoosh | 398520 | 400 | Layout switch |
| 50 | chime | 412000 | 600 | "Real voice" |
| 51 | whoosh | 420890 | 400 | Layout switch |
| 52 | impact | 430000 | 500 | "Say things never said" |
| 53 | bass_drop | 435000 | 800 | "No other AI" |
| 54 | whoosh | 439000 | 400 | Layout switch |
| 55 | impact | 440000 | 500 | Final 98.9% |
| 56 | shimmer | 446000 | 2000 | Achievement/success |
| 57 | whoosh | 454450 | 400 | Final layout switch |
| 58 | shimmer | 455000 | 2000 | Demo starts |
| 59 | stinger | 470000 | 1000 | CTA drop |

**Total SFX: 59 sound effects across the 7:57 video**

SFX volume: All SFX at -18dB (subtle, enhancing, not distracting). Generate unique file per SFX type (reuse type files where possible).

---

## BACKGROUND MUSIC

Generate via `clipcannon_compose_midi()`:

```
clipcannon_compose_midi(
  project_id = "proj_ace4bcb3",
  edit_id = "<edit_id from create_edit>",
  preset = "corporate",
  duration_s = 480,
  tempo_bpm = 100,
  key = "C"
)
```

- **Preset**: `corporate` -- professional, tech-demo appropriate
- **Volume**: -22dB (very subtle, under speech)
- **Ducking**: enabled, duck under speech by -6dB
- Music should feel like a tech keynote underscore -- present but never competing with voice

---

## COLOR GRADING

### Global Color (apply first)
```
clipcannon_color_adjust(
  project_id = "proj_ace4bcb3",
  edit_id = "<edit_id>",
  brightness = 0.02,
  contrast = 1.15,
  saturation = 1.05,
  gamma = 1.0
)
```

### Per-Segment Color Overrides (apply after global)

| Segments | Mood | Brightness | Contrast | Saturation | Reason |
|----------|------|------------|----------|------------|--------|
| 1-3 | Hook energy | 0.05 | 1.15 | 1.1 | Pop the face, warm feel |
| 10, 13, 22 | Bold claims | 0.02 | 1.25-1.35 | 1.2-1.25 | Peak visual intensity |
| 12, 26 | Demo playback | 0.05 | 1.15 | 1.1 | Clean, let demo shine |
| 14 | Philosophy | 0.02 | 1.15 | 1.1 | Warm, personal |
| 17c, 18 | Dramatic | -0.02 | 1.2 | 1.0 | Slightly dark, intimate |
| 15, 25 | Benchmark data | 0.0 | 1.2 | 1.1 | Sharp, crisp for numbers |

---

## AUDIO CLEANUP (Source Audio)

Run before rendering:
```
clipcannon_audio_cleanup(
  project_id = "proj_ace4bcb3",
  edit_id = "<edit_id>",
  operations = ["noise_reduction", "normalize"]
)
```

This cleans up the screen recording audio (removes background hum, normalizes volume).

---

## RENDERING

```
clipcannon_render(
  project_id = "proj_ace4bcb3",
  edit_id = "<edit_id>"
)
```

The edit was created with `target_platform = "tiktok"`, so it will automatically use:
- Profile: `tiktok_vertical`
- Resolution: 1080x1920
- FPS: 30
- Codec: h264_nvenc (GPU) or libx264 (fallback)
- Bitrate: 8M
- Audio: AAC 128k

---

## POST-RENDER QUALITY ASSURANCE

### Step 1: Inspect the render
```
clipcannon_inspect_render(
  project_id = "proj_ace4bcb3",
  render_id = "<render_id>"
)
```

This extracts frames at 0%, 25%, 50%, 75%, 100% and runs quality checks.

### Step 2: Verify key frames

Check these specific timestamps to ensure correct layout and overlay placement:

| Timestamp | What to Verify |
|-----------|---------------|
| 1000ms | Face fills screen, hook title card visible |
| 11000ms | "CLONE MYSELF" overlay in red |
| 28500ms | Layout switched to PIP, screen dominant |
| 72000ms | "CAN YOU TELL THE DIFFERENCE?" overlay |
| 110000ms | Face fills screen, "CLONE ANYBODY" overlay |
| 140000ms | "GG CLONE COMPLETE" in green |
| 214000ms | "98.9% ACCURACY" in large green text |
| 386000ms | "2 DAYS TO DUMPSTER YOUR INDUSTRY" in red |
| 440000ms | Final "98.9% SECS ACCURACY" overlay |
| 470000ms | CTA overlays visible |

```
# For each timestamp:
clipcannon_get_frame(
  project_id = "proj_ace4bcb3",
  render_id = "<render_id>",
  timestamp_ms = <timestamp>
)
```

### Step 3: Preview first 5 seconds
```
clipcannon_preview_clip(
  project_id = "proj_ace4bcb3",
  start_ms = 0,
  duration_ms = 5000
)
```

Verify: Face fills screen, impact SFX audible, title card slides up at 500ms, zoom effect active.

---

## EXECUTION CHECKLIST

Run these steps IN ORDER. Do not skip any step.

- [ ] 1. `clipcannon_project_open(project_id="proj_ace4bcb3")` -- Verify project is ready
- [ ] 2. `clipcannon_get_scene_map(project_id="proj_ace4bcb3", detail="full", start_ms=0)` -- Get scene data for screen crop coordinates
- [ ] 3. `clipcannon_get_scene_map(project_id="proj_ace4bcb3", detail="full", start_ms=300000)` -- Get remaining scenes
- [ ] 4. `clipcannon_get_frame(...)` -- Inspect frames at key timestamps to verify screen content positions
- [ ] 5. `clipcannon_create_edit(...)` -- Create the edit with ALL 26+ segments from Parts 2 & 3
- [ ] 6. `clipcannon_add_overlay(...)` x 39 -- Add all overlays from the timeline above
- [ ] 7. `clipcannon_add_motion(...)` -- Add motion effects to segments 1, 3, 5, 10, 13, 14, 17a, 17c, 18, 22, 24
- [ ] 8. `clipcannon_color_adjust(...)` -- Apply global color, then per-segment overrides
- [ ] 9. `clipcannon_generate_sfx(...)` -- Generate SFX files (7 types: impact, whoosh, chime, riser, bass_drop, shimmer, tick, stinger)
- [ ] 10. `clipcannon_compose_midi(...)` -- Generate background music
- [ ] 11. `clipcannon_audio_cleanup(...)` -- Clean source audio
- [ ] 12. `clipcannon_preview_layout(...)` -- Preview layout at 3 key timestamps
- [ ] 13. `clipcannon_preview_clip(...)` -- Preview first 5 seconds
- [ ] 14. `clipcannon_render(...)` -- Final render (2 credits)
- [ ] 15. `clipcannon_inspect_render(...)` -- Quality check
- [ ] 16. `clipcannon_get_frame(render_id=...)` -- Verify 10 key frames

---

## FINAL NOTES FOR THE AI AGENT

1. **The source video is already ingested.** Do NOT run `clipcannon_ingest` again.
2. **All 22 pipeline stages passed.** Transcript, scenes, embeddings, OCR -- everything is in the database.
3. **Use `get_frame` liberally.** Before finalizing any screen crop coordinates, inspect the actual frame to verify the content is what the speaker is discussing.
4. **The webcam is at (2712, 1448, 840, 711).** This is consistent across the entire video. The face crop should always reference this region (with some padding for cover fit).
5. **Overlays must NOT overlap the caption safe zone.** Captions are at the bottom. Place title_cards and overlays in the upper-middle area of the screen.
6. **SFX volume is -18dB.** They should enhance, not distract. The speaker's voice is the primary audio.
7. **Background music at -22dB with ducking.** Barely audible. Just enough to fill silence gaps.
8. **This is a 7:57 video for TikTok.** That's long for the platform. Every retention technique matters. The overlays, layout switches, SFX, and zoom effects exist to fight the retention curve.
9. **The viewer intent**: Someone scrolling TikTok sees a bold claim about AI voice cloning. They stay because the demos are compelling and the bold claims create curiosity. They share because the benchmarks are impressive and the "2 days to dumpster your industry" energy is entertaining.
10. **Profit maximization**: This video drives traffic to the 4-hour livestream (mentioned in the video). The CTA should drive follows and shares. The educational value positions the creator as an authority in AI development.
