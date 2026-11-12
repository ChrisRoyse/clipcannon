"""Speech-buffer processing, Whisper transcription and Ollama responses for the Santa bot."""
import asyncio
import logging
import time

import numpy as np

from .avatar import speak
from .config import _MAX_TRANSCRIPT_SEGMENTS, LLM_MODEL, _transcript_segments
from .models import get_whisper, gpu_cleanup, log_gpu_state, search_meeting_history

logger = logging.getLogger("santa_bot")


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
    # Disable Whisper's internal VAD — it filters out PulseAudio TCP's quiet audio.
    # We normalize audio before calling transcribe(), so VAD isn't needed.
    segs, _ = model.transcribe(audio, language="en", vad_filter=False)
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
                    # Gemma 4 doesn't use think parameter
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


# Audio/video injection is handled entirely by the init script
# (MediaStreamTrackGenerator for video, AudioContext for audio)
# No post-join track replacement needed
