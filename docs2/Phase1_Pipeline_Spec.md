# Phase 1: Foundation — Pipeline Stage Specifications

**Version:** 1.0
**Date:** 2026-03-21

---

## 1. Pipeline Orchestrator

### 1.1 Design

The pipeline orchestrator is a DAG-based task runner. Each stage declares its dependencies, inputs, outputs, and whether it is required or optional.

```python
@dataclass
class PipelineStage:
    name: str
    operation: str               # Provenance operation ID
    required: bool               # If True, failure stops entire pipeline
    depends_on: list[str]        # Stages that must complete first
    run: Callable                # Stage execution function
    fallback_values: dict | None # Values to insert if optional stage fails
```

### 1.2 Task Classification

| Stage | Required? | If It Fails |
|:------|:----------|:-----------|
| probe | Yes | Pipeline stops — can't read the file |
| vfr_normalize | Yes (if VFR) | Pipeline stops — timestamps unreliable |
| audio_extract | Yes | Pipeline stops — no audio = no transcript |
| source_separation | No | Fallback: feed mixed audio to all audio models |
| frame_extract | Yes | Pipeline stops — no frames = no visual |
| transcribe | Yes | Pipeline stops — transcript is primary signal |
| visual_embed | No | Fallback: no scene detection, no visual similarity |
| ocr | No | Fallback: empty on_screen_text[] |
| quality | No | Fallback: all scenes "unknown" quality |
| shot_type | No | Fallback: all scenes "unknown" shot type |
| semantic_embed | No | Fallback: no topic segmentation |
| emotion_embed | No | Fallback: flat energy (0.5 everywhere) |
| speaker_embed | No | Fallback: single "speaker_0" for all |
| reactions | No | Fallback: empty reactions[] |
| acoustic | No | Fallback: no silence gaps, no beats |
| profanity | No | Fallback: content rated "unknown" |
| chronemic | No | Fallback: no pacing data |
| highlights | No | Fallback: highlights based on available data only |
| storyboard | No | Fallback: AI requests frames via get_frame instead |
| finalize | Yes | Always runs — verifies chain |

### 1.3 Execution Order (DAG)

```
probe
  └──► vfr_normalize (if VFR)
         └──► audio_extract ──► source_separation ──┬──► transcribe ──┬──► semantic_embed
              │                                      │                 ├──► profanity
              │                                      ├──► emotion_embed│
              │                                      ├──► speaker_embed└──► chronemic ──► highlights
              │                                      ├──► reactions
              │                                      └──► acoustic
              └──► frame_extract ──┬──► visual_embed ──► shot_type
                                   ├──► ocr
                                   ├──► quality
                                   └──► storyboard
                                                     └──► finalize
```

Stages at the same depth level with no mutual dependencies run in parallel when VRAM permits.

### 1.4 Stream Status in VUD

After pipeline completion, stream_status is recorded:

```json
{
  "stream_status": {
    "source_separation": "completed",
    "transcription": "completed",
    "visual": "completed",
    "ocr": "failed",
    "quality": "completed",
    "shot_type": "completed",
    "semantic": "completed",
    "emotion": "failed",
    "speaker": "completed",
    "reactions": "completed",
    "acoustic": "completed",
    "beats": "completed",
    "chronemic": "completed",
    "storyboards": "completed",
    "profanity": "completed",
    "highlights": "completed"
  },
  "failed_streams": ["ocr", "emotion"],
  "degradation_note": "OCR and emotion analysis failed. On-screen text unavailable. Energy data is flat (0.5)."
}
```

---

## 2. Stage Specifications

### Stage 1: Probe

**Operation ID:** `probe`
**Required:** Yes
**Input:** Source video file path
**Output:** Project record in `project` table
**Tools:** FFmpeg `ffprobe`, `vfrdet` filter

