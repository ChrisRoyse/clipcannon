"""MouthMemory lip-sync v2 MCP tool dispatch for ClipCannon.

Handles dispatch for the ER-NeRF person-specific lip-sync engine.
The viseme map and mouth indexer provide reference selection and
data prep for the neural renderer.
"""

from __future__ import annotations

import logging
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
    """Handle clipcannon_lip_sync_v2 tool call.

    Currently a placeholder — will be wired to ER-NeRF inference
    once the person-specific model is trained.
    """
    project_id = str(arguments.get("project_id", ""))
    audio_path_str = str(arguments.get("audio_path", ""))
    voice_name = arguments.get("voice_name")

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

    return _error(
        "NOT_IMPLEMENTED",
        "lip_sync_v2 is being upgraded to ER-NeRF neural rendering. "
        "Use clipcannon_lip_sync (LatentSync) in the meantime.",
    )


async def dispatch_mouthmemory_tool(
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    """Dispatch a MouthMemory tool call by name."""
    if name == "clipcannon_lip_sync_v2":
        return await _handle_lip_sync_v2(arguments)
    return _error("INTERNAL_ERROR", f"Unknown MouthMemory tool: {name}")
