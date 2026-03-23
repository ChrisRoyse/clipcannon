# Pipeline Stages -- Current Code State

This document describes the ClipCannon pipeline as implemented in `src/clipcannon/pipeline/`. Every statement below is derived from the source code at the time of writing.

## DAG Orchestrator Design

### Topological Sort (Kahn's Algorithm)

The file `pipeline/dag.py` implements `topological_sort()` using Kahn's algorithm. It accepts a list of `PipelineStage` objects and returns a list of **levels**, where each level is a list of stages that share no mutual dependencies and can execute in parallel.

Algorithm steps:

1. Build an in-degree map and a dependents adjacency list from stage `depends_on` fields.
2. Seed the queue with all stages that have in-degree zero.
3. Process the queue level by level. For each level, decrement in-degrees of dependents; stages reaching zero enter the next queue.
4. After processing, if the number of processed stages does not equal the total stage count, raise a `PipelineError` indicating a dependency cycle. The error message includes the names of the stages involved in the cycle.

Unregistered dependencies (a stage declares a dependency on a name that is not registered) are logged as warnings and skipped rather than raising an error.

### Dependency Resolution at Runtime

`PipelineOrchestrator.run()` calls `topological_sort(self.stages)` to get the level ordering, then iterates levels sequentially. Within each level, stages run concurrently via `asyncio.gather()`.

Before running a level, `_filter_runnable()` checks each stage's dependencies:

- If a dependency is in the `_failed` set **and** that dependency stage is marked `required`, the dependent stage is skipped with `"Skipped: dependency not met"`.
- If a dependency has neither completed nor failed (e.g., was skipped from an earlier abort), the stage is also skipped.
- If a dependency failed but was **optional**, the dependent stage is still considered runnable.

### Pipeline Abort on Required Stage Failure

When a required stage fails, the orchestrator sets `pipeline_aborted = True`. All stages in subsequent levels are marked as `"skipped"` with the message `"Skipped: pipeline aborted due to required stage failure"`.

## StageResult Model

Defined in `pipeline/orchestrator.py` as a Pydantic `BaseModel`:

| Field                  | Type            | Default | Description                                  |
|------------------------|-----------------|---------|----------------------------------------------|
| `success`              | `bool`          | --      | Whether the stage completed without error    |
| `operation`            | `str`           | --      | Provenance operation identifier              |
| `error_message`        | `str \| None`   | `None`  | Error description if the stage failed        |
| `duration_ms`          | `int`           | `0`     | Wall-clock execution time in milliseconds    |
| `provenance_record_id` | `str \| None`  | `None`  | ID of the provenance record created          |

## PipelineResult Model

Defined in `pipeline/orchestrator.py` as a Pydantic `BaseModel`:

| Field              | Type                      | Default | Description                                  |
|--------------------|---------------------------|---------|----------------------------------------------|
| `project_id`       | `str`                     | --      | Project that was processed                   |
| `success`          | `bool`                    | --      | True if all required stages succeeded        |
| `total_duration_ms`| `int`                     | `0`     | Total wall-clock time for the pipeline       |
| `stage_results`    | `dict[str, StageResult]`  | `{}`    | Mapping of stage name to its result          |
| `failed_required`  | `list[str]`               | `[]`    | List of required stages that failed          |
| `failed_optional`  | `list[str]`               | `[]`    | List of optional stages that failed          |

## PipelineStage Dataclass

Defined in `pipeline/orchestrator.py` as a `@dataclass`:

| Field             | Type                  | Default           | Description                                        |
|-------------------|-----------------------|-------------------|----------------------------------------------------|
| `name`            | `str`                 | --                | Unique stage identifier                            |
| `operation`       | `str`                 | --                | Provenance operation ID for this stage             |
| `required`        | `bool`                | --                | If True, failure stops the entire pipeline         |
| `depends_on`      | `list[str]`           | `[]`              | Stage names that must complete successfully first  |
| `run`             | `StageRunFn \| None`  | `None`            | Async function implementing the stage logic        |
| `fallback_values` | `dict \| None`        | `None`            | Values to record if an optional stage fails        |

`StageRunFn` is typed as `Callable[[str, Path, Path, ClipCannonConfig], Awaitable[StageResult]]`.

## Required vs Optional Stage Classification

### Required stages (6 stages)

Failure of any required stage aborts the pipeline. All subsequent stages are skipped.

1. `probe`
2. `vfr_normalize`
3. `audio_extract`
4. `frame_extract`
5. `transcribe`
6. `finalize`

### Optional stages (15 stages)

Failure is logged but does not stop the pipeline. Downstream stages that depend only on optional stages can still attempt to run.

1. `source_separation`
2. `visual_embed`
3. `ocr`
4. `quality`
5. `shot_type`
6. `storyboard`
7. `scene_analysis`
8. `semantic_embed`
9. `speaker_embed`
10. `emotion_embed`
11. `reactions`
12. `acoustic`
13. `profanity`
14. `chronemic`
15. `highlights`

## Complete Dependency Graph

Defined in `pipeline/registry.py` in the `_STAGE_DEFS` list. The comment block in that file documents the intended level assignments.

