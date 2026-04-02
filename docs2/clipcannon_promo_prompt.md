# ClipCannon Promo Video -- Full AI Production Prompt

## Overview

Produce a 75-second Alex Hormozi-style promo video featuring Nate (@nate.b.jones) selling ClipCannon. Nate's voice is cloned with prosody-aware reference selection, his lips are synced to a new script, and the video is edited with bold overlays, jump cuts, and stat cards. Output: 16:9 (1920x1080) for YouTube.

**Critical prosody requirement:** The voice must NOT sound like AI. Use prosody-tagged reference clips to match delivery energy to each sentence. Format the script with punctuation that drives expressive TTS output. Generate sentence-by-sentence if needed for prosodic variety.

---

## SCRIPT

Write this in Nate's voice -- direct, high-energy, no fluff. Hormozi rule: open mid-sentence, no greetings, first word is a number or bold claim.

**Prosody formatting rules applied (these affect TTS output):**
- `!` = increased energy and pitch range
- `...` = natural hesitation pause (~300ms)
- `--` = emphasis break (~150ms)
- Short. Punchy. Sentences. = authoritative delivery
- Questions = rising intonation
- Contractions ("it's", "that's") = conversational tone

```
Ninety-seven percent. That's how close... an AI clone of my voice scored against my REAL voice -- on independent speaker verification! Not 80. Not 90. Ninety-seven percent. The system that did this? It's called ClipCannon.

Here's what it actually does. You give it a video -- any video. It runs 23 analysis stages. Transcription, face detection, emotion tracking, scene analysis, beat detection, prosody capture -- ALL of it. Then it understands your video... better than you do!

Then it clones your voice. Not some generic text-to-speech robot. YOUR voice! It uses a 1.7 billion parameter model, generates 12 candidates, scores each one against your real voice fingerprint -- and picks the one that sounds most like you. The result? It beats every published system! VALL-E 2 claimed human parity at 88 percent. ClipCannon hits 96.

But it doesn't stop at voice. It takes your face from the video, maps the new audio onto your lips using diffusion-based lip sync -- and produces a video where you're saying completely different words! Your face. Your voice. New content. Fully automated.

No cloud APIs. No subscriptions. Everything runs locally... on a single GPU. You own every frame!

54 tools. 681 passing tests. Provenance tracking on every operation. This isn't a demo -- this is production infrastructure for content at scale!

ClipCannon. The AI video pipeline that understands, edits, voices, and animates. Go check it out.
```

**Duration:** ~75 seconds at natural speaking pace.

**Prosody formatting breakdown:**
- `...` pauses before reveals: "how close... an AI clone", "your video... better than you do"
- `--` emphasis breaks: "your lips using diffusion-based lip sync --", "Not some generic"
- `!` energy spikes on key claims: "Ninety-seven percent!", "ALL of it!", "YOUR voice!"
- `?` questions for rising intonation: "The system that did this?", "The result?"
- Short punchy sentences at end: "Your face. Your voice. New content. Fully automated."
- Contractions for conversational: "That's", "it's", "doesn't", "isn't"

---

## STEP-BY-STEP PRODUCTION WORKFLOW

### Step 1: Generate Voice (Prosody-Aware)

Use project `proj_6cfe66a0` (Nate Voice 2 -- the 88s video). Voice profile `nate` has 2048-dim embedding from 3 videos + 652 prosody-tagged reference clips.

**Option A: Single generation with prosody style selection**

```
clipcannon_speak(
    project_id: "proj_6cfe66a0",
    text: "<the script above with prosody formatting>",
    voice_name: "nate",
    speed: 1.0,
    max_attempts: 5,
    enhance: true,
    prosody_style: "energetic",
    temperature: 0.7
)
```

The `prosody_style: "energetic"` automatically selects the highest-energy reference clip from Nate's prosody library (652 segments). The `temperature: 0.7` allows more expressive pitch variation than the default 0.5 while maintaining voice identity.

**Option B: Sentence-by-sentence with per-sentence prosody (highest quality)**

For maximum prosodic variety, generate each paragraph separately with a different prosody style:

