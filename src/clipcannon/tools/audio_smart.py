"""Smart music generation MCP tools for ClipCannon.

Contains video-aware auto_music and description-based compose_music tools.
Separated from audio.py to keep modules under 500 lines.
"""

from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path

logger = logging.getLogger(__name__)


async def clipcannon_auto_music(
    project_id: str,
    edit_id: str,
    style_override: str | None = None,
    tier: str = "auto",
    duration_override_s: float | None = None,
    *,
    validate_project: object,
    validate_edit: object,
    db_path_fn: object,
    audio_dir_fn: object,
    store_asset_fn: object,
    error_fn: object,
) -> dict[str, object]:
    """Analyze video edit and generate matching background music."""
    start_time = time.monotonic()

    err = validate_project(project_id)  # type: ignore[operator]
    if err is not None:
        return err
    err = validate_edit(project_id, edit_id)  # type: ignore[operator]
    if err is not None:
        return err

    if tier not in ("ai", "midi", "auto"):
        return error_fn(  # type: ignore[operator]
            "INVALID_PARAMETER",
            f"Unknown tier: {tier}. Must be 'ai', 'midi', or 'auto'.",
        )

    from clipcannon.audio.music_planner import MusicPlanner

    db = db_path_fn(project_id)  # type: ignore[operator]
    planner = MusicPlanner()
    brief = planner.plan_for_edit(db, project_id, edit_id)

    if style_override:
        brief.overall_mood = style_override.lower()
        from clipcannon.audio.music_planner import (
            _build_ace_step_prompt,
            _map_mood_to_music,
        )
        preset, key = _map_mood_to_music(brief.overall_mood)
        brief.suggested_preset = preset
        brief.suggested_key = key
        brief.ace_step_prompt = _build_ace_step_prompt(
            brief.overall_mood, brief.energy_level,
            brief.suggested_tempo_bpm, brief.suggested_key,
        )

    duration_s = (
        duration_override_s
        if duration_override_s is not None
        else brief.edit_duration_ms / 1000.0
    )
    duration_s = max(1.0, min(duration_s, 300.0))

    asset_id = f"audio_{secrets.token_hex(6)}"
    audio_dir: Path = audio_dir_fn(project_id)  # type: ignore[operator]

    if tier == "ai":
        return await _auto_music_ai(
            project_id, edit_id, asset_id, audio_dir, brief,
            duration_s, start_time, store_asset_fn,
        )
    if tier == "midi":
        return await _auto_music_midi(
            project_id, edit_id, asset_id, audio_dir, brief,
            duration_s, start_time, store_asset_fn,
        )

    # tier == "auto": try AI first, then MIDI
    try:
        return await _auto_music_ai(
            project_id, edit_id, asset_id, audio_dir, brief,
            duration_s, start_time, store_asset_fn,
        )
    except ImportError:
        logger.info("ACE-Step unavailable; falling back to MIDI")
        return await _auto_music_midi(
            project_id, edit_id, asset_id, audio_dir, brief,
            duration_s, start_time, store_asset_fn,
        )


async def _auto_music_ai(
    project_id: str, edit_id: str, asset_id: str, audio_dir: Path,
    brief: object, duration_s: float, start_time: float,
    store_asset_fn: object,
) -> dict[str, object]:
    """Generate music via ACE-Step for auto_music."""
    from clipcannon.audio.music_gen import generate_music
    from clipcannon.audio.music_planner import MusicBrief

    b: MusicBrief = brief  # type: ignore[assignment]
    output_path = audio_dir / f"{asset_id}_auto_music.wav"

    result = await generate_music(
        prompt=b.ace_step_prompt, duration_s=duration_s,
        output_path=output_path,
    )

    store_asset_fn(  # type: ignore[operator]
        project_id=project_id, edit_id=edit_id, asset_id=asset_id,
        asset_type="music", file_path=str(result.file_path),
        duration_ms=result.duration_ms, sample_rate=result.sample_rate,
        model_used=result.model_used,
        generation_params={
            "auto_music": True, "mood": b.overall_mood,
            "energy": b.energy_level, "prompt": b.ace_step_prompt,
            "tier": "ai",
        },
        seed=result.seed, volume_db=-18.0,
    )

    return {
        "audio_asset_id": asset_id,
        "file_path": str(result.file_path),
        "duration_ms": result.duration_ms,
        "detected_mood": b.overall_mood,
        "suggested_tempo": b.suggested_tempo_bpm,
        "generation_method": "ace-step",
        "elapsed_s": round(time.monotonic() - start_time, 2),
    }