```
Level 0: probe                     (no dependencies)
Level 1: vfr_normalize             -> probe
Level 2: audio_extract             -> vfr_normalize
         frame_extract             -> vfr_normalize
Level 3: source_separation         -> audio_extract
         visual_embed              -> frame_extract
         ocr                       -> frame_extract
         quality                   -> frame_extract
         shot_type                 -> frame_extract
         storyboard                -> frame_extract
         scene_analysis            -> frame_extract
         acoustic                  -> audio_extract
Level 4: transcribe                -> source_separation
Level 5: semantic_embed            -> transcribe
         speaker_embed             -> source_separation, transcribe
         emotion_embed             -> source_separation
         reactions                 -> source_separation
         profanity                 -> transcribe
Level 6: chronemic                 -> transcribe, speaker_embed
Level 7: highlights                -> emotion_embed, reactions, semantic_embed,
                                      visual_embed, quality, speaker_embed,
                                      chronemic
Level 8: finalize                  -> transcribe, visual_embed, ocr, quality,
                                      shot_type, storyboard, semantic_embed,
                                      speaker_embed, emotion_embed, reactions,
                                      acoustic, profanity, chronemic, highlights
```

Note: The actual level numbers at runtime depend on the topological sort output. The comment levels in the registry are approximate; the sort algorithm determines the true execution order based on the dependency edges above.

## Stage Details (All 21 Stages)

---

### 1. probe

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `probe`                                             |
| **Operation ID**| `probe`                                             |
| **Required**    | Yes                                                 |
| **Depends on**  | *(none)*                                            |
| **Module**      | `pipeline/probe.py`                                 |
| **Internal stage name** | `ffprobe_vfr`                                |

**Inputs**: Source video file path (read from `project` table `source_path` column).

**Operations**:
1. Validates the source file exists, is a file (not directory), and has a supported format suffix (checked against `SUPPORTED_FORMATS` from `tools.video_probe`).
2. Runs `ffprobe` (via `run_ffprobe()`) to extract metadata: duration_ms, resolution, fps, codec, audio_codec, audio_channels.
3. Validates that `duration_ms > 0`.
4. Runs VFR detection via `detect_vfr()`.
5. Computes SHA-256 of the source file.
6. Updates the `project` table with: `source_sha256`, `duration_ms`, `resolution`, `fps`, `codec`, `audio_codec`, `audio_channels`, `file_size_bytes`, `vfr_detected`, `status='probed'`.

**Outputs / DB writes**: `project` table (UPDATE).

**ML model**: None. Uses ffprobe (external CLI tool).

**Fallback**: None (required stage; raises `PipelineError` on failure).

---

### 2. vfr_normalize

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `vfr_normalize`                                     |
| **Operation ID**| `vfr_normalize`                                     |
| **Required**    | Yes                                                 |
| **Depends on**  | `probe`                                             |
| **Module**      | `pipeline/vfr_normalize.py`                         |
| **Internal stage name** | `ffmpeg_cfr`                                 |

**Inputs**: Source video path, `vfr_detected`, `fps`, `source_sha256` from `project` table.

**Operations**:
1. If `vfr_detected` is False, returns success immediately (no-op for CFR sources).
2. Selects the nearest standard frame rate from: `[23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0]`.
3. Attempts GPU-accelerated encoding with `h264_nvenc` (preset `p4`, CQ 18) if `rendering.use_nvenc` config is set.
4. Falls back to `libx264` (CRF 18, preset `medium`) if NVENC fails.
5. Output written to `<project_dir>/source/source_cfr.mp4`.
6. Updates `project` table with: `source_cfr_path`, `vfr_normalized=1`, `fps` (the new target fps).

**Outputs / DB writes**: `project` table (UPDATE). Creates `source_cfr.mp4` file.

**ML model**: None. Uses ffmpeg (external CLI tool).

**Fallback**: NVENC -> libx264 cascade. No further fallback (required stage).

---

### 3. audio_extract

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `audio_extract`                                     |
| **Operation ID**| `audio_extract`                                     |
| **Required**    | Yes                                                 |
| **Depends on**  | `vfr_normalize`                                     |
| **Module**      | `pipeline/audio_extract.py`                         |
| **Internal stage name** | `ffmpeg_audio`                               |

**Inputs**: Source video path (resolved via `resolve_source_path()` which prefers CFR path if available).

**Operations**:
1. Extracts `stems/audio_16k.wav`: 16 kHz mono PCM (for speech models like Whisper).
2. Extracts `stems/audio_original.wav`: native sample rate, original channels (for source separation).
3. Validates both files exist and are non-empty.

**Outputs / DB writes**: Creates two WAV files in `<project_dir>/stems/`. Provenance record only (no table inserts).

**ML model**: None. Uses ffmpeg (external CLI tool).

**Fallback**: None (required stage).

---

### 4. frame_extract

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `frame_extract`                                     |
| **Operation ID**| `frame_extract`                                     |
| **Required**    | Yes                                                 |
| **Depends on**  | `vfr_normalize`                                     |
| **Module**      | `pipeline/frame_extract.py`                         |
| **Internal stage name** | `ffmpeg_frames`                              |

**Inputs**: Source video path (resolved via `resolve_source_path()`), `duration_ms` from `project` table.

**Operations**:
1. Reads `processing.frame_extraction_fps` from config (default 2 fps).
2. Clears any existing `frame_*.jpg` in the frames directory.
3. Attempts GPU-accelerated extraction with CUDA hwaccel if `rendering.use_nvenc` is set.
4. Falls back to software decoding if GPU fails.
5. Output format: `<project_dir>/frames/frame_NNNNNN.jpg` (JPEG quality 2).
6. Validates frame count is non-zero. Warns (but does not fail) if frame count differs from expected by more than 5 frames.

**Outputs / DB writes**: Creates JPEG frame files in `<project_dir>/frames/`. Provenance record only.

**ML model**: None. Uses ffmpeg.

**Fallback**: CUDA hwaccel -> software decoding cascade. No further fallback (required stage).

---

