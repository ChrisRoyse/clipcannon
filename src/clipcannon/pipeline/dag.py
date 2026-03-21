"""DAG resolution and stream status tracking for the pipeline.

Provides topological sort for stage dependency resolution and
stream_status table management.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_one
from clipcannon.exceptions import PipelineError

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def topological_sort(stages: list) -> list[list]:
    """Sort pipeline stages into dependency levels using Kahn's algorithm.

    Stages at the same level have no mutual dependencies and can
    run concurrently. Returns a list of levels, where each level
    is a list of stages that can execute in parallel.

    Args:
        stages: All registered pipeline stages (PipelineStage instances).

    Returns:
        List of levels, each containing stages runnable in parallel.

    Raises:
        PipelineError: If the dependency graph contains a cycle.
    """
    name_to_stage = {s.name: s for s in stages}
    in_degree: dict[str, int] = {s.name: 0 for s in stages}
    dependents: dict[str, list[str]] = {s.name: [] for s in stages}

    for stage in stages:
        for dep_name in stage.depends_on:
            if dep_name not in name_to_stage:
                logger.warning(
                    "Stage '%s' depends on unregistered stage '%s', skipping dependency",
                    stage.name,
                    dep_name,
                )
                continue
            in_degree[stage.name] += 1
            dependents[dep_name].append(stage.name)

    levels: list[list] = []
    queue = [name for name, deg in in_degree.items() if deg == 0]

    processed = 0
    while queue:
        level = [name_to_stage[name] for name in queue]
        levels.append(level)
        processed += len(queue)

        next_queue: list[str] = []
        for name in queue:
            for dep_name in dependents[name]:
                in_degree[dep_name] -= 1
                if in_degree[dep_name] == 0:
                    next_queue.append(dep_name)
        queue = next_queue

    if processed != len(stages):
        cycle_stages = [s.name for s in stages if in_degree[s.name] > 0]
        raise PipelineError(
            f"Dependency cycle detected involving stages: {cycle_stages}",
            stage_name="orchestrator",
            operation="dag_resolution",
        )

    return levels


def update_stream_status(
    db_path: Path,
    project_id: str,
    stream_name: str,
    status: str,
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Update or insert a stream_status record.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        stream_name: Name of the pipeline stream/stage.
        status: New status value (pending, running, completed, failed, skipped).
        error_message: Error message if status is 'failed'.
        duration_ms: Execution time in milliseconds.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        existing = fetch_one(
            conn,
            "SELECT id FROM stream_status WHERE project_id = ? AND stream_name = ?",
            (project_id, stream_name),
        )
        if existing:
            if status == "running":
                execute(
                    conn,
                    "UPDATE stream_status SET status = ?, started_at = datetime('now'), "
                    "error_message = NULL WHERE project_id = ? AND stream_name = ?",
                    (status, project_id, stream_name),
                )
            elif status in ("completed", "failed", "skipped"):
                execute(
                    conn,
                    "UPDATE stream_status SET status = ?, completed_at = datetime('now'), "
                    "error_message = ?, duration_ms = ? "
                    "WHERE project_id = ? AND stream_name = ?",
                    (status, error_message, duration_ms, project_id, stream_name),
                )
            else:
                execute(
                    conn,
                    "UPDATE stream_status SET status = ? WHERE project_id = ? AND stream_name = ?",
                    (status, project_id, stream_name),
                )
        else:
            execute(
                conn,
                "INSERT INTO stream_status (project_id, stream_name, status, "
                "error_message, duration_ms) VALUES (?, ?, ?, ?, ?)",
                (project_id, stream_name, status, error_message, duration_ms),
            )
        conn.commit()
    finally:
        conn.close()