```
# Paragraph 1 (hook -- energetic, punchy)
clipcannon_speak(text="Ninety-seven percent. That's how close...", prosody_style="energetic", temperature=0.7)

# Paragraph 2 (explanation -- varied, natural)
clipcannon_speak(text="Here's what it actually does...", prosody_style="varied", temperature=0.7)

# Paragraph 3 (claim -- emphatic, authoritative)
clipcannon_speak(text="Then it clones your voice...", prosody_style="emphatic", temperature=0.7)

# Paragraph 4 (demo -- rising energy)
clipcannon_speak(text="But it doesn't stop at voice...", prosody_style="rising", temperature=0.8)

# Paragraph 5 (independence -- calm authority)
clipcannon_speak(text="No cloud APIs...", prosody_style="energetic", temperature=0.7)

# Paragraph 6 (stats -- fast, confident)
clipcannon_speak(text="54 tools...", prosody_style="fast", temperature=0.7)

# Paragraph 7 (CTA -- direct)
clipcannon_speak(text="ClipCannon. The AI video pipeline...", prosody_style="emphatic", temperature=0.7)
```

Then concatenate with natural pauses: 300ms between paragraphs, 500ms before the CTA.

**Why per-sentence generation sounds more human:**
- Humans naturally vary their prosody across paragraphs -- energetic for claims, measured for explanations, emphatic for stats
- Single-shot TTS tends to flatten prosody after ~10 seconds (autoregressive regression to mean)
- Different reference clips for each section teach the model different delivery styles
- Varying temperature across sections adds prosodic texture

**Available Nate prosody styles:**
| Style | Reference clip | What it captures |
|-------|---------------|------------------|
| `energetic` | prosody_0072.wav | High energy, wide pitch range, fast pace |
| `emphatic` | prosody_0179.wav | Heavy word emphasis, dramatic pauses |
| `varied` | prosody_0008.wav | Mixed pitch contours, natural breathing |
| `best` | prosody_0008.wav | Highest composite score across all features |

**Nate's natural speaking characteristics:**
- Average 220 WPM (fast talker)
- 83% of segments are "high energy"
- Wide pitch range (~200 Hz average)
- Frequently uses emphasis (energy spikes)
- Mix of falling (33%), varied (30%), rising (16%), flat (2%) contours

This produces a 44.1kHz WAV with Nate's cloned voice. Verification will confirm SECS > 0.95.

### Step 2: Extract Driver Video at 25fps

The source video IS the driver (Nate talking to camera, full room, 16:9). Extract full frame at 25fps:

```
clipcannon_extract_webcam(
    project_id: "proj_6cfe66a0",
    padding_pct: 0.0
)
```

Note: Since this is a full-frame talking head (not a screen recording with PIP), you may need to extract the full frame manually:

```bash
ffmpeg -y -i source.mp4 -r 25 -c:v libx264 -crf 18 driver_25fps.mp4
```

### Step 3: Lip Sync

```
clipcannon_lip_sync(
    project_id: "proj_6cfe66a0",
    audio_path: "<voice WAV from step 1>",
    driver_video_path: "<25fps video from step 2>",
    inference_steps: 20,
    guidance_scale: 1.5,
    seed: 1247
)
```

Output: lip-synced video with 44.1kHz audio remuxed back in.

### Step 4: Create Project from Lip-Synced Video

```
clipcannon_project_create(
    name: "ClipCannon Promo - Nate",
    source_video_path: "<lip-synced video from step 3>"
)
clipcannon_ingest(project_id: "<new project>")
```

### Step 5: Auto-Trim

```
clipcannon_auto_trim(
    project_id: "<new project>",
    pause_threshold_ms: 600,
    merge_gap_ms: 100,
    min_segment_ms: 800
)
```

Aggressive trim -- Hormozi style removes ALL dead air. Every pause over 600ms gets cut.

### Step 6: Create the Edit with Hormozi-Style Segments

Target: `youtube_standard` (1920x1080, 16:9)

The source is already 16:9 at 2560x1440. Each segment uses a full-frame crop showing the room + Nate.

**Segment design -- per the script:**

