# ClipCannon Phase 3: Voice Cloning + AI Avatar Pipeline

**Goal:** Give AI a script, it speaks in your voice. Give it your face, it makes a video of you saying it. ClipCannon produces complete videos autonomously.

**Hardware:** RTX 5090 (32GB GDDR7)
**Approach:** Occam's razor — simplest pipeline that produces professional results.
**Core principle:** Every generation step has a verification gate. If the output doesn't match your voice fingerprint, the system retries automatically until it does. This is the same iterative refinement philosophy as the edit-review-fix workflow — AI gets good through iteration, not one-shot perfection.

---

## The End State

```
clipcannon_generate_video(
    script="Hey everyone, today I want to show you how OCR Providence handles...",
    speaker_profile="boris",
    video_style="webcam_talking_head",
    platform="tiktok"
)
--> Outputs: 60-90s video of you saying the script, with your voice, your face, your mannerisms
```

Three capabilities, built in order:

| Phase | Capability | What It Does |
|-------|-----------|-------------|
| **3A** | Voice Clone | Text in --> your voice audio out |
| **3B** | Lip Sync | Your voice audio + your face video --> talking head video |
| **3C** | Full Autonomy | Script --> voice --> video --> edited final output |

---

## Phase 3A: Voice Cloning

### The Model: StyleTTS 2

**Why StyleTTS 2 over alternatives:**
- Highest naturalness score (MOS 4.5-4.8) after fine-tuning
- Fastest inference: 95x real-time on RTX 4090 (~4GB VRAM)
- MIT license — no commercial restrictions
- Mature, stable codebase (6.2k stars)
- Fine-tuning produces a permanent voice model — no reference audio needed at inference time

**Why not zero-shot alternatives (Chatterbox, Fish Speech):**
- Zero-shot cloning tops out at ~85% similarity. Fine-tuned StyleTTS 2 reaches 95%+
- Zero-shot requires passing reference audio every time. Fine-tuned = instant, no reference needed
- You want "indistinguishable from real" — that requires fine-tuning

### What You Need to Record

**Target: 1 hour of clean speech** (the quality sweet spot for StyleTTS 2)

Record yourself speaking naturally. Content doesn't matter — what matters is coverage:

| Recording Type | Duration | Purpose |
|---------------|----------|---------|
| **Read-aloud passages** | 20 min | Diverse phoneme coverage, consistent pacing |
| **Conversational monologue** | 20 min | Natural cadence, filler words, real rhythm |
| **Technical explanation** | 10 min | Your "teaching" voice (for tutorial content) |
| **High-energy pitch** | 5 min | Excited, fast-paced (for hooks/CTAs) |
| **Calm narration** | 5 min | Slow, deliberate (for explanations) |

**Recording specs:**
- Quiet room, same mic you use for videos (consistency matters)
- 48kHz, 24-bit WAV (or just record video and we extract audio)
- Mono preferred, stereo OK (we convert)
- ~60 minutes total raw --> ~45-50 min after silence trimming

**Shortcut: Use your existing videos.** You already have 3.5 min of isolated vocals from the OCR Providence video. Every video you ingest through ClipCannon adds to the voice pool. 5-6 more videos of similar length and you'll have your hour.

### Data Pipeline (Automated)

ClipCannon already has everything needed for preprocessing. New tool:

```
clipcannon_prepare_voice_data(
    project_ids=["proj_76961210", "proj_1502ef29", ...],
    speaker_label="speaker_0",
    output_dir="/path/to/voice_training_data"
)
```

This tool:
1. For each project, reads `stems/vocals.wav` (isolated speech from htdemucs)
2. Segments into 1-12 second clips at silence boundaries (from `silence_gaps` table)
3. Pairs each clip with its WhisperX transcript (from `transcript_words`)
4. Normalizes volume to -16 LUFS (from existing `audio_cleanup`)
5. Filters out clips with low confidence transcription
6. Phonemizes text using espeak-ng
7. Outputs: `train_list.txt`, `val_list.txt`, audio clips, phoneme files

**Zero new models needed.** This is pure data reformatting from existing pipeline outputs.

### Fine-Tuning Pipeline

New tool:

```
clipcannon_train_voice(
    training_data_dir="/path/to/voice_training_data",
    voice_name="boris",
    epochs=50,
    batch_size=4
)
```

