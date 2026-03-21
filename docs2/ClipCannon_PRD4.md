#### 7.4.1 Database Capabilities

| Capability | How |
|:---|:---|
| Single portable file per project | One .db file — copyable, backupable |
| Cross-stream queries | SQL JOINs across all tables by timestamp |
| Atomic writes | ACID transactions — no partial/corrupt writes |
| Vector similarity search | sqlite-vec KNN in <15ms on 28K vectors |
| Provenance audit trail | Provenance records with foreign keys in same DB |
| Analytics | GROUP BY, AVG(), SUM(), window functions |
| Concurrent pipeline writes | WAL mode — concurrent readers + writer |


#### 7.4.2 Embedding Space Isolation (No Cross-Space Comparison)

Each embedding model produces vectors in its own mathematical space. Vectors from different models are NEVER compared to each other. A 1152-dim SigLIP visual embedding and a 768-dim Nomic semantic embedding exist in entirely different spaces — computing cosine similarity between them is mathematically meaningless.

This is enforced architecturally by storing each embedding type in its own vec0 virtual table with its own dimension:

| Vector Table | Model | Dimensions | Space | Comparable With |
|:---|:---|:---|:---|:---|
| vec_frames | SigLIP SO400M | 1152 | Visual | Only other vec_frames rows (frame-to-frame visual similarity) |
| vec_semantic | Nomic Embed v1.5 | 768 | Text semantic | Only other vec_semantic rows (segment-to-segment topic similarity) |
| vec_emotion | Wav2Vec2 | 1024 | Audio emotion | Only other vec_emotion rows (emotion-to-emotion similarity) |
| vec_speakers | WavLM | 512 | Speaker voice | Only other vec_speakers rows (voice-to-voice similarity for diarization) |

sqlite-vec enforces dimension matching per table — you cannot query a 1152-dim table with a 768-dim vector. It will error.

Cross-stream correlation is done via timestamps, not vectors. To find "the moment where high visual change coincides with high emotion energy," the system JOINs tables on timestamp_ms ranges — not by comparing embedding vectors:

-- CORRECT: Join on timestamps (apples to apples within each space)
```sql
SELECT s.scene_id, s.start_ms, s.visual_similarity_avg, e.energy
FROM scenes s
JOIN emotion_curve e ON e.start_ms BETWEEN s.start_ms AND s.end_ms
WHERE s.visual_similarity_avg < 0.5   -- High visual change (within visual space)
  AND e.energy > 0.8;                 -- High emotion (within emotion space)

-- WRONG (never done): Comparing vectors across spaces
-- SELECT vec_distance_cosine(f.visual_embedding, e.emotion_embedding) -- MEANINGLESS
The derived scalar scores (energy, quality, similarity) are the bridge between spaces. Each embedding model produces its own scalars (energy 0-1, quality 0-100, similarity 0-1) which are directly comparable because they're on normalized scales. The AI reads these scalars, not the raw vectors.
```


#### 7.4.3 Vector-Metadata Co-Storage Pattern

The key advantage of sqlite-vec: vectors are stored alongside their source data in the same row. When you query for similar vectors, you get the metadata back in the same result — no second lookup.

Example: "Find frames visually similar to timestamp 845000ms":

```sql
SELECT f.frame_id, f.timestamp_ms, f.energy_score, f.quality_score,
       f.frame_path, f.distance
FROM vec_frames f
WHERE f.visual_embedding MATCH (
    SELECT visual_embedding FROM vec_frames WHERE timestamp_ms = 845000
)
AND k = 10
ORDER BY f.distance;
Returns: 10 most similar frames with their timestamps, energy scores, quality scores, and file paths — in a single query, ~10ms.
```

Example: "Find transcript segments semantically similar to 'breakthrough results'":

```sql
SELECT s.segment_id, s.transcript_text, s.timestamp_ms, s.distance
FROM vec_semantic s
WHERE s.semantic_embedding MATCH vec_encode(:query_embedding)
AND k = 5;
Returns: 5 most semantically similar segments with the actual transcript text attached — the vector and its source text come back together.
```

Example: "Identify which speaker said something similar to this utterance":

```sql
SELECT sp.speaker_id, sp.segment_text, sp.timestamp_ms, sp.distance,
       speakers.label
FROM vec_speakers sp
JOIN speakers ON speakers.speaker_id = sp.speaker_id
WHERE sp.speaker_embedding MATCH vec_encode(:query_embedding)
AND k = 3;
```

#### 7.4.3 MCP Tools Query the Database

All MCP tools internally execute SQL queries against analysis.db and return results as JSON (under 25K tokens per response). The AI never writes SQL — it calls MCP tools which encapsulate the queries.

