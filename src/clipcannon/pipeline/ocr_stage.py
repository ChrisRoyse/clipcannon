"""The run_ocr stage entry point."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert
from clipcannon.pipeline.ocr_engine import _run_paddleocr_on_frames
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)

OPERATION = "ocr_detection"
STAGE = "paddleocr"


async def run_ocr(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute PaddleOCR PP-OCRv5 text detection on extracted frames.

    Processes frames at 1fps (every other frame from 2fps extraction),
    deduplicates consecutive identical text, and detects slide transitions.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    import asyncio

    start_time = time.monotonic()

    try:
        frames_dir = project_dir / "frames"
        all_frames = sorted(frames_dir.glob("frame_*.jpg"))

        if not all_frames:
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message="No frames found for OCR",
            )

        extraction_fps = int(config.get("processing.frame_extraction_fps"))

        # Sample frames for OCR. PaddleOCR processes ~1 frame/sec on CPU.
        # Cap at 240 frames to stay well within the 600s stage timeout.
        max_ocr_frames = 240
        step = max(1, extraction_fps)
        ocr_frames = all_frames[::step]
        if len(ocr_frames) > max_ocr_frames:
            further_step = max(1, len(ocr_frames) // max_ocr_frames)
            ocr_frames = ocr_frames[::further_step]

        logger.info(
            "Running OCR on %d frames (sampled from %d total at %dfps)",
            len(ocr_frames),
            len(all_frames),
            extraction_fps,
        )

        # Run OCR in thread pool (blocking operation)
        text_records, change_events = await asyncio.to_thread(
            _run_paddleocr_on_frames,
            ocr_frames,
            extraction_fps,
        )

        # Insert text records
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            if text_records:
                text_rows: list[tuple[object, ...]] = [
                    (
                        project_id,
                        rec["start_ms"],
                        rec["end_ms"],
                        rec["texts"],
                        rec["type"],
                        rec["change_from_previous"],
                    )
                    for rec in text_records
                ]
                batch_insert(
                    conn,
                    "on_screen_text",
                    ["project_id", "start_ms", "end_ms", "texts", "type", "change_from_previous"],
                    text_rows,
                )

            if change_events:
                event_rows: list[tuple[object, ...]] = [
                    (project_id, ev["timestamp_ms"], ev["type"], ev["new_title"])
                    for ev in change_events
                ]
                batch_insert(
                    conn,
                    "text_change_events",
                    ["project_id", "timestamp_ms", "type", "new_title"],
                    event_rows,
                )

            conn.commit()
        finally:
            conn.close()

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        logger.info(
            "OCR complete: %d text records, %d change events in %d ms",
            len(text_records),
            len(change_events),
            elapsed_ms,
        )

        content_hash = sha256_string(
            f"texts:{len(text_records)},events:{len(change_events)}",
        )

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path=str(frames_dir),
                sha256=sha256_string(
                    "\n".join(f.name for f in ocr_frames),
                ),
            ),
            output_info=OutputInfo(
                sha256=content_hash,
                record_count=len(text_records),
            ),
            model_info=ModelInfo(
                name="PaddleOCR-PP-OCRv5",
                version="3.4",
                parameters={
                    "lang": "en",
                    "frames_processed": len(ocr_frames),
                    "max_resolution": 1920,
                },
            ),
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=(
                f"OCR detected {len(text_records)} text regions, "
                f"{len(change_events)} slide transitions"
            ),
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )

    except ImportError as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        error_msg = f"PaddleOCR not available: {exc}"
        logger.warning("OCR stage skipped: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
            duration_ms=elapsed_ms,
        )
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("OCR stage failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
            duration_ms=elapsed_ms,
        )
