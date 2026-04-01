# Voice Agent

Source: `src/voiceagent/`

Real-time conversational AI assistant ("Jarvis") with on-demand GPU lifecycle management. Operates independently from the ClipCannon MCP server. Not included in the ClipCannon wheel -- run via `python -m voiceagent`.

## Architecture

```
Activation Layer (CPU only)
    Wake Word ("Hey Jarvis")  or  Hotkey (Ctrl+Space)
        |
    GPU Model Loading (~10-20s)
        |
Audio Pipeline (GPU)
    Mic -> VAD (Silero) -> ASR (faster-whisper Large v3)
        -> LLM Brain (Qwen3-14B FP8)
        -> TTS (faster-qwen3-tts 0.6B, CUDA graphs)
        -> Speaker
        |
    "Go to sleep" -> GPU Model Unloading -> Dormant
```

Two pipeline implementations:
- **Pipecat** (recommended): `pipecat_agent.py` -- Uses Pipecat framework with Ollama for LLM. Handles streaming, turn-taking, barge-in natively.
- **Custom** (legacy): `agent.py` -- Direct vLLM integration with custom ASR/TTS wiring.

---

## Lifecycle States

| State | GPU Usage | Description |
|-------|-----------|-------------|
| `DORMANT` | Zero | Only wake word detector runs on CPU. No VRAM allocated. |
| `LOADING` | Growing | Models loaded sequentially: ASR -> LLM -> TTS. GC between each. ~10-20s. |
| `ACTIVE` | Full (~30GB) | All 3 models resident. Full conversation capability. |
| `UNLOADING` | Shrinking | Models released in reverse order. Aggressive VRAM cleanup. |

Transitions:
- DORMANT -> LOADING: Wake word detected or hotkey pressed
- LOADING -> ACTIVE: All models loaded, agent says "I'm here"
- ACTIVE -> UNLOADING: Dismiss phrase ("go to sleep", "goodbye", "dismiss", "shut down")
- UNLOADING -> DORMANT: All models freed, other GPU workers resumed

---

## Operation Modes

### `talk` (Pipecat + Ollama, recommended)

```bash
python -m voiceagent talk --voice boris
```

Uses Pipecat framework with local Ollama serving Qwen3-14B (GGUF). Handles streaming LLM -> TTS at sentence level, Silero VAD turn-taking, and barge-in. All local, no cloud APIs.

### `talk-legacy` (Custom Pipeline)

```bash
python -m voiceagent talk-legacy --voice boris
```

Custom pipeline with vLLM for LLM inference. Uses `LocalAudioTransport` for PyAudio mic/speaker with echo suppression (bot_speaking gate + post-speech guard window).

### `serve` (WebSocket Server)

```bash
python -m voiceagent serve --port 8765 --voice boris
```

FastAPI WebSocket server for remote clients. Loads all models immediately (no dormant state). Clients send audio chunks, receive audio responses.

---

## Components

### ASR (`asr/`)

- **StreamingASR** (`streaming.py`): Chunk-based speech recognition using `faster-whisper` (Whisper Large v3, float16, CUDA). Processes audio in configurable chunks (default 200ms).
- **VADFilter** (`vad.py`): Silero VAD wrapper with configurable speech probability threshold (default 0.5). Filters non-speech audio before sending to Whisper.
- **Endpointing** (`endpointing.py`): Detects end of user speech using configurable silence threshold (default 600ms).
- **ASREvent** (`types.py`): Typed event with `text`, `final` flag, and timing metadata.

### LLM Brain (`brain/`)

- **LLMBrain** (`llm.py`): Local LLM inference via vLLM (Qwen3-14B FP8, 45% GPU memory utilization). Streaming token generation with configurable max_tokens (default 150).
- **ContextManager** (`context.py`): Sliding window context management with token counting. Manages system prompt + conversation history within model context window (32768 tokens).
- **Prompts** (`prompts.py`): System prompt builder for Jarvis personality. Voice-profile-aware prompting (adjusts personality based on voice name).

### TTS (`tts/`, `adapters/`)

- **FastTTSAdapter** (`adapters/fast_tts.py`): Real-time TTS using `faster-qwen3-tts` 0.6B model with CUDA graph capture for 4-5x speedup. ~500ms TTFB. Full ICL mode with reference text for accurate accent/cadence cloning. Runtime voice switching between pre-loaded profiles.
- **ClipCannonAdapter** (`adapters/clipcannon.py`): Bridge to ClipCannon's full 1.7B Qwen3-TTS model for higher quality at higher latency.
- **StreamingTTS** (`tts/streaming.py`): Chunk-by-chunk synthesis using adapter pattern. Accepts either FastTTSAdapter or ClipCannonAdapter.
- **SentenceChunker** (`tts/chunker.py`): Splits LLM streaming output into sentence-sized chunks for incremental TTS synthesis.

### Activation (`activation/`)

- **WakeWordDetector** (`wake_word.py`): "Hey Jarvis" detection using openWakeWord with Silero VAD pre-filter. CPU-only, runs in dormant state.
- **HotkeyActivator** (`hotkey.py`): Ctrl+Space keyboard activation via pynput.
- **WakeListener** (`wake_listener.py`): Always-on lightweight wake word listener using Silero VAD (~1% CPU idle) + faster-whisper tiny (CPU, ~50ms per segment) + sentence embedding similarity for wake phrase matching. Launches the full Pipecat agent as a subprocess on detection, resumes listening when agent exits.