| MCP Tool | Internal SQL | Returns |
|:---|:---|:---|
| clipcannon_get_vud_summary | SELECT * FROM project + SELECT COUNT(*) FROM scenes + SELECT * FROM speakers + SELECT * FROM highlights ORDER BY score DESC LIMIT 10 + ... | Compact overview JSON (~8K tokens) |
| clipcannon_get_analytics | SELECT * FROM scenes + SELECT * FROM topics + SELECT * FROM highlights + SELECT * FROM reactions | Structural map JSON (~18K tokens) |
| clipcannon_get_transcript | SELECT * FROM transcript_segments WHERE start_ms >= ? AND end_ms <= ? ORDER BY start_ms | Paginated transcript JSON (~12K tokens) |
| clipcannon_get_segment_detail | JOINs across emotion_curve, reactions, beats, pacing, on_screen_text for a time range | Full-resolution detail JSON (~15K tokens) |
| clipcannon_search_content | SELECT ... FROM vec_semantic WHERE semantic_embedding MATCH ? AND k = ? | Semantically similar segments with text |


### 7.3 Processing Pipeline

```
INGEST PIPELINE (clipcannon_ingest)
================================
Each step computes SHA-256 hashes and writes a provenance record.
HTDemucs runs FIRST to produce clean stems for all audio models.

1. PROBE (CPU, <1s)
   └─> FFprobe: extract duration, resolution, fps, codecs, audio channels
   └─> Detect VFR: run ffmpeg vfrdet filter (see Section 8.4)
   └─> Validate: supported format, file integrity
   └─> PROVENANCE: hash(source.mp4) → prov_001 [probe]

1.5. VFR NORMALIZATION (GPU NVDEC+NVENC, ~30-60s if VFR detected, SKIP if CFR)
   └─> If vfrdet ratio > 0.0: normalize to CFR at nearest standard rate
   └─> FFmpeg: fps filter + NVENC re-encode at CRF 18 (near-lossless)
   └─> Output: source_cfr.mp4 (becomes the working source for all subsequent steps)
   └─> If already CFR: skip, use original directly
   └─> PROVENANCE: hash(source) + hash(source_cfr.mp4) + target_fps → prov_001b [normalize_vfr]

2. EXTRACT AUDIO (GPU NVDEC + CPU, ~5s for 1hr video)
   └─> FFmpeg: demux audio → PCM 16kHz mono WAV + original sample rate WAV
   └─> Store: analysis/audio_16k.wav, analysis/audio_original.wav
   └─> PROVENANCE: hash(source) + hash(audio files) → prov_002 [extract_audio]

3. SOURCE SEPARATION (GPU, ~60-90s for 1hr audio) ★ NEW
   └─> HTDemucs: separate audio into 4 stems
   └─> Output: analysis/stems/vocals.wav, music.wav, drums.wav, other.wav
   └─> Unload HTDemucs from VRAM after completion
   └─> PROVENANCE: hash(audio_original) + hash(all stems) + model_version → prov_003 [separate_audio]

4. EXTRACT FRAMES (GPU NVDEC, ~30s for 1hr video)
   └─> FFmpeg: decode → extract 2fps JPEGs via NVDEC
   └─> Output: frames/frame_NNNNNN.jpg (7200 frames for 1hr)
   └─> PROVENANCE: hash(source) + hash(frame_manifest) → prov_004 [extract_frames]

5. TRANSCRIBE (GPU — WhisperX on VOCAL STEM, mandatory forced alignment)
   └─> WhisperX on stems/vocals.wav: transcribe + wav2vec2 forced alignment (20-50ms precision)
   └─> INSERT INTO analysis.db: transcript_segments, transcript_words
   └─> PROVENANCE → prov_005 [transcribe]

6. EMBED VISUAL (GPU — SigLIP batch inference)
   └─> SigLIP SO400M: batch=64, NVFP4 precision
   └─> INSERT INTO analysis.db: vec_frames (embedding + timestamp + frame_path)
   └─> Compute scene boundaries via sqlite-vec cosine similarity on consecutive frames
   └─> INSERT INTO analysis.db: scenes
   └─> PROVENANCE → prov_006 [embed_visual]

7. OCR TEXT DETECTION (GPU — PaddleOCR)
   └─> PP-OCRv5 on frames at 1fps, deduplicate consecutive identical text
   └─> INSERT INTO analysis.db: on_screen_text, text_change_events
   └─> PROVENANCE → prov_007 [detect_text]

8. QUALITY ASSESSMENT (GPU — pyiqa BRISQUE + DOVER-Mobile)
   └─> Batch inference on all frames, aggregate per scene via CCCL 3.2
   └─> UPDATE analysis.db: scenes SET quality_avg, quality_classification, quality_issues
   └─> PROVENANCE → prov_008 [assess_quality]

9. SHOT TYPE CLASSIFICATION (GPU — ResNet-50)
   └─> Classify 1 key frame per scene
   └─> UPDATE analysis.db: scenes SET shot_type, crop_recommendation
   └─> PROVENANCE → prov_009 [classify_shots]

10. EMBED SEMANTIC (GPU — Nomic Embed)
    └─> Embed transcript segments, cluster for topics
    └─> INSERT INTO analysis.db: vec_semantic (embedding + transcript_text), topics
    └─> PROVENANCE → prov_010 [embed_semantic]

11. EMBED EMOTION (GPU — Wav2Vec2 on VOCAL STEM)
    └─> 5s windows, 2.5s stride on stems/vocals.wav
    └─> INSERT INTO analysis.db: vec_emotion (embedding + energy + arousal), emotion_curve
    └─> PROVENANCE → prov_011 [embed_emotion]

12. EMBED SPEAKERS (GPU — WavLM on VOCAL STEM)
    └─> Extract X-vectors, cluster unique speakers
    └─> INSERT INTO analysis.db: vec_speakers (embedding + segment_text), speakers
    └─> UPDATE transcript_segments SET speaker_id, transcript_words SET speaker_id
    └─> PROVENANCE → prov_012 [embed_speakers]

13. DETECT REACTIONS (GPU — SenseVoice on VOCAL STEM)
    └─> Detect laughter, applause, BGM leakage with timestamps
    └─> INSERT INTO analysis.db: reactions
    └─> PROVENANCE → prov_013 [detect_reactions]

14. ACOUSTIC ANALYSIS + BEAT DETECTION (GPU — cuFFT + Beat This!)
    └─> cuFFT + CuPy: RMS energy, spectral features, silence detection
    └─> Beat This!: beat positions, downbeats, BPM from music stem
    └─> INSERT INTO analysis.db: silence_gaps, acoustic, music_sections, beats, beat_sections
    └─> PROVENANCE → prov_014 [analyze_acoustic]

15. PROFANITY DETECTION (CPU + GPU)
    └─> Word list match on transcript_words → INSERT INTO profanity_events
    └─> CLIP-NSFW on key frames → INSERT INTO content_safety
    └─> PROVENANCE → prov_015 [detect_profanity]

16. CHRONEMIC COMPUTATION (GPU — CuPy)
    └─> WPM, pause ratios, energy variance, speaker change rates
    └─> INSERT INTO analysis.db: pacing
    └─> PROVENANCE → prov_016 [compute_chronemic]

17. COMPUTE HIGHLIGHTS (GPU — CCCL 3.2 DeviceTopK)
    └─> Multi-signal scoring: emotion + reactions + semantic density + quality
    └─> INSERT INTO analysis.db: highlights (score, type, reason, component scores)
    └─> PROVENANCE → prov_017 [compute_highlights]

18. GENERATE STORYBOARD GRIDS (GPU — CuPy compositing)
    └─> 80 grids, adaptive interval: max(video_duration_s / 720, 0.5)
    └─> Store grid JPEGs to disk: storyboards/grid_001.jpg through grid_080.jpg
    └─> INSERT INTO analysis.db: storyboard_grids (path, timestamps per cell)
    └─> PROVENANCE → prov_018 [generate_storyboards]

19. FINALIZE + VERIFY (CPU, <1s)
    └─> UPDATE analysis.db: stream_status for all streams (completed/failed/skipped)
    └─> Verify provenance chain integrity across all 18 prior records
    └─> UPDATE session_state with pinned manifest
    └─> PROVENANCE → prov_019 [finalize]
```

