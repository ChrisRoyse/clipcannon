"""Voice MCP tools: shared helpers, profile resolution, data prep and profiles."""

from __future__ import annotations

import logging
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
    """Resolve projects base directory from config or default."""
    try:
        config = ClipCannonConfig.load()
        return config.resolve_path("directories.projects")
    except ClipCannonError:
        return Path.home() / ".clipcannon" / "projects"


def _voice_db_path() -> Path:
    """Resolve the central voice profiles database path."""
    return Path.home() / ".clipcannon" / "voice_profiles.db"


def resolve_voice_profile(voice_name: str) -> dict[str, object]:
    """Load a voice profile and extract synthesis parameters.

    Shared by ``_handle_speak`` and ``generate_video`` to avoid
    duplicating the profile-loading + embedding-extraction logic.

    Args:
        voice_name: Name of the voice profile to look up.

    Returns:
        Dict with ``model_path``, ``verification_threshold``, and
        ``reference_embedding`` (numpy array or None).
        On failure returns an ``{"error": ...}`` dict instead.
    """
    import numpy as np

    from clipcannon.voice.profiles import get_voice_profile

    db_path = _voice_db_path()
    profile = get_voice_profile(db_path, voice_name)
    if profile is None:
        return _error("PROFILE_NOT_FOUND", f"Voice profile not found: {voice_name}")

    verification_threshold = float(profile.get("verification_threshold", 0.80))

    reference_embedding = None
    if profile.get("reference_embedding"):
        reference_embedding = np.frombuffer(
            profile["reference_embedding"], dtype=np.float32,
        ).copy()
        # Detect stale 192-dim SpeechBrain embeddings (now need 2048-dim)
        if reference_embedding.shape[0] != 2048:
            return _error(
                "EMBEDDING_OUTDATED",
                f"Voice profile '{voice_name}' has a {reference_embedding.shape[0]}-dim "
                f"embedding from the old speaker encoder. Rebuild the fingerprint: "
                f"run build_reference_embedding() with the voice data clips, then "
                f"update the profile's reference_embedding.",
            )

    # Auto-discover a reference audio clip for style transfer.
    # The fine-tuned model produces much better results when given
    # a reference clip of the target speaker at inference time.
    reference_audio = None
    training_projects = profile.get("training_projects", "[]")
    import json as _json
    try:
        proj_ids = _json.loads(training_projects) if isinstance(training_projects, str) else []
    except Exception:
        proj_ids = []

    # Look for vocals.wav in any training project
    if proj_ids:
        projects_dir = _projects_dir()
        for pid in proj_ids:
            vocals = projects_dir / pid / "stems" / "vocals.wav"
            if vocals.exists():
                reference_audio = str(vocals)
                break

    # Fallback: check voice_data directory for training clips
    if reference_audio is None:
        from pathlib import Path as _Path
        voice_data = _Path.home() / ".clipcannon" / "voice_data" / voice_name / "wavs"
        if voice_data.exists():
            clips = sorted(voice_data.glob("*.wav"))
            if clips:
                reference_audio = str(clips[0])

    # Collect ALL available reference clips for optimized synthesis
    all_reference_clips: list[str] = []
    from pathlib import Path as _Path
    voice_data = _Path.home() / ".clipcannon" / "voice_data" / voice_name / "wavs"
    if voice_data.exists():
        all_reference_clips = [str(c) for c in sorted(voice_data.glob("*.wav"))]

    return {
        "verification_threshold": verification_threshold,
        "reference_embedding": reference_embedding,
        "reference_audio": reference_audio,
        "all_reference_clips": all_reference_clips,
    }


