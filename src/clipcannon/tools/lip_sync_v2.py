"""MouthMemory lip-sync v2 MCP tool dispatch for ClipCannon.

Handles dispatch for the retrieval-based lip-sync engine and
mouth atlas builder.
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


async def _handle_lip_sync_v2(
    arguments: dict[str, object],
) -> dict[str, object]:
    """Handle clipcannon_lip_sync_v2 tool call."""
    project_id = str(arguments.get("project_id", ""))
    audio_path_str = str(arguments.get("audio_path", ""))
    driver_path_str = str(arguments.get("driver_video_path", ""))
    voice_name = arguments.get("voice_name")
    fps_val = int(arguments.get("fps", 25))
    blend_mode = str(arguments.get("blend_mode", "laplacian"))
    temporal_smooth = float(arguments.get("temporal_smooth", 0.5))

    if not project_id:
        return _error("MISSING_PARAMETER", "project_id is required")
    if not audio_path_str:
        return _error("MISSING_PARAMETER", "audio_path is required")

    audio_path = Path(audio_path_str)
    if not audio_path.exists():
        return _error("FILE_NOT_FOUND", f"Audio file not found: {audio_path}")

    projects_dir = _projects_dir()
    project_dir = projects_dir / project_id
    if not project_dir.exists():
        return _error("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    db_path = project_dir / "analysis.db"

    # Resolve driver video
    driver_path: Path | None = None
    if driver_path_str:
        driver_path = Path(driver_path_str)
        if not driver_path.exists():
            return _error("FILE_NOT_FOUND", f"Driver video not found: {driver_path}")
    else:
        # Auto-extract webcam from project
        from clipcannon.tools.avatar import _get_webcam_region, _get_source_info

        if db_path.exists():
            source_info = _get_source_info(db_path, project_id)
            if source_info:
                # Use source video directly as driver
                driver_path = Path(str(source_info["source_path"]))

        if driver_path is None or not driver_path.exists():
            return _error(
                "NO_DRIVER_VIDEO",
                "No driver_video_path provided and could not auto-discover source video. "
                "Provide a driver_video_path or ensure the project has a source video.",
            )

    # Resolve atlas for voice profile mode
    atlas_project_id: str | None = None
    atlas_db_path: Path | None = None

    if voice_name:
        voice_name_str = str(voice_name)
        atlas_db = Path.home() / ".clipcannon" / "voice_data" / voice_name_str / "mouth_atlas.db"
        if atlas_db.exists():
            atlas_project_id = voice_name_str
            atlas_db_path = atlas_db
            logger.info("MouthMemory: using pre-built atlas for '%s'", voice_name_str)

    # Output path
    avatar_dir = project_dir / "avatar"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    output_id = f"mm_{secrets.token_hex(6)}"
    output_path = avatar_dir / f"{output_id}.mp4"

    start = time.monotonic()

    try:
        from clipcannon.avatar.mouth_memory import generate_lip_sync

        result = await generate_lip_sync(
            project_id=project_id,
            audio_path=audio_path,
            driver_video_path=driver_path,
            output_path=output_path,
            db_path=db_path,
            project_dir=project_dir,
            atlas_project_id=atlas_project_id,
            atlas_db_path=atlas_db_path,
            fps=fps_val,
            temporal_smooth=temporal_smooth,
            blend_mode=blend_mode,
        )
    except FileNotFoundError as exc:
        return _error("PREREQUISITE_MISSING", str(exc))
    except RuntimeError as exc:
        logger.exception("MouthMemory lip-sync failed for %s", project_id)
        return _error("LIP_SYNC_FAILED", str(exc))
    except Exception as exc:
        logger.exception("MouthMemory lip-sync failed for %s", project_id)
        return _error("LIP_SYNC_FAILED", str(exc))

    elapsed_ms = int((time.monotonic() - start) * 1000)

    return {
        "output_id": output_id,
        "video_path": str(result.video_path),
        "duration_ms": result.duration_ms,
        "resolution": result.resolution,
        "engine": "mouthmemory",
        "frames_total": result.frames_total,
        "frames_matched": result.frames_matched,
        "frames_warped": result.frames_warped,
        "frames_fallback": result.frames_fallback,
        "elapsed_ms": elapsed_ms,
    }


async def _handle_build_mouth_atlas(
    arguments: dict[str, object],
) -> dict[str, object]:
    """Handle clipcannon_build_mouth_atlas tool call."""
    voice_name = str(arguments.get("voice_name", ""))
    project_ids = arguments.get("project_ids")
    min_quality = float(arguments.get("min_quality", 0.2))

    if not voice_name:
        return _error("MISSING_PARAMETER", "voice_name is required")

    try:
        from clipcannon.avatar.mouth_atlas import build_mouth_atlas

        result = await build_mouth_atlas(
            voice_name=voice_name,
            project_ids=list(project_ids) if project_ids else None,
            min_quality=min_quality,
        )
    except Exception as exc:
        logger.exception("Mouth atlas build failed for %s", voice_name)
        return _error("ATLAS_BUILD_FAILED", str(exc))

    return result


async def dispatch_mouthmemory_tool(
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    """Dispatch a MouthMemory tool call by name."""
    if name == "clipcannon_lip_sync_v2":
        return await _handle_lip_sync_v2(arguments)
    if name == "clipcannon_build_mouth_atlas":
        return await _handle_build_mouth_atlas(arguments)
    return _error("INTERNAL_ERROR", f"Unknown MouthMemory tool: {name}")