All structured data goes to analysis.db.
Binary media (frames, storyboards, stems, renders) is stored on disk as files, referenced by path in the database.

TOTAL (RTX 5090, NVFP4, all models concurrent):
  ~3-5 minutes for a 1-hour source video
  ~12-18 minutes for a 4-hour source video
  (NVFP4 enables concurrent model loading — no load/unload overhead)
  (CUDA Tile kernels accelerate similarity, clustering, scoring by 100x over CPU)
  (CCCL 3.2 Top-K + Segmented Reduction accelerate highlight/quality aggregation)
PROVENANCE: 18 records in understanding chain, full integrity verification at synthesis

### 7.4 Rendering Pipeline

```
RENDER PIPELINE (clipcannon_render)
================================

1. VALIDATE EDL (CPU, <1s)
   └─> Check all time ranges are within source bounds
   └─> Validate profile compatibility

2. BUILD FILTER GRAPH (CPU, <1s)
   └─> Translate EDL into FFmpeg filter_complex string
   └─> Handle: crop, scale, transitions, captions, overlays

3. GENERATE CAPTIONS (CPU, ~2s)
   └─> Extract word timestamps for clip time range
   └─> Group into display chunks
   └─> Generate ASS subtitle file or drawtext filter chain

4. RENDER (GPU NVENC, ~10-30s per clip, up to 3 parallel on RTX 5090)
   └─> FFmpeg with hardware encoding:
       - NVDEC for decode (2 decoders available)
       - CUDA filters for crop/scale
       - NVENC for encode (3 encoders available — 3 clips simultaneously)
   └─> Output: renders/{render_id}/output.mp4
   └─> RTX 5090 encodes 1080p @ 500+ fps (5x faster than x264 CPU)

5. GENERATE THUMBNAIL (GPU, <2s)
   └─> Extract frame at specified timestamp
   └─> Apply platform-specific sizing

6. VALIDATE OUTPUT (CPU, <1s)
   └─> FFprobe: verify output matches profile specs
   └─> Check: duration, resolution, codec, bitrate, file size
```

