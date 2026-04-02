# MouthMemory: Retrieval-Based Lip Sync Engine

## Problem Statement

All current lip-sync models (LatentSync, Wav2Lip, SadTalker, MuseTalk) use neural generation to create mouth pixels from audio. This causes:

- **VAE blur** (diffusion models): 512px face encoded to 64px latent, decoded back. High-frequency mouth detail (teeth edges, lip texture) is destroyed in the round-trip.
- **GAN artifacts** (Wav2Lip/MuseTalk): temporal flickering, color shifts, ghosting at mouth boundaries.
- **Fixed quality ceiling**: the model never improves after training. Your 100th video looks as blurry as your 1st.
- **Slow inference**: LatentSync takes ~300s for 40s of video on an RTX 5090. Diffusion needs 20+ denoising steps per 16-frame chunk.

## Core Insight

Lip sync is not a generation problem -- it's a search problem. The mouth shapes corresponding to speech sounds are finite (~14 visemes for English) and the person's face already exists in the source video at full resolution. We don't need to generate mouth pixels. We need to find the right ones and put them in the right place.

## How It Works (One Paragraph)

MouthMemory builds a database of real mouth frames extracted from video, labeled with what sound is being made (viseme), head pose, energy level, and emotion. At runtime, given new audio, it looks up the transcript to know which phoneme is being spoken at each frame, queries the database for the best matching mouth frame, warps it to align with the target face using landmark-guided affine transforms, and composites it using Laplacian pyramid blending. Every pixel is real. No generation, no blur, no artifacts.

---

## Architecture

### Two Operating Modes

MouthMemory operates in two modes depending on available data:

**Mode A: Atlas Mode (pre-built profile)**
For voices with existing video data (like boris with 10 source videos). A rich mouth atlas is pre-built offline with thousands of mouth frames across all visemes, head poses, and energy levels. At runtime, the atlas is queried for the closest match.

**Mode B: Self-Source Mode (any video)**
For arbitrary videos with no pre-built atlas. The source/driver video itself becomes the atlas. Since ingest already provides word-level timestamps and face detection for every ingested video, we can label the source video's own mouth frames with visemes and re-sequence them to match new audio. This works for ANY person in ANY ingested video with zero setup.

Both modes use the same runtime pipeline. The only difference is where the mouth frames come from.

```
┌─────────────────────────────────────────────────────┐
│                   OFFLINE PHASE                      │
│                                                      │
│   Mode A: Voice Profile Atlas                        │
│   ───────────────────────                            │
│   Multiple source videos → ingest (already done)     │
│   → High-fps face extraction (25fps)                 │
│   → Landmark detection per frame                     │
│   → Word→phoneme→viseme labeling                     │
│   → Mouth atlas DB (~45,000+ frames per profile)     │
│                                                      │
│   Mode B: Self-Source (any video)                     │
│   ──────────────────────────                         │
│   Single driver video → ingest (already done)        │
│   → High-fps face extraction (25fps)                 │
│   → Landmark detection per frame                     │
│   → Word→phoneme→viseme labeling                     │
│   → Ephemeral atlas from this video only             │
│                                                      │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│                   RUNTIME PHASE                      │
│                (same for both modes)                  │
│                                                      │
│   Target audio → Whisper → word timestamps           │
│   Words → CMU Dict → phonemes → visemes              │
│                     │                                │
│   For each output frame at time T:                   │
│     1. target_viseme = phoneme_at_T → viseme map     │
│     2. target_pose = driver_frame_T head pose        │
│     3. target_energy = audio energy at T             │
│     4. Query atlas for best matching mouth frame     │
│     5. Affine warp mouth to target face geometry     │
│     6. Laplacian pyramid blend into output frame     │
│                                                      │
│   Output: lip-synced video, full resolution,         │
│           real mouth pixels, <5s for 40s video       │
│                                                      │
└─────────────────────────────────────────────────────┘
```

---

## Data Already Available From Ingest

Every `clipcannon_ingest` run produces all of this automatically. MouthMemory requires ZERO new ingest stages for basic operation.

