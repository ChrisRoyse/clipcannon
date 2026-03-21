"""Provenance MCP tools for ClipCannon.

Provides tools for verifying provenance chains, querying provenance
records, walking chains, and viewing timelines.
"""

from __future__ import annotations

import logging
from pathlib import Path

from mcp.types import Tool

from clipcannon.config import ClipCannonConfig
from clipcannon.exceptions import ClipCannonError
from clipcannon.provenance import (
    get_chain_from_genesis,
    get_provenance_records,
    get_provenance_timeline,
    verify_chain,
)

logger = logging.getLogger(__name__)


def _error_response(
    code: str, message: str, details: dict[str, object] | None = None
) -> dict[str, object]:
    """Build a standardized error response dict.

    Args:
        code: Machine-readable error code.
        message: Human-readable error message.
        details: Optional additional context.

    Returns:
        Error response dictionary.
    """
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _get_db_path(project_id: str) -> Path:
    """Build the database path for a project.

    Args:
        project_id: Project identifier.

    Returns:
        Path to the project's analysis.db.
    """
    try:
        config = ClipCannonConfig.load()
        projects_dir = config.resolve_path("directories.projects")
    except ClipCannonError:
        projects_dir = Path.home() / ".clipcannon" / "projects"
    return projects_dir / project_id / "analysis.db"