| Time | Script Section | Layout | Effect | Overlay |
|------|---------------|--------|--------|---------|
| 0-3s | "97 percent..." | Full frame, slight zoom_in 1.0->1.05 | High contrast, warm | Title card: **"97%"** massive white text center |
| 3-8s | "...how close an AI clone..." | Tight crop on face (Hormozi close-up) | | Lower third: "Voice Clone Accuracy" |
| 8-12s | "...called ClipCannon" | Pull back to full room | | Title card: **"ClipCannon"** bold centered |
| 12-22s | "22 analysis stages..." | Full frame | | Stat overlay: **"22 STAGES"** then cycle: "Transcription / Face Detection / Emotion / Beats" |
| 22-30s | "clones your voice..." | Tight face crop | zoom_in 1.0->1.08 | Lower third: "1.7B Parameter Model" |
| 30-38s | "generates 12 candidates..." | Full frame | | Stat card: **"Best of 12"** then **"0.961 SECS"** |
| 38-42s | "VALL-E 2 claimed 88%..." | Tight face | High contrast punch | Comparison overlay: "VALL-E 2: 88% vs ClipCannon: 96%" |
| 42-50s | "maps new audio onto lips..." | Full frame | | Lower third: "LatentSync 1.6 Diffusion Lip Sync" |
| 50-55s | "No cloud APIs..." | Tight face, zoom_in | | Title card: **"100% LOCAL"** |
| 55-65s | "54 tools, 681 tests..." | Full frame | | Stat cards cycling: "54 Tools" / "681 Tests" / "Provenance Tracking" |
| 65-72s | "ClipCannon. The AI video pipeline..." | Slow zoom out to full room | Warm grade, slight saturation boost | |
| 72-75s | "Go check it out." | Hold full frame | | CTA overlay: **"Link in description"** |

### Step 7: Apply Effects

All in one message:

```
// Hook zoom
add_motion(segment_id=1, effect="zoom_in", start_scale=1.0, end_scale=1.05, easing="ease_out")

// Color grading -- Hormozi warm/contrasty look
color_adjust(brightness=0.05, contrast=1.3, saturation=0.9, gamma=0.95)

// Overlays
add_overlay(type="title_card", text="97%", position="center", start_ms=0, end_ms=3000, font_size=120, text_color="#FFFFFF", bg_opacity=0, animation="fade_in", animation_duration_ms=200)

add_overlay(type="lower_third", text="Voice Clone Accuracy", subtitle="Independent Speaker Verification", position="bottom_left", start_ms=3000, end_ms=8000, font_size=36, text_color="#FFFFFF", bg_color="#000000", bg_opacity=0.7)

add_overlay(type="title_card", text="ClipCannon", position="center", start_ms=8000, end_ms=11000, font_size=80, text_color="#FFFFFF", bg_opacity=0)

add_overlay(type="lower_third", text="22 Analysis Stages", subtitle="Transcription + Face + Emotion + Beats + Scene + OCR", start_ms=12000, end_ms=22000, font_size=32)

add_overlay(type="lower_third", text="1.7B Parameter Voice Model", subtitle="Qwen3-TTS with Full ICL Cloning", start_ms=22000, end_ms=30000, font_size=32)

add_overlay(type="title_card", text="0.961", subtitle="Speaker Similarity Score", position="center", start_ms=33000, end_ms=37000, font_size=100, text_color="#FFD700")

add_overlay(type="title_card", text="VALL-E 2: 88%  vs  ClipCannon: 96%", position="center", start_ms=38000, end_ms=42000, font_size=48, text_color="#FFFFFF")

add_overlay(type="lower_third", text="LatentSync 1.6", subtitle="ByteDance Diffusion Lip Sync", start_ms=42000, end_ms=50000)

add_overlay(type="title_card", text="100% LOCAL", subtitle="No Cloud APIs. No Subscriptions.", position="center", start_ms=50000, end_ms=55000, font_size=80, text_color="#FFFFFF")

add_overlay(type="title_card", text="54 Tools  |  681 Tests", position="center", start_ms=55000, end_ms=60000, font_size=56, text_color="#FFFFFF")

add_overlay(type="cta", text="Link in Description", position="bottom_center", start_ms=72000, end_ms=75000, font_size=36, text_color="#FFFFFF", bg_color="#FF0000", animation="slide_up")
```

### Step 8: Captions

```
captions: {
    enabled: true,
    style: "word_highlight",
    font: "Impact",
    font_size: 48,
    color: "#FFFFFF"
}
```