| Data | Source | Resolution | Lip-Sync Use |
|------|--------|------------|--------------|
| Word timestamps | `transcript_words` | 20-50ms (WhisperX) | Which phoneme at which millisecond |
| Sentence segments | `transcript_segments` | Per sentence | Coarticulation context |
| Face bounding boxes | `scene_map` | Per scene | Where to crop the mouth |
| Vocal stem | `stems/vocals.wav` | Full quality | Clean audio for energy analysis |
| Emotion curve | `emotion_curve` | Per time window | Match mouth intensity to emotion |
| Speaker embeddings | `vec_speakers` (512-dim) | Per speaker | Verify correct speaker |
| Acoustic data | `acoustic` | Per time window | Volume → mouth openness correlation |
| Prosody features | `prosody_segments` | Per sentence clip | F0, energy, speaking rate |
| Visual embeddings | `vec_frames` (1152-dim) | Per frame at 2fps | Similarity search for frame matching |
| Silence gaps | `silence_gaps` | Per gap | Mouth closed during silence |
| Scene boundaries | `scenes` | Per scene | Don't blend across cuts |
| Extracted frames | `frames/frame_*.jpg` | 2fps | Low-fps reference (need 25fps for lip-sync) |

### New Data Needed (One New Pipeline Stage)

The only missing piece is **high-fps face frame extraction with landmarks**. The current ingest extracts frames at 2fps (for scene analysis). Lip sync needs 25fps face crops with per-frame landmark data.

This is added as an optional post-ingest stage: `mouth_index`. It runs only when requested (before lip-sync or atlas build) and stores results in a new `mouth_frames` table.

---

## Database Schema

### `mouth_frames` table (per-project analysis.db)

Stores per-frame mouth data extracted at 25fps from source videos.

| Column | Type | Description |
|--------|------|-------------|
| `frame_id` | INTEGER | Primary key, auto-increment |
| `project_id` | TEXT | FK to project |
| `timestamp_ms` | INTEGER | Frame timestamp in video |
| `face_crop_path` | TEXT | Path to cropped face image |
| `mouth_crop_path` | TEXT | Path to cropped mouth region |
| `landmarks_json` | TEXT | JSON: 20 lip landmark points (InsightFace 52-71) |
| `head_yaw` | REAL | Head rotation left/right (degrees) |
| `head_pitch` | REAL | Head rotation up/down (degrees) |
| `head_roll` | REAL | Head tilt (degrees) |
| `viseme` | TEXT | Viseme category (one of ~14) |
| `phoneme` | TEXT | ARPAbet phoneme (AA, AE, AH, B, CH, ...) |
| `word` | TEXT | Word being spoken at this frame |
| `word_position` | TEXT | Position within word: start/middle/end |
| `prev_viseme` | TEXT | Previous frame's viseme (coarticulation) |
| `next_viseme` | TEXT | Next frame's viseme (coarticulation) |
| `mouth_openness` | REAL | Vertical lip distance normalized 0-1 |
| `mouth_width` | REAL | Horizontal lip distance normalized 0-1 |
| `energy` | REAL | Audio energy at this timestamp |
| `f0` | REAL | Fundamental frequency at this timestamp |
| `emotion_label` | TEXT | Emotion from emotion_curve |
| `speaker_id` | INTEGER | Speaker from speaker diarization |
| `quality_score` | REAL | Face detection confidence * blur score |

Indexes:
- `idx_mouth_viseme`: `(project_id, viseme, quality_score DESC)`
- `idx_mouth_time`: `(project_id, timestamp_ms)`
- `idx_mouth_speaker`: `(project_id, speaker_id, viseme)`

### `vec_mouth` virtual table (sqlite-vec)

Vector similarity search for finding visually similar mouth frames.

| Column | Type | Description |
|--------|------|-------------|
| `frame_id` | INTEGER | FK to mouth_frames |
| `mouth_embedding` | float[128] | Mouth region visual embedding (SigLIP on cropped mouth) |

### `mouth_atlas` table (in ~/.clipcannon/voice_data/{name}/mouth_atlas.db)

Pre-built atlas for voice profiles. Same schema as `mouth_frames` but aggregated across multiple source projects.

| Column | Type | Description |
|--------|------|-------------|
| (same as mouth_frames) | | |
| `source_project_id` | TEXT | Which project this frame came from |

---

## Phoneme-to-Viseme System

### Phoneme Extraction

Words are already timestamped by WhisperX in `transcript_words`. Convert words to phonemes using the CMU Pronouncing Dictionary (134,000 entries, BSD licensed, included with NLTK):