**Steps:**
1. Run `ffprobe -v quiet -print_format json -show_format -show_streams {video_path}`
2. Extract: duration, resolution, fps, codec, audio codec, channels, file size
3. Run VFR detection: `ffmpeg -i {video_path} -vf vfrdet -f null -` — parse `VFR:X.XXXXXX`
4. If VFR ratio > 0.0: mark `vfr_detected = True`
5. Compute SHA-256 of source file (streaming, 8KB chunks)
6. INSERT into `project` table
7. Write provenance record `prov_001`

**Validation:**
- File exists and is readable
- At least one video stream
- At least one audio stream (warn if missing)
- Duration > 0
- Supported format (mp4, mov, mkv, webm, avi, ts, mts)

---

### Stage 1.5: VFR Normalization

**Operation ID:** `normalize_vfr`
**Required:** Yes (only runs if VFR detected)
**Input:** Source video
**Output:** `source/source_cfr.mp4`
**Tools:** FFmpeg with NVDEC + NVENC

**Steps:**
1. Determine target CFR: nearest standard rate to source avg fps (23.976, 24, 25, 29.97, 30, 50, 59.94, 60)
2. Run: `ffmpeg -hwaccel cuda -i source.mp4 -vf fps={target_fps} -c:v h264_nvenc -crf 18 -c:a copy source_cfr.mp4`
3. Compute SHA-256 of output
4. Update `project` table: `source_cfr_path`, `vfr_normalized = True`
5. Write provenance record

**All subsequent stages use `source_cfr.mp4` as the working source if VFR was detected.**

---

### Stage 2: Audio Extraction

**Operation ID:** `extract_audio`
**Required:** Yes
**Input:** Source video (or source_cfr if normalized)
**Output:** `audio_16k.wav` (16kHz mono), `audio_original.wav` (original rate)
**Tools:** FFmpeg

**Steps:**
1. Extract 16kHz mono for WhisperX: `ffmpeg -i source.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 audio_16k.wav`
2. Extract original sample rate for HTDemucs: `ffmpeg -i source.mp4 -vn -acodec pcm_s16le audio_original.wav`
3. Compute SHA-256 of both outputs
4. Write provenance record

---

### Stage 3: Source Separation (HTDemucs)

**Operation ID:** `separate_audio`
**Required:** No (fallback: use mixed audio for all streams)
**Input:** `audio_original.wav`
**Output:** `stems/vocals.wav`, `stems/music.wav`, `stems/drums.wav`, `stems/other.wav`
**Model:** HTDemucs v4 (`htdemucs_ft`), MIT license
**VRAM:** ~4GB FP16, ~2GB NVFP4

**Steps:**
1. Load HTDemucs model (GPU preferred, CPU fallback with `cpu_offload=True`)
2. Process audio through model → 4 stem outputs
3. Save stems as WAV files at source sample rate
4. Unload model from VRAM
5. Compute SHA-256 of all 4 stems
6. Write provenance record

**Fallback on failure:** Set `source_separation` status to `failed`. All downstream audio stages receive `audio_16k.wav` (mixed) instead of `vocals.wav`.

---

### Stage 4: Frame Extraction

**Operation ID:** `extract_frames`
**Required:** Yes
**Input:** Source video
**Output:** `frames/frame_NNNNNN.jpg` (at 2fps)
**Tools:** FFmpeg with NVDEC

**Steps:**
1. Calculate expected frame count: `duration_s * 2`
2. Run: `ffmpeg -hwaccel cuda -hwaccel_output_format cuda -i source.mp4 -vf "fps=2,hwdownload,format=nv12" -q:v 2 frames/frame_%06d.jpg`
3. Verify frame count matches expected (±1 tolerance)
4. Compute SHA-256 of frame manifest (sorted list of filenames + sizes)
5. Write provenance record

**Output:** For 1-hour video: 7,200 JPEG frames. For 4-hour: 28,800 frames.

---

### Stage 5: Transcription (WhisperX)

**Operation ID:** `transcribe`
**Required:** Yes
**Input:** `stems/vocals.wav` (or `audio_16k.wav` if separation failed)
**Output:** Rows in `transcript_segments` + `transcript_words` tables
**Model:** WhisperX (faster-whisper large-v3 + wav2vec2 forced alignment)
**VRAM:** ~3.5GB FP16, ~1.5GB NVFP4

