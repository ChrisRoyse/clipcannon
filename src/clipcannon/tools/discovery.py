"""Discovery MCP tools for ClipCannon.

Provides tools for finding the best moments, querying scenes at
specific timestamps, and locating natural cut points in long-form
video content. These are read-only analytical tools that do not
charge credits.
"""

from __future__ import annotations

# Facade: the implementation lives in the sibling modules imported below. Every name
# this module exposed before the split is re-imported here so existing imports keep
# working, hence the file-level F401 waiver.
# ruff: noqa: F401
import json
import logging
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all, fetch_one
from clipcannon.exceptions import ClipCannonError
from clipcannon.tools.discovery_common import (
    _db_path,
    _error,
    _parse_canvas_regions,
    _projects_dir,
    _validate_project,
)
from clipcannon.tools.discovery_cuts import _score_cut_point, clipcannon_find_cut_points
from clipcannon.tools.discovery_defs import DISCOVERY_TOOL_DEFINITIONS
from clipcannon.tools.discovery_dispatch import dispatch_discovery_tool
from clipcannon.tools.discovery_moments import clipcannon_find_best_moments
from clipcannon.tools.discovery_narrative import (
    _KEY_PHRASE_MARKERS,
    PROMISE_KEYWORDS,
    _extract_key_phrases,
    _extract_sentences,
    _has_promise,
    _thought_complete,
    clipcannon_get_narrative_flow,
)
from clipcannon.tools.discovery_safe_cuts import clipcannon_find_safe_cuts

# Bare annotations (no rebinding) keep this module's __annotations__
# identical to before the split.
PROMISE_KEYWORDS: list[str]
_KEY_PHRASE_MARKERS: list[str]

__all__ = [
    "DISCOVERY_TOOL_DEFINITIONS",
    "dispatch_discovery_tool",
]

logger = logging.getLogger(__name__)
