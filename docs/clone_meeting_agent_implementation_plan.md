# Clone Meeting Agent — Implementation Plan

## Overview

Add a new subsystem to ClipCannon that creates AI voice/video clones which can participate in Zoom, Google Meet, Microsoft Teams, and other video conferencing apps. The system supports **two operating modes**, with Mode 2 as the **primary recommended path**:

**Mode 2 — Join as Participant (PRIMARY)**: The clone joins the meeting as a SEPARATE participant with a custom display name (e.g., "Nate's AI Assistant", "Meeting Notes Bot", "Jarvis"). It appears in the participant list alongside you. Think of it as an AI note-taker you can interact with — it transcribes everything, and responds if addressed by name. The user names it whatever they want. **No OBS, no virtual webcam drivers, no Windows-side dependencies beyond PulseAudio bridge.** The bot handles its own audio/video I/O directly through the meeting platform SDK or browser.

**Mode 1 — Replace Me (Secondary)**: The clone replaces you. It shows up as a selectable virtual webcam + microphone (e.g., "Clone Nate") in the OS device list. You select it in Zoom/Meet as your camera/mic. Other participants see the clone as YOU. You don't need to be in the meeting at all. Requires v4l2loopback (native Linux) or Unity Capture (Windows, free open-source). **No OBS dependency.**

Both modes share the same core pipeline (audio capture, transcription, address detection, response generation, TTS with SECS >0.95, lip sync). The difference is how they connect to the meeting:

| | Mode 2: Join as Participant (PRIMARY) | Mode 1: Replace Me (Secondary) |
|---|---|---|
| **Appears as** | Separate participant with custom name | Your webcam/mic device |
| **Connection** | Zoom Meeting SDK (headless, free) or Playwright (Google Meet/Teams) | v4l2loopback + PulseAudio (Linux) or Unity Capture (Windows, free) |
| **You in meeting?** | Yes — clone joins alongside you | No — clone IS you |
| **Display name** | User-configurable: "AI Notes", "Jarvis", any name | Whatever the meeting app shows for your camera |
| **Use case** | AI note-taker, interactive assistant, second presence | Stand-in for meetings you can't attend |
| **Video out** | Raw video frames via Zoom SDK / static image via Playwright | Lip-synced avatar via virtual webcam |
| **Audio in** | Raw audio from meeting SDK / browser audio capture | PulseAudio system monitor capture |
| **Audio out** | Raw audio injection via SDK / browser virtual mic | PulseAudio virtual mic |
| **Windows deps** | None (all runs in WSL2/Docker) | PulseAudio bridge + Unity Capture |
| **Cost** | Free (Zoom Meeting SDK free tier, Playwright MIT) | Free (v4l2loopback GPL, Unity Capture MIT) |

**Everything is free. No OBS required. No paid SDKs.**

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
- Output format: RGB24 or YUYV at 720p 30fps (matches MuseTalk output).

**WSL2 limitation**: The default WSL2 kernel does not include v4l2loopback. Two options:
1. **Native Linux** (recommended for production): Works out of the box.
2. **WSL2 workaround**: Compile a custom WSL2 kernel with `CONFIG_VIDEO_V4L2=y` and `CONFIG_V4L2_LOOPBACK=m`. Or use Unity Capture (free, open-source DirectShow virtual camera for Windows, no test signing needed) with a small bridge script. **Mode 2 (bot join) is recommended on WSL2** — it avoids the virtual webcam problem entirely.

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

### 1b. Meeting Bot Join — Mode 2 (`src/voiceagent/meeting/bot_join.py`)

**Purpose**: Join a meeting as a separate participant with a custom display name. The user names the bot whatever they want ("AI Notes", "Jarvis", "Nate's Assistant", etc.).

#### Platform-Specific Join Methods

**Zoom — Meeting SDK Headless Linux Bot (Preferred)**

