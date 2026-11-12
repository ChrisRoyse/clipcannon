"""MCP tool definitions for the project management tools."""

from __future__ import annotations

from mcp.types import Tool

_PROJECT_ID_SCHEMA = {
    "type": "object",
    "properties": {
        "project_id": {"type": "string", "description": "Project identifier"},
    },
    "required": ["project_id"],
}

PROJECT_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_project_create",
        description=(
            "Create a new project from a source video. Validates format,"
            " extracts metadata via ffprobe, computes SHA-256,"
            " and initializes the project database."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Human-readable project name"},
                "source_video_path": {
                    "type": "string",
                    "description": "Absolute path to source video (mp4/mov/mkv/webm/avi/ts/mts)",
                },
            },
            "required": ["name", "source_video_path"],
        },
    ),
    Tool(
        name="clipcannon_project_open",
        description="Open an existing project and return its current state.",
        inputSchema=_PROJECT_ID_SCHEMA,
    ),
    Tool(
        name="clipcannon_project_list",
        description="List all projects, optionally filtered by status.",
        inputSchema={
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "description": "Filter: all, created, analyzing, ready, error",
                    "default": "all",
                },
            },
        },
    ),
    Tool(
        name="clipcannon_project_status",
        description="Get detailed status with pipeline progress and disk usage.",
        inputSchema=_PROJECT_ID_SCHEMA,
    ),
    Tool(
        name="clipcannon_project_delete",
        description="Delete a project. Can optionally preserve the original source video.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "keep_source": {
                    "type": "boolean",
                    "description": "Preserve source video",
                    "default": True,
                },
            },
            "required": ["project_id"],
        },
    ),
]