```python
import nltk
nltk.download('cmudict')
cmu = nltk.corpus.cmudict.dict()

# "hello" → [['HH', 'AH0', 'L', 'OW1']]
# Each phoneme gets proportional time within the word's start_ms-end_ms
```

For out-of-vocabulary words, use `g2p-en` (grapheme-to-phoneme neural model) as fallback.

### Viseme Mapping

Standard phoneme-to-viseme mapping (based on MPEG-4 FAP / Disney 14-viseme system):

| Viseme | Phonemes | Mouth Shape |
|--------|----------|-------------|
| `SIL` | (silence) | Closed/neutral |
| `PP` | P, B, M | Lips pressed together |
| `FF` | F, V | Lower lip under upper teeth |
| `TH` | TH, DH | Tongue between teeth |
| `DD` | T, D, N, L | Tongue on upper ridge |
| `KK` | K, G, NG | Back tongue raised |
| `CH` | CH, JH, SH, ZH | Lips rounded, teeth close |
| `SS` | S, Z | Teeth close, lips slightly open |
| `RR` | R, ER | Lips slightly rounded |
| `AA` | AA, AE, AH | Wide open |
| `EH` | EH, EY | Mid-open, spread |
| `IH` | IH, IY | Narrow, spread |
| `OH` | AO, OW | Rounded, mid-open |
| `OO` | UW, UH, W | Tight round |

### Coarticulation Handling

Human mouths don't jump between visemes -- they blend. The mouth starts transitioning to the NEXT viseme before the current phoneme ends. This is modeled by:

1. **Lookahead labeling**: Each `mouth_frames` entry stores `prev_viseme` and `next_viseme`.
2. **Transition preference**: When selecting a mouth frame for viseme X, prefer frames where `prev_viseme` and `next_viseme` match the actual context. This naturally captures coarticulation because the source video's mouth was doing the same transition.
3. **Blending window**: For the last 25% of each viseme's duration, linearly interpolate landmark positions toward the next viseme's target. This is just landmark lerp -- no pixel generation.

---

## Runtime Pipeline: Frame-by-Frame

### Input