### 7.5 Provenance Hash Chain System

Every data transformation in ClipCannon is tracked with a SHA-256 hash chain. This creates an immutable audit trail from source video to published output -- enabling debugging, replay, integrity verification, and full system visibility at every stage.


#### 7.5.1 Architecture

SOURCE VIDEO ──hash──► AUDIO EXTRACT ──hash──► TRANSCRIPT ──hash──► SEMANTIC EMBED ──hash──►
```
    │                      │                       │                      │
    │                      │                       │                      │
    ▼                      ▼                       ▼                      ▼
 ┌──────────┐         ┌──────────┐           ┌──────────┐          ┌──────────┐
 │ prov_001 │────────►│ prov_002 │──────────►│ prov_003 │─────────►│ prov_004 │──► ...
 │ sha256:  │         │ sha256:  │           │ sha256:  │          │ sha256:  │
 │ a3f7...  │         │ 8b2c...  │           │ d91e...  │          │ 4f6a...  │
 └──────────┘         └──────────┘           └──────────┘          └──────────┘
                                                                        │
                                                                        ▼
                                                              ┌─────────────────┐
                                                              │ PROVENANCE DB    │
                                                              │ (SQLite)         │
                                                              │ project_id/      │
                                                              │   provenance.db  │
                                                              └─────────────────┘
Every provenance record links to its parent(s) via parent_hash, forming a directed acyclic graph (DAG) from source to output.
```


#### 7.5.2 Provenance Record Schema

Every data transformation produces a provenance record:

```json
{
  "record_id": "prov_003",
  "project_id": "proj_abc123",
  "timestamp_utc": "2026-03-20T14:32:05.123Z",
  "operation": "transcribe",
  "stage": "understanding",
  "description": "Transcribe audio to word-level text via faster-whisper",

  "input": {
    "file_path": "analysis/audio_16k.wav",
    "sha256": "8b2c4f1a9d3e7b6c5a8f2d1e4b7c9a3f6d8e2b5c1a4f7d9e3b6c8a2f5d1e4b",
    "size_bytes": 115200000,
    "parent_record_id": "prov_002"
  },

  "output": {
    "file_path": "analysis.db:transcript_segments",
    "sha256": "d91e3f7a2b5c8d4e6f1a9b3c7d5e2f8a4b6c1d9e3f7a2b5c8d4e6f1a9b3c7d",
    "size_bytes": 245678,
    "record_count": 847
  },

  "model": {
    "name": "faster-whisper-large-v3",
    "version": "1.0.0",
    "quantization": "int8",
    "compute_type": "cuda",
    "parameters": {
      "language": "en",
      "word_timestamps": true,
      "beam_size": 5,
      "vad_filter": true
    }
  },

  "execution": {
    "duration_ms": 67452,
    "gpu_device": "cuda:0",
    "gpu_name": "NVIDIA GeForce RTX 5090",
    "vram_peak_mb": 3120,
    "cpu_threads_used": 4
  },

  "chain_hash": "SHA256(parent_hash + input.sha256 + output.sha256 + operation + model.name + model.version + model.parameters_json)",
  "chain_hash_value": "7e4a2f9d1c6b3e8a5f2d7c4b9e1a6f3d8c5b2e7a4f9d1c6b3e8a5f2d7c4b9e"
}
chain_hash computation: The chain hash incorporates the parent hash, creating an unbreakable chain. If any prior record is tampered with, all downstream chain hashes become invalid.

import hashlib, json

def compute_chain_hash(parent_hash, input_sha256, output_sha256, operation, model_name, model_version, model_params):
    payload = f"{parent_hash}|{input_sha256}|{output_sha256}|{operation}|{model_name}|{model_version}|{json.dumps(model_params, sort_keys=True)}"
    return hashlib.sha256(payload.encode()).hexdigest()
```

#### 7.5.3 Provenance Points (Every Data Transformation)

Every stage in the pipeline where data is transformed produces a provenance record:

