# PRD: Voice Agent — Personal AI Assistant with Total Recall

**Version**: 3.0
**Author**: Chris Royse
**Date**: 2026-03-28
**Status**: Draft

---

## 1. What This Is

A voice-first personal AI assistant that lives at `src/voiceagent/` inside the ClipCannon monolith repo. You talk to it. It talks back in your cloned voice (ClipCannon, 0.975 SECS). It knows everything you've been doing on your computer because it continuously captures screenshots, OCR-processes them via the OCR Provenance MCP server, and stores them as searchable text in organized databases. You can ask it anything about your past activity and it retrieves the answer from its permanent memory.

**Three systems, one agent:**
1. **ClipCannon** -- voice synthesis (read-only import, never modified)
2. **OCR Provenance MCP** -- document intelligence, memory storage, semantic search (153 tools via HTTP at `localhost:3366`)
3. **Qwen3-14B-FP8** -- reasoning engine (local, `~/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/`)

**What is NOT this system's job:** modifying ClipCannon code, running OCR Provenance (it's already running in Docker), training models, or cloud deployment.

---

## 2. Hardware

| Component | Spec |
|-----------|------|
| CPU | AMD Ryzen 9 9950X3D (16C/32T, 5.7GHz, 192MB L3 cache) |
| GPU | NVIDIA RTX 5090 (170 SMs, 32GB GDDR7, Blackwell) |
| RAM | 128GB DDR5-3592 |
| OS | Windows 11 Pro / WSL2 Linux |

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Voice Agent (src/voiceagent/)                  │
│                                                                   │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────────┐   │
│  │ ASR      │───>│ Qwen3-14B    │───>│ TTS (ClipCannon)     │   │
│  │ Streaming│    │ FP8 Brain    │    │ Streaming chunks     │   │
│  └──────────┘    └──────┬───────┘    └──────────────────────┘   │
│                         │                                        │
│              ┌──────────┴──────────┐                             │
│              │    Tool Router      │                             │
│              └──┬───────┬──────┬──┘                             │
│                 │       │      │                                  │
│     ┌───────────┘       │      └──────────┐                     │
│     ▼                   ▼                  ▼                     │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────┐            │
│  │ OCR Prov │   │ Screen       │   │ Agent        │            │
│  │ Client   │   │ Monitor      │   │ Registry     │            │
│  │ (HTTP)   │   │ (cron/daemon)│   │ (local DB)   │            │
│  └────┬─────┘   └──────┬───────┘   └──────────────┘            │
│       │                 │                                        │
└───────│─────────────────│────────────────────────────────────────┘
        │                 │
        ▼                 ▼
┌───────────────┐  ┌────────────────┐  ┌──────────────────────┐
│ OCR Provenance│  │ Screenshots    │  │ ClipCannon           │
│ MCP Server    │  │ /tmp/va_caps/  │  │ (voice profiles,     │
│ Docker :3366  │  │ → OCR → delete │  │  speak, verify)      │
│ 153 tools     │  │                │  │  read-only import    │
└───────────────┘  └────────────────┘  └──────────────────────┘
```

### 3.1 Data Flow: Screenshot → Memory

**CRITICAL: WSL2 cannot use Linux screenshot tools (scrot, PIL.ImageGrab, python-mss) to capture the Windows desktop.** There is no X11/Wayland display server connection to the Windows desktop from WSL2. All screenshot capture MUST go through PowerShell interop via `powershell.exe`.

**Design: Capture all day, OCR once at night (dream state).**

Screenshots are cheap (~400ms, ~1MB each). OCR is expensive (~37s per image via Marker-pdf). So the capture daemon takes screenshots and stores them locally with metadata all day, then the dream state batch-processes them through OCR Provenance overnight.

```
DAYTIME — Capture Only (no OCR, no GPU):
  Every screen-change detection (pixel diff, checked every 5 seconds):
  1. powershell.exe CopyFromScreen → /mnt/c/Users/Public/wsl_screenshot.png
     Per-monitor: only capture monitors that changed (pHash per-monitor diff)
  2. Copy PNG to ~/.voiceagent/captures/YYYY-MM-DD/screenshot_{timestamp}.png
  3. Collect active window metadata via powershell.exe:
     - Window title, process name, PID
     - Browser URL (if Chrome/Edge active, via UI Automation)
  4. Perceptual hash (pHash) compared against last 10 captures per monitor
     - If hamming distance < 5 (duplicate): delete file, skip
     - If unique: keep
  5. Check window title against privacy blocklist
     - If match (1Password, banking, etc.): delete file, skip
  6. Save metadata sidecar: ~/.voiceagent/captures/YYYY-MM-DD/screenshot_{timestamp}.json
     { "timestamp": "...", "app": "Code", "title": "server.py - clipcannon",
       "url": "", "monitor": 0, "phash": "a1b2c3..." }
  7. Clean up /mnt/c/Users/Public/ temp file

