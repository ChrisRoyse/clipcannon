# ClipCannon TikTok Conversion Prompt -- Part 2: Segments with Screen Tracking (0:00 - 5:10)

## CONTEXT FOR THE AI AGENT

You are working in `/home/cabdru/clipcannon/`. The ClipCannon MCP server exposes tools prefixed `clipcannon_`. The source video is already ingested into project `proj_ace4bcb3` at `~/.clipcannon/projects/proj_ace4bcb3/`. All 22 pipeline stages passed. The analysis database with transcript, scenes, OCR, embeddings is at `~/.clipcannon/projects/proj_ace4bcb3/analysis.db`.

**Source**: `03262026voiceclonevideo.mp4` -- 3840x2160, 60fps, 476,961ms (7:57), screen recording with webcam at bottom-right (x=2712, y=1448, w=840, h=711).

**What you are building**: A TikTok 9:16 (1080x1920) version of this video. ZERO CUTS -- every second stays. Enhanced with dynamic layouts, overlays, SFX, music, color grading.

---

## THE ABSOLUTE #1 RULE: SCREEN TRACKING

**Every segment of this video follows one unbreakable law: the bottom 70% of the output frame (1344px of 1920px) MUST display exactly what the speaker is currently talking about. The top 30% (576px) shows the speaker's face extracted from the webcam overlay. This is Layout A (30/70 split) and it is the DEFAULT for the entire video.**

This means:
- When the speaker says "look at these benchmarks" -- the bottom 70% shows the benchmark chart
- When the speaker says "I took this intro video" -- the bottom 70% shows the file browser with the video file
- When the speaker says "I removed the audio" -- the bottom 70% shows the video editor/player
- When the speaker says "clone anybody" with NO screen reference -- STILL show the screen, because his code/terminal IS his work and contextualizes every word

**To get the screen crop right, the AI agent MUST**:
1. Call `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=MIDPOINT_OF_SEGMENT)` to SEE what's on screen
2. Call `clipcannon_analyze_frame(project_id="proj_ace4bcb3", timestamp_ms=MIDPOINT_OF_SEGMENT)` to get bounding boxes
3. Adjust the screen region `source_x`, `source_y`, `source_width`, `source_height` to crop to the RELEVANT content area, removing browser chrome, taskbar, and the webcam overlay area
4. NEVER guess. Always inspect. If the screen content is different from what this prompt says, trust what you SEE in the frame.

**The webcam overlay at (2712, 1448, 840, 711) must be cropped OUT of the screen region.** The face is already shown in the top 30%. Showing it again in the bottom 70% creates a distracting duplicate. Set `source_width` to end before x=2700 or mask the region.

---

## FACE REGION (TOP 30%) -- CONSTANT FOR ALL LAYOUT A SEGMENTS

This stays the same for every segment using Layout A:

```json
{
  "region_id": "speaker_top",
  "source_x": 2612, "source_y": 1348,
  "source_width": 940, "source_height": 811,
  "output_x": 0, "output_y": 0,
  "output_width": 1080, "output_height": 576,
  "z_index": 2, "fit_mode": "cover"
}
```

This extracts the webcam region with slight padding and scales it to fill the top 30% of the 1080x1920 canvas.

---

## SEGMENT-BY-SEGMENT BREAKDOWN (0:00 - 5:10)

Every segment below follows this structure:
1. **WHAT THE SPEAKER SAYS** -- exact transcript
2. **WHAT THE SPEAKER IS REFERRING TO** -- the topic/content they're describing
3. **WHAT IS ON THE SOURCE SCREEN** -- from OCR/scene_map analysis
4. **SCREEN CROP INSTRUCTION** -- exactly what the bottom 70% must show and the source coordinates
5. **VERIFY COMMAND** -- the exact `get_frame` call to confirm before finalizing
6. **CANVAS SPEC** -- the full JSON
7. **EFFECTS** -- overlays, SFX, motion, color

---

### Segment 1 (0 - 6160ms) -- THE HOOK

**WHAT THE SPEAKER SAYS**: "Over the past few days, originally I built Clip Cannon and I was using it to edit my videos."

**WHAT THE SPEAKER IS REFERRING TO**: Introducing himself and his project. This is a direct-to-camera address. He's establishing credibility. There is no specific screen content being referenced yet.