- `driver_video`: Video with the face to lip-sync (from `extract_webcam` or any video)
- `target_audio`: Speech audio (from `clipcannon_speak` or any audio file)
- `atlas_source`: Either a voice profile name (Mode A) or "self" (Mode B, use driver video's own mouth frames)

### Step 1: Prepare Target Phoneme Timeline

```
target_audio
    → Whisper transcribe → word-level timestamps
    → CMU Dict lookup → phoneme sequence with timing
    → Phoneme → viseme mapping → viseme timeline at ~40ms resolution
    → Energy extraction → energy curve (numpy RMS, no ML)
```

Output: For each output frame at time T (25fps = every 40ms):
- `target_viseme`: which mouth shape
- `target_energy`: how open/intense
- `prev_viseme`, `next_viseme`: context for coarticulation
- `is_silence`: bool (from silence_gaps or energy threshold)

### Step 2: Prepare Driver Video

```
driver_video (at 25fps)
    → InsightFace per frame → face bbox, 106-point landmarks
    → Extract head_yaw, head_pitch, head_roll per frame
    → Extract mouth region landmarks[52:72] per frame
```

Output: For each driver frame at time T:
- `driver_landmarks`: 106-point facial landmarks
- `driver_lip_landmarks`: points 52-72
- `driver_head_pose`: yaw, pitch, roll
- `driver_face_bbox`: where to composite

### Step 3: Select Mouth Frames

For each output frame at time T:

```sql
-- Primary query: exact viseme match + pose + energy
SELECT frame_id, mouth_crop_path, landmarks_json, quality_score
FROM mouth_frames
WHERE viseme = :target_viseme
  AND ABS(head_yaw - :driver_yaw) < 15
  AND ABS(head_pitch - :driver_pitch) < 10
  AND ABS(energy - :target_energy) < 0.3
  AND quality_score > 0.5
ORDER BY
  -- Prefer matching coarticulation context
  CASE WHEN prev_viseme = :prev_viseme THEN 0 ELSE 1 END,
  CASE WHEN next_viseme = :next_viseme THEN 0 ELSE 1 END,
  -- Then closest energy match
  ABS(energy - :target_energy),
  -- Then highest quality
  quality_score DESC
LIMIT 5
```

If no exact viseme match: fall back to closest mouth_openness + mouth_width match (geometric similarity regardless of viseme label).

**Temporal coherence**: Track the previous selected frame's source timestamp. Add a bonus score for frames that are temporally close to the previous selection in the source video. This creates natural sequences where consecutive output frames come from the same source segment, avoiding jarring jumps.

### Step 4: Warp and Composite

For the selected mouth frame:

1. **Affine alignment**: Compute affine transform from source mouth landmarks to driver mouth landmarks. This handles position, scale, and rotation.

```python
src_pts = source_landmarks[52:72]  # 20 lip points
dst_pts = driver_landmarks[52:72]
M = cv2.estimateAffinePartial2D(src_pts, dst_pts)[0]
warped_mouth = cv2.warpAffine(source_mouth_crop, M, (w, h))
```

2. **Mask creation**: Create soft mask from driver lip landmarks (same technique as existing `face_enhance.py` `_get_lip_mask`). Dilate by 8px, Gaussian blur by 7px for soft edges.

3. **Laplacian pyramid blending**: Blend warped mouth into driver frame using multi-scale Laplacian pyramid. This produces seamless edges without the color bleeding of Poisson blending.

```python
# 4-level Laplacian pyramid blend
blended = laplacian_pyramid_blend(
    foreground=warped_mouth_frame,
    background=driver_frame,
    mask=lip_mask,
    levels=4,
)
```

4. **Color matching**: Histogram-match the mouth crop's color statistics to the driver frame's face region. This handles lighting differences between source and driver.

### Step 5: Temporal Smoothing

Apply 3-frame Gaussian smoothing to the landmark warp parameters (not the pixels) to prevent per-frame jitter:

```python
# Smooth affine transform parameters over 3-frame window
M_smoothed = gaussian_filter1d(M_sequence, sigma=0.5, axis=0)
```

### Step 6: Output Assembly

Write frames to video via OpenCV VideoWriter, remux original target audio (same pattern as existing LatentSync audio remux).

---

## Self-Source Mode (Any Video, Zero Setup)

This is how MouthMemory works on arbitrary videos without a pre-built atlas:

1. User calls `clipcannon_lip_sync_v2(project_id, audio_path, driver_video_path)`
2. Driver video has already been ingested → word timestamps and face data exist
3. System extracts 25fps face frames from driver video with landmarks
4. Labels each frame with the viseme it's currently showing (from existing transcript_words)
5. Builds an ephemeral mouth atlas from the driver video's own frames
6. Runs the same selection + warp + composite pipeline
7. Ephemeral atlas can be cached for reuse or discarded

**Why this works for any person**: The atlas is built FROM the target person's face. The mouth frames are their actual mouth. No training on their identity needed.

**Minimum footage needed**: A 30-second video with clear face and speech gives ~750 face frames. With 14 visemes, that's ~54 frames per viseme on average. This is enough for good coverage, though more footage always helps.

**Graceful degradation**: If a viseme has zero coverage (the person never made that mouth shape in the source video), fall back to landmark-warp of the closest available viseme. The warp stretches existing mouth pixels to approximate the target shape. Not perfect, but avoids blank/glitch frames.

---

## Voice Profile Atlas Mode (Pre-Built)

For recurring identities (like boris), build a rich atlas once:

1. Gather all source videos associated with the voice profile (from `training_projects`)
2. Run `mouth_index` on each project to extract 25fps face frames
3. Merge all mouth_frames into `mouth_atlas.db` (in voice_data directory)
4. With 10 source videos at ~5 min each = ~75,000 mouth frames
5. Rich coverage of every viseme at every angle and energy level

The atlas persists and improves as more videos are ingested. New MCP tool: `clipcannon_build_mouth_atlas(voice_name)`.

---

## Quality Safeguards

### Frame Quality Gating

Not all mouth frames are usable. Gate by:
- **Face detection confidence** > 0.5 (InsightFace)
- **Blur score** > 40 (Laplacian variance, same as quality pipeline stage)
- **Mouth visibility** > 0.7 (ratio of visible lip landmarks to expected)
- **No occlusion** (hand over mouth, microphone blocking, etc.)

### Fallback Chain

If the atlas doesn't have a good match:

```
1. Exact viseme + close pose + close energy → BEST
2. Exact viseme + any pose → GOOD (warp handles pose difference)
3. Close viseme + close openness → ACCEPTABLE (similar mouth shape)
4. Warp current driver frame mouth to target landmarks → FALLBACK
5. Keep driver frame unchanged → LAST RESORT (for undetected faces)
```

### A/B Quality Comparison

Include a built-in comparison mode: render the same clip with MouthMemory and LatentSync side-by-side. Let the user judge which is better for their content.

---

## File Structure

### New Source Files

```
src/clipcannon/
    avatar/
        mouth_memory.py          # Core MouthMemory engine (selection, warp, composite)
        mouth_atlas.py           # Atlas builder (offline, per voice profile)
        mouth_index.py           # Per-project mouth frame extraction + labeling
        viseme_map.py            # Phoneme-to-viseme mapping, CMU dict wrapper
        laplacian_blend.py       # Laplacian pyramid blending utility
    pipeline/
        mouth_index_stage.py     # Optional ingest stage for 25fps face extraction
    tools/
        lip_sync_v2.py           # MCP tool handler for clipcannon_lip_sync_v2
        lip_sync_v2_defs.py      # MCP tool schema definition
```

### Modified Files

```
src/clipcannon/
    db/schema.py                 # Add mouth_frames table + vec_mouth + indexes
    pipeline/registry.py         # Register mouth_index as optional post-ingest stage
    tools/__init__.py            # Register lip_sync_v2 tool
    tools/generate_video.py      # Add engine="mouthmemory" option
```

---

## MCP Tool Interface

### `clipcannon_lip_sync_v2`

```json
{
    "name": "clipcannon_lip_sync_v2",
    "description": "Lip-sync using MouthMemory retrieval engine. Uses real mouth frames instead of neural generation. Supports any person in any ingested video.",
    "inputSchema": {
        "type": "object",
        "required": ["project_id", "audio_path"],
        "properties": {
            "project_id": {
                "type": "string",
                "description": "Project ID for output storage"
            },
            "audio_path": {
                "type": "string",
                "description": "Path to target speech audio (from clipcannon_speak or any WAV)"
            },
            "driver_video_path": {
                "type": "string",
                "description": "Path to driver video with face. If omitted, uses extracted webcam from project."
            },
            "voice_name": {
                "type": "string",
                "description": "Voice profile name for atlas mode. If omitted, uses self-source mode (driver video as its own atlas)."
            },
            "fps": {
                "type": "integer",
                "default": 25,
                "description": "Output frame rate"
            },
            "blend_mode": {
                "type": "string",
                "enum": ["laplacian", "gaussian", "alpha"],
                "default": "laplacian",
                "description": "Blending method for mouth composite"
            },
            "temporal_smooth": {
                "type": "number",
                "default": 0.5,
                "description": "Temporal smoothing sigma (0 = none, 1 = heavy)"
            },
            "fallback_to_warp": {
                "type": "boolean",
                "default": true,
                "description": "If no atlas match found, warp driver mouth to target shape"
            },
            "compare_with_latentsync": {
                "type": "boolean",
                "default": false,
                "description": "Also render with LatentSync for side-by-side comparison"
            }
        }
    }
}
```

### `clipcannon_build_mouth_atlas`

```json
{
    "name": "clipcannon_build_mouth_atlas",
    "description": "Build a mouth atlas for a voice profile from its training project videos. One-time offline operation.",
    "inputSchema": {
        "type": "object",
        "required": ["voice_name"],
        "properties": {
            "voice_name": {
                "type": "string",
                "description": "Voice profile name (e.g. 'boris')"
            },
            "project_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific project IDs to include. If omitted, uses all training_projects from voice profile."
            },
            "min_quality": {
                "type": "number",
                "default": 0.5,
                "description": "Minimum quality score for included frames"
            }
        }
    }
}
```

---

## Performance Targets

| Metric | LatentSync (current) | MouthMemory (target) |
|--------|---------------------|---------------------|
| 40s video render | ~300s | <5s |
| Quality (mouth detail) | Blurry (VAE bottleneck) | Full resolution (real pixels) |
| VRAM usage | ~18GB | ~2GB (InsightFace only, one-time) |
| Runtime GPU needed | Yes (diffusion UNet) | No (CPU: SQLite + OpenCV) |
| Works on any face | Yes | Yes (self-source mode) |
| Improves with more data | No (fixed model) | Yes (atlas grows) |
| Atlas build (offline) | N/A | ~2min per 5min video |
| Self-source mode overhead | N/A | ~30s (25fps extraction + labeling) |

---

## Implementation Phases

### Phase 1: Core Engine (MVP)

Build the fundamental pipeline that works in self-source mode on any ingested video.

**Deliverables:**
- `viseme_map.py`: CMU dict phoneme lookup + phoneme-to-viseme mapping
- `mouth_index.py`: 25fps face extraction with InsightFace landmarks + viseme labeling
- `mouth_memory.py`: Frame selection (SQL query) + affine warp + alpha blend composite
- `lip_sync_v2.py` + `lip_sync_v2_defs.py`: MCP tool wiring
- DB schema additions: `mouth_frames` table + indexes

**Test:** Lip-sync a 10-second clip using the driver video's own mouth frames.

### Phase 2: Quality Refinement

Improve blending, temporal coherence, and edge cases.

**Deliverables:**
- `laplacian_blend.py`: Multi-scale Laplacian pyramid blending
- Temporal smoothing on warp parameters
- Color histogram matching between source and driver
- Coarticulation-aware frame selection (prev/next viseme context)
- Quality gating (blur, occlusion, confidence thresholds)
- Silence handling (mouth closed during gaps)

**Test:** Full 40-second lip-sync compared side-by-side with LatentSync.

### Phase 3: Atlas Mode

Pre-built voice profile atlases for recurring identities.

**Deliverables:**
- `mouth_atlas.py`: Aggregates mouth_frames across multiple projects
- `mouth_atlas.db` storage in voice_data directory
- `vec_mouth` sqlite-vec table for visual similarity search
- `clipcannon_build_mouth_atlas` MCP tool
- Integration with `clipcannon_generate_video` (`engine="mouthmemory"`)

**Test:** Boris atlas from 10 source videos, lip-sync quality vs self-source mode.

### Phase 4: Polish

Production hardening and edge case handling.

**Deliverables:**
- Fallback chain implementation (exact → close → warp → unchanged)
- A/B comparison mode (`compare_with_latentsync` flag)
- `mouth_index` as optional pipeline stage in registry
- Prosody-aware selection (use prosody_segments energy/F0 for better matching)
- Speaker diarization integration (only use frames from correct speaker)
- Batch processing optimization (frame extraction parallelized)

---

## Dependencies

### Already Available (zero new deps)
- OpenCV (`cv2`): affine warp, video I/O, image processing
- NumPy: landmark math, blending
- SQLite + sqlite-vec: frame database + vector search
- InsightFace: face detection + 106-point landmarks (already used in face_enhance.py)
- Whisper/WhisperX: word-level transcription (already used in ingest)
- scipy: signal processing for energy extraction

### New (small, pure Python)
- `nltk` (cmudict corpus): phoneme dictionary, ~3MB download
- `g2p-en` (optional): neural grapheme-to-phoneme for OOV words, ~10MB

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Insufficient viseme coverage in short videos | Visible artifacts for rare phonemes | Fallback to landmark warp; recommend >30s source |
| Head pose mismatch between atlas and driver | Distorted mouth composite | Wide pose tolerance (15 deg), affine warp compensates |
| Lighting mismatch | Color discontinuity at mouth boundary | Histogram matching + Laplacian blend hides edges |
| Fast speech (>200 WPM) | Viseme transitions too fast | Frame interpolation; mouth shapes have 40ms resolution at 25fps |
| Multiple faces in frame | Wrong face selected | Use speaker diarization + face tracking from scene_map |
| Mouth occluded (hand, mic) | Bad frame in atlas | Quality gating excludes occluded frames |
| Non-English speech | CMU dict doesn't cover | IPA-based viseme mapping as extension; core 14 visemes are language-universal |

---

## Success Criteria

1. **Sharpness**: MouthMemory output has higher PSNR in the mouth region than LatentSync output when compared to ground truth frames
2. **Speed**: 40s video rendered in <5s (excluding one-time atlas build)
3. **Universality**: Works on any ingested video in self-source mode without any per-person setup
4. **Sync accuracy**: Mouth-audio alignment within 40ms (1 frame at 25fps), validated by SyncNet score
5. **No GPU at runtime**: Full pipeline runs on CPU (atlas build uses GPU for InsightFace, but runtime is CPU-only)