Zoom provides an official [Meeting SDK for Linux](https://github.com/zoom/meetingsdk-headless-linux-sample) that runs headless in Docker. This is the proper, supported way to build meeting bots.

Capabilities:
- Join any meeting by meeting ID + password or join URL
- Custom display name (set at join time)
- **Receive raw audio** from all participants (PCM 16LE) via `IZoomSDKAudioRawDataHelper`
- **Send raw audio** (TTS output) via `setExternalAudioSource`
- **Send raw video** (lip-synced avatar frames) via `IZoomSDKVideoSource` (I420 format)
- **Receive raw video** for participant faces (not needed for our use case)
- Runs in Docker, no GUI required

Requirements:
- Zoom Meeting SDK credentials (Client ID + Client Secret) — free from [Zoom Marketplace](https://marketplace.zoom.us)
- SDK key/secret for JWT authentication
- SDK available for Linux x86_64

```python
class ZoomBotJoin:
    """Join a Zoom meeting as a headless bot participant.

    Uses the Zoom Meeting SDK for Linux (C++ SDK with Python bindings).
    The bot joins with a custom display name, receives mixed audio,
    and can send raw audio/video frames.
    """

    def __init__(self, client_id: str, client_secret: str):
        self._client_id = client_id
        self._client_secret = client_secret

    async def join(
        self,
        meeting_url: str,
        display_name: str = "AI Notes",
        send_video: bool = True,
    ) -> ZoomBotSession:
        """Join meeting. Returns session with audio/video I/O handles."""

    async def leave(self) -> None:
        """Leave meeting gracefully."""
```

**Google Meet / Microsoft Teams — Puppeteer Browser Bot**

No official SDK for bots. Use headless Chromium via Puppeteer:
- Navigate to meeting URL
- Enter custom display name in the "What's your name?" field
- Click "Ask to join" / "Join now"
- Capture audio via WASAPI loopback or virtual audio routing
- Send audio via virtual microphone (PulseAudio null sink in headless Chromium)
- Video: static avatar image or screen share of animated face

```python
class BrowserBotJoin:
    """Join a Google Meet or Teams meeting via headless Chromium.

    Uses Puppeteer to automate the browser join flow.
    Display name entered in the meeting lobby.
    Audio captured from browser audio output.
    """

    async def join(
        self,
        meeting_url: str,
        display_name: str = "AI Notes",
        platform: str = "auto",  # auto-detect from URL
    ) -> BrowserBotSession:
        """Join meeting. Returns session with audio I/O handles."""

    async def leave(self) -> None:
        """Leave meeting gracefully (click leave button)."""
```

#### Unified Bot Interface

Both join methods implement the same interface:

```python
class MeetingBotSession(Protocol):
    """Protocol for a connected meeting bot session."""

    @property
    def display_name(self) -> str: ...

    @property
    def platform(self) -> str: ...

    async def get_audio_stream(self) -> AsyncIterator[bytes]:
        """Receive mixed audio from all participants (PCM 16kHz mono)."""

    async def send_audio(self, audio: bytes) -> None:
        """Send audio to the meeting (TTS output)."""

    async def send_video_frame(self, frame: bytes, width: int, height: int) -> None:
        """Send a video frame (I420 or RGB). Zoom SDK only."""

    async def leave(self) -> None:
        """Leave the meeting."""
```

#### Configuration for Mode 2

```json
{
    "bot_join": {
        "enabled": false,
        "default_display_name": "AI Notes",
        "zoom_sdk": {
            "client_id": "",
            "client_secret": ""
        },
        "browser_bot": {
            "chromium_path": null,
            "headless": true,
            "user_data_dir": "~/.voiceagent/chromium-profile"
        }
    }
}
```

#### CLI for Mode 2

```bash
# Join as a separate participant (Mode 2)
python -m voiceagent meeting join \
    --url "https://zoom.us/j/123456789?pwd=abc" \
    --name "Nate's AI Assistant" \
    --clone nate \
    --voice nate

# Join Google Meet
python -m voiceagent meeting join \
    --url "https://meet.google.com/abc-defg-hij" \
    --name "Meeting Notes" \
    --clone nate

# Mode 1 (replace me) is still via:
python -m voiceagent meeting start --clone nate --voice nate
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

### 7. Clone Realism & Real-Time Avatar (`src/voiceagent/meeting/avatar_rt.py`, `idle_renderer.py`, `webcam_writer.py`)

**Purpose**: Render a clone that other meeting participants perceive as a real human. This requires going far beyond lip sync — every visual and behavioral cue that humans unconsciously read must be convincingly reproduced.

#### 7.1 What Humans Perceive in Video Calls (Realism Requirements)

Humans unconsciously process dozens of micro-cues during a video call. Missing ANY of these triggers uncanny valley detection. The clone must reproduce ALL of them:

| Channel | What Humans Detect | Clone Must Reproduce | Implementation |
|---|---|---|---|
| **Eyes** | Micro-saccades (tiny eye jitter 2-3x/sec), blink timing (every 3-6s, irregular), gaze direction, pupil response | Natural irregular blinks, micro-saccade jitter, gaze toward camera | Pre-recorded blink animation library + random timing. Micro-saccade: 1-2px random eye jitter at 2-3 Hz. Gaze: eyes fixed at camera position (simulates eye contact). |
| **Mouth** | Lip shape precision, teeth visibility, tongue movement, jaw articulation, saliva gloss | Precise lip sync with visible teeth, jaw movement tracking audio energy | MuseTalk 1.5 at 256x256 face region — lip inpainting preserves skin texture while generating accurate mouth shapes. |
| **Skin** | Pores, subtle color variation, micro-flush, specular highlights | Preserved original skin texture from driver video, no smoothing | MuseTalk inpaints only the mouth region. Rest of face is original texture from the driver video. NO post-processing blur or smoothing. |
| **Head** | Constant micro-movement (1-3mm sway), breathing-induced bob, nods, tilts | Continuous subtle motion even when not speaking | **Driver video approach**: Record 10-30 second loops of the real person sitting naturally (breathing, micro-sway). Loop this as the base — gives natural head motion for free. |
| **Shoulders/body** | Breathing (chest rise/fall), posture shifts, hand gestures | Visible breathing, occasional posture adjustment | Captured in the driver video loop. Ensure driver video includes upper chest/shoulders. |
| **Timing** | Response onset timing, hesitation patterns, "thinking" pauses | Natural start delay (200-400ms), no robotic snap-to-speech | Handled by MeetingBehavior (pre/post speech pauses). |
| **Audio** | Voice timbre, speaking rhythm, emphasis, breath sounds | SECS >0.95, full prosody, breath sounds in TTS | Handled by MeetingVoiceOutput. Resemble Enhance preserves breath sounds. |
| **Webcam quality** | 720p/1080p, typical webcam noise/grain, auto-exposure variation, compression artifacts | Match typical webcam look — NOT too perfect | Add subtle film grain (1-2%) and slight brightness variation to avoid "too clean" look that screams synthetic. |

#### 7.2 Driver Video Strategy (Critical for Realism)

The single most important factor for realism is the **driver video** — a real recording of the person sitting at their desk in their normal meeting setup. This provides:
- Natural head micro-movement and sway
- Breathing visible in chest/shoulders
- Real skin texture at real webcam quality
- Room lighting and background
- Occasional posture shifts

**Driver video recording requirements**:
```
Duration: 15-30 seconds (will be looped seamlessly)
Resolution: 1280x720 or 1920x1080 (match target output)
Frame rate: 30 FPS (MuseTalk requirement)
Content: Person sitting at desk, looking at camera, NOT speaking
         (mouth closed, neutral expression, natural breathing)
Lighting: Normal room/desk lighting (matches what a webcam would capture)
Framing: Head + shoulders visible (typical webcam framing)
Format: MP4 h264
```

The driver video loop is the "canvas" — MuseTalk only overwrites the mouth region during speech, everything else is the real recorded video playing in a seamless loop.

**Seamless loop creation**: The driver video is ping-pong looped (forward then reverse) to avoid a visible jump at the loop point. Cross-fade the 500ms boundary for extra smoothness.

#### 7.3 MuseTalk 1.5 — Lip Sync Engine

Per the project's findings (memory: `feedback_lipsync_quality_v2.md`), LatentSync has VAE blur. MuseTalk 1.5 is the right choice:

- **30+ FPS** on V100/A5000/5090 (real-time capable)
- **256x256 face region** — only the mouth/lower-face is regenerated
- **Latent space inpainting** — preserves identity and skin texture in untouched regions
- **MIT license** — no commercial restrictions
- **Training code open-source** — can fine-tune on clone's face for even better results

**Pipeline (speaking state)**:
```
TTS audio chunks (streaming, 24kHz)
    │
    ▼
Mel spectrogram extraction (real-time)
    │
    ▼
MuseTalk 1.5 inference (GPU, ~30ms per frame)
    │  Input: driver video face crop + audio mel
    │  Output: 256x256 face with synced lips
    │
    ▼
Composite back onto driver video frame
    │  (only mouth region replaced, rest is original video)
    │
    ▼
Realism post-processing
    │  + micro-saccade eye jitter (1-2px random at 2-3Hz)
    │  + subtle film grain (1-2% gaussian noise)
    │  + slight brightness jitter (±1% per 5-10 frames)
    │
    ▼
pyvirtualcam / Zoom SDK raw frames → meeting
```

#### 7.4 Idle State (Not Speaking) — Alive, Not Frozen

When the clone is NOT actively responding, it must still look alive:

| Behavior | Implementation | Frequency |
|---|---|---|
| **Driver video loop** | Ping-pong loop of recorded video. Provides natural head sway, breathing, posture micro-shifts. | Continuous (30 FPS) |
| **Natural blinks** | Pre-rendered blink overlay (3-5 frames per blink). Alpha-composited over the eye region of the driver frame. | Every 3-6 seconds (randomized, gaussian distribution around 4.5s) |
| **Micro-saccade** | 1-2 pixel random offset applied to both eyes each frame. Simulates the involuntary tiny eye movements all humans make. | Continuous (2-3 jitter events per second) |
| **Occasional gaze shift** | Eyes shift slightly off-center for 0.5-1s then return to camera. Simulates natural gaze wandering. | Every 15-30 seconds (rare, subtle) |
| **Breathing emphasis** | Slight periodic brightness oscillation in the chest region (~15 cycles/min = normal breathing rate). | Continuous, amplitude: ±0.5% brightness |

**Idle FPS**: 30 FPS (must match driver video rate for smooth playback). The GPU cost is minimal since we're just playing a pre-recorded video with lightweight overlays — no MuseTalk inference during idle.

#### 7.5 Speaking State — Lip Sync Active

When the clone is responding:
- MuseTalk processes TTS audio mel spectrograms in real-time
- Face region composited at 30 FPS onto driver video frame
- Eye blinks continue (don't stop blinking while talking)
- Head movement continues from driver video (don't freeze)
- Micro-saccade continues

**Transition from idle to speaking**:
1. Continue playing driver video (no freeze frame)
2. MuseTalk begins generating mouth frames
3. Cross-fade from idle mouth to MuseTalk mouth over 2-3 frames (80ms)
4. Full MuseTalk lip sync active

**Transition from speaking to idle**:
1. MuseTalk generates final mouth frames
2. Cross-fade from MuseTalk mouth back to driver video mouth over 3-4 frames (120ms)
3. Resume idle driver video loop

#### 7.6 Webcam Realism Post-Processing

A perfectly clean render looks synthetic. Real webcams have:
- **Sensor noise**: Add 1-2% Gaussian noise (temporal, changes each frame)
- **Compression artifacts**: Apply mild JPEG-like artifact simulation (not needed if pyvirtualcam compresses naturally)
- **Auto-exposure drift**: ±1% global brightness shift every 5-10 seconds (slow sine wave)
- **White balance micro-shift**: ±0.5% color temperature drift (very slow, barely perceptible)

These are lightweight numpy operations — negligible GPU cost.

#### 7.7 VRAM Budget

| Component | VRAM |
|---|---|
| MuseTalk 1.5 (UNet + VAE decoder) | ~3 GB |
| faster-whisper large-v3-turbo (ASR) | ~3 GB |
| faster-qwen3-tts 0.6B (TTS) | ~4 GB |
| pyannote diarization | ~2 GB |
| Resemble Enhance | ~1 GB |
| Overhead (driver video decode, compositing) | ~3 GB |
| **Total per clone** | **~16 GB** |

**Multi-clone strategy**: On a 32GB GPU (RTX 5090), run 1 clone with all models resident. For 2+ clones, share ASR/LLM/diarization models across clones (they process the same meeting audio), and time-slice MuseTalk + TTS (only one clone speaks at a time). Driver video playback for idle state is CPU-only (no GPU contention).

#### 7.8 File Layout for Avatar

```
src/voiceagent/meeting/
    avatar_rt.py            # MuseTalk 1.5 real-time inference wrapper
    idle_renderer.py        # Driver video loop + blink + micro-saccade + breathing
    webcam_writer.py        # pyvirtualcam frame writer + realism post-processing
    realism.py              # Film grain, brightness jitter, micro-saccade, blink overlay
```

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

### 9. Meeting Transcript Storage & Retrieval via OCR Provenance MCP

**Purpose**: Persist every meeting's full transcript, speaker attribution, clone responses, and metadata so users can find and review any meeting at any time — days, weeks, or months later.

**Backend**: The OCR Provenance MCP server (153 tools, always running) handles ALL document storage, semantic search, tagging, annotations, export, and provenance tracking. We do NOT build a custom SQLite store — we use OCR Provenance as the transcript intelligence layer.

#### Design Philosophy (UX-First)

The user should never have to think about "saving" a transcript. It happens automatically. Finding a past meeting should be as easy as searching email — by date, by person, by keyword, by what was discussed. No file management, no export steps, no "where did I put that?"

#### 9.1 Architecture: OCR Provenance as Transcript Backend

Each meeting transcript is saved as a **Markdown document** and ingested into a dedicated OCR Provenance database called `"meetings"`. This gives us for free:
- **Semantic search** (768-dim nomic embeddings + HNSW + cross-encoder reranking)
- **Full-text search** (FTS5 with BM25 scoring)
- **Hybrid search** (RRF fusion of BM25 + semantic)
- **Provenance tracking** (SHA-256 hash chain for every transformation)
- **Tagging** (tag meetings by topic, clone, date)
- **Annotations** (mark important moments, Q&A highlights)
- **Export** (JSON, Markdown, CSV via built-in tools)
- **Dashboard** (OCR Provenance dashboard at port 3367 for browsing)
- **Cross-meeting search** (search all meetings at once)
- **Document workflow** (review states, approval chains)

#### 9.2 Data Model — Meeting as Markdown Document

Each meeting is represented as a **single Markdown file** with structured frontmatter. This file is ingested into OCR Provenance, which handles chunking, embedding, indexing, and search automatically.

**Markdown document format per meeting** (written to `~/.voiceagent/meeting_transcripts/`):

```markdown
---
title: "Project Sync with Sarah and Mike"
date: 2026-04-03T10:30:00
ended: 2026-04-03T11:17:00
duration_minutes: 47
platform: zoom
clones: [nate]
participants: [Sarah, Mike, SPEAKER_02]
tags: [project update, Q3 timeline]
---

# Summary

- Agreed to push Q3 launch to July 15
- Sarah will handle vendor negotiations by Friday
- Mike raised concern about testing capacity
- Nate confirmed the API integration is on schedule

# Clone Q&A

## Q1 — Sarah asked Nate (10:31:05)
> Nate, what's the status on the API integration?

**Nate (Clone)** [SECS: 0.97, prosody: calm, latency: 500ms] (10:31:09):
The API integration is on schedule. Load testing starts Monday.

## Q2 — Mike asked Nate (10:45:22)
> Can we get the load test results by Thursday?

**Nate (Clone)** [SECS: 0.96, prosody: emphatic, latency: 620ms] (10:45:25):
Yes, I'll have the results shared by end of day Thursday.

# Full Transcript

**10:30:12 — Sarah**
Hey everyone, let's get started. First up is the Q3 timeline.

**10:30:28 — Mike**
Yeah so I've been looking at the testing schedule and I think we might need an extra week.

**10:31:05 — Sarah**
Nate, what's the status on the API integration?

**10:31:09 — Nate (Clone)** [SECS: 0.97]
The API integration is on schedule. Load testing starts Monday.

**10:31:18 — Sarah**
Great, thanks.
```

#### 9.3 OCR Provenance MCP Tool Mapping

The `MeetingTranscriptStore` class wraps OCR Provenance MCP calls:

| Operation | OCR Provenance MCP Tool | Details |
|---|---|---|
| **Setup** | `ocr_db_create` | Create `"meetings"` database on first use (one-time) |
| **Select DB** | `ocr_db_select` | Switch to `"meetings"` database before any operation |
| **Save transcript** | `ocr_ingest_files` | Ingest the Markdown file with `disable_image_extraction=true` (text-only, no GPU needed) |
| **Search meetings** | `ocr_search` | Hybrid semantic + FTS5 search with cross-encoder reranking. Natural language queries. |
| **List meetings** | `ocr_document_list` | Paginated list of all meeting documents |
| **Get meeting** | `ocr_document_get` + `ocr_chunk_list` | Full document details + all chunks (transcript segments) |
| **Tag meeting** | `ocr_tag_create` + `ocr_tag_apply` | Tag by topic, clone, platform |
| **Search by tag** | `ocr_tag_search` | Find meetings by tag |
| **Export** | `ocr_export` | Export as JSON or Markdown |
| **Annotate** | `ocr_annotation_create` | Add notes, corrections, highlights to specific chunks |
| **Archive** | `ocr_db_archive` | Hide from default list (or use tags: `archived=true`) |
| **Update title** | `ocr_document_update_metadata` | Update `doc_title` field |
| **Find similar** | `ocr_document_find_similar` | Find meetings discussing similar topics |
| **Stats** | `ocr_db_stats` | Meeting count, total size, quality metrics |
| **Provenance** | `ocr_provenance_get` | Full provenance chain for any meeting |

#### 9.4 MeetingTranscriptStore Implementation (`src/voiceagent/meeting/transcript_store.py`)

```python
class MeetingTranscriptStore:
    """Meeting transcript storage via OCR Provenance MCP server.

    Each meeting is a Markdown document ingested into the 'meetings' database.
    OCR Provenance handles chunking, embedding, indexing, search, and export.
    The MCP server must be running at all times.
    """

    TRANSCRIPT_DIR = "~/.voiceagent/meeting_transcripts"
    DB_NAME = "meetings"

    def __init__(self):
        self._transcript_dir = Path(self.TRANSCRIPT_DIR).expanduser()
        self._transcript_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_db()

    def _call_mcp(self, tool: str, args: dict) -> dict:
        """Call an OCR Provenance MCP tool via HTTP POST to localhost:3377/mcp.
        
        Uses OcrProvenanceClient (mcp_client.py) which sends JSON-RPC over HTTP
        to the SESSION PROXY (port 3377), NOT directly to the MCP server (3366).
        The session proxy gives each clone its own isolated container session —
        independent database selection, operation tracking, and connection state.
        
        Auth: Docker bridge trust (172.x IPs). No X-License-Key needed from WSL2.
        
        Concurrency: Multiple clones call concurrently via separate sessions.
        OCR Provenance handles this via WAL mode (concurrent reads) +
        ref-counted shared SQLite connections + operation locking.
        No rate limiting — all local. Good GC and connection cleanup only.
        
        Memory: Client is lightweight (just HTTP via httpx.AsyncClient with
        connection pooling). Responses processed and released immediately.
        Client properly closed on shutdown — no leaked connections.
        
        Text passthrough: Markdown files (.md) skip OCR entirely in OCR
        Provenance — straight to chunking → embedding → indexing. Zero GPU
        needed for meeting transcript ingestion.
        
        Raises MeetingTranscriptStoreError on failure."""

    def _ensure_db(self) -> None:
        """Create 'meetings' database if it doesn't exist, then select it."""
        # ocr_db_create(name="meetings", description="Clone meeting transcripts")
        # ocr_db_select(name="meetings")

    def create_meeting(self, clone_names: list[str], platform: str = "unknown") -> str:
        """Create meeting. Returns meeting_id. Writes initial Markdown file."""

    def append_segment(self, meeting_id: str, segment: MeetingSegmentData) -> None:
        """Append a transcript segment to the in-memory buffer.
        Flushes to Markdown file every N segments or on demand."""

    def record_interaction(self, meeting_id: str, interaction: CloneInteractionData) -> None:
        """Record a clone Q&A interaction."""

    def end_meeting(self, meeting_id: str, summary: str = "") -> str:
        """End meeting: finalize Markdown, ingest into OCR Provenance, tag.
        Returns the OCR Provenance document_id."""

    def flush_to_disk(self, meeting_id: str) -> Path:
        """Write current transcript state to Markdown file on disk.
        Called periodically during meeting for crash safety."""

    def ingest_to_provenance(self, transcript_path: Path) -> str:
        """Ingest finalized Markdown into OCR Provenance. Returns document_id."""
        # ocr_ingest_files(files=[str(transcript_path)], disable_image_extraction=true)

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Semantic + full-text hybrid search across all meetings."""
        # ocr_search(query=query, limit=limit)  -- natural language

    def get_meeting_document(self, document_id: str) -> dict:
        """Get full meeting document from OCR Provenance."""
        # ocr_document_get(id=document_id)

    def list_meetings(self, limit: int = 50, cursor: str | None = None) -> list[dict]:
        """List all meeting documents."""
        # ocr_document_list(limit=limit, cursor=cursor)

    def tag_meeting(self, document_id: str, tags: list[str]) -> None:
        """Apply tags to a meeting document."""
        # For each tag: ocr_tag_create + ocr_tag_apply

    def export_meeting(self, document_id: str, format: str = "markdown") -> str:
        """Export meeting via OCR Provenance."""
        # ocr_export(document_id=document_id, format=format)
```

#### 9.5 Auto-Save Behavior (Crash Safety)

Transcripts use a **dual-write strategy** for crash safety:

1. **During meeting**: Segments accumulate in memory AND are periodically flushed to a Markdown file on disk (`~/.voiceagent/meeting_transcripts/{meeting_id}.md`) every 30 seconds or every 10 segments (whichever comes first).

2. **On meeting end**: The final Markdown is written to disk, then ingested into OCR Provenance via `ocr_ingest_files`. Tags are applied. Summary is generated.

3. **On crash recovery**: On startup, scan `meeting_transcripts/` for `.md` files that don't have a corresponding OCR Provenance document. Ingest them. This means even if the process dies mid-meeting, the transcript up to the last flush is preserved on disk and will be ingested on next startup.

#### 9.6 Search & Discovery (Powered by OCR Provenance)

All search is delegated to OCR Provenance's hybrid search engine:

```bash
# From CLI (calls ocr_search under the hood):
python -m voiceagent meeting search "what did we decide about the API launch date"

# Returns semantically relevant results ranked by:
# 1. BM25 keyword relevance
# 2. Nomic 768-dim semantic similarity
# 3. Cross-encoder reranking (ms-marco-MiniLM)
# 4. Reciprocal Rank Fusion
```

**Advantages over custom SQLite LIKE search**:
- Semantic: "API timeline" finds "integration schedule" even without exact word match
- Cross-meeting: finds related discussions across different meetings
- Quality-weighted: higher confidence segments rank higher
- Natural language: "what did Nate say about testing" works out of the box

#### 9.7 Dashboard (OCR Provenance Dashboard at port 3367)

The OCR Provenance dashboard at `localhost:3367` already provides:
- Document browsing (meeting list)
- Full document viewer (meeting transcript)
- Search interface (hybrid search)
- Tag management
- Export functionality
- Provenance viewer

No custom ClipCannon dashboard routes needed for meetings — the OCR Provenance dashboard handles it. The `"meetings"` database is browsable like any other OCR Provenance database.

For ClipCannon-specific meeting UI (clone Q&A view, SECS score display), a thin wrapper page can be added to the ClipCannon dashboard (port 3200) that reads from OCR Provenance via MCP calls.

#### 9.8 CLI Transcript Access

```bash
# List recent meetings (reads from OCR Provenance)
python -m voiceagent meeting history

# Semantic search across all meetings
python -m voiceagent meeting search "API integration timeline"

# Show a specific meeting
python -m voiceagent meeting show <document_id>

# Show only clone Q&A sections
python -m voiceagent meeting show <document_id> --qa-only

# Export
python -m voiceagent meeting export <document_id> --format markdown -o meeting.md
python -m voiceagent meeting export <document_id> --format json -o meeting.json

# Open in OCR Provenance dashboard
python -m voiceagent meeting open <document_id>
# -> Opens localhost:3367 in browser, navigated to the meeting document
```

#### 9.9 Retention & Cleanup

- Meetings are never auto-deleted. OCR Provenance handles storage efficiently.
- Users can archive via `ocr_db_archive` or tag with `status:archived`.
- Full provenance chain preserved for compliance.
- Backup via `ocr_db_backup` (atomic VACUUM INTO).
- Transfer to another machine via `ocr_db_transfer` / `ocr_db_receive`.

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

# Setup virtual devices (one-time, requires sudo) — Mode 1 only
python -m voiceagent meeting setup-devices --clones nate,boris

# Mode 2: Join as a separate participant with custom name
python -m voiceagent meeting join \
    --url "https://zoom.us/j/123456789?pwd=abc" \
    --name "Nate's AI Assistant" \
    --clone nate --voice nate

# Join Google Meet as "Meeting Notes"
python -m voiceagent meeting join \
    --url "https://meet.google.com/abc-defg-hij" \
    --name "Meeting Notes" \
    --clone nate

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
        "output_fps": 30,
        "idle_fps": 30,
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
        "ocr_provenance_url": "http://localhost:3377/mcp",
        "database_name": "meetings",
        "transcript_dir": "~/.voiceagent/meeting_transcripts",
        "flush_interval_seconds": 30,
        "flush_interval_segments": 10,
        "auto_end_silence_minutes": 5,
        "auto_summary": true,
        "auto_title": true,
        "auto_tag": true
    },
    "behavior": {
        "default_muted": true,
        "unmute_before_speak_ms": 200,
        "mute_after_speak_ms": 300,
        "platform_auto_detect": true,
        "platform_override": null,
        "idle_blink_interval_s": [3, 6],
        "comfort_noise_dbfs": -60
    },
    "bot_join": {
        "enabled": false,
        "default_display_name": "AI Notes",
        "zoom_sdk": {
            "client_id": "",
            "client_secret": ""
        },
        "browser_bot": {
            "chromium_path": null,
            "headless": true,
            "user_data_dir": "~/.voiceagent/chromium-profile"
        }
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
    avatar_rt.py            # MuseTalk 1.5 real-time inference wrapper
    idle_renderer.py        # Driver video loop + blink + micro-saccade + breathing overlays
    webcam_writer.py        # pyvirtualcam frame writer + Zoom SDK raw video output
    realism.py              # Film grain, brightness jitter, micro-saccade, blink overlay generation
    meeting_behavior.py     # Mute/unmute automation, human presence simulation
    app_controller.py       # xdotool meeting app keyboard control (mute/unmute)
    bot_join.py             # Mode 2: Join meeting as separate participant (unified interface)
    zoom_bot.py             # Zoom Meeting SDK headless Linux bot (raw audio/video I/O)
    browser_bot.py          # Google Meet / Teams Puppeteer browser bot
    transcript_store.py     # MeetingTranscriptStore — wraps OCR Provenance MCP calls
    transcript_format.py    # Markdown document builder for meeting transcripts
    meeting_summary.py      # Post-meeting LLM summary + topic extraction
    mcp_client.py           # OCR Provenance MCP HTTP client (JSON-RPC POST to localhost:3377, session proxy for multi-agent isolation)
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
| `zoom-meeting-sdk` | Zoom SDK | Headless Linux meeting bot for Mode 2 (free from Zoom Marketplace, C++ with Python bindings) |
| `pyppeteer` or `playwright` | >=latest | Headless Chromium for Google Meet/Teams Mode 2 join (pip install) |
| `ocr-provenance-mcp` | Docker container | 4 services: MCP Server (3366), License Server (3000), Dashboard (3367), Session Proxy (3377). Transcript storage, semantic search, tagging, export. Markdown text passthrough (no GPU for transcripts). Session proxy at 3377 for multi-clone isolation. |

Already in project: `faster-whisper`, `faster-qwen3-tts`, `torch`, `numpy`, `pipecat`, `pyaudio`, `httpx` (for OCR Provenance HTTP calls), Resemble Enhance, Ollama, ClipCannon voice engine.

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
| **OCR Provenance Session Proxy** (`localhost:3377/mcp`) | Transcript storage, semantic search, tagging, export, provenance — via HTTP JSON-RPC through session proxy. Each clone gets its own isolated session. `"meetings"` database. Docker bridge auth trust (172.x, no API key needed from WSL2). No rate limits. Good concurrency via WAL + ref-counted connections. Markdown files skip OCR (text passthrough → chunk → embed → index, zero GPU). |
| **OCR Provenance Dashboard** (`localhost:3367`) | Meeting transcript browsing, search UI, tag management, document viewer, VLM Chunks — already built. 4th mandatory service. |

---

## Implementation Phases

### Phase 1: Audio Pipeline + Transcript Storage (Week 1-2)

1. **OCR Provenance MCP client** — `mcp_client.py` HTTP JSON-RPC client connecting to session proxy (port 3377) for per-clone session isolation. httpx.AsyncClient with connection pooling, proper GC/cleanup. Docker bridge auth trust (no API key). No rate limits.
2. **Transcript store** — `MeetingTranscriptStore` wrapping OCR Provenance: create `"meetings"` DB, Markdown document builder, periodic flush to disk, ingest on meeting end, crash recovery.
3. **Meeting audio capture** — PulseAudio monitor source capture in a background thread.
4. **Streaming transcription** — faster-whisper processing meeting audio in sliding windows, segments accumulated in memory + periodic Markdown flush.
4. **Address detection** — Name mention detection from transcript.
5. **Response generation** — Ollama LLM generating direct answers.
6. **Voice output** — TTS with full prosody + SECS >0.95 gate + Resemble Enhance.
7. **Virtual microphone** — PulseAudio null sink + remap source.
8. **Mute/unmute automation** — `MeetingAppController` with xdotool, platform auto-detection, comfort noise stream.
9. **Stale meeting recovery** — Auto-close meetings from crashes on startup.
10. **End-to-end audio test**: Someone says "Hey Nate, what time is the deadline?" → Clone unmutes in Zoom → Nate responds through virtual mic with verified voice → Clone re-mutes → full transcript persisted.

### Phase 2: Video Pipeline + Clone Realism (Week 3-4)

1. **Driver video system** — Record and process 15-30s loop videos per clone. Ping-pong seamless looping with 500ms cross-fade boundary.
2. **MuseTalk 1.5 integration** — Real-time lip sync (256x256 face region inpainting from audio mel spectrogram).
3. **Idle renderer** — Driver video loop playback + blink overlays (3-6s random gaussian interval) + micro-saccade eye jitter (1-2px at 2-3Hz) + gaze shift (every 15-30s) + breathing emphasis.
4. **Realism post-processing** — Film grain (1-2% gaussian), brightness jitter (±1% sine wave), white balance micro-shift. Makes output match typical webcam quality, not synthetic perfection.
5. **Speaking state transitions** — Cross-fade idle mouth → MuseTalk mouth (80ms) and back (120ms). Blinks and head motion continue during speech.
6. **Webcam writer** — pyvirtualcam (Mode 1) or Zoom SDK raw video frames (Mode 2). 30 FPS continuous, both idle and speaking.
7. **End-to-end video test**: Clone appears in Zoom with natural breathing, blinking, micro-saccade. When addressed, lips sync to response. Another human in the call should not immediately identify it as AI.

### Phase 3: Multi-Clone + Mode 2 Bot Join (Week 5-6)

1. **Post-meeting summary** — LLM-generated 3-5 bullet summary, auto-title, topic tags (written into Markdown before ingest).
2. **OCR Provenance tagging** — Auto-tag meetings by clone, platform, date, topic via `ocr_tag_create` + `ocr_tag_apply`.
3. **Speaker diarization** — pyannote integration for who-said-what.
4. **Multi-clone support** — Shared ASR/LLM, per-clone TTS/video. Each clone connects to session proxy (3377) which assigns isolated container sessions.
5. **Clone Meeting Manager** — Orchestrator for N clones.
6. **CLI commands** — `meeting start/stop/join/list/history/search/show/export/setup-devices`.
7. **Configuration** — `meeting.json` config file.
8. **Device setup script** — Automated v4l2loopback + PulseAudio provisioning.

### Phase 4: Mode 2 — Join as Participant (Week 7-8)

1. **Unified MeetingBotSession protocol** — Common interface for all join methods (audio stream in/out, video send, leave).
2. **Zoom Meeting SDK integration** — `zoom_bot.py` headless Linux bot with raw audio/video I/O, custom display name, JWT auth.
3. **Puppeteer browser bot** — `browser_bot.py` for Google Meet and Teams (headless Chromium, name entry, audio capture via virtual routing).
4. **Bot join orchestrator** — `bot_join.py` auto-detects platform from URL, routes to Zoom SDK or Puppeteer.
5. **CLI `meeting join`** — `--url`, `--name`, `--clone`, `--voice` flags.
6. **Audio routing** — Mode 2 bots receive audio from SDK/browser and feed it to the same transcription pipeline as Mode 1.
7. **End-to-end test**: `python -m voiceagent meeting join --url <zoom_url> --name "AI Notes" --clone nate` → bot appears in Zoom participant list as "AI Notes", transcribes, responds when addressed.

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
| `test_mcp_client.py` | HTTP JSON-RPC to OCR Provenance, session ID handling, connection pooling, error propagation |
| `test_transcript_store.py` | Markdown generation, flush to disk, ingest via OCR Provenance, search delegation, crash recovery |
| `test_transcript_format.py` | Markdown document format correctness, frontmatter, Q&A sections, speaker labels |
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
| Transcript persistence | Kill clone mid-meeting, restart, verify Markdown file on disk has all segments up to last flush |
| OCR Provenance ingest | End a meeting, verify document appears in OCR Provenance via `ocr_document_list` on `"meetings"` DB |
| Search via OCR Provenance | Ingest 3 meetings, search via `ocr_search` with natural language, verify ranked results |
| Concurrent sessions | 2 clones write transcripts simultaneously via different MCP session IDs, verify no cross-contamination |
| Export roundtrip | Export via `ocr_export`, verify Markdown contains all segments, speakers, timestamps |
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
13. Open OCR Provenance dashboard at `localhost:3367`, select `"meetings"` database — verify meeting document with full transcript, searchable, tagged.

---

## Risk Mitigation

| Risk | Mitigation |
|---|---|
| WSL2 lacks v4l2loopback | Mode 2 (bot join) recommended on WSL2 — avoids virtual webcam entirely. For Mode 1: Unity Capture (free) on Windows or custom WSL2 kernel with V4L2 enabled. |
| MuseTalk quality insufficient | Fall back to static image + audio only (still useful for phone meetings). Investigate MuseTalk fine-tuning on clone face. |
| SECS <0.95 on short utterances | Increase best-of-N to 7. Use longer reference clips. Fall back to 1.7B model. |
| GPU VRAM overflow with 2+ clones | Share ASR + diarization + LLM across clones. Only load clone-specific TTS + MuseTalk. Time-slice if needed. |
| False address detection | Conservative threshold (0.8). Require name + question pattern. Log all triggers for tuning. |
| Meeting audio echo | Clone TTS routes to its own null sink, not default output. Echo cancellation not needed since clone doesn't hear itself. |
| xdotool fails on Wayland | xdotool requires X11. On Wayland, use `ydotool` or `wtype` as alternatives. Document in setup guide. |
| Meeting app updates shortcuts | Keyboard shortcuts may change between app versions. Store shortcuts in config, not hardcoded. User can override via `behavior.platform_override`. |
| Mute/unmute timing visible to others | The brief unmute/re-mute is natural — humans do this constantly in meetings. The 200-300ms pauses make it look intentional, not robotic. |
| OCR Provenance server down | Clone still works for real-time conversation. Transcripts flush to Markdown files on disk. On next startup with server available, stale files are ingested. Fail-fast on search/export if server unreachable. All 4 OCR Provenance services (3366, 3367, 3000, 3377) must be running. |
| Concurrent clone writes | Each clone connects via session proxy (3377) which gives isolated container sessions. WAL mode, ref-counted connections, operation locking. Docker bridge auth trust — no API key needed from WSL2. No rate limits. |
