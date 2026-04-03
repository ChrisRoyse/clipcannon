# Clone Meeting Agent — Implementation Plan

## Overview

Add a new subsystem to ClipCannon that creates AI voice/video clones which appear as selectable virtual webcam devices in Zoom, Google Meet, Microsoft Teams, and other video conferencing apps. Each clone (e.g., "Clone Boris", "Clone Nate") shows up as a separate webcam + microphone pair in the OS device list. When selected, the clone renders a real-time lip-synced avatar, listens to the meeting via system audio capture, transcribes all speech with speaker diarization, and responds only when directly addressed — answering concisely and stopping immediately.

**Test clone**: Nate (first integration target)

---

## Hard Constraints

| Constraint | Value | Rationale |
|---|---|---|
| **Voice quality (SECS)** | **>0.95 at all times** | Non-negotiable. Every utterance must pass the identity gate before reaching the virtual mic. If a candidate scores below 0.95, regenerate with best-of-N until it passes. Never degrade quality for speed. |
| **Prosody pipeline** | **Full prosody, always** | Must use prosody-aware reference selection (`prosody_select.py`) for every response. Match target style (energetic, calm, emphatic, question, etc.) based on the semantic context of the response. No flat/monotone fallback. |
| **Response behavior** | **Direct answer only** | When addressed, answer the specific question asked. No preamble, no extra context, no unsolicited information. Stop talking when the answer is complete. |
| **Resemble Enhance** | **Always on** | Every TTS output goes through denoise + 44.1kHz upsample before hitting the virtual mic. No raw 24kHz output in meetings. |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Clone Meeting Manager                        │
│  (orchestrates N clones, manages v4l2loopback + PulseAudio)     │
└──────────┬──────────────────────────────────────────┬───────────┘
           │                                          │
    ┌──────▼──────┐                           ┌──────▼──────┐
    │ Clone Nate  │                           │ Clone Boris │
    │  Instance   │                           │  Instance   │
    └──────┬──────┘                           └──────┬──────┘
           │                                          │
    ┌──────▼──────────────────────────────────────────▼───────┐
    │                    Per-Clone Pipeline                     │
    │                                                          │
    │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
    │  │ Meeting  │  │ Meeting  │  │ Address  │  │ Response│ │
    │  │ Audio    │──│ Transcr. │──│ Detect   │──│ Gen     │ │
    │  │ Capture  │  │ + Diariz │  │ (Name)   │  │ (LLM)   │ │
    │  └──────────┘  └──────────┘  └──────────┘  └────┬────┘ │
    │                                                  │      │
    │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───▼────┐ │
    │  │ Virtual  │  │ Lip Sync │  │ TTS      │  │Prosody │ │
    │  │ Webcam   │◄─│ (MuseT.  │◄─│ (0.6B +  │◄─│Select  │ │
    │  │ Output   │  │  1.5 RT) │  │  Enhance)│  │+ SECS  │ │
    │  └──────────┘  └──────────┘  └──────────┘  └────────┘ │
    │       │                                                 │
    │  ┌────▼─────┐                                          │
    │  │ Virtual  │  (TTS audio -> virtual mic)              │
    │  │ Mic Out  │                                          │
    │  └──────────┘                                          │
    └─────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

### 1. Virtual Device Layer (`src/voiceagent/meeting/devices.py`)

**Purpose**: Create and manage named v4l2loopback video devices and PulseAudio virtual audio devices per clone.

#### 1.1 Virtual Webcam (v4l2loopback)

Each clone gets a dedicated `/dev/videoN` device with a human-readable name.

**Setup (one-time, requires sudo)**:
```bash
# Create N virtual webcams (example: 2 clones)
sudo modprobe v4l2loopback \
    devices=2 \
    exclusive_caps=1,1 \
    video_nr=20,21 \
    card_label="Clone Nate","Clone Boris"
```

**Key details**:
- `exclusive_caps=1` — required for Chrome/WebRTC to recognize the device as a camera (not a capture card). Without this, Google Meet won't list it.
- `video_nr=20,21` — high numbers to avoid collision with real cameras.
- `card_label` — the name users see in Zoom/Meet webcam dropdown.
- Frames written via `pyvirtualcam.Camera(width=1280, height=720, fps=25, device="/dev/video20")`.
- Output format: RGB24 or YUYV at 720p 25fps (matches MuseTalk output).

**WSL2 limitation**: The default WSL2 kernel does not include v4l2loopback. Two options:
1. **Native Linux** (recommended for production): Works out of the box.
2. **WSL2 workaround**: Compile a custom WSL2 kernel with `CONFIG_VIDEO_V4L2=y` and `CONFIG_V4L2_LOOPBACK=m`. Alternatively, run the virtual device host on Windows-side using OBS Virtual Camera and bridge frames from WSL2 via shared memory or socket.

#### 1.2 Virtual Microphone (PulseAudio/PipeWire)

Each clone gets a virtual audio output that appears as a microphone in Zoom/Meet.

**Setup per clone**:
```bash
# Create a null sink (audio goes nowhere physically)
pactl load-module module-null-sink \
    sink_name="clone_nate_sink" \
    sink_properties=device.description="Clone_Nate_Audio"

# Remap the monitor as a source (so apps see it as a mic, not a monitor)
pactl load-module module-remap-source \
    master="clone_nate_sink.monitor" \
    source_name="clone_nate_mic" \
    source_properties=device.description="Clone Nate Mic"
```

**Key details**:
- TTS audio is played into `clone_nate_sink` via PyAudio or ffplay.
- Zoom/Meet sees `"Clone Nate Mic"` in the microphone dropdown.
- Audio format: 44100Hz mono (post-Resemble Enhance upsample).
- The `module-remap-source` trick is essential — many apps (Chrome, Zoom) filter out monitor sources from mic lists.

#### 1.3 Device Manager Class

```python
class CloneDeviceManager:
    """Create/destroy virtual webcam + mic pairs for clones."""

    def create_clone_devices(self, clone_name: str) -> CloneDevicePair
    def destroy_clone_devices(self, clone_name: str) -> None
    def list_active_clones(self) -> list[CloneDevicePair]

@dataclass
class CloneDevicePair:
    clone_name: str          # "nate", "boris"
    video_device: str        # "/dev/video20"
    video_label: str         # "Clone Nate"
    audio_sink: str          # "clone_nate_sink"
    audio_source: str        # "clone_nate_mic"
    pid: int | None          # Process ID of the clone pipeline
```

---

### 2. Meeting Audio Capture (`src/voiceagent/meeting/audio_capture.py`)

**Purpose**: Capture all meeting audio (what other participants say) in real-time for transcription.

#### Approach: PulseAudio/PipeWire Monitor Source

Capture the system audio output (the meeting audio coming through speakers/headphones):

```python
# Capture the default output monitor (hears everything Zoom plays)
ffmpeg -f pulse -i "default.monitor" -ac 1 -ar 16000 -f s16le pipe:1
```

