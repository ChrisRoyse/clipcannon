"""Audio capture + Reasoning Controller loop (with avatar video render) for the Santa bot."""
import asyncio
import logging
import os
import time

import cv2
import numpy as np

from . import avatar
from .avatar import speak
from .config import (
    _MAX_TRANSCRIPT_SEGMENTS,
    CAPTURE_DEVICE,
    CHUNK_BYTES,
    MIN_SPEECH_BYTES,
    SAMPLE_RATE,
    _transcript_segments,
)
from .dialogue import respond, transcribe
from .models import ingest_transcript, log_gpu_state

logger = logging.getLogger("santa_bot")


# ---------------------------------------------------------------------------
# Audio capture + Reasoning Controller loop
# ---------------------------------------------------------------------------
async def audio_loop(page, stop):
    """Continuous listening loop driven by the Reasoning Controller.

    The controller observes all speech, reasons about what to do,
    and controls prosody selection, lip sync, and response timing.
    """
    from voiceagent.meeting.reasoning_controller import (
        ActionIntent,
        ReasoningController,
    )

    log_gpu_state("models-ready")
    logger.info("ALL MODELS IN VRAM — ready to converse")

    history: list[dict] = []
    meeting_id = f"mtg_{int(time.time())}"

    # --- Response handler called by reasoning controller ---
    async def handle_respond(user_text: str) -> str | None:
        """Generate response, speak it, return the text."""
        t_start = time.time()
        resp = await respond(user_text, history)
        if not resp or len(resp) < 10:
            logger.warning("Skipped short/empty response: '%s'", resp)
            return None

        t_llm = time.time()
        logger.info("SANTA: '%s' (LLM: %dms)", resp, (t_llm - t_start) * 1000)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": resp})
        if len(history) > 6:
            del history[:len(history) - 6]

        await speak(page, resp)
        t_total = time.time() - t_start
        logger.info("TOTAL RESPONSE: %.1fs (target <2s)", t_total)
        return resp

    # --- Avatar rendering driven by controller commands ---
    _last_avatar_cmd = None

    def handle_avatar_command(cmd) -> None:
        """Receive command from reasoning controller — queue for rendering."""
        nonlocal _last_avatar_cmd
        _last_avatar_cmd = cmd

    def handle_expression(intent: ActionIntent, awareness) -> None:
        if intent in (ActionIntent.RESPOND, ActionIntent.INTERJECT,
                       ActionIntent.LISTEN_AMUSED, ActionIntent.LISTEN_EMPATHETIC):
            logger.info("Avatar: %s [emo=%s]", intent.value, awareness.detected_emotion)

    async def video_render_loop():
        """Render avatar → push JPEG to Chrome via page.evaluate.

        Chrome's init script uses MediaStreamTrackGenerator + OffscreenCanvas.
        We set window.__santaJpegB64 with a JPEG base64 string (~30KB).
        The generator loop decodes it and produces VideoFrames at 15fps.
        Much smaller than raw RGBA (30KB vs 4.9MB per frame).
        """
        import base64, math

        FPS = 15  # 15fps JPEG updates, generator runs at 30fps
        frame_count = 0

        # Try loading the trained Gaussian renderer (real 3D video generation)
        _gaussian_renderer = None
        gaussian_model_path = os.path.expanduser("~/.clipcannon/models/santa/gaussian_avatar.pt")
        if os.path.exists(gaussian_model_path):
            try:
                from phoenix.render.avatar_renderer import GaussianAvatarRenderer
                _gaussian_renderer = GaussianAvatarRenderer.load_trained(gaussian_model_path)
                logger.info("Gaussian Avatar loaded — rendering real 3D video at 731 FPS")
            except Exception as e:
                logger.warning("Gaussian renderer failed (%s), falling back to FaceWarper", e)

        # Wait for at least one renderer to be ready
        while not stop.is_set():
            if _gaussian_renderer is not None or (
                avatar._face_warper is not None and avatar._face_warper.ready
            ):
                break
            await asyncio.sleep(1)

        use_gaussian = _gaussian_renderer is not None
        has_physics = avatar._physics_face is not None
        logger.info("Video render: %s + %s at %dfps -> Insertable Streams",
                     "Gaussian 3D" if use_gaussian else "FaceWarper 2D",
                     "PhysicsFace" if has_physics else "manual blend",
                     FPS)

        while not stop.is_set():
            frame_count += 1
            t = frame_count / FPS
            cmd = _last_avatar_cmd

            # Build expression from PhysicsFaceEngine or controller commands
            breath = math.sin(t * 0.4) * 0.03
            sway = math.sin(t * 0.3) * 2.0

            if cmd is not None:
                jaw_open = cmd.blendshapes.get("jawOpen", 0.0) + max(0, breath)
                smile = cmd.blendshapes.get("mouthSmileLeft", 0.0)
                head_tilt = (cmd.head_pose[2] if cmd.head_pose else 0.0) + sway * 0.3
                jaw_open = min(1.0, jaw_open + smile * 0.1)
            else:
                jaw_open = max(0, breath)
                smile = 0.0
                head_tilt = sway

            if (t % 4.0) < 0.15:
                jaw_open += 0.04

            # RENDER: Gaussian 3D + PhysicsFace > Gaussian 3D > FaceWarper
            if use_gaussian:
                try:
                    import torch
                    if has_physics and cmd is not None:
                        # PhysicsFaceEngine provides FLAME params directly
                        # from the last processed audio chunk (set by speak())
                        physics_bs = cmd.blendshapes
                        exp = torch.zeros(100, device="cuda")
                        exp[0] = physics_bs.get("jawOpen", jaw_open) * 5.0
                        exp[1] = physics_bs.get("mouthSmileLeft", 0.0) * 3.0
                        exp[2] = physics_bs.get("mouthPucker", 0.0) * 4.0
                        exp[3] = physics_bs.get("mouthUpperUpLeft", 0.0) * 2.0
                        exp[4] = physics_bs.get("mouthLowerDownLeft", 0.0) * 2.0
                        exp[5] = physics_bs.get("browInnerUp", 0.0) * 3.0
                        exp[6] = physics_bs.get("eyeSquintLeft", 0.0) * 2.0
                        exp[7] = physics_bs.get("mouthFunnel", 0.0) * 2.5
                        jp = torch.zeros(3, device="cuda")
                        jp[0] = physics_bs.get("jawOpen", jaw_open) * 0.4
                    else:
                        exp = torch.zeros(100, device="cuda")
                        exp[0] = jaw_open * 5.0
                        exp[1] = (smile * 3.0) if cmd else 0.0
                        exp[2] = math.sin(t * 0.5) * 0.5
                        jp = torch.zeros(3, device="cuda")
                        jp[0] = jaw_open * 0.3
                    result = _gaussian_renderer.render_frame(
                        expression_params=exp, jaw_pose=jp,
                    )
                    img = result["image"]
                    frame_np = (img.detach().cpu().clamp(0, 1).numpy() * 255).astype(np.uint8)
                    frame_bgr = cv2.cvtColor(cv2.resize(frame_np, (1280, 720)), cv2.COLOR_RGB2BGR)
                except Exception as e:
                    if frame_count % 100 == 1:
                        logger.warning("Gaussian render failed: %s", e)
                    frame_bgr = avatar._face_warper.warp_mouth(jaw_open, head_tilt) if avatar._face_warper and avatar._face_warper.ready else np.zeros((720, 1280, 3), dtype=np.uint8)
            else:
                frame_bgr = avatar._face_warper.warp_mouth(jaw_open, head_tilt)

            # Encode as JPEG (~30KB vs 4.9MB for raw RGBA)
            _, jpg_buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 60])
            jpg_b64 = base64.b64encode(jpg_buf).decode('ascii')

            try:
                await page.evaluate("b64 => { window.__santaJpegB64 = b64; }", jpg_b64)
            except Exception:
                pass

            if frame_count % (FPS * 10) == 1:
                logger.info("Video frame #%d (%dKB JPEG, jaw=%.2f)",
                            frame_count, len(jpg_b64) // 1024, jaw_open)

            await asyncio.sleep(1.0 / FPS)

    # --- Create the reasoning controller ---
    controller = ReasoningController(
        character_name="Santa",
        aliases=("claus", "mr. claus", "father christmas", "jarvis"),
        respond_callback=handle_respond,
        expression_callback=handle_expression,
        avatar_callback=handle_avatar_command,
    )

    # Start reasoning controller + video render as async tasks
    reasoning_task = asyncio.create_task(controller.run(stop))
    video_task = asyncio.create_task(video_render_loop())
    logger.info("Reasoning controller + video render started")

    # Start audio capture
    parec = await asyncio.create_subprocess_exec(
        "parec", f"--device={CAPTURE_DEVICE}",
        "--format=s16le", f"--rate={SAMPLE_RATE}", "--channels=1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    logger.info("Capturing from %s (PID %d)", CAPTURE_DEVICE, parec.pid)

    buf = bytearray()
    window_start = time.time()
    WINDOW_S = 2.0  # Transcribe every 2 seconds
    MAX_BUF_BYTES = SAMPLE_RATE * 2 * 8

    while not stop.is_set():
        try:
            chunk = await asyncio.wait_for(
                parec.stdout.read(CHUNK_BYTES), timeout=0.2,
            )
        except asyncio.TimeoutError:
            chunk = None
            # Track silence for the controller
            controller.tick_silence(200)
        except Exception:
            break

        # While responding, drain audio but don't accumulate
        if controller.is_responding:
            continue

        if chunk:
            buf.extend(chunk)
            if len(buf) > MAX_BUF_BYTES:
                buf = buf[-MAX_BUF_BYTES:]

        # Transcribe on window boundary
        elapsed = time.time() - window_start
        if elapsed >= WINDOW_S and len(buf) > MIN_SPEECH_BYTES:
            window_start = time.time()

            # Normalize quiet PulseAudio audio
            audio = np.frombuffer(bytes(buf), dtype=np.int16).astype(np.float32) / 32768.0
            peak = np.max(np.abs(audio))
            if peak > 0:
                audio = audio * min(0.9 / peak, 50.0)

            text = await transcribe(audio)
            del audio

            if text and len(text) > 2:
                logger.info("HEARD: '%s'", text)

                # Feed to reasoning controller (Tier 1 observation)
                controller.observe(text)

                # Store transcript
                _transcript_segments.append({
                    "speaker": "Participant", "text": text,
                    "timestamp": time.strftime("%H:%M:%S"),
                })
                if len(_transcript_segments) > _MAX_TRANSCRIPT_SEGMENTS:
                    del _transcript_segments[:len(_transcript_segments) - _MAX_TRANSCRIPT_SEGMENTS]

                # Let the controller decide what to do (Tier 2)
                intent = controller.reason()

                if intent in (ActionIntent.RESPOND, ActionIntent.INTERJECT):
                    # Tier 3: Generate and speak response
                    recent_text = controller._get_recent_text(15)
                    await controller.execute_response(recent_text)
                    window_start = time.time()  # Reset so next listen starts fast

            buf.clear()

    # Cleanup
    controller.stop()
    reasoning_task.cancel()
    video_task.cancel()
    parec.kill()
    await ingest_transcript(_transcript_segments, meeting_id)
