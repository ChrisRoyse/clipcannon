# ClipCannon TikTok Conversion Prompt -- Part 3: Segments with Screen Tracking (5:10 - 7:57)

## CONTEXT REMINDER

- **Project**: `proj_ace4bcb3` at `~/.clipcannon/projects/proj_ace4bcb3/`
- **Working Directory**: `/home/cabdru/clipcannon/`
- **Source**: 3840x2160, 60fps, 476,961ms. Webcam at (2712, 1448, 840, 711).
- **Target**: 1080x1920 TikTok vertical. ZERO CUTS. ALL content preserved.
- All segments below continue from Part 2. Same `clipcannon_create_edit` call.

## SCREEN TRACKING MANDATE (REPEATED FROM PART 2 -- READ AGAIN)

**Every segment uses Layout A (30/70 split) by default.** Top 30% = speaker face. Bottom 70% = EXACTLY what the speaker is currently talking about.

**For EVERY segment below, the AI agent MUST:**
1. Read the transcript to know what the speaker is discussing
2. Call `get_frame(timestamp_ms=MIDPOINT)` to see what's on the source screen
3. Adjust the screen region coordinates to crop to the relevant content
4. If the screen content changes mid-segment, SPLIT into sub-segments
5. NEVER show screen content that doesn't match what the speaker is saying

**The face region is constant for all Layout A segments:**
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

---

## SEGMENTS (5:10 - 7:57)

### Segment 16 (307900 - 314660ms) -- "A Secret About These Benchmarks"

**WHAT THE SPEAKER SAYS**: "Now, you're looking at these benchmarks. And let me just tell you a little secret about these benchmarks."

**WHAT THE SPEAKER IS REFERRING TO**: He's directing the viewer's attention to the benchmarks on screen. "You're LOOKING at these benchmarks" -- he's explicitly pointing at the screen content. Then he teases a secret.

**WHAT IS ON THE SOURCE SCREEN**: The benchmark comparison chart has been on screen since ~161s. At this timestamp, the screen likely still shows the comparison data or has transitioned slightly. OCR from scene 38 shows no significant text -- he may have scrolled or the screen transitioned.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% MUST show whatever benchmark data is on screen. He's literally saying "you're looking at THESE benchmarks" -- the "these" means the thing on screen RIGHT NOW. Inspect the frame. If the benchmark chart is still visible, keep the same crop. If the screen has changed, adjust the crop to show whatever he's now referring to.

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=311000)` -- what benchmarks are visible? Crop to center on them.

```json
{
  "source_start_ms": 307900, "source_end_ms": 314660, "speed": 1.0,
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

**OVERLAY**: Title card at 310000ms: "A SECRET ABOUT THESE BENCHMARKS..." -- `fade_in`, 44px, #FFD700, 4000ms
**SFX**: `riser` at 310000ms (building tension)
**COLOR**: brightness=-0.02, contrast=1.2

---

### Segment 17 (315320 - 330190ms) -- "My Test Is Harder"

**WHAT THE SPEAKER SAYS**: "This key selling point for this test, every other benchmark scores the AI same text from a data set where the speaker's real version also exists. My test is harder. The reference clip says completely different words."

**WHAT THE SPEAKER IS REFERRING TO**: He's explaining WHY his benchmark methodology is superior. He's comparing his approach to standard academic benchmarks. The screen likely shows benchmark data with competitor scores.

**WHAT IS ON THE SOURCE SCREEN** (OCR): Scene 47 shows "85.6%" -- competitor benchmark scores are visible. This is the comparison data he's referencing when he says "every other benchmark."

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% MUST show the benchmark comparison data with the 85.6% competitor score visible. This is the DATA that proves "my test is harder." The viewer needs to SEE the competitor numbers to understand the comparison.

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=325000)` -- MUST show benchmark data with 85.6% or competitor scores visible. Crop to center on this data.

```json
{
  "source_start_ms": 315320, "source_end_ms": 330190, "speed": 1.0,
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
        "region_id": "screen_bottom_competitor_scores",
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

**OVERLAY**: Title card at 327000ms: "MY TEST IS HARDER" -- `slide_up`, 52px, #FF0050, 3000ms
**SFX**: `impact` at 327000ms

---

### Segment 18 (330330 - 349920ms) -- "Different Words, Zero Data Overlap"

**WHAT THE SPEAKER SAYS**: "the reference clip says completely different words than what was generated the words that jimmy crack corn video said is not in any of my test data anywhere those words do not exist anywhere at all"

**WHAT THE SPEAKER IS REFERRING TO**: He's explaining that his benchmark uses novel content -- the AI generated words it was never trained on. The screen still shows benchmark comparison data.

**WHAT IS ON THE SOURCE SCREEN** (OCR): Scene 48 shows "85.6%" -- same benchmark data screen. He's scrolling through or pointing at specific parts of the comparison.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% MUST show the benchmark comparison. The 85.6% competitor score and the comparison methodology should be visible. He's explaining the methodology column by column.

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=340000)` -- benchmark data still visible.

Same canvas spec as Segment 17.

**OVERLAY**: Title card at 335000ms: "NOVEL WORDS = HARDER TEST" -- `fade_in`, 36px, #00CCFF, 4000ms
**OVERLAY**: Title card at 345000ms: "ZERO DATA OVERLAP" -- `slide_up`, 40px, #00FF88, 3000ms
**SFX**: `chime` at 335000ms, `impact` at 345000ms

---

### Segment 19 (349920 - 372480ms) -- "Hello Ann" Example Setup

**WHAT THE SPEAKER SAYS**: "and i could just be like make another video of me saying hello ann i love the dress you're wearing today look cute that's it right don't have any of me saying that"

**WHAT THE SPEAKER IS REFERRING TO**: He's explaining that the AI can generate speech for any text, even text he never recorded. He's still in the benchmark context but now giving a practical example.

**WHAT IS ON THE SOURCE SCREEN** (OCR): Still the benchmark comparison data. He hasn't navigated away from this screen.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% keeps showing the benchmark data. Even though he's giving a verbal example ("hello ann"), the screen data provides the quantitative context for his claim. The benchmark data IS the proof.

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=360000)` -- benchmark data or code/terminal visible.