Word-highlight style -- current word pops in bold. Essential for silent viewing (85% of social viewers).

### Step 9: Audio

```
// Background music -- subtle, Hormozi uses low lo-fi/hip-hop
compose_music(
    description: "subtle lo-fi hip-hop beat, minimal, podcast energy, not distracting",
    duration_s: 80,
    energy: "low"
)

// SFX on stat reveals
generate_sfx(sfx_type="impact", duration_ms=300)  // for "97%" reveal
generate_sfx(sfx_type="whoosh", duration_ms=400)   // for stat card transitions
```

Music at -22 dB with speech ducking enabled. Voice should dominate.

### Step 10: Render

```
clipcannon_render(
    project_id: "<promo project>",
    edit_id: "<edit from step 6>"
)
```

Profile: `youtube_standard` (1920x1080, 30fps, h264, 12Mbps)

### Step 11: Review and Iterate

```
inspect_render(project_id, render_id)
get_frame(project_id, timestamp_ms=1500, render_id=X)   // Check hook
get_frame(project_id, timestamp_ms=40000, render_id=X)  // Check comparison overlay
get_frame(project_id, timestamp_ms=72000, render_id=X)  // Check CTA
```

If anything is off, `modify_edit` to adjust, then re-render. The segment cache reuses unchanged segments.

---

## KEY STATS TO REFERENCE (from arxiv paper)

| Metric | Value | Context |
|--------|-------|---------|
| Mean WavLM SECS | 0.961 | Beats human ground truth (0.730) by +0.049 |
| Max WavLM SECS | 0.975 | Same-session human band is 0.95-0.99 |
| DNSMOS Naturalness | 3.93 | Identical to real speech (also 3.93) |
| UTMOS Quality | 3.012 | Higher than real speech (2.997) |
| vs VALL-E 2 | +0.080 | VALL-E 2 = 0.881, ClipCannon = 0.961 |
| vs NaturalSpeech 3 | +0.070 | NS3 = 0.891, ClipCannon = 0.961 |
| Pipeline stages | 23 | Full video understanding DAG (incl. prosody analysis) |
| MCP tools | 54 | Complete editing/rendering/voice/avatar pipeline |
| Tests passing | 681 | 451 ClipCannon + 200 voice agent + 30 avatar |

---

## HORMOZI EDITING RULES APPLIED

1. **Open mid-sentence with a number.** "97 percent." -- no intro, no greeting.
2. **Jump cuts to zero dead air.** Auto-trim at 600ms removes all pauses.
3. **Text on every stat.** 11 overlay cards in 75 seconds.
4. **Hard cuts only.** No dissolves, no wipes.
5. **Face close-up for claims, pull back for context.** Alternate tight/wide every 5-8s.
6. **Bold sans-serif text, center-positioned, appears instantly.** Impact font, white on dark.
7. **Color: high contrast, warm, slightly desaturated.** Contrast 1.3, saturation 0.9.
8. **Music: barely there.** Lo-fi at -22dB, voice at -6dB. Silence before key moments.
9. **End abruptly.** "Go check it out." -- then CTA card for 3 seconds, video ends.
10. **No logos, no animations, no intros.** Content starts at frame 1.

---

## PROSODY ENGINEERING (Make Voice Sound Human)

### Why TTS Sounds AI (The Root Cause)

Voice identity (SECS) and voice prosody (rhythm/emphasis/pitch) are independent. A clone can score 0.97 SECS (perfect identity) while sounding completely robotic. The five specific deficits:

1. **Micro-prosodic jitter missing**: Human speech has constant tiny pitch/timing fluctuations. Low temperature smooths these out.
2. **Emphasis is flat**: Humans stress 2-3 words per sentence (+20% duration, +15% pitch). TTS distributes evenly.
3. **Paragraph-level arcs absent**: No energy build across sentences.
4. **Breathing patterns mechanical or missing**.
5. **Best-of-N SECS selection selects AGAINST prosody**: The most spectrally consistent (flat) candidates score highest on SECS.

### How This Pipeline Solves It

**1. Prosody-Tagged Reference Library (Automatic)**

