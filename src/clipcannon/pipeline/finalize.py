"""Finalize pipeline stage for ClipCannon.

Updates stream_status for all tracked streams, verifies the provenance
chain, sets the project status to 'ready' or 'error', and cleans up
ephemeral files. This is a REQUIRED stage -- failure aborts the pipeline.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.db.schema import PIPELINE_STREAMS
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
    verify_chain,
)

logger = logging.getLogger(__name__)

OPERATION = "finalize"
STAGE = "finalize"

# Tables to check for each stream to determine completion
_STREAM_EVIDENCE: dict[str, list[str]] = {
    "source_separation": ["silence_gaps"],
    "visual": ["scenes"],
    "ocr": ["on_screen_text"],
    "quality": ["scenes"],
    "shot_type": ["scenes"],
    "transcription": ["transcript_segments", "transcript_words"],
    "semantic": ["topics"],
    "emotion": ["emotion_curve"],
    "speaker": ["speakers"],
    "reactions": ["reactions"],
    "acoustic": ["acoustic", "silence_gaps"],
    "beats": ["beats"],
    "chronemic": ["pacing"],
    "storyboards": ["storyboard_grids"],
    "profanity": ["content_safety"],
    "highlights": ["highlights"],
}


def _check_table_has_data(
    db_path: Path,
    project_id: str,
    table_name: str,
) -> bool:
    """Check if a table has any rows for the project.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        table_name: Table to check.

    Returns:
        True if the table has data for this project.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        row = fetch_one(
            conn,
            f"SELECT count(*) as cnt FROM {table_name} WHERE project_id = ?",  # noqa: S608
            (project_id,),
        )
        if row and isinstance(row, dict):
            return int(row.get("cnt", 0)) > 0
        return False
    except Exception:
        return False
    finally:
        conn.close()


def _determine_stream_statuses(
    db_path: Path,
    project_id: str,
) -> dict[str, str]:
    """Determine completion status for all pipeline streams.

    Checks the stream_status table first; if a stream has already
    been recorded as completed/failed/skipped, that status is used.
    Otherwise, checks evidence tables for data.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.

    Returns:
        Mapping of stream_name to status.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        existing = fetch_all(
            conn,
            "SELECT stream_name, status, error_message FROM stream_status "
            "WHERE project_id = ?",
            (project_id,),
        )
    finally:
        conn.close()

    existing_map: dict[str, dict[str, str | None]] = {
        str(r["stream_name"]): {
            "status": str(r["status"]),
            "error": str(r["error_message"]) if r.get("error_message") else None,
        }
        for r in existing
    }

    results: dict[str, str] = {}

    for stream_name in PIPELINE_STREAMS:
        if stream_name in existing_map:
            status = existing_map[stream_name]["status"]
            if status in ("completed", "failed", "skipped"):
                results[stream_name] = status
                continue

        # Check evidence tables
        evidence_tables = _STREAM_EVIDENCE.get(stream_name, [])
        has_data = False
        for table in evidence_tables:
            if _check_table_has_data(db_path, project_id, table):
                has_data = True
                break

        results[stream_name] = "completed" if has_data else "skipped"

    return results


def _update_all_stream_statuses(
    db_path: Path,
    project_id: str,
    statuses: dict[str, str],
) -> None:
    """Update stream_status table with final statuses.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        statuses: Mapping of stream_name to final status.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        for stream_name, status in statuses.items():
            existing = fetch_one(
                conn,
                "SELECT id FROM stream_status "
                "WHERE project_id = ? AND stream_name = ?",
                (project_id, stream_name),
            )
            if existing:
                execute(
                    conn,
                    "UPDATE stream_status SET status = ?, "
                    "completed_at = datetime('now') "
                    "WHERE project_id = ? AND stream_name = ?",
                    (status, project_id, stream_name),
                )
            else:
                execute(
                    conn,
                    "INSERT INTO stream_status "
                    "(project_id, stream_name, status, completed_at) "
                    "VALUES (?, ?, ?, datetime('now'))",
                    (project_id, stream_name, status),
                )
        conn.commit()
    finally:
        conn.close()


def _compute_degradation_note(statuses: dict[str, str]) -> str:
    """Generate a human-readable degradation note for failed/skipped streams.

    Args:
        statuses: Final stream statuses.

    Returns:
        Degradation description, or empty string if all completed.
    """
    failed = [name for name, st in statuses.items() if st == "failed"]
    skipped = [name for name, st in statuses.items() if st == "skipped"]

    parts: list[str] = []
    if failed:
        parts.append(f"Failed streams: {', '.join(sorted(failed))}")
    if skipped:
        parts.append(f"Skipped streams: {', '.join(sorted(skipped))}")

    if not parts:
        return ""

    return ". ".join(parts) + "."


