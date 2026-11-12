"""Visual understanding MCP tools for ClipCannon.

Provides get_frame tool for retrieving visual and temporal data.
"""

from __future__ import annotations

# Facade: the implementation lives in the sibling modules imported below. Every name
# this module exposed before the split is re-imported here so existing imports keep
# working, hence the file-level F401 waiver.
# ruff: noqa: F401
import base64
import logging
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.tools.understanding import _db_path, _error, _project_dir, _validate_project
from clipcannon.tools.understanding_frame import (
    _FRAME_INTERVAL_MS,
    _find_nearest_frame,
    _get_moment_context,
    _safe_fetch_all,
    clipcannon_get_frame,
)
from clipcannon.tools.understanding_segment import clipcannon_get_segment_detail

logger = logging.getLogger(__name__)
