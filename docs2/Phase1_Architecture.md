# Phase 1: Foundation — Architecture & Database Spec

**Version:** 1.0
**Date:** 2026-03-21

---

## 1. System Architecture

### 1.1 Process Model

Phase 1 runs 3 processes inside a Docker container:

| Process | Port | Role | Technology |
|:--------|:-----|:-----|:-----------|
| ClipCannon MCP Server | 3366 (or stdio) | MCP tool execution, pipeline orchestration | Python + FastMCP |
| License Server | 3100 | Credit billing, HMAC integrity, D1 sync | Python + HTTP |
| Dashboard | 3200 | Web UI for credits, health, provenance | Python + FastAPI |

All 3 processes share access to the filesystem (`~/.clipcannon/`) but each project's `analysis.db` is accessed by only the MCP server process (single writer).

### 1.2 GPU Management

```python
# Precision auto-selection based on GPU capability
PRECISION_MAP = {
    "12.0": "nvfp4",   # Blackwell (RTX 5090)
    "8.9":  "int8",    # Ada Lovelace (RTX 4090, 4080, etc.)
    "8.6":  "int8",    # Ampere (RTX 3090, 3080, etc.)
    "7.5":  "fp16",    # Turing (RTX 2080, 2070, etc.)
}
```

The GPU manager:
1. Detects GPU via `torch.cuda.get_device_capability()`
2. Selects precision from `PRECISION_MAP`
3. Monitors VRAM usage via `torch.cuda.memory_allocated()`
4. Manages model lifecycle (load on demand, keep resident if VRAM permits)
5. Reports health to dashboard

### 1.3 Model Loading Strategy

**RTX 5090 (32GB, NVFP4):** All 12 understanding models loaded concurrently (~10.6 GB). No load/unload overhead during pipeline execution.

**RTX 4090 (24GB, INT8):** All models fit concurrently (~21.2 GB). Tight but functional.

**RTX 3090 (24GB, INT8):** Same as 4090 but slower inference.

**RTX 3070 (8GB, FP16):** Sequential model loading required. Pipeline runs stages one at a time, loading/unloading each model. ~3x slower.

```python
class ModelManager:
    """Manages ML model lifecycle based on available VRAM."""

    def __init__(self, device: str = "cuda:0"):
        self.device = device
        self.precision = auto_detect_precision()
        self.vram_total = torch.cuda.get_device_properties(0).total_memory
        self.loaded_models: dict[str, torch.nn.Module] = {}
        self.concurrent = self.vram_total > 16 * 1024**3  # >16GB = concurrent

    def load(self, model_name: str) -> torch.nn.Module:
        """Load model if not already loaded. Evict LRU if VRAM tight."""
        ...

    def unload(self, model_name: str) -> None:
        """Unload model and free VRAM."""
        ...
```

---

## 2. Database Schema (analysis.db)

Every project gets one SQLite database file at `~/.clipcannon/projects/{project_id}/analysis.db`.

