"""Avatar/lip-sync MCP tool dispatch for ClipCannon.

Handles dispatch for lip-sync video generation tools.
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


async def _handle_lip_sync(arguments: dict[str, object]) -> dict[str, object]:
    """Handle clipcannon_lip_sync tool call.

    Args:
        arguments: Tool arguments from MCP.

    Returns:
        Result dict with output video path and metadata.
    """
    project_id = str(arguments.get("project_id", ""))
    audio_path_str = str(arguments.get("audio_path", ""))
    driver_path_str = str(arguments.get("driver_video_path", ""))
    inference_steps = int(arguments.get("inference_steps", 20))
    seed = arguments.get("seed")

    if not project_id:
        return _error("MISSING_PARAMETER", "project_id is required")
    if not audio_path_str:
        return _error("MISSING_PARAMETER", "audio_path is required")
    if not driver_path_str:
        return _error("MISSING_PARAMETER", "driver_video_path is required")

    audio_path = Path(audio_path_str)
    driver_path = Path(driver_path_str)

    if not audio_path.exists():
        return _error("FILE_NOT_FOUND", f"Audio file not found: {audio_path}")
    if not driver_path.exists():
        return _error("FILE_NOT_FOUND", f"Driver video not found: {driver_path}")

    # Output path
    projects_dir = _projects_dir()
    project_dir = projects_dir / project_id
    if not project_dir.exists():
        return _error("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    avatar_dir = project_dir / "avatar"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    output_id = f"avatar_{secrets.token_hex(6)}"
    output_path = avatar_dir / f"{output_id}.mp4"

    start = time.monotonic()

    try:
        from clipcannon.avatar.lip_sync import get_engine

        engine = get_engine()
        result = engine.generate(
            video_path=driver_path,
            audio_path=audio_path,
            output_path=output_path,
            inference_steps=inference_steps,
            seed=int(seed) if seed is not None else None,
        )
    except FileNotFoundError as exc:
        return _error("PREREQUISITE_MISSING", str(exc))
    except Exception as exc:
        logger.exception("Lip sync failed for project %s", project_id)
        return _error("LIP_SYNC_FAILED", str(exc))

    elapsed_ms = int((time.monotonic() - start) * 1000)

    return {
        "output_id": output_id,
        "video_path": str(result.video_path),
        "duration_ms": result.duration_ms,
        "resolution": result.resolution,
        "inference_steps": result.inference_steps,
        "elapsed_ms": elapsed_ms,
    }


async def dispatch_avatar_tool(
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    """Dispatch an avatar tool call by name.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        Tool result dictionary.
    """
    if name == "clipcannon_lip_sync":
        return await _handle_lip_sync(arguments)
    return _error("INTERNAL_ERROR", f"Unknown avatar tool: {name}")