**WHAT IS ON THE SOURCE SCREEN**: General desktop/IDE. Scene_map shows no significant OCR text. The speaker is looking at camera and talking generally.

**SCREEN CROP INSTRUCTION**: This is the ONE exception where Layout D (full-screen face) is justified. The speaker is making direct eye contact with zero screen references. Full-face close-up creates the "cocktail party effect" hook that Hormozi says drives 80% of retention decisions.

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=3000)` -- confirm screen shows generic desktop with no specific content being discussed.

**LAYOUT**: D (Full-Screen Face) -- ONLY for the hook. Returns to Layout A immediately after.

```json
{
  "source_start_ms": 0, "source_end_ms": 6160, "speed": 1.0,
  "canvas": {
    "enabled": true, "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "face_full",
        "source_x": 2412, "source_y": 1148,
        "source_width": 1200, "source_height": 1012,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 1920,
        "z_index": 1, "fit_mode": "cover"
      }
    ]
  }
}
```

**OVERLAY**: Title card at 500ms: "I CLONED ANY VOICE WITH 98.9% ACCURACY" -- `slide_up`, 48px, #FFFFFF, bg_opacity=0.7, 4000ms
**SFX**: `impact` at 0ms, `whoosh` at 500ms
**MOTION**: `zoom_in` 1.0->1.15, ease_in_out
**COLOR**: brightness=0.05, contrast=1.15, saturation=1.1

---

### Segment 2 (6360 - 9720ms) -- "Create Videos"

**WHAT THE SPEAKER SAYS**: "And then I wanted to use Clip Cannon to create videos."

**WHAT THE SPEAKER IS REFERRING TO**: Still direct address, pivoting from "edit" to "create." The key word "create" signals the shift. No specific screen content referenced.

**WHAT IS ON THE SOURCE SCREEN**: Same general desktop/IDE as segment 1.

**SCREEN CROP INSTRUCTION**: Transition to Layout A NOW. Even though he's not pointing at specific screen content, the screen shows his development environment (the IDE/terminal where ClipCannon lives). This contextualizes him as a builder. The bottom 70% shows his workspace. Crop to the main IDE/terminal area, excluding browser chrome and taskbar.

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=8000)` -- confirm screen shows IDE/workspace.

**LAYOUT**: A (30/70 Split) -- DEFAULT from here forward.

```json
{
  "source_start_ms": 6360, "source_end_ms": 9720, "speed": 1.0,
  "canvas": {
    "enabled": true, "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "speaker_top",
        "source_x": 2612, "source_y": 1348,
        "source_width": 940, "source_height": 811,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 576,
        "z_index": 2, "fit_mode": "cover"
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

**SFX**: `whoosh` at 6360ms (transition from D to A)
**COLOR**: brightness=0.02, contrast=1.15, saturation=1.05

---

### Segment 3 (9800 - 13700ms) -- "Clone Myself" (OPEN LOOP)

**WHAT THE SPEAKER SAYS**: "So in order to do that, I needed to be able to clone myself."

**WHAT THE SPEAKER IS REFERRING TO**: The problem statement -- he needs to clone his own voice to generate videos autonomously.

**WHAT IS ON THE SOURCE SCREEN**: Still his workspace/IDE environment.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% shows workspace. Same crop as Segment 2. The screen hasn't changed.

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=11500)` -- confirm same workspace view.

**LAYOUT**: A (30/70 Split)

```json
{
  "source_start_ms": 9800, "source_end_ms": 13700, "speed": 1.0,
  "canvas": {
    "enabled": true, "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "speaker_top",
        "source_x": 2612, "source_y": 1348,
        "source_width": 940, "source_height": 811,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 576,
        "z_index": 2, "fit_mode": "cover"
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

**OVERLAY**: Title card at 11000ms: "CLONE MYSELF" -- `slide_up`, 64px, #FF0050, 2500ms
**SFX**: `impact` at 11000ms
**MOTION**: `zoom_in` 1.0->1.2, ease_in (on face region only)

---

### Segment 4 (14760 - 24740ms) -- "Qwen3 TTS Model, Two Days"

**WHAT THE SPEAKER SAYS**: "And to clone myself, I've been fine tuning and honing a system over the past two days, the Quinn 3 TTS model."

**WHAT THE SPEAKER IS REFERRING TO**: The specific AI model he used (Qwen3-TTS) and the timeframe (2 days).

**WHAT IS ON THE SOURCE SCREEN**: His development workspace/IDE. He may be looking at code or terminal output related to TTS fine-tuning.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% shows workspace. The speaker is describing technical work -- the screen shows his development environment which IS the context. Crop to main code/terminal area.

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=20000)` -- see what's on screen (likely terminal or code editor).

