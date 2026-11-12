"""Model warm-up, Xvfb + Playwright launch and Google Meet join for the Santa bot."""
import asyncio
import logging
import os
from pathlib import Path

from .avatar import (
    _set_ref_transcripts,
    init_face_warper,
    init_physics_face,
    init_semantic_model,
)
from .config import IDLE_Y4M, MEET_URL, SESSION_DIR, _ref_mapping
from .init_script import AVATAR_INIT_SCRIPT
from .models import get_tts, get_whisper, gpu_cleanup, log_gpu_state

logger = logging.getLogger("santa_bot")


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
        _set_ref_transcripts(_ref_transcripts)
    gpu_cleanup()
    log_gpu_state("tts")

    # 4. Physics face engine + semantic model + legacy face warper fallback
    init_physics_face()
    init_semantic_model()
    init_face_warper()
    gpu_cleanup()

    logger.info("=== ALL MODELS WARM — joining meeting ===")

    # Start Xvfb virtual display — Chrome runs invisible, no window on user's screen
    import subprocess as _sp
    _xvfb = _sp.Popen(
        ["Xvfb", ":99", "-screen", "0", "1280x720x24", "-ac"],
        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
    )
    os.environ["DISPLAY"] = ":99"
    logger.info("Xvfb started on :99 (invisible virtual display)")

    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=SESSION_DIR, headless=False,  # headful on virtual display
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
    # Init script: Intercept getUserMedia with REAL fake-device track metadata
    #
    # THE KEY INSIGHT: Google Meet validates video tracks by checking
    # getSettings() and getCapabilities(). A raw MediaStreamTrackGenerator
    # returns empty metadata and Meet silently disables it.
    #
    # SOLUTION: Call the ORIGINAL getUserMedia to get the fake device's
    # video track (which has real camera metadata). Then use Insertable
    # Streams (MediaStreamTrackProcessor → transform → MediaStreamTrackGenerator)
    # to pipe our custom canvas frames THROUGH the real track's pipeline.
    # The generator inherits the processor's metadata chain, so Meet sees
    # a track with real getSettings()/getCapabilities() that contains our frames.
    #
    # If Insertable Streams are not available (older Chrome), fall back to
    # canvas.captureStream() with getSettings/getCapabilities spoofed from
    # the real track.
    #
    # MUST be minimal — large scripts crash the page.
    await context.add_init_script(AVATAR_INIT_SCRIPT)
    page = context.pages[0] if context.pages else await context.new_page()
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
                            '[aria-label*="Unmute"]',
                            '[aria-label*="microphone"][data-is-muted="true"]',
                            'button[aria-label*="micro"]']:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible(timeout=2000):
                            await btn.click()
                            logger.info("Mic unmuted")
                            break
                    except Exception:
                        continue

                # No replaceTrack needed — getUserMedia was intercepted by init script.
                # Video: real fake-device track → Insertable Streams → our canvas frames
                # Audio: AudioContext created in init script for TTS injection
                await asyncio.sleep(2)

                # Verify the video pipeline is working
                try:
                    status = await page.evaluate("""() => {
                        const info = {
                            jpegVar: typeof window.__santaJpegB64,
                            audioCtx: !!window.__santaAudioCtx,
                            audioDest: !!window.__santaAudioDest,
                        };
                        return JSON.stringify(info);
                    }""")
                    logger.info("Avatar pipeline status: %s", status)
                except Exception:
                    pass

                logger.info("Insertable Streams avatar pipeline active")
                return pw, context, page
        except Exception:
            continue

    return None, None, None
