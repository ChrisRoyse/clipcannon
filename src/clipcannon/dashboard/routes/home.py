"""Home page routes for the ClipCannon dashboard.

Provides the root endpoint with system overview including credit balance,
GPU status, recent projects, and system health.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from clipcannon import __version__

logger = logging.getLogger(__name__)

router = APIRouter(tags=["home"])

PROJECTS_DIR = Path(
    os.environ.get(
        "CLIPCANNON_PROJECTS_DIR",
        str(Path.home() / ".clipcannon" / "projects"),
    )
)


def _get_disk_usage() -> dict[str, str | int]:
    """Get disk usage information for the projects directory.

    Returns:
        Dictionary with total, used, and free disk space.
    """
    try:
        usage = shutil.disk_usage(str(PROJECTS_DIR.parent))
        return {
            "total_gb": round(usage.total / (1024**3), 2),
            "used_gb": round(usage.used / (1024**3), 2),
            "free_gb": round(usage.free / (1024**3), 2),
            "usage_pct": round(usage.used / usage.total * 100, 1),
        }
    except OSError:
        return {
            "total_gb": 0,
            "used_gb": 0,
            "free_gb": 0,
            "usage_pct": 0,
        }


def _get_gpu_status() -> dict[str, str | bool | float | None]:
    """Get GPU availability and status.

    Returns:
        Dictionary with GPU device info and availability.
    """
    try:
        import torch

        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            vram_total = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            vram_used = torch.cuda.memory_allocated(0) / (1024**3)
            return {
                "available": True,
                "device": device_name,
                "vram_total_gb": round(vram_total, 2),
                "vram_used_gb": round(vram_used, 2),
                "cuda_version": torch.version.cuda or "unknown",
            }
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("GPU status check failed: %s", exc)

    return {
        "available": False,
        "device": None,
        "vram_total_gb": None,
        "vram_used_gb": None,
        "cuda_version": None,
    }


def _list_recent_projects(limit: int = 10) -> list[dict[str, str | int | None]]:
    """List recent projects from the projects directory.

    Args:
        limit: Maximum number of projects to return.

    Returns:
        List of project summary dictionaries.
    """
    projects: list[dict[str, str | int | None]] = []

    if not PROJECTS_DIR.exists():
        return projects

    try:
        project_dirs = sorted(
            [d for d in PROJECTS_DIR.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )

        for proj_dir in project_dirs[:limit]:
            db_path = proj_dir / "analysis.db"
            status = "ready" if db_path.exists() else "created"
            stat = proj_dir.stat()
            projects.append(
                {
                    "project_id": proj_dir.name,
                    "name": proj_dir.name,
                    "status": status,
                    "created_at": datetime.fromtimestamp(
                        stat.st_ctime,
                        tz=UTC,
                    ).isoformat(),
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime,
                        tz=UTC,
                    ).isoformat(),
                }
            )
    except OSError as exc:
        logger.warning("Failed to list projects: %s", exc)

    return projects


@router.get("/", response_model=None)
async def home() -> FileResponse | dict[str, object]:
    """Serve the dashboard home page.

    If a static index.html exists, serve it. Otherwise return the
    JSON API overview response.

    Returns:
        Static HTML file or JSON system overview.
    """
    static_index = Path(__file__).parent.parent / "static" / "index.html"
    if static_index.exists():
        return FileResponse(str(static_index), media_type="text/html")

    return _get_system_overview()


@router.get("/api/overview")
async def api_overview() -> dict[str, object]:
    """Get system overview data as JSON.

    Returns:
        Dictionary with credit balance, GPU status, projects, and health.
    """
    return _get_system_overview()


def _get_system_overview() -> dict[str, object]:
    """Build the system overview response.

    Returns:
        Dictionary with all dashboard home page data.
    """
    return {
        "version": __version__,
        "timestamp": datetime.now(UTC).isoformat(),
        "gpu": _get_gpu_status(),
        "recent_projects": _list_recent_projects(),
        "system_health": {
            "disk": _get_disk_usage(),
            "status": "healthy",
        },
    }
