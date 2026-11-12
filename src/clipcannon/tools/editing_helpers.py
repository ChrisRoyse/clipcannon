"""Helper functions for editing tool parameter construction.

Provides builder functions that convert raw MCP tool parameter dicts
into validated Pydantic models (SegmentSpec, CaptionSpec, CropSpec,
AudioSpec, MetadataSpec). Also provides shared project/DB utilities
and edit version management.
"""

from __future__ import annotations

# Facade: the implementation lives in the sibling modules imported below. Every name
# this module exposed before the split is re-imported here so existing imports keep
# working, hence the file-level F401 waiver.
# ruff: noqa: F401
import logging
import secrets
import sqlite3 as _sqlite3
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_one
from clipcannon.editing.captions import (
    chunk_transcript_words,
    fetch_words_for_segments,
    remap_timestamps,
)
from clipcannon.editing.edl import (
    AudioSpec,
    CaptionChunk,
    CaptionSpec,
    CaptionWord,
    CropSpec,
    EditDecisionList,
    MetadataSpec,
    RenderSettingsSpec,
    SegmentCanvasSpec,
    SegmentSpec,
    TransitionSpec,
)
from clipcannon.editing.smart_crop import PLATFORM_ASPECTS
from clipcannon.exceptions import ClipCannonError
from clipcannon.tools.editing_base import (
    PLATFORM_PROFILES,
    db_path,
    error_response,
    project_dir,
    projects_dir,
    validate_project,
)
from clipcannon.tools.editing_specs import (
    apply_changes,
    auto_generate_captions,
    build_audio_spec,
    build_caption_spec,
    build_crop_spec,
    build_metadata_spec,
    build_render_settings,
    build_segments,
    build_transition,
    store_edit_segments,
)
from clipcannon.tools.editing_versions import (
    _EDIT_VERSIONS_DDL,
    ensure_branch_columns,
    ensure_edit_versions_table,
    generate_change_description,
    save_edit_version,
)

# Bare annotations (no rebinding) keep this module's __annotations__
# identical to before the split.
PLATFORM_PROFILES: dict[str, str]

logger = logging.getLogger(__name__)