NIGHTTIME (4 AM Dream State) — Batch OCR:
  1. Unload all voice agent models from GPU (LLM, ASR, TTS)
  2. List all un-processed PNGs in ~/.voiceagent/captures/
  3. Batch ingest into OCR Provenance:
     ocr_ingest_files(files=[all_pngs], disable_image_extraction=true)
     → Marker-pdf OCR + chunking + embeddings, synchronous
     → ~37s per image × N images, but running unattended overnight
  4. For each processed document:
     - PII redaction via Presidio on extracted text
     - Auto-tag by app name from sidecar metadata
     - Store window metadata via ocr_document_update_metadata
  5. Deduplicate: ocr_document_duplicates → remove near-identical text
  6. Generate daily digest (Qwen3-14B summarizes the day's captures)
  7. Delete all processed PNGs from ~/.voiceagent/captures/
  8. Reload voice agent models

Result: Zero GPU contention during the day. Full OCR overnight when nobody cares about latency.
```

**Why this is better than real-time OCR:**
- Zero GPU contention during daytime — voice agent has full 32GB VRAM
- No 37-second processing delays interrupting the capture cadence
- Batch processing is more efficient (Marker loads once, processes many)
- Overnight processing has no time pressure — 500 screenshots × 37s = ~5 hours, finishes by 9 AM
- Screenshots are still captured with full metadata, so the agent knows WHAT you were doing (app, title, URL) even before OCR runs
- The only thing delayed is full-text search of screenshot content — but window title/app metadata is immediate

**What the agent knows DURING the day (before OCR):**
Even without OCR, the metadata sidecars give the agent real-time awareness:
- "At 3:15 PM you were in VS Code editing server.py"
- "You spent 2 hours in Chrome on GitHub"
- "You switched between Slack and Terminal 14 times between 2-4 PM"

The agent can answer time/app/window questions immediately from sidecar metadata. Full-text content search ("find the code with the JWT bug") becomes available after dream state OCR.

### 3.1.1 WSL2 Screenshot Implementation

PowerShell interop is the ONLY way to capture the Windows desktop from WSL2. The voice agent calls `powershell.exe` with a .NET script that uses `System.Drawing.Graphics.CopyFromScreen()`.

```python
# This is how screenshots work in WSL2 — no alternatives exist
import subprocess
from pathlib import Path

def capture_screen(output_path: str) -> str:
    win_tmp = "/mnt/c/Users/Public/wsl_screenshot.png"
    ps_script = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$gfx.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bmp.Save('C:\Users\Public\wsl_screenshot.png', [System.Drawing.Imaging.ImageFormat]::Png)
$gfx.Dispose(); $bmp.Dispose()
'''
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps_script],
        capture_output=True, timeout=10
    )
    if result.returncode != 0:
        raise RuntimeError(f"Screenshot failed: {result.stderr}")
    Path(output_path).write_bytes(Path(win_tmp).read_bytes())
    Path(win_tmp).unlink()
    return output_path
```

For **multi-monitor**: use `[System.Windows.Forms.Screen]::AllScreens` to iterate monitors and capture each separately. Do NOT use `VirtualScreen` stitched capture -- it wastes OCR processing on unchanged monitors.

**Per-monitor differential capture**: Each monitor maintains its own pHash history. On every capture cycle:

1. Capture all monitors separately → `monitor_0.png`, `monitor_1.png`, `monitor_2.png`
2. Compute pHash for each monitor image independently
3. Compare each monitor's pHash against its own last-known hash
4. Only upload + OCR monitors whose pHash changed (hamming distance >= 5)
5. Unchanged monitors are skipped entirely -- no upload, no OCR, no storage

```python
class PerMonitorCapture:
    def __init__(self, phash_threshold: int = 5):
        self.threshold = phash_threshold
        self.last_hashes: dict[int, str] = {}  # monitor_index -> last pHash

    def capture_cycle(self) -> list[dict]:
        """Returns list of changed monitors with their screenshots."""
        monitors = self._capture_all_monitors()  # PowerShell AllScreens
        changed = []

        for mon in monitors:
            idx = mon["index"]
            current_hash = imagehash.phash(Image.open(mon["path"]))
            prev_hash = self.last_hashes.get(idx)

            if prev_hash is None:
                # First capture for this monitor -- always process
                changed.append(mon)
            elif current_hash - prev_hash >= self.threshold:
                # Monitor content changed -- process
                changed.append(mon)
            else:
                # Duplicate -- delete screenshot, skip OCR
                os.unlink(mon["path"])

            self.last_hashes[idx] = current_hash

        return changed  # Only these get uploaded to OCR Provenance
```

This means: if you have 3 monitors and only monitor 1 changes, you OCR 1 image instead of 3. Over a full day (~480 capture cycles at 60s), this typically reduces OCR processing by 60-70% since reference monitors (docs, dashboards) rarely change.

Each monitor's OCR document is tagged with `monitor:0`, `monitor:1`, etc. so the agent knows which screen the content came from.

Latency: ~400ms per capture (PowerShell startup + .NET rendering for all monitors in one call). pHash comparison is <1ms per image. Only changed monitors incur the OCR upload + processing cost.

### 3.1.2 Active Window Metadata

Captured alongside every screenshot via PowerShell `GetForegroundWindow` P/Invoke:

```python
def get_active_window() -> dict:
    ps_script = r'''
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public class Win32 {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder t, int c);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
}
"@
$h = [Win32]::GetForegroundWindow()
$sb = New-Object System.Text.StringBuilder 256
[Win32]::GetWindowText($h, $sb, 256) | Out-Null
$pid = 0; [Win32]::GetWindowThreadProcessId($h, [ref]$pid) | Out-Null
$proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
@{title=$sb.ToString(); process=$proc.ProcessName; pid=$pid} | ConvertTo-Json -Compress
'''
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True, timeout=5
    )
    return json.loads(result.stdout.strip())
# Returns: {"title": "server.py - Visual Studio Code", "process": "Code", "pid": 12345}
```

This metadata is stored with every capture, making queries like "what file was I editing at 3pm?" trivially answerable without OCR.

### 3.2 OCR Provenance Integration

The voice agent communicates with OCR Provenance via **HTTP JSON-RPC** at `localhost:3366/mcp`. This is the MCP over HTTP transport -- same protocol the Docker container already exposes.

**Critical tools the agent uses:**

| Tool | Purpose |
|------|---------|
| `ocr_db_create` | Create new databases to organize captured data |
| `ocr_db_list` | Know what databases exist |
| `ocr_db_select` | Switch active database |
| `ocr_db_stats` | Check database size and counts |
| `ocr_db_summary` | AI-readable database profile |
| `ocr_ingest_files` | Ingest + process screenshots in one call (with `disable_image_extraction=true`) |
| `ocr_search` | Semantic/keyword/hybrid search across processed documents |
| `ocr_search_cross_db` | Search across ALL databases at once |
| `ocr_rag_context` | Assemble search context for the LLM |
| `ocr_document_list` | Browse stored documents |
| `ocr_document_get` | Get full document details |
| `ocr_document_delete` | Remove a document |
| `ocr_document_duplicates` | Find duplicate entries |
| `ocr_status` | Check processing status |
| `ocr_chunk_list` | Browse text chunks in a document |
| `ocr_chunk_context` | Expand result with surrounding text |
| `ocr_tag_create` | Create tags for categorization |
| `ocr_tag_apply` | Tag documents (e.g., "vscode", "browser", "terminal") |
| `ocr_tag_search` | Find all documents with a specific tag |

**Database Organization Strategy:**

The agent creates and manages OCR Provenance databases by category:

| Database | Content | Retention |
|----------|---------|-----------|
| `va_screen_captures` | All screenshot OCR text, tagged by application, with window metadata | Rolling 30 days |
| `va_conversations` | Transcript of voice conversations with the agent | Permanent |
| `va_documents` | Documents the user explicitly asks the agent to remember | Permanent |
| `va_ambient_audio` | Ambient mic transcriptions (15-min segments, speech only) | Rolling 14 days |
| `va_system_audio` | System audio loopback transcriptions (meetings, videos, podcasts) | Rolling 14 days |
| `va_clipboard` | Clipboard text entries (deduplicated by content hash) | Rolling 7 days |
| `va_user_knowledge` | Durable facts about user: preferences, contacts, appointments, projects | Permanent |
| `va_web_browsing` | Browser screenshots (tagged "browser") with URLs | Rolling 7 days |
| `va_code_activity` | IDE/terminal screenshots (tagged "code") with file paths from window titles | Rolling 14 days |

The agent maintains a **local registry** (`~/.voiceagent/registry.json`) mapping database names to their purposes, creation dates, and retention policies. This is the agent's own index -- separate from OCR Provenance's `_databases.db` registry.

### 3.3 Integration with ClipCannon

The voice agent imports ClipCannon's voice modules as a Python library. No MCP, no subprocess, no protocol overhead.

```python
from clipcannon.voice.profiles import get_voice_profile
from clipcannon.voice.inference import VoiceSynthesizer
from clipcannon.voice.verify import build_reference_embedding
from clipcannon.voice.enhance import enhance_speech
```

**Rules:**
- NEVER write to ClipCannon's database, config, or project directories
- NEVER modify ClipCannon source files
- Read voice profiles from `~/.clipcannon/voice_profiles.db` (read-only)
- Use ClipCannon's GPU ModelManager for TTS model loading
- Adapter layer at `voiceagent/adapters/clipcannon.py` absorbs API changes

### 3.2.1 GPU Management (CUDA 13.1/13.2 + NVFP4 + Green Contexts)

**Solution Stack**:

1. **`disable_image_extraction=true`** on all `ocr_ingest_files` calls. Skips Chandra VLM -- saves 10.6GB VRAM.

2. **NVFP4** cuts Qwen3-14B from ~15GB (FP8) to **~7.5GB (FP4)**. Total voice agent: ~13GB instead of ~21GB.

3. **Green Contexts** partition 170 SMs into isolated compute pools with deterministic latency:

| Context | SMs | Models | Peak VRAM |
|---------|-----|--------|-----------|
| **A (Voice, 70%)** | 120 SMs | Qwen3-14B FP4 + ASR + TTS | ~13GB |
| **B (Background, 30%)** | 50 SMs | Ambient Whisper + embeddings | ~2.5GB |

Total: ~15.5GB. **16.5GB headroom.** Marker OCR (~8GB) fits alongside everything.

**Daytime (FP4 + Green Contexts)**: Everything runs simultaneously. Voice conversation in Context A with guaranteed latency. Background ambient/system audio transcription in Context B. If OCR is needed during the day, it can run in Context B without touching Context A.

**Dream state (3 AM)**: Unload all voice models. Full 170 SMs + 32GB VRAM for batch OCR. Maximum throughput.

**Fallback (FP8, no Green Contexts)**: Temporal separation only. Voice agent owns GPU during day. Dream state owns GPU at night.

### 3.2.2 Wake Word and Activation

The agent supports two activation modes:

**1. Wake word (hands-free)**: OpenWakeWord v0.6+ running on CPU. ~50MB RAM, 3-5% single core, 80ms processing per audio chunk. Pre-trained model for "hey jarvis" or custom-trained wake word. Always listening via `sounddevice` InputStream.

```python
import openwakeword
from openwakeword.model import Model

oww = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
# Runs in background thread, fires callback when detected
```

**2. Global hotkey (push-to-talk)**: `pynput` global hotkey listener. Zero CPU when idle. Requires X server in WSL2 (WSLg provides this on Windows 11). Fallback: PowerShell-side hotkey listener.

Default: wake word mode. Configurable in config.json `"activation": "wake_word"` or `"activation": "hotkey"`.

### 3.2.3 Ambient Microphone Transcription

The microphone records continuously in the background. Audio is buffered to disk in 15-minute segments. At the end of each segment, VAD checks if any speech was detected. If yes, it's transcribed via Whisper and saved as a `.txt` file, then ingested into OCR Provenance `va_ambient_audio` database (text passthrough -- no Marker OCR, no GPU on OCR Prov side, instant embedding). If no speech detected, the audio segment is silently discarded.

**Pipeline (runs every 15 minutes):**

```
Mic audio (continuous) → 15-min WAV buffer on disk
    │
    ▼
Silero VAD scan: any speech frames in this segment?
    │
    ├── No speech detected → delete WAV, skip entirely
    │
    └── Speech detected →
        │
        ▼
    Whisper transcribe (ASR model already loaded on GPU)
        │
        ▼
    Save as ~/.voiceagent/transcripts/ambient_{timestamp}.txt
    Format: "[14:30] spoken text here\n[14:31] more text...\n"
        │
        ▼
    ocr_ingest_files(files=[.txt], disable_image_extraction=true)
    → Text passthrough: no Marker OCR, just chunk + embed
    → Into database: va_ambient_audio
    → Instant processing (<1 second)
        │
        ▼
    Delete WAV buffer (text is now in OCR Prov)
    Delete .txt file (embedded in OCR Prov)
```

**Why this is cheap:**
- ASR (Whisper) is already loaded on GPU for voice conversations -- zero additional VRAM
- `.txt` files are free in OCR Provenance (no Marker, no per-page charge)
- Embedding is the only GPU work on the OCR Prov side (~1GB VRAM, <1 second)
- Silent segments (often 80%+ of the day) are discarded immediately after VAD scan

**Silence handling:**
- Silero VAD scans the 15-min WAV for speech frames (80ms chunks, CPU, <100ms total)
- If zero speech frames detected: delete WAV, log "no speech in segment", done
- If speech detected but <5 seconds total: still transcribe (might be a quick comment)
- Empty/whitespace-only transcriptions after Whisper: delete, don't ingest

**Transcript format** (stored as `.txt`, one line per utterance with timestamp):
```
[2026-03-28 14:30:15] Hey can you look at the authentication module
[2026-03-28 14:30:22] I think the JWT refresh logic is wrong
[2026-03-28 14:35:41] Yeah that's the bug, the token expiry isn't being checked
```

**Privacy**: Same Presidio PII redaction runs on transcript text before ingestion. Configurable: `"ambient_mic": false` disables entirely.

**Disk management**: WAV buffers at 16kHz mono = ~15MB per 15-minute segment. Max 1 segment on disk at a time (previous is processed/deleted before next starts). Transcripts are <10KB each, deleted after OCR Prov ingestion.

```python
class AmbientMicCapture:
    SEGMENT_DURATION_S = 900    # 15 minutes
    SAMPLE_RATE = 16000
    WAV_DIR = Path.home() / ".voiceagent" / "audio_buffer"
    TRANSCRIPT_DIR = Path.home() / ".voiceagent" / "transcripts"
    MIN_SPEECH_SECONDS = 0.5    # ignore segments with <0.5s speech

    def segment_loop(self):
        while self.running:
            wav_path = self._record_segment()         # 15-min WAV to disk
            speech_seconds = self._vad_scan(wav_path)  # Silero VAD, CPU

            if speech_seconds < self.MIN_SPEECH_SECONDS:
                os.unlink(wav_path)
                self.log.debug(f"No speech in segment ({speech_seconds:.1f}s), discarded")
                continue

            transcript = self._transcribe(wav_path)    # Whisper, GPU (already loaded)
            transcript = self._redact_pii(transcript)  # Presidio
            os.unlink(wav_path)                        # WAV no longer needed

            if not transcript.strip():
                continue

            txt_path = self._save_transcript(transcript)
            self._ingest_to_ocr_prov(txt_path, "va_ambient_audio")
            os.unlink(txt_path)                        # txt no longer needed
```

**Configuration:**
```json
"ambient_mic": {
    "enabled": true,
    "segment_duration_s": 900,
    "min_speech_seconds": 0.5,
    "database": "va_ambient_audio",
    "retention_days": 14,
    "pii_redaction": true
}
```

### 3.2.3.1 System Audio Capture (Loopback)

Same pipeline as ambient mic, but captures all audio output from Windows (meetings, YouTube, podcasts, tutorials, calls). Uses the system loopback audio device.

**How loopback works in WSL2**: Windows exposes a virtual "Stereo Mix" or "What U Hear" device. PulseAudio in WSLg can access it. Alternatively, capture via PowerShell using `NAudio` or `Windows.Media.Capture` loopback and pipe the PCM to WSL2.

```python
# sounddevice can capture loopback if the device is exposed via PulseAudio
loopback_idx = find_device("stereo mix", kind="input")  # or "what u hear"
# If not available via PulseAudio, use PowerShell:
# powershell.exe -Command "Start-Process -FilePath 'ffmpeg' -ArgumentList '-f dshow -i audio=\"Stereo Mix\" output.wav'"
```

**Pipeline**: Identical to ambient mic (3.2.3) with these differences:

| | Ambient Mic | System Audio Loopback |
|---|---|---|
| Source | Microphone input | System audio output (loopback) |
| Database | `va_ambient_audio` | `va_system_audio` |
| Content | Your voice, conversations around you | Meetings, videos, podcasts, tutorials |
| VAD filtering | Catches your speech | Catches any speech in system output |
| Non-speech | Silence (discarded) | Music/SFX (Whisper produces garbage → discarded) |
| Retention | 14 days | 14 days |

**Non-speech handling**: When Whisper processes music or sound effects, it either produces empty output or hallucinated text (repeated phrases, nonsense). The transcript validator checks for:
- Empty/whitespace-only output → discard
- Repeated phrases (>3 identical lines) → hallucination, discard
- Very low average confidence from Whisper → discard
- <5 words total in 15-minute segment → likely noise, discard

**Use case**: "What did they say in that meeting at 2pm?" → searches `va_system_audio` for meeting transcript. "What was that YouTube tutorial about?" → finds the transcribed tutorial audio.

**Configuration:**
```json
"system_audio": {
    "enabled": true,
    "segment_duration_s": 900,
    "min_speech_seconds": 2.0,
    "database": "va_system_audio",
    "retention_days": 14,
    "pii_redaction": true,
    "loopback_device": "stereo mix",
    "min_words_per_segment": 5,
    "hallucination_repeat_threshold": 3
}
```

---

### 3.2.4 Clipboard Monitoring

Background thread polls `powershell.exe Get-Clipboard` every 500ms. Content-hashed for change detection. Unique clipboard entries are stored as text documents in `va_clipboard` OCR Provenance database.

```python
class ClipboardWatcher:
    INTERVAL = 0.5  # seconds
    def _get_clipboard(self) -> str:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=3
        )
        return result.stdout.rstrip("\r\n")

    def _poll(self):
        while self.running:
            content = self._get_clipboard()
            content_hash = hashlib.md5(content.encode()).hexdigest()
            if content_hash != self._last_hash and content.strip():
                self._last_hash = content_hash
                self._store(content)  # ingest into OCR Prov as text document
            time.sleep(self.INTERVAL)
```

### 3.2.5 PII Detection and Redaction

Microsoft Presidio v2.2+ scans all OCR output before storage. CPU-only, ~50ms per page after model warmup.

**Detected entity types**: PERSON, EMAIL_ADDRESS, PHONE_NUMBER, US_SSN, CREDIT_CARD, DATE_TIME, US_DRIVER_LICENSE, US_PASSPORT, IBAN_CODE.

**Redaction strategy**: Replace detected PII spans with type labels (`[REDACTED_SSN]`, `[REDACTED_CC]`). Original PII is never stored.

**Privacy blocklist**: Window titles matching these patterns cause the entire screenshot to be skipped (not captured at all):
- `*1Password*`, `*LastPass*`, `*Bitwarden*`
- `*Chase*`, `*Bank of America*`, `*Wells Fargo*` (banking)
- `*MyChart*`, `*patient portal*` (medical)
- Custom patterns configurable in `config.json`

```python
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()

def redact_pii(text: str) -> str:
    results = analyzer.analyze(text=text, language="en", score_threshold=0.4)
    if not results:
        return text
    anonymized = anonymizer.anonymize(text=text, analyzer_results=results)
    return anonymized.text
```

### 3.2.6 Cross-Conversation Persistent Memory

The agent maintains durable knowledge about the user across sessions using a dedicated OCR Provenance database `va_user_knowledge`.

When the user says "remember that I prefer dark mode" or "my dentist appointment is April 15th", the LLM extracts the fact and stores it as a document in `va_user_knowledge` via `ocr_ingest_files` (as a text file).

On startup, the agent loads recent knowledge entries via `ocr_search` on `va_user_knowledge` and injects them into the system prompt.

The LLM has a dedicated tool:
```json
{
    "name": "remember_fact",
    "description": "Store a durable fact about the user for future sessions",
    "parameters": {"fact": "string", "category": "preference|appointment|contact|project|other"}
}
```

When called, the agent creates a text document containing the fact, tagged with the category, and ingests it into `va_user_knowledge`. On next startup, `ocr_search(query="user preferences", database="va_user_knowledge")` retrieves relevant facts.

### 3.2.7 Dream State (3 AM Nightly Consolidation)

A scheduled job runs at 4:00 AM daily when the system is idle. It consolidates, deduplicates, and distills the day's data into compact knowledge -- like a brain consolidating short-term memory into long-term memory during sleep.

**Schedule**: Cron-style via `scheduler.py`. If the user is in an active conversation at 4 AM, the dream state defers until the conversation ends (max defer: 2 hours, then runs anyway).

**Dream Pipeline** (runs sequentially):

```
3:00 AM — DREAM STATE START (must complete by 5:00 AM)
│
├── Step 0: PRE-FLIGHT — COUNT AND BUDGET
│   Count un-processed PNGs in ~/.voiceagent/captures/
│   Estimate OCR time: count × 37s
│   If estimate > 110 minutes (leaving 10 min for steps 2-8):
│     Sort by timestamp (newest first — most relevant)
│     Truncate to 178 images (178 × 37s = ~110 min)
│     Remaining images carry over to next night
│   Log: { pending: N, will_process: M, estimated_minutes: X, carry_over: N-M }
│
├── Step 1: UNLOAD ALL VOICE MODELS
│   Unload Qwen3-14B, ASR, TTS from GPU → free all 32GB VRAM for OCR
│
├── Step 2: BATCH OCR (3:00 AM — ~4:50 AM, max 110 minutes)
│   Batch ingest the budgeted PNGs into OCR Provenance:
│     ocr_ingest_files(files=[budgeted_pngs], disable_image_extraction=true)
│     → Marker-pdf OCR + chunking + embeddings, synchronous
│     → ~37s per image. 190 images max ≈ ~117 min.
│   Track progress: log every 10th image with elapsed time and ETA
│   If wall-clock exceeds 4:50 AM: stop processing, carry remainder to next night
│   For each processed document:
│     - Read sidecar .json for window metadata (app, title, URL, monitor)
│     - ocr_document_update_metadata with app/title info
│     - Auto-tag: app name, category (code/browser/terminal/email/chat)
│     - PII redaction via Presidio on extracted text
│
├── Step 3: CLEANUP CAPTURES
│   Delete ALL processed PNGs + sidecars from ~/.voiceagent/captures/
│   Delete any stale captures older than 48 hours (failed retries)
│   Log: total_processed, total_deleted, disk_freed_mb
│
├── Step 4: DEDUPLICATION (per database)
│   For each va_* database:
│     ocr_document_duplicates(database) → find identical text
│     Keep earliest, delete rest
│     ocr_comparison_discover → find >0.90 similarity pairs
│     Same monitor + within 5 min → delete the newer one
│     ocr_db_maintenance(operation="vacuum") → reclaim disk space
│
├── Step 5: RELOAD QWEN3-14B (needed for digest + knowledge steps)
│   Load Qwen3-14B to GPU (~15GB). OCR Prov daemons already killed.
│
├── Step 6: DAILY DIGEST
│   Query yesterday's captures from OCR Prov + sidecar metadata
│   Feed to Qwen3-14B: "Summarize what the user did yesterday. Group by activity."
│   Store digest as document in va_conversations:
│     title: "Daily Digest — 2026-03-28", tagged: "digest", "date:2026-03-28"
│
├── Step 7: KNOWLEDGE EXTRACTION
│   Feed yesterday's voice conversations to Qwen3-14B:
│     "Extract durable facts about the user (preferences, appointments, projects)."
│   Store new facts in va_user_knowledge, tagged by category
│
├── Step 8: RETENTION ENFORCEMENT
│   Delete expired documents per database retention policy
│   ocr_db_maintenance(operation="vacuum") per database
│
├── Step 9: STATS + HEALTH
│   ocr_db_stats + ocr_health_check for each va_* database
│   Write dream report to ~/.voiceagent/logs/dream_2026-03-28.json
│   { images_pending, images_processed, images_carried_over,
│     duplicates_removed, facts_extracted, wall_clock_minutes }
│
├── Step 10: RELOAD VOICE MODELS
│   Reload ASR + TTS (Qwen3-14B already loaded from step 5)
│
└── 5:00 AM — DREAM STATE END — agent fully operational
```

**GPU Coordination**: Dream state only reads/searches/deletes existing documents — no new OCR processing. Only Qwen3-14B stays loaded (for digest generation and knowledge extraction). ASR + TTS can be unloaded to free VRAM if needed. No OCR Provenance GPU workers are invoked.

**Important**: All `ocr_ingest_files` calls throughout this system MUST use `disable_image_extraction=true`. Screenshots only need text extraction — VLM image analysis is wasted compute and VRAM. This parameter is being added to `ocr_ingest_files` (which triggers the full pipeline synchronously), eliminating the need for separate `ocr_process_pending` calls.

**Configuration**:

```json
"dream": {
    "enabled": true,
    "schedule": "0 3 * * *",
    "hard_deadline": "05:00",
    "max_ocr_minutes": 110,
    "defer_if_active": true,
    "max_defer_hours": 1,
    "near_dupe_similarity": 0.90,
    "near_dupe_window_minutes": 5,
    "digest_max_words": 500,
    "auto_extract_knowledge": true,
    "prioritize": "newest_first"
}
```

**Why "dream state"**: Human brains consolidate memories during sleep — replaying the day's experiences, discarding noise, strengthening important connections. This does the same thing: removes redundant captures, creates a searchable daily summary, and extracts durable facts into long-term memory. The result: 30-day rolling captures stay compact, and the agent's long-term knowledge grows automatically without the user having to say "remember this."

---

### 3.2.9 Session Restoration

On graceful shutdown or periodic checkpoint (every 5 minutes), the agent saves session state to `~/.voiceagent/session.json`:

```json
{
    "session_id": "va_2026-03-28_10-00-00",
    "started_at": "2026-03-28T10:00:00Z",
    "last_checkpoint": "2026-03-28T14:30:00Z",
    "conversation_summary": "User asked about authentication code from yesterday. Found relevant screenshots from 3pm showing JWT refactoring in VS Code. Also discussed upcoming dentist appointment.",
    "captures_since_start": 245,
    "active_databases": ["va_screen_captures", "va_user_knowledge", "va_conversations"],
    "pending_ocr_count": 3
}
```

On restart:
1. Load `session.json` if it exists
2. Inject `conversation_summary` into system prompt
3. Load user knowledge from `va_user_knowledge` database
4. Check for pending OCR items and process them
5. Resume capture daemon

The `conversation_summary` is generated by the LLM before shutdown: "Summarize this conversation in 3 sentences focusing on decisions made and information retrieved."

### 3.2.10 Whisper Contention Resolution

The ambient mic, system audio, and live conversation ASR all use Whisper. With Green Contexts this is handled:

- **Context A (voice)**: Live conversation ASR -- always has priority, 70% SMs
- **Context B (background)**: Ambient + system audio transcription -- 30% SMs, can be slower

If Green Contexts are unavailable (fallback mode): live conversation ASR holds a mutex. Background transcription jobs queue and wait. Live conversation ALWAYS wins.

### 3.2.11 Self-Capture Prevention

When the agent speaks through speakers, the mic picks it up. The system audio loopback also captures it. This creates duplicate/circular data.

**Fix**: Mute ambient mic AND system audio capture during active voice conversations. The conversation manager tracks state (IDLE/LISTENING/THINKING/SPEAKING). Capture threads check this state before recording. Resume capture when conversation returns to IDLE for >5 seconds.

Conversation transcripts already go to `va_conversations` -- no need to capture them again via ambient mic.

### 3.2.12 Cross-Database Search Default

When the user asks an ambiguous question ("what was that JWT thing?"), the LLM must search ALL databases, not guess one. The system prompt instructs the LLM: "For any recall/memory question, use `ocr_search_cross_db` with ALL va_* databases unless the user specifies a source. Only narrow to a single database if the user says 'in my code' or 'in that meeting' etc."

### 3.2.13 Whisper Hallucination Filtering

Whisper hallucinates on near-silent or noise-only audio. Common hallucinations:

```python
WHISPER_HALLUCINATIONS = {
    "thank you for watching", "thanks for watching", "please subscribe",
    "thanks for listening", "thank you for listening",
    "you", "the", "i", "so", "and",  # single repeated words
    "...", "♪", "♫",  # music/silence markers
}

def is_hallucination(text: str) -> bool:
    stripped = text.strip().lower()
    # Check known hallucinations
    if stripped in WHISPER_HALLUCINATIONS:
        return True
    # Check repeated phrases (>2 times)
    sentences = stripped.split(".")
    if len(sentences) > 2 and len(set(s.strip() for s in sentences if s.strip())) == 1:
        return True
    # Too few words for a 15-min segment
    if len(stripped.split()) < 5:
        return True
    return False
```

Applied to BOTH ambient mic and system audio transcriptions before ingestion.

### 3.2.14 Startup Self-Test

On first launch, run a 30-second end-to-end verification:

```
1. Screenshot: capture one screenshot → verify PNG exists, >10KB
2. Active window: get window title → verify non-empty string
3. Mic: record 1 second → verify audio buffer non-zero
4. System audio: record 1 second from loopback → verify device accessible
5. Clipboard: read clipboard → verify returns without error
6. OCR Prov: ocr_db_list → verify connection, list databases
7. LLM: generate("Say hello") → verify text output
8. TTS: synthesize("test") → verify audio file produced
9. GPU: query VRAM → verify 32GB total, correct device name
10. Green Contexts: query SM count → verify 170 SMs available
```

If ANY check fails: print which check failed, expected vs actual result, and refuse to start. All checks logged to `~/.voiceagent/logs/selftest.json`.

### 3.2.15 Health Monitoring and Proactive Alerts

Background health thread checks every 60 seconds:

| Check | Alert Condition | Notification |
|-------|----------------|-------------|
| OCR Provenance | HTTP health check fails | "OCR Provenance container is down" |
| Capture daemon | No captures in >10 minutes (if enabled) | "Screen capture has stopped" |
| Disk usage | Captures dir >80% of limit | "Capture storage almost full" |
| GPU VRAM | >90% utilization | "GPU memory critically high" |
| Dream state | Failed to run for >2 nights | "Dream state hasn't run, captures accumulating" |

Alerts are surfaced two ways:
1. **Proactive voice**: Next time you start a conversation, the agent opens with "Before we start, I should mention that screen captures have been failing for the last 3 hours because..."
2. **Log file**: `~/.voiceagent/logs/health.json` with timestamped alerts

### 3.2.16 Deterministic OCR Provenance Tool Calls (No LLM Required)

Most OCR Provenance interactions are predictable and should be called DIRECTLY by application code, not by the LLM. The LLM is only needed when the USER asks a question that requires search/reasoning.

**Application code calls directly (no LLM involvement):**

| Operation | Tool | Trigger | Code Handles |
|-----------|------|---------|-------------|
| Ingest screenshot | `ocr_ingest_files(disable_image_extraction=true)` | Dream state batch | Always same params |
| Ingest ambient transcript | `ocr_ingest_files` (.txt) | Every 15 min | Always same params |
| Ingest clipboard | `ocr_ingest_files` (.txt) | On change | Always same params |
| Create database | `ocr_db_create` | Startup (if missing) | Fixed database names |
| Switch database | `ocr_db_select` | Before each ingest | Known database name |
| Tag document | `ocr_tag_apply` | After ingest | Deterministic app-based tags |
| Update metadata | `ocr_document_update_metadata` | After ingest | Window title from sidecar |
| Find duplicates | `ocr_document_duplicates` | Dream state | Per-database sweep |
| Delete document | `ocr_document_delete` | Dream state retention | By age filter |
| Vacuum database | `ocr_db_maintenance` | Dream state | Standard cleanup |
| Health check | `ocr_health_check` | Every 60s monitoring | Standard check |
| Database stats | `ocr_db_stats` | Dream state reporting | Per-database |

These calls have fixed parameters known at compile time. The OCR client module wraps them as simple Python functions:

```python
class OCRProvClient:
    """Deterministic OCR Provenance calls. No LLM needed."""

    def ingest_screenshot(self, filepath: str) -> str:
        """Always uses va_screen_captures, always disables image extraction."""
        self._select_db("va_screen_captures")
        return self._call("ocr_ingest_files", {
            "file_paths": [filepath],
            "disable_image_extraction": True
        })

    def ingest_transcript(self, filepath: str, database: str) -> str:
        """Txt passthrough — instant, no OCR GPU."""
        self._select_db(database)
        return self._call("ocr_ingest_files", {"file_paths": [filepath]})

    def find_duplicates(self, database: str) -> list:
        self._select_db(database)
        return self._call("ocr_document_duplicates", {})

    def search(self, query: str, databases: list[str]) -> list:
        """This one IS called by the LLM via tool dispatch."""
        return self._call("ocr_search_cross_db", {
            "query": query, "databases": databases
        })
```

**LLM calls only when the user asks a question:**

| User Says | LLM Calls |
|-----------|-----------|
| "What was I doing at 3pm?" | `ocr_search_cross_db(query="activity at 3pm", databases=all_va_*)` |
| "Find that JWT code" | `ocr_search(query="JWT authentication", database="va_code_activity")` |
| "What did they say in the meeting?" | `ocr_search(query="meeting discussion", database="va_system_audio")` |
| "Remember I prefer dark mode" | `remember_fact(fact="prefers dark mode", category="preference")` |
| "What databases do I have?" | `ocr_db_list()` |

This means ~90% of OCR Provenance calls are deterministic code paths with zero LLM overhead. The LLM only activates for user-initiated search/recall queries.

### 3.2.17 Audio Input Device Selection

Uses `sounddevice` (already installed, v0.5.5) to enumerate and select audio input devices by name.

```python
import sounddevice as sd

def find_device(name_substring: str) -> int:
    for i, dev in enumerate(sd.query_devices()):
        if name_substring.lower() in dev["name"].lower() and dev["max_input_channels"] > 0:
            return i
    raise ValueError(f"No input device matching '{name_substring}'")
```

Config field: `"audio_device": "USB Audio"` (substring match) or `"audio_device": "default"`.

**WSL2 note**: On Windows 11 with WSLg, PulseAudio passthrough works automatically. On Windows 10, a PulseAudio server must run on the Windows side. Devices appear as `pulse` or `default` in WSL2.

### 3.3 CUDA 13.1/13.2 Optimizations for RTX 5090

The RTX 5090 (Blackwell GB202, Compute Capability 12.0) with CUDA 13.1/13.2 unlocks three capabilities that fundamentally change the architecture:

#### Green Contexts: Deterministic GPU Partitioning

Green Contexts provide static SM partitioning -- divide the 170 SMs into isolated pools with guaranteed compute allocation. Unlike MPS (thread percentage) or time-slicing (unpredictable latency), Green Contexts give hardware-level isolation.

**Voice Agent GPU Partition:**

| Context | SMs | VRAM* | Purpose |
|---------|-----|-------|---------|
| **A (Voice)** | 120 SMs (70%) | ~20GB | Qwen3-14B + ASR + TTS — latency-critical |
| **B (Background)** | 50 SMs (30%) | ~12GB | Ambient audio Whisper transcription, embedding |

*VRAM is shared (Green Contexts partition compute, not memory), but budgeted by context to prevent contention.

**Why this matters**: Background Whisper transcription of ambient audio (every 15 min) runs in Context B without ANY impact on voice conversation latency in Context A. No model swapping, no queuing, no contention. Both run simultaneously.

#### NVFP4: 50% VRAM Reduction for LLM

Blackwell's 5th-gen Tensor Cores support NVFP4 natively -- 4-bit weights with FP8 scales. This cuts Qwen3-14B from ~15GB (FP8) to **~7.5GB (FP4)** with <1% accuracy loss (validated on MLPerf benchmarks for similar-scale models).

**Impact on VRAM budget**: With FP4, the entire voice agent stack fits in ~13GB instead of ~21GB. This unlocks running OCR Provenance Marker (~8GB) SIMULTANEOUSLY during the day -- eliminating the dream-state-only limitation if desired.

#### Memory Bandwidth: 1,792 GB/s

78% more bandwidth than RTX 4090. Memory-bound operations fly:
- KV cache reads during LLM generation: 1.76x faster
- Embedding generation: 1.84x faster
- Audio buffer processing: effectively free

### 3.4 Docker Containerization Strategy

**Architecture**: Two processes -- a Docker container (Linux + CUDA) for the AI stack, and a lightweight Windows companion for capture.

```
┌────────────────────────────────────────────────────────────┐
│  Windows Host                                               │
│                                                              │
│  ┌──────────────────────────┐    ┌───────────────────────┐  │
│  │ Companion (Python .exe)  │    │ OCR Provenance Docker │  │
│  │ • Screenshot capture     │───>│ (already running)     │  │
│  │ • Active window metadata │    │ Port 3366             │  │
│  │ • Clipboard monitoring   │    └───────────────────────┘  │
│  │ • Mic + system audio     │                               │
│  │ • Saves to shared volume │    ┌───────────────────────┐  │
│  └────────────┬─────────────┘    │ Voice Agent Docker    │  │
│               │ shared volume    │ • Qwen3-14B (FP4)     │  │
│               └─────────────────>│ • ASR (Whisper)       │  │
│                                  │ • TTS (ClipCannon)    │  │
│                                  │ • Conversation engine │  │
│                                  │ Port 8765 (WebSocket) │  │
│                                  └───────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

**Why two processes**:
- Docker (Linux) containers CANNOT call Windows APIs (no PowerShell, no Win32, no UI Automation)
- The Windows companion handles all Windows-native capture (screenshots, clipboard, audio devices, window titles)
- The Docker container handles all AI/ML (GPU inference, conversation, OCR integration)
- Communication via shared Docker volume for files + HTTP for commands

**Windows Companion** (`voiceagent-capture.exe`, ~5MB PyInstaller bundle):
- Captures screenshots via native `PIL.ImageGrab.grab()` (works natively on Windows, no PowerShell needed)
- Gets active window via `win32gui.GetForegroundWindow()` + `win32process`
- Monitors clipboard via `win32clipboard`
- Records mic + system audio via `sounddevice` (direct Windows audio devices)
- Saves everything to a shared volume mount (e.g., `C:\voiceagent_data\`)
- Exposes a tiny HTTP API on localhost for the Docker container to query status

**Docker Container** (`voiceagent:latest`):
- Mounts `C:\voiceagent_data\` as `/data/captures/`
- Reads captures, processes them, manages conversations
- Full CUDA GPU access via Docker Desktop WSL2 backend
- Connects to OCR Provenance container via Docker network

This eliminates ALL WSL2 interop hacks (PowerShell subprocess calls, PulseAudio passthrough, etc.). Native Windows APIs for capture, native CUDA for AI.

---

## 4. LLM: Qwen3-14B — FP4 on Blackwell

**Model location**: `/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/`

**Precision**: NVFP4 (Blackwell-native). Load FP8 checkpoint, quantize to FP4 at load time via vLLM or TensorRT-LLM. 4-bit weights + FP8 scale per 16 values + FP32 tensor scale = 4.5 bits effective.

**VRAM**: ~7.5GB for FP4 inference (down from ~15GB FP8). Validated <1% accuracy loss on MLPerf benchmarks.

**Fallback**: If FP4 quantization degrades tool-calling accuracy on Qwen3, fall back to FP8 (~15GB). Both fit the VRAM budget.

**Why Qwen3-14B**:
- 14B has significantly better tool-calling accuracy and multi-turn reasoning than 8B
- FP4 on Blackwell tensor cores: 3x throughput vs FP8, native hardware support
- Already downloaded and cached locally

**Context Window**: 32K tokens. Conversation history + OCR Provenance search results + system prompt must fit within this.

**System Prompt Structure**:
```
[Identity: personal assistant for Chris Royse]
[Voice profile: boris]
[Available tools: OCR Provenance tools + conversation tools]
[Database registry: what databases exist and what they contain]
[Current date/time]
[Conversation history: last N turns, summarized if >8K tokens]
[User's current query]
```

**Tool Calling**: Qwen3-14B supports structured tool calling natively. The agent defines tools as JSON schemas, the LLM generates tool_call messages, and the agent dispatches them.

---

## 5. Package Structure

```
src/
    voiceagent/
        __init__.py
        agent.py                        # Main VoiceAgent class — lifecycle, startup, shutdown
        config.py                       # VoiceAgentConfig (dataclass, loaded from ~/.voiceagent/config.json)
        errors.py                       # All exceptions — FailFast, no silent fallbacks

        asr/
            __init__.py
            streaming.py                # StreamingASR: 200ms audio chunks → streaming text
            vad.py                      # Silero VAD v5 (ONNX, CPU)
            endpointing.py              # 600ms silence = utterance end
            entities.py                 # Name/email/number extraction + confirmation

        brain/
            __init__.py
            llm.py                      # Qwen3-14B-FP8 loader, streaming generation, tool dispatch
            prompts.py                  # System prompt builder (injects registry, datetime, history)
            tools.py                    # Tool registry: OCR Prov tools + conversation tools
            context.py                  # Context window management (32K budget)

        conversation/
            __init__.py
            manager.py                  # Full-duplex state machine (IDLE/LISTENING/THINKING/SPEAKING)
            turn_taking.py              # Floor control, endpoint detection
            barge_in.py                 # Interruption detection (<200ms), TTS flush
            backchannel.py              # "mm-hmm" / "right" / "okay" injection
            state.py                    # ConversationState dataclass

        tts/
            __init__.py
            streaming.py                # LLM tokens → sentence chunks → ClipCannon TTS → audio
            chunker.py                  # Sentence boundary detection (. ! ? and long clause splits)
            warmup.py                   # Pre-load voice embeddings on startup
            cache.py                    # Common phrase audio cache (pre-rendered)

        transport/
            __init__.py
            websocket.py                # WebSocket bidirectional audio
            webrtc.py                   # WebRTC peer connection
            sip.py                      # SIP/telephony (Twilio/Telnyx)
            opus.py                     # Opus encode/decode
            echo_cancel.py              # AEC (WebRTC built-in or SpeexDSP)
            noise_suppress.py           # RNNoise (CPU, <1ms/frame)

        memory/
            __init__.py
            ocr_client.py              # HTTP JSON-RPC client for OCR Provenance at localhost:3366
            screen_capture.py           # Screenshot daemon: PowerShell interop, pHash dedup, save to disk
            ambient_mic.py              # Continuous mic recording, VAD, Whisper transcribe, .txt ingest
            system_audio.py             # System audio loopback capture, same pipeline as ambient_mic
            clipboard_watcher.py        # Clipboard monitoring: PowerShell Get-Clipboard polling, dedup
            active_window.py            # Active window metadata: PowerShell GetForegroundWindow + UI Automation
            pii_filter.py              # Presidio PII detection + redaction before storage
            registry.py                 # Agent's database registry (~/.voiceagent/registry.json)
            retriever.py               # Search across OCR Prov databases, assemble RAG context
            knowledge.py               # Cross-session persistent memory: user facts, preferences
            dream.py                   # 4 AM nightly consolidation: dedup, digest, knowledge extraction, retention
            scheduler.py               # Cron/interval scheduler for capture + dream state + maintenance
            session.py                  # Session state serialization + restoration on restart

        adapters/
            __init__.py
            clipcannon.py              # ClipCannon voice system adapter (import wrapper)

        activation/
            __init__.py
            wake_word.py               # OpenWakeWord v0.6+ (CPU, "hey jarvis" or custom)
            hotkey.py                  # Global hotkey push-to-talk (pynput or PowerShell fallback)

        eval/
            __init__.py
            tau_voice.py               # tau-Voice benchmark runner
            vaqi.py                    # VAQI score computation
            latency.py                 # Per-stage + end-to-end latency profiler
            task_completion.py         # Task success rate scorer
            conversation_quality.py    # Turn-taking, interruption, dead air metrics
            benchmark_runner.py        # Unified runner: all benchmarks, JSON output

        db/
            __init__.py
            schema.py                  # SQLite schema for conversations, turns, metrics
            connection.py              # Connection factory (separate from ClipCannon)

        server.py                      # FastAPI server (REST + WebSocket)
        cli.py                         # CLI: voiceagent serve|talk|bench|capture|registry

    clipcannon/                        # UNTOUCHED — read-only dependency
        ...
```

---

## 6. Screen Capture System

### 6.1 Capture Daemon

Runs as a background thread. Checks for screen changes every 5 seconds, captures only on change. NO OCR during daytime -- screenshots saved to disk with metadata sidecars, batch-processed during dream state.

```python
class ScreenCaptureDaemon:
    """Captures screenshots to disk with metadata. OCR happens in dream state only."""

    CAPTURE_DIR = Path.home() / ".voiceagent" / "captures"
    DIFF_CHECK_INTERVAL_S = 5    # check for screen changes every 5s
    PHASH_THRESHOLD = 5           # hamming distance < 5 = duplicate
    MAX_CAPTURES_PER_DAY = 190    # hard cap: 190 × 37s = ~117 min OCR (fits in 2-hour dream window)
    MAX_DISK_MB = 500             # ~190 PNGs at ~2MB each ≈ 380MB, 500MB with headroom

    def capture_loop(self):
        while self.running:
            if self._screen_changed():              # fast pixel-sum diff (<1ms)
                filepath = self._take_screenshot()   # PowerShell CopyFromScreen
                phash = self._compute_phash(filepath)

                if self._is_duplicate(phash):
                    os.unlink(filepath)
                elif self._check_privacy_blocklist():
                    os.unlink(filepath)
                elif self.today_count >= self.MAX_CAPTURES_PER_DAY:
                    os.unlink(filepath)
                elif self._disk_usage_mb() >= self.MAX_DISK_MB:
                    os.unlink(filepath)
                    self.log.warning("Disk limit reached, skipping")
                else:
                    metadata = self._get_active_window()
                    self._save_sidecar(filepath, metadata, phash)
                    self.today_count += 1

            time.sleep(self.DIFF_CHECK_INTERVAL_S)
```

### 6.2 Disk Management and Garbage Collection

**The #1 risk with continuous screen capture is filling the disk.** Multiple safeguards prevent this:

| Guard | Limit | Action |
|-------|-------|--------|
| Per-day capture cap | 190 screenshots/day | Stop capturing for the day (190 × 37s = ~117 min OCR, fits 2-hour dream window) |
| Disk usage cap | 500 MB for `~/.voiceagent/captures/` | Stop capturing until dream state clears space |
| Duplicate detection | pHash hamming < 5 | Delete immediately, never saved |
| Privacy blocklist match | Window title match | Delete immediately, never saved |
| Dream state cleanup | After OCR processing | Delete ALL processed PNGs |
| Stale capture cleanup | Captures older than 48 hours un-processed | Delete (dream state failed or was skipped) |

**Storage math**: A 1920x1080 PNG screenshot is ~1-3MB. At 2GB cap, that's 700-2000 screenshots max on disk at any time. Dream state processes and deletes them nightly, so the typical daily accumulation is 200-500 screenshots (~500MB-1.5GB) that get cleared overnight.

**Capture directory structure**:
```
~/.voiceagent/captures/
    2026-03-28/
        screenshot_143215.png       # 2:32:15 PM
        screenshot_143215.json      # metadata sidecar
        screenshot_143512.png
        screenshot_143512.json
    2026-03-29/
        ...
```

**Sidecar metadata format** (JSON, ~200 bytes each):
```json
{
    "timestamp": "2026-03-28T14:32:15Z",
    "app": "Code",
    "title": "server.py - clipcannon - Visual Studio Code",
    "url": "",
    "monitor": 0,
    "phash": "a1b2c3d4e5f6a7b8",
    "processed": false
}
```

**On startup**: Check `~/.voiceagent/captures/` disk usage. If over limit, delete oldest un-processed day directories until under limit. Log a warning.

**On dream state completion**: Delete all PNGs + sidecars for successfully processed days. Mark any failed captures for retry the next night. After 2 failed retries, delete anyway.

### 6.3 Deduplication

Uses **perceptual hashing** (pHash) via the `imagehash` library:
- Compute pHash of new screenshot
- Compare hamming distance against last 10 stored hashes
- If distance < 5: screens are visually identical → skip
- This catches: idle screens, paused videos, static documents

**Why pHash and not file hash**: File hashes differ on every capture due to timestamp rendering, cursor position, notification badges. pHash compares visual similarity.

### 6.3 Auto-Tagging

After OCR processing, the agent reads the extracted text and auto-tags by detected application:
- Text contains "Visual Studio Code" or file tree patterns → tag: `code`
- Text contains URL bar, tabs, web content → tag: `browser`
- Text contains `$` prompts, command output → tag: `terminal`
- Text contains email headers, inbox → tag: `email`
- Text contains chat messages, Slack/Discord UI → tag: `chat`

Tags are applied via `ocr_tag_create` + `ocr_tag_apply`.

### 6.4 Cleanup

- Screenshots are deleted from `/tmp/va_captures/` immediately after successful OCR processing
- Failed screenshots are retried on next cycle, then deleted after 3 failures
- OCR Provenance handles document storage — no local copies needed
- Rolling retention: `va_screen_captures` database auto-purges entries older than 30 days via a daily maintenance cron

---

## 7. Memory Retrieval

When the user asks "what was I doing at 3pm yesterday?" or "find that code I was looking at with the authentication bug":

```
User voice → ASR → text query
    │
    ▼
LLM decides which tool to call:
    │
    ├── ocr_search(query="authentication bug code", database="va_code_activity")
    │   → Returns matching chunks with page numbers, timestamps, similarity scores
    │
    ├── ocr_search_cross_db(query="authentication bug", databases=["va_code_activity", "va_screen_captures"])
    │   → Searches across multiple databases
    │
    ├── ocr_rag_context(query="what was I doing at 3pm yesterday")
    │   → Assembles full context with surrounding chunks for RAG
    │
    └── ocr_document_list(database="va_screen_captures", filter="created_at > '2026-03-27T15:00:00'")
        → Lists documents captured around that time
    │
    ▼
LLM synthesizes results into natural language answer
    │
    ▼
TTS speaks the answer
```

**Context Assembly for LLM:**
1. User's question enters the context window
2. LLM generates tool_call for the appropriate OCR Provenance search
3. Search results (text chunks + metadata) injected into context
4. LLM reads the results and generates a conversational answer
5. Answer is streamed to TTS

---

## 8. Agent Registry

The agent maintains its own registry at `~/.voiceagent/registry.json`:

```json
{
    "databases": {
        "va_screen_captures": {
            "purpose": "Continuous screen capture OCR text",
            "created_at": "2026-03-28T10:00:00Z",
            "retention_days": 30,
            "auto_tag": true,
            "embedding_model": "general"
        },
        "va_conversations": {
            "purpose": "Voice conversation transcripts with the assistant",
            "created_at": "2026-03-28T10:00:00Z",
            "retention_days": null,
            "auto_tag": false,
            "embedding_model": "general"
        },
        "va_documents": {
            "purpose": "Documents the user explicitly asked to remember",
            "created_at": "2026-03-28T10:00:00Z",
            "retention_days": null,
            "auto_tag": false,
            "embedding_model": "general"
        }
    },
    "last_capture_at": "2026-03-28T14:32:00Z",
    "total_captures": 1247,
    "total_unique": 892,
    "duplicates_skipped": 355
}
```

On startup, the agent:
1. Reads `registry.json`
2. Verifies each database exists in OCR Provenance via `ocr_db_list`
3. Creates any missing databases via `ocr_db_create`
4. If `registry.json` doesn't exist, creates it and initializes all databases
5. Errors hard if OCR Provenance is not reachable at `localhost:3366`

---

## 9. VRAM Budget

### With NVFP4 (preferred — Blackwell native):

| Model | VRAM | Purpose |
|-------|------|---------|
| Qwen3-14B **FP4** | **~7.5GB** | LLM reasoning, tool calling |
| Distil-Whisper Large v3 (INT8) | ~1.5GB | Streaming ASR (Context A) |
| Distil-Whisper (ambient, Green Context B) | shared | Background transcription (same weights, separate context) |
| Qwen3-TTS (ClipCannon) | ~4GB | Voice synthesis |
| Silero VAD v5 (ONNX) | CPU | Voice activity detection |
| KV Cache + Buffers | ~2GB | Runtime overhead for 32K context |
| **Total** | **~15GB** | **Leaves 17GB headroom** |

17GB headroom means OCR Provenance Marker (~8GB) + embeddings (~1GB) can run SIMULTANEOUSLY during the day via Green Context B. Dream state becomes optional optimization, not a requirement.

### Fallback with FP8 (if FP4 degrades tool-calling):

| Model | VRAM | Purpose |
|-------|------|---------|
| Qwen3-14B FP8 | ~15GB | LLM reasoning |
| Distil-Whisper + TTS + KV Cache | ~7.5GB | ASR + voice synthesis + runtime |
| **Total** | **~22.5GB** | **Leaves ~9.5GB headroom** |

9.5GB headroom still fits Marker (~8GB) for daytime OCR, but tighter. Dream state batch processing remains the safer path in FP8 mode.

---

## 10. Latency Budget

Target: **<500ms mouth-to-ear** on local GPU.

| Stage | Budget (FP4) | Budget (FP8) | Strategy |
|-------|-------------|-------------|----------|
| ASR streaming partial | 80ms | 100ms | Distil-Whisper INT8, 200ms audio chunks, VAD |
| Conversation manager | 5ms | 5ms | CPU state machine, no I/O |
| LLM first token | **120ms** | 200ms | Qwen3-14B FP4: 3x tensor core throughput, smaller KV cache |
| TTS first audio byte | 130ms | 150ms | Sentence-chunked, pre-loaded voice embedding |
| Audio encoding + transport | 30ms | 30ms | Opus 20ms frames, local WebSocket |
| **Total** | **~365ms** | **~485ms** | |

FP4 delivers ~120ms faster end-to-end than FP8 due to 3x tensor core throughput and 50% smaller KV cache reads (1,792 GB/s bandwidth handles the smaller cache even faster). Sub-400ms beats every cloud and most on-premise providers.

---

## 11. Conversation Database

At `~/.voiceagent/agent.db`. Separate from ClipCannon and OCR Provenance.

```sql
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,                    -- UUID
    voice_profile TEXT NOT NULL,            -- ClipCannon voice profile name
    started_at TEXT NOT NULL,               -- ISO 8601
    ended_at TEXT,
    duration_ms INTEGER,
    turns INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active'   -- active|completed|error
        CHECK (status IN ('active', 'completed', 'error'))
);

CREATE TABLE turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    turn_number INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'agent', 'system')),
    text TEXT NOT NULL,
    started_at TEXT NOT NULL,
    duration_ms INTEGER,
    latency_ms INTEGER,                     -- agent response latency
    asr_confidence REAL,                    -- for user turns
    interrupted BOOLEAN DEFAULT FALSE,
    tool_calls_json TEXT                    -- JSON array of tool calls
);

CREATE TABLE tool_executions (
    id TEXT PRIMARY KEY,                    -- UUID
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    turn_id INTEGER REFERENCES turns(id),
    tool_name TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    result_json TEXT,
    success BOOLEAN NOT NULL,
    duration_ms INTEGER NOT NULL,
    error_message TEXT,                     -- populated on failure
    executed_at TEXT NOT NULL
);

CREATE TABLE metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE capture_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filepath TEXT NOT NULL,
    phash TEXT NOT NULL,
    is_duplicate BOOLEAN NOT NULL,
    ocr_document_id TEXT,                   -- OCR Provenance document ID (null if duplicate)
    ocr_database TEXT,                      -- which OCR Prov database
    success BOOLEAN NOT NULL,
    error_message TEXT,
    captured_at TEXT NOT NULL,
    processed_at TEXT
);

CREATE INDEX idx_turns_conversation ON turns(conversation_id);
CREATE INDEX idx_tool_exec_conversation ON tool_executions(conversation_id);
CREATE INDEX idx_metrics_conversation ON metrics(conversation_id);
CREATE INDEX idx_capture_log_time ON capture_log(captured_at DESC);
CREATE INDEX idx_capture_log_phash ON capture_log(phash);
```

---

## 12. Configuration

At `~/.voiceagent/config.json`:

```json
{
    "version": "2.0",
    "llm": {
        "model_path": "/home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a",
        "max_new_tokens": 512,
        "temperature": 0.7,
        "device": "cuda:0"
    },
    "asr": {
        "model": "distil-whisper-large-v3",
        "compute_type": "int8",
        "language": "en",
        "chunk_ms": 200,
        "endpoint_silence_ms": 600,
        "vad_threshold": 0.5
    },
    "tts": {
        "default_voice": "boris",
        "enhance": false,
        "sentence_min_words": 3,
        "sentence_max_words": 50,
        "cache_common_phrases": true
    },
    "conversation": {
        "barge_in_threshold_ms": 300,
        "barge_in_db_threshold": -30,
        "backchannel_interval_s": 3,
        "max_silence_ms": 3000,
        "filler_threshold_ms": 2000,
        "max_turns": 200,
        "max_duration_s": 3600
    },
    "activation": {
        "mode": "wake_word",
        "wake_word_model": "hey_jarvis",
        "wake_word_threshold": 0.6,
        "hotkey": "ctrl+space"
    },
    "capture": {
        "enabled": true,
        "diff_check_interval_s": 5,
        "capture_dir": "~/.voiceagent/captures",
        "phash_threshold": 5,
        "phash_history": 10,
        "max_captures_per_day": 1500,
        "max_disk_mb": 2000,
        "multi_monitor": "per_monitor_diff",
        "default_database": "va_screen_captures",
        "retention_days": 30,
        "stale_capture_hours": 48,
        "privacy_blocklist": ["1Password", "LastPass", "Bitwarden", "Chase", "Bank of America"]
    },
    "clipboard": {
        "enabled": true,
        "poll_interval_s": 0.5,
        "database": "va_clipboard",
        "retention_days": 7,
        "min_length": 10,
        "max_length": 50000
    },
    "pii": {
        "enabled": true,
        "entities": ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "CREDIT_CARD"],
        "score_threshold": 0.4,
        "redaction_char": "[REDACTED]"
    },
    "audio_device": "default",
    "ocr_provenance": {
        "base_url": "http://localhost:3366",
        "mcp_endpoint": "/mcp",
        "upload_endpoint": "/api/upload",
        "timeout_s": 30
    },
    "transport": {
        "default": "websocket",
        "websocket_port": 8765,
        "audio_format": "pcm_16khz",
        "output_sample_rate": 24000
    },
    "gpu": {
        "device": "cuda:0"
    }
}
```

---

## 13. CLI

```bash
# Start the voice agent (loads models, starts capture daemon, opens WebSocket)
voiceagent serve --port 8765

# Interactive voice conversation (local microphone)
voiceagent talk --voice boris

# Manual capture control
voiceagent capture start       # start screenshot daemon
voiceagent capture stop        # stop screenshot daemon
voiceagent capture status      # show capture stats
voiceagent capture now         # take one screenshot immediately

# Registry management
voiceagent registry list       # show all managed databases
voiceagent registry sync       # verify databases exist in OCR Prov
voiceagent registry cleanup    # run retention policy (delete old entries)

# Benchmarks
voiceagent bench --suite latency
voiceagent bench --suite vaqi
voiceagent bench --suite tau-voice
voiceagent bench --all --output results/

# Metrics
voiceagent metrics --last 24h
```

---

## 14. API

### 14.1 WebSocket (Primary)

```
ws://localhost:8765/conversation

Client → Server (binary): 16kHz 16-bit PCM mono audio chunks
Client → Server (text):   {"type": "start", "voice": "boris"}
                           {"type": "end"}
Server → Client (binary): 24kHz 16-bit PCM mono audio chunks
Server → Client (text):   {"type": "transcript", "text": "...", "final": true}
                           {"type": "agent_text", "text": "...", "turn": 3}
                           {"type": "tool_call", "tool": "ocr_search", "status": "executing"}
                           {"type": "state", "state": "SPEAKING"}
                           {"type": "metrics", "latency_ms": 420}
                           {"type": "end", "reason": "completed"}
```

### 14.2 REST API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Model load status + OCR Prov connectivity |
| GET | `/conversations` | List conversations (paginated) |
| GET | `/conversations/{id}` | Conversation detail with turns |
| GET | `/capture/status` | Capture daemon status and stats |
| POST | `/capture/now` | Trigger immediate screenshot |
| GET | `/registry` | List managed databases |
| POST | `/warmup` | Pre-load all models |
| GET | `/voices` | List ClipCannon voice profiles |

---

## 15. Error Handling

**FAIL FAST. NO FALLBACKS. NO WORKAROUNDS.**

| Failure | Behavior |
|---------|----------|
| OCR Provenance unreachable at startup | `raise ConnectionError("OCR Provenance not reachable at localhost:3366")` -- do not start |
| Qwen3-14B-FP8 model files missing | `raise FileNotFoundError(f"Model not found at {model_path}")` -- do not start |
| ClipCannon voice profile not found | `raise ValueError(f"Voice profile '{name}' not in voice_profiles.db")` -- do not start |
| Screenshot capture fails | `raise RuntimeError(f"scrot failed: {stderr}")` -- log full error, re-raise |
| OCR Provenance upload fails | `raise IOError(f"Upload to OCR Prov failed: {status} {body}")` -- log full response |
| OCR processing fails | `raise RuntimeError(f"ocr_process_pending failed: {error}")` -- log tool response |
| LLM generation fails | `raise RuntimeError(f"Qwen3-14B generation failed: {e}")` -- log full traceback |
| TTS synthesis fails | `raise RuntimeError(f"ClipCannon TTS failed: {e}")` -- log full traceback |
| Database write fails | `raise sqlite3.Error(f"DB write failed: {e}")` -- log query + params |
| Tool call fails | Log full tool name, params, error. Return error to LLM so it can inform user |

Every error log includes:
- Timestamp (ISO 8601)
- Component (asr/llm/tts/capture/ocr_client/registry)
- Full exception traceback
- Input data that caused the failure
- System state at time of failure (GPU memory, active conversations, capture count)

Logging to: stderr + `~/.voiceagent/logs/voiceagent.log` (rotating, 10MB max, 5 backups).

---

## 16. Testing Requirements

### 16.1 Rules

- **NO MOCK DATA.** Every test hits the real system (real OCR Provenance, real database, real model inference).
- **NO BACKWARDS COMPATIBILITY.** If a test would require a workaround to pass, the code is broken. Fix the code.
- **FAIL FAST.** Tests must fail loudly with clear error messages. A passing test on a broken system is worse than a crash.

### 16.2 Full State Verification Protocol

Every test must:

1. **Define Source of Truth**: Identify where the result lives (database table, OCR Provenance database, file on disk, GPU memory state).
2. **Execute & Inspect**: Run the operation, then immediately perform a **separate read** on the source of truth to verify the data was written correctly. Do not trust return values alone.
3. **Boundary & Edge Case Audit**: For each test, simulate 3 edge cases (empty input, maximum limits, invalid formats). Print system state before and after.
4. **Evidence of Success**: Provide a log showing the actual data in the system after execution. If something was saved to a database, query the database and assert the row exists with correct values.

### 16.3 Test Categories

**Capture Pipeline Tests** (real screenshots, real OCR Provenance):
```
Test: capture_and_verify_in_ocr_prov
  Input: take real screenshot of current screen
  Execute: upload to OCR Prov, process, verify
  Source of Truth: ocr_db_stats on va_screen_captures → document_count should increase by 1
  Verify: ocr_document_get on the new document_id → text should contain recognizable screen content
  Edge cases:
    - Duplicate screenshot (same pHash) → should skip, count should NOT increase
    - OCR Prov container stopped → should raise ConnectionError immediately
    - Empty/black screenshot → should still process (OCR extracts nothing, document exists with empty text)
```

**OCR Client Tests** (real HTTP calls to localhost:3366):
```
Test: create_database_and_verify
  Input: ocr_db_create(name="test_voiceagent_xyz")
  Source of Truth: ocr_db_list → should contain "test_voiceagent_xyz"
  Cleanup: ocr_db_delete(name="test_voiceagent_xyz")
  Verify: ocr_db_list → should NOT contain "test_voiceagent_xyz"
```

**LLM Tests** (real Qwen3-14B-FP8 inference):
```
Test: llm_generates_tool_call
  Input: "What databases do I have?"
  Execute: send to Qwen3-14B with tool definitions
  Source of Truth: output should contain a tool_call for ocr_db_list
  Verify: parse output, confirm tool_call structure matches schema
```

**TTS Tests** (real ClipCannon synthesis):
```
Test: tts_produces_audio
  Input: "Hello, how can I help you?"
  Execute: ClipCannon speak with voice profile "boris"
  Source of Truth: output audio file exists, duration > 0, sample rate = 24000
  Verify: check file exists on disk, check audio metadata
```

**Registry Tests** (real file I/O):
```
Test: registry_creates_missing_databases
  Input: registry.json with database "va_test_missing" that doesn't exist in OCR Prov
  Execute: registry.sync()
  Source of Truth: ocr_db_list → should now contain "va_test_missing"
  Cleanup: delete test database
```

**End-to-End Conversation Test**:
```
Test: full_conversation_turn
  Input: pre-recorded audio file of user saying "What was I working on today?"
  Execute: ASR → LLM (generates ocr_search tool call) → tool execution → LLM response → TTS
  Source of Truth:
    - turns table: should have 1 user turn + 1 agent turn
    - tool_executions table: should have 1 ocr_search execution
    - output audio: should exist and be playable
  Verify: query all three sources of truth independently
```

### 16.4 Synthetic Test Data

For predictable testing, the agent creates a known test database:

```python
# Setup: create "va_test_data" database with known content
ocr_db_create(name="va_test_data")
# Ingest a known test document (a simple text file with predictable content)
# Content: "The authentication module was refactored on March 27 2026. The new JWT handler
#           uses RS256 signing with 15-minute token expiry."
ocr_ingest_files(files=["/path/to/test_document.txt"])
ocr_process_pending()

# Now test search:
result = ocr_search(query="JWT authentication refactoring", database="va_test_data")
# Expected: result contains chunks mentioning "JWT handler", "RS256", "15-minute token expiry"
# Verify: result.chunks[0].text contains "authentication module was refactored"

# Cleanup:
ocr_db_delete(name="va_test_data")
```

---

## 17. Benchmark Targets

| Benchmark | Metric | Current SOTA | Target | Strategy |
|-----------|--------|-------------|--------|----------|
| **tau-Voice** | Pass@1 (clean) | 51% | >60% | 14B reasoning + entity confirmation |
| **VAQI** | Score (0-100) | 71.5 (Deepgram) | >70 | Barge-in <200ms, no dead air |
| **Latency** | E2E P95 | ~600ms (Retell) | <500ms | All-local GPU, no cloud |
| **WER** | Streaming | 14.5% (AssemblyAI) | <8% | Distil-Whisper + entity correction |
| **TTS Quality** | SECS | 0.881 (VALL-E 2) | 0.975 | ClipCannon (done) |
| **TTS Quality** | DNSMOS | 4.5 (Inworld) | 3.93 | ClipCannon (done, = human parity) |
| **Memory Retrieval** | Recall accuracy | N/A | >90% | OCR Prov semantic search |
| **Task Success** | TSR | ~75% (industry) | >85% | Tool reliability + confirmation |

---

## 18. Phases

### Phase 1: Core Pipeline (Weeks 1-3)
- Streaming ASR (Distil-Whisper + Silero VAD) with audio device selection
- Qwen3-14B-FP8 brain with streaming generation and tool calling
- Sentence-chunked TTS via ClipCannon adapter
- WebSocket audio transport
- Basic conversation state machine
- Conversation database (SQLite)
- Wake word detection (OpenWakeWord) OR global hotkey activation
- CLI `voiceagent talk` for local mic testing
- **Exit**: end-to-end voice conversation works, <500ms P95

### Phase 2: Memory System (Weeks 4-5)
- OCR Provenance HTTP JSON-RPC client
- Screenshot capture daemon: PowerShell interop, multi-monitor, pHash dedup
- Active window metadata collection (title, process, browser URL)
- Clipboard watcher (PowerShell Get-Clipboard polling)
- PII detection and redaction (Presidio) before storage
- Privacy blocklist (skip captures of sensitive apps)
- Auto-tagging by application type
- Agent registry (create/sync/verify databases in OCR Prov)
- Memory retrieval via LLM tool calls (ocr_search, ocr_rag_context)
- Screenshot cleanup after processing
- GPU coordination: unload LLM during OCR batch processing
- **Exit**: "What was I doing at 3pm?" returns accurate answer with app context

### Phase 3: Persistent Intelligence (Weeks 6-7)
- Cross-conversation memory (`va_user_knowledge` database)
- "Remember this" tool for durable fact storage
- Session state serialization + restoration on restart
- Conversation transcript storage in OCR Provenance (`va_conversations`)
- Full-duplex conversation manager with barge-in
- Backchannel generation and dead air prevention
- Entity extraction and confirmation
- Rolling retention cleanup cron for old captures
- **Exit**: VAQI score >70, facts persist across restarts

### Phase 4: Hardening + Benchmarks (Weeks 8-10)
- WebRTC transport
- Echo cancellation + noise suppression (RNNoise)
- Concurrent conversation support
- REST API for monitoring
- Full benchmark suite (tau-Voice, VAQI, latency, task completion)
- Text input fallback (typed queries via CLI and WebSocket)
- **Exit**: all benchmark targets met

---

## 19. Non-Goals

- Cloud deployment
- Multi-language (English only)
- Video/avatar
- Training/fine-tuning models
- Modifying ClipCannon source code
- Modifying OCR Provenance source code
- Building a SaaS platform
- Backwards compatibility with anything

---

## 20. Dependencies

| Dependency | Version | Purpose | Status |
|------------|---------|---------|--------|
| `clipcannon` | local (src/) | Voice synthesis, profiles | Exists, read-only |
| `ocr-provenance-mcp` | Docker container | Document intelligence, memory | Running at :3366 |
| `Qwen3-14B-FP8` | HF cache | LLM reasoning | Downloaded at ~/.cache/huggingface/ |
| `faster-whisper` | >=1.0 | Streaming ASR | In ClipCannon deps |
| `transformers` | >=4.40 | Model loading | In ClipCannon deps |
| `vllm` | latest | LLM serving (FP8) | New |
| `silero-vad` | >=5.0 | Voice activity detection | New |
| `openwakeword` | >=0.6.0 | Wake word detection (CPU) | New |
| `imagehash` | >=4.3 | Perceptual hashing for dedup | New |
| `Pillow` | >=10.0 | Image handling | In ClipCannon deps |
| `websockets` | >=12.0 | WebSocket transport | New |
| `fastapi` | >=0.110 | REST API | In ClipCannon deps |
| `httpx` | >=0.27 | Async HTTP client for OCR Prov | New |
| `sounddevice` | >=0.5.5 | Audio input/output, device selection | Exists (installed) |
| `presidio-analyzer` | >=2.2 | PII detection (SSN, CC, phone, etc.) | New |
| `presidio-anonymizer` | >=2.2 | PII redaction | New |
| `pynput` | >=1.7 | Global hotkey (push-to-talk fallback) | New |
| `rnnoise-python` | latest | Noise suppression | New |

---

## 21. External System Verification Checklist

Before any code runs, verify these are operational:

| System | How to Verify | Expected Result |
|--------|---------------|-----------------|
| OCR Provenance Docker | `curl http://localhost:3366/health` | `{"status":"ok"}` |
| OCR Provenance MCP | `curl -X POST http://localhost:3366/mcp -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'` | 153 tools listed |
| OCR Provenance Upload | `curl http://localhost:3366/api/upload` (GET should 405) | Method not allowed (proves endpoint exists) |
| Qwen3-14B-FP8 model | `ls ~/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/*/config.json` | File exists |
| ClipCannon voice profiles | `python -c "from clipcannon.voice.profiles import get_voice_profile; print(get_voice_profile('boris'))"` | Profile object returned |
| GPU available | `python -c "import torch; print(torch.cuda.get_device_name(0))"` | `NVIDIA GeForce RTX 5090` |
| PowerShell interop (WSL2) | `powershell.exe -NoProfile -Command "Write-Output ok"` | `ok` |
| Windows screenshot | `powershell.exe -NoProfile -Command "[System.Windows.Forms.Screen]::PrimaryScreen.Bounds"` (after Add-Type) | Resolution string |
| Audio device | `python -c "import sounddevice; print(sounddevice.query_devices())"` | Device list with at least 1 input |
| PulseAudio (WSL2 audio) | `python -c "import sounddevice; print(sounddevice.query_devices('default', 'input'))"` | Default input device info |

If ANY check fails, the system must not start. Print exactly which check failed and what the expected result was.

---

## 22. References

- [AI Voice Agent Benchmarks Report](./ai_voice_agent_benchmarks.md)
- [ClipCannon Codestate](./codestate/)
- [OCR Provenance System Overview](/home/cabdru/datalab/docs2/systemdescription/SYSTEM_OVERVIEW.md)
- [OCR Provenance MCP Tools Reference](/home/cabdru/datalab/docs2/systemdescription/MCP_TOOLS_REFERENCE.md)
- [OCR Provenance Database Schema](/home/cabdru/datalab/docs2/systemdescription/DATABASE_SCHEMA.md)
- [OCR Provenance Data Flow](/home/cabdru/datalab/docs2/systemdescription/DATA_FLOW.md)
- [ClipCannon Voice Benchmarks](../benchmarks/)