Under the hood:
1. Downloads StyleTTS 2 pretrained weights (LibriTTS, ~800MB, one-time)
2. Generates mel spectrograms from training audio
3. Runs two-stage fine-tuning:
   - Stage 1: Acoustic model adaptation (~4-6 hours on RTX 5090)
   - Stage 2: Style diffusion adaptation (~4-6 hours)
4. Saves voice checkpoint to `~/.clipcannon/voices/{voice_name}/`
5. Runs validation: generates 10 test utterances, computes speaker similarity against reference

**Training time: 8-12 hours total.** Run overnight. One-time cost per voice.

### Inference Tool

```
clipcannon_speak(
    text="Hey everyone, today I want to show you...",
    voice_name="boris",
    speed=1.0,
    emotion="confident",
    output_format="wav"
)
--> Returns: audio_asset_id, file_path, duration_ms
```

Inference: ~4GB VRAM, 95x real-time (1 second of speech generates in ~10ms).

The output is a standard audio asset — plugs directly into the existing audio mixing pipeline. Can be attached to any edit.

### Voice Verification Gate (The Iterative Refinement Loop)

This is the critical quality system. ClipCannon already has WavLM speaker embeddings (30 x 512-dim vectors) stored for your voice. These are your voice fingerprint. Every generated utterance is compared against this fingerprint and rejected if it doesn't match.

**The Loop:**

```
clipcannon_speak(text="...", voice_name="boris")
    │
    ▼
GENERATE: StyleTTS 2 produces audio (seed=random)
    │
    ▼
GATE 1 — Sanity (instant, CPU):
    ├── Duration ratio: audio_length / expected_from_text < 3.0?
    ├── No silence gaps > 500ms?
    ├── No clipping (peak < 0.99)?
    ├── SNR > 15dB?
    │   FAIL → retry with new seed (don't even bother with expensive checks)
    │
    ▼
GATE 2 — Intelligibility (~500ms, Whisper):
    ├── Transcribe generated audio with Whisper
    ├── Compare against input text
    ├── WER (Word Error Rate) <= 5%?
    │   FAIL → retry with increased diffusion_steps
    │
    ▼
GATE 3 — Voice Identity (~200ms, ECAPA-TDNN):
    ├── Extract speaker embedding from generated audio
    ├── Compute cosine similarity against stored voice fingerprint
    ├── SECS >= 0.80? (Speaker Encoder Cosine Similarity)
    │   FAIL → retry with lower alpha (more speaker-faithful)
    │
    ▼
GATE 4 — Naturalness (~300ms, UTMOS):
    ├── Run UTMOS automated MOS prediction
    ├── Score >= 3.8 (out of 5.0)?
    │   FAIL → retry with more diffusion_steps (higher quality)
    │
    ▼
ALL GATES PASS → Accept audio, return to caller
    │
    ▼
MAX RETRIES (5) EXCEEDED → Return best attempt (highest SECS score)
                           + quality_warning flag so AI knows to try different approach
```

**What changes between retries:**

| Retry # | What Changes | Why |
|---------|-------------|-----|
| 1 | Random seed only | Cheapest change, often enough |
| 2 | Seed + diffusion_steps 5→10 | More diversity in generation |
| 3 | Seed + diffusion_steps 10→20 + alpha 0.3→0.15 | Push harder on speaker fidelity |
| 4 | Different reference audio segment (from training data) | Fresh style vector |
| 5 | All parameters maximized: steps=20, alpha=0.1, beta=0.5 | Last resort, maximum quality |

**The models used for verification:**

| Model | Purpose | VRAM | Speed | Already in ClipCannon? |
|-------|---------|------|-------|----------------------|
| **ECAPA-TDNN** (SpeechBrain) | Speaker identity verification | ~0.5GB | ~200ms | No — new dependency |
| **Whisper medium** | Intelligibility (WER) | ~1.5GB | ~500ms | Yes (WhisperX already installed) |
| **UTMOS** | Naturalness scoring | ~0.3GB | ~300ms | No — new dependency |

**Why ECAPA-TDNN instead of the existing WavLM embeddings?**
ECAPA-TDNN has 0.80% EER (Equal Error Rate) on VoxCeleb — best-in-class for speaker verification. WavLM is excellent for clustering/diarization but ECAPA-TDNN is specifically designed and benchmarked for "is this the same person?" comparisons. We keep WavLM for the pipeline analysis and add ECAPA-TDNN specifically for the verification gate.