### 2.1 Pragmas (Set on Every Connection)

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-64000;        -- 64MB cache
PRAGMA foreign_keys=ON;
PRAGMA temp_store=MEMORY;
```

### 2.2 Core Tables

```sql
-- ============================================================
-- PROJECT METADATA
-- ============================================================
CREATE TABLE project (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_cfr_path TEXT,            -- NULL if source was already CFR
    duration_ms INTEGER NOT NULL,
    resolution TEXT NOT NULL,        -- "3840x2160"
    fps REAL NOT NULL,
    codec TEXT NOT NULL,
    audio_codec TEXT,
    audio_channels INTEGER,
    file_size_bytes INTEGER,
    vfr_detected BOOLEAN DEFAULT FALSE,
    vfr_normalized BOOLEAN DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'created',  -- created, analyzing, ready, error
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- TRANSCRIPT (WhisperX forced-aligned, from vocal stem)
-- ============================================================
CREATE TABLE transcript_segments (
    segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    text TEXT NOT NULL,
    speaker_id INTEGER,
    language TEXT DEFAULT 'en',
    word_count INTEGER,
    FOREIGN KEY (project_id) REFERENCES project(project_id),
    FOREIGN KEY (speaker_id) REFERENCES speakers(speaker_id)
);
CREATE INDEX idx_segments_time ON transcript_segments(project_id, start_ms, end_ms);

CREATE TABLE transcript_words (
    word_id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    confidence REAL,
    speaker_id INTEGER,
    FOREIGN KEY (segment_id) REFERENCES transcript_segments(segment_id)
);
CREATE INDEX idx_words_time ON transcript_words(start_ms, end_ms);
CREATE INDEX idx_words_segment ON transcript_words(segment_id);

-- ============================================================
-- SCENES (from SigLIP cosine similarity)
-- ============================================================
CREATE TABLE scenes (
    scene_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    key_frame_path TEXT NOT NULL,
    key_frame_timestamp_ms INTEGER NOT NULL,
    visual_similarity_avg REAL,
    dominant_colors TEXT,            -- JSON array: ["#3a2a1a", "#f0e6d2"]
    face_detected BOOLEAN DEFAULT FALSE,
    face_position_x REAL,           -- x_center_pct (0.0 - 1.0)
    face_position_y REAL,           -- y_center_pct (0.0 - 1.0)
    shot_type TEXT,                  -- extreme_closeup, closeup, medium, wide, establishing
    shot_type_confidence REAL,
    crop_recommendation TEXT,        -- safe_for_vertical, needs_reframe, keep_landscape
    quality_avg REAL,
    quality_min REAL,
    quality_classification TEXT,     -- good, acceptable, poor
    quality_issues TEXT,             -- JSON array: ["heavy_blur", "camera_shake"]
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);
CREATE INDEX idx_scenes_time ON scenes(project_id, start_ms, end_ms);

-- ============================================================
-- SPEAKERS (from WavLM clustering)
-- ============================================================
CREATE TABLE speakers (
    speaker_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    label TEXT NOT NULL,             -- "Host", "Guest", "speaker_0"
    total_speaking_ms INTEGER,
    speaking_pct REAL,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- ============================================================
-- EMOTION CURVE (from Wav2Vec2 on vocal stem)
-- ============================================================
CREATE TABLE emotion_curve (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    arousal REAL NOT NULL,           -- 0.0 - 1.0
    valence REAL NOT NULL,           -- 0.0 - 1.0
    energy REAL NOT NULL,            -- 0.0 - 1.0
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);
CREATE INDEX idx_emotion_time ON emotion_curve(project_id, start_ms);

-- ============================================================
-- TOPICS (from Nomic Embed clustering)
-- ============================================================
CREATE TABLE topics (
    topic_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    label TEXT NOT NULL,
    keywords TEXT,                   -- JSON array
    coherence_score REAL,
    semantic_density REAL,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- ============================================================
-- HIGHLIGHTS (multi-signal scored)
-- ============================================================
CREATE TABLE highlights (
    highlight_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    type TEXT NOT NULL,              -- high_energy, emotional_peak, reaction, information_dense
    score REAL NOT NULL,             -- 0.0 - 1.0
    reason TEXT NOT NULL,            -- natural language explanation
    emotion_score REAL,
    reaction_score REAL,
    semantic_score REAL,
    narrative_score REAL,
    visual_score REAL,
    quality_score REAL,
    speaker_score REAL,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);
CREATE INDEX idx_highlights_score ON highlights(project_id, score DESC);

-- ============================================================
-- REACTIONS (from SenseVoice on vocal stem)
-- ============================================================
CREATE TABLE reactions (
    reaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    type TEXT NOT NULL,              -- laughter, applause, bgm, cry
    confidence REAL,
    duration_ms INTEGER,
    intensity TEXT,                  -- weak, moderate, strong
    context_transcript TEXT,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);
CREATE INDEX idx_reactions_time ON reactions(project_id, start_ms);

-- ============================================================
-- SILENCE GAPS (from acoustic analysis)
-- ============================================================
CREATE TABLE silence_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    type TEXT,                       -- natural_break, pause, dead_air
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- ============================================================
-- ACOUSTIC FEATURES
-- ============================================================
CREATE TABLE acoustic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    avg_volume_db REAL,
    dynamic_range_db REAL,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

CREATE TABLE music_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    type TEXT,                       -- intro_music, outro_music, background_music
    confidence REAL,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- ============================================================
-- BEATS (from Beat This! on music stem)
-- ============================================================
CREATE TABLE beats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    has_music BOOLEAN DEFAULT FALSE,
    source TEXT,                     -- music_stem, full_mix
    tempo_bpm REAL,
    tempo_confidence REAL,
    beat_positions_ms TEXT,          -- JSON array of milliseconds
    downbeat_positions_ms TEXT,      -- JSON array of milliseconds
    beat_count INTEGER,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

CREATE TABLE beat_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    tempo_bpm REAL,
    time_signature TEXT,             -- "4/4", "3/4"
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- ============================================================
-- ON-SCREEN TEXT (from PaddleOCR)
-- ============================================================
CREATE TABLE on_screen_text (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    texts TEXT NOT NULL,             -- JSON array of {text, confidence, region, font_size_est}
    type TEXT,                       -- slide, lower_third, watermark, caption
    change_from_previous BOOLEAN,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

CREATE TABLE text_change_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    type TEXT,                       -- slide_transition, lower_third_appeared, text_disappeared
    new_title TEXT,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- ============================================================
-- PROFANITY / CONTENT SAFETY
-- ============================================================
CREATE TABLE profanity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    word TEXT NOT NULL,              -- REDACTED in MCP responses
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    severity TEXT,                   -- mild, moderate, severe
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

CREATE TABLE content_safety (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    profanity_count INTEGER DEFAULT 0,
    profanity_density REAL DEFAULT 0,
    content_rating TEXT DEFAULT 'unknown', -- clean, mild, moderate, explicit
    nsfw_frame_count INTEGER DEFAULT 0,
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- ============================================================
-- PACING / CHRONEMIC (derived)
-- ============================================================
CREATE TABLE pacing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    words_per_minute REAL,
    pause_ratio REAL,
    speaker_changes INTEGER,
    label TEXT,                      -- fast_dialogue, normal, slow_monologue, dead_air
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- ============================================================
-- STORYBOARD GRIDS
-- ============================================================
CREATE TABLE storyboard_grids (
    grid_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    grid_number INTEGER NOT NULL,    -- 1-80
    grid_path TEXT NOT NULL,         -- storyboards/grid_001.jpg
    cell_timestamps_ms TEXT NOT NULL, -- JSON array of 9 timestamps
    cell_metadata TEXT,              -- JSON array of per-cell stream data
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);

-- ============================================================
-- STREAM STATUS (pipeline completion tracking)
-- ============================================================
CREATE TABLE stream_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    stream_name TEXT NOT NULL,       -- source_separation, visual, ocr, quality, shot_type,
                                     -- transcription, semantic, emotion, speaker, reactions,
                                     -- acoustic, beats, chronemic, storyboards, profanity, highlights
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed, skipped
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    duration_ms INTEGER,
    FOREIGN KEY (project_id) REFERENCES project(project_id),
    UNIQUE(project_id, stream_name)
);

-- ============================================================
-- PROVENANCE HASH CHAIN
-- ============================================================
CREATE TABLE provenance (
    record_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    operation TEXT NOT NULL,         -- probe, normalize_vfr, extract_audio, etc.
    stage TEXT NOT NULL,             -- understanding, editing, rendering, publishing
    description TEXT,
    input_file_path TEXT,
    input_sha256 TEXT,
    input_size_bytes INTEGER,
    parent_record_id TEXT,
    output_file_path TEXT,
    output_sha256 TEXT,
    output_size_bytes INTEGER,
    output_record_count INTEGER,
    model_name TEXT,
    model_version TEXT,
    model_quantization TEXT,
    model_parameters TEXT,           -- JSON
    execution_duration_ms INTEGER,
    execution_gpu_device TEXT,
    execution_vram_peak_mb REAL,
    chain_hash TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES project(project_id),
    FOREIGN KEY (parent_record_id) REFERENCES provenance(record_id)
);
CREATE INDEX idx_provenance_project ON provenance(project_id, timestamp_utc);
CREATE INDEX idx_provenance_chain ON provenance(project_id, operation);
```

### 2.3 Vector Tables (sqlite-vec)

```sql
-- ============================================================
-- VECTOR TABLES (sqlite-vec virtual tables)
-- Each model's embeddings in its own table (no cross-space comparison)
-- ============================================================

-- Visual embeddings (SigLIP SO400M) — 1152 dimensions
CREATE VIRTUAL TABLE vec_frames USING vec0(
    frame_id INTEGER PRIMARY KEY,
    project_id TEXT,
    timestamp_ms INTEGER,
    frame_path TEXT,
    visual_embedding float[1152]
);

-- Semantic embeddings (Nomic Embed v1.5) — 768 dimensions
CREATE VIRTUAL TABLE vec_semantic USING vec0(
    segment_id INTEGER PRIMARY KEY,
    project_id TEXT,
    timestamp_ms INTEGER,
    transcript_text TEXT,
    semantic_embedding float[768]
);

-- Emotion embeddings (Wav2Vec2) — 1024 dimensions
CREATE VIRTUAL TABLE vec_emotion USING vec0(
    id INTEGER PRIMARY KEY,
    project_id TEXT,
    start_ms INTEGER,
    end_ms INTEGER,
    energy REAL,
    arousal REAL,
    emotion_embedding float[1024]
);

-- Speaker embeddings (WavLM) — 512 dimensions
CREATE VIRTUAL TABLE vec_speakers USING vec0(
    id INTEGER PRIMARY KEY,
    project_id TEXT,
    segment_text TEXT,
    timestamp_ms INTEGER,
    speaker_id INTEGER,
    speaker_embedding float[512]
);
```

### 2.4 Embedding Space Isolation Rules

| Vector Table | Model | Dimensions | Comparable With |
|:-------------|:------|:-----------|:---------------|
| vec_frames | SigLIP | 1152 | Only other vec_frames (frame-to-frame visual similarity) |
| vec_semantic | Nomic | 768 | Only other vec_semantic (segment-to-segment topic similarity) |
| vec_emotion | Wav2Vec2 | 1024 | Only other vec_emotion (emotion-to-emotion similarity) |
| vec_speakers | WavLM | 512 | Only other vec_speakers (voice-to-voice for diarization) |

Cross-stream correlation is done via timestamp JOINs, never via cross-table vector comparison.

---

## 3. Project Directory Structure (On Disk)

```
~/.clipcannon/
├── config.json                      # Global configuration
├── models/                          # Downloaded model weights (~15GB total)
│   ├── whisperx-large-v3/
│   ├── siglip-so400m/
│   ├── nomic-embed-text-v1.5/
│   ├── wav2vec2-emotion/
│   ├── wavlm-base-plus-sv/
│   ├── sensevoice-small/
│   ├── htdemucs/
│   ├── paddleocr-ppv5/
│   ├── beat-this/
│   ├── dover-mobile/
│   ├── resnet50-shottype/
│   └── silero-vad/
├── projects/
│   └── {project_id}/
│       ├── analysis.db              # ALL structured data + vectors + provenance
│       ├── source/
│       │   ├── original.mp4         # Source video (SACRED — never modified)
│       │   └── source_cfr.mp4       # VFR-normalized copy (only if VFR detected)
│       ├── stems/                   # HTDemucs output (REGENERABLE)
│       │   ├── vocals.wav
│       │   ├── music.wav
│       │   ├── drums.wav
│       │   └── other.wav
│       ├── frames/                  # Extracted frames at 2fps (REGENERABLE)
│       │   ├── frame_000000.jpg
│       │   └── ...
│       └── storyboards/             # 3x3 grid composites (REGENERABLE)
│           ├── grid_001.jpg
│           └── ...grid_080.jpg
└── tmp/                             # Ephemeral processing files
```

### Disk Tier Classification (Phase 1)

| Tier | Files | Auto-Delete |
|:-----|:------|:-----------|
| Sacred | original.mp4, analysis.db | Never |
| Regenerable | source_cfr.mp4, stems/*.wav, frames/*.jpg, storyboards/*.jpg | When disk space needed |
| Ephemeral | tmp/* (intermediate processing) | After pipeline step completes |

---

## 4. Provenance Chain Architecture

### 4.1 Chain Hash Computation

```python
import hashlib
import json

def compute_chain_hash(
    parent_hash: str,
    input_sha256: str,
    output_sha256: str,
    operation: str,
    model_name: str,
    model_version: str,
    model_params: dict
) -> str:
    """Compute chain hash incorporating parent hash for immutable linking."""
    payload = (
        f"{parent_hash}|{input_sha256}|{output_sha256}|"
        f"{operation}|{model_name}|{model_version}|"
        f"{json.dumps(model_params, sort_keys=True)}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()
```

### 4.2 Chain Verification Algorithm

```python
def verify_chain(project_id: str, db: sqlite3.Connection) -> bool:
    """Verify entire provenance chain for a project."""
    records = db.execute(
        "SELECT * FROM provenance WHERE project_id = ? ORDER BY timestamp_utc",
        (project_id,)
    ).fetchall()

    for record in records:
        parent = db.execute(
            "SELECT chain_hash FROM provenance WHERE record_id = ?",
            (record["parent_record_id"],)
        ).fetchone() if record["parent_record_id"] else None

        parent_hash = parent["chain_hash"] if parent else "GENESIS"

        expected = compute_chain_hash(
            parent_hash,
            record["input_sha256"],
            record["output_sha256"],
            record["operation"],
            record["model_name"] or "",
            record["model_version"] or "",
            json.loads(record["model_parameters"] or "{}")
        )

        if expected != record["chain_hash"]:
            return False  # Chain broken at this record

    return True
```

### 4.3 Provenance Points (19 in Phase 1)

| # | Operation | Input | Output | Required |
|:--|:----------|:------|:-------|:---------|
| 1 | probe | source.mp4 | project table | Yes |
| 1.5 | normalize_vfr | source.mp4 | source_cfr.mp4 | If VFR |
| 2 | extract_audio | source | audio_16k.wav + audio_original.wav | Yes |
| 3 | separate_audio | audio_original.wav | 4 stem WAVs | Yes |
| 4 | extract_frames | source | frames/*.jpg | Yes |
| 5 | transcribe | vocals.wav | transcript_segments + words | Yes |
| 6 | embed_visual | frames | vec_frames + scenes | No |
| 7 | detect_text | frames | on_screen_text + text_change_events | No |
| 8 | assess_quality | frames | scenes (quality columns) | No |
| 9 | classify_shots | key frames | scenes (shot_type columns) | No |
| 10 | embed_semantic | transcript | vec_semantic + topics | No |
| 11 | embed_emotion | vocals.wav | vec_emotion + emotion_curve | No |
| 12 | embed_speakers | vocals.wav | vec_speakers + speakers | No |
| 13 | detect_reactions | vocals.wav | reactions | No |
| 14 | analyze_acoustic | audio + stems | silence_gaps + beats + acoustic | No |
| 15 | detect_profanity | transcript | profanity_events + content_safety | No |
| 16 | compute_chronemic | multiple tables | pacing | No |
| 17 | compute_highlights | multiple tables | highlights | No |
| 18 | generate_storyboards | frames | storyboard_grids + grid JPEGs | No |
| 19 | finalize | all tables | stream_status + chain verify | Yes |

---

## 5. Billing Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ ClipCannon   │     │License Server│     │Cloudflare D1 │
│ MCP Server   │────▶│  port 3100   │────▶│ (truth)      │
│              │     │ SQLite cache │     │ Stripe hooks │
│ LicenseClient│     │ HMAC verify  │     │ Credit bal.  │
└──────────────┘     └──────────────┘     └──────────────┘
```

### Credit Operations (Phase 1)

| Operation | Credits | When Charged |
|:----------|:--------|:-------------|
| Video Analysis (full pipeline) | 10 | On clipcannon_ingest success |
| Video Analysis (failed) | 0 | Automatic refund on failure |

### HMAC Integrity

Every credit mutation is HMAC-SHA256 signed. The key is derived deterministically from the machine ID. If a balance record's HMAC doesn't match the expected value, the license server exits fatally.

```python
import hmac
import hashlib

def sign_balance(balance: int, machine_id: str) -> str:
    key = hashlib.sha256(machine_id.encode()).digest()
    return hmac.new(key, str(balance).encode(), hashlib.sha256).hexdigest()

def verify_balance(balance: int, signature: str, machine_id: str) -> bool:
    expected = sign_balance(balance, machine_id)
    return hmac.compare_digest(expected, signature)
```

---

*End of Phase 1 Architecture*