**LAYOUT**: A (30/70 Split)

```json
{
  "source_start_ms": 14760, "source_end_ms": 24740, "speed": 1.0,
  "canvas": {
    "enabled": true, "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "speaker_top",
        "source_x": 2612, "source_y": 1348,
        "source_width": 940, "source_height": 811,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 576,
        "z_index": 2, "fit_mode": "cover"
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

**OVERLAY**: Title card at 16000ms: "BUILT IN 2 DAYS" -- `fade_in`, 52px, #00FF88, 3000ms
**SFX**: `chime` at 16000ms

---

### Segment 5 (25180 - 28020ms) -- "Show You"

**WHAT THE SPEAKER SAYS**: "And I'm going to show you a picture of the video."

**WHAT THE SPEAKER IS REFERRING TO**: He's about to navigate to show the video file. Anticipation moment.

**WHAT IS ON THE SOURCE SCREEN**: He's about to navigate to the file browser. Screen may be transitioning.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% shows whatever is on screen -- he's about to click into the file browser. Keep the same full-workspace crop.

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=26500)`

**LAYOUT**: A (30/70 Split)

Same canvas spec as Segment 4.

**SFX**: `riser` at 25180ms (2500ms duration, building tension)

---

### Segment 6 (28020 - 38000ms) -- File Browser Navigation

**WHAT THE SPEAKER SAYS**: "so here's what I did let's show you so I took this intro video right here okay"

**WHAT THE SPEAKER IS REFERRING TO**: He's NAVIGATING his file browser to show the intro video file. He's pointing at and clicking on files. The screen IS what he's talking about.

**WHAT IS ON THE SOURCE SCREEN** (from OCR/scene_map): Scene shows "docs2" folder, then "03202026introvide01min.mp4" file. This is the video file he used as the base for the voice clone.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% MUST show the file browser. The speaker is DIRECTLY REFERENCING files on screen. The file names are visible via OCR. Crop to show the file browser area clearly, zooming in enough that file names are readable at 1080px width.

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=33000)` -- MUST show file browser with "docs2" or "03202026introvide01min.mp4" visible.

**SPECIFIC SCREEN CROP**: The file browser is likely in the center-left of the screen. Crop tighter than full-screen to make file names readable:

```json
{
  "source_start_ms": 28020, "source_end_ms": 38000, "speed": 1.0,
  "canvas": {
    "enabled": true, "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "speaker_top",
        "source_x": 2612, "source_y": 1348,
        "source_width": 940, "source_height": 811,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 576,
        "z_index": 2, "fit_mode": "cover"
      },
      {
        "region_id": "screen_bottom_file_browser",
        "source_x": 100, "source_y": 100,
        "source_width": 2500, "source_height": 1300,
        "output_x": 0, "output_y": 576,
        "output_width": 1080, "output_height": 1344,
        "z_index": 1, "fit_mode": "contain"
      }
    ]
  }
}
```

**OVERLAY**: Lower third at 30000ms: "LIVE DEMO: Voice Clone Process" -- `slide_up`, 32px, 5000ms
**SFX**: `whoosh` at 28020ms, `tick` at 35000ms (file click)

---

### Segment 7 (38000 - 45500ms) -- Showing the Intro Video (ocrprovenance.com)

**WHAT THE SPEAKER SAYS**: (continuing) "...and then..."

**WHAT THE SPEAKER IS REFERRING TO**: He has opened the intro video or is showing the ocrprovenance.com website in the video.

**WHAT IS ON THE SOURCE SCREEN** (OCR): "ocrprovenance.com" -- a website is visible. This is the content of the intro video he's showing.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% MUST show the ocrprovenance.com website/video. This is what he's demonstrating. Crop to center on the video player or website content area.

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=41000)` -- MUST show ocrprovenance.com content.

