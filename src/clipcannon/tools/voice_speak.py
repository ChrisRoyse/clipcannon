"""Voice MCP tools: speak and speak_optimized handlers."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from clipcannon.tools.voice_profiles import _error, _projects_dir, resolve_voice_profile

logger = logging.getLogger(__name__)


async def _handle_speak(arguments: dict[str, object]) -> dict[str, object]:
    """Handle clipcannon_speak tool call."""
    project_id = str(arguments.get("project_id", ""))
    text = str(arguments.get("text", ""))
    voice_name = arguments.get("voice_name")
    speed = float(arguments.get("speed", 1.0))
    max_attempts = int(arguments.get("max_attempts", 5))
    prosody_style = str(arguments.get("prosody_style", "")) or None
    temperature = float(arguments.get("temperature", 0.7))

    if not project_id or not text:
        return _error("MISSING_PARAMETER", "project_id and text are required")

    import secrets as _secrets

    from clipcannon.voice.inference import VoiceSynthesizer

    # Resolve voice profile if provided
    reference_embedding = None
    reference_audio_path: Path | None = None
    verification_threshold = 0.80

    if voice_name:
        resolved = resolve_voice_profile(str(voice_name))
        if "error" in resolved:
            return resolved
        verification_threshold = resolved["verification_threshold"]
        reference_embedding = resolved["reference_embedding"]
        ref_audio_str = resolved.get("reference_audio")
        if ref_audio_str:
            reference_audio_path = Path(str(ref_audio_str))

    # Prosody-aware reference selection: override default ref with a
    # clip whose prosody matches the target style
    if prosody_style and voice_name:
        try:
            from clipcannon.voice.prosody_select import select_prosody_reference

            prosody_ref = select_prosody_reference(
                str(voice_name), prosody_style,
            )
            if prosody_ref is not None:
                reference_audio_path = prosody_ref
                logger.info(
                    "Prosody style '%s': using reference %s",
                    prosody_style, prosody_ref.name,
                )
        except Exception as exc:
            return _error(
                "PROSODY_SELECTION_FAILED",
                f"Prosody style '{prosody_style}' was requested but selection failed: {exc}",
                {"remediation": "Retry without prosody_style, or backfill prosody data "
                                "for this voice first."},
            )

    # Output path
    projects_dir = _projects_dir()
    project_dir = projects_dir / project_id
    if not project_dir.exists():
        return _error("PROJECT_NOT_FOUND", f"Project directory not found: {project_id}")

    audio_dir = project_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    asset_id = f"audio_{_secrets.token_hex(6)}"
    output_path = audio_dir / f"{asset_id}_voice.wav"

    start = time.monotonic()
    try:
        synth = VoiceSynthesizer()
        result = synth.speak(
            text=text,
            output_path=output_path,
            reference_audio=reference_audio_path,
            reference_embedding=reference_embedding,
            verification_threshold=verification_threshold,
            max_attempts=max_attempts,
            temperature=temperature,
            speed=speed,
        )
    except Exception as exc:
        logger.exception("speak() failed for project %s", project_id)
        return _error("SYNTHESIS_FAILED", str(exc))

    # Post-process: enhance audio to remove vocoder artifacts
    enhanced_audio_path = result.audio_path
    enhanced_duration_ms = result.duration_ms
    enhanced_sample_rate = result.sample_rate

    enhance = arguments.get("enhance", True)
    if enhance:
        try:
            from clipcannon.voice.enhance import enhance_speech

            enhanced_path = output_path.parent / f"{asset_id}_voice_enhanced.wav"
            enhance_speech(result.audio_path, enhanced_path)
            enhanced_audio_path = enhanced_path
            # Update duration/SR from enhanced file
            import soundfile as _sf
            _info = _sf.info(str(enhanced_path))
            enhanced_duration_ms = int(_info.duration * 1000)
            enhanced_sample_rate = _info.samplerate
        except Exception as exc:
            # enhance=True was requested; raw TTS is a different output (#68).
            return _error(
                "ENHANCEMENT_FAILED", f"Speech enhancement failed: {exc}",
                {"raw_audio_path": str(result.audio_path),
                 "remediation": "Retry, or call again with enhance=false to accept raw TTS."},
            )

    elapsed_ms = int((time.monotonic() - start) * 1000)

    response: dict[str, object] = {
        "audio_asset_id": asset_id,
        "file_path": str(enhanced_audio_path),
        "duration_ms": enhanced_duration_ms,
        "sample_rate": enhanced_sample_rate,
        "attempts": result.attempts,
        "parameters_used": result.parameters_used,
        "elapsed_ms": elapsed_ms,
    }

    if result.verification is not None:
        response["verification"] = {
            "passed": result.verification.passed,
            "secs_score": round(result.verification.secs_score, 4),
            "wer": round(result.verification.wer, 4),
            "gate_failed": result.verification.gate_failed,
        }

    return response


async def _handle_speak_optimized(arguments: dict[str, object]) -> dict[str, object]:
    """Handle clipcannon_speak_optimized tool call.

    SECS-optimized synthesis: selects best references, generates N
    candidates, scores ALL by SECS (same model, same embedding space),
    returns the winner.
    """
    project_id = str(arguments.get("project_id", ""))
    text = str(arguments.get("text", ""))
    voice_name = str(arguments.get("voice_name", ""))
    n_candidates = int(arguments.get("n_candidates", 8))

    if not project_id or not text or not voice_name:
        return _error("MISSING_PARAMETER", "project_id, text, and voice_name are required")

    resolved = resolve_voice_profile(voice_name)
    if "error" in resolved:
        return resolved

    reference_embedding = resolved["reference_embedding"]
    all_clips = resolved.get("all_reference_clips", [])

    if reference_embedding is None:
        return _error(
            "NO_FINGERPRINT",
            "Voice profile has no reference embedding. "
            "Run voice data prep and build the fingerprint first.",
        )

    if not all_clips:
        return _error(
            "NO_REFERENCE_CLIPS",
            "No reference audio clips found for this voice profile. "
            "Run clipcannon_prepare_voice_data first.",
        )

    projects_dir = _projects_dir()
    project_dir = projects_dir / project_id
    if not project_dir.exists():
        return _error("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    import secrets as _secrets

    audio_dir = project_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    asset_id = f"audio_{_secrets.token_hex(6)}"
    output_path = audio_dir / f"{asset_id}_voice_optimized.wav"

    try:
        from clipcannon.voice.inference import VoiceSynthesizer
        from clipcannon.voice.optimize import optimized_speak
        from clipcannon.voice.verify import VoiceVerifier

        synth = VoiceSynthesizer()
        engine = synth._ensure_engine()
        verifier = VoiceVerifier(reference_embedding, threshold=0.35)

        result = optimized_speak(
            engine=engine,
            text=text,
            output_path=output_path,
            verifier=verifier,
            reference_clips=[Path(c) for c in all_clips],
            n_candidates=n_candidates,
        )
    except Exception as exc:
        logger.exception("Optimized speak failed for %s", voice_name)
        return _error("SYNTHESIS_FAILED", str(exc))

    # Post-process: enhance audio to remove vocoder artifacts
    enhanced_audio_path = result.audio_path
    enhanced_duration_ms = result.duration_ms
    enhanced_sample_rate = result.sample_rate

    enhance = arguments.get("enhance", True)
    if enhance:
        try:
            from clipcannon.voice.enhance import enhance_speech

            enhanced_path = output_path.parent / f"{asset_id}_voice_opt_enhanced.wav"
            enhance_speech(result.audio_path, enhanced_path)
            enhanced_audio_path = enhanced_path
            import soundfile as _sf
            _info = _sf.info(str(enhanced_path))
            enhanced_duration_ms = int(_info.duration * 1000)
            enhanced_sample_rate = _info.samplerate
        except Exception as exc:
            # enhance=True was requested; raw TTS is a different output (#68).
            return _error(
                "ENHANCEMENT_FAILED", f"Speech enhancement failed: {exc}",
                {"raw_audio_path": str(result.audio_path),
                 "remediation": "Retry, or call again with enhance=false to accept raw TTS."},
            )

    return {
        "audio_asset_id": asset_id,
        "file_path": str(enhanced_audio_path),
        "duration_ms": enhanced_duration_ms,
        "sample_rate": enhanced_sample_rate,
        "secs_score": round(result.secs_score, 4),
        "candidates_generated": result.candidates_generated,
        "best_candidate_index": result.best_candidate_index,
        "reference_clip_used": result.reference_clip_used,
        "elapsed_s": result.elapsed_s,
    }