### Audio Processing (`audio/`)

- **AECFilter** (`aec_filter.py`): Two-layer acoustic echo cancellation for Pipecat: Layer 1 mic gating (silences mic during bot speech + echo tail), Layer 2 spectral suppression (attenuates frequencies matching echo reference). Designed for WSL2/PulseAudio speaker playback without headphones.
- **EchoRefProcessor** (`echo_ref_processor.py`): Pipecat processor that captures speaker output audio frames as AEC reference signal and tracks bot speaking state for mic gating.
- **VoiceCommandDetector** (`voice_command_detector.py`): Detects voice switch commands from ASR text using sentence embedding similarity (~5ms per query on CPU). Runs as Pipecat processor between STT and LLM, intercepting commands before they reach the LLM.

### Conversation (`conversation/`)

- **ConversationManager** (`manager.py`): Wires ASR -> Brain -> TTS with state transitions (IDLE -> LISTENING -> THINKING -> SPEAKING). Coordinates echo suppression with transport layer. Logs turns to database.
- **ConversationState** (`state.py`): Enum: IDLE, LISTENING, THINKING, SPEAKING.

### Transport (`transport/`)

- **LocalAudioTransport** (`local_audio.py`): PyAudio-based mic/speaker transport with echo suppression. Bot_speaking gate drops mic audio while agent speaks. Post-speech guard window prevents echo feedback.
- **WebSocketTransport** (`websocket.py`): FastAPI WebSocket endpoint for remote voice agent clients. Binary audio frames + JSON control messages.

### GPU Management (`gpu_manager.py`)

- `pause_gpu_workers()`: Sends SIGSTOP to other GPU processes to free VRAM.
- `resume_gpu_workers(pids)`: Sends SIGCONT to restore paused processes.
- `force_free_gpu_memory()`: Clears CUDA cache and IPC.
- VRAM fraction capped at 93% to prevent OOM thrashing.

---

## Database

Stored at `~/.voiceagent/agent.db` (separate from ClipCannon). Three tables:

| Table | Purpose |
|-------|---------|
| `conversations` | Conversation sessions with voice profile and turn count |
| `turns` | Individual turns with role, text, and latency metrics (asr_ms, llm_ttft_ms, tts_ttfb_ms, total_ms) |
| `metrics` | General performance metrics with timestamps |

See [04_database_schema.md](04_database_schema.md) section 10 for full column definitions.

---

## Configuration

Stored at `~/.voiceagent/config.json`. All values have sensible defaults -- the file is optional. See [03_configuration.md](03_configuration.md) Voice Agent Configuration section for full reference.

---

## VRAM Budget

Target: RTX 5090 32GB

| Component | Model | VRAM |
|-----------|-------|------|
| ASR | Whisper Large v3 float32 | ~6 GB |
| LLM | Qwen3-14B FP8 (vLLM) | ~15 GB |
| TTS | faster-qwen3-tts 0.6B | ~4 GB |
| Overhead | KV caches + activations | ~5 GB |
| **Total** | | **~30 GB** |

Models loaded sequentially with `gc.collect()` + `torch.cuda.empty_cache()` between each to prevent VRAM fragmentation. 2GB headroom reserved.

---

## Dismiss Phrases

The following phrases trigger deactivation (intercepted before LLM processing):

`"go to sleep"`, `"goodbye"`, `"dismiss"`, `"shut down"`

---

## Pipecat Pipeline (`pipecat_agent.py`)

All-local pipeline, no cloud APIs:

| Component | Implementation |
|-----------|----------------|
| ASR | faster-whisper (Whisper Large v3, float16, CUDA) |
| LLM | Ollama serving Qwen3-14B locally (GGUF, ~120 tok/s) |
| TTS | faster-qwen3-tts (0.6B, CUDA graphs) |
| VAD | Silero VAD |
| Transport | PyAudio local mic/speaker |

Pipecat handles streaming LLM -> TTS at sentence level, turn-taking via Silero VAD, and barge-in (interrupt agent mid-sentence). WSL2 PulseAudio TCP bridge is auto-detected and configured.

---

## Relationship to ClipCannon

The voice agent uses ClipCannon's voice profiles (`~/.clipcannon/voice_profiles.db`) for voice cloning but is otherwise independent:

- **Separate package**: `src/voiceagent/` vs `src/clipcannon/`
- **Separate database**: `~/.voiceagent/agent.db` vs `~/.clipcannon/projects/*/analysis.db`
- **Separate config**: `~/.voiceagent/config.json` vs `~/.clipcannon/config.json`
- **Not in wheel**: `voiceagent` is not in pyproject.toml `[tool.hatch.build.targets.wheel]`
- **Different TTS model**: Voice agent uses 0.6B (fast, ~500ms TTFB) vs ClipCannon's 1.7B (high quality for video)
- **GPU sharing**: Voice agent pauses ClipCannon GPU workers during activation, resumes on deactivation
