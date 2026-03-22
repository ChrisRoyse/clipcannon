"""OCR on-screen text detection pipeline stage.

Runs EasyOCR on extracted frames at 1fps to detect on-screen text,
deduplicates consecutive identical text, classifies text regions by
position, and detects slide-transition events.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert
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
STAGE = "easyocr"


def _classify_region(
    bbox: list[list[float]],
    img_width: int,
    img_height: int,
) -> str:
    """Classify text region based on bounding box position.

    Args:
        bbox: Bounding box as list of 4 corner points [[x,y], ...].
        img_width: Image width in pixels.
        img_height: Image height in pixels.

    Returns:
        Region classification string.
    """
    if not bbox or len(bbox) < 4:
        return "unknown"

    # Compute center of bounding box
    y_coords = [pt[1] for pt in bbox]
    y_center = sum(y_coords) / len(y_coords)
    relative_y = y_center / img_height if img_height > 0 else 0.5

    if relative_y < 0.25:
        return "center_top"
    elif relative_y < 0.67:
        return "center_middle"
    elif relative_y < 0.85:
        return "bottom_third"
    else:
        return "full_screen"


def _estimate_font_size(bbox: list[list[float]], img_height: int) -> str:
    """Estimate font size category from bounding box height.

    Args:
        bbox: Bounding box as list of 4 corner points.
        img_height: Image height in pixels.

    Returns:
        Font size classification: "small", "medium", or "large".
    """
    if not bbox or len(bbox) < 4:
        return "medium"

    y_coords = [pt[1] for pt in bbox]
    bbox_height = max(y_coords) - min(y_coords)
    relative_height = bbox_height / img_height if img_height > 0 else 0.0

    if relative_height < 0.03:
        return "small"
    elif relative_height < 0.08:
        return "medium"
    else:
        return "large"


def _frame_timestamp_ms(frame_path: Path, fps: int) -> int:
    """Compute timestamp in ms from frame filename and extraction fps.

    Args:
        frame_path: Path like frame_000001.jpg (1-indexed).
        fps: Frame extraction rate (e.g. 2).

    Returns:
        Timestamp in milliseconds.
    """
    stem = frame_path.stem
    frame_number = int(stem.split("_")[1])
    return int((frame_number - 1) * 1000 / fps)


def _texts_differ_significantly(
    prev_texts: list[str],
    curr_texts: list[str],
) -> bool:
    """Check if text content changed significantly between frames.

    Args:
        prev_texts: Previous frame text list.
        curr_texts: Current frame text list.

    Returns:
        True if significant text change detected.
    """
    if not prev_texts and not curr_texts:
        return False
    if not prev_texts or not curr_texts:
        return True

    prev_set = set(prev_texts)
    curr_set = set(curr_texts)
    overlap = prev_set & curr_set
    total = prev_set | curr_set

    if not total:
        return False

    # More than 50% change is significant
    return len(overlap) / len(total) < 0.5


def _run_ocr_on_frames(
    frame_paths: list[Path],
    extraction_fps: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Run EasyOCR on frames and return text records + change events.

    Args:
        frame_paths: Paths to frames to process (1fps subset).
        extraction_fps: Original frame extraction rate.

    Returns:
        Tuple of (text_records, change_events).

    Raises:
        ImportError: If EasyOCR is not available.
    """
    try:
        import easyocr  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "EasyOCR not installed. Install with: pip install easyocr"
        ) from exc

    from PIL import Image

    reader = easyocr.Reader(["en"], gpu=True, verbose=False)

    text_records: list[dict[str, object]] = []
    change_events: list[dict[str, object]] = []
    prev_texts: list[str] = []

    for fp in frame_paths:
        ts_ms = _frame_timestamp_ms(fp, extraction_fps)

        try:
            img = Image.open(fp)
            img_width, img_height = img.size
        except Exception as exc:
            logger.warning("Failed to open frame %s: %s", fp, exc)
            continue

        # EasyOCR returns list of (bbox, text, confidence)
        # bbox is [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        result = reader.readtext(str(fp))

        curr_texts: list[str] = []
        frame_text_entries: list[dict[str, str]] = []

        for bbox, text, confidence in result:
            if confidence < 0.5:
                continue

            curr_texts.append(text)
            region = _classify_region(bbox, img_width, img_height)
            font_size = _estimate_font_size(bbox, img_height)

            frame_text_entries.append(
                {
                    "text": text,
                    "confidence": str(round(confidence, 3)),
                    "region": region,
                    "font_size": font_size,
                }
            )

        # Deduplicate: skip if identical to previous frame
        if curr_texts == prev_texts:
            continue

        # Check for significant change (slide transition)
        changed = _texts_differ_significantly(prev_texts, curr_texts)

        if curr_texts:
            text_records.append(
                {
                    "start_ms": ts_ms,
                    "end_ms": ts_ms + int(1000 / extraction_fps),
                    "texts": json.dumps(frame_text_entries),
                    "type": "detected",
                    "change_from_previous": changed,
                }
            )

        if changed and prev_texts:
            title = curr_texts[0] if curr_texts else ""
            change_events.append(
                {
                    "timestamp_ms": ts_ms,
                    "type": "slide_transition",
                    "new_title": title,
                }
            )

        prev_texts = curr_texts

    return text_records, change_events


async def run_ocr(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute PaddleOCR text detection on extracted frames.

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

        # Process at 1fps: take every other frame (since extraction is 2fps)
        step = max(1, extraction_fps)
        ocr_frames = all_frames[::step]

        logger.info(
            "Running OCR on %d frames (1fps from %d total at %dfps)",
            len(ocr_frames),
            len(all_frames),
            extraction_fps,
        )

        # Run OCR in thread pool (blocking operation)
        text_records, change_events = await asyncio.to_thread(
            _run_ocr_on_frames,
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
                name="EasyOCR",
                version="1.7",
                parameters={
                    "lang": "en",
                    "use_angle_cls": True,
                    "frames_processed": len(ocr_frames),
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
        error_msg = f"EasyOCR not available: {exc}"
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
