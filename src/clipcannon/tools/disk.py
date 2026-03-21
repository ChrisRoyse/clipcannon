"""Disk management MCP tools for ClipCannon.

Provides tools for inspecting disk usage by storage tier (sacred,
regenerable, ephemeral) and cleaning up files to free space.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from mcp.types import Tool

from clipcannon.config import ClipCannonConfig
from clipcannon.exceptions import ClipCannonError

logger = logging.getLogger(__name__)

# File classification by storage tier
SACRED_PATTERNS: set[str] = {"analysis.db", "analysis.db-wal", "analysis.db-shm"}
SACRED_DIRS: set[str] = {"source"}

REGENERABLE_DIRS: set[str] = {"stems", "frames", "storyboards"}
REGENERABLE_FILE_PATTERNS: set[str] = {"source_cfr.mp4"}

# Everything else is ephemeral (logs, temp files, etc.)


def _error_response(code: str, message: str, details: dict[str, object] | None = None) -> dict[str, object]:
    """Build a standardized error response dict.

    Args:
        code: Machine-readable error code.
        message: Human-readable error message.
        details: Optional additional context.

    Returns:
        Error response dictionary.
    """
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _get_projects_dir() -> Path:
    """Resolve the projects base directory from config.

    Returns:
        Absolute path to the projects directory.
    """
    try:
        config = ClipCannonConfig.load()
        return config.resolve_path("directories.projects")
    except ClipCannonError:
        return Path.home() / ".clipcannon" / "projects"


def _classify_file(file_path: Path, project_dir: Path) -> str:
    """Classify a file into a storage tier.

    Args:
        file_path: Absolute path to the file.
        project_dir: Root of the project directory.

    Returns:
        Tier name: "sacred", "regenerable", or "ephemeral".
    """
    relative = file_path.relative_to(project_dir)
    parts = relative.parts

    # Check sacred files
    if file_path.name in SACRED_PATTERNS:
        return "sacred"

    # Check sacred directories (source/)
    if len(parts) >= 1 and parts[0] in SACRED_DIRS:
        return "sacred"

    # Check regenerable directories (stems/, frames/, storyboards/)
    if len(parts) >= 1 and parts[0] in REGENERABLE_DIRS:
        return "regenerable"

    # Check regenerable file patterns
    if file_path.name in REGENERABLE_FILE_PATTERNS:
        return "regenerable"

    return "ephemeral"


def _get_system_free_space(path: Path) -> int:
    """Get free disk space on the filesystem containing the given path.

    Args:
        path: Any path on the target filesystem.

    Returns:
        Free space in bytes.
    """
    try:
        usage = shutil.disk_usage(str(path))
        return usage.free
    except OSError:
        return 0


async def clipcannon_disk_status(project_id: str) -> dict[str, object]:
    """Inspect disk usage for a project, classified by storage tier.

    Sacred: original source video, analysis.db -- never auto-deleted.
    Regenerable: CFR video, stems, frames, storyboards -- can be recreated.
    Ephemeral: temporary files, logs -- safe to delete anytime.

    Args:
        project_id: Project identifier.

    Returns:
        Disk usage breakdown by tier or error response.
    """
    project_dir = _get_projects_dir() / project_id
    if not project_dir.exists():
        return _error_response("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    try:
        tiers: dict[str, dict[str, object]] = {
            "sacred": {"bytes": 0, "files": [], "count": 0},
            "regenerable": {"bytes": 0, "files": [], "count": 0},
            "ephemeral": {"bytes": 0, "files": [], "count": 0},
        }

        for file_path in project_dir.rglob("*"):
            if not file_path.is_file():
                continue

            tier = _classify_file(file_path, project_dir)
            size = file_path.stat().st_size
            relative_path = str(file_path.relative_to(project_dir))

            tier_data = tiers[tier]
            tier_data["bytes"] = int(tier_data["bytes"]) + size
            tier_data["count"] = int(tier_data["count"]) + 1

            # Only list individual files for small counts
            file_list = tier_data["files"]
            if isinstance(file_list, list) and len(file_list) < 50:
                file_list.append({"path": relative_path, "size_bytes": size})

        total_bytes = sum(int(t["bytes"]) for t in tiers.values())
        free_space = _get_system_free_space(project_dir)

        return {
            "project_id": project_id,
            "tiers": {
                name: {
                    "bytes": data["bytes"],
                    "mb": round(int(data["bytes"]) / (1024 * 1024), 2),
                    "count": data["count"],
                    "files": data["files"],
                }
                for name, data in tiers.items()
            },
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / (1024 * 1024), 2),
            "system_free_bytes": free_space,
            "system_free_gb": round(free_space / (1024 ** 3), 2),
        }

    except Exception as exc:
        logger.exception("Error computing disk status for %s", project_id)
        return _error_response("INTERNAL_ERROR", f"Disk status failed: {exc}")


async def clipcannon_disk_cleanup(
    project_id: str,
    target_free_gb: float | None = None,
) -> dict[str, object]:
    """Clean up project files to free disk space.

    Deletes ephemeral files first, then regenerable files (largest first).
    Sacred files (source video, analysis.db) are never deleted.

    Args:
        project_id: Project identifier.
        target_free_gb: If set, stop deleting once this much free space
            is available on the filesystem.

    Returns:
        Cleanup result with files deleted and space freed.
    """
    project_dir = _get_projects_dir() / project_id
    if not project_dir.exists():
        return _error_response("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    try:
        deleted_files: list[dict[str, object]] = []
        total_freed = 0
        target_bytes = int(target_free_gb * (1024 ** 3)) if target_free_gb else None

        # Collect files by tier
        ephemeral_files: list[tuple[Path, int]] = []
        regenerable_files: list[tuple[Path, int]] = []

        for file_path in project_dir.rglob("*"):
            if not file_path.is_file():
                continue
            tier = _classify_file(file_path, project_dir)
            size = file_path.stat().st_size
            if tier == "ephemeral":
                ephemeral_files.append((file_path, size))
            elif tier == "regenerable":
                regenerable_files.append((file_path, size))

        # Sort regenerable by size (largest first)
        regenerable_files.sort(key=lambda x: x[1], reverse=True)

        def _should_stop() -> bool:
            if target_bytes is None:
                return False
            free = _get_system_free_space(project_dir)
            return free >= target_bytes

        # Delete ephemeral first
        for file_path, size in ephemeral_files:
            if _should_stop():
                break
            try:
                relative = str(file_path.relative_to(project_dir))
                file_path.unlink()
                deleted_files.append({"path": relative, "size_bytes": size, "tier": "ephemeral"})
                total_freed += size
            except OSError as exc:
                logger.warning("Failed to delete %s: %s", file_path, exc)

        # Then regenerable (largest first)
        if not _should_stop():
            for file_path, size in regenerable_files:
                if _should_stop():
                    break
                try:
                    relative = str(file_path.relative_to(project_dir))
                    file_path.unlink()
                    deleted_files.append({"path": relative, "size_bytes": size, "tier": "regenerable"})
                    total_freed += size
                except OSError as exc:
                    logger.warning("Failed to delete %s: %s", file_path, exc)

        # Clean up empty directories
        for dir_path in sorted(project_dir.rglob("*"), reverse=True):
            if dir_path.is_dir() and not list(dir_path.iterdir()):
                try:
                    dir_path.rmdir()
                except OSError:
                    pass

        free_after = _get_system_free_space(project_dir)

        return {
            "project_id": project_id,
            "deleted_files": deleted_files,
            "total_deleted": len(deleted_files),
            "freed_bytes": total_freed,
            "freed_mb": round(total_freed / (1024 * 1024), 2),
            "system_free_gb_after": round(free_after / (1024 ** 3), 2),
        }

    except Exception as exc:
        logger.exception("Error cleaning up project %s", project_id)
        return _error_response("INTERNAL_ERROR", f"Cleanup failed: {exc}")


# ============================================================
# TOOL DEFINITIONS
# ============================================================

DISK_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_disk_status",
        description="Show disk usage for a project classified by storage tier: sacred (never deleted), regenerable (can be recreated), and ephemeral (safe to delete).",
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
        name="clipcannon_disk_cleanup",
        description="Free disk space by deleting ephemeral files first, then regenerable files (largest first). Sacred files are never touched.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project identifier",
                },
                "target_free_gb": {
                    "type": "number",
                    "description": "Stop cleanup once this many GB are free on disk (omit to clean all non-sacred)",
                },
            },
            "required": ["project_id"],
        },
    ),
]


async def dispatch_disk_tool(name: str, arguments: dict[str, object]) -> dict[str, object]:
    """Dispatch a disk tool call by name.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        Tool result dictionary.
    """
    if name == "clipcannon_disk_status":
        return await clipcannon_disk_status(
            project_id=str(arguments["project_id"]),
        )
    elif name == "clipcannon_disk_cleanup":
        target = arguments.get("target_free_gb")
        return await clipcannon_disk_cleanup(
            project_id=str(arguments["project_id"]),
            target_free_gb=float(target) if target is not None else None,
        )
    else:
        return _error_response("INTERNAL_ERROR", f"Unknown disk tool: {name}")