**Steps:**
1. Load WhisperX model with forced alignment
2. Transcribe with `word_timestamps=True`, `beam_size=5`, `vad_filter=True`
3. Run wav2vec2 forced alignment for 20-50ms word precision
4. Auto-detect language
5. INSERT segments into `transcript_segments` (start_ms, end_ms, text, language)
6. INSERT words into `transcript_words` (word, start_ms, end_ms, confidence)
7. Compute SHA-256 of serialized transcript output
8. Write provenance record

**Critical:** Base Whisper timestamps drift 200-500ms. WhisperX with wav2vec2 alignment is MANDATORY for word-level caption accuracy.

---

### Stage 6: Visual Embedding (SigLIP)

**Operation ID:** `embed_visual`
**Required:** No
**Input:** `frames/*.jpg`
**Output:** Rows in `vec_frames` + `scenes` tables
**Model:** SigLIP SO400M-patch14-384
**VRAM:** ~1.2GB FP16, ~0.6GB NVFP4

**Steps:**
1. Load SigLIP model
2. For each frame in batches of 64:
   a. Resize to 384x384 (maintaining aspect, pad)
   b. Run inference → 1152-dim embedding
   c. INSERT into `vec_frames` (timestamp_ms, frame_path, embedding)
3. Compute scene boundaries:
   a. For consecutive frames: `cosine_sim(embed[i], embed[i+1])`
   b. If similarity < 0.75 (SCENE_THRESHOLD): mark scene boundary
4. For each scene: identify key frame (first frame), detect face position, compute dominant colors
5. INSERT scenes into `scenes` table
6. Write provenance record

**Fallback:** No scene detection. AI relies on storyboard grids only.

---

### Stage 7: OCR Text Detection (PaddleOCR)

**Operation ID:** `detect_text`
**Required:** No
**Input:** Frames at 1fps (every other extracted frame)
**Output:** Rows in `on_screen_text` + `text_change_events` tables
**Model:** PaddleOCR PP-OCRv5 (mobile pipeline)
**VRAM:** ~1-2GB

**Steps:**
1. Load PaddleOCR model
2. For frames at 1fps intervals:
   a. Run detection + recognition
   b. Deduplicate: if text identical to previous frame → skip
   c. Classify region: center_top, center_middle, bottom_third, etc.
   d. Estimate font size: small, medium, large
3. INSERT distinct text blocks into `on_screen_text`
4. Detect text-change events (significant text change = slide transition)
5. INSERT into `text_change_events`
6. Write provenance record

---

### Stage 8: Quality Assessment

**Operation ID:** `assess_quality`
**Required:** No
**Input:** `frames/*.jpg`
**Output:** Updates to `scenes` table (quality columns)
**Model:** pyiqa BRISQUE (GPU) + DOVER-Mobile (GPU)
**VRAM:** ~2.9GB combined

**Steps:**
1. Load BRISQUE and DOVER-Mobile models
2. Batch inference on all frames → per-frame quality score (0-100)
3. Compute Laplacian variance for blur detection (CuPy GPU)
4. Aggregate per scene: quality_avg, quality_min, blur_frames, blur_pct
5. Classify: good (>60), acceptable (40-60), poor (<40)
6. Identify issues: heavy_blur, camera_shake, low_light, overexposed
7. UPDATE `scenes` SET quality columns
8. Write provenance record

---

### Stage 9: Shot Type Classification

**Operation ID:** `classify_shots`
**Required:** No
**Input:** Key frames from scenes (1 per scene)
**Output:** Updates to `scenes` table (shot_type, crop_recommendation)
**Model:** ResNet-50 fine-tuned on MovieShots
**VRAM:** ~1-2GB

**Steps:**
1. Load ResNet-50 shot classifier
2. For each scene's key frame: classify → extreme_closeup, closeup, medium, wide, establishing
3. Compute crop recommendation:
   - extreme_closeup/closeup → "safe_for_vertical"
   - medium → "needs_reframe" (use face detection for center)
   - wide/establishing → "keep_landscape"