| Stage | Operation ID | Input | Output (DB table or file) | What Is Hashed |
|:---|:---|:---|:---|:---|
| 1. Probe | probe | Source video file | project table | Source file SHA-256, FFprobe metadata |
| 1.5. VFR Normalize | normalize_vfr | Source video | source_cfr.mp4 (if VFR) | Source hash, CFR hash, target FPS |
| 2. Audio Extract | extract_audio | Source video | stems/*.wav | Source hash, WAV hashes, FFmpeg params |
| 3. Source Separation | separate_audio | Raw audio | stems/vocals.wav, music.wav, drums.wav, other.wav | Audio hash, all stem hashes, HTDemucs version |
| 4. Frame Extract | extract_frames | Source video | frames/frame_*.jpg | Source hash, frame manifest hash |
| 5. Transcribe | transcribe | stems/vocals.wav | transcript_segments, transcript_words tables | Vocal hash, DB table hash, WhisperX version |
| 6. Visual Embed | embed_visual | Frames | vec_frames + scenes tables | Frame manifest hash, vector table hash, SigLIP version |
| 7. OCR | detect_text | Frames | on_screen_text, text_change_events tables | Frame hash, table hash, PaddleOCR version |
| 8. Quality | assess_quality | Frames | scenes table (quality columns) | Frame hash, quality hash |
| 9. Shot Type | classify_shots | Key frames | scenes table (shot_type columns) | Key frame hash, classification hash |
| 10. Semantic Embed | embed_semantic | Transcript | vec_semantic + topics tables | Transcript hash, vector table hash |
| 11. Emotion Embed | embed_emotion | stems/vocals.wav | vec_emotion + emotion_curve tables | Vocal hash, vector table hash |
| 12. Speaker Embed | embed_speakers | stems/vocals.wav | vec_speakers + speakers tables | Vocal hash, vector table hash |
| 13. Reactions | detect_reactions | stems/vocals.wav | reactions table | Vocal hash, table hash |
| 14. Acoustic + Beats | analyze_acoustic | Audio + music stem | silence_gaps, beats, acoustic tables | Audio hashes, table hashes |
| 15. Profanity | detect_profanity | Transcript | profanity_events, content_safety tables | Transcript hash, table hash |
| 16. Chronemic | compute_chronemic | Multiple tables | pacing table | Input table hashes, output hash |
| 17. Highlights | compute_highlights | Multiple tables | highlights table | Input hashes, output hash |
| 18. Storyboards | generate_storyboards | Frames | storyboard_grids table + grid JPEGs | Frame hash, grid manifest hash |
| 19. Finalize | finalize | All tables | stream_status, session_state | All table hashes, chain verification |
| 20. EDL Create | create_edl | AI decision | edits table | DB state hash, EDL hash, AI model ID |
| 21. Music Generate | generate_music | ACE-Step params | background_music.wav | Params hash, WAV hash, model version + seed |
| 22. SFX Generate | generate_sfx | DSP parameters | sfx_*.wav | Params hash, WAV hash |
| 23. Audio Mix | mix_audio | Source audio + generated audio | final_mix.wav | All input hashes, mix params |
| 24. Animation Render | render_animation | Animation spec | PNG frame sequence | Spec hash, manifest hash |
| 25. Video Render | render_video | EDL + all assets | output.mp4 + renders table | EDL hash, asset hashes, FFmpeg command hash |
| 26. Publish | publish | Rendered video + metadata | publish_queue table + Platform post ID | Video hash, metadata hash, platform response |

Total: 26 provenance points per full pipeline run. Each links to its parent(s) via chain hash. All provenance records are stored in the provenance table within analysis.db.


#### 7.5.4 Provenance Storage

Provenance records are stored in the provenance table within analysis.db (the same database as all other project data):

~/.clipcannon/projects/{project_id}/analysis.db → provenance table
Schema:

```sql
CREATE TABLE provenance (
    record_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    operation TEXT NOT NULL,
    stage TEXT NOT NULL,              -- 'understanding' | 'editing' | 'rendering' | 'publishing'
    description TEXT,
```

    input_path TEXT,
    input_sha256 TEXT NOT NULL,
    input_size_bytes INTEGER,
    parent_record_id TEXT,            -- links to parent provenance record

    output_path TEXT,
    output_sha256 TEXT NOT NULL,
    output_size_bytes INTEGER,

    model_name TEXT,
    model_version TEXT,
    model_params_json TEXT,           -- JSON string of model parameters

    duration_ms INTEGER,
    gpu_device TEXT,
    vram_peak_mb INTEGER,

    chain_hash TEXT NOT NULL UNIQUE,  -- immutable chain integrity hash
    metadata_json TEXT                -- arbitrary extra data

    -- FOREIGN KEY (parent_record_id) REFERENCES provenance(record_id)
);

```sql
CREATE INDEX idx_prov_operation ON provenance(operation);
CREATE INDEX idx_prov_stage ON provenance(stage);
CREATE INDEX idx_prov_chain ON provenance(chain_hash);
CREATE INDEX idx_prov_output ON provenance(output_sha256);
```

#### 7.5.5 Provenance Verification

At any point, the entire chain can be verified:

```python
def verify_provenance_chain(project_id):
    """Walk the provenance DAG from leaves to root, verify every chain_hash."""
    records = load_all_provenance_records(project_id)
```

    for record in records:
        # Recompute chain hash from stored fields
        expected = compute_chain_hash(
            parent_hash=get_parent_chain_hash(record.parent_record_id),
            input_sha256=record.input_sha256,
            output_sha256=record.output_sha256,
            operation=record.operation,
            model_name=record.model_name or "",
            model_version=record.model_version or "",
            model_params=json.loads(record.model_params_json or "{}")
        )
        if expected != record.chain_hash:
            raise ProvenanceIntegrityError(
                f"Chain hash mismatch at {record.record_id} ({record.operation}). "
                f"Expected {expected}, got {record.chain_hash}. "
                f"Data may have been tampered with or corrupted."
            )

        # Verify output file still matches its recorded hash
        if record.output_path and os.path.exists(record.output_path):
            actual_hash = sha256_file(record.output_path)
            if actual_hash != record.output_sha256:
                raise ProvenanceIntegrityError(
                    f"File hash mismatch for {record.output_path}. "
                    f"Recorded: {record.output_sha256}, Actual: {actual_hash}. "
                    f"File has been modified since provenance was recorded."
                )

    return {"status": "verified", "records_checked": len(records)}

#### 7.5.6 Provenance Use Cases

| Use Case | How Provenance Helps |
|:---|:---|
| Debugging: "Why did the AI cut here?" | Trace the highlight that led to the cut: highlight → emotion_curve peak → Wav2Vec2 embedding → audio segment → source timestamp. Every step is hashed and verifiable. |
| Debugging: "Why is the transcript wrong?" | Check prov_004 (transcribe): see the exact Whisper model version, quantization, beam size, and audio input hash. Re-run with same params for deterministic reproduction. |
| Debugging: "Music sounds wrong" | Check prov_016 (generate_music): see the exact ACE-Step prompt, seed, guidance_scale, LoRA. Same seed + same prompt = same output. Compare with expected. |
| Audit: "Prove this video came from this source" | Walk the chain from output.mp4 back to source.mp4. Every intermediate hash is verifiable. No step can be forged without breaking the chain. |
| Replay: "Re-run with different settings" | Provenance records store all model parameters. Change one parameter, re-run from that point, and the new branch gets its own provenance chain. |
| Monitoring: "Which stage is slowest?" | Every record has duration_ms and vram_peak_mb. Query across projects to find bottlenecks: SELECT operation, AVG(duration_ms) FROM provenance GROUP BY operation ORDER BY 2 DESC. |
| Integrity: "Has anything been tampered with?" | Run clipcannon_provenance_verify. If any file has been modified or any record altered, the chain hash mismatch is immediately detected. |


#### 7.5.7 Provenance in the VUD

The VUD itself carries a provenance summary so the AI knows the lineage of the data it's reasoning about:

```json
{
  "provenance": {
    "source_file_sha256": "a3f7...",
    "vud_sha256": "9c4e...",
    "pipeline_chain_hash": "7e4a...",
    "total_provenance_records": 13,
    "stages_completed": ["probe", "extract_audio", "extract_frames", "transcribe",
                          "embed_visual", "detect_scenes", "embed_semantic", "detect_topics",
                          "embed_emotion", "embed_speakers", "analyze_acoustic",
                          "compute_chronemic", "synthesize_vud"],
    "models_used": {
      "transcription": {"name": "faster-whisper-large-v3", "version": "1.0.0", "quantization": "int8"},
      "visual": {"name": "siglip-so400m-patch14-384", "version": "1.0.0"},
      "semantic": {"name": "nomic-embed-text-v1.5", "version": "1.5.0"},
      "emotion": {"name": "wav2vec2-large-emotion", "version": "1.0.0"},
      "speaker": {"name": "wavlm-base-plus-sv", "version": "1.0.0"}
    },
    "total_processing_time_ms": 285000,
    "integrity_status": "verified"
  }
}
```

### 7.6 Face-Aware Smart Cropping

When converting landscape (16:9) source to vertical (9:16), simple center-crop loses critical content. ClipCannon implements face-aware smart cropping:

Face Detection: Run MediaPipe Face Detection on key frames (1 per scene)
Face Tracking: Interpolate face positions between key frames
Crop Window: Position the 9:16 crop window to keep primary face(s) centered
Smoothing: Apply temporal smoothing to prevent jerky crop movements
Fallback: If no faces detected, use center crop with rule-of-thirds bias

## 8. Robustness & Failure Handling

This section addresses the 8 architectural risks that would cause the system to fail in production if not mitigated.


### 8.1 Context Eviction Mitigation (Long Editing Sessions)

Problem: The AI uses ~291K tokens to understand a 4-hour video. After producing 10+ clips, the conversation exceeds 500K+ tokens and Claude Code compresses early messages — evicting the VUD summary, storyboards, and transcript pages. The AI loses its understanding of the video mid-session.

Solution: The MCP server acts as a stateful VUD cache. The AI can re-query any data at any time without it needing to persist in the conversation context. All understanding data is server-side, not context-side.

Implementation:

Server-Side VUD Cache: The MCP server holds the full VUD, all storyboard grids, and all analysis outputs in memory (or SQLite) for the duration of the session. The AI's context window is a viewport into the data, not the data itself. Data that scrolls out of context is not lost — it is re-queryable.

Pinned Context Block (~3K tokens, always in conversation): A compact manifest that the AI keeps in its working context:

```json
{
  "project_id": "proj_abc123",
  "source": "podcast_ep42.mp4",
  "duration_ms": 14400000,
  "speakers": ["Host", "Guest 1", "Guest 2"],
  "total_highlights": 24,
  "total_scenes": 142,
  "clips_produced": [
    {"clip_id": "clip_001", "range": "14:00-15:00", "platform": "tiktok", "status": "rendered"},
    {"clip_id": "clip_002", "range": "53:20-54:50", "platform": "instagram", "status": "rendered"}
  ],
  "current_task": "Producing clip_003 from highlight at 2:15:00"
}
This manifest is small enough to survive context compression and reminds the AI what it's working on.
```

Re-Query Pattern: When the AI needs data for clip #15 that was loaded for clip #3 (now evicted from context), it simply re-calls the same MCP tool:
clipcannon_get_segment_detail(project_id, start_ms=8100000, end_ms=8160000)
The MCP server returns the same data instantly from cache — no reprocessing.

Clip Registry Tool: clipcannon_get_clip_registry(project_id) returns the current list of all clips produced, their status, and what remains to be done. The AI calls this after context compression to re-orient itself.

Session Persistence: The full session state (VUD cache + clip registry + provenance records) is written to disk at {project_id}/session.db. If Claude Code crashes or the MCP connection drops, the session can be restored with clipcannon_session_restore(project_id).


### 8.2 EDL-to-FFmpeg Translation Layer

Problem: Converting JSON Edit Decision Lists into working ffmpeg -filter_complex commands is extremely error-prone. A 60-second clip with captions + lower third + music + SFX + transitions + smart crop produces a filter_complex string of 2000+ characters with dozens of named stream labels. One wrong bracket crashes the render with a cryptic FFmpeg error.

Solution: Use typed-ffmpeg v3.0 as the primary command builder. All FFmpeg commands are constructed via a type-safe Python API with IDE auto-completion, compile-time validation, and visual debugging.

Library: typed-ffmpeg (github.com/livingbio/typed-ffmpeg, MIT license)

Type safety: catches invalid filter names/parameters before execution
IDE auto-completion: every FFmpeg filter is a typed method
Reversible: can parse existing FFmpeg CLI strings back into Python objects
Visual debugger: v3.0 includes a drag-and-drop graph editor
Pure Python stdlib: no dependencies beyond Python 3.10+
Architecture:

EDL JSON (from AI)
```
    │
    ▼
EDL Validator (Section 8.5)
    │
    ▼
typed-ffmpeg Graph Builder
    ├─ Input streams (source video, audio stems, overlay PNGs, WebM assets)
    ├─ Video filters (trim, crop, scale, overlay, xfade, drawtext)
    ├─ Audio filters (atrim, amix, loudnorm, afade)
    └─ Output (NVENC encode to platform profile)
    │
    ▼
FFmpeg CLI String (auto-generated, type-validated)
    │
    ▼
subprocess.run(["ffmpeg", ...])
    │
    ▼
Rendered output.mp4
Key rule: The AI NEVER writes FFmpeg commands. The AI writes EDL JSON (a high-level declarative spec). The typed-ffmpeg translation layer converts the EDL into valid FFmpeg commands. This separation ensures that FFmpeg complexity is encapsulated in tested, type-safe code — not in LLM-generated strings.
```

Fallback: ffmpegio filtergraph module (python-ffmpegio.github.io) provides an operator-based graph construction API as an alternative.


### 8.3 WhisperX Forced Alignment

Every cut point, caption sync, and temporal alignment depends on word-level timestamp precision. WhisperX with wav2vec2 forced alignment achieves 20-50ms accuracy for word boundaries on the clean vocal stem from HTDemucs.

Pipeline:

```python
import whisperx

# Step 1: Transcribe with Whisper (batch mode for speed)
model = whisperx.load_model("large-v3", device="cuda", compute_type="float16")
audio = whisperx.load_audio("analysis/stems/vocals.wav")  # Clean vocal stem
result = model.transcribe(audio, batch_size=16)

# Step 2: Force-align with wav2vec2 (the critical accuracy step)
align_model, metadata = whisperx.load_align_model(language_code="en", device="cuda")
result = whisperx.align(
    result["segments"], align_model, metadata, audio, device="cuda",
    return_char_alignments=False
)

# Step 3: Speaker diarization (supplements WavLM Stream K)
diarize_model = whisperx.DiarizePipeline(use_auth_token="HF_TOKEN")
diarize_segments = diarize_model(audio)
result = whisperx.assign_word_speakers(diarize_segments, result)
The combination of HTDemucs (clean vocal stem) + WhisperX (forced alignment) produces the most accurate word-level timestamps achievable with current open-source models. This is the foundation every other system depends on.
```


### 8.4 Variable Frame Rate (VFR) Detection and Normalization

Problem: Phone videos, screen recordings, and game captures frequently use variable frame rate (VFR). FFmpeg's timestamp handling with VFR is unreliable. If the source is VFR, all timestamp-based alignment (frames ↔ transcript ↔ embedder data) breaks silently — the AI thinks frame at "timestamp 845000ms" shows one thing, but it actually shows something 200ms earlier or later.

Solution: Detect VFR in the PROBE step (pipeline step 1) and normalize to constant frame rate (CFR) BEFORE any other processing. The CFR-normalized copy becomes the working source for the entire pipeline.

Detection (FFmpeg vfrdet filter):

```bash
ffmpeg -i input.mp4 -vf vfrdet -an -f null - 2>&1 | grep "VFR:"
# Output: VFR:0.354167 — any value > 0.0 means variable frame rate
Normalization (MUST happen before ANY timestamp-dependent processing):

# Normalize to nearest standard CFR rate using NVDEC decode + NVENC encode
ffmpeg -hwaccel cuda -i input_vfr.mp4 \
  -vf "fps=30" \
  -c:v h264_nvenc -preset p4 -crf 18 \
  -c:a copy -vsync cfr \
  source_cfr.mp4
Pipeline integration: VFR normalization is step 1.5 — after PROBE, before EXTRACT AUDIO. If the source is already CFR (detected by vfrdet returning 0.0), this step is skipped and the original file is used directly. The provenance record captures whether normalization occurred and what target frame rate was selected.
```

Target frame rate selection: Round the source's detected maximum frame rate to the nearest standard rate (24, 25, 30, 50, 60 fps). Never upsample — if the source maxes at 24fps, normalize to 24fps.


### 8.5 EDL Timestamp Validation and Snapping

Problem: When the AI writes "source_start_ms": 845200, it is recalling a timestamp from the VUD. LLMs approximate — it might write 845200 instead of 845000, or reference a timestamp that falls mid-word. There is no guarantee the AI-specified timestamps are valid cut points.

Solution: A 3-layer timestamp validator that runs on every EDL before rendering. Each timestamp is snapped to the nearest valid cut point using a priority hierarchy: silence gap > word boundary > nearest frame.

Layer 1 — Bounds Check: Verify all timestamps fall within [0, source_duration_ms]. Reject any EDL with out-of-bounds timestamps.

Layer 2 — Silence Snap (best audio cut quality): Check if a silence gap exists within ±300ms of the specified timestamp. If yes, snap to the midpoint of the silence gap. Silence-based cuts produce zero audio artifacts.

Layer 3 — Word Boundary Snap (no mid-word cuts): For clip start points, snap to the END of the preceding word. For clip end points, snap to the START of the following word. This ensures no word is cut in half. Uses WhisperX forced-alignment timestamps (20-50ms precision).

Layer 4 — Frame Snap: Snap to the nearest extracted frame timestamp (500ms intervals at 2fps). This ensures the visual cut aligns with an actual frame rather than interpolating between frames.

Validation output (returned to the AI so it can verify):

```json
{
  "original_start_ms": 845200,
  "validated_start_ms": 845000,
  "start_snap_type": "silence_gap",
  "start_drift_ms": 200,
  "original_end_ms": 900500,
  "validated_end_ms": 900300,
  "end_snap_type": "word_boundary",
  "end_drift_ms": 200,
  "validation": "passed"
}
MCP Tool: clipcannon_validate_edl(project_id, edl) — validates all timestamps in an EDL and returns the corrected version. This is called automatically by clipcannon_create_edit before saving the EDL.
```