### 5. source_separation

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `source_separation`                                 |
| **Operation ID**| `source_separation`                                 |
| **Required**    | No                                                  |
| **Depends on**  | `audio_extract`                                     |
| **Module**      | `pipeline/source_separation.py`                     |
| **Internal stage name** | `htdemucs`                                   |

**Inputs**: `<project_dir>/stems/audio_original.wav`.

**Operations**:
1. Checks if the `demucs` package is importable. Returns failure with install instructions if not.
2. Runs demucs via subprocess first (`python -m demucs --two-stems vocals -n htdemucs`).
3. If subprocess fails, falls back to the demucs Python API (`demucs.apply.apply_model` with `get_model("htdemucs")`).
4. Moves output stems from demucs temp directory to `<project_dir>/stems/`.
5. Verifies `vocals.wav` exists and is non-empty.
6. Hashes all produced stems: `vocals.wav`, `no_vocals.wav`, `drums.wav`, `bass.wav`, `other.wav`.

**Outputs / DB writes**: Creates stem WAV files in `<project_dir>/stems/`. Provenance record only.

**ML model**: `htdemucs` v4.0 (Meta's Hybrid Transformer Demucs).

**Fallback if optional stage fails**: Downstream stages (`transcribe`, `speaker_embed`, `emotion_embed`, `reactions`) use `audio_16k.wav` instead of `vocals.wav`. This fallback is handled by `resolve_audio_input()` which checks for `vocals.wav` first, then falls back to `audio_16k.wav`.

---

### 6. visual_embed

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `visual_embed`                                      |
| **Operation ID**| `visual_embedding`                                  |
| **Required**    | No                                                  |
| **Depends on**  | `frame_extract`                                     |
| **Module**      | `pipeline/visual_embed.py`                          |
| **Internal stage name** | `siglip_visual`                              |

**Inputs**: All `frame_*.jpg` files in `<project_dir>/frames/`.

**Operations**:
1. Loads SigLIP-SO400M model (`google/siglip-so400m-patch14-384`) via `transformers.AutoModel`.
2. Processes frames in batches of `processing.batch_size_visual` (config). Default batch size constant is 64.
3. Computes 1152-dimensional L2-normalized visual embeddings per frame.
4. Inserts embeddings into `vec_frames` virtual table (sqlite-vec): columns `frame_id`, `project_id`, `timestamp_ms`, `frame_path`, `visual_embedding`.
5. Detects scene boundaries by computing cosine similarity between consecutive frame embeddings. A new scene starts where similarity drops below `SCENE_THRESHOLD` (0.75, overridable via `processing.scene_change_threshold` config).
6. For each scene: records `start_ms`, `end_ms`, `key_frame_path` (first frame of scene), `key_frame_timestamp_ms`, `visual_similarity_avg`, and `dominant_colors` (top 5 hex colors extracted via PIL median-cut quantization on 64x64 thumbnail).
7. Inserts scene records into the `scenes` table.

**Outputs / DB writes**: `vec_frames` (INSERT), `scenes` (INSERT).

**ML model**: SigLIP-SO400M-patch14-384 (google). Embedding dimension: 1152.

**Fallback if optional stage fails**: Returns `StageResult(success=False)` with error message. Downstream stages (`highlights`, `shot_type`) receive no scene/embedding data and use default scores.

---

### 7. ocr

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `ocr`                                               |
| **Operation ID**| `ocr_extraction` (registry) / `ocr_detection` (module constant) |
| **Required**    | No                                                  |
| **Depends on**  | `frame_extract`                                     |
| **Module**      | `pipeline/ocr.py`                                   |
| **Internal stage name** | `paddleocr`                                  |

**Inputs**: Frame JPEG files from `<project_dir>/frames/`, processed at 1 fps (every Nth frame where N = `extraction_fps`).

**Operations**:
1. Instantiates `PaddleOCR(use_angle_cls=True, lang="en", show_log=False)`.
2. For each sampled frame: runs OCR, filters results with confidence >= 0.5.
3. Classifies text region by bounding box Y-position: `center_top` (< 25%), `center_middle` (25-67%), `bottom_third` (67-85%), `full_screen` (> 85%).
4. Estimates font size from bbox height relative to image: `small` (< 3%), `medium` (3-8%), `large` (> 8%).
5. Deduplicates consecutive identical text.
6. Detects slide transitions when > 50% of text content changes between frames.
7. Inserts text records into `on_screen_text` table.
8. Inserts slide transition events into `text_change_events` table.

**Outputs / DB writes**: `on_screen_text` (INSERT), `text_change_events` (INSERT).

**ML model**: PaddleOCR PP-OCRv5.

**Fallback if optional stage fails**: Returns `StageResult(success=False)`. If PaddleOCR is not installed, returns immediately with an ImportError message.

---

### 8. quality

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `quality`                                           |
| **Operation ID**| `quality_assessment`                                |
| **Required**    | No                                                  |
| **Depends on**  | `frame_extract`                                     |
| **Module**      | `pipeline/quality.py`                               |
| **Internal stage name** | `brisque`                                    |

**Inputs**: All `frame_*.jpg` files, plus `scenes` table records.

**Operations**:
1. Attempts `pyiqa` BRISQUE scoring (GPU-accelerated). Converts BRISQUE raw score to 0-100 scale: `quality_score = max(0, min(100, 100 - brisque_raw))`.
2. If `pyiqa` is not installed, falls back to Laplacian variance blur detection (CPU, numpy-only). Maps variance to 0-100 via `score = variance / 10.0`.
3. Classifies quality: `good` (> 60), `acceptable` (> 40), `poor` (<= 40).
4. Detects issues per scene: `heavy_blur` if min score < 30, `camera_shake` if average consecutive-frame diff > 20.
5. Updates each row in the `scenes` table with: `quality_avg`, `quality_min`, `quality_classification`, `quality_issues` (JSON array).

**Outputs / DB writes**: `scenes` (UPDATE with quality columns).

**ML model**: pyiqa BRISQUE (primary) or Laplacian variance (fallback, no ML model).

**Fallback if optional stage fails**: Returns `StageResult(success=False)`. Scenes will have NULL quality columns.

---

### 9. shot_type

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `shot_type`                                         |
| **Operation ID**| `shot_type_classification`                          |
| **Required**    | No                                                  |
| **Depends on**  | `frame_extract`                                     |
| **Module**      | `pipeline/shot_type.py`                             |
| **Internal stage name** | `siglip_zero_shot`                           |

**Inputs**: Key frame paths from the `scenes` table (`key_frame_path` column).

**Operations**:
1. Loads SigLIP-SO400M model for zero-shot image-text classification.
2. Classifies each scene's key frame against five text prompts:
   - `"an extreme close-up shot of a face"` -> `extreme_closeup`
   - `"a close-up shot"` -> `closeup`
   - `"a medium shot showing waist up"` -> `medium`
   - `"a wide shot showing full body"` -> `wide`
   - `"an establishing shot of a location"` -> `establishing`
3. Computes softmax over image-text similarity logits; selects the highest-probability label.
4. Assigns crop recommendations per shot type:
   - `extreme_closeup`, `closeup` -> `safe_for_vertical`
   - `medium` -> `needs_reframe`
   - `wide`, `establishing` -> `keep_landscape`
5. Updates each row in the `scenes` table with: `shot_type`, `shot_type_confidence`, `crop_recommendation`.

**Outputs / DB writes**: `scenes` (UPDATE with shot type columns).

**ML model**: SigLIP-SO400M-patch14-384 (google), used for zero-shot classification.

**Fallback if optional stage fails**: Returns `StageResult(success=False)`. If classification fails for a single frame, defaults to `("medium", 0.0)`.

---

### 10. transcribe

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `transcribe`                                        |
| **Operation ID**| `transcription`                                     |
| **Required**    | Yes                                                 |
| **Depends on**  | `source_separation`                                 |
| **Module**      | `pipeline/transcribe.py`                            |
| **Internal stage name** | `whisperx`                                   |

**Inputs**: Audio file resolved by `resolve_audio_input()` (prefers `vocals.wav`, falls back to `audio_16k.wav`). Config values: `processing.whisper_model`, `processing.whisper_compute_type`, `gpu.device`.

**Operations**:
1. **Primary backend**: WhisperX with wav2vec2 forced alignment for 20-50ms word-level precision.
   - Loads model via `whisperx.load_model()`.
   - Transcribes with `batch_size=16`.
   - Runs forced alignment via `whisperx.load_align_model()` and `whisperx.align()`.
2. **Fallback backend**: faster-whisper (no forced alignment, reduced precision).
   - Loads `WhisperModel` with `beam_size=5`, `word_timestamps=True`, `vad_filter=True`.
3. If neither is installed, returns failure with install instructions.
4. **Anti-hallucination filtering** (Phase 2 addition):
   - **VAD tuning**: WhisperX uses `_VAD_ONSET=0.5`, `_VAD_OFFSET=0.363`. Fallback uses `_NO_SPEECH_THRESHOLD=0.4`.
   - **Confidence thresholds**: `_LOG_PROB_THRESHOLD=-0.7`, `_COMPRESSION_RATIO_THRESHOLD=2.0`, `_HALLUCINATION_SILENCE_THRESHOLD=2.0s`.
   - **Word-level filtering**: `_MIN_WORD_CONFIDENCE=0.3` per word, `_MIN_SEGMENT_CONFIDENCE=0.4` per segment, `_MAX_COMPRESSION_RATIO=2.0`.
   - **Known hallucination phrase rejection**: 35 known phrases including YouTube artifacts ("thank you for watching", "please subscribe", "click the notification bell"), repetitive patterns, and non-speech defaults ("♪♪", "[INAUDIBLE]").
   - Segments matching known hallucination phrases are silently dropped.
   - Words below confidence threshold are removed; segments with no remaining words are dropped.
5. Inserts segments into `transcript_segments` table: `project_id`, `start_ms`, `end_ms`, `text`, `language`, `word_count`.
6. Inserts individual words into `transcript_words` table: `segment_id`, `word`, `start_ms`, `end_ms`, `confidence`.

**Outputs / DB writes**: `transcript_segments` (INSERT), `transcript_words` (INSERT).

**ML model**: WhisperX (primary, model size from config e.g. `large-v3`) + wav2vec2 alignment model. faster-whisper (fallback).

**Fallback**: WhisperX -> faster-whisper cascade. If both are missing, returns `StageResult(success=False)` which triggers a pipeline abort since this is a required stage.

---

### 11. storyboard

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `storyboard`                                        |
| **Operation ID**| `storyboard_generation`                             |
| **Required**    | No                                                  |
| **Depends on**  | `frame_extract`                                     |
| **Module**      | `pipeline/storyboard.py`                            |
| **Internal stage name** | `storyboard_grids`                           |

**Inputs**: All `frame_*.jpg` files, `duration_ms` from `project` table.

**Operations**:
1. Selects up to 720 frames at adaptive intervals. If fewer than 720 frames exist, uses all of them. Minimum interval is 0.5 seconds.
2. Groups selected frames into 3x3 grids (9 frames per grid), producing up to 80 grid images.
3. Each grid is a 1044x1044 pixel JPEG (3 columns x 348px cells). Each cell has a semi-transparent timestamp overlay bar.
4. Grid images are saved to `<project_dir>/storyboards/grid_NNN.jpg` at JPEG quality 80.
5. Inserts grid metadata into `storyboard_grids` table: `project_id`, `grid_number`, `grid_path`, `cell_timestamps_ms` (JSON array).

**Outputs / DB writes**: `storyboard_grids` (INSERT). Creates grid JPEG files in `<project_dir>/storyboards/`.

**ML model**: None. Uses PIL/Pillow for image compositing.

**Fallback if optional stage fails**: Returns `StageResult(success=False)`.

---

### 12. semantic_embed

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `semantic_embed`                                    |
| **Operation ID**| `semantic_embedding`                                |
| **Required**    | No                                                  |
| **Depends on**  | `transcribe`                                        |
| **Module**      | `pipeline/semantic_embed.py`                        |
| **Internal stage name** | `nomic_embed`                                |

**Inputs**: Transcript segments from `transcript_segments` table.

**Operations**:
1. Loads `nomic-ai/nomic-embed-text-v1.5` via `sentence-transformers.SentenceTransformer`.
2. Prefixes each segment text with `"search_document: "` before encoding.
3. Computes 768-dimensional L2-normalized embeddings.
4. Clusters segments into topics using `sklearn.cluster.AgglomerativeClustering` with `distance_threshold=1.2`, `metric="cosine"`, `linkage="average"`.
5. For each topic: extracts top-5 keywords (word frequency after stop-word removal), computes coherence (average pairwise cosine similarity within cluster), computes semantic density (`1 / (1 + mean_distance_from_centroid)`).
6. Inserts embeddings into `vec_semantic` virtual table: `segment_id`, `project_id`, `timestamp_ms`, `transcript_text`, `semantic_embedding`.
7. Inserts topics into `topics` table: `project_id`, `start_ms`, `end_ms`, `label`, `keywords` (JSON), `coherence_score`, `semantic_density`.

**Outputs / DB writes**: `vec_semantic` (INSERT), `topics` (INSERT).

**ML model**: nomic-embed-text v1.5 (nomic-ai). Embedding dimension: 768.

**Fallback if optional stage fails**: Returns `StageResult(success=False)`. If `sentence-transformers` is not installed, returns immediately with an import error message.

---

### 13. speaker_embed

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `speaker_embed`                                     |
| **Operation ID**| `speaker_diarization`                               |
| **Required**    | No                                                  |
| **Depends on**  | `source_separation`, `transcribe`                   |
| **Module**      | `pipeline/speaker_embed.py`                         |
| **Internal stage name** | `wavlm_speaker`                              |

**Inputs**: Audio file (via `resolve_audio_input()`), transcript segments from DB.

**Operations**:
1. Loads audio and resamples to 16 kHz mono (via torchaudio or scipy fallback).
2. Detects speech segments using **Silero VAD** (via `torch.hub.load("snakers4/silero-vad")`). Falls back to energy-threshold detection if Silero is unavailable.
3. Extracts 512-dimensional speaker embeddings per speech segment using **WavLM** (`microsoft/wavlm-base-plus-sv`). Mean-pools last hidden state, L2-normalizes, pads/truncates to 512 dims.
4. Clusters speakers with `AgglomerativeClustering(distance_threshold=0.7, metric="cosine", linkage="average")`.
5. Inserts speaker records into `speakers` table: `project_id`, `label` (`speaker_N`), `total_speaking_ms`, `speaking_pct`.
6. Updates `transcript_segments.speaker_id` by overlapping speech segments with transcript segments (max-overlap assignment).
7. Propagates `speaker_id` to `transcript_words` via a correlated UPDATE.
8. Inserts embeddings into `vec_speakers` virtual table: `project_id`, `segment_text`, `timestamp_ms`, `speaker_id`, `speaker_embedding`.

**Outputs / DB writes**: `speakers` (INSERT), `transcript_segments` (UPDATE), `transcript_words` (UPDATE), `vec_speakers` (INSERT).

**ML model**: Silero VAD (speech detection) + WavLM base-plus-sv (microsoft). Embedding dimension: 512.

**Fallback if optional stage fails**: If WavLM fails, all segments are assigned to `speaker_0` via `_insert_fallback_speaker()`. If no speech segments are detected, also falls back to `speaker_0`.

---

### 14. emotion_embed

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `emotion_embed`                                     |
| **Operation ID**| `emotion_analysis`                                  |
| **Required**    | No                                                  |
| **Depends on**  | `source_separation`                                 |
| **Module**      | `pipeline/emotion_embed.py`                         |
| **Internal stage name** | `wav2vec2_emotion`                           |

**Inputs**: Audio file (via `resolve_audio_input()`).

**Operations**:
1. Loads audio, resamples to 16 kHz mono.
2. Segments audio into 5-second windows with 2.5-second stride.
3. **Primary**: Loads `facebook/wav2vec2-large-960h` via transformers. Computes from last hidden state:
   - **Energy**: `RMS / (RMS + 1)`, range 0.0-1.0.
   - **Arousal**: `variance / (variance + 1)`, range 0.0-1.0.
   - **Valence**: `0.5 + mean / (|mean| + 2)`, range 0.0-1.0.
   - **Embedding**: Mean-pooled hidden states, 1024-dim float32.
4. **Fallback** (if model loading fails): Computes energy from raw audio RMS (`rms * 5.0`, clipped to 0-1), arousal from sub-window energy variance, valence fixed at 0.5, embedding is all-zeros (1024-dim).
5. Inserts into `emotion_curve` table: `project_id`, `start_ms`, `end_ms`, `arousal`, `valence`, `energy`.
6. Inserts into `vec_emotion` virtual table: `project_id`, `start_ms`, `end_ms`, `energy`, `arousal`, `emotion_embedding`.

**Outputs / DB writes**: `emotion_curve` (INSERT), `vec_emotion` (INSERT).

**ML model**: Wav2Vec2-large-960h (facebook). Embedding dimension: 1024.

**Fallback if optional stage fails**: RMS-based computation with zero embeddings.

---

### 15. reactions

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `reactions`                                         |
| **Operation ID**| `reaction_detection`                                |
| **Required**    | No                                                  |
| **Depends on**  | `source_separation`                                 |
| **Module**      | `pipeline/reactions.py`                             |
| **Internal stage name** | `sensevoice_reactions`                       |

**Inputs**: Audio file (via `resolve_audio_input()`), transcript segments from DB (for context attachment).

**Operations**:
1. Loads audio, resamples to 16 kHz mono.
2. **Primary**: FunASR SenseVoice model (`iic/SenseVoiceSmall`). Processes 3-second windows with 1.5-second stride. Detects `<laughter>` and `<applause>` tags in model output.
3. **Fallback**: Energy-based detection using spectral analysis. Classifies high-energy segments by spectral centroid, spread, and zero-crossing rate:
   - Applause: centroid > 1000 Hz, spread > 500, ZCR > 0.1.
   - Laughter: centroid > 500 Hz, ZCR > 0.05, RMS > 0.2.
   - Minimum confidence threshold: 0.3.
4. Merges overlapping reactions of the same type.
5. Attaches nearest transcript text as `context_transcript` (truncated to 200 chars).
6. Inserts into `reactions` table: `project_id`, `start_ms`, `end_ms`, `type`, `confidence`, `duration_ms`, `intensity`, `context_transcript`.

**Outputs / DB writes**: `reactions` (INSERT).

**ML model**: SenseVoice Small (FunASR, primary) or energy-based spectral analysis (fallback, no ML model).

**Fallback if optional stage fails**: Returns `StageResult(success=False)`.

---

### 16. acoustic

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `acoustic`                                          |
| **Operation ID**| `acoustic_analysis`                                 |
| **Required**    | No                                                  |
| **Depends on**  | `audio_extract`                                     |
| **Module**      | `pipeline/acoustic.py`                              |
| **Internal stage name** | `acoustic`                                   |

**Inputs**: Audio file (via `resolve_audio_input()`).

**Operations**:
1. Loads audio via scipy.io.wavfile.
2. Computes RMS energy envelope (hop_length=512, frame_length=1024).
3. Detects silence gaps: RMS < 0.01 for >= 500ms.
4. Computes average volume (dB) and dynamic range (dB) from RMS.
5. Computes spectral flatness in 2-second windows to discriminate music vs speech. Music sections: flatness < 0.3 for >= 3 seconds.
6. Beat detection: tries librosa (`librosa.beat.beat_track`) first, falls back to scipy (`find_peaks` on spectral flux).
7. Inserts into multiple tables:
   - `silence_gaps`: `project_id`, `start_ms`, `end_ms`, `duration_ms`, `type`.
   - `acoustic`: `project_id`, `avg_volume_db`, `dynamic_range_db`.
   - `music_sections`: `project_id`, `start_ms`, `end_ms`, `type`, `confidence`.
   - `beats`: `project_id`, `has_music`, `source`, `tempo_bpm`, `tempo_confidence`, `beat_positions_ms`, `downbeat_positions_ms`, `beat_count`.
   - `beat_sections`: `project_id`, `start_ms`, `end_ms`, `tempo_bpm`, `time_signature` (if music detected).

**Outputs / DB writes**: `silence_gaps` (INSERT), `acoustic` (INSERT), `music_sections` (INSERT), `beats` (INSERT), `beat_sections` (INSERT, conditional).

**ML model**: None. Uses numpy, scipy, and optionally librosa (CPU-only algorithms).

**Fallback if optional stage fails**: librosa -> scipy cascade for beats. Returns `StageResult(success=False)` on unrecoverable errors.

---

### 17. profanity

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `profanity`                                         |
| **Operation ID**| `profanity_detection`                               |
| **Required**    | No                                                  |
| **Depends on**  | `transcribe`                                        |
| **Module**      | `pipeline/profanity.py`                             |
| **Internal stage name** | `profanity`                                  |

**Inputs**: Transcript words from `transcript_words` table (joined with `transcript_segments`), word list file at `assets/profanity/wordlist.txt`.

**Operations**:
1. Resolves word list path by walking up from the module file to find `assets/profanity/wordlist.txt`. Falls back to CWD-based path.
2. Loads tab-separated word list (`word\tseverity` where severity is `severe`, `moderate`, or `mild`).
3. Matches each transcript word (lowercased, punctuation-stripped) against the word list.
4. Computes content rating by match count: `clean` (0), `mild` (1-3), `moderate` (4-10), `explicit` (>10).
5. Computes profanity density (matches per minute of video).
6. Inserts matches into `profanity_events` table: `project_id`, `word`, `start_ms`, `end_ms`, `severity`.
7. Inserts summary into `content_safety` table: `project_id`, `profanity_count`, `profanity_density`, `content_rating`.

**Outputs / DB writes**: `profanity_events` (INSERT), `content_safety` (INSERT).

**ML model**: None. Uses a static word list.

**Fallback if optional stage fails**: Returns `StageResult(success=False)`. If word list is empty, records a clean result.

---

### 18. chronemic

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `chronemic`                                         |
| **Operation ID**| `chronemic_analysis`                                |
| **Required**    | No                                                  |
| **Depends on**  | `transcribe`, `speaker_embed`                       |
| **Module**      | `pipeline/chronemic.py`                             |
| **Internal stage name** | `chronemic`                                  |

**Inputs**: `duration_ms` from `project` table, `transcript_words` (via join), `silence_gaps`, `transcript_segments` (with `speaker_id`).

**Operations**:
1. Computes metrics in 60-second non-overlapping windows (`WINDOW_MS = 60_000`):
   - **Words per minute**: Count of words whose midpoint falls in the window, divided by window duration in minutes.
   - **Pause ratio**: Total silence gap overlap with window / window duration (0.0-1.0).
   - **Speaker changes**: Count of adjacent-segment speaker_id transitions within window.
2. Classifies pacing per window:
   - `dead_air`: pause_ratio > 0.5 (highest priority).
   - `fast_dialogue`: WPM > 150.
   - `normal`: WPM >= 100.
   - `slow_monologue`: WPM < 100 and speaker_changes == 0.
3. Inserts into `pacing` table: `project_id`, `start_ms`, `end_ms`, `words_per_minute`, `pause_ratio`, `speaker_changes`, `label`.

**Outputs / DB writes**: `pacing` (INSERT).

**ML model**: None. Algorithmic computation from DB data.

**Fallback if optional stage fails**: Returns `StageResult(success=False)`. If duration is zero, returns success with `"Skipped: no duration data"`.

---

### 19. highlights

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `highlights`                                        |
| **Operation ID**| `highlight_scoring`                                 |
| **Required**    | No                                                  |
| **Depends on**  | `emotion_embed`, `reactions`, `semantic_embed`, `visual_embed`, `quality`, `speaker_embed`, `chronemic` |
| **Module**      | `pipeline/highlights.py`                            |
| **Internal stage name** | `highlights`                                 |

**Inputs**: Data from multiple tables: `emotion_curve`, `reactions`, `topics`, `scenes`, `transcript_segments`. All loaded in parallel via `asyncio.gather`.

**Operations**:
1. Generates candidate windows of 30 seconds (`CANDIDATE_WINDOW_MS = 30_000`).
2. Scores each window using seven weighted signals:

   | Signal            | Weight | Source                  | Computation                                                    |
   |-------------------|--------|------------------------|----------------------------------------------------------------|
   | Emotion energy    | 0.25   | `emotion_curve`        | Average energy of overlapping emotion records                  |
   | Reaction presence | 0.20   | `reactions`            | 1.0 if any reaction overlaps, 0.0 otherwise                   |
   | Semantic density  | 0.20   | `topics`               | Average semantic_density of overlapping topics                 |
   | Narrative         | 0.15   | `transcript_segments`  | 1.0 if window starts/ends at sentence boundary, else 0.5-0.75 |
   | Visual variety    | 0.10   | `scenes`               | Scene boundary count / expected (1 per 10s), capped at 1.0    |
   | Quality           | 0.05   | `scenes`               | Average quality_avg of overlapping scenes                      |
   | Speaker confidence| 0.05   | `transcript_segments`  | 1.0 if one speaker > 80% of segments, else 0.5                |

3. Total score = weighted sum of all signals.
4. Classifies highlight type by dominant signal: `emotional_peak`, `audience_reaction`, `key_topic`, `story_arc`, `visual_montage`, `visual_showcase`, `key_speaker_moment`, or `multi_signal`.
5. Generates a human-readable reason string.
6. Selects top-N candidates (sorted by score descending). N is from `processing.highlight_count_default` config, defaulting to 20.
7. Inserts into `highlights` table: `project_id`, `start_ms`, `end_ms`, `type`, `score`, `reason`, plus individual component scores (`emotion_score`, `reaction_score`, `semantic_score`, `narrative_score`, `visual_score`, `quality_score`, `speaker_score`).

**Outputs / DB writes**: `highlights` (INSERT).

**ML model**: None. Algorithmic scoring from pre-computed signals.

**Fallback if optional stage fails**: Returns `StageResult(success=False)`. Missing upstream data defaults to 0.5 for most signals and 0.0 for reactions.

---

### 20. scene_analysis

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `scene_analysis`                                    |
| **Operation ID**| `scene_analysis`                                    |
| **Required**    | No                                                  |
| **Depends on**  | `frame_extract`                                     |
| **Module**      | `pipeline/scene_analysis.py`                        |
| **Internal stage name** | `scene_analysis`                             |

**Inputs**: All `frame_*.jpg` files in `<project_dir>/frames/`, transcript data from `transcript_segments` table (if available).

**Operations**:
1. Creates the `scene_map` table if it does not exist.
2. Analyzes every extracted frame using OpenCV to detect scene boundaries via SSIM comparison (threshold: 0.92). Forces scene breaks after 8 seconds (`MAX_SCENE_DURATION_MS`).
3. For each frame, detects face positions using OpenCV Haar cascades or MediaPipe.
4. Identifies webcam overlay regions by detecting small face-containing rectangles in typical webcam positions (corners).
5. Detects content areas by excluding browser chrome (top 70px) and OS taskbar (bottom 50px) regions.
6. Classifies content type (code, slides, browser, terminal, etc.) based on detected text and layout patterns.
7. Computes layout recommendations (A, B, C, or D) based on face-to-screen ratio and content type.
8. Pre-computes canvas regions for all 4 layout types on a 1080x1920 (9:16) canvas:
   - Layout A: 30/70 split (speaker 576px top, screen 1344px bottom)
   - Layout B: 40/60 split (speaker 768px top, screen 1152px bottom)
   - Layout C: PIP (240px speaker circle at position (24, 140), full-screen content)
   - Layout D: Full-screen face crop
9. Aligns transcript text with each scene from the `transcript_segments` table.
10. Inserts scene records into the `scene_map` table.

**Outputs / DB writes**: `scene_map` (INSERT) -- stores per-scene face position, webcam region, content area, content type, visible text, layout recommendation, canvas regions JSON, and aligned transcript.

**ML model**: OpenCV Haar cascades for face detection (CPU-only). No GPU required.

**Fallback if optional stage fails**: The `get_scene_map` MCP tool returns an error indicating the scene analysis has not been run. Editing still works but requires manual coordinate measurement via `measure_layout` or `analyze_frame` tools.

---

### 21. finalize

| Property        | Value                                               |
|-----------------|-----------------------------------------------------|
| **Name**        | `finalize`                                          |
| **Operation ID**| `finalize`                                          |
| **Required**    | Yes                                                 |
| **Depends on**  | `transcribe`, `visual_embed`, `ocr`, `quality`, `shot_type`, `storyboard`, `semantic_embed`, `speaker_embed`, `emotion_embed`, `reactions`, `acoustic`, `profanity`, `chronemic`, `highlights` |
| **Module**      | `pipeline/finalize.py`                              |
| **Internal stage name** | `finalize`                                   |

**Inputs**: `stream_status` table, evidence tables for each stream (defined in `_STREAM_EVIDENCE` mapping), provenance chain.

**Operations**:
1. Determines final status for all pipeline streams by checking `stream_status` records and evidence tables. The evidence table mapping:
   - `source_separation` -> `silence_gaps`
   - `visual` -> `scenes`
   - `ocr` -> `on_screen_text`
   - `quality` -> `scenes`
   - `shot_type` -> `scenes`
   - `transcription` -> `transcript_segments`, `transcript_words`
   - `semantic` -> `topics`
   - `emotion` -> `emotion_curve`
   - `speaker` -> `speakers`
   - `reactions` -> `reactions`
   - `acoustic` -> `acoustic`, `silence_gaps`
   - `beats` -> `beats`
   - `chronemic` -> `pacing`
   - `storyboards` -> `storyboard_grids`
   - `profanity` -> `content_safety`
   - `highlights` -> `highlights`
2. Updates all stream_status records with final statuses.
3. Computes a degradation note listing failed/skipped streams.
4. Verifies the provenance chain via `verify_chain()`. If verification fails, sets project status to `"error"` and raises `PipelineError`.
5. Sets project status to `"ready"` in the `project` table.
6. Cleans up ephemeral files: `*.tmp`, `*.part`, `*.temp`, `__pycache__` directories.
7. Writes a final provenance record summarizing the pipeline outcome.

**Outputs / DB writes**: `stream_status` (INSERT/UPDATE), `project` (UPDATE status to `"ready"` or `"error"`).

**ML model**: None.

**Fallback**: None (required stage; raises `PipelineError` on failure).

## Graceful Degradation Mechanism

The pipeline implements graceful degradation through the required/optional stage distinction:

1. **Required stages** (`probe`, `vfr_normalize`, `audio_extract`, `frame_extract`, `transcribe`, `finalize`) must all succeed. Failure of any required stage sets `pipeline_aborted = True` and all subsequent stages are skipped.

2. **Optional stages** can fail without aborting the pipeline. When an optional stage fails:
   - The orchestrator logs the failure and records it in `stream_status` as `"failed"`.
   - The `StageResult` is stored with `success=False` and the error message.
   - The stage is added to `PipelineResult.failed_optional`.
   - Downstream stages that depend on the failed optional stage check dependencies: if a dependency failed but was optional, the dependent stage still attempts to run.

3. **Audio input resolution** (`resolve_audio_input`): If source separation fails and `vocals.wav` is unavailable, downstream audio stages (`transcribe`, `emotion_embed`, `speaker_embed`, `reactions`) fall back to `audio_16k.wav`.

4. **Model-level fallbacks**: Several stages implement cascading model fallbacks:
   - `transcribe`: WhisperX -> faster-whisper.
   - `quality`: pyiqa BRISQUE -> Laplacian variance.
   - `emotion_embed`: Wav2Vec2 -> RMS energy.
   - `speaker_embed`: Silero VAD + WavLM -> energy threshold + speaker_0 fallback.
   - `reactions`: SenseVoice (FunASR) -> energy-based spectral analysis.
   - `acoustic` (beats): librosa -> scipy.
   - `vfr_normalize`: NVENC -> libx264.
   - `frame_extract`: CUDA hwaccel -> software decoding.

5. **Finalize stage**: The finalize stage computes a degradation note listing all failed and skipped streams, which is logged as a warning. The project is still marked as `"ready"` as long as the provenance chain verifies successfully.

## Stream Status Tracking

The `dag.py` module provides `update_stream_status()` which manages the `stream_status` table. Status values are:

| Status      | When set                                             |
|-------------|------------------------------------------------------|
| `pending`   | Default / initial state                              |
| `running`   | Stage execution begins; sets `started_at`            |
| `completed` | Stage succeeds; sets `completed_at`, `duration_ms`   |
| `failed`    | Stage fails; sets `completed_at`, `error_message`, `duration_ms` |
| `skipped`   | Stage skipped due to dependency failure or pipeline abort; sets `error_message` |

The function performs an UPSERT: if a record exists for `(project_id, stream_name)`, it updates; otherwise it inserts. When status is `"running"`, it clears any previous `error_message` and sets `started_at`. When status is a terminal state (`completed`, `failed`, `skipped`), it sets `completed_at` and records the error message and duration.