async def clipcannon_provenance_verify(project_id: str) -> dict[str, object]:
    """Verify the integrity of the provenance chain for a project.

    Walks the entire chain, recomputing hashes and comparing them
    against stored values. Detects any tampering or broken links.

    Args:
        project_id: Project identifier.

    Returns:
        Verification result dict or error response.
    """
    db_path = _get_db_path(project_id)
    if not db_path.exists():
        return _error_response("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    try:
        result = verify_chain(project_id, db_path)
        return {
            "project_id": project_id,
            "verified": result.verified,
            "total_records": result.total_records,
            "broken_at": result.broken_at,
            "issue": result.issue,
        }
    except ClipCannonError as exc:
        return _error_response("INTERNAL_ERROR", str(exc), exc.details)


async def clipcannon_provenance_query(
    project_id: str,
    operation: str | None = None,
    stage: str | None = None,
) -> dict[str, object]:
    """Query provenance records with optional filtering.

    Args:
        project_id: Project identifier.
        operation: Optional filter by operation name (e.g., "transcription").
        stage: Optional filter by stage name (e.g., "whisperx").

    Returns:
        List of matching provenance records or error response.
    """
    db_path = _get_db_path(project_id)
    if not db_path.exists():
        return _error_response("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    try:
        records = get_provenance_records(db_path, project_id, operation, stage)
        return {
            "project_id": project_id,
            "records": [r.model_dump() for r in records],
            "total": len(records),
            "filters": {"operation": operation, "stage": stage},
        }
    except ClipCannonError as exc:
        return _error_response("INTERNAL_ERROR", str(exc), exc.details)


async def clipcannon_provenance_chain(
    project_id: str,
    record_id: str | None = None,
) -> dict[str, object]:
    """Walk the provenance chain from genesis to a target record.

    If no record_id is given, returns the full chain for the project.

    Args:
        project_id: Project identifier.
        record_id: Optional target record ID to trace back from.

    Returns:
        Chain records ordered genesis-first, or error response.
    """
    db_path = _get_db_path(project_id)
    if not db_path.exists():
        return _error_response("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    try:
        if record_id is None:
            # Return full timeline as the chain
            records = get_provenance_records(db_path, project_id)
            return {
                "project_id": project_id,
                "chain": [r.model_dump() for r in records],
                "total": len(records),
            }

        chain = get_chain_from_genesis(project_id, record_id, db_path)
        return {
            "project_id": project_id,
            "target_record_id": record_id,
            "chain": [r.model_dump() for r in chain],
            "total": len(chain),
        }
    except ClipCannonError as exc:
        return _error_response("INTERNAL_ERROR", str(exc), exc.details)


async def clipcannon_provenance_timeline(project_id: str) -> dict[str, object]:
    """Get a chronological timeline summary of all provenance events.

    Args:
        project_id: Project identifier.

    Returns:
        Timeline with summary entries or error response.
    """
    db_path = _get_db_path(project_id)
    if not db_path.exists():
        return _error_response("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    try:
        records = get_provenance_timeline(db_path, project_id)

        timeline_entries: list[dict[str, object]] = []
        for record in records:
            entry: dict[str, object] = {
                "record_id": record.record_id,
                "timestamp": record.timestamp_utc,
                "operation": record.operation,
                "stage": record.stage,
                "description": record.description,
            }
            if record.execution_duration_ms is not None:
                entry["duration_ms"] = record.execution_duration_ms
            if record.model_name:
                entry["model"] = record.model_name
            if record.input_file_path:
                entry["input"] = record.input_file_path
            if record.output_file_path:
                entry["output"] = record.output_file_path
            timeline_entries.append(entry)

        total_duration_ms = sum(
            r.execution_duration_ms for r in records if r.execution_duration_ms is not None
        )

        return {
            "project_id": project_id,
            "timeline": timeline_entries,
            "total_records": len(records),
            "total_duration_ms": total_duration_ms,
        }
    except ClipCannonError as exc:
        return _error_response("INTERNAL_ERROR", str(exc), exc.details)


# ============================================================
# TOOL DEFINITIONS
# ============================================================

PROVENANCE_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_provenance_verify",
        description=(
            "Verify the integrity of the provenance hash chain"
            " for a project. Detects tampering or broken links."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier",
                },
            },
            "required": ["project_id"],
        },
    ),
    Tool(
        name="clipcannon_provenance_query",
        description=(
            "Query provenance records for a project, optionally filtered by operation or stage."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier",
                },
                "operation": {
                    "type": "string",
                    "description": "Filter by operation name (e.g., probe, transcription)",
                },
                "stage": {
                    "type": "string",
                    "description": "Filter by stage name (e.g., ffprobe, whisperx)",
                },
            },
            "required": ["project_id"],
        },
    ),
    Tool(
        name="clipcannon_provenance_chain",
        description=(
            "Walk the provenance chain from genesis to a specific"
            " record. Shows the full lineage of a processing result."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier",
                },
                "record_id": {
                    "type": "string",
                    "description": "Target record ID to trace back from (omit for full chain)",
                },
            },
            "required": ["project_id"],
        },
    ),
    Tool(
        name="clipcannon_provenance_timeline",
        description=(
            "Get a chronological timeline of all provenance events"
            " for a project, with durations and models used."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier",
                },
            },
            "required": ["project_id"],
        },
    ),
]


async def dispatch_provenance_tool(name: str, arguments: dict[str, object]) -> dict[str, object]:
    """Dispatch a provenance tool call by name.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        Tool result dictionary.
    """
    if name == "clipcannon_provenance_verify":
        return await clipcannon_provenance_verify(
            project_id=str(arguments["project_id"]),
        )
    elif name == "clipcannon_provenance_query":
        return await clipcannon_provenance_query(
            project_id=str(arguments["project_id"]),
            operation=str(arguments["operation"]) if arguments.get("operation") else None,
            stage=str(arguments["stage"]) if arguments.get("stage") else None,
        )
    elif name == "clipcannon_provenance_chain":
        return await clipcannon_provenance_chain(
            project_id=str(arguments["project_id"]),
            record_id=str(arguments["record_id"]) if arguments.get("record_id") else None,
        )
    elif name == "clipcannon_provenance_timeline":
        return await clipcannon_provenance_timeline(
            project_id=str(arguments["project_id"]),
        )
    else:
        return _error_response("INTERNAL_ERROR", f"Unknown provenance tool: {name}")