```json
{
  "source_start_ms": 38000, "source_end_ms": 45500, "speed": 1.0,
  "canvas": {
    "enabled": true, "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "speaker_top",
        "source_x": 2612, "source_y": 1348,
        "source_width": 940, "source_height": 811,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 576,
        "z_index": 2, "fit_mode": "cover"
      },
      {
        "region_id": "screen_bottom_website",
        "source_x": 200, "source_y": 100,
        "source_width": 2400, "source_height": 1300,
        "output_x": 0, "output_y": 576,
        "output_width": 1080, "output_height": 1344,
        "z_index": 1, "fit_mode": "contain"
      }
    ]
  }
}
```

**SFX**: `tick` at 39000ms (navigation click)

---

### Segment 8 (45500 - 53240ms) -- Navigating / Showing Video Player

**WHAT THE SPEAKER SAYS**: (continuing navigation)

**WHAT THE SPEAKER IS REFERRING TO**: Still demonstrating the video he made. He's navigating through the screen.

**WHAT IS ON THE SOURCE SCREEN**: Scene transitions through various views. May show video player interface.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% tracks whatever the speaker is looking at. Use the same general workspace crop since the content is shifting.

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=49000)` -- check what's on screen.

Same canvas spec as Segment 6 (general workspace crop).

---

### Segment 9 (53780 - 69680ms) -- "Removed Audio, Added Voice, OCR Providence"

**WHAT THE SPEAKER SAYS**: "then I removed all of the audio and then I added my voice into the video and what I said is OCR Providence MCP server is the best AI memory system in existence now that's exactly what I say in this video"

**WHAT THE SPEAKER IS REFERRING TO**: He's explaining the voice replacement process. He removed audio from the intro video and replaced it with AI-generated voice. He's showing the result on screen.

**WHAT IS ON THE SOURCE SCREEN** (OCR): "01_system_overview.md" -- a code/documentation editor is visible. He may also be showing the video player with the modified audio.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% MUST show the code editor or video player that demonstrates the voice replacement. The speaker is walking through his process step by step. Every frame of the bottom 70% must show the tool/interface he's currently describing. If the content shifts mid-segment (from code editor to video player), split into sub-segments with different screen crops.

**VERIFY**:
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=57000)` -- check if code editor visible
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=64000)` -- check if video player visible
If these show DIFFERENT content, SPLIT this into two sub-segments with different screen crops.

```json
{
  "source_start_ms": 53780, "source_end_ms": 69680, "speed": 1.0,
  "canvas": {
    "enabled": true, "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "speaker_top",
        "source_x": 2612, "source_y": 1348,
        "source_width": 940, "source_height": 811,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 576,
        "z_index": 2, "fit_mode": "cover"
      },
      {
        "region_id": "screen_bottom_editor",
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

**OVERLAY**: Title card at 58000ms: "STEP 1: Replace Audio with AI Voice" -- `fade_in`, 36px, #FFFFFF, bg_opacity=0.5, 4000ms
**SFX**: `whoosh` at 53780ms

---

### Segment 10 (69680 - 91790ms) -- "Compare My Voice" + "How Beautiful"

**WHAT THE SPEAKER SAYS**: "so i want you to compare my voice in the video to what i just said ocr providence mcp is the best ai memory system in existence how beautiful was that now i'm setting up lip sync"

**WHAT THE SPEAKER IS REFERRING TO**: He's asking the viewer to compare the AI voice to his real voice. Then he mentions setting up lip sync. He's likely showing a video player playing back the cloned audio.

**WHAT IS ON THE SOURCE SCREEN** (OCR): Scene 20 shows "Sideo Subtite Tools Vew Help" (video player menu bar -- VLC). Scene 21 shows "RER" (possibly terminal). The video player is visible during the comparison moment, then transitions to terminal for the lip sync setup.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% MUST show the video player during the "compare my voice" section (69680-85000ms), then transition to the terminal/code during "setting up lip sync" (85000-91790ms). SPLIT if needed:

#### Sub-segment 10a (69680 - 85000ms) -- Voice comparison, video player visible
**SCREEN SHOWS**: Video player (VLC) playing back the cloned voice demo
**CROP**: Center on video player area

```json
{
  "source_start_ms": 69680, "source_end_ms": 85000, "speed": 1.0,
  "canvas": {
    "enabled": true, "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "speaker_top",
        "source_x": 2612, "source_y": 1348,
        "source_width": 940, "source_height": 811,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 576,
        "z_index": 2, "fit_mode": "cover"
      },
      {
        "region_id": "screen_bottom_player",
        "source_x": 200, "source_y": 80,
        "source_width": 2500, "source_height": 1360,
        "output_x": 0, "output_y": 576,
        "output_width": 1080, "output_height": 1344,
        "z_index": 1, "fit_mode": "contain"
      }
    ]
  }
}
```

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=77000)` -- MUST show video player

#### Sub-segment 10b (85000 - 91790ms) -- Lip sync setup, terminal visible
**SCREEN SHOWS**: Terminal/IDE with lip sync setup code
**CROP**: Center on terminal

```json
{
  "source_start_ms": 85000, "source_end_ms": 91790, "speed": 1.0,
  "canvas": {
    "enabled": true, "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "speaker_top",
        "source_x": 2612, "source_y": 1348,
        "source_width": 940, "source_height": 811,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 576,
        "z_index": 2, "fit_mode": "cover"
      },
      {
        "region_id": "screen_bottom_terminal",
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

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=88000)` -- MUST show terminal

**OVERLAY**: Title card at 72000ms: "CAN YOU TELL THE DIFFERENCE?" -- `slide_up`, 48px, #FFD700, 4000ms
**SFX**: `whoosh` at 69680ms, `chime` at 82000ms

---

### Segment 11 (92630 - 121700ms) -- Avatar Setup + "Clone Anybody Perfectly"

**WHAT THE SPEAKER SAYS**: "i've got it capturing my webcam being able to generate my own avatar... just need to prompt the ai and that's it i can clone anybody perfectly without you being in a hotel a difference even in the slightest"

**WHAT THE SPEAKER IS REFERRING TO**: He's showing his webcam capture + avatar generation system, then transitions to bold claims about cloning.

**WHAT IS ON THE SOURCE SCREEN** (OCR): Scene 21 shows terminal/code output ("RER"). The screen shows his terminal with avatar/lip-sync code running for the ENTIRE segment from 88s-130s.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% shows the terminal with code output. This is constant for this entire segment -- the terminal output IS the avatar system he's describing. Do NOT switch to face-only even during the bold "clone anybody" claim because the terminal output proves the claim.

**VERIFY**:
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=100000)` -- terminal with code
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=115000)` -- still terminal

```json
{
  "source_start_ms": 92630, "source_end_ms": 121700, "speed": 1.0,
  "canvas": {
    "enabled": true, "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "speaker_top",
        "source_x": 2612, "source_y": 1348,
        "source_width": 940, "source_height": 811,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 576,
        "z_index": 2, "fit_mode": "cover"
      },
      {
        "region_id": "screen_bottom_terminal",
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

**OVERLAY**: Title card at 106000ms: "JUST PROMPT THE AI. THAT'S IT." -- `slide_up`, 44px, #FF0050, 3500ms
**OVERLAY**: Title card at 110000ms: "CLONE ANYBODY. PERFECTLY." -- `slide_up`, 56px, #FFFFFF, 4000ms
**SFX**: `whoosh` at 92630ms, `impact` at 106000ms, `bass_drop` at 110000ms

---

### Segment 12 (122700 - 156630ms) -- Voice Fingerprinting + "GG Clone Complete" Demo

**WHAT THE SPEAKER SAYS**: "voice fingerprinting... SECS system... You just need fingerprints and then combine that with SECS. GG. Clone complete. Jimmy cracked corn on a hill near the avalanche until he was hungry and then he went home. See how beautiful that was?"

**WHAT THE SPEAKER IS REFERRING TO**: He explains voice fingerprinting, then plays the cloned voice demo ("Jimmy cracked corn"). The demo video is playing on screen.

**WHAT IS ON THE SOURCE SCREEN** (OCR): Scene 22 shows "0:00 / 0:14" -- a video player progress bar. A demo video is playing. Then scenes 23-25 show "ocrprovenance.com".

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% shows the video player playing the voice clone demo. THIS IS A REWARD MOMENT -- the proof of the promise. The demo audio is playing and the screen shows the video player with the cloned voice output. The viewer needs to SEE the video player to understand a demo is playing.

**VERIFY**:
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=138000)` -- video player with progress bar visible
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=150000)` -- ocrprovenance.com demo

```json
{
  "source_start_ms": 122700, "source_end_ms": 156630, "speed": 1.0,
  "canvas": {
    "enabled": true, "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "speaker_top",
        "source_x": 2612, "source_y": 1348,
        "source_width": 940, "source_height": 811,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 576,
        "z_index": 2, "fit_mode": "cover"
      },
      {
        "region_id": "screen_bottom_demo_player",
        "source_x": 200, "source_y": 100,
        "source_width": 2500, "source_height": 1350,
        "output_x": 0, "output_y": 576,
        "output_width": 1080, "output_height": 1344,
        "z_index": 1, "fit_mode": "contain"
      }
    ]
  }
}
```

**OVERLAY**: Title card at 125000ms: "VOICE FINGERPRINTING + SECS" -- `fade_in`, 40px, #00CCFF, 4000ms
**OVERLAY**: Title card at 140000ms: "GG. CLONE COMPLETE." -- `slide_up`, 56px, #00FF88, 3000ms
**OVERLAY**: Title card at 149000ms: "AI-GENERATED VOICE DEMO" -- `fade_in`, 32px, #FFD700, 5000ms
**SFX**: `whoosh` at 122700ms, `impact` at 140000ms, `shimmer` at 143000ms, `chime` at 154000ms

---

### Segment 13 (157320 - 200600ms) -- "Destroy Industries" + Philosophy

**WHAT THE SPEAKER SAYS**: "I'm going to show you the comparison of my system to the rest of the world. This is everybody else's system. You see what happens when I start working on something for even just one or two days, I can completely destroy entire industries. And that's because I'm a genie... you don't need to know how to do things. You only need to know what AI needs to do."

**WHAT THE SPEAKER IS REFERRING TO**: He's showing a BENCHMARK COMPARISON on screen. He's comparing his system to competitors. Then he transitions into philosophy about AI-first thinking.

**WHAT IS ON THE SOURCE SCREEN** (OCR): Scene 30-34 shows "Good point - that 0.9893 is the stronger claim since the tar..." -- this is the benchmark comparison text/chart. It stays on screen from ~161s to ~306s.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% MUST show the benchmark comparison text/chart. Even during the "I'm a genie" philosophy section, the benchmark data stays on screen and provides VISUAL PROOF of his claims. Do not switch to face-only. The data validates the bold words.

**VERIFY**:
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=165000)` -- benchmark chart/text
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=180000)` -- STILL benchmark chart
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=195000)` -- STILL on screen

```json
{
  "source_start_ms": 157320, "source_end_ms": 200600, "speed": 1.0,
  "canvas": {
    "enabled": true, "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "speaker_top",
        "source_x": 2612, "source_y": 1348,
        "source_width": 940, "source_height": 811,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 576,
        "z_index": 2, "fit_mode": "cover"
      },
      {
        "region_id": "screen_bottom_benchmarks",
        "source_x": 100, "source_y": 80,
        "source_width": 2600, "source_height": 1360,
        "output_x": 0, "output_y": 576,
        "output_width": 1080, "output_height": 1344,
        "z_index": 1, "fit_mode": "contain"
      }
    ]
  }
}
```

**OVERLAY**: Title card at 164000ms: "DESTROYED ENTIRE INDUSTRIES" -- `slide_up`, 52px, #FF0050, 4000ms
**OVERLAY**: Title card at 175000ms: "HOW IS HE DOING IT?" -- `slide_up`, 48px, #FFD700, 3500ms
**OVERLAY**: Title card at 192000ms: "YOU DON'T NEED TO KNOW HOW" -- `fade_in`, 44px, #FFFFFF, 5000ms
**OVERLAY**: Title card at 195000ms: "YOU NEED TO KNOW WHAT AI NEEDS" -- `fade_in`, 36px, #00FF88, 5000ms
**SFX**: `bass_drop` at 164000ms, `impact` at 175000ms, `chime` at 192000ms
**COLOR**: contrast=1.25, saturation=1.2

---

### Segment 14 (201140 - 258410ms) -- "98.9%" Benchmark + "First Natural Sounding" + Livestream Plug

**WHAT THE SPEAKER SAYS**: "verify and validate the output... look at these benchmarks on voice cloning I hit 98.9%... the closest to this is garbage 10% less accurate... this is the first natural sounding voice clone system in existence... built this in two days as an add-on feature... go watch my four-hour livestream... 300 views and all the secrets are in there"

**WHAT THE SPEAKER IS REFERRING TO**: Still the same benchmark comparison chart. He's reading off the numbers, comparing to competitors, and plugging the livestream. The benchmark chart has been on screen since ~161s.

**WHAT IS ON THE SOURCE SCREEN** (OCR): Same benchmark comparison text/chart. "Good point - that 0.9893 is the stronger claim..." remains visible. This screen content doesn't change.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% CONTINUES to show the benchmark chart. This is a LONG segment (57 seconds) but the screen content is stable. The benchmarks are the PROOF -- they must be visible the entire time the speaker is talking about them.

**VERIFY**:
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=215000)` -- benchmarks
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=240000)` -- still benchmarks
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=255000)` -- still benchmarks

