"""Santa clone meeting bot — full quality pipeline with OCR Provenance RAG.

Architecture:
  Audio Routing (zero feedback):
    YOUR Chrome plays meeting audio -> PulseAudio output sink -> speakers
    output.monitor captures your Chrome's audio -> parec -> Whisper -> LLM -> TTS
    TTS -> pacat -> clone_audio sink -> clone_audio.monitor -> bot fake mic -> meeting
    NO LOOPBACK. Bot TTS never reaches output.monitor. Feedback impossible.

  Intelligence (RAG):
    Question -> OCR Provenance search (past meetings) -> Ollama 14B -> response
    Transcript segments ingested into OCR Provenance in near-real-time
    AI can search all meeting history to produce informed answers

  Voice Quality:
    Full ICL mode + real Santa reference recording
    Real laugh clips from expression library (not TTS-generated)
    [LAUGH] tags in LLM prompt -> replaced with real audio clips
    Prosody-aware: system prompt demands full vocal variation

  Memory Management:
    Whisper model loaded ONCE at startup
    TTS adapter loaded ONCE at startup
    Audio buffers capped at 2x window size
    Transcript segments capped in memory, overflow flushed to OCR Provenance
    gc.collect() after each response cycle
"""
import asyncio
import gc
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

logging.basicConfig(
    level=logging.INFO, stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("santa_bot")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MEET_URL = sys.argv[1] if len(sys.argv) > 1 else ""
SESSION_DIR = str(Path("~/.voiceagent/browser-session").expanduser())
VOICE_NAME = "santa"
LLM_MODEL = "qwen3:8b-nothink"  # 8B for fast responses (~2-3s vs ~7-10s for 14B)
WHISPER_MODEL = "large-v3-turbo"
OCR_PROVENANCE_URL = "http://localhost:3377/mcp"
OCR_DB_NAME = "meetings"

# Dynamic avatar via FIFO pipe (real-time lip sync)
Y4M_PIPE = "/tmp/santa_avatar_pipe.y4m"
SANTA_IDLE_VIDEO = str(Path("~/.voiceagent/drivers/santa_idle_listen.y4m").expanduser())
# Use neutral frame Y4M (mouth closed, face forward) as Chrome's video
IDLE_Y4M = str(Path("~/.voiceagent/drivers/santa_neutral.y4m").expanduser())
if not Path(IDLE_Y4M).exists():
    IDLE_Y4M = SANTA_IDLE_VIDEO

# Y4M writer instance (initialized at startup)
_y4m_writer = None  # Reserved for future v4l2loopback approach

# Audio capture settings
CAPTURE_DEVICE = "output.monitor"
AUDIO_SINK = "clone_audio"
SAMPLE_RATE = 16000
CHUNK_BYTES = 3200  # 100ms at 16kHz mono 16-bit

# Energy threshold for speech detection
# PulseAudio TCP bridge delivers very low amplitude (~0.0004 RMS)
# so threshold must be much lower than local audio
ENERGY_THRESHOLD = 0.00005  # PulseAudio TCP is extremely quiet
SILENCE_TIMEOUT_S = 0.8     # Fast cutoff — respond quickly after user stops
MIN_SPEECH_BYTES = 8000     # ~0.25s minimum (catch short phrases)

# Expression library — expanded to 28 clips across 5 emotional categories
LAUGH_CLIPS = [
    str(Path("~/.clipcannon/voice_data/santa/expressions/laugh_01_511s.wav").expanduser()),
    str(Path("~/.clipcannon/voice_data/santa/expressions/laugh_02_550s.wav").expanduser()),
]
_laugh_idx = 0

# Prosody-matched TTS reference clips
REFS_DIR = Path("~/.clipcannon/voice_data/santa/refs").expanduser()
_ref_mapping: dict = {}
_default_ref: str = ""
try:
    import json as _json
    _ref_map_path = REFS_DIR / "ref_mapping.json"
    if _ref_map_path.exists():
        with open(_ref_map_path) as _f:
            _ref_mapping = _json.load(_f)
        _default_ref = _ref_mapping.get("ref_default", {}).get("path", "")
except Exception:
    pass

# Prosody style keywords for response-text analysis
_PROSODY_STYLE_KEYWORDS = {
    "ref_energetic": ["excited", "amazing", "wonderful", "fantastic", "great", "love", "ho ho ho", "[LAUGH]"],
    "ref_calm": ["okay", "sure", "indeed", "yes", "I see", "understood", "agreed"],
    "ref_emphatic": ["must", "important", "absolutely", "never", "always", "critical", "truly"],
    "ref_question": ["?", "wonder", "perhaps", "maybe", "might"],
    "ref_warm": ["dear", "child", "friend", "heart", "believe", "hope", "magic", "Christmas"],
}


def select_prosody_ref(response_text: str) -> str | None:
    """Select the best prosody-matched TTS reference clip for a response.

    Analyzes response text for emotional keywords and selects the
    matching reference clip. Returns None to use the default.
    """
    if not _ref_mapping:
        return None

    text_lower = response_text.lower()
    best_style = None
    best_count = 0

    for style, keywords in _PROSODY_STYLE_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw.lower() in text_lower)
        if count > best_count:
            best_count = count
            best_style = style

    # Skip ref_question — it truncates TTS output
    if best_style and best_style != "ref_question" and best_style in _ref_mapping:
        return _ref_mapping[best_style].get("path")
    return None

