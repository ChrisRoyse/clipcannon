"""main() entry coroutine for the Santa bot."""
import asyncio
import logging
import signal

from . import models
from .browser import launch_browser
from .config import LLM_MODEL, OCR_PROVENANCE_URL, VOICE_NAME, WHISPER_MODEL
from .listen import audio_loop
from .models import release_models

logger = logging.getLogger("santa_bot")


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
    print("  Audio: parec output.monitor (meeting only) | TTS -> bot_output (null)")
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
        if models._ocr_client is not None:
            await models._ocr_client.close()

        # Kill Xvfb
        try:
            _xvfb.kill()
        except Exception:
            pass
        logger.info("Shutdown complete")
