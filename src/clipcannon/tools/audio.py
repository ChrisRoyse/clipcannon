"""Audio generation MCP tools for ClipCannon."""

from __future__ import annotations

import json
import logging
import secrets
import time
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_one
from clipcannon.exceptions import ClipCannonError
from clipcannon.tools.audio_defs import AUDIO_TOOL_DEFINITIONS

logger = logging.getLogger(__name__)

__all__ = ["AUDIO_TOOL_DEFINITIONS", "dispatch_audio_tool"]


def _error(
    code: str, message: str, details: dict[str, object] | None = None
) -> dict[str, object]:
    """Build standardized error response dict."""
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _projects_dir() -> Path:
    """Resolve projects base directory from config or default."""
    try:
        config = ClipCannonConfig.load()
        return config.resolve_path("directories.projects")
    except ClipCannonError:
        return Path.home() / ".clipcannon" / "projects"


def _db_path(project_id: str) -> Path:
    """Build database path for a project."""
    return _projects_dir() / project_id / "analysis.db"


def _project_dir(project_id: str) -> Path:
    """Build project directory path."""
    return _projects_dir() / project_id


def _audio_dir(project_id: str) -> Path:
    """Build audio assets directory, creating it if needed."""
    audio_path = _project_dir(project_id) / "audio"
    audio_path.mkdir(parents=True, exist_ok=True)
    return audio_path


def _validate_project(project_id: str) -> dict[str, object] | None:
    """Return error dict if project does not exist, else None."""
    db = _db_path(project_id)
    if not db.exists():
        return _error("PROJECT_NOT_FOUND", f"Project not found: {project_id}")
    return None


def _validate_edit(project_id: str, edit_id: str) -> dict[str, object] | None:
    """Return error dict if edit does not exist within project, else None."""
    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            "SELECT edit_id FROM edits WHERE edit_id = ? AND project_id = ?",
            (edit_id, project_id),
        )
    finally:
        conn.close()
    if row is None:
        return _error(
            "EDIT_NOT_FOUND",
            f"Edit not found: {edit_id} in project {project_id}",
        )
    return None


