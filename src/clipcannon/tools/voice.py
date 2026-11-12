"""Voice cloning MCP tool dispatch for ClipCannon.

Handles dispatch for voice data preparation and voice profile
management tools.
"""

from __future__ import annotations

# Facade: the implementation lives in the sibling modules imported below. Every name
# this module exposed before the split is re-imported here so existing imports keep
# working, hence the file-level F401 waiver.
# ruff: noqa: F401
import logging
import time
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.exceptions import ClipCannonError
from clipcannon.tools.voice_profiles import (
    _error,
    _handle_prepare_voice_data,
    _handle_voice_profiles,
    _projects_dir,
    _voice_db_path,
    resolve_voice_profile,
)
from clipcannon.tools.voice_speak import _handle_speak, _handle_speak_optimized

logger = logging.getLogger(__name__)


async def dispatch_voice_tool(
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    """Dispatch a voice tool call by name.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        Tool result dictionary.
    """
    if name == "clipcannon_prepare_voice_data":
        return await _handle_prepare_voice_data(arguments)
    if name == "clipcannon_voice_profiles":
        return await _handle_voice_profiles(arguments)
    if name == "clipcannon_speak":
        return await _handle_speak(arguments)
    if name == "clipcannon_speak_optimized":
        return await _handle_speak_optimized(arguments)
    return _error("INTERNAL_ERROR", f"Unknown voice tool: {name}")
