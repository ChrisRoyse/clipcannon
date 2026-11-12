"""Highlight persistence and the run_highlights stage entry point."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert
from clipcannon.pipeline.highlights_loaders import (
    _get_duration_ms,
    _load_emotion_curve,
    _load_reactions,
    _load_scenes,
    _load_segments_with_speakers,
    _load_topics,
)
from clipcannon.pipeline.highlights_scoring import _score_candidates
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)

OPERATION = "highlight_scoring"
STAGE = "highlights"


def _insert_highlights(
    db_path: Path,
    project_id: str,
    highlights: list[dict[str, int | float | str]],
) -> int:
    """Insert highlight records into the database.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        highlights: Highlight dicts to insert.

    Returns:
        Number of highlights inserted.
    """
    if not highlights:
        return 0

    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        rows: list[tuple[object, ...]] = [
            (
                project_id,
                int(h["start_ms"]),
                int(h["end_ms"]),
                str(h["type"]),
                float(h["score"]),
                str(h["reason"]),
                float(h["emotion_score"]),
                float(h["reaction_score"]),
                float(h["semantic_score"]),
                float(h["narrative_score"]),
                float(h["visual_score"]),
                float(h["quality_score"]),
                float(h["speaker_score"]),
            )
            for h in highlights
        ]
        batch_insert(
            conn,
            "highlights",
            [
                "project_id",
                "start_ms",
                "end_ms",
                "type",
                "score",
                "reason",
                "emotion_score",
                "reaction_score",
                "semantic_score",
                "narrative_score",
                "visual_score",
                "quality_score",
                "speaker_score",
            ],
            rows,
        )
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def run_highlights(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the multi-signal highlight scoring pipeline stage.

    Scores candidate windows using seven weighted signals and selects
    the top-N highlights.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    start_time = time.monotonic()

    try:
        duration_ms = await asyncio.to_thread(
            _get_duration_ms,
            db_path,
            project_id,
        )
        if duration_ms <= 0:
            logger.warning("No duration found, skipping highlight scoring")
            return StageResult(
                success=True,
                operation=OPERATION,
                error_message="Skipped: no duration data",
            )

        # Determine max highlights from config
        # No silent default (#68): a missing/invalid key raises ConfigError.
        max_highlights = int(config.get("processing.highlight_count_default"))

        # Load all signal data in parallel
        emotions, reactions, topics, scenes, segments = await asyncio.gather(
            asyncio.to_thread(_load_emotion_curve, db_path, project_id),
            asyncio.to_thread(_load_reactions, db_path, project_id),
            asyncio.to_thread(_load_topics, db_path, project_id),
            asyncio.to_thread(_load_scenes, db_path, project_id),
            asyncio.to_thread(
                _load_segments_with_speakers,
                db_path,
                project_id,
            ),
        )

        # Score candidates
        highlights = _score_candidates(
            duration_ms,
            emotions,
            reactions,
            topics,
            scenes,
            segments,
            max_highlights,
        )

        # Insert
        count = await asyncio.to_thread(
            _insert_highlights,
            db_path,
            project_id,
            highlights,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Build provenance
        top_score = highlights[0]["score"] if highlights else 0.0
        summary = (
            f"{count} highlights selected (top score={top_score}), max_requested={max_highlights}"
        )
        output_sha = sha256_string(summary)

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                sha256=sha256_string(f"highlights-{project_id}"),
            ),
            output_info=OutputInfo(
                sha256=output_sha,
                record_count=count,
            ),
            model_info=None,
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=f"Highlight scoring: {summary}",
        )

        logger.info(
            "Highlight scoring complete in %d ms: %s",
            elapsed_ms,
            summary,
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Highlight scoring failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
        )
