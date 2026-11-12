"""Editing MCP tools for ClipCannon.

Provides tools for creating, modifying, and listing edit decision
lists (EDLs). Each edit represents a planned output clip with segments,
captions, crop, audio, and metadata specifications.
"""

from __future__ import annotations

# Facade: the implementation lives in the sibling modules imported below. Every name
# this module exposed before the split is re-imported here so existing imports keep
# working, hence the file-level F401 waiver.
# ruff: noqa: F401
import json
import logging
import secrets
import sqlite3 as _sqlite3
import time
from copy import deepcopy

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.editing.change_classifier import RenderHint, classify_changes
from clipcannon.editing.edl import (
    CanvasSpec,
    ColorSpec,
    EditDecisionList,
    MotionSpec,
    OverlaySpec,
    RenderSettingsSpec,
    compute_total_duration,
    validate_edl,
)
from clipcannon.exceptions import ClipCannonError
from clipcannon.tools.editing_branches import (
    _project_source_size,
    clipcannon_branch_edit,
    clipcannon_list_branches,
)
from clipcannon.tools.editing_create import _ensure_render_hint_column, clipcannon_create_edit
from clipcannon.tools.editing_defs import EDITING_TOOL_DEFINITIONS
from clipcannon.tools.editing_dispatch import dispatch_editing_tool
from clipcannon.tools.editing_effects import (
    clipcannon_add_motion,
    clipcannon_add_overlay,
    clipcannon_color_adjust,
)
from clipcannon.tools.editing_helpers import (
    PLATFORM_PROFILES,
    apply_changes,
    auto_generate_captions,
    build_audio_spec,
    build_caption_spec,
    build_crop_spec,
    build_metadata_spec,
    build_segments,
    db_path,
    ensure_branch_columns,
    ensure_edit_versions_table,
    error_response,
    project_dir,
    save_edit_version,
    store_edit_segments,
    validate_project,
)
from clipcannon.tools.editing_history import (
    clipcannon_apply_feedback,
    clipcannon_edit_history,
    clipcannon_revert_edit,
)
from clipcannon.tools.editing_modify import clipcannon_auto_trim, clipcannon_modify_edit

__all__ = [
    "EDITING_TOOL_DEFINITIONS",
    "dispatch_editing_tool",
]

logger = logging.getLogger(__name__)