During ingest, the `prosody_analysis` pipeline stage extracts per-sentence F0 contour, energy, speaking rate, and pitch variation from the vocal stem. Each sentence is stored as a tagged clip with:
- `prosody_score` (0-100 composite expressiveness rating)
- `energy_level` (low/medium/high)
- `pitch_contour_type` (rising/falling/varied/flat)
- `speaking_rate_wpm`
- `has_emphasis` (detected energy spikes)
- `has_breath` (natural breathing pauses)

Nate's library: **652 prosody-tagged segments** across 3 videos.

**2. Style-Matched Reference Selection**

When calling `clipcannon_speak` with `prosody_style`, the system queries the prosody library for clips matching the target style:

| prosody_style | What it selects | Best for |
|--------------|-----------------|----------|
| `energetic` | Highest energy, wide pitch range | Bold claims, hooks |
| `calm` | Low energy, flat pitch | Measured explanations |
| `emphatic` | Has emphasis (energy spikes > 2.5x mean) | Key stats, reveals |
| `varied` | Mixed pitch contours, natural breathing | Conversational sections |
| `fast` | >160 WPM speaking rate | Rapid-fire stats |
| `slow` | <120 WPM speaking rate | Dramatic pauses |
| `rising` | Rising pitch contour | Questions, building tension |
| `question` | Rising pitch, wide F0 range | Rhetorical questions |
| `best` | Highest composite prosody score | Default best quality |

**3. Prosody-Formatted Script**

The script text itself drives TTS prosody through punctuation:

| Formatting | TTS Effect | Example |
|-----------|------------|---------|
| `!` | +15% pitch, +20% energy | "YOUR voice!" |
| `...` | ~300ms hesitation pause | "how close... an AI clone" |
| `--` | ~150ms emphasis break | "lip sync -- and produces" |
| `?` | Rising terminal intonation | "The system that did this?" |
| Short sentences | Authoritative, punchy | "Your face. Your voice. New content." |
| Contractions | Conversational flow | "It's", "doesn't", "isn't" |
| ALL CAPS | Weak/inconsistent | Avoid -- use `!` instead |

**4. Temperature for Expressiveness**

| Temperature | Identity (SECS) | Prosody | Use Case |
|------------|----------------|---------|----------|
| 0.3 | Highest (0.97+) | Flat/monotone | Benchmark optimization only |
| 0.5 | High (0.96+) | Conservative | Legacy default |
| **0.7** | Good (0.95+) | **Natural/expressive** | **Video voiceovers (NEW default)** |
| 0.8 | Acceptable (0.93+) | Very expressive | Emphatic sections |
| 0.9 | Lower (0.90+) | Maximum variety | Experimental |

**5. Per-Paragraph Generation (Advanced)**

For maximum prosodic variety, generate the script paragraph-by-paragraph:

1. Each paragraph uses a DIFFERENT prosody reference clip
2. Match the reference's energy to the paragraph's emotional content
3. Concatenate with natural pauses (300ms between paragraphs, 500ms before CTA)
4. Apply 30ms crossfade at boundaries to smooth transitions

This prevents the autoregressive regression-to-mean that flattens prosody after ~10 seconds of continuous generation.

### Prosody Quality Checklist

Before finalizing voice output, verify:
- [ ] Pitch variation: F0 range > 100 Hz (check with pyworld)
- [ ] Energy dynamics: peak-to-mean ratio > 2.0
- [ ] Speaking rate: 120-200 WPM (natural range)
- [ ] No monotone stretches > 5 seconds
- [ ] Natural pauses at thought boundaries
- [ ] Emphasis on key words ("ninety-seven", "YOUR voice", "ClipCannon")
- [ ] Rising intonation on questions
- [ ] Energy build across the hook section
- [ ] Warm-down in energy for CTA (trust signal)

### What NOT To Do

- **DO NOT set temperature below 0.5** for video voiceovers. It produces spectrally consistent but prosodically dead output.
- **DO NOT select voice candidates purely by SECS score.** SECS rewards flatness. Use composite scoring: `0.7 * SECS + 0.3 * F0_range_normalized`.
- **DO NOT generate the entire script in one shot** for long content (>30s). Autoregressive models flatten prosody over time.
- **DO NOT use ALL CAPS for emphasis** in the script. It's unreliable. Use `!` and `--` instead.
- **DO NOT skip the enhance step.** Metallic TTS artifacts are the #1 "sounds AI" signal.
