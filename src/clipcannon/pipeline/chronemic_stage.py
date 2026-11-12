"""The run_chronemic stage entry point."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from clipcannon.pipeline.chronemic_data import (
    _get_duration_ms,
    _insert_pacing,
    _load_segments_with_speakers,
    _load_silence_gaps,
    _load_transcript_words,
)
from clipcannon.pipeline.chronemic_math import _compute_pacing_windows
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

OPERATION = "chronemic_analysis"
STAGE = "chronemic"


async def run_chronemic(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the chronemic/pacing computation pipeline stage.

    Computes words-per-minute, pause ratio, speaker changes, and
    pacing labels for each 60-second window.

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
            logger.warning("No duration found, skipping chronemic analysis")
            return StageResult(
                success=True,
                operation=OPERATION,
                error_message="Skipped: no duration data",
            )

        words = await asyncio.to_thread(
            _load_transcript_words,
            db_path,
            project_id,
        )
        gaps = await asyncio.to_thread(
            _load_silence_gaps,
            db_path,
            project_id,
        )
        segments = await asyncio.to_thread(
            _load_segments_with_speakers,
            db_path,
            project_id,
        )

        windows = _compute_pacing_windows(duration_ms, words, gaps, segments)

        count = await asyncio.to_thread(
            _insert_pacing,
            db_path,
            project_id,
            windows,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Compute summary for provenance
        labels: dict[str, int] = {}
        for w in windows:
            lbl = str(w["label"])
            labels[lbl] = labels.get(lbl, 0) + 1

        summary = f"{count} windows: " + ", ".join(f"{k}={v}" for k, v in sorted(labels.items()))
        output_sha = sha256_string(summary)

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                sha256=sha256_string(f"chronemic-{project_id}"),
            ),
            output_info=OutputInfo(
                sha256=output_sha,
                record_count=count,
            ),
            model_info=None,
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=f"Chronemic analysis: {summary}",
        )

        logger.info(
            "Chronemic analysis complete in %d ms: %s",
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
        logger.error("Chronemic analysis failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
        )