4. UPDATE `scenes` SET shot_type, shot_type_confidence, crop_recommendation
5. Write provenance record

---

### Stage 10: Semantic Embedding (Nomic)

**Operation ID:** `embed_semantic`
**Required:** No
**Input:** Transcript segments from `transcript_segments`
**Output:** Rows in `vec_semantic` + `topics` tables
**Model:** Nomic Embed Text v1.5
**VRAM:** ~0.5GB

**Steps:**
1. Load Nomic model
2. For each transcript segment: prepend `search_document: ` prefix → embed → 768-dim vector
3. L2-normalize embeddings
4. INSERT into `vec_semantic` (timestamp_ms, transcript_text, embedding)
5. Cluster segments by cosine similarity (k-means or agglomerative)
6. For each cluster: generate topic label from top keywords, compute coherence + density
7. INSERT into `topics`
8. Write provenance record

---

### Stage 11: Emotion/Energy Analysis (Wav2Vec2)

**Operation ID:** `embed_emotion`
**Required:** No
**Input:** `stems/vocals.wav`
**Output:** Rows in `vec_emotion` + `emotion_curve` tables
**Model:** Wav2Vec2 Large (emotion fine-tuned)
**VRAM:** ~1.5GB FP16, ~0.75GB NVFP4

**Steps:**
1. Load Wav2Vec2 emotion model
2. Segment audio into 5s windows with 2.5s stride
3. For each window: inference → 1024-dim embedding + arousal/valence/energy scalars
4. INSERT into `vec_emotion` (start_ms, end_ms, energy, arousal, embedding)
5. INSERT into `emotion_curve` (start_ms, end_ms, arousal, valence, energy)
6. Write provenance record

**Fallback:** Flat energy (0.5) everywhere. Highlights rely on reactions + transcript only.

---

### Stage 12: Speaker Diarization (WavLM)

**Operation ID:** `embed_speakers`
**Required:** No
**Input:** `stems/vocals.wav`
**Output:** Rows in `vec_speakers` + `speakers` tables, updates to `transcript_segments`/`transcript_words`
**Model:** WavLM Base Plus SV
**VRAM:** ~0.4GB

**Steps:**
1. Run Silero VAD → speech segment timestamps
2. Load WavLM model
3. For each speech segment: extract 512-dim X-vector
4. Cluster X-vectors (agglomerative) → unique speaker IDs
5. INSERT into `speakers` (label, total_speaking_ms, speaking_pct)
6. INSERT into `vec_speakers` (segment_text, timestamp_ms, speaker_id, embedding)
7. UPDATE `transcript_segments` SET speaker_id
8. UPDATE `transcript_words` SET speaker_id
9. Write provenance record

**Fallback:** Single "speaker_0" for all segments.

---

### Stage 13: Reaction Detection (SenseVoice)

**Operation ID:** `detect_reactions`
**Required:** No
**Input:** `stems/vocals.wav`
**Output:** Rows in `reactions` table
**Model:** SenseVoice-Small
**VRAM:** ~1.1GB

**Steps:**
1. Load SenseVoice model
2. Process audio → event tags: `<Laughter>`, `<Applause>`, `<BGM>`, etc.
3. Filter to editing-relevant: laughter, applause
4. For each event: compute confidence, duration, intensity (weak/moderate/strong)
5. Attach context_transcript (nearest transcript text)
6. INSERT into `reactions`
7. Write provenance record

---

### Stage 14: Acoustic Analysis + Beat Detection

**Operation ID:** `analyze_acoustic`
**Required:** No
**Input:** Full audio mix + music stem
**Output:** Rows in `silence_gaps`, `acoustic`, `music_sections`, `beats`, `beat_sections`
**Tools:** cuFFT (GPU), CuPy, Beat This!
**VRAM:** ~0.5GB (cuFFT) + ~1-2GB (Beat This!)

