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
IDLE_Y4M = str(Path("~/.voiceagent/drivers/santa_idle.y4m").expanduser())
VOICE_NAME = "santa"
LLM_MODEL = "qwen3:14b-nothink"
WHISPER_MODEL = "large-v3-turbo"
OCR_PROVENANCE_URL = "http://localhost:3377/mcp"
OCR_DB_NAME = "meetings"

# Audio capture settings
CAPTURE_DEVICE = "output.monitor"
AUDIO_SINK = "clone_audio"
SAMPLE_RATE = 16000
CHUNK_BYTES = 3200  # 100ms at 16kHz mono 16-bit

# Energy threshold for speech detection
ENERGY_THRESHOLD = 0.01
SILENCE_TIMEOUT_S = 1.5
MIN_SPEECH_BYTES = 16000  # ~0.5s minimum speech

# Expression library
LAUGH_CLIPS = [
    str(Path("~/.clipcannon/voice_data/santa/expressions/laugh_01_511s.wav").expanduser()),
    str(Path("~/.clipcannon/voice_data/santa/expressions/laugh_02_550s.wav").expanduser()),
]
_laugh_idx = 0

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

# Remove ALL loopbacks
subprocess.run(["pactl", "set-default-source", "clone_audio.monitor"],
               capture_output=True, timeout=5)
subprocess.run(["pactl", "set-default-sink", "output"],
               capture_output=True, timeout=5)
for line in subprocess.run(
    ["pactl", "list", "short", "modules"],
    capture_output=True, text=True, timeout=5,
).stdout.strip().split("\n"):
    if "loopback" in line.lower():
        mid = line.split()[0]
        subprocess.run(["pactl", "unload-module", mid],
                       capture_output=True, timeout=5)
        logger.info("Removed loopback module %s", mid)


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
        _tts_adapter.release()
        _tts_adapter = None
    if _whisper_model is not None:
        del _whisper_model
        _whisper_model = None
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except ImportError:
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
            await _ocr_client.call_tool("ocr_db_select", {"name": OCR_DB_NAME})
        except Exception:
            try:
                await _ocr_client.call_tool("ocr_db_create", {
                    "name": OCR_DB_NAME,
                    "description": "Clone meeting transcripts",
                })
                await _ocr_client.call_tool("ocr_db_select", {"name": OCR_DB_NAME})
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
# Browser launch
# ---------------------------------------------------------------------------
async def launch_browser():
    """Launch Playwright browser and join the meeting."""
    if not MEET_URL:
        logger.error("No meeting URL provided. Usage: python santa_meet_bot.py <URL>")
        return None, None, None

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
        ],
        viewport={"width": 1280, "height": 720},
        locale="en-US",
        permissions=["camera", "microphone"],
    )
    page = context.pages[0] if context.pages else await context.new_page()
    await page.add_init_script(
        'Object.defineProperty(navigator,"webdriver",{get:()=>false});'
    )
    await page.goto(MEET_URL, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(4)

    # Mute mic before joining
    for sel in ['[aria-label*="Turn off microphone"]']:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=2000):
                await btn.click()
                logger.info("Mic off")
            break
        except Exception:
            continue

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
                return pw, context, page
        except Exception:
            continue

    return None, None, None