**Storing the voice fingerprint:**

When `clipcannon_train_voice` completes, it also:
1. Extracts ECAPA-TDNN embeddings from 20 representative clips
2. Averages them into a single 192-dim "reference embedding"
3. Stores it in the `voice_profiles` table as `reference_embedding` (BLOB)
4. This embedding IS your voice fingerprint — compact, fast to compare

**The verification result is returned to the caller:**

```json
{
  "audio_asset_id": "audio_xxx",
  "file_path": "/path/to/output.wav",
  "duration_ms": 5230,
  "verification": {
    "attempts": 2,
    "final_secs": 0.87,
    "final_wer": 0.02,
    "final_utmos": 4.1,
    "passed_all_gates": true
  }
}
```

If the AI sees `passed_all_gates: false`, it knows to try a different approach — maybe shorter text, different phrasing, or use `apply_feedback` to adjust parameters.

**New dependencies for verification:**

| Package | VRAM | License | Purpose |
|---------|------|---------|---------|
| `speechbrain` | ~0.5GB | Apache 2.0 | ECAPA-TDNN speaker verification |
| `utmos` or `torch-squim` | ~0.3GB | MIT/BSD | Automated MOS scoring |

Both are lightweight and run on GPU alongside the TTS model.

**Schema update — voice_profiles table gets:**

```sql
reference_embedding BLOB,        -- 192-dim ECAPA-TDNN average embedding
verification_threshold REAL DEFAULT 0.80,  -- SECS threshold (tunable per voice)
```

**New file:**

```
src/clipcannon/voice/
    verify.py           # Voice verification gate (~200 lines)
                        # Functions: extract_embedding, compute_secs,
                        #            verify_generation, run_quality_gates
```

### Voice Accumulation (Automatic)

Every time you run `ingest` on a new video, ClipCannon already:
- Separates vocals via htdemucs
- Transcribes with WhisperX word-level alignment
- Extracts WavLM speaker embeddings

New behavior: after ingest, auto-append clean vocal segments to the voice training pool. Periodically prompt: "You now have 2.5 hours of voice data. Re-training would improve voice quality. Run `clipcannon_train_voice`?"

### New Dependencies

| Package | Version | VRAM | License | Purpose |
|---------|---------|------|---------|---------|
| `styletts2` | latest | ~4GB inference, ~16GB training | MIT | Voice synthesis |
| `phonemizer` | 3.x | CPU | GPL-3.0 | Text-to-phoneme conversion |
| `espeak-ng` | system package | CPU | GPL-3.0 | Phoneme backend |
| `librosa` | 0.10+ | CPU | ISC | Mel spectrogram generation |

StyleTTS 2 training uses PyTorch (already installed) + the `accelerate` library for mixed-precision.

### Files to Create

```
src/clipcannon/voice/
    __init__.py
    train.py            # Fine-tuning pipeline (~300 lines)
    inference.py         # TTS inference (~150 lines)
    data_prep.py         # Voice data preparation from projects (~200 lines)
    profiles.py          # Voice profile management (~100 lines)

src/clipcannon/tools/
    voice.py             # MCP tools: prepare_voice_data, train_voice, speak (~250 lines)
    voice_defs.py        # Tool definitions (~80 lines)
```

### Schema Addition

