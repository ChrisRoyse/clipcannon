"""Full autonomous video generation orchestrator for ClipCannon.

End-to-end pipeline: Script --> Voice Clone --> Lip Sync --> Output.
Optionally extracts webcam from an ingested project for the driver video.
Every step has verification gates. Bad output never propagates forward.
"""

from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.exceptions import ClipCannonError

logger = logging.getLogger(__name__)


def _error(
    code: str, message: str, details: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build standardized error response dict."""
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _projects_dir() -> Path:
    """Resolve projects base directory."""
    try:
        config = ClipCannonConfig.load()
        return config.resolve_path("directories.projects")
    except ClipCannonError:
        return Path.home() / ".clipcannon" / "projects"


async def clipcannon_generate_video(
    arguments: dict[str, object],
) -> dict[str, object]:
    """Generate a complete video from a text script.

    Pipeline:
    1. WEBCAM (optional): Extract webcam from ingested project
    2. VOICE: Qwen3-TTS generates speech (with verification loop)
    3. LIP SYNC: LatentSync maps audio onto driver video
    4. Result: A video file of the person speaking the script

    If ``driver_video_path`` is not provided but the project has
    scene_map data with detected faces, the webcam region is
    automatically extracted and used as the driver video.

    Args:
        arguments: Tool arguments including script, voice_name,
            driver_video_path (or auto-extract from project),
            and optional style parameters.

    Returns:
        Result dict with paths to generated audio and video.
    """
    script = str(arguments.get("script", ""))
    voice_name = arguments.get("voice_name")
    driver_video_path = str(arguments.get("driver_video_path", ""))
    project_id = str(arguments.get("project_id", ""))
    speed = float(arguments.get("speed", 1.0))
    max_voice_attempts = int(arguments.get("max_voice_attempts", 5))
    lip_sync_steps = int(arguments.get("lip_sync_steps", 20))
    guidance_scale = float(arguments.get("guidance_scale", 1.5))
    seed = arguments.get("seed")

    if not script:
        return _error("MISSING_PARAMETER", "script text is required")
    if not project_id:
        return _error("MISSING_PARAMETER", "project_id is required")

    projects_dir = _projects_dir()
    project_dir = projects_dir / project_id
    if not project_dir.exists():
        return _error("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    gen_id = f"gen_{secrets.token_hex(6)}"
    gen_dir = project_dir / "generated" / gen_id
    gen_dir.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    steps_completed: list[str] = []

    # ============================================================
    # STEP 0: Driver Video Resolution
    # ============================================================
    driver_path: Path | None = None

    if driver_video_path:
        driver_path = Path(driver_video_path)
        if not driver_path.exists():
            return _error("FILE_NOT_FOUND", f"Driver video not found: {driver_path}")
    else:
        # Auto-extract webcam from the ingested project
        logger.info("Generate %s: No driver video -- extracting webcam from project", gen_id)
        from clipcannon.tools.avatar import _handle_extract_webcam

        extract_result = await _handle_extract_webcam({
            "project_id": project_id,
            "padding_pct": 0.15,
        })
        if "error" in extract_result:
            return _error(
                "WEBCAM_EXTRACTION_FAILED",
                f"Could not extract webcam from project: "
                f"{extract_result['error']['message']}. "
                f"Either provide driver_video_path or ensure the project "
                f"is ingested and contains a visible face.",
                {"extraction_error": extract_result["error"]},
            )
        driver_path = Path(str(extract_result["video_path"]))
        steps_completed.append("webcam_extract")
        logger.info(
            "Generate %s: Webcam extracted — %s (%s)",
            gen_id, extract_result["resolution"], extract_result["video_path"],
        )

    # ============================================================
    # STEP 1: Voice Generation
    # ============================================================
    logger.info("Generate %s: Step 1 — Voice synthesis", gen_id)

    voice_path = gen_dir / "voice.wav"
    reference_embedding = None
    reference_audio_path = None
    verification_threshold = 0.80

    if voice_name:
        from clipcannon.tools.voice import resolve_voice_profile

        resolved = resolve_voice_profile(str(voice_name))
        if "error" in resolved:
            return resolved
        verification_threshold = resolved["verification_threshold"]
        reference_embedding = resolved["reference_embedding"]
        ref_audio_str = resolved.get("reference_audio")
        if ref_audio_str:
            reference_audio_path = Path(str(ref_audio_str))

    try:
        from clipcannon.voice.inference import VoiceSynthesizer

        synth = VoiceSynthesizer()
        voice_result = synth.speak(
            text=script,
            output_path=voice_path,
            reference_audio=reference_audio_path,
            reference_embedding=reference_embedding,
            verification_threshold=verification_threshold,
            max_attempts=max_voice_attempts,
            speed=speed,
        )
    except Exception as exc:
        logger.exception("Generate %s: Voice synthesis failed", gen_id)
        return _error("VOICE_FAILED", str(exc), {"step": "voice", "gen_id": gen_id})

    voice_info: dict[str, object] = {
        "audio_path": str(voice_result.audio_path),
        "duration_ms": voice_result.duration_ms,
        "attempts": voice_result.attempts,
    }
    if voice_result.verification:
        voice_info["verification"] = {
            "passed": voice_result.verification.passed,
            "secs_score": round(voice_result.verification.secs_score, 4),
        }

    steps_completed.append("voice")
    logger.info(
        "Generate %s: Voice done — %dms, %d attempts",
        gen_id, voice_result.duration_ms, voice_result.attempts,
    )

    # ============================================================
    # STEP 2: Lip Sync
    # ============================================================
    logger.info("Generate %s: Step 2 — Lip sync", gen_id)

    lipsync_path = gen_dir / "lipsync.mp4"

    try:
        from clipcannon.avatar.lip_sync import get_engine

        engine = get_engine()
        lipsync_result = engine.generate(
            video_path=driver_path,
            audio_path=voice_path,
            output_path=lipsync_path,
            inference_steps=lip_sync_steps,
            guidance_scale=guidance_scale,
            seed=int(seed) if seed is not None else None,
        )
    except RuntimeError as exc:
        if "Face not detected" in str(exc):
            return _error(
                "FACE_NOT_DETECTED", str(exc),
                {"step": "lip_sync", "gen_id": gen_id, "voice": voice_info},
            )
        logger.exception("Generate %s: Lip sync failed", gen_id)
        return _error(
            "LIP_SYNC_FAILED", str(exc),
            {"step": "lip_sync", "gen_id": gen_id, "voice": voice_info},
        )
    except Exception as exc:
        logger.exception("Generate %s: Lip sync failed", gen_id)
        return _error(
            "LIP_SYNC_FAILED", str(exc),
            {"step": "lip_sync", "gen_id": gen_id, "voice": voice_info},
        )

    lipsync_info = {
        "video_path": str(lipsync_result.video_path),
        "duration_ms": lipsync_result.duration_ms,
        "resolution": lipsync_result.resolution,
        "elapsed_s": lipsync_result.elapsed_s,
    }

    steps_completed.append("lip_sync")
    logger.info(
        "Generate %s: Lip sync done — %dms, %s",
        gen_id, lipsync_result.duration_ms, lipsync_result.resolution,
    )

    # ============================================================
    # RESULT
    # ============================================================
    total_elapsed = time.monotonic() - start

    return {
        "gen_id": gen_id,
        "steps_completed": steps_completed,
        "voice": voice_info,
        "lip_sync": lipsync_info,
        "total_elapsed_s": round(total_elapsed, 2),
        "output_video": str(lipsync_result.video_path),
        "output_audio": str(voice_result.audio_path),
    }


async def dispatch_generate_tool(
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    """Dispatch a generate tool call by name."""
    if name == "clipcannon_generate_video":
        return await clipcannon_generate_video(arguments)
    return _error("INTERNAL_ERROR", f"Unknown generate tool: {name}")