Or via PyAudio:
```python
import pyaudio
pa = pyaudio.PyAudio()
# Find the monitor source for the default output
stream = pa.open(
    format=pyaudio.paInt16,
    channels=1,
    rate=16000,
    input=True,
    input_device_index=monitor_device_index,
    frames_per_buffer=1024,
)
```

**Key details**:
- Captures ALL audio from the meeting (all participants).
- 16kHz mono 16-bit PCM — optimal for faster-whisper.
- Runs in a dedicated thread, feeds audio chunks to the transcription pipeline.
- Must NOT capture the clone's own TTS output (echo). Solution: the clone's TTS goes to its own null sink, not to the default output.

---

### 3. Real-Time Transcription + Diarization (`src/voiceagent/meeting/transcriber.py`)

**Purpose**: Continuously transcribe meeting audio with speaker identification.

#### 3.1 Streaming Transcription

Use faster-whisper in streaming mode (already in the codebase):

```python
from faster_whisper import WhisperModel

model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")

# Process in 5-second sliding windows with 1s overlap
segments, info = model.transcribe(
    audio_chunk,
    language="en",
    vad_filter=True,
    vad_parameters={"min_silence_duration_ms": 300},
)
```

**Key details**:
- Reuses the existing `ASR_MODEL = "large-v3-turbo"` from `pipecat_agent.py`.
- 5-second windows with 1-second overlap for continuous recognition.
- VAD pre-filtering to skip silence (saves GPU).
- Maintains a rolling transcript buffer (last 10 minutes) for context.

#### 3.2 Speaker Diarization

Use pyannote.audio community-1 (latest open-source, MIT license):

```python
from pyannote.audio import Pipeline

diarization = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-community-1",
    use_auth_token="HF_TOKEN",
)

# Process each 30-second chunk
result = diarization(audio_chunk)
for turn, _, speaker in result.itertracks(yield_label=True):
    # turn.start, turn.end, speaker = "SPEAKER_00", "SPEAKER_01", etc.
```

**Key details**:
- Runs on 30-second chunks with speaker embedding carryover for consistency.
- Labels speakers as SPEAKER_00, SPEAKER_01, etc.
- If participants introduce themselves, map names to speaker IDs via transcript matching (e.g., "Hi, I'm Sarah" → SPEAKER_02 = Sarah).
- CPU-capable but GPU-accelerated. ~2GB VRAM on GPU.

#### 3.3 Transcript Store

```python
@dataclass
class MeetingTranscript:
    segments: list[TranscriptSegment]  # Rolling buffer, last 10 min
    speaker_map: dict[str, str]        # SPEAKER_00 -> "Sarah"
    clone_name: str                     # Which clone this transcript belongs to

@dataclass
class TranscriptSegment:
    start_ms: int
    end_ms: int
    text: str
    speaker_id: str          # "SPEAKER_00"
    speaker_name: str | None # "Sarah" (if identified)
    timestamp: datetime
```

---

### 4. Address Detection (`src/voiceagent/meeting/address_detector.py`)

**Purpose**: Detect when someone in the meeting is speaking to/asking a question of the clone.

#### Multi-Signal Detection

1. **Name mention** (primary signal):
   - Scan each transcript segment for the clone's name or aliases.
   - Fuzzy match: "Nate", "Hey Nate", "Nate can you", "what do you think Nate".
   - Use sentence embedding similarity as backup (same approach as existing `VoiceCommandDetector`).

2. **Direct question detection** (secondary signal):
   - If the clone's name appears within 5 seconds of a question mark or rising intonation.
   - Questions directed "at the screen" when clone is the only other participant.

3. **Contextual addressing** (tertiary signal):
   - Track conversation flow — if someone says "what do you think?" and the clone was the last topic, it's likely addressed to the clone.
   - Conservative: only trigger on high-confidence matches. Silence is better than false triggers.

```python
class AddressDetector:
    """Detect when the clone is being addressed in a meeting."""

    def __init__(self, clone_name: str, aliases: list[str] | None = None):
        self.clone_name = clone_name
        self.aliases = aliases or [clone_name]
        self._embedding_model = None  # Lazy load

    def check_segment(
        self, segment: TranscriptSegment, recent_context: list[TranscriptSegment],
    ) -> AddressResult:
        """Returns (is_addressed, confidence, extracted_question)."""

    def extract_question(
        self, segment: TranscriptSegment, context: list[TranscriptSegment],
    ) -> str:
        """Extract the actual question/query from the addressing segment + context."""
```

**Threshold**: Only trigger response when confidence > 0.8. In ambiguous cases, stay silent.

---

### 5. Response Generation (`src/voiceagent/meeting/responder.py`)

**Purpose**: Generate a concise, direct answer to the question asked of the clone.

#### LLM Integration

Reuses the existing Ollama/Qwen3 integration from the voice agent:

```python
class MeetingResponder:
    """Generate meeting-appropriate responses for clones."""

    SYSTEM_PROMPT = (
        "You are {clone_name}, attending a video meeting. "
        "You have been directly asked a question. "
        "Answer ONLY the specific question asked. "
        "Be direct and concise — 1-3 sentences maximum. "
        "Do not volunteer additional information. "
        "Do not ask follow-up questions. "
        "Do not use filler phrases like 'great question' or 'that's interesting'. "
        "Stop talking as soon as you have answered the question. "
        "No markdown, no lists, no formatting — this is spoken conversation."
    )

    def generate_response(
        self,
        question: str,
        meeting_context: list[TranscriptSegment],  # Last 2 min for context
        clone_name: str,
    ) -> str:
        """Generate a direct answer to the question."""
```