# ---------------------------------------------------------------------------
# Audio capture + processing loop
# ---------------------------------------------------------------------------
async def audio_loop(page, stop):
    """Main audio capture and response loop."""
    # Warm up models before capturing audio
    get_whisper()
    get_tts()

    # Start parec from output.monitor
    parec = await asyncio.create_subprocess_exec(
        "parec", f"--device={CAPTURE_DEVICE}",
        "--format=s16le", f"--rate={SAMPLE_RATE}", "--channels=1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    logger.info("Capturing from %s (PID %d)", CAPTURE_DEVICE, parec.pid)

    history: list[dict] = []
    buf = bytearray()
    last_t = time.time()
    speaking = False
    responding = False
    meeting_id = f"mtg_{int(time.time())}"
    ingest_counter = 0

    while not stop.is_set():
        try:
            chunk = await asyncio.wait_for(
                parec.stdout.read(CHUNK_BYTES), timeout=0.3,
            )
        except asyncio.TimeoutError:
            if speaking and not responding and (time.time() - last_t) > SILENCE_TIMEOUT_S:
                speaking = False
                if len(buf) > MIN_SPEECH_BYTES:
                    responding = True
                    await process(buf, history, page, meeting_id)
                    responding = False
                    # Periodic transcript ingestion
                    ingest_counter += 1
                    if ingest_counter >= 3:
                        ingest_counter = 0
                        await ingest_transcript(_transcript_segments, meeting_id)
                buf.clear()
            continue
        if not chunk:
            break
        if responding:
            continue  # Ignore audio while bot is speaking

        energy = np.sqrt(np.mean(
            (np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768) ** 2,
        ))
        if energy > ENERGY_THRESHOLD:
            buf.extend(chunk)
            last_t = time.time()
            # Cap buffer at 30s to prevent memory bloat
            max_buf = SAMPLE_RATE * 2 * 30  # 30s of 16-bit mono
            if len(buf) > max_buf:
                buf = buf[-max_buf:]
            if not speaking:
                speaking = True
        elif speaking and (time.time() - last_t) > SILENCE_TIMEOUT_S:
            speaking = False
            if len(buf) > MIN_SPEECH_BYTES:
                responding = True
                await process(buf, history, page, meeting_id)
                responding = False
                ingest_counter += 1
                if ingest_counter >= 3:
                    ingest_counter = 0
                    await ingest_transcript(_transcript_segments, meeting_id)
            buf.clear()

    parec.kill()

    # Final transcript ingest
    await ingest_transcript(_transcript_segments, meeting_id)


async def process(buf, history, page, meeting_id):
    """Process speech buffer: transcribe -> search -> respond -> speak."""
    audio = np.frombuffer(bytes(buf), dtype=np.int16).astype(np.float32) / 32768.0
    text = await transcribe(audio)
    if not text or len(text) < 3:
        return
    logger.info("HEARD: '%s'", text)

    # Store in transcript
    ts = time.strftime("%H:%M:%S")
    _transcript_segments.append({
        "speaker": "Participant", "text": text, "timestamp": ts,
    })
    # Cap transcript buffer
    if len(_transcript_segments) > _MAX_TRANSCRIPT_SEGMENTS:
        del _transcript_segments[:len(_transcript_segments) - _MAX_TRANSCRIPT_SEGMENTS]

    resp = await respond(text, history)
    if not resp:
        return
    logger.info("SANTA: '%s'", resp)

    # Store response in transcript
    _transcript_segments.append({
        "speaker": "Santa (Clone)", "text": resp, "timestamp": time.strftime("%H:%M:%S"),
    })

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": resp})
    # Keep history bounded
    if len(history) > 20:
        del history[:len(history) - 20]

    await speak(page, resp)

    # Free memory after response cycle
    gc.collect()


async def transcribe(audio):
    """Transcribe audio using the singleton Whisper model."""
    model = get_whisper()
    segs, _ = model.transcribe(audio, language="en", vad_filter=True)
    return " ".join(s.text.strip() for s in segs).strip()


async def respond(text, history):
    """Generate response using Ollama 14B with OCR Provenance RAG."""
    import httpx

    # Search meeting history for relevant context
    history_context = await search_meeting_history(text)

    # Build system prompt with full prosody instructions
    system = (
        "You are Santa Claus in a video meeting. Warm, jolly, and wise. "
        "Use [LAUGH] when laughing — start most responses with [LAUGH]. "
        "No markdown. Spoken conversation only. 1-3 sentences. "
        "Speak with full vocal expression — vary your pitch, pace, and "
        "emphasis. Use pauses for dramatic effect. Be warm and engaging. "
    )
    if history_context:
        system += (
            "You have access to context from past meetings. "
            "Use it to give informed answers when relevant. "
        )

    # Build messages
    msgs = [{"role": "system", "content": system}]
    msgs.extend(history[-10:])

    # Build user message with RAG context
    user_msg = text
    if history_context:
        user_msg = (
            f"[Context from past meetings]\n{history_context}\n\n"
            f"[Current question]\n{text}"
        )
    msgs.append({"role": "user", "content": user_msg})

    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(
            "http://localhost:11434/api/chat",
            json={
                "model": LLM_MODEL,
                "messages": msgs,
                "stream": False,
                "options": {
                    "num_predict": 200,
                    "temperature": 0.6,
                    "top_p": 0.85,
                },
            },
        )
    return r.json().get("message", {}).get("content", "").strip()


async def speak(page, text):
    """Synthesize speech with laugh clips and play to meeting."""
    global _laugh_idx
    import soundfile as sf

    tts = get_tts()
    try:
        parts = re.split(r'\[LAUGH\]', text)
        lc = text.count('[LAUGH]')
        segs, sr = [], 24000

        for i, p in enumerate(parts):
            # Insert laugh clip before this part (if preceded by [LAUGH])
            if i > 0 and i <= lc:
                try:
                    clip_path = LAUGH_CLIPS[_laugh_idx % len(LAUGH_CLIPS)]
                    _laugh_idx += 1
                    la, lsr = sf.read(clip_path)
                    if lsr != sr:
                        from scipy.signal import resample as rs
                        la = rs(la, int(len(la) * sr / lsr))
                    segs.append(la.astype(np.float32))
                except Exception:
                    pass

            p = p.strip()
            if p:
                try:
                    a = await tts.synthesize(p)
                    if len(a) > 0:
                        segs.append(a)
                except Exception as e:
                    logger.warning("TTS: %s", e)

        if not segs:
            return
        audio = np.concatenate(segs)
        # Free segment arrays immediately
        del segs

        pcm = (audio * 32767).astype(np.int16).tobytes()
        del audio  # Free float array

        # Mic on
        for sel in ['[aria-label*="Turn on microphone"]']:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    break
            except Exception:
                continue
        await asyncio.sleep(0.2)

        # Send TTS to clone_audio -> browser fake mic -> meeting
        proc = await asyncio.create_subprocess_exec(
            "pacat", f"--device={AUDIO_SINK}",
            "--format=s16le", f"--rate={sr}", "--channels=1",
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        proc.stdin.write(pcm)
        await proc.stdin.drain()
        proc.stdin.close()
        await proc.wait()
        del pcm  # Free PCM buffer
        await asyncio.sleep(0.3)

        # Mic off
        for sel in ['[aria-label*="Turn off microphone"]']:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    break
            except Exception:
                continue

        logger.info("Spoke: %.1fs", len(audio) / sr if 'audio' in dir() else 0)
    except Exception as e:
        logger.error("Speak failed: %s", e)


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