**Steps:**
1. cuFFT spectral analysis on full mix:
   - RMS energy envelope
   - Spectral centroid
   - Silence detection (gaps > 500ms)
   - Music vs speech classification
2. INSERT into `silence_gaps`, `acoustic`, `music_sections`
3. Load Beat This! model
4. Run on music stem (or full mix if no music stem):
   - Beat positions (ms), downbeat positions (ms), tempo (BPM)
5. INSERT into `beats`, `beat_sections`
6. Write provenance record

---

### Stage 15: Profanity Detection

**Operation ID:** `detect_profanity`
**Required:** No
**Input:** `transcript_words` table + key frames (for NSFW)
**Output:** Rows in `profanity_events` + `content_safety`

**Steps:**
1. Load profanity word list (~4000 words)
2. Match each word in `transcript_words` against list
3. For each match: record word (REDACTED in MCP responses), start_ms, end_ms, severity
4. INSERT into `profanity_events`
5. Optional: run CLIP-NSFW classifier on key frames (reuses SigLIP embeddings)
6. Compute content_rating: clean (0), mild (1-3), moderate (4-10), explicit (>10)
7. INSERT into `content_safety`
8. Write provenance record

---

### Stage 16: Chronemic Computation

**Operation ID:** `compute_chronemic`
**Required:** No
**Input:** `transcript_segments`, `speakers`, `silence_gaps`, `emotion_curve`
**Output:** Rows in `pacing` table

**Steps:**
1. For 60-second windows across the video:
   - words_per_minute: word count / duration
   - pause_ratio: silence duration / window duration
   - speaker_changes: count of speaker transitions
   - label: fast_dialogue (>150 WPM), normal, slow_monologue (<100 WPM), dead_air (pause >0.5)
2. INSERT into `pacing`
3. Write provenance record

---

### Stage 17: Highlight Scoring

**Operation ID:** `compute_highlights`
**Required:** No
**Input:** `emotion_curve`, `reactions`, `topics`, `scenes`, `pacing`
**Output:** Rows in `highlights` table

**Scoring formula:**
```
highlight_score(segment) =
    0.25 * emotion_energy     +
    0.20 * reaction_presence  +
    0.20 * semantic_density   +
    0.15 * narrative_completeness +
    0.10 * visual_variety     +
    0.05 * visual_quality     +
    0.05 * speaker_confidence
```

**Steps:**
1. Define candidate segments (every transcript segment or scene)
2. For each candidate: compute all 7 component scores
3. Compute weighted sum → total score
4. Generate natural language reason for each highlight
5. Select top-N highlights (configurable, default 20)
6. INSERT into `highlights` with all component scores
7. Write provenance record

---

### Stage 18: Storyboard Grid Generation

**Operation ID:** `generate_storyboards`
**Required:** No
**Input:** `frames/*.jpg`
**Output:** `storyboards/grid_NNN.jpg` + rows in `storyboard_grids`

**Steps:**
1. Compute adaptive interval: `max(duration_s / 720, 0.5)`
2. Select 720 frames at computed interval
3. Group into batches of 9 (for 3x3 grids)
4. For each batch:
   a. Create 1044x1044 composite image (3 cols × 3 rows, 348x348 per cell)
   b. Overlay timestamp text on each cell (top-left, 14px Montserrat-Bold)
   c. Save as grid_NNN.jpg (quality 80)
5. INSERT into `storyboard_grids` (grid_number, grid_path, cell_timestamps_ms, cell_metadata)
6. Write provenance record

**Output:** 80 grids. ~1.4MB per grid = ~112MB total storyboard storage.

---

### Stage 19: Finalize

**Operation ID:** `finalize`
**Required:** Yes (always runs last)

**Steps:**
1. UPDATE `stream_status` for all streams (completed/failed/skipped)
2. Compute degradation_note from failed streams
3. Verify entire provenance chain (all prior records)
4. If chain verification fails: log error, mark project status as "error"
5. If chain verification passes: mark project status as "ready"
6. Write final provenance record
7. Clean up ephemeral temp files

---

*End of Phase 1 Pipeline Spec*