def _set_project_status(
    db_path: Path,
    project_id: str,
    status: str,
    degradation_note: str,
) -> None:
    """Update the project status in the project table.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        status: New project status ('ready' or 'error').
        degradation_note: Description of degraded streams.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        execute(
            conn,
            "UPDATE project SET status = ?, updated_at = datetime('now') "
            "WHERE project_id = ?",
            (status, project_id),
        )
        conn.commit()
    finally:
        conn.close()

    if degradation_note:
        logger.warning(
            "Project %s finalized with degradation: %s",
            project_id, degradation_note,
        )


def _cleanup_temp_files(project_dir: Path) -> int:
    """Remove ephemeral temporary files from the project directory.

    Cleans up:
    - *.tmp files
    - *.part files
    - __pycache__ directories

    Args:
        project_dir: Path to the project directory.

    Returns:
        Number of items cleaned up.
    """
    cleaned = 0
    if not project_dir.exists():
        return cleaned

    for pattern in ("*.tmp", "*.part", "*.temp"):
        for f in project_dir.rglob(pattern):
            try:
                f.unlink()
                cleaned += 1
            except OSError as exc:
                logger.warning("Failed to remove temp file %s: %s", f, exc)

    for cache_dir in project_dir.rglob("__pycache__"):
        try:
            shutil.rmtree(cache_dir)
            cleaned += 1
        except OSError as exc:
            logger.warning(
                "Failed to remove cache dir %s: %s", cache_dir, exc,
            )

    return cleaned


async def run_finalize(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the finalize pipeline stage.

    This is a REQUIRED stage. It:
    1. Updates stream_status for all tracked streams
    2. Computes degradation notes for failed/skipped streams
    3. Verifies the entire provenance chain
    4. Sets project status to 'ready' or 'error'
    5. Cleans up ephemeral temp files
    6. Writes a final provenance record

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.

    Raises:
        PipelineError: If finalization fails critically.
    """
    start_time = time.monotonic()

    try:
        # 1. Determine and update all stream statuses
        statuses = await asyncio.to_thread(
            _determine_stream_statuses, db_path, project_id,
        )
        await asyncio.to_thread(
            _update_all_stream_statuses, db_path, project_id, statuses,
        )

        completed_count = sum(1 for s in statuses.values() if s == "completed")
        failed_count = sum(1 for s in statuses.values() if s == "failed")
        skipped_count = sum(1 for s in statuses.values() if s == "skipped")

        logger.info(
            "Stream statuses: %d completed, %d failed, %d skipped",
            completed_count, failed_count, skipped_count,
        )

        # 2. Compute degradation note
        degradation_note = _compute_degradation_note(statuses)

        # 3. Verify provenance chain
        chain_result = await asyncio.to_thread(
            verify_chain, project_id, db_path,
        )

        if not chain_result.verified:
            error_detail = (
                f"Provenance chain verification failed: {chain_result.issue}"
            )
            logger.error(error_detail)
            await asyncio.to_thread(
                _set_project_status, db_path, project_id, "error",
                error_detail,
            )
            raise PipelineError(
                error_detail,
                stage_name=STAGE,
                operation=OPERATION,
            )

        logger.info(
            "Provenance chain verified: %d records OK",
            chain_result.total_records,
        )

        # 4. Set project status to 'ready'
        await asyncio.to_thread(
            _set_project_status, db_path, project_id, "ready",
            degradation_note,
        )

        # 5. Clean up temp files
        cleaned = await asyncio.to_thread(
            _cleanup_temp_files, project_dir,
        )
        if cleaned > 0:
            logger.info("Cleaned up %d ephemeral files", cleaned)

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # 6. Write final provenance record
        summary = (
            f"Finalized: {completed_count}/{len(statuses)} streams completed, "
            f"{chain_result.total_records} provenance records verified"
        )
        if degradation_note:
            summary += f". {degradation_note}"

        output_sha = sha256_string(summary)

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                sha256=sha256_string(f"finalize-{project_id}"),
            ),
            output_info=OutputInfo(
                sha256=output_sha,
                record_count=completed_count,
            ),
            model_info=None,
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=f"Pipeline finalized: {summary}",
        )

        logger.info(
            "Finalize complete in %d ms: status=ready, %s",
            elapsed_ms, summary,
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )

    except PipelineError:
        raise
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Finalize failed: %s", error_msg)
        raise PipelineError(
            f"Required stage 'finalize' failed: {error_msg}",
            stage_name=STAGE,
            operation=OPERATION,
        ) from exc
