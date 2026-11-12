"""Rendering MCP tools for ClipCannon.

Provides tools for rendering edits to video files, checking render
status, and batch rendering multiple edits concurrently. Each render
charges 2 credits via the license server.
"""

from __future__ import annotations

# Facade: the implementation lives in the sibling modules imported below. Every name
# this module exposed before the split is re-imported here so existing imports keep
# working, hence the file-level F401 waiver.
# ruff: noqa: F401
import asyncio
import base64
import json
import logging
import time
from pathlib import Path

from clipcannon.billing.license_client import LicenseClient
from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.editing.edl import EditDecisionList
from clipcannon.exceptions import ClipCannonError
from clipcannon.rendering.renderer import RenderEngine
from clipcannon.tools.rendering_common import (
    _db_path,
    _error,
    _extract_render_frame,
    _load_edl,
    _project_dir,
    _projects_dir,
    _resolve_render_path,
    _resolve_source,
    _validate_project,
)
from clipcannon.tools.rendering_context import clipcannon_get_editing_context
from clipcannon.tools.rendering_defs import RENDERING_TOOL_DEFINITIONS
from clipcannon.tools.rendering_dispatch import dispatch_rendering_tool
from clipcannon.tools.rendering_preview import (
    clipcannon_preview_clip,
    clipcannon_preview_layout,
    clipcannon_preview_segment,
)
from clipcannon.tools.rendering_render import (
    _RENDER_CREDITS,
    clipcannon_analyze_frame,
    clipcannon_inspect_render,
    clipcannon_render,
)
from clipcannon.tools.rendering_scene_map import clipcannon_get_scene_map

__all__ = [
    "RENDERING_TOOL_DEFINITIONS",
    "dispatch_rendering_tool",
]

logger = logging.getLogger(__name__)