```sql
CREATE TABLE voice_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    model_path TEXT NOT NULL,
    training_hours REAL,
    training_projects TEXT,  -- JSON list of project_ids used
    sample_rate INTEGER DEFAULT 24000,
    speaker_embedding BLOB,  -- average WavLM embedding for verification
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

---

## Phase 3B: Lip Sync (Voice-to-Video)

### The Model: LatentSync 1.6

**Why LatentSync 1.6:**
- Best lip sync quality in 2026 benchmarks (ByteDance, ECCV 2025)
- Works directly with existing webcam footage (video-to-video)
- Apache 2.0 license
- 512x512 face region output (upscaled into original frame)
- Strong identity preservation — doesn't distort your face
- 18GB VRAM — fits on RTX 5090 alongside other tools

**The alternative for no-video scenarios: Hallo2**
- MIT license, single photo input, up to 4K output
- 24GB VRAM — tight but works on RTX 5090
- Use when you don't have video footage, just a photo

### What You Need to Record

**A "driver video" of yourself:**
- 2-5 minutes of webcam footage of you talking naturally
- Well-lit, consistent background, head and shoulders framing
- Multiple angles/expressions not needed — LatentSync handles variation
- This is a one-time recording. Once you have it, the model maps any audio onto it.

**Why video works better than photos:**
- Video provides natural head movement, blink patterns, and expression transitions
- LatentSync preserves these mannerisms while replacing the lip movement to match new audio
- A photo-based approach (Hallo2) has to hallucinate all movement — less natural

### Pipeline

```
clipcannon_lip_sync(
    audio_asset_id="audio_xxx",           # from clipcannon_speak
    driver_video="/path/to/webcam.mp4",   # your face video
    output_resolution="1080p"
)
--> Returns: video file of you "saying" the audio content
```

Under the hood:
1. Load LatentSync 1.6 model (~18GB VRAM)
2. Extract face region from driver video
3. Extract Whisper audio embeddings from the cloned voice audio
4. Cross-attention: audio drives lip movement on the face video
5. Composite lip-synced face back into the original frame
6. Output: video file with your face speaking the cloned audio

### Lip Sync Verification Gate

Same philosophy — verify before accepting:

```
GENERATE: LatentSync produces talking head video
    │
    ▼
GATE 1 — Face Identity:
    ├── Extract face embedding from generated video (frame at 50%)
    ├── Compare against face embedding from driver video
    ├── Face similarity >= 0.85? (using existing MediaPipe or ArcFace)
    │   FAIL → retry with different frame sampling
    │
    ▼
GATE 2 — Lip Sync Accuracy:
    ├── Extract audio from generated video
    ├── Run SyncNet confidence scoring (the standard lip sync metric)
    ├── Sync confidence >= 5.0? (SyncNet scale, >5 = good sync)
    │   FAIL → retry with adjusted parameters
    │
    ▼
GATE 3 — Visual Quality:
    ├── No face distortion (SSIM of face region vs driver > 0.7)
    ├── No flickering (frame-to-frame face consistency)
    ├── No artifacts in mouth region
    │   FAIL → fall back to Wav2Lip (lower quality but rock-solid)
    │
    ▼
ALL PASS → Accept video
```

### Integration with ClipCannon Edits

The lip-synced video becomes a **new source** that can be edited like any other:
- Ingest it as a new project
- Apply layouts, effects, overlays, captions via the existing editing pipeline
- Or use it directly as a segment in an existing edit

### New Dependencies

| Package | Version | VRAM | License | Purpose |
|---------|---------|------|---------|---------|
| `latentsync` | 1.6 | ~18GB | Apache 2.0 | Lip sync generation |
| `face-alignment` | latest | ~1GB | BSD | Face detection for LatentSync |

### Files to Create

```
src/clipcannon/avatar/
    __init__.py
    lip_sync.py          # LatentSync wrapper (~200 lines)
    face_extract.py      # Face region extraction (~100 lines)
    composite.py         # Face back into frame (~100 lines)

src/clipcannon/tools/
    avatar.py            # MCP tools: lip_sync, generate_avatar_video (~200 lines)
    avatar_defs.py       # Tool definitions (~60 lines)
```

---

## Phase 3C: Full Autonomy (Script-to-Video)

### The Grand Tool

```
clipcannon_generate_video(
    script="Hey everyone, today I want to show you how OCR Providence
            handles 18 different file types...",
    voice_name="boris",
    driver_video="/path/to/webcam.mp4",
    platform="tiktok",
    style={
        "hook_duration_s": 3,
        "background_music": "upbeat tech demo",
        "overlay_style": "bold_centered",
        "color_grade": "warm_confident"
    }
)
```

### The Pipeline (Sequential on RTX 5090, Verified at Every Step)

```
Step 1: VOICE (~4GB, ~2-10 seconds)
  StyleTTS 2 generates speech from script
  ┌─── VERIFICATION LOOP (up to 5 attempts) ───┐
  │ Gate 1: Sanity (duration, clipping, SNR)    │
  │ Gate 2: Intelligibility (WER <= 5%)         │
  │ Gate 3: Voice identity (SECS >= 0.80)       │
  │ Gate 4: Naturalness (UTMOS >= 3.8)          │
  │ FAIL → vary seed/steps/alpha → retry        │
  └─── PASS → voice_audio.wav ─────────────────┘