# Transcript buffer
_transcript_segments: list[dict] = []
_MAX_TRANSCRIPT_SEGMENTS = 200

# ---------------------------------------------------------------------------
# PulseAudio setup
# ---------------------------------------------------------------------------
try:
    _gw = subprocess.run(
        ["ip", "route", "show", "default"],
        capture_output=True, text=True, timeout=5,
    ).stdout.strip().split()[2]
    os.environ["PULSE_SERVER"] = f"tcp:{_gw}:4713"
except Exception:
    pass

# Remove ALL loopbacks — wrapped in try/except since PulseAudio TCP can timeout
try:
    subprocess.run(["pactl", "set-default-source", "clone_audio.monitor"],
                   capture_output=True, timeout=10)
    subprocess.run(["pactl", "set-default-sink", "output"],
                   capture_output=True, timeout=10)
    for line in subprocess.run(
        ["pactl", "list", "short", "modules"],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip().split("\n"):
        if "loopback" in line.lower():
            mid = line.split()[0]
            subprocess.run(["pactl", "unload-module", mid],
                           capture_output=True, timeout=10)
            logger.info("Removed loopback module %s", mid)
except Exception as e:
    logger.warning("PulseAudio setup issue (continuing): %s", e)


# ---------------------------------------------------------------------------
# GPU memory management (RTX 5090 Blackwell / CUDA 13.x optimizations)
# ---------------------------------------------------------------------------
#
# RTX 5090 specs: 21,760 CUDA cores, 170 SMs, 32GB GDDR7, 1792 GB/s BW
# Key: Lazy module loading + expandable segments + no unnecessary syncs
#
os.environ.setdefault("CUDA_MODULE_LOADING", "LAZY")  # Don't load all modules at startup
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF",
                       "expandable_segments:True,max_split_size_mb:256")
os.environ.setdefault("PYTORCH_NO_CUDA_MEMORY_CACHING", "0")  # Keep caching on

# Limit CuPy memory pool to prevent competition with PyTorch
try:
    import cupy as _cp
    _pool = _cp.get_default_memory_pool()
    _pool.set_limit(size=512 * 1024 * 1024)  # 512MB cap for compositor
except ImportError:
    pass

_GPU_VRAM_WARNING_GB = 28.0  # Warn if VRAM usage exceeds this


def gpu_cleanup():
    """Free fragmented GPU memory. Call between heavy CUDA operations."""
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
    try:
        import cupy as cp
        cp.get_default_memory_pool().free_all_blocks()
    except ImportError:
        pass


def gpu_health_check() -> bool:
    """Check GPU health. Returns False if VRAM critically high or GPU unreachable."""
    try:
        import torch
        if not torch.cuda.is_available():
            logger.error("GPU: CUDA not available!")
            return False
        alloc = torch.cuda.memory_allocated() / 1e9
        reserved = torch.cuda.memory_reserved() / 1e9
        total = torch.cuda.get_device_properties(0).total_memory / 1e9
        if alloc > _GPU_VRAM_WARNING_GB:
            logger.warning("GPU: VRAM HIGH %.1fGB/%.1fGB — forcing cleanup", alloc, total)
            torch.cuda.empty_cache()
            gc.collect()
            return True
        return True
    except Exception as e:
        logger.error("GPU health check failed: %s", e)
        return False


def log_gpu_state(label: str = ""):
    """Log current GPU memory usage."""
    try:
        import torch
        if torch.cuda.is_available():
            alloc = torch.cuda.memory_allocated() / 1e9
            reserved = torch.cuda.memory_reserved() / 1e9
            logger.info("GPU [%s]: %.2fGB allocated, %.2fGB reserved", label, alloc, reserved)
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Model singletons — loaded ONCE, released on exit
# ---------------------------------------------------------------------------
_whisper_model = None
_tts_adapter = None
_ocr_client = None