```json
{
  "source_start_ms": 201140, "source_end_ms": 258410, "speed": 1.0,
  "canvas": {
    "enabled": true, "canvas_width": 1080, "canvas_height": 1920,
    "background_color": "#0D0D0D",
    "regions": [
      {
        "region_id": "speaker_top",
        "source_x": 2612, "source_y": 1348,
        "source_width": 940, "source_height": 811,
        "output_x": 0, "output_y": 0,
        "output_width": 1080, "output_height": 576,
        "z_index": 2, "fit_mode": "cover"
      },
      {
        "region_id": "screen_bottom_benchmarks",
        "source_x": 100, "source_y": 80,
        "source_width": 2600, "source_height": 1360,
        "output_x": 0, "output_y": 576,
        "output_width": 1080, "output_height": 1344,
        "z_index": 1, "fit_mode": "contain"
      }
    ]
  }
}
```

**OVERLAY**: Title card at 214000ms: "98.9% ACCURACY" -- `slide_up`, 72px bold, #00FF88, 5000ms
**OVERLAY**: Title card at 219000ms: "CLOSEST COMPETITOR: 10% LESS" -- `fade_in`, 36px, #FF4444, 4000ms
**OVERLAY**: Title card at 235000ms: "FIRST NATURAL-SOUNDING VOICE CLONE" -- `slide_up`, 40px, #FFD700, 5000ms
**OVERLAY**: Title card at 245000ms: "BUILT IN 2 DAYS AS A SIDE FEATURE" -- `fade_in`, 36px, #00CCFF, 4000ms
**OVERLAY**: Title card at 260000ms: "4-HR LIVESTREAM (ONLY 300 VIEWS)" -- `slide_up`, 36px, #FF0050, 4000ms
**SFX**: `impact` at 214000ms, `bass_drop` at 219000ms, `chime` at 235000ms, `impact` at 245000ms, `impact` at 260000ms