Step 2: LIP SYNC (~18GB, ~30-90 seconds)
  LatentSync maps voice audio onto your driver video
  ┌─── VERIFICATION LOOP (up to 3 attempts) ───┐
  │ Gate 1: Face identity preserved             │
  │ Gate 2: Lip sync accuracy (SyncNet >= 5.0)  │
  │ Gate 3: No visual artifacts                 │
  │ FAIL → adjust params → retry                │
  │ HARD FAIL → fall back to Wav2Lip            │
  └─── PASS → talking_head.mp4 ────────────────┘

Step 3: INGEST (~8GB, ~60 seconds)
  ClipCannon analyzes the talking head video
  (transcript, scenes, faces -- full existing pipeline)

Step 4: EDIT (CPU, ~1 second)
  AI creates an EDL with:
  - Segments timed to the script's natural breaks
  - Per-segment layouts (face dominant for claims, screen for demos)
  - Color grading, overlays, captions
  - Background music + SFX

Step 5: RENDER (~4GB, ~60-90 seconds)
  FFmpeg renders the final output with all effects
  ┌─── POST-RENDER VERIFICATION ────────────────┐
  │ inspect_render: 5-point quality check        │
  │ Caption sync: verify at 3 timestamps         │
  │ Audio levels: verify loudness normalization   │
  └─── PASS → final_output.mp4 ────────────────┘

Total: ~3-5 minutes end-to-end for a 60-second video
VRAM peak: 18GB (LatentSync step, everything else is lighter)
Every step is verified. Bad output never propagates to the next step.
```

### Mixing Talking Head with Screen Content

For tutorial videos, the AI can composite:
- Talking head segments (from voice clone + lip sync)
- Screen recording segments (from separate recordings or AI-generated)
- Using the existing layout system (A/B/C/D layouts, per-segment canvas)

This means a fully AI-generated tutorial could alternate between "you explaining" (talking head) and "the demo" (screen recording), all automatically.

### Files to Create

```
src/clipcannon/tools/
    generate_video.py    # Orchestrator: script --> final video (~300 lines)
    generate_defs.py     # Tool definitions (~40 lines)