Same canvas spec as Segment 17.

**OVERLAY**: Title card at 355000ms: "MAKE AI SAY ANYTHING" -- `slide_up`, 44px, #FFD700, 4000ms
**SFX**: `chime` at 355000ms

---

### Segment 20 (372480 - 396740ms) -- "2 Days to Dumpster Your Entire Industry"

**WHAT THE SPEAKER SAYS**: "all of these other people are copying audio patterns from references and that is a terrible way to do voice you need to do multi and better fingerprinting and build SECS systems idiots took me two days to dumpster your entire industry"

**WHAT THE SPEAKER IS REFERRING TO**: He's attacking competitors' methodology (copying audio patterns vs fingerprinting). Then delivers the boldest claim in the video. The screen still shows benchmark comparison data proving his superiority.

**WHAT IS ON THE SOURCE SCREEN**: Still benchmark data. This is the same screen that's been up since ~161s. The comparison data IS the visual proof of "dumpster your entire industry."

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% MUST show the benchmark comparison. This is the MOST IMPORTANT segment for screen tracking because the bold verbal claim ("dumpster your industry") is backed by the visual data (98.9% vs competitors' lower scores). The viewer sees the words AND the proof simultaneously. This is Hormozi's "visualize data" principle.

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=385000)` -- benchmark comparison still on screen.

```json
{
  "source_start_ms": 372480, "source_end_ms": 396740, "speed": 1.0,
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
        "region_id": "screen_bottom_benchmarks_proof",
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

**OVERLAY**: Title card at 386000ms: "2 DAYS TO DUMPSTER YOUR INDUSTRY" -- `slide_up`, 52px bold, #FF0050, bg_opacity=0.7, 5000ms
**SFX**: `bass_drop` at 386000ms (LOUDEST in entire video), `impact` at 392000ms
**MOTION**: `zoom_in` 1.0->1.15 on face region, ease_in (intensity builds)
**COLOR**: contrast=1.35, saturation=1.25 (PEAK VISUAL INTENSITY)

---

### Segment 21 (398520 - 420890ms) -- Benchmark Methodology: "Scored Against Real Voice"

**WHAT THE SPEAKER SAYS**: "let's see this video when it pops out... i scored myself against a real voice and not a synthetic fingerprint all other scores published academic or independent benchmarks using cross encoder evaluation and clip cannon scored matched encoder"

**WHAT THE SPEAKER IS REFERRING TO**: He's explaining his scoring methodology -- he used a real voice reference, not a synthetic fingerprint. Competitors use cross-encoder evaluation. The screen now shows a different view -- likely the ClipCannon pipeline comparison chart.

**WHAT IS ON THE SOURCE SCREEN** (OCR): Scene 49 shows "VALL-E 2 (Microsoft)" -- the comparison chart has shifted to show the specific competitor (Microsoft's VALL-E 2). This is a new view of the benchmark data.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% MUST show the VALL-E 2 comparison chart. The speaker is specifically comparing to Microsoft's system. The competitor name must be visible. Inspect the frame -- if the chart layout has changed from the previous segments, adjust the crop coordinates to center on the new comparison view.

**VERIFY**:
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=410000)` -- MUST show "VALL-E 2 (Microsoft)" text
- `clipcannon_analyze_frame(project_id="proj_ace4bcb3", timestamp_ms=410000)` -- get bounding boxes of the comparison chart

```json
{
  "source_start_ms": 398520, "source_end_ms": 420890, "speed": 1.0,
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
        "region_id": "screen_bottom_valle2_comparison",
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

**OVERLAY**: Lower third at 405000ms: "vs VALL-E 2 (Microsoft)" -- `slide_up`, 32px, #FF4444, 5000ms
**OVERLAY**: Title card at 412000ms: "REAL VOICE, NOT SYNTHETIC" -- `fade_in`, 40px, #00FF88, 4000ms
**SFX**: `chime` at 412000ms

---

### Segment 22 (420890 - 454450ms) -- "No Other AI Can Do This" + Final 98.9%

**WHAT THE SPEAKER SAYS**: "on novel content, the speaker never said. The model had zero opportunity to copy the target's sentence. I can make people say things they've never said. No other AI can do that with 98.9% accuracy literally indistinguishable by human beings completely"

**WHAT THE SPEAKER IS REFERRING TO**: The thesis statement. He's making the strongest claim in the entire video. The screen shows the ClipCannon Pipeline benchmark comparison with VALL-E 2.

**WHAT IS ON THE SOURCE SCREEN** (OCR): Scenes 49-52 show "VALL-E 2 (Microsoft)" and then "ClipCannon Pipeline" -- the comparison chart is showing both systems side by side.

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% MUST show the ClipCannon vs VALL-E 2 comparison. Both system names should be visible. The 98.9% number should be on screen (or nearby in the chart). THIS IS THE VISUAL PROOF MOMENT. The viewer hears "98.9% indistinguishable by humans" AND sees the data chart. Maximum impact.

**VERIFY**:
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=430000)` -- ClipCannon Pipeline label visible
- `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=445000)` -- benchmark still on screen

If the screen transitions during this segment (e.g., from benchmark chart to another view), SPLIT into sub-segments with different crops.

```json
{
  "source_start_ms": 420890, "source_end_ms": 454450, "speed": 1.0,
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
        "region_id": "screen_bottom_clipcannon_pipeline",
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

**OVERLAY**: Title card at 430000ms: "MAKE PEOPLE SAY THINGS THEY'VE NEVER SAID" -- `slide_up`, 44px, #FFFFFF, 5000ms
**OVERLAY**: Title card at 435000ms: "NO OTHER AI CAN DO THIS" -- `fade_in`, 40px, #FF0050, 4000ms
**OVERLAY**: Title card at 440000ms: "98.9% SECS ACCURACY" -- `slide_up`, 72px bold, #00FF88, 6000ms
**OVERLAY**: Title card at 446000ms: "INDISTINGUISHABLE BY HUMANS" -- `fade_in`, 40px, #FFD700, 5000ms
**SFX**: `impact` at 430000ms, `bass_drop` at 435000ms, `impact` at 440000ms, `shimmer` at 446000ms
**MOTION**: `zoom_in` 1.0->1.2 on face region, ease_in_out
**COLOR**: contrast=1.25, saturation=1.15

---

### Segment 23 (454450 - 476961ms) -- FINAL DEMO: "Hello Ann" Video Plays

**WHAT THE SPEAKER SAYS**: "let's watch this video hello and I love the dress you're wearing today you look cute"

**WHAT THE SPEAKER IS REFERRING TO**: He says "let's watch this video" and then the AI-generated video plays. The screen shows a video player playing "hello_anne.mp4" -- the final demo of the cloned voice saying words never in the training data.

**WHAT IS ON THE SOURCE SCREEN** (OCR): Scenes 52-55 show "ClipCannon Pipeline", "03_configuration.md" (briefly), then scenes 56-58 show "ORER", "XPLORER" (file explorer). Scenes 59-61 show "hello_anne.mp4" -- the video file name. Scene 62 shows "Sideo Subtitle Tools Vew Help" (VLC video player menu).

**SCREEN CROP INSTRUCTION**: Layout A. Bottom 70% MUST show the video player playing the "hello_anne.mp4" demo. This is the FINAL REWARD -- the entire video's promise is fulfilled here. The viewer must SEE the demo video playing.

**CRITICAL**: The screen content CHANGES during this segment:
- 454-456s: May show benchmark chart transitioning to file browser
- 456-469s: File explorer, navigating to hello_anne.mp4
- 469-477s: VLC video player playing hello_anne.mp4

**If the screen changes, SPLIT into sub-segments:**

#### Sub-segment 23a (454450 - 469000ms) -- Navigating to demo file

**SCREEN SHOWS**: File explorer, navigating to hello_anne.mp4

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=462000)` -- file explorer visible

```json
{
  "source_start_ms": 454450, "source_end_ms": 469000, "speed": 1.0,
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
        "region_id": "screen_bottom_file_nav",
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

**OVERLAY**: Title card at 455000ms: "FINAL DEMO: AI-GENERATED VOICE" -- `slide_up`, 40px, #FFD700, 4000ms
**OVERLAY**: Title card at 460000ms: "WORDS HE NEVER SAID IN TRAINING" -- `fade_in`, 32px, #00CCFF, 5000ms
**SFX**: `shimmer` at 455000ms

#### Sub-segment 23b (469000 - 476961ms) -- Demo Video Playing (THE REWARD)

**SCREEN SHOWS**: VLC video player playing hello_anne.mp4 -- the AI-generated voice saying "Hello Ann, I love the dress you're wearing today, you look cute"

**VERIFY**: `clipcannon_get_frame(project_id="proj_ace4bcb3", timestamp_ms=473000)` -- VLC player with hello_anne.mp4 visible

**THIS IS THE MOST IMPORTANT SCREEN TRACKING MOMENT IN THE ENTIRE VIDEO.** The demo video is playing. The cloned voice is speaking. The viewer must SEE and HEAR the proof. The screen region should be cropped to CENTER on the video player, removing file browser sidebars and chrome.

```json
{
  "source_start_ms": 469000, "source_end_ms": 476961, "speed": 1.0,
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
        "region_id": "screen_bottom_demo_playing",
        "source_x": 300, "source_y": 150,
        "source_width": 2300, "source_height": 1250,
        "output_x": 0, "output_y": 576,
        "output_width": 1080, "output_height": 1344,
        "z_index": 1, "fit_mode": "contain"
      }
    ]
  }
}
```

**OVERLAY (CTA)**: At 470000ms: "FOLLOW FOR MORE AI BUILDS" -- `fade_in`, 48px, #FF0050, position=bottom_center, until end
**OVERLAY (CTA)**: At 472000ms: "SEND THIS TO SOMEONE BUILDING WITH AI" -- `fade_in`, 32px, #FFFFFF, position=bottom_center, until end
**SFX**: `stinger` at 470000ms (CTA drop)
**COLOR**: brightness=0.05, contrast=1.1, saturation=1.05

---

## COMPLETE SEGMENT SUMMARY TABLE

| # | Start | End | Duration | Layout | Screen Content Shown (bottom 70%) | Speaker Topic |
|---|-------|-----|----------|--------|-----------------------------------|---------------|
| 1 | 0 | 6160 | 6.2s | D (HOOK ONLY) | Full face -- no screen ref | Intro, "I built ClipCannon" |
| 2 | 6360 | 9720 | 3.4s | A | IDE/workspace | "Create videos" |
| 3 | 9800 | 13700 | 3.9s | A | IDE/workspace | "Clone myself" |
| 4 | 14760 | 24740 | 10.0s | A | Terminal/code editor | "Qwen3 TTS, 2 days" |
| 5 | 25180 | 28020 | 2.8s | A | Workspace (transitioning) | "Show you" |
| 6 | 28020 | 38000 | 10.0s | A | File browser (docs2, video file) | Showing the intro video file |
| 7 | 38000 | 45500 | 7.5s | A | ocrprovenance.com website | Showing the video content |
| 8 | 45500 | 53240 | 7.7s | A | Video player/navigator | Navigating to demo |
| 9 | 53780 | 69680 | 15.9s | A | Code editor (01_system_overview.md) | "Removed audio, added voice" |
| 10a | 69680 | 85000 | 15.3s | A | VLC video player | "Compare my voice" |
| 10b | 85000 | 91790 | 6.8s | A | Terminal (lip sync setup) | "Setting up lip sync" |
| 11 | 92630 | 121700 | 29.1s | A | Terminal (avatar code output) | Avatar setup + "clone anybody" |
| 12 | 122700 | 156630 | 33.9s | A | Video player (0:00/0:14, demo) | Fingerprinting + "GG Clone Complete" demo |
| 13 | 157320 | 200600 | 43.3s | A | Benchmark comparison chart | "Destroy industries" + philosophy |
| 14 | 201140 | 258410 | 57.3s | A | Benchmark comparison chart | 98.9% reveal + "first natural" + livestream |
| 15 | 258410 | 305510 | 47.1s | A | Benchmark comparison chart | Embedders + "beyond human detection" |
| 16 | 307900 | 314660 | 6.8s | A | Benchmark data | "Secret about benchmarks" |
| 17 | 315320 | 330190 | 14.9s | A | Competitor scores (85.6%) | "My test is harder" |
| 18 | 330330 | 349920 | 19.6s | A | Benchmark data (85.6%) | "Different words, zero overlap" |
| 19 | 349920 | 372480 | 22.6s | A | Benchmark data | "Hello Ann" setup |
| 20 | 372480 | 396740 | 24.3s | A | Benchmark data (PROOF) | "DUMPSTER YOUR INDUSTRY" |
| 21 | 398520 | 420890 | 22.4s | A | VALL-E 2 comparison chart | "Scored against real voice" |
| 22 | 420890 | 454450 | 33.6s | A | ClipCannon Pipeline chart | "No other AI" + final 98.9% |
| 23a | 454450 | 469000 | 14.6s | A | File explorer (hello_anne.mp4) | Navigating to final demo |
| 23b | 469000 | 476961 | 8.0s | A | VLC playing hello_anne.mp4 | FINAL DEMO PLAYS |

**Layout D used**: ONLY for Segment 1 (hook, 0-6.2s). That's 6.2 seconds out of 477 seconds.
**Layout A used**: EVERYTHING ELSE. Face top 30%, screen content bottom 70%, tracking the speaker's topic at ALL TIMES.

**Total segments**: 25 (including sub-segments 10a, 10b, 23a, 23b)

---

## SCREEN TRACKING VERIFICATION CHECKLIST

Before rendering, the AI agent MUST verify these critical alignment points:

| Timestamp | Speaker Says | Bottom 70% Must Show | get_frame call |
|-----------|-------------|---------------------|----------------|
| 33000ms | "this intro video right here" | File browser with video files | `get_frame(ts=33000)` |
| 41000ms | (showing website) | ocrprovenance.com | `get_frame(ts=41000)` |
| 57000ms | "removed the audio" | Code editor or video editor | `get_frame(ts=57000)` |
| 77000ms | "compare my voice" | Video player (VLC) | `get_frame(ts=77000)` |
| 100000ms | "capturing my webcam" | Terminal with code output | `get_frame(ts=100000)` |
| 138000ms | "GG Clone Complete" | Video player with demo | `get_frame(ts=138000)` |
| 165000ms | "everybody else's system" | Benchmark comparison chart | `get_frame(ts=165000)` |
| 214000ms | "98.9%" | Benchmark with 98.9% visible | `get_frame(ts=214000)` |
| 325000ms | "my test is harder" | Competitor scores (85.6%) | `get_frame(ts=325000)` |
| 385000ms | "dumpster your industry" | Benchmark PROOF data | `get_frame(ts=385000)` |
| 410000ms | "VALL-E 2 (Microsoft)" | VALL-E 2 comparison | `get_frame(ts=410000)` |
| 440000ms | "98.9% accuracy" | ClipCannon Pipeline chart | `get_frame(ts=440000)` |
| 473000ms | (demo playing) | VLC playing hello_anne.mp4 | `get_frame(ts=473000)` |

If ANY of these frames don't match, the screen crop coordinates MUST be adjusted before rendering. DO NOT render until every verification passes.

---

**PROCEED TO PART 4 FOR EFFECTS, MUSIC, RENDERING, AND EXECUTION CHECKLIST.**