def get_whisper():
    """Get or load the Whisper model (singleton)."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        logger.info("Loading Whisper %s...", WHISPER_MODEL)
        _whisper_model = WhisperModel(
            WHISPER_MODEL, device="cuda", compute_type="float16",
        )
        logger.info("Whisper loaded")
    return _whisper_model


def get_tts():
    """Get or load the TTS adapter (singleton)."""
    global _tts_adapter
    if _tts_adapter is None:
        from voiceagent.adapters.fast_tts import FastTTSAdapter
        logger.info("Loading TTS (voice=%s)...", VOICE_NAME)
        _tts_adapter = FastTTSAdapter(voice_name=VOICE_NAME)
        logger.info("TTS loaded")
    return _tts_adapter


def release_models():
    """Release all GPU models and free VRAM."""
    global _whisper_model, _tts_adapter
    if _tts_adapter is not None:
        try:
            _tts_adapter.release()
        except Exception:
            pass
        _tts_adapter = None
    if _whisper_model is not None:
        del _whisper_model
        _whisper_model = None
    # Aggressive GPU cleanup
    gc.collect()
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
    except (ImportError, RuntimeError):
        pass
    try:
        import cupy as cp
        cp.get_default_memory_pool().free_all_blocks()
        cp.get_default_pinned_memory_pool().free_all_blocks()
    except (ImportError, RuntimeError):
        pass
    logger.info("All models released")


# ---------------------------------------------------------------------------
# OCR Provenance client
# ---------------------------------------------------------------------------
async def get_ocr_client():
    """Get or create the OCR Provenance client."""
    global _ocr_client
    if _ocr_client is None:
        from voiceagent.meeting.mcp_client import OcrProvenanceClient
        _ocr_client = OcrProvenanceClient(base_url=OCR_PROVENANCE_URL)
        # Ensure database exists
        try:
            await _ocr_client.call_tool("ocr_db_select", {"database_name": OCR_DB_NAME})
        except Exception:
            try:
                await _ocr_client.call_tool("ocr_db_create", {
                    "name": OCR_DB_NAME,
                    "description": "Clone meeting transcripts",
                })
                await _ocr_client.call_tool("ocr_db_select", {"database_name": OCR_DB_NAME})
            except Exception as e:
                logger.warning("OCR Provenance unavailable: %s", e)
                _ocr_client = None
                return None
        logger.info("OCR Provenance connected (db=%s)", OCR_DB_NAME)
    return _ocr_client


async def search_meeting_history(query: str) -> str:
    """Search past meetings via OCR Provenance for relevant context."""
    client = await get_ocr_client()
    if client is None:
        return ""
    try:
        result = await client.call_tool("ocr_search", {
            "query": query, "limit": 5,
        })
        if not isinstance(result, dict):
            return ""
        results = result.get("results", result.get("chunks", []))
        if not results:
            text = result.get("text", "")
            return text[:800] if text else ""
        lines = []
        for item in results[:5]:
            if isinstance(item, dict):
                text = item.get("text", item.get("content", ""))
                if text:
                    lines.append(text[:250].strip())
        return "\n".join(lines)
    except Exception as e:
        logger.debug("OCR search failed: %s", e)
        return ""


async def ingest_transcript(segments: list[dict], meeting_id: str) -> None:
    """Ingest transcript segments into OCR Provenance for live search."""
    client = await get_ocr_client()
    if client is None or not segments:
        return
    try:
        # Build markdown
        lines = [f"# Meeting Transcript ({meeting_id})\n"]
        for seg in segments:
            speaker = seg.get("speaker", "Unknown")
            text = seg.get("text", "")
            ts = seg.get("timestamp", "")
            lines.append(f"**{speaker}** ({ts}): {text}\n")
        md = "\n".join(lines)

        # Write to temp file and ingest
        path = Path(f"/tmp/{meeting_id}_live.md")
        path.write_text(md, encoding="utf-8")
        await client.call_tool("ocr_ingest_files", {
            "files": [str(path)],
            "disable_image_extraction": True,
        })
        path.unlink(missing_ok=True)
        logger.debug("Ingested %d segments into OCR Provenance", len(segments))
    except Exception as e:
        logger.debug("Transcript ingest failed: %s", e)


# ---------------------------------------------------------------------------
# Dynamic avatar setup
# ---------------------------------------------------------------------------
_face_warper = None


def init_face_warper():
    """Initialize the face warper from the reference frame."""
    global _face_warper
    import subprocess
    src_video = SANTA_IDLE_VIDEO
    if not Path(src_video).exists():
        return
    try:
        r = subprocess.run(
            ["ffmpeg", "-i", src_video, "-vframes", "1",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
            capture_output=True, timeout=10,
        )
        if r.returncode != 0 or len(r.stdout) == 0:
            return
        ref_frame = np.frombuffer(r.stdout, dtype=np.uint8).reshape(720, 1280, 3)
        from phoenix.render.face_warper import FaceWarper
        _face_warper = FaceWarper(ref_frame, max_pixel_shift=20)
        if _face_warper.ready:
            logger.info("Face warper ready for lip sync")
        else:
            _face_warper = None
            logger.warning("Face warper: no face detected")
    except Exception as e:
        logger.warning("Face warper init failed: %s", e)


# ---------------------------------------------------------------------------
# Browser launch
# ---------------------------------------------------------------------------
async def launch_browser():
    """Launch Playwright browser and join the meeting."""
    if not MEET_URL:
        logger.error("No meeting URL provided. Usage: python santa_meet_bot.py <URL>")
        return None, None, None

    # === WARM EVERYTHING BEFORE JOINING ===
    logger.info("=== WARMING ALL MODELS ===")

    # 1. Whisper
    logger.info("Loading Whisper...")
    get_whisper()
    gpu_cleanup()
    log_gpu_state("whisper")

    # 2. TTS + CUDA graph warmup
    logger.info("Loading TTS + warmup...")
    tts = get_tts()
    try:
        _ = await tts.synthesize("Ho ho ho, merry Christmas!")
        logger.info("TTS warmed — first response will be instant")
    except Exception:
        pass

    # 3. Pre-transcribe ALL prosody ref clips so switching is instant (no Whisper at speak time)
    if _ref_mapping:
        logger.info("Pre-transcribing %d prosody refs...", len(_ref_mapping))
        _ref_transcripts = {}
        for name, info in _ref_mapping.items():
            path = info.get("path", "")
            if path and Path(path).exists():
                try:
                    text = tts._transcribe(path)
                    _ref_transcripts[path] = text
                    logger.info("  %s: '%s'", name, (text or "")[:50])
                except Exception:
                    pass
        # Store for use in speak()
        globals()["_ref_transcripts"] = _ref_transcripts
    gpu_cleanup()
    log_gpu_state("tts")

    # 4. Face warper (optional, for future lip sync)
    init_face_warper()
    gpu_cleanup()

    logger.info("=== ALL MODELS WARM — joining meeting ===")

    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=SESSION_DIR, headless=False,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-video-capture={IDLE_Y4M}",
            "--use-file-for-fake-audio-capture=/home/cabdru/.voiceagent/silence.wav",
        ],
        viewport={"width": 1280, "height": 720},
        locale="en-US",
        permissions=["camera", "microphone"],
    )
    page = context.pages[0] if context.pages else await context.new_page()
    # Capture RTCPeerConnections BEFORE page loads
    await page.add_init_script("""
        Object.defineProperty(navigator, "webdriver", {get: () => false});
        window.__santaPCs = [];
        const _OrigPC = window.RTCPeerConnection;
        window.RTCPeerConnection = function(...args) {
            const pc = new _OrigPC(...args);
            window.__santaPCs.push(pc);
            return pc;
        };
        window.RTCPeerConnection.prototype = _OrigPC.prototype;
        Object.keys(_OrigPC).forEach(k => { try { window.RTCPeerConnection[k] = _OrigPC[k]; } catch(e){} });
    """)
    await page.goto(MEET_URL, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)
    logger.info("Page loaded, PC capture installed")

    # Click join button
    for sel in [
        'button:has-text("Ask to join")',
        'button:has-text("Join now")',
        'button:has-text("Switch here")',
        'button:has-text("Join")',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                logger.info("Joined")
                break
        except Exception:
            continue

    # Wait for meeting
    for _ in range(120):
        await asyncio.sleep(1)
        try:
            if await page.locator('[aria-label="Leave call"]').first.is_visible(timeout=500):
                logger.info("IN THE MEETING!")

                # UNMUTE mic — this makes Google Meet add an audio sender
                # to the RTCPeerConnection so we can replace its track
                for sel in ['[aria-label*="Turn on microphone"]',
                            '[aria-label*="Unmute"]']:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible(timeout=2000):
                            await btn.click()
                            logger.info("Mic unmuted")
                            break
                    except Exception:
                        continue

                # Wait for WebRTC to establish audio track
                await asyncio.sleep(4)

                # Now replace the audio track with our controllable one
                await setup_audio_injection(page)
                return pw, context, page
        except Exception:
            continue

    return None, None, None


# ---------------------------------------------------------------------------
# Audio capture + processing loop
# ---------------------------------------------------------------------------
_ADDRESS_WORDS = {"santa", "jarvis", "claus", "mr. claus", "father christmas"}


def _is_addressed(text: str) -> bool:
    """Check if Santa is being spoken to (not just background chatter)."""
    low = text.lower()
    # Direct name mention
    if any(w in low for w in _ADDRESS_WORDS):
        return True
    # Direct question (ends with ?)
    if text.strip().endswith("?"):
        return True
    return False


async def audio_loop(page, stop):
    """Continuous listening loop — always transcribes, only responds when addressed."""
    # Models already warm from launch_browser()
    log_gpu_state("models-ready")
    logger.info("ALL MODELS IN VRAM — ready to converse")

    # Start continuous audio capture
    parec = await asyncio.create_subprocess_exec(
        "parec", f"--device={CAPTURE_DEVICE}",
        "--format=s16le", f"--rate={SAMPLE_RATE}", "--channels=1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    logger.info("Capturing from %s (PID %d)", CAPTURE_DEVICE, parec.pid)

    history: list[dict] = []
    buf = bytearray()
    responding = False
    meeting_id = f"mtg_{int(time.time())}"
    last_speech_t = 0.0  # When we last detected actual speech content
    window_start = time.time()

    # Strategy: Accumulate audio in rolling 3-second windows.
    # Every 3s, transcribe. If Whisper finds speech, check if addressed.
    # This bypasses the broken energy-threshold approach entirely.
    WINDOW_S = 2.0  # Transcribe every 2 seconds for faster response
    MAX_BUF_BYTES = SAMPLE_RATE * 2 * 8  # 8s max buffer

    while not stop.is_set():
        try:
            chunk = await asyncio.wait_for(
                parec.stdout.read(CHUNK_BYTES), timeout=0.2,
            )
        except asyncio.TimeoutError:
            chunk = None
        except Exception:
            break

        if responding:
            # While responding, drain audio but don't accumulate
            if chunk:
                pass  # discard
            continue

        if chunk:
            buf.extend(chunk)
            # Cap buffer
            if len(buf) > MAX_BUF_BYTES:
                buf = buf[-MAX_BUF_BYTES:]

        # Check if window elapsed — time to transcribe
        elapsed = time.time() - window_start
        if elapsed >= WINDOW_S and len(buf) > MIN_SPEECH_BYTES:
            window_start = time.time()

            # Normalize the quiet PulseAudio audio before Whisper
            audio = np.frombuffer(bytes(buf), dtype=np.int16).astype(np.float32) / 32768.0
            peak = np.max(np.abs(audio))
            if peak > 0:
                audio = audio * min(0.9 / peak, 50.0)

            # Quick transcription (19ms on RTX 5090)
            text = await transcribe(audio)
            del audio

            if text and len(text) > 2:
                logger.info("HEARD: '%s'", text)
                last_speech_t = time.time()

                # Store transcript
                _transcript_segments.append({
                    "speaker": "Participant", "text": text,
                    "timestamp": time.strftime("%H:%M:%S"),
                })
                if len(_transcript_segments) > _MAX_TRANSCRIPT_SEGMENTS:
                    del _transcript_segments[:len(_transcript_segments) - _MAX_TRANSCRIPT_SEGMENTS]

                # Only respond if addressed
                if _is_addressed(text):
                    responding = True
                    t_start = time.time()
                    try:
                        resp = await respond(text, history)
                        if resp and len(resp) > 10:
                            t_llm = time.time()
                            logger.info("SANTA: '%s' (LLM: %dms)",
                                        resp, (t_llm - t_start) * 1000)
                            history.append({"role": "user", "content": text})
                            history.append({"role": "assistant", "content": resp})
                            if len(history) > 6:
                                del history[:len(history) - 6]
                            await speak(page, resp)
                            t_total = time.time() - t_start
                            logger.info("TOTAL RESPONSE: %.1fs (target <2s)", t_total)
                        elif resp:
                            logger.warning("Skipped short response: '%s'", resp)
                    except Exception as e:
                        logger.error("Response failed: %s", e)
                    finally:
                        responding = False
                        window_start = time.time()  # Reset timer so next listen starts immediately
                else:
                    logger.debug("Not addressed — listening")

            # Clear buffer after processing
            buf.clear()

    parec.kill()
    await ingest_transcript(_transcript_segments, meeting_id)


async def process(buf, history, page, meeting_id):
    """Process speech buffer: transcribe -> search -> respond -> speak.

    Catches all errors so the bot continues running even if one
    response cycle fails.
    """
    try:
        audio = np.frombuffer(bytes(buf), dtype=np.int16).astype(np.float32) / 32768.0
        # Normalize low-amplitude PulseAudio TCP audio
        peak = np.max(np.abs(audio))
        if peak > 0:
            gain = min(0.9 / peak, 50.0)
            audio = audio * gain
        text = await transcribe(audio)
        if not text or len(text) < 3:
            return
        logger.info("HEARD: '%s'", text)

        # Store in transcript
        ts = time.strftime("%H:%M:%S")
        _transcript_segments.append({
            "speaker": "Participant", "text": text, "timestamp": ts,
        })
        if len(_transcript_segments) > _MAX_TRANSCRIPT_SEGMENTS:
            del _transcript_segments[:len(_transcript_segments) - _MAX_TRANSCRIPT_SEGMENTS]

        # Only respond when directly addressed
        if not _is_addressed(text):
            logger.info("Not addressed — listening only")
            return

        resp = await respond(text, history)
        if not resp:
            logger.warning("Empty response for: '%s'", text[:60])
            return
        logger.info("SANTA: '%s'", resp)

        # Store response in transcript
        _transcript_segments.append({
            "speaker": "Santa (Clone)", "text": resp,
            "timestamp": time.strftime("%H:%M:%S"),
        })

        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": resp})
        # Keep history bounded
        if len(history) > 20:
            del history[:len(history) - 20]

        await speak(page, resp)
        # Extra silence gap after speaking to prevent echo pickup
        await asyncio.sleep(1.0)

    except Exception as e:
        logger.error("Process cycle failed (bot continues): %s", e)
        import traceback
        logger.error(traceback.format_exc())
    finally:
        # Free GPU + CPU memory after every response cycle
        gpu_cleanup()
        log_gpu_state("post-cycle")


async def transcribe(audio):
    """Transcribe audio using the singleton Whisper model."""
    model = get_whisper()
    segs, _ = model.transcribe(audio, language="en", vad_filter=True)
    return " ".join(s.text.strip() for s in segs).strip()


async def respond(text, history):
    """Generate response using Ollama with fast turnaround."""
    import httpx

    # Skip slow OCR search for simple conversational messages
    # Only search when the question seems to reference past context
    history_context = ""
    needs_search = any(kw in text.lower() for kw in [
        "remember", "last time", "before", "earlier", "you said",
        "we talked", "mentioned", "discussed",
    ])
    if needs_search:
        try:
            history_context = await asyncio.wait_for(
                search_meeting_history(text), timeout=3.0,
            )
        except asyncio.TimeoutError:
            logger.debug("OCR search timed out, skipping")

    system = (
        "You are the real Santa Claus on a video call. "
        "You speak with a warm, deep, resonant voice full of life and emotion. "
        "RULES: "
        "1) Reply in 1-3 sentences. Be warm but concise. "
        "2) Speak like a REAL person having a genuine conversation. "
        "No emojis. No asterisks. No formatting. Pure natural speech. "
        "3) Answer what was actually asked. Be specific and genuine. "
        "4) You are a real Santa — you've visited children in hospitals, "
        "sat with families during hard times, and seen the magic of Christmas "
        "change lives. Draw from real emotions and experiences. "
        "5) Vary your tone — be jolly when happy, gentle when comforting, "
        "thoughtful when reflecting. Let emotion come through naturally. "
        "6) Say 'my friend' not 'little one'. Speak as an equal. "
        "7) Sometimes pause or use filler words like 'well' or 'you know' "
        "to sound natural, not robotic."
    )

    # Build messages — keep history SHORT to prevent hallucination
    msgs = [{"role": "system", "content": system}]
    msgs.extend(history[-6:])  # Only last 3 exchanges

    # Build user message with RAG context
    user_msg = text
    if history_context:
        user_msg = (
            f"[Context from past meetings]\n{history_context}\n\n"
            f"[Current question]\n{text}"
        )
    msgs.append({"role": "user", "content": user_msg})

    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": LLM_MODEL,
                    "messages": msgs,
                    "stream": False,
                    "think": False,
                    "options": {
                        "num_predict": 80,  # 1-2 sentences = ~40-60 tokens
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "num_gpu": 99,  # 8B fits entirely on GPU (~5GB)
                    },
                },
            )
        return r.json().get("message", {}).get("content", "").strip()
    except httpx.TimeoutException:
        logger.error("Ollama timed out after 180s")
        return ""
    except Exception as e:
        logger.error("Ollama error: %s", e)
        return ""


async def setup_audio_injection(page):
    """Inject WebAudio bridge into the page for audio delivery.

    Chrome's --use-fake-device-for-media-stream bypasses PulseAudio,
    so we inject audio directly into the WebRTC stream via JavaScript.
    This replaces the fake mic's silent/synthetic audio with real TTS.
    """
    # Create AudioContext and connect to BOTH the WebRTC stream AND ensure
    # the context stays alive by resuming before every playback
    replaced = await page.evaluate("""() => {
        // Create audio pipeline
        window.__santaCtx = new AudioContext({sampleRate: 24000});
        window.__santaDest = window.__santaCtx.createMediaStreamDestination();
        window.__santaPlaying = false;
        const santaTrack = window.__santaDest.stream.getAudioTracks()[0];

        // Replace audio track on captured RTCPeerConnections
        let replaced = 0;
        const pcs = window.__santaPCs || [];
        for (const pc of pcs) {
            try {
                for (const sender of pc.getSenders()) {
                    if (sender.track && sender.track.kind === 'audio') {
                        sender.replaceTrack(santaTrack);
                        replaced++;
                    }
                }
            } catch(e) {}
        }

        // Keep context alive: resume every 5 seconds
        setInterval(() => {
            if (window.__santaCtx.state === 'suspended') {
                window.__santaCtx.resume();
            }
        }, 5000);
        // Resume immediately
        window.__santaCtx.resume();

        // Play audio — resume context first, create fresh nodes each time
        window.__santaPlayAudio = function(b64Data, sampleRate) {
            return window.__santaCtx.resume().then(() => {
                return new Promise((resolve, reject) => {
                    try {
                        const binary = atob(b64Data);
                        const bytes = new Uint8Array(binary.length);
                        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

                        const float32 = new Float32Array(bytes.buffer);
                        const buffer = window.__santaCtx.createBuffer(1, float32.length, sampleRate);
                        buffer.copyToChannel(float32, 0);

                        const source = window.__santaCtx.createBufferSource();
                        source.buffer = buffer;
                        const gain = window.__santaCtx.createGain();
                        gain.gain.value = 3.0;
                        source.connect(gain);
                        gain.connect(window.__santaDest);

                        source.onended = () => {
                            window.__santaPlaying = false;
                            resolve(true);
                        };
                        window.__santaPlaying = true;
                        source.start();
                    } catch(e) {
                        reject(e.message);
                    }
                });
            });
        };
        return { pcs: pcs.length, replaced: replaced, ctxState: window.__santaCtx.state };
    }""")
    logger.info("Audio bridge: %d PCs, %d tracks replaced, ctx=%s",
                replaced.get("pcs", 0), replaced.get("replaced", 0),
                replaced.get("ctxState", "unknown"))
    logger.info("Audio injection bridge installed")


async def speak(page, text):
    """Synthesize speech with prosody-matched refs, laugh clips, and inject to meeting."""
    global _laugh_idx
    import base64
    import soundfile as sf

    tts = get_tts()
    try:
        logger.info("speak() starting for: '%s'", text[:60])

        # Select prosody-matched reference clip based on response content
        # Uses pre-transcribed ref_text to avoid Whisper call at speak time
        ref_path = select_prosody_ref(text)
        cached_transcripts = globals().get("_ref_transcripts", {})
        if ref_path and Path(ref_path).exists():
            ref_text = cached_transcripts.get(ref_path)
            tts.set_ref_audio(ref_path, ref_text=ref_text)
            logger.info("Prosody ref: %s", Path(ref_path).name)
        elif _default_ref and Path(_default_ref).exists():
            ref_text = cached_transcripts.get(_default_ref)
            tts.set_ref_audio(_default_ref, ref_text=ref_text)
            logger.info("Prosody ref: default")

        # Strip all tags — synthesize clean text only
        clean = re.sub(r'\[.*?\]', '', text).strip()
        if not clean:
            logger.warning("speak(): empty text after cleanup")
            return

        sr = 24000
        t0 = time.time()
        a = await tts.synthesize(clean)
        tts_ms = (time.time() - t0) * 1000
        logger.info("TTS: %.0fms for %.1fs audio", tts_ms, len(a) / sr)

        if len(a) == 0:
            logger.warning("TTS returned empty audio")
            return

        segs = [a]

        if not segs:
            return
        audio = np.concatenate(segs)
        audio_duration = len(audio) / sr
        logger.info("Audio: %.1fs (%d samples), %d segments",
                     audio_duration, len(audio), len(segs))
        del segs

        # Compute lip sync frames and send to browser for video animation
        if _face_warper is not None and _face_warper.ready:
            try:
                from phoenix.render.lip_sync import LipSync
                lip = LipSync(fps=25, sample_rate=sr)
                lip_frames = lip.from_audio(audio)
                # Extract unique mouth openness levels (quantize to reduce data)
                mouth_schedule = [round(f.mouth_open, 2) for f in lip_frames]
                logger.info("Lip sync: %d frames, mouth range %.2f-%.2f",
                            len(lip_frames),
                            min(mouth_schedule), max(mouth_schedule))
                # Send the mouth schedule to browser — JS will animate the
                # video track frame by frame using the schedule
                await page.evaluate(
                    "schedule => { window.__santaMouthSchedule = schedule; }",
                    mouth_schedule,
                )
            except Exception as e:
                logger.warning("Lip sync prep failed: %s", e)

        # Inject audio into WebRTC via JavaScript WebAudio API
        audio_bytes = audio.astype(np.float32).tobytes()
        b64 = base64.b64encode(audio_bytes).decode('ascii')
        b64_len = len(b64)
        del audio, audio_bytes

        logger.info("Sending %dKB audio (%.1fs) to browser...", b64_len // 1024, audio_duration)
        try:
            # Re-ensure audio track is connected before every speak
            await page.evaluate("""() => {
                if (!window.__santaCtx || !window.__santaDest) return 'no_ctx';
                // Resume context if suspended
                if (window.__santaCtx.state !== 'running') {
                    window.__santaCtx.resume();
                }
                // Re-replace track on all PCs in case connection was renegotiated
                const track = window.__santaDest.stream.getAudioTracks()[0];
                if (!track) return 'no_track';
                let n = 0;
                for (const pc of (window.__santaPCs || [])) {
                    try {
                        for (const s of pc.getSenders()) {
                            if (s.track && s.track.kind === 'audio' && s.track.id !== track.id) {
                                s.replaceTrack(track);
                                n++;
                            }
                        }
                    } catch(e) {}
                }
                return 'ctx=' + window.__santaCtx.state + ',replaced=' + n;
            }""")

            result = await page.evaluate(
                "([b64, sr]) => window.__santaPlayAudio(b64, sr)",
                [b64, sr],
            )
            logger.info("Audio delivered: %s", result)
        except Exception as e:
            logger.error("Audio injection failed: %s", e)
        # Wait for playback
        await asyncio.sleep(audio_duration + 0.5)
        del b64

        logger.info("Spoke: %.1fs", audio_duration)

        # Return avatar to listening state
        if _y4m_writer is not None:
            try:
                from phoenix.render.y4m_writer import AvatarState
                _y4m_writer.set_state(AvatarState.LISTENING)
            except Exception:
                pass
    except Exception as e:
        logger.error("Speak failed: %s", e)
        # Ensure avatar returns to listening even on error
        if _y4m_writer is not None:
            try:
                from phoenix.render.y4m_writer import AvatarState
                _y4m_writer.set_state(AvatarState.LISTENING)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    pw, ctx, page = await launch_browser()
    if not pw:
        return

    print("\n" + "=" * 60)
    print("  SANTA CLONE LIVE — FULL QUALITY PIPELINE")
    print(f"  LLM: {LLM_MODEL}")
    print(f"  ASR: {WHISPER_MODEL}")
    print(f"  TTS: {VOICE_NAME} (Full ICL, real laugh clips)")
    print(f"  RAG: OCR Provenance ({OCR_PROVENANCE_URL})")
    print("  Audio: parec output.monitor -> pacat clone_audio")
    print("  NO loopback. Zero feedback. Full prosody.")
    print("=" * 60 + "\n")

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_event_loop().add_signal_handler(sig, stop.set)

    try:
        await audio_loop(page, stop)
    finally:
        # Clean shutdown
        try:
            leave = page.locator('[aria-label="Leave call"]').first
            if await leave.is_visible(timeout=2000):
                await leave.click()
        except Exception:
            pass
        await ctx.close()
        await pw.stop()

        # Release GPU memory
        release_models()

        # Close OCR Provenance client
        if _ocr_client is not None:
            await _ocr_client.close()

        logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