---

### Segment 15 (258410 - 305510ms) -- Technical Deep Dive + "Beyond Human Detection"

**WHAT THE SPEAKER SAYS**: "all of the secrets are in there... they don't understand the world is all mathematically calculable through the lens of embedders... voice fingerprint... clone people perfectly... my level of ability to make deep fakes will be beyond anything humans can decipher"

**WHAT THE SPEAKER IS REFERRING TO**: Still benchmark chart context, then transitioning to discussing the technical approach (embedders, fingerprinting).

**WHAT IS ON THE SOURCE SCREEN**: The benchmark comparison is still visible through ~306s. Same screen content.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% still shows the benchmark chart. The speaker is making claims while the data supports them visually. Even the "beyond human detection" claim is backed by the 98.9% number on screen.

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=280000)` -- confirm benchmarks still on screen.

Same canvas spec as Segment 14.

**OVERLAY**: Title card at 268000ms: "ALL THE SECRETS ARE IN THERE" -- `fade_in`, 44px, #FFD700, 4000ms
**OVERLAY**: Lower third at 278000ms: "Voice Fingerprinting via Embedders" -- `slide_up`, 32px, 4000ms
**OVERLAY**: Title card at 296000ms: "BEYOND ANYTHING HUMANS CAN DETECT" -- `slide_up`, 44px, #FF0050, 4000ms
**SFX**: `impact` at 268000ms, `whoosh` at 278000ms, `bass_drop` at 296000ms

---

**CONTINUE TO PART 3 FOR SEGMENTS 16-FINAL (5:10 - 7:57)**
