"""Provenance chain routes for the ClipCannon dashboard.

Provides endpoints to view provenance records, verify chain integrity,
and display timeline views for project provenance chains.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter

from clipcannon.exceptions import ProvenanceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/provenance", tags=["provenance"])

PROJECTS_DIR = Path(os.environ.get(
    "CLIPCANNON_PROJECTS_DIR",
    str(Path.home() / ".clipcannon" / "projects"),
))


def _get_db_path(project_id: str) -> Path:
    """Resolve the database path for a project.

    Args:
        project_id: The project identifier.

    Returns:
        Path to the project's analysis.db file.
    """
    return PROJECTS_DIR / project_id / "analysis.db"


@router.get("/{project_id}")
async def get_provenance_records(project_id: str) -> dict[str, object]:
    """Get all provenance records for a project.

    Args:
        project_id: The project identifier.

    Returns:
        Dictionary with provenance records and metadata.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return {
            "project_id": project_id,
            "records": [],
            "count": 0,
            "error": f"Project database not found: {project_id}",
        }

    try:
        from clipcannon.provenance import get_provenance_records as _get_records

        records = _get_records(db_path, project_id)
        return {
            "project_id": project_id,
            "records": [r.model_dump() for r in records],
            "count": len(records),
        }
    except ProvenanceError as exc:
        logger.warning("Provenance query failed for %s: %s", project_id, exc)
        return {
            "project_id": project_id,
            "records": [],
            "count": 0,
            "error": str(exc),
        }
    except Exception as exc:
        logger.error("Unexpected error querying provenance for %s: %s", project_id, exc)
        return {
            "project_id": project_id,
            "records": [],
            "count": 0,
            "error": f"Internal error: {exc}",
        }


@router.get("/{project_id}/verify")
async def verify_provenance_chain(project_id: str) -> dict[str, object]:
    """Verify the integrity of a project's provenance chain.

    Recomputes all chain hashes and checks for tampering.

    Args:
        project_id: The project identifier.

    Returns:
        Dictionary with verification result.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return {
            "project_id": project_id,
            "verified": False,
            "total_records": 0,
            "error": f"Project database not found: {project_id}",
        }

    try:
        from clipcannon.provenance import verify_chain

        result = verify_chain(project_id, db_path)
        return {
            "project_id": project_id,
            "verified": result.verified,
            "total_records": result.total_records,
            "broken_at": result.broken_at,
            "issue": result.issue,
        }
    except ProvenanceError as exc:
        logger.warning("Chain verification failed for %s: %s", project_id, exc)
        return {
            "project_id": project_id,
            "verified": False,
            "total_records": 0,
            "error": str(exc),
        }
    except Exception as exc:
        logger.error("Unexpected error verifying chain for %s: %s", project_id, exc)
        return {
            "project_id": project_id,
            "verified": False,
            "total_records": 0,
            "error": f"Internal error: {exc}",
        }


@router.get("/{project_id}/timeline")
async def get_provenance_timeline(project_id: str) -> dict[str, object]:
    """Get a timeline view of provenance records for a project.

    Returns records ordered chronologically with simplified fields
    suitable for timeline visualization.

    Args:
        project_id: The project identifier.

    Returns:
        Dictionary with timeline entries.
    """
    db_path = _get_db_path(project_id)

    if not db_path.exists():
        return {
            "project_id": project_id,
            "timeline": [],
            "count": 0,
            "error": f"Project database not found: {project_id}",
        }

    try:
        from clipcannon.provenance import get_provenance_timeline as _get_timeline

        records = _get_timeline(db_path, project_id)

        timeline = []
        for record in records:
            timeline.append({
                "record_id": record.record_id,
                "timestamp": record.timestamp_utc,
                "operation": record.operation,
                "stage": record.stage,
                "description": record.description,
                "model_name": record.model_name,
                "duration_ms": record.execution_duration_ms,
                "parent_id": record.parent_record_id,
                "chain_hash_prefix": record.chain_hash[:12] if record.chain_hash else None,
            })

        return {
            "project_id": project_id,
            "timeline": timeline,
            "count": len(timeline),
        }
    except ProvenanceError as exc:
        logger.warning("Timeline query failed for %s: %s", project_id, exc)
        return {
            "project_id": project_id,
            "timeline": [],
            "count": 0,
            "error": str(exc),
        }
    except Exception as exc:
        logger.error("Unexpected error querying timeline for %s: %s", project_id, exc)
        return {
            "project_id": project_id,
            "timeline": [],
            "count": 0,
            "error": f"Internal error: {exc}",
        }