async def _handle_prepare_voice_data(
    arguments: dict[str, object],
) -> dict[str, object]:
    """Handle clipcannon_prepare_voice_data tool call.

    Args:
        arguments: Tool arguments from MCP.

    Returns:
        Result dictionary.
    """
    from clipcannon.voice.data_prep import prepare_voice_training_data

    project_ids = list(arguments["project_ids"])  # type: ignore[arg-type]
    speaker_label = str(arguments["speaker_label"])

    output_dir_raw = arguments.get("output_dir")
    if output_dir_raw:
        output_dir = Path(str(output_dir_raw))
    else:
        output_dir = (
            Path.home() / ".clipcannon" / "voice_data" / speaker_label
        )

    min_clip_ms = int(arguments.get("min_clip_duration_ms", 1000))  # type: ignore[arg-type]
    max_clip_ms = int(arguments.get("max_clip_duration_ms", 12000))  # type: ignore[arg-type]
    projects_base = _projects_dir()

    start_time = time.monotonic()

    try:
        result = await prepare_voice_training_data(
            project_ids=project_ids,
            speaker_label=speaker_label,
            output_dir=output_dir,
            projects_base=projects_base,
            min_clip_duration_ms=min_clip_ms,
            max_clip_duration_ms=max_clip_ms,
        )
    except FileNotFoundError as exc:
        return _error("FILE_NOT_FOUND", str(exc))
    except RuntimeError as exc:
        return _error("NO_CLIPS_PRODUCED", str(exc))
    except Exception as exc:
        logger.exception("Voice data preparation failed")
        return _error(
            "PREPARATION_FAILED",
            f"Voice data preparation failed: {exc}",
        )

    # Also export prosody manifest if prosody data exists
    prosody_manifest = None
    try:
        from clipcannon.voice.data_prep import export_prosody_manifest

        manifest = export_prosody_manifest(
            project_ids=project_ids,
            output_dir=output_dir,
            projects_base=projects_base,
        )
        if manifest is not None:
            prosody_manifest = str(manifest)
    except Exception as exc:
        logger.debug("Prosody manifest export skipped: %s", exc)

    elapsed = time.monotonic() - start_time

    response: dict[str, object] = {
        "total_clips": result.total_clips,
        "total_duration_s": result.total_duration_s,
        "train_count": result.train_count,
        "val_count": result.val_count,
        "output_dir": str(result.output_dir),
        "elapsed_s": round(elapsed, 2),
    }
    if prosody_manifest:
        response["prosody_manifest"] = prosody_manifest

    return response


async def _handle_voice_profiles(
    arguments: dict[str, object],
) -> dict[str, object]:
    """Handle clipcannon_voice_profiles tool call.

    Args:
        arguments: Tool arguments from MCP.

    Returns:
        Result dictionary.
    """
    from clipcannon.voice.profiles import (
        create_voice_profile,
        delete_voice_profile,
        get_voice_profile,
        list_voice_profiles,
        update_voice_profile,
    )

    action = str(arguments["action"])
    db_path = _voice_db_path()
    name = str(arguments.get("name", "")) if arguments.get("name") else None

    if action == "list":
        profiles = list_voice_profiles(db_path)
        # Strip binary reference_embedding from response
        for p in profiles:
            if "reference_embedding" in p:
                has_emb = p["reference_embedding"] is not None
                p["reference_embedding"] = f"<{len(p['reference_embedding'])} bytes>" if has_emb else None  # type: ignore[arg-type]
        return {"profiles": profiles, "count": len(profiles)}

    if action == "get":
        if not name:
            return _error("MISSING_PARAMETER", "name is required for get")
        profile = get_voice_profile(db_path, name)
        if profile is None:
            return _error("NOT_FOUND", f"Voice profile not found: {name}")
        if profile.get("reference_embedding") is not None:
            profile["reference_embedding"] = "<binary>"
        return {"profile": profile}

    if action == "create":
        if not name:
            return _error("MISSING_PARAMETER", "name is required for create")
        model_path = str(arguments.get("model_path", ""))
        if not model_path:
            return _error(
                "MISSING_PARAMETER", "model_path is required for create"
            )
        sample_rate = int(arguments.get("sample_rate", 24000))  # type: ignore[arg-type]
        try:
            profile_id = create_voice_profile(
                db_path, name, model_path, sample_rate,
            )
        except Exception as exc:
            if "UNIQUE" in str(exc):
                return _error(
                    "DUPLICATE_NAME",
                    f"A voice profile named '{name}' already exists",
                )
            return _error("CREATE_FAILED", str(exc))
        return {"profile_id": profile_id, "name": name}

    if action == "delete":
        if not name:
            return _error("MISSING_PARAMETER", "name is required for delete")
        try:
            delete_voice_profile(db_path, name)
        except ValueError as exc:
            return _error("NOT_FOUND", str(exc))
        return {"deleted": name}

    if action == "update":
        if not name:
            return _error("MISSING_PARAMETER", "name is required for update")
        update_kwargs: dict[str, object] = {}
        for field in (
            "training_status", "training_hours", "model_path",
            "sample_rate",
        ):
            if field in arguments and arguments[field] is not None:
                update_kwargs[field] = arguments[field]

        if not update_kwargs:
            return _error(
                "MISSING_PARAMETER",
                "At least one field to update is required",
            )
        try:
            update_voice_profile(db_path, name, **update_kwargs)
        except ValueError as exc:
            return _error("UPDATE_FAILED", str(exc))
        return {"updated": name, "fields": list(update_kwargs.keys())}

    return _error("INVALID_ACTION", f"Unknown action: {action}")