async def _auto_music_midi(
    project_id: str, edit_id: str, asset_id: str, audio_dir: Path,
    brief: object, duration_s: float, start_time: float,
    store_asset_fn: object,
) -> dict[str, object]:
    """Generate music via MIDI composition for auto_music."""
    from clipcannon.audio.midi_compose import compose_midi
    from clipcannon.audio.music_planner import MusicBrief

    b: MusicBrief = brief  # type: ignore[assignment]
    midi_path = audio_dir / f"{asset_id}_auto_music.mid"
    wav_path = audio_dir / f"{asset_id}_auto_music.wav"

    midi_result = compose_midi(
        preset=b.suggested_preset, duration_s=duration_s,
        output_path=midi_path, tempo_bpm=b.suggested_tempo_bpm,
        key=b.suggested_key,
    )

    out_path, model_used = midi_path, "midiutil"
    try:
        from clipcannon.audio.midi_render import render_midi_to_wav
        await render_midi_to_wav(midi_path=midi_path, output_path=wav_path)
        out_path, model_used = wav_path, "midiutil+fluidsynth"
    except ImportError:
        logger.warning("FluidSynth not available; storing MIDI only")
    except Exception as exc:
        logger.warning("MIDI render failed, storing MIDI only: %s", exc)

    store_asset_fn(  # type: ignore[operator]
        project_id=project_id, edit_id=edit_id, asset_id=asset_id,
        asset_type="midi", file_path=str(out_path),
        duration_ms=midi_result.duration_ms, sample_rate=44100,
        model_used=model_used,
        generation_params={
            "auto_music": True, "mood": b.overall_mood,
            "energy": b.energy_level, "preset": b.suggested_preset,
            "tier": "midi",
        },
        seed=None, volume_db=0.0,
    )

    return {
        "audio_asset_id": asset_id,
        "file_path": str(out_path),
        "duration_ms": midi_result.duration_ms,
        "detected_mood": b.overall_mood,
        "suggested_tempo": b.suggested_tempo_bpm,
        "generation_method": "midi",
        "elapsed_s": round(time.monotonic() - start_time, 2),
    }


async def clipcannon_compose_music(
    project_id: str,
    edit_id: str,
    description: str,
    duration_s: float,
    tempo_bpm: int | None = None,
    key: str | None = None,
    energy: str | None = None,
    *,
    validate_project: object,
    validate_edit: object,
    audio_dir_fn: object,
    store_asset_fn: object,
    error_fn: object,
) -> dict[str, object]:
    """Compose music from a natural language description via MIDI."""
    start_time = time.monotonic()

    err = validate_project(project_id)  # type: ignore[operator]
    if err is not None:
        return err
    err = validate_edit(project_id, edit_id)  # type: ignore[operator]
    if err is not None:
        return err

    if duration_s <= 0 or duration_s > 600:
        return error_fn(  # type: ignore[operator]
            "INVALID_PARAMETER",
            "duration_s must be between 0 and 600 seconds",
            {"duration_s": duration_s},
        )

    try:
        from clipcannon.audio.midi_ai import plan_midi_from_keywords
    except ImportError as exc:
        return error_fn("DEPENDENCY_MISSING", str(exc))  # type: ignore[operator]

    plan = plan_midi_from_keywords(description)
    if tempo_bpm is not None:
        plan.tempo_bpm = tempo_bpm
    if key is not None:
        plan.key = key
    if energy is not None and energy in ("low", "medium", "high"):
        plan.energy = energy

    asset_id = f"audio_{secrets.token_hex(6)}"
    audio_dir: Path = audio_dir_fn(project_id)  # type: ignore[operator]
    midi_path = audio_dir / f"{asset_id}_composed.mid"
    wav_path = audio_dir / f"{asset_id}_composed.wav"

    try:
        from clipcannon.audio.midi_compose import compose_midi

        midi_result = compose_midi(
            preset=plan.preset, duration_s=duration_s,
            output_path=midi_path, tempo_bpm=plan.tempo_bpm,
            key=plan.key,
        )
    except ImportError as exc:
        return error_fn("DEPENDENCY_MISSING", str(exc), {"dependency": "MIDIUtil"})  # type: ignore[operator]
    except ValueError as exc:
        return error_fn("INVALID_PARAMETER", str(exc), {"preset": plan.preset})  # type: ignore[operator]
    except Exception as exc:
        logger.exception("MIDI composition failed for compose_music")
        return error_fn("GENERATION_FAILED", f"MIDI composition failed: {exc}")  # type: ignore[operator]

    out_path, model_used = midi_path, "midiutil"
    try:
        from clipcannon.audio.midi_render import render_midi_to_wav
        await render_midi_to_wav(midi_path=midi_path, output_path=wav_path)
        out_path, model_used = wav_path, "midiutil+fluidsynth"
    except ImportError:
        logger.warning("FluidSynth not available; storing MIDI only")
    except Exception as exc:
        logger.exception("MIDI rendering failed for compose_music")
        return error_fn("RENDER_FAILED", f"MIDI rendering failed: {exc}")  # type: ignore[operator]

    store_asset_fn(  # type: ignore[operator]
        project_id=project_id, edit_id=edit_id, asset_id=asset_id,
        asset_type="midi", file_path=str(out_path),
        duration_ms=midi_result.duration_ms, sample_rate=44100,
        model_used=model_used,
        generation_params={
            "description": description, "preset": plan.preset,
            "tempo_bpm": plan.tempo_bpm, "key": plan.key,
            "energy": plan.energy, "duration_s": duration_s,
        },
        seed=None, volume_db=0.0,
    )

    return {
        "audio_asset_id": asset_id,
        "file_path": str(out_path),
        "duration_ms": midi_result.duration_ms,
        "preset": plan.preset,
        "tempo_bpm": plan.tempo_bpm,
        "key": plan.key,
        "elapsed_s": round(time.monotonic() - start_time, 2),
    }