```

---

## Implementation Order (Occam's Razor)

### Step 1: Voice Data Prep (1 day)
- `data_prep.py`: Extract and format training data from existing projects
- `clipcannon_prepare_voice_data` MCP tool
- Test: run on proj_76961210, verify output format matches StyleTTS 2 requirements

### Step 2: Voice Verification System (1 day)
- Install `speechbrain` (ECAPA-TDNN) + UTMOS
- `verify.py`: Speaker embedding extraction, SECS computation, multi-gate quality pipeline
- Build the voice fingerprint from existing WavLM embeddings as bootstrap, then generate ECAPA-TDNN reference embeddings
- Test: extract embeddings from known speech, verify cosine similarity thresholds work correctly, verify different speakers score below threshold

### Step 3: StyleTTS 2 Integration (2 days)
- Install StyleTTS 2 + dependencies
- `train.py`: Fine-tuning wrapper
- `inference.py`: TTS inference WITH verification loop built in (not bolted on after)
- `clipcannon_train_voice` + `clipcannon_speak` MCP tools
- The `speak` tool internally runs the 4-gate verification loop, returning quality metrics
- Test: train on available data, generate test utterances, verify SECS >= 0.80 against reference

### Step 4: Voice Profile Management (0.5 day)
- `profiles.py`: Save/load/list voice profiles
- Schema: `voice_profiles` table with `reference_embedding` and `verification_threshold`
- Auto-accumulation hook: after each ingest, offer to add vocals to training pool
- `clipcannon_voice_profiles` MCP tool to list/manage voices

### Step 5: LatentSync Integration (2 days)
- Install LatentSync 1.6
- `lip_sync.py`: Audio + video --> talking head WITH verification loop
- `face_extract.py` + `composite.py`: Face region handling
- `clipcannon_lip_sync` MCP tool
- Lip sync verification: face identity check + SyncNet confidence scoring
- Test: clone voice, lip-sync onto webcam footage, verify all quality gates pass

### Step 6: Orchestrator (1 day)
- `generate_video.py`: Script --> voice (verified) --> lip sync (verified) --> edit --> render (verified)
- `clipcannon_generate_video` MCP tool
- Every step has its verification gate — bad output never propagates forward
- If any step fails after max retries, returns partial result + diagnostic info so AI can adjust approach
- Test: end-to-end from script to final output

### Step 7: Iteration + Tuning (ongoing)
- Record more voice data, retrain (each retrain improves the fingerprint too)
- Record better driver video, improve lip sync
- Tune verification thresholds based on real-world results:
  - If too many false rejections → lower SECS threshold from 0.80 to 0.75
  - If poor quality passing → raise SECS threshold to 0.85
  - Track pass rates per gate to identify bottlenecks

**Total estimated effort: ~8 days of implementation**

### The Verification Philosophy

This is the same pattern that makes the edit-review-fix workflow powerful: **AI doesn't need to be perfect on the first try. It needs to KNOW when it's wrong and have the tools to fix itself.**

The voice fingerprint is the "source of truth." Every generation is measured against it. The verification loop is cheap (< 1 second total for all 4 gates) compared to the generation itself (~2 seconds). Running 3-5 attempts costs 6-10 seconds total — still under 15 seconds for a verified voice clip.

The same pattern extends to every future capability:
- **Video generation**: Verify face identity after lip sync
- **Music generation**: Verify tempo/energy matches the video mood
- **Caption generation**: Verify WER against transcript
- **Full video**: Verify retention curve meets platform benchmarks

**Generate → Verify → Retry → Ship.** That's the entire system philosophy.

---

## What You Need to Do (Non-Code Tasks)

| Task | Time | Priority |
|------|------|----------|
| **Record 1 hour of speech** (or ingest 5-6 more video projects) | 1-2 hours | Required for Phase 3A |
| **Record 2-5 min webcam "driver" video** | 5 minutes | Required for Phase 3B |
| **Provide a test script** (what you want the AI to say) | 5 minutes | For testing |

The webcam driver video should be:
- Well-lit (same setup as your normal videos)
- Head and shoulders, facing camera
- Talk naturally about anything — the words don't matter, just the movement
- 2-5 minutes gives LatentSync plenty of material to work with

---

## Architecture Diagram

```
                    YOUR DATA (one-time)
                    ==================
                    1 hour speech audio
                    2-5 min webcam video
                           |
                    TRAINING (one-time, overnight)
                    ==============================
                    StyleTTS 2 fine-tune (8-12 hrs)
                           |
                           v
                    VOICE PROFILE (~200MB checkpoint)
                    saved at ~/.clipcannon/voices/boris/
                           |
                           |
           ================|=================
           |                                |
    PER-VIDEO GENERATION              VOICE ACCUMULATION
    ====================              ===================
    Script text                       Each new video ingest
         |                            adds vocals to pool
         v                            Periodic retrain
    StyleTTS 2 inference (~10ms/s)    improves quality
         |
         v
    Voice audio (WAV)
         |
         v
    LatentSync 1.6 (~30-60s)
         |
         v
    Talking head video
         |
         v
    ClipCannon edit pipeline
    (layouts, effects, captions,
     music, SFX, color grading)
         |
         v
    FINAL VIDEO
```

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| 3.5 min insufficient for fine-tuning | Medium | Start zero-shot with Chatterbox while accumulating data. Switch to StyleTTS 2 at 30+ min. |
| LatentSync face distortion | Low | Model is SOTA for identity preservation. Fallback: Wav2Lip (lower quality but rock-solid sync) |
| VRAM pressure during lip sync | Low | 18GB + overhead = ~20GB. RTX 5090 has 32GB. Comfortable margin. |
| StyleTTS 2 repo abandoned | Low | MIT license, code is self-contained, community forks active. Stylish-TTS is a viable successor. |
| Voice sounds "off" | Medium | WavLM embedding verification gate rejects poor generations. User can regenerate with different seed. |

---

## Summary: The Simplest Path

1. **Accumulate voice data** from your existing videos (already happening via ingest)
2. **Fine-tune StyleTTS 2** overnight once you have enough data
3. **Record a 2-minute webcam clip** of yourself talking
4. **LatentSync maps any cloned audio** onto that footage
5. **ClipCannon's existing edit pipeline** adds all the polish

No new AI architectures. No complex training loops. Just two well-proven models (StyleTTS 2 + LatentSync 1.6) plugged into the existing ClipCannon pipeline with new MCP tools as the interface. The hardest part is waiting for the fine-tuning to finish.