**Key details**:
- Uses same `qwen3:14b-nothink` (or 8b-nothink) Ollama model.
- Meeting transcript context window: last 2 minutes of conversation (not full 10 min — LLM doesn't need that much).
- Max tokens: 150 (enforced hard — prevents rambling).
- Temperature: 0.4 (lower than conversational — meeting responses should be precise).

---

### 6. Voice Synthesis with Full Prosody (`src/voiceagent/meeting/voice_output.py`)

**Purpose**: Convert the response text to speech in the clone's voice with full prosody and SECS >0.95 verification.

#### Pipeline

```
Response text
    │
    ▼
Prosody style analysis (from response semantics)
    │
    ▼
Reference clip selection (prosody_select.py)
    │
    ▼
TTS synthesis (faster-qwen3-tts 0.6B, Full ICL mode)
    │
    ▼
SECS verification (>0.95 hard gate)
    │  ├─ PASS → continue
    │  └─ FAIL → regenerate (best-of-N, up to 5 candidates)
    │             └─ All fail → use ClipCannon 1.7B as fallback
    ▼
Resemble Enhance (denoise + 44.1kHz upsample)
    │
    ▼
Virtual microphone output
```

#### Prosody-Aware Reference Selection

For EVERY response, analyze the semantic content to determine the appropriate prosody style:

```python
def determine_prosody_style(response_text: str, question_context: str) -> str:
    """Map response semantics to prosody style.

    Styles (from prosody_select.py):
        energetic, calm, emphatic, varied, fast, slow, rising, question, best
    """
    # Question responses → "varied" or "calm" depending on content
    # Agreement → "calm"
    # Disagreement/correction → "emphatic"
    # Technical explanation → "slow" + "calm"
    # Excitement/positive → "energetic"
    # Uncertainty → "rising"
```

Then select the best reference clip from the voice profile's prosody segments:

```python
from clipcannon.voice.prosody_select import select_prosody_reference

ref_clip = select_prosody_reference(
    prosody_db_path=prosody_db,
    voice_name=clone_name,
    target_style=prosody_style,
)
```

#### SECS Verification (Hard >0.95 Gate)

Every synthesized utterance MUST pass identity verification before output:

```python
from clipcannon.voice.verify import VoiceVerifier

verifier = VoiceVerifier()

async def synthesize_verified(
    text: str,
    clone_name: str,
    prosody_style: str,
) -> np.ndarray:
    """Synthesize with SECS >0.95 guarantee.

    Best-of-N strategy: generate up to 5 candidates, pick best SECS.
    If none exceed 0.95, fall back to ClipCannon 1.7B model.
    """
    candidates = []
    for attempt in range(5):
        audio = await tts_adapter.synthesize(text)
        secs_score = verifier.compute_secs(audio, reference_embedding)

        if secs_score >= 0.95:
            return await enhance(audio)  # Resemble Enhance

        candidates.append((audio, secs_score))

    # Best-of-N: return highest scoring candidate if any > 0.93
    best_audio, best_score = max(candidates, key=lambda x: x[1])
    if best_score >= 0.93:
        logger.warning("SECS %.3f (below 0.95, best of 5)", best_score)
        return await enhance(best_audio)

    # Nuclear fallback: use full 1.7B model
    logger.warning("All 0.6B candidates below 0.93, using 1.7B fallback")
    from clipcannon.voice.inference import VoiceSynthesizer
    synth = VoiceSynthesizer()
    result = await synth.speak(text, voice_profile=clone_name)
    return await enhance(result.audio)
```

#### Resemble Enhance (Always On)

```python
from clipcannon.voice.enhance import enhance_speech

async def enhance(audio: np.ndarray) -> np.ndarray:
    """Denoise + upsample 24kHz → 44.1kHz broadcast quality."""
    return await enhance_speech(audio, sample_rate=24000)
```

---

### 7. Real-Time Lip Sync — MuseTalk 1.5 (`src/voiceagent/meeting/lip_sync_rt.py`)

**Purpose**: Generate lip-synced video frames at 25+ FPS for the virtual webcam.

#### Why MuseTalk 1.5 (Not LatentSync)

Per the project's own findings (memory: `feedback_lipsync_quality_v2.md`), LatentSync has architectural VAE blur that makes it unsuitable for real-time use. MuseTalk 1.5 is the confirmed best alternative:
- **30+ FPS** on V100/A5000 class GPUs (real-time capable).
- **MIT license** — no commercial restrictions.
- **256x256 face region** — lightweight, composited onto full frame.
- **Latent space inpainting** — only the mouth region is regenerated, preserving identity.
- **Training code open-sourced** (April 2025) — can fine-tune on clone's face.

#### Pipeline

```
TTS audio chunks (streaming)
    │
    ▼
MuseTalk 1.5 inference (GPU)
    │  Input: reference face image + audio mel spectrogram
    │  Output: 256x256 face frame with synced lips
    │
    ▼
Face compositing onto base frame (720p)
    │  Reference driver frame (static or looping video)
    │  + MuseTalk lip region overlay
    │
    ▼
pyvirtualcam → /dev/videoN ("Clone Nate")
```

#### Idle State (Not Speaking)

When the clone is not actively responding:
- Display a static or subtly animated idle frame (slight head movement loop from a short driver video, 3-5 seconds looped).
- No lip movement.
- Optional: periodic blink animation (pre-rendered, composited).
- Frame rate can drop to 10 FPS during idle to save GPU.

#### Speaking State

When the clone is responding:
- MuseTalk processes TTS audio in real-time.
- Output composited at 25 FPS to virtual webcam.
- Face region tracked and composited onto the base frame.

#### VRAM Budget

| Component | VRAM |
|---|---|
| MuseTalk 1.5 (UNet + VAE decoder) | ~3 GB |
| faster-whisper large-v3-turbo (ASR) | ~3 GB |
| faster-qwen3-tts 0.6B (TTS) | ~4 GB |
| pyannote diarization | ~2 GB |
| Resemble Enhance | ~1 GB |
| Overhead | ~3 GB |
| **Total per clone** | **~16 GB** |

**Multi-clone strategy**: On a 32GB GPU (RTX 5090), run 1 clone with all models resident. For 2+ clones, share ASR/LLM/diarization models across clones (they process the same meeting audio), and time-slice MuseTalk + TTS (only one clone speaks at a time).

---

### 8. Clone Meeting Manager (`src/voiceagent/meeting/manager.py`)

**Purpose**: Top-level orchestrator that ties everything together.

```python
class CloneMeetingManager:
    """Orchestrate multiple meeting clones."""

    def __init__(self, config: MeetingConfig):
        self.device_manager = CloneDeviceManager()
        self.clones: dict[str, CloneInstance] = {}

    async def start_clone(
        self,
        clone_name: str,
        voice_profile: str,
        driver_video: str | None = None,
        driver_image: str | None = None,
    ) -> CloneInstance:
        """Start a clone: create devices, launch pipeline."""

    async def stop_clone(self, clone_name: str) -> None:
        """Stop a clone: tear down pipeline, destroy devices."""

    async def stop_all(self) -> None:
        """Stop all clones and clean up."""


class CloneInstance:
    """A running clone with all pipeline components."""

    clone_name: str
    devices: CloneDevicePair
    audio_capture: MeetingAudioCapture
    transcriber: MeetingTranscriber
    address_detector: AddressDetector
    responder: MeetingResponder
    voice_output: MeetingVoiceOutput   # Full prosody + SECS gate
    lip_sync: RealtimeLipSync          # MuseTalk 1.5
    webcam_writer: VirtualWebcamWriter # pyvirtualcam

    async def run(self) -> None:
        """Main loop: capture → transcribe → detect → respond → speak → render."""
```

---

### 9. Meeting Transcript Storage & Retrieval (`src/voiceagent/meeting/transcript_store.py`)

**Purpose**: Persist every meeting's full transcript, speaker attribution, clone responses, and metadata so users can find and review any meeting at any time — days, weeks, or months later.

#### Design Philosophy (UX-First)

The user should never have to think about "saving" a transcript. It happens automatically. Finding a past meeting should be as easy as searching email — by date, by person, by keyword, by what was discussed. No file management, no export steps, no "where did I put that?"

#### 9.1 Database Schema

Stored in `~/.voiceagent/meetings.db` (shared across all clones, separate from `agent.db`).

```sql
-- A single meeting session (one per Zoom/Meet call)
CREATE TABLE IF NOT EXISTS meetings (
    meeting_id    TEXT PRIMARY KEY,           -- UUID
    title         TEXT NOT NULL DEFAULT '',   -- Auto-generated or user-set
    started_at    TEXT NOT NULL,              -- ISO-8601
    ended_at      TEXT,                       -- ISO-8601, set on meeting end
    duration_ms   INTEGER DEFAULT 0,         -- Computed on end
    clone_names   TEXT NOT NULL DEFAULT '[]', -- JSON array: ["nate", "boris"]
    participant_names TEXT NOT NULL DEFAULT '[]', -- JSON array: ["Sarah", "SPEAKER_01"]
    summary       TEXT DEFAULT '',            -- LLM-generated summary (post-meeting)
    topic_tags    TEXT DEFAULT '[]',          -- JSON array: ["project update", "Q3 budget"]
    platform      TEXT DEFAULT 'unknown',     -- "zoom", "google_meet", "teams", "unknown"
    status        TEXT NOT NULL DEFAULT 'active',  -- active, ended, archived
    metadata_json TEXT DEFAULT '{}',          -- Extensible metadata
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Every utterance in the meeting (what was said, by whom, when)
CREATE TABLE IF NOT EXISTS meeting_segments (
    segment_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id    TEXT NOT NULL REFERENCES meetings(meeting_id),
    start_ms      INTEGER NOT NULL,          -- Offset from meeting start
    end_ms        INTEGER NOT NULL,
    text          TEXT NOT NULL,
    speaker_id    TEXT NOT NULL DEFAULT '',   -- "SPEAKER_00", "clone_nate", etc.
    speaker_name  TEXT DEFAULT '',            -- "Sarah", "Nate (clone)", etc.
    is_clone      INTEGER DEFAULT 0,         -- 1 if this is clone speech
    clone_name    TEXT DEFAULT '',            -- Which clone spoke (if is_clone)
    confidence    REAL DEFAULT 0.0,          -- ASR confidence
    segment_type  TEXT DEFAULT 'speech',     -- speech, question, response, silence
    secs_score    REAL DEFAULT 0.0,          -- SECS score if clone speech
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Clone interactions: when a clone was addressed and how it responded
CREATE TABLE IF NOT EXISTS meeting_interactions (
    interaction_id TEXT PRIMARY KEY,          -- UUID
    meeting_id     TEXT NOT NULL REFERENCES meetings(meeting_id),
    clone_name     TEXT NOT NULL,             -- Which clone was addressed
    question_text  TEXT NOT NULL,             -- What was asked
    response_text  TEXT NOT NULL,             -- What the clone said
    questioner     TEXT DEFAULT '',           -- Who asked (speaker name/ID)
    question_at_ms INTEGER NOT NULL,         -- When the question happened
    response_at_ms INTEGER NOT NULL,         -- When the clone responded
    latency_ms     INTEGER DEFAULT 0,        -- Time from question end to response start
    secs_score     REAL DEFAULT 0.0,         -- Voice quality of the response
    prosody_style  TEXT DEFAULT '',           -- Prosody style used
    address_confidence REAL DEFAULT 0.0,     -- How confident the address detection was
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes for fast retrieval
CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings(started_at);
CREATE INDEX IF NOT EXISTS idx_meetings_status ON meetings(status);
CREATE INDEX IF NOT EXISTS idx_segments_meeting ON meeting_segments(meeting_id, start_ms);
CREATE INDEX IF NOT EXISTS idx_segments_speaker ON meeting_segments(meeting_id, speaker_name);
CREATE INDEX IF NOT EXISTS idx_segments_text ON meeting_segments(text);  -- For LIKE search
CREATE INDEX IF NOT EXISTS idx_interactions_meeting ON meeting_interactions(meeting_id);
CREATE INDEX IF NOT EXISTS idx_interactions_clone ON meeting_interactions(clone_name, created_at);
```

#### 9.2 Auto-Save Behavior

Transcripts are saved **continuously during the meeting**, not just at the end. If the process crashes or the user kills it, everything up to that point is preserved.

```python
class MeetingTranscriptStore:
    """Persistent meeting transcript storage with auto-save."""

    def __init__(self, db_path: str = "~/.voiceagent/meetings.db"):
        self._db_path = Path(db_path).expanduser()
        self._init_db()

    def create_meeting(self, clone_names: list[str]) -> str:
        """Called when clone joins a meeting. Returns meeting_id."""

    def append_segment(self, meeting_id: str, segment: TranscriptSegment) -> None:
        """Called in real-time as each segment is transcribed.
        Writes immediately — no batching, no buffering.
        If process crashes, all segments up to this point are safe."""

    def record_interaction(
        self, meeting_id: str, interaction: CloneInteraction,
    ) -> None:
        """Called when a clone responds to a question."""

    def end_meeting(self, meeting_id: str) -> MeetingSummary:
        """Called when clone leaves or meeting ends.
        Generates summary, sets ended_at, computes duration.
        Returns a summary the user can immediately see."""

    def search(self, query: str, ...) -> list[MeetingResult]:
        """Full-text search across all meetings."""

    def get_meeting(self, meeting_id: str) -> FullMeetingRecord:
        """Get complete meeting with all segments and interactions."""

    def list_meetings(self, ...) -> list[MeetingSummaryRow]:
        """List meetings with filtering and pagination."""
```

**Key UX decisions**:
- Segments written to SQLite on every transcription callback (~every 5 seconds). WAL mode ensures no locking contention.
- Meeting auto-ends if no audio for 5 minutes (configurable). No action required from user.
- If the clone process is killed (Ctrl+C, crash, system reboot), the meeting record still exists with all segments written up to that point. `ended_at` is NULL, `status` stays "active". On next startup, stale active meetings are detected and auto-closed.

#### 9.3 Post-Meeting Summary Generation

When a meeting ends, the LLM generates a concise summary from the full transcript:

```python
async def _generate_meeting_summary(
    self, meeting_id: str, segments: list[TranscriptSegment],
) -> str:
    """Generate a 3-5 bullet summary of the meeting.

    Uses the same Ollama/Qwen3 LLM as the clone responses.
    Runs in background — meeting end isn't blocked by this.
    """
    # Prompt: "Summarize this meeting transcript in 3-5 bullet points.
    #          Focus on decisions made, action items, and key discussion points.
    #          Do not include small talk or greetings."
```

Also auto-generates topic tags from the summary for filtering.

Also auto-generates a title if none was set (e.g., "Project Sync with Sarah and Mike — Apr 3, 2026").

#### 9.4 Dashboard Integration (Meeting History UI)

Extend the existing ClipCannon dashboard (port 3200) with meeting transcript pages.

**New API endpoints** (`src/clipcannon/dashboard/routes/meetings.py`):

```
GET  /api/meetings                        — List all meetings (paginated, filterable)
GET  /api/meetings/{meeting_id}           — Full meeting detail + transcript
GET  /api/meetings/{meeting_id}/transcript — Transcript segments only (paginated)
GET  /api/meetings/{meeting_id}/interactions — Clone Q&A interactions only
GET  /api/meetings/search?q=budget        — Full-text search across all meetings
POST /api/meetings/{meeting_id}/title     — Update meeting title
POST /api/meetings/{meeting_id}/archive   — Archive a meeting
GET  /api/meetings/export/{meeting_id}    — Export as Markdown, JSON, or SRT
```

**List View** (`/meetings`):

The default landing page for meeting history. Designed for quick scanning:

```
┌─────────────────────────────────────────────────────────┐
│  Meeting History                          [Search... 🔍] │
│                                                          │
│  Filter: [All] [This Week] [This Month]  Clone: [All ▾] │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │ 📅 Apr 3, 2026 · 10:30 AM · 47 min               │  │
│  │ Project Sync with Sarah and Mike                   │  │
│  │ Clone Nate · 3 questions answered                  │  │
│  │ Tags: project update, Q3 timeline                  │  │
│  │ "Discussed the Q3 launch date and agreed to..."    │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │ 📅 Apr 2, 2026 · 2:00 PM · 32 min                │  │
│  │ Weekly Standup                                     │  │
│  │ Clone Nate, Clone Boris · 5 questions answered     │  │
│  │ Tags: standup, sprint review                       │  │
│  │ "Sprint 14 is on track. Three blockers raised..."  │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  [Load More]                                             │
└─────────────────────────────────────────────────────────┘
```

**Detail View** (`/meetings/{id}`):

Full transcript with speaker-color-coded segments, clone interactions highlighted, and easy navigation:

```
┌──────────────────────────────────────────────────────────┐
│  ← Back to Meetings                                      │
│                                                          │
│  Project Sync with Sarah and Mike          [Edit Title]  │
│  Apr 3, 2026 · 10:30 - 11:17 AM · 47 min               │
│  Clone: Nate · Participants: Sarah, Mike, SPEAKER_02     │
│                                                          │
│  [Transcript] [Q&A Only] [Summary] [Export ▾]           │
│                                                          │
│  ── Summary ──────────────────────────────────────────── │
│  • Agreed to push Q3 launch to July 15                   │
│  • Sarah will handle vendor negotiations by Friday       │
│  • Mike raised concern about testing capacity             │
│  • Nate confirmed the API integration is on schedule     │
│                                                          │
│  ── Transcript ───────────────────────────────────────── │
│                                                          │
│  10:30:12  Sarah                                         │
│  Hey everyone, let's get started. First up is the        │
│  Q3 timeline.                                            │
│                                                          │
│  10:30:28  Mike                                          │
│  Yeah so I've been looking at the testing schedule        │
│  and I think we might need an extra week.                │
│                                                          │
│  10:31:05  Sarah                                         │
│  Nate, what's the status on the API integration?         │
│                                                          │
│  10:31:09  Nate (Clone) ────────── SECS: 0.97 ───────── │
│  The API integration is on schedule. We completed the    │
│  auth module last week and load testing starts Monday.   │
│  ──────────────────────────────────────────────────────  │
│                                                          │
│  10:31:18  Sarah                                         │
│  Great, thanks.                                          │
│                                                          │
│  [Jump to: ▾ Next clone response | End of meeting]       │
└──────────────────────────────────────────────────────────┘
```

**UX details**:
- **Speaker colors**: Each participant gets a consistent color (left border or avatar). Clone responses are visually distinct (highlighted background, SECS score badge).
- **Jump-to navigation**: Quick jump to "next clone response" or "next question to clone" — users often want to review specifically what their clone said.
- **Q&A Only view**: Filtered to show only the question-and-response pairs, hiding everything else. Fastest way to audit what the clone actually said.
- **Search within meeting**: Ctrl+F style search within a single meeting's transcript.
- **Timestamps as anchors**: Every timestamp is a clickable anchor link, so users can share `meetings/abc123#t=10m31s` to point someone at a specific moment.
- **Edit title**: Click to rename (auto-generated title is just a starting point).

**Search** (`/meetings/search`):

Global search across all meetings. Searches transcript text, speaker names, topics, and summaries.

```
Search: "API integration"

Results:
  Apr 3 — Project Sync — "...the API integration is on schedule..."
  Mar 28 — Sprint Planning — "...need to prioritize API integration..."
  Mar 15 — Tech Review — "...API integration design doc reviewed..."
```

**Export Formats**:

| Format | Use Case |
|---|---|
| **Markdown** | Copy into docs, notes, wikis. Includes speaker labels, timestamps, summary. |
| **JSON** | Programmatic access. Full segment data with all metadata. |
| **SRT** | Subtitle format. Can be used with video recordings of the meeting. |
| **Plain text** | Simple copy-paste. Speaker: text format, no metadata. |

Export triggered from the detail view dropdown or via API:
```bash
# CLI export
python -m voiceagent meeting export --id abc123 --format markdown --output meeting.md

# API export
GET /api/meetings/export/abc123?format=markdown
```

#### 9.5 CLI Transcript Access

For users who prefer the terminal:

```bash
# List recent meetings
python -m voiceagent meeting history
# Output:
#   abc123  Apr 3  10:30-11:17  Project Sync with Sarah and Mike  (Nate, 3 Q&A)
#   def456  Apr 2  14:00-14:32  Weekly Standup                     (Nate+Boris, 5 Q&A)

# Search across all meetings
python -m voiceagent meeting search "API integration"

# Show a specific meeting's transcript
python -m voiceagent meeting show abc123

# Show only clone Q&A from a meeting
python -m voiceagent meeting show abc123 --qa-only

# Export
python -m voiceagent meeting export abc123 --format markdown -o meeting.md
python -m voiceagent meeting export abc123 --format json -o meeting.json
```

#### 9.6 Stale Meeting Recovery

On startup, the manager checks for meetings stuck in `status='active'`:

```python
def _recover_stale_meetings(self) -> None:
    """Close any meetings left active from a previous crash.

    Sets ended_at to the last segment's timestamp, generates
    summary if missing, and sets status to 'ended'.
    Runs automatically on CloneMeetingManager init.
    """
```

This means: even if the user's machine crashes mid-meeting, the next time they start the clone system, all previous transcript data is intact and the meeting is properly closed.

#### 9.7 Retention & Cleanup

- Meetings are never auto-deleted. Storage is cheap and transcripts are small (~1KB per minute of meeting).
- Users can archive meetings (`POST /api/meetings/{id}/archive`) to hide them from default list view.
- Archived meetings remain searchable and exportable.
- A `meeting cleanup --older-than 1y` CLI command is available for users who want to purge old data, but it requires explicit confirmation.

---

### 10. Human Meeting Behavior Simulation (`src/voiceagent/meeting/meeting_behavior.py`)

**Purpose**: The clone must behave exactly like a real human in a meeting — muted by default, unmuting only when speaking, and re-muting immediately after. No human participant should notice anything unnatural about how the clone participates.

#### 10.1 Mute/Unmute Automation

**Core rule**: The clone stays muted at ALL times except during the brief window when it is actively responding to a question. This prevents background noise, breathing artifacts, or TTS artifacts from leaking into the meeting.

**Two-layer approach** (belt and suspenders):

**Layer 1 — Audio silence (virtual mic level)**:
The virtual microphone (`clone_nate_sink`) receives zero-energy silence at all times by default. TTS audio is only routed to the sink during active responses. This is the primary control — even if the app-level mute fails, no audio leaks.

```python
class VirtualMicController:
    """Controls audio flow to the virtual microphone."""

    def __init__(self, sink_name: str):
        self._sink_name = sink_name
        self._muted = True      # Always start muted
        self._silence_thread = None

    async def start_silence(self) -> None:
        """Feed continuous silence to the virtual mic.
        Prevents 'no audio device' detection by meeting apps."""

    async def unmute_and_speak(self, audio: np.ndarray) -> None:
        """Pause silence → send app unmute keystroke → play audio →
        send app mute keystroke → resume silence."""

    async def mute(self) -> None:
        """Ensure mic is muted at app level + resume silence stream."""
```

**Layer 2 — App-level mute toggle (keyboard simulation)**:
Use `xdotool` to send the mute/unmute keyboard shortcut to the meeting app window. This toggles the visible mute indicator in the UI so other participants see the clone mute/unmute naturally.

```python
class MeetingAppController:
    """Control meeting app mute/unmute via keyboard shortcuts."""

    # Platform-specific mute/unmute shortcuts
    SHORTCUTS = {
        "zoom": "alt+a",            # Zoom: Alt+A toggles mute
        "google_meet": "ctrl+d",    # Meet: Ctrl+D toggles mic
        "teams": "ctrl+shift+m",    # Teams: Ctrl+Shift+M toggles mic
        "generic": "ctrl+m",        # Common fallback
    }

    # Window title patterns for finding the meeting app
    WINDOW_PATTERNS = {
        "zoom": r"^Zoom Meeting",
        "google_meet": r"^Meet - .+",
        "teams": r"Microsoft Teams",
    }

    def __init__(self, platform: str = "auto"):
        self._platform = platform
        self._window_id: int | None = None

    def detect_platform(self) -> str:
        """Auto-detect which meeting app is running by scanning window titles."""

    async def unmute(self) -> None:
        """Send unmute keystroke to the meeting app window.

        1. Find the meeting window by title pattern
        2. Save current focused window
        3. Activate meeting window
        4. Send mute toggle key
        5. Restore focus to original window

        Uses xdotool on Linux:
            xdotool search --name '<pattern>' windowactivate --sync key <shortcut>
        """

    async def mute(self) -> None:
        """Send mute keystroke to the meeting app window."""

    def is_muted(self) -> bool | None:
        """Best-effort check if currently muted. Returns None if unknown."""
```

**Sequence when clone responds**:

```
1. Address detected → clone has a response ready
2. MeetingAppController.unmute()           # Toggle mute in Zoom/Meet UI
3. Brief 200ms pause                       # Natural pause before speaking
4. VirtualMicController.unmute_and_speak() # Play TTS audio to virtual mic
5. Audio playback completes
6. Brief 300ms pause                       # Natural pause after speaking
7. MeetingAppController.mute()             # Toggle mute back on
8. VirtualMicController.mute()             # Resume silence to virtual mic
```

#### 10.2 Natural Presence Behaviors

Beyond mute/unmute, the clone should exhibit subtle human-like behaviors that prevent it from looking like a frozen avatar:

**Idle behaviors** (when not speaking):

| Behavior | Implementation | Frequency |
|---|---|---|
| **Occasional blink** | Pre-rendered blink frames composited onto idle frame | Every 3-6s (randomized) |
| **Subtle head movement** | 3-5 second looping driver video with slight sway | Continuous during idle |
| **Attentive posture** | Base frame shows the person looking at camera, slight forward lean | Static |
| **React to name** | Brief head-turn or eyebrow-raise animation when name is detected (even if no question) | On name mention |

**Speaking behaviors** (when responding):

| Behavior | Implementation | Timing |
|---|---|---|
| **Natural start delay** | 200-400ms pause after unmute before speaking | Before every response |
| **Head nod start** | Slight downward nod composited at response start | First 500ms |
| **Lip sync** | MuseTalk 1.5 real-time | During speech |
| **Natural end** | Brief pause + slight nod at end of response | After last word |
| **Clean stop** | No lingering mouth movement after speech ends | Immediate |

**Error behaviors** (graceful degradation):

| Scenario | Behavior |
|---|---|
| SECS fails all 5 attempts | Stay muted, log the failure. Don't respond with bad audio. Silence is better than a wrong-sounding clone. |
| LLM times out | Stay muted. Don't say "I'm sorry, I couldn't process that." Just stay silent. |
| MuseTalk crashes | Fall back to static image. Audio still works through virtual mic. |
| Meeting app window not found | Skip app-level mute/unmute. Audio-level silence still prevents leaks. |

#### 10.3 Meeting App Auto-Detection

On startup, the clone scans for running meeting app windows:

```python
def detect_meeting_platform() -> str:
    """Scan running windows to detect which meeting app is active.

    Uses xdotool search to find windows matching known patterns.
    Returns: 'zoom', 'google_meet', 'teams', or 'generic'.
    """
    import subprocess

    for platform, pattern in MeetingAppController.WINDOW_PATTERNS.items():
        result = subprocess.run(
            ["xdotool", "search", "--name", pattern],
            capture_output=True, text=True, timeout=3,
        )
        if result.stdout.strip():
            return platform
    return "generic"
```

If no meeting app is detected, the clone still works — it just can't toggle the app-level mute indicator. The audio-level silence ensures no leaks regardless.

#### 10.4 Continuous Silence Stream

The virtual mic must send a low-level silence signal (not true zero — some apps detect "no signal" and show a warning). A comfort noise floor of -60 dBFS keeps the mic "alive":

```python
def _generate_comfort_noise(duration_ms: int = 100, sr: int = 44100) -> np.ndarray:
    """Generate near-silent comfort noise for virtual mic keepalive.
    -60 dBFS = imperceptible but prevents 'no mic signal' warnings."""
    samples = int(sr * duration_ms / 1000)
    return np.random.randn(samples).astype(np.float32) * 0.001  # -60 dBFS
```

---

### 11. CLI Interface (`src/voiceagent/cli.py` — extend existing)

Add a `meeting` command group to the existing voice agent CLI:

```bash
# Start a clone for a meeting
python -m voiceagent meeting start --clone nate --voice nate --driver ~/nate_headshot.png

# Start multiple clones
python -m voiceagent meeting start --clone nate --voice nate
python -m voiceagent meeting start --clone boris --voice boris

# List active clones
python -m voiceagent meeting list

# Stop a clone
python -m voiceagent meeting stop --clone nate

# Stop all
python -m voiceagent meeting stop-all

# Setup virtual devices (one-time, requires sudo)
python -m voiceagent meeting setup-devices --clones nate,boris

# Meeting transcript history
python -m voiceagent meeting history
python -m voiceagent meeting search "API integration"
python -m voiceagent meeting show abc123
python -m voiceagent meeting show abc123 --qa-only
python -m voiceagent meeting export abc123 --format markdown -o meeting.md
```

---

### 12. Configuration (`~/.voiceagent/meeting.json`)

```json
{
    "clones": {
        "nate": {
            "voice_profile": "nate",
            "driver_image": "~/.voiceagent/drivers/nate_headshot.png",
            "driver_video": null,
            "aliases": ["Nate", "Nathan", "hey Nate"],
            "video_device_nr": 20,
            "address_threshold": 0.8,
            "llm_max_tokens": 150,
            "llm_temperature": 0.4
        },
        "boris": {
            "voice_profile": "boris",
            "driver_image": "~/.voiceagent/drivers/boris_headshot.png",
            "aliases": ["Boris", "hey Boris"],
            "video_device_nr": 21,
            "address_threshold": 0.8
        }
    },
    "audio_capture": {
        "source": "default.monitor",
        "sample_rate": 16000
    },
    "transcription": {
        "model": "large-v3-turbo",
        "compute_type": "float16",
        "window_seconds": 5,
        "context_buffer_minutes": 10
    },
    "diarization": {
        "model": "pyannote/speaker-diarization-community-1",
        "enabled": true
    },
    "voice": {
        "secs_threshold": 0.95,
        "secs_candidates_max": 5,
        "prosody_selection": "always",
        "enhance": true,
        "enhance_sample_rate": 44100
    },
    "lip_sync": {
        "engine": "musetalk-1.5",
        "output_fps": 25,
        "idle_fps": 10,
        "resolution": [1280, 720],
        "face_resolution": [256, 256]
    },
    "response": {
        "max_tokens": 150,
        "temperature": 0.4,
        "model": "qwen3:14b-nothink",
        "system_prompt_override": null
    },
    "transcript": {
        "db_path": "~/.voiceagent/meetings.db",
        "auto_save": true,
        "save_interval_segments": 1,
        "auto_end_silence_minutes": 5,
        "auto_summary": true,
        "auto_title": true,
        "retention_days": null
    },
    "behavior": {
        "default_muted": true,
        "unmute_before_speak_ms": 200,
        "mute_after_speak_ms": 300,
        "platform_auto_detect": true,
        "platform_override": null,
        "idle_blink_interval_s": [3, 6],
        "comfort_noise_dbfs": -60
    }
}
```

---

## File Layout

All new code goes under `src/voiceagent/meeting/`:

```
src/voiceagent/meeting/
    __init__.py
    manager.py              # CloneMeetingManager — top-level orchestrator
    devices.py              # CloneDeviceManager — v4l2loopback + PulseAudio
    audio_capture.py        # Meeting audio capture via PulseAudio monitor
    transcriber.py          # Streaming faster-whisper + pyannote diarization
    address_detector.py     # Name/question detection from transcript
    responder.py            # LLM response generation (Ollama)
    voice_output.py         # TTS + prosody selection + SECS gate + enhance
    lip_sync_rt.py          # MuseTalk 1.5 real-time lip sync
    webcam_writer.py        # pyvirtualcam frame writer
    config.py               # MeetingConfig dataclass
    idle_renderer.py        # Idle frame generation (static + blink)
    meeting_behavior.py     # Mute/unmute automation, human presence simulation
    app_controller.py       # xdotool meeting app keyboard control (mute/unmute)
    transcript_store.py     # SQLite meeting transcript storage + search
    transcript_export.py    # Export to Markdown, JSON, SRT, plain text
    meeting_summary.py      # Post-meeting LLM summary + topic extraction
    db/
        __init__.py
        schema.py           # DDL for meetings, meeting_segments, meeting_interactions
        connection.py       # get_connection for ~/.voiceagent/meetings.db

src/clipcannon/dashboard/routes/
    meetings.py             # Dashboard API: list, detail, search, export, archive
```

---

## Dependencies (New)

| Package | Version | Purpose |
|---|---|---|
| `pyvirtualcam` | >=0.15.0 | Write frames to v4l2loopback virtual webcam |
| `pyannote.audio` | >=4.0 | Speaker diarization (community-1 model) |
| `musetalk` | 1.5 | Real-time lip sync (30+ FPS) |
| `v4l2loopback-dkms` | system | Virtual webcam kernel module (apt install) |
| `xdotool` | system | Keyboard simulation for mute/unmute in meeting apps (apt install) |

Already in project: `faster-whisper`, `faster-qwen3-tts`, `torch`, `numpy`, `pipecat`, `pyaudio`, Resemble Enhance, Ollama, ClipCannon voice engine.

---

## Integration with Existing ClipCannon Systems

| System | Integration |
|---|---|
| **Voice profiles** (`~/.clipcannon/voice_profiles.db`) | Clone reads voice profile + reference embedding for SECS verification |
| **Prosody segments** (`prosody_segments` table / `prosody.db`) | Clone uses `select_prosody_reference()` for every TTS call |
| **FastTTSAdapter** (`adapters/fast_tts.py`) | Clone reuses the same 0.6B streaming TTS with Full ICL mode |
| **VoiceVerifier** (`voice/verify.py`) | Clone uses SECS scorer for >0.95 gate |
| **Resemble Enhance** (`voice/enhance.py`) | Clone runs enhance on every output |
| **Voice data** (`~/.clipcannon/voice_data/<name>/`) | Reference clips for TTS |
| **GPU Manager** (`gpu_manager.py`) | Clone pauses other GPU workers when active |
| **Wake Listener** (`wake_listener.py`) | Coexists — wake listener stays dormant while clone is active |
| **Dashboard** (`dashboard/`) | New `/api/meetings` routes for transcript list, detail, search, export |
| **Meeting DB** (`~/.voiceagent/meetings.db`) | Shared transcript store across all clones, separate from agent.db |

---

## Implementation Phases

### Phase 1: Audio Pipeline + Transcript Storage (Week 1-2)

1. **Meeting transcript database** — Schema, `MeetingTranscriptStore`, auto-save on every segment.
2. **Meeting audio capture** — PulseAudio monitor source capture in a background thread.
3. **Streaming transcription** — faster-whisper processing meeting audio in sliding windows, writing segments to DB in real-time.
4. **Address detection** — Name mention detection from transcript.
5. **Response generation** — Ollama LLM generating direct answers.
6. **Voice output** — TTS with full prosody + SECS >0.95 gate + Resemble Enhance.
7. **Virtual microphone** — PulseAudio null sink + remap source.
8. **Mute/unmute automation** — `MeetingAppController` with xdotool, platform auto-detection, comfort noise stream.
9. **Stale meeting recovery** — Auto-close meetings from crashes on startup.
10. **End-to-end audio test**: Someone says "Hey Nate, what time is the deadline?" → Clone unmutes in Zoom → Nate responds through virtual mic with verified voice → Clone re-mutes → full transcript persisted.

### Phase 2: Video Pipeline + Human Behavior (Week 3-4)

1. **MuseTalk 1.5 integration** — Real-time lip sync from TTS audio.
2. **Idle renderer** — Static/looping face with blink animation (randomized 3-6s interval).
3. **Virtual webcam** — pyvirtualcam writing to v4l2loopback.
4. **Face compositing** — MuseTalk face region onto 720p base frame.
5. **Natural speaking behavior** — Pre-speech pause, head nod start, clean stop after response.
6. **Name reaction** — Subtle head-turn animation when clone's name is mentioned (even without a question).
7. **End-to-end video test**: Clone appears in Zoom as named webcam, unmutes/lip-syncs response/re-mutes naturally.

### Phase 3: Transcript UI + Multi-Clone (Week 5-6)

1. **Dashboard meeting routes** — List, detail, search, export API endpoints.
2. **Meeting list UI** — Date-grouped cards with summary, participants, clone Q&A count.
3. **Meeting detail UI** — Speaker-colored transcript, clone responses highlighted, jump navigation, Q&A-only filter.
4. **Search** — Full-text search across all meetings (transcript, speakers, topics).
5. **Export** — Markdown, JSON, SRT, plain text formats from dashboard and CLI.
6. **Post-meeting summary** — LLM-generated 3-5 bullet summary, auto-title, topic tags.
7. **Speaker diarization** — pyannote integration for who-said-what.
8. **Multi-clone support** — Shared ASR/LLM, per-clone TTS/video.
9. **Clone Meeting Manager** — Orchestrator for N clones.
10. **CLI commands** — `meeting start/stop/list/history/search/show/export/setup-devices`.
11. **Configuration** — `meeting.json` config file.
12. **Device setup script** — Automated v4l2loopback + PulseAudio provisioning.

---

## Latency Budget (Response Time)

Target: Clone responds within **3-5 seconds** of being addressed.

| Stage | Target | Notes |
|---|---|---|
| Address detection | ~200ms | Name match in transcript text |
| LLM response (Ollama 14B) | ~800ms | TTFT ~50ms + generation ~750ms for 1-3 sentences |
| Prosody ref selection | ~50ms | DB query + style match |
| TTS streaming (0.6B) | ~150ms TTFB | Streaming chunks, first audio in 150ms |
| SECS verification | ~100ms | Speaker embedding comparison |
| Resemble Enhance | ~300ms | Denoise + upsample |
| MuseTalk lip sync | ~200ms | First frame from audio chunk |
| **Total to first audio** | **~1.8s** | Audio starts playing |
| **Total to first video** | **~2.0s** | Lip-synced video starts |

If SECS fails and regeneration is needed: add ~500ms per retry (up to 5 retries = 2.5s worst case). Total worst case: ~4.5s. Acceptable for meeting context.

---

## Testing Plan

### Test Clone: Nate

All initial development and testing uses the "nate" voice profile.

#### Unit Tests (`tests/voiceagent/meeting/`)

| Test | Validates |
|---|---|
| `test_address_detector.py` | Name detection accuracy, false positive rate |
| `test_transcriber.py` | Streaming transcription accuracy, window management |
| `test_voice_output.py` | SECS >0.95 gate, prosody selection, enhance pipeline |
| `test_devices.py` | v4l2loopback creation/destruction, PulseAudio sink management |
| `test_responder.py` | Response conciseness (word count), no-ramble enforcement |
| `test_transcript_store.py` | Auto-save on every segment, crash recovery, search, stale meeting closure |
| `test_transcript_export.py` | Markdown/JSON/SRT/text export formatting correctness |
| `test_meeting_summary.py` | LLM summary generation, auto-title, topic tag extraction |
| `test_meeting_behavior.py` | Mute/unmute sequence, comfort noise, platform detection |
| `test_app_controller.py` | xdotool command generation for Zoom/Meet/Teams shortcuts |

#### Integration Tests

| Test | Validates |
|---|---|
| Audio loopback | Capture meeting audio → transcribe → detect "Hey Nate" → respond via virtual mic |
| Video loopback | TTS audio → MuseTalk lip sync → pyvirtualcam → read back from /dev/videoN |
| SECS regression | Generate 100 responses, verify ALL have SECS >0.95 |
| Prosody coverage | Verify prosody_select is called for every response, never falls back to flat |
| Latency benchmark | Measure end-to-end from address detection to first audio/video frame |
| Transcript persistence | Kill clone mid-meeting, restart, verify all segments up to crash are in DB |
| Search accuracy | Insert 10 meetings, search by keyword/speaker/date, verify correct results |
| Dashboard API | All 8 meeting endpoints return correct data, pagination, filtering |
| Export roundtrip | Export as Markdown, verify it contains all segments, speakers, timestamps |
| Mute/unmute cycle | Clone starts muted → unmutes on address → speaks → re-mutes. Verify no audio leaks between responses |
| Comfort noise | Virtual mic sends -60 dBFS noise when muted, meeting app shows mic "alive" but no audible sound |
| Platform detection | Start Zoom, verify auto-detect returns "zoom". Start Meet in Chrome, verify "google_meet" |

#### Manual Test: Zoom Meeting

1. Start clone: `python -m voiceagent meeting start --clone nate --voice nate`
2. Open Zoom, select "Clone Nate" as webcam, "Clone Nate Mic" as microphone.
3. Join a test meeting with a second participant.
4. **Verify**: Clone joins MUTED. Zoom shows mute indicator on clone's tile.
5. Second participant says: "Hey Nate, what's the status of the project?"
6. **Verify**: Clone UNMUTES in Zoom (mute icon disappears), responds with direct answer, lip-synced video, SECS >0.95.
7. **Verify**: Clone RE-MUTES immediately after response (mute icon returns).
8. **Verify**: Nate does NOT respond to conversation that doesn't address him. Stays muted and idle.
9. **Verify**: Nate stops talking after answering (no follow-ups, no rambling).
10. **Verify**: During idle, clone shows subtle blink/movement (not a frozen image).
11. End the meeting. Run `python -m voiceagent meeting history` — verify meeting appears with transcript.
12. Run `python -m voiceagent meeting show <id>` — verify full transcript with speaker labels.
13. Check dashboard at `localhost:3200/meetings` — verify meeting card with summary and Q&A count.

---

## Risk Mitigation

| Risk | Mitigation |
|---|---|
| WSL2 lacks v4l2loopback | Document custom kernel build. Recommend native Linux or OBS bridge for WSL2 users. Phase 1 audio-only works without video device. |
| MuseTalk quality insufficient | Fall back to static image + audio only (still useful for phone meetings). Investigate MuseTalk fine-tuning on clone face. |
| SECS <0.95 on short utterances | Increase best-of-N to 7. Use longer reference clips. Fall back to 1.7B model. |
| GPU VRAM overflow with 2+ clones | Share ASR + diarization + LLM across clones. Only load clone-specific TTS + MuseTalk. Time-slice if needed. |
| False address detection | Conservative threshold (0.8). Require name + question pattern. Log all triggers for tuning. |
| Meeting audio echo | Clone TTS routes to its own null sink, not default output. Echo cancellation not needed since clone doesn't hear itself. |
| xdotool fails on Wayland | xdotool requires X11. On Wayland, use `ydotool` or `wtype` as alternatives. Document in setup guide. |
| Meeting app updates shortcuts | Keyboard shortcuts may change between app versions. Store shortcuts in config, not hardcoded. User can override via `behavior.platform_override`. |
| Mute/unmute timing visible to others | The brief unmute/re-mute is natural — humans do this constantly in meetings. The 200-300ms pauses make it look intentional, not robotic. |
| Transcript DB grows large | At ~1KB/min, a year of daily 1-hour meetings = ~22MB. Negligible. SQLite handles this fine. Archive option available if user wants to declutter. |