def _store_audio_asset(
    project_id: str, edit_id: str, asset_id: str, asset_type: str,
    file_path: str, duration_ms: int, sample_rate: int,
    model_used: str | None, generation_params: dict[str, object],
    seed: int | None, volume_db: float,
) -> None:
    """Insert an audio asset record into the database."""
    db = _db_path(project_id)
    conn = get_connection(db, enable_vec=False, dict_rows=True)
    try:
        execute(
            conn,
            """INSERT INTO audio_assets (
                asset_id, edit_id, project_id, type, file_path,
                duration_ms, sample_rate, model_used, generation_params,
                seed, volume_db
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                asset_id, edit_id, project_id, asset_type, file_path,
                duration_ms, sample_rate, model_used,
                json.dumps(generation_params), seed, volume_db,
            ),
        )
        conn.commit()
    finally:
        conn.close()


async def clipcannon_generate_music(
    project_id: str,
    edit_id: str,
    prompt: str,
    duration_s: float,
    seed: int | None = None,
    volume_db: float = -18.0,
    model: str = "ace-step",
) -> dict[str, object]:
    """Generate AI music from a text prompt, store as audio asset.

    Args:
        model: "ace-step" (default) or "musicgen". No fallback --
            if the specified model is unavailable, an error is returned.
    """
    start_time = time.monotonic()

    err = _validate_project(project_id)
    if err is not None:
        return err
    err = _validate_edit(project_id, edit_id)
    if err is not None:
        return err

    if model not in ("ace-step", "musicgen"):
        return _error(
            "INVALID_PARAMETER",
            f"Unknown model: {model}. Must be 'ace-step' or 'musicgen'.",
            {"model": model},
        )

    if duration_s <= 0 or duration_s > 300:
        return _error(
            "INVALID_PARAMETER",
            "duration_s must be between 0 and 300 seconds",
            {"duration_s": duration_s},
        )

    asset_id = f"audio_{secrets.token_hex(6)}"
    audio_dir = _audio_dir(project_id)
    output_path = audio_dir / f"{asset_id}_music.wav"

    try:
        if model == "musicgen":
            from clipcannon.audio.musicgen import generate_music_musicgen

            result = await generate_music_musicgen(
                prompt=prompt,
                duration_s=duration_s,
                output_path=output_path,
                seed=seed,
            )
        else:
            from clipcannon.audio.music_gen import generate_music

            result = await generate_music(
                prompt=prompt,
                duration_s=duration_s,
                output_path=output_path,
                seed=seed,
            )
    except ImportError as exc:
        dep = "audiocraft" if model == "musicgen" else "ace-step"
        return _error(
            "DEPENDENCY_MISSING", str(exc), {"dependency": dep},
        )
    except Exception as exc:
        logger.exception("Music generation failed (model=%s)", model)
        return _error(
            "GENERATION_FAILED",
            f"Music generation failed ({model}): {exc}",
            {"error": str(exc), "model": model},
        )

    _store_audio_asset(
        project_id=project_id, edit_id=edit_id, asset_id=asset_id,
        asset_type="music", file_path=str(result.file_path),
        duration_ms=result.duration_ms, sample_rate=result.sample_rate,
        model_used=result.model_used,
        generation_params={
            "prompt": prompt, "duration_s": duration_s,
            "model": model,
        },
        seed=result.seed, volume_db=volume_db,
    )

    elapsed = time.monotonic() - start_time
    return {
        "audio_asset_id": asset_id,
        "file_path": str(result.file_path),
        "duration_ms": result.duration_ms,
        "seed": result.seed,
        "model_used": result.model_used,
        "elapsed_s": round(elapsed, 2),
    }


async def clipcannon_compose_midi(
    project_id: str,
    edit_id: str,
    preset: str,
    duration_s: float,
    tempo_bpm: int | None = None,
    key: str | None = None,
) -> dict[str, object]:
    """Compose MIDI from preset, render to WAV, store as audio asset."""
    start_time = time.monotonic()

    err = _validate_project(project_id)
    if err is not None:
        return err
    err = _validate_edit(project_id, edit_id)
    if err is not None:
        return err
    if duration_s <= 0 or duration_s > 600:
        return _error("INVALID_PARAMETER", "duration_s must be between 0 and 600 seconds")
    asset_id = f"audio_{secrets.token_hex(6)}"
    audio_dir = _audio_dir(project_id)
    midi_path = audio_dir / f"{asset_id}_composition.mid"
    wav_path = audio_dir / f"{asset_id}_composition.wav"

    try:
        from clipcannon.audio.midi_compose import compose_midi

        midi_result = compose_midi(
            preset=preset,
            duration_s=duration_s,
            output_path=midi_path,
            tempo_bpm=tempo_bpm,
            key=key,
        )
    except ImportError as exc:
        return _error(
            "DEPENDENCY_MISSING",
            str(exc),
            {"dependency": "MIDIUtil"},
        )
    except ValueError as exc:
        return _error(
            "INVALID_PARAMETER",
            str(exc),
            {"preset": preset},
        )
    except Exception as exc:
        logger.exception("MIDI composition failed")
        return _error(
            "GENERATION_FAILED",
            f"MIDI composition failed: {exc}",
            {"error": str(exc)},
        )

    gen_params: dict[str, object] = {
        "preset": preset, "duration_s": duration_s,
        "tempo_bpm": midi_result.tempo_bpm, "key": midi_result.key,
    }
    wav_rendered = False
    try:
        from clipcannon.audio.midi_render import render_midi_to_wav

        await render_midi_to_wav(midi_path=midi_path, output_path=wav_path)
        wav_rendered = True
    except ImportError as exc:
        logger.warning("FluidSynth not available, storing MIDI only: %s", exc)
    except Exception as exc:
        logger.exception("MIDI rendering failed")
        return _error("RENDER_FAILED", f"MIDI rendering failed: {exc}")

    out_path = wav_path if wav_rendered else midi_path
    model = "midiutil+fluidsynth" if wav_rendered else "midiutil"
    _store_audio_asset(
        project_id=project_id, edit_id=edit_id, asset_id=asset_id,
        asset_type="midi", file_path=str(out_path),
        duration_ms=midi_result.duration_ms, sample_rate=44100,
        model_used=model, generation_params=gen_params,
        seed=None, volume_db=0.0,
    )

    elapsed = time.monotonic() - start_time
    result: dict[str, object] = {
        "audio_asset_id": asset_id,
        "file_path": str(out_path),
        "midi_path": str(midi_path),
        "duration_ms": midi_result.duration_ms,
        "preset": midi_result.preset,
        "tempo_bpm": midi_result.tempo_bpm,
        "key": midi_result.key,
        "elapsed_s": round(elapsed, 2),
    }
    if not wav_rendered:
        result["note"] = "FluidSynth not available; MIDI only"
    return result


async def clipcannon_generate_sfx(
    project_id: str,
    edit_id: str,
    sfx_type: str,
    duration_ms: int = 500,
    params: dict[str, object] | None = None,
) -> dict[str, object]:
    """Generate a DSP sound effect, store as audio asset."""
    start_time = time.monotonic()

    err = _validate_project(project_id)
    if err is not None:
        return err
    err = _validate_edit(project_id, edit_id)
    if err is not None:
        return err
    if duration_ms <= 0 or duration_ms > 30000:
        return _error(
            "INVALID_PARAMETER",
            "duration_ms must be between 1 and 30000",
            {"duration_ms": duration_ms},
        )

    asset_id = f"audio_{secrets.token_hex(6)}"
    audio_dir = _audio_dir(project_id)
    output_path = audio_dir / f"{asset_id}_{sfx_type}.wav"

    try:
        from clipcannon.audio.sfx import generate_sfx

        result = generate_sfx(
            sfx_type=sfx_type,
            output_path=output_path,
            duration_ms=duration_ms,
            params=params,
        )
    except ValueError as exc:
        return _error(
            "INVALID_PARAMETER",
            str(exc),
            {"sfx_type": sfx_type},
        )
    except Exception as exc:
        logger.exception("SFX generation failed")
        return _error(
            "GENERATION_FAILED",
            f"SFX generation failed: {exc}",
            {"error": str(exc)},
        )

    _store_audio_asset(
        project_id=project_id, edit_id=edit_id, asset_id=asset_id,
        asset_type="sfx", file_path=str(result.file_path),
        duration_ms=result.duration_ms, sample_rate=result.sample_rate,
        model_used="dsp",
        generation_params={"sfx_type": sfx_type, "duration_ms": duration_ms, "params": params or {}},
        seed=None, volume_db=0.0,
    )
    elapsed = time.monotonic() - start_time
    return {
        "audio_asset_id": asset_id,
        "file_path": str(result.file_path),
        "duration_ms": result.duration_ms,
        "sfx_type": result.sfx_type,
        "elapsed_s": round(elapsed, 2),
    }


async def clipcannon_auto_music(
    project_id: str, edit_id: str,
    style_override: str | None = None,
    tier: str = "auto",
    duration_override_s: float | None = None,
) -> dict[str, object]:
    """Analyze video edit and generate matching background music."""
    from clipcannon.tools.audio_smart import (
        clipcannon_auto_music as _impl,
    )
    return await _impl(
        project_id, edit_id, style_override, tier, duration_override_s,
        validate_project=_validate_project, validate_edit=_validate_edit,
        db_path_fn=_db_path, audio_dir_fn=_audio_dir,
        store_asset_fn=_store_audio_asset, error_fn=_error,
    )


async def clipcannon_compose_music(
    project_id: str, edit_id: str,
    description: str, duration_s: float,
    tempo_bpm: int | None = None,
    key: str | None = None,
    energy: str | None = None,
) -> dict[str, object]:
    """Compose music from a natural language description via MIDI."""
    from clipcannon.tools.audio_smart import (
        clipcannon_compose_music as _impl,
    )
    return await _impl(
        project_id, edit_id, description, duration_s,
        tempo_bpm, key, energy,
        validate_project=_validate_project, validate_edit=_validate_edit,
        audio_dir_fn=_audio_dir, store_asset_fn=_store_audio_asset,
        error_fn=_error,
    )


async def clipcannon_audio_cleanup(
    project_id: str,
    edit_id: str,
    operations: list[str],
    hum_frequency: int = 50,
) -> dict[str, object]:
    """Clean up audio with FFmpeg filters. Delegates to audio_cleanup module."""
    from clipcannon.tools.audio_cleanup import run_audio_cleanup

    return await run_audio_cleanup(
        project_id=project_id, edit_id=edit_id,
        operations=operations, hum_frequency=hum_frequency,
        validate_project=_validate_project, validate_edit=_validate_edit,
        project_dir_fn=_project_dir, store_asset_fn=_store_audio_asset,
        error_fn=_error,
    )


async def dispatch_audio_tool(
    name: str, arguments: dict[str, object],
) -> dict[str, object]:
    """Dispatch an audio tool call by name."""
    if name == "clipcannon_generate_music":
        seed_raw = arguments.get("seed")
        return await clipcannon_generate_music(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
            prompt=str(arguments["prompt"]),
            duration_s=float(arguments["duration_s"]),  # type: ignore[arg-type]
            seed=int(seed_raw) if seed_raw is not None else None,  # type: ignore[arg-type]
            volume_db=float(arguments.get("volume_db", -18)),  # type: ignore[arg-type]
            model=str(arguments.get("model", "ace-step")),
        )
    if name == "clipcannon_compose_midi":
        tempo_raw = arguments.get("tempo_bpm")
        key_raw = arguments.get("key")
        return await clipcannon_compose_midi(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
            preset=str(arguments["preset"]),
            duration_s=float(arguments["duration_s"]),  # type: ignore[arg-type]
            tempo_bpm=int(tempo_raw) if tempo_raw is not None else None,  # type: ignore[arg-type]
            key=str(key_raw) if key_raw is not None else None,
        )
    if name == "clipcannon_generate_sfx":
        return await clipcannon_generate_sfx(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
            sfx_type=str(arguments["sfx_type"]),
            duration_ms=int(arguments.get("duration_ms", 500)),  # type: ignore[arg-type]
            params=arguments.get("params"),  # type: ignore[arg-type]
        )
    if name == "clipcannon_auto_music":
        dur_raw = arguments.get("duration_override_s")
        return await clipcannon_auto_music(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
            style_override=str(arguments["style_override"]) if arguments.get("style_override") else None,
            tier=str(arguments.get("tier", "auto")),
            duration_override_s=float(dur_raw) if dur_raw is not None else None,  # type: ignore[arg-type]
        )
    if name == "clipcannon_compose_music":
        tempo_raw = arguments.get("tempo_bpm")
        key_raw = arguments.get("key")
        energy_raw = arguments.get("energy")
        return await clipcannon_compose_music(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
            description=str(arguments["description"]),
            duration_s=float(arguments["duration_s"]),  # type: ignore[arg-type]
            tempo_bpm=int(tempo_raw) if tempo_raw is not None else None,  # type: ignore[arg-type]
            key=str(key_raw) if key_raw is not None else None,
            energy=str(energy_raw) if energy_raw is not None else None,
        )
    if name == "clipcannon_audio_cleanup":
        return await clipcannon_audio_cleanup(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
            operations=list(arguments["operations"]),  # type: ignore[arg-type]
            hum_frequency=int(arguments.get("hum_frequency", 50)),  # type: ignore[arg-type]
        )
    return _error("INTERNAL_ERROR", f"Unknown audio tool: {name}")
