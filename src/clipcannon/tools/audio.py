"""Audio generation MCP tools for ClipCannon.

Provides tools for generating AI music, composing MIDI tracks,
and creating programmatic sound effects.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from pathlib import Path

from mcp.types import Tool

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_one
from clipcannon.exceptions import ClipCannonError

logger = logging.getLogger(__name__)


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


async def _extract_audio_from_source(
    proj_dir: Path, project_id: str
) -> Path | None:
    """Extract audio from source video when stems are missing.

    This is a self-healing fallback: if disk_cleanup removed stems,
    we re-extract audio directly from the source video using ffmpeg.

    Args:
        proj_dir: Project directory path.
        project_id: Project identifier (for logging).

    Returns:
        Path to extracted audio WAV, or None if extraction fails.
    """
    import asyncio

    source_dir = proj_dir / "source"
    if not source_dir.exists():
        return None
    videos = list(source_dir.glob("*.mp4")) + list(source_dir.glob("*.mkv"))
    if not videos:
        return None

    stems_dir = proj_dir / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)
    output = stems_dir / "audio_original.wav"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(videos[0]),
        "-vn", "-acodec", "pcm_s16le",
        str(output),
    ]
    logger.info(
        "Stems missing for %s — extracting audio from source video", project_id
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(
                "Audio extraction failed for %s: %s",
                project_id, stderr.decode()[-500:],
            )
            return None
    except FileNotFoundError:
        logger.error("ffmpeg not found — cannot extract audio")
        return None

    if output.exists() and output.stat().st_size > 0:
        logger.info("Audio extracted to %s (%d bytes)", output, output.stat().st_size)
        return output
    return None


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
) -> dict[str, object]:
    """Generate AI music from a text prompt, store as audio asset."""
    start_time = time.monotonic()

    # Validate project and edit
    err = _validate_project(project_id)
    if err is not None:
        return err
    err = _validate_edit(project_id, edit_id)
    if err is not None:
        return err

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
        from clipcannon.audio.music_gen import generate_music

        result = await generate_music(
            prompt=prompt,
            duration_s=duration_s,
            output_path=output_path,
            seed=seed,
        )
    except ImportError as exc:
        return _error(
            "DEPENDENCY_MISSING",
            str(exc),
            {"dependency": "ace-step"},
        )
    except Exception as exc:
        logger.exception("Music generation failed")
        return _error(
            "GENERATION_FAILED",
            f"Music generation failed: {exc}",
            {"error": str(exc)},
        )

    # Store in database
    _store_audio_asset(
        project_id=project_id,
        edit_id=edit_id,
        asset_id=asset_id,
        asset_type="music",
        file_path=str(result.file_path),
        duration_ms=result.duration_ms,
        sample_rate=result.sample_rate,
        model_used=result.model_used,
        generation_params={
            "prompt": prompt,
            "duration_s": duration_s,
            "guidance_scale": 15.0,
        },
        seed=result.seed,
        volume_db=volume_db,
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

    # Validate project and edit
    err = _validate_project(project_id)
    if err is not None:
        return err
    err = _validate_edit(project_id, edit_id)
    if err is not None:
        return err

    if duration_s <= 0 or duration_s > 600:
        return _error(
            "INVALID_PARAMETER",
            "duration_s must be between 0 and 600 seconds",
            {"duration_s": duration_s},
        )

    asset_id = f"audio_{secrets.token_hex(6)}"
    audio_dir = _audio_dir(project_id)
    midi_path = audio_dir / f"{asset_id}_composition.mid"
    wav_path = audio_dir / f"{asset_id}_composition.wav"

    # Step 1: Compose MIDI
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

    # Step 2: Render MIDI to WAV
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

    # Store in database
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

    # Validate project and edit
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

    # Store in database
    _store_audio_asset(
        project_id=project_id,
        edit_id=edit_id,
        asset_id=asset_id,
        asset_type="sfx",
        file_path=str(result.file_path),
        duration_ms=result.duration_ms,
        sample_rate=result.sample_rate,
        model_used="dsp",
        generation_params={
            "sfx_type": sfx_type,
            "duration_ms": duration_ms,
            "params": params or {},
        },
        seed=None,
        volume_db=0.0,
    )

    elapsed = time.monotonic() - start_time

    return {
        "audio_asset_id": asset_id,
        "file_path": str(result.file_path),
        "duration_ms": result.duration_ms,
        "sfx_type": result.sfx_type,
        "elapsed_s": round(elapsed, 2),
    }


_PID = {"type": "string", "description": "Project identifier"}
_EID = {"type": "string", "description": "Edit identifier to attach audio to"}

AUDIO_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_generate_music",
        description=(
            "Generate original AI background music from a text prompt "
            "using ACE-Step v1.5. Requires GPU with 4+ GB VRAM."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": _PID,
                "edit_id": _EID,
                "prompt": {"type": "string", "description": "Music description"},
                "duration_s": {"type": "number", "description": "Duration in seconds"},
                "seed": {"type": "integer", "description": "Seed for reproducibility"},
                "volume_db": {"type": "number", "description": "Volume in dB", "default": -18},
            },
            "required": ["project_id", "edit_id", "prompt", "duration_s"],
        },
    ),
    Tool(
        name="clipcannon_compose_midi",
        description=(
            "Compose a MIDI track from preset and render to WAV. "
            "CPU-only. Presets: ambient_pad, upbeat_pop, corporate, "
            "dramatic, minimal_piano, intro_jingle."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": _PID,
                "edit_id": _EID,
                "preset": {
                    "type": "string", "description": "Composition preset",
                    "enum": [
                        "ambient_pad", "upbeat_pop", "corporate",
                        "dramatic", "minimal_piano", "intro_jingle",
                    ],
                },
                "duration_s": {"type": "number", "description": "Duration in seconds"},
                "tempo_bpm": {"type": "integer", "description": "Override tempo in BPM"},
                "key": {"type": "string", "description": "Override musical key"},
            },
            "required": ["project_id", "edit_id", "preset", "duration_s"],
        },
    ),
    Tool(
        name="clipcannon_generate_sfx",
        description=(
            "Generate a DSP sound effect. CPU-only, instant. Types: "
            "whoosh, riser, downer, impact, chime, tick, bass_drop, shimmer, stinger."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": _PID,
                "edit_id": _EID,
                "sfx_type": {
                    "type": "string", "description": "Sound effect type",
                    "enum": [
                        "whoosh", "riser", "downer", "impact", "chime",
                        "tick", "bass_drop", "shimmer", "stinger",
                    ],
                },
                "duration_ms": {
                    "type": "integer", "description": "Duration in ms",
                    "default": 500,
                },
                "params": {"type": "object", "description": "Effect-specific params"},
            },
            "required": ["project_id", "edit_id", "sfx_type"],
        },
    ),
    Tool(
        name="clipcannon_audio_cleanup",
        description=(
            "Clean up audio by removing noise, hum, sibilance, or normalizing loudness. "
            "Operations: noise_reduction (gentle denoising), de_hum (remove 50/60Hz hum), "
            "de_ess (reduce sibilance), normalize_loudness (EBU R128 normalization). "
            "Creates cleaned audio file stored as audio asset."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": _PID,
                "edit_id": _EID,
                "operations": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "noise_reduction", "de_hum",
                            "de_ess", "normalize_loudness",
                        ],
                    },
                    "minItems": 1,
                    "description": "Cleanup operations to apply",
                },
                "hum_frequency": {
                    "type": "integer",
                    "default": 50,
                    "description": "Hum frequency: 50 (EU) or 60 (US) Hz",
                },
            },
            "required": ["project_id", "edit_id", "operations"],
        },
    ),
]


async def clipcannon_audio_cleanup(
    project_id: str,
    edit_id: str,
    operations: list[str],
    hum_frequency: int = 50,
) -> dict[str, object]:
    """Clean up audio with FFmpeg filters."""
    from clipcannon.audio.cleanup import SUPPORTED_CLEANUP_OPS, cleanup_audio

    err = _validate_project(project_id)
    if err is not None:
        return err
    err = _validate_edit(project_id, edit_id)
    if err is not None:
        return err

    # Validate operations
    invalid = [op for op in operations if op not in SUPPORTED_CLEANUP_OPS]
    if invalid:
        return _error("INVALID_PARAMETER", f"Unknown operations: {invalid}")

    # Find source audio
    proj_dir = _project_dir(project_id)
    audio_dir = proj_dir / "edits" / edit_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Use vocal stem if available, otherwise extracted audio
    source_audio = proj_dir / "stems" / "vocals.wav"
    if not source_audio.exists():
        source_audio = proj_dir / "stems" / "audio_original.wav"
    if not source_audio.exists():
        source_audio = proj_dir / "stems" / "audio_16k.wav"
    if not source_audio.exists():
        # Try any WAV in project (stems/ first, then root)
        wavs = list((proj_dir / "stems").glob("*.wav")) if (proj_dir / "stems").exists() else []
        if not wavs:
            wavs = list(proj_dir.glob("*.wav"))
        if wavs:
            source_audio = wavs[0]
        else:
            # Self-heal: extract audio from source video on the fly
            source_audio = await _extract_audio_from_source(proj_dir, project_id)
            if source_audio is None:
                return _error(
                    "AUDIO_NOT_FOUND",
                    "No audio stems found and source video extraction failed. "
                    "Run ingest again or check source video has audio.",
                )

    output_path = audio_dir / f"cleaned_{secrets.token_hex(4)}.wav"

    start = time.monotonic()
    try:
        result = await cleanup_audio(
            input_path=source_audio,
            output_path=output_path,
            operations=operations,
            hum_frequency=hum_frequency,
        )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        return _error("CLEANUP_FAILED", str(exc))

    elapsed_ms = int((time.monotonic() - start) * 1000)

    # Store as audio asset
    _store_audio_asset(
        project_id=project_id,
        edit_id=edit_id,
        asset_id=result.asset_id,
        asset_type="cleaned",
        file_path=str(result.file_path),
        duration_ms=result.duration_ms,
        sample_rate=result.sample_rate,
        model_used="ffmpeg",
        generation_params={
            "operations": operations,
            "hum_frequency": hum_frequency,
        },
        seed=None,
        volume_db=0.0,
    )

    return {
        "asset_id": result.asset_id,
        "file_path": str(result.file_path),
        "duration_ms": result.duration_ms,
        "operations_applied": result.operations_applied,
        "elapsed_ms": elapsed_ms,
    }


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
    if name == "clipcannon_audio_cleanup":
        return await clipcannon_audio_cleanup(
            project_id=str(arguments["project_id"]),
            edit_id=str(arguments["edit_id"]),
            operations=list(arguments["operations"]),  # type: ignore[arg-type]
            hum_frequency=int(arguments.get("hum_frequency", 50)),  # type: ignore[arg-type]
        )
    return _error("INTERNAL_ERROR", f"Unknown audio tool: {name}")
