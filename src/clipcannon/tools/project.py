"""Project management MCP tools for ClipCannon.

Provides tools for creating, opening, listing, inspecting, and deleting
video analysis projects. Each project gets its own directory structure
and SQLite database under ~/.clipcannon/projects/.
"""

from __future__ import annotations

# Facade: the implementation lives in the sibling modules imported below. Every name
# this module exposed before the split is re-imported here so existing imports keep
# working, hence the file-level F401 waiver.
# ruff: noqa: F401
import logging
import secrets
import shutil
import time
from pathlib import Path

from mcp.types import Tool  # noqa: TC002 - re-exported, must stay a runtime name

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.db.schema import PIPELINE_STREAMS, init_project_directory
from clipcannon.exceptions import ClipCannonError
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_file,
)
from clipcannon.tools.project_defs import _PROJECT_ID_SCHEMA, PROJECT_TOOL_DEFINITIONS
from clipcannon.tools.project_lifecycle import (
    _error_response,
    _get_db_path,
    _get_projects_dir,
    clipcannon_project_create,
    clipcannon_project_open,
)
from clipcannon.tools.project_manage import (
    _compute_disk_usage,
    clipcannon_project_delete,
    clipcannon_project_list,
    clipcannon_project_status,
)
from clipcannon.tools.video_probe import (
    SUPPORTED_FORMATS,
    detect_vfr,
    extract_video_metadata,
    run_ffprobe,
)

# Bare annotations (no rebinding) keep this module's __annotations__
# identical to before the split.
PROJECT_TOOL_DEFINITIONS: list[Tool]

logger = logging.getLogger(__name__)


async def dispatch_project_tool(name: str, arguments: dict[str, object]) -> dict[str, object]:
    """Dispatch a project tool call by name."""
    if name == "clipcannon_project_create":
        return await clipcannon_project_create(
            str(arguments["name"]), str(arguments["source_video_path"])
        )
    elif name == "clipcannon_project_open":
        return await clipcannon_project_open(str(arguments["project_id"]))
    elif name == "clipcannon_project_list":
        return await clipcannon_project_list(str(arguments.get("status_filter", "all")))
    elif name == "clipcannon_project_status":
        return await clipcannon_project_status(str(arguments["project_id"]))
    elif name == "clipcannon_project_delete":
        return await clipcannon_project_delete(
            str(arguments["project_id"]), bool(arguments.get("keep_source", True))
        )
    return _error_response("INTERNAL_ERROR", f"Unknown project tool: {name}")
