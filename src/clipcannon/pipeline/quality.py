"""Quality assessment pipeline stage for ClipCannon.

Uses pyiqa BRISQUE scoring for GPU-accelerated image quality assessment.
Falls back to Laplacian variance blur detection when pyiqa is unavailable.

BRISQUE is an inverse quality metric (lower = better). We convert to
a 0-100 scale where 100 = best quality using:
    quality_score = max(0, min(100, 100 - brisque_raw))
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all
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

OPERATION = "quality_assessment"
STAGE = "brisque"

# Quality classification thresholds
GOOD_THRESHOLD = 60.0
ACCEPTABLE_THRESHOLD = 40.0
POOR_THRESHOLD = 40.0
BLUR_THRESHOLD = 30.0

# Camera shake detection: if std dev of consecutive quality > this value
SHAKE_VARIANCE_THRESHOLD = 20.0


def _brisque_to_quality(brisque_raw: float) -> float:
    """Convert BRISQUE raw score to 0-100 quality scale.

    BRISQUE is inverse (lower = better). We map to 0-100 where 100 = best.

    Args:
        brisque_raw: Raw BRISQUE score.

    Returns:
        Quality score in [0, 100].
    """
    return max(0.0, min(100.0, 100.0 - brisque_raw))


def _classify_quality(score: float) -> str:
    """Classify a quality score into a category.

    Args:
        score: Quality score in [0, 100].

    Returns:
        Classification string: "good", "acceptable", or "poor".
    """
    if score > GOOD_THRESHOLD:
        return "good"
    elif score > ACCEPTABLE_THRESHOLD:
        return "acceptable"
    else:
        return "poor"


def _detect_issues(
    scores: list[float],
) -> list[str]:
    """Detect quality issues from a sequence of scores.

    Args:
        scores: List of quality scores for frames in a scene.

    Returns:
        List of issue strings.
    """
    issues: list[str] = []

    if not scores:
        return issues

    # Check for heavy blur
    min_score = min(scores)
    if min_score < BLUR_THRESHOLD:
        issues.append("heavy_blur")

    # Check for camera shake (high variance between consecutive frames)
    if len(scores) >= 3:
        diffs = [abs(scores[i] - scores[i - 1]) for i in range(1, len(scores))]
        avg_diff = sum(diffs) / len(diffs) if diffs else 0.0
        if avg_diff > SHAKE_VARIANCE_THRESHOLD:
            issues.append("camera_shake")

    return issues


def _run_pyiqa_scoring(
    frame_paths: list[Path],
    device: str,
) -> list[float]:
    """Run pyiqa BRISQUE scoring on all frames.

    Args:
        frame_paths: Paths to frame files.
        device: Torch device string.

    Returns:
        List of quality scores (0-100 scale) for each frame.

    Raises:
        ImportError: If pyiqa is not installed.
    """
    import pyiqa  # type: ignore[import-untyped]
    import torch
    from PIL import Image
    from torchvision import transforms

    logger.info("Loading pyiqa BRISQUE model on device=%s", device)

    if not torch.cuda.is_available():
        device = "cpu"

    metric = pyiqa.create_metric("brisque", device=device)

    transform = transforms.Compose(
        [
            transforms.ToTensor(),
        ]
    )

    quality_scores: list[float] = []
    batch_size = 16

    for batch_start in range(0, len(frame_paths), batch_size):
        batch_paths = frame_paths[batch_start : batch_start + batch_size]
        batch_tensors: list[object] = []

        for fp in batch_paths:
            try:
                img = Image.open(fp).convert("RGB")
                tensor = transform(img).unsqueeze(0).to(device)
                batch_tensors.append(tensor)
            except Exception as exc:
                logger.warning("Failed to load frame %s: %s", fp, exc)
                batch_tensors.append(None)

        for tensor in batch_tensors:
            if tensor is None:
                quality_scores.append(50.0)  # Default for failed frames
                continue

            try:
                with torch.no_grad():
                    brisque_raw = metric(tensor).item()
                quality_scores.append(_brisque_to_quality(brisque_raw))
            except Exception as exc:
                logger.warning("BRISQUE scoring failed: %s", exc)
                quality_scores.append(50.0)

    return quality_scores


def _run_laplacian_fallback(frame_paths: list[Path]) -> list[float]:
    """Fallback quality scoring using Laplacian variance for blur detection.

    Args:
        frame_paths: Paths to frame files.

    Returns:
        List of quality scores (0-100 scale) for each frame.
    """
    import numpy as np
    from PIL import Image

    logger.info("Using Laplacian variance fallback for quality assessment")

    quality_scores: list[float] = []

    for fp in frame_paths:
        try:
            img = Image.open(fp).convert("L")
            img_array = np.array(img, dtype=np.float64)

            # Laplacian kernel
            kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)

            # Simple convolution for Laplacian
            h, w = img_array.shape
            padded = np.pad(img_array, 1, mode="edge")
            laplacian = np.zeros_like(img_array)

            for di in range(3):
                for dj in range(3):
                    laplacian += padded[di : di + h, dj : dj + w] * kernel[di, dj]

            variance = float(np.var(laplacian))

            # Map variance to 0-100 quality score
            # Typical range: blurry=0-100, sharp=500+
            score = max(0.0, min(100.0, variance / 10.0))
            quality_scores.append(score)

        except Exception as exc:
            logger.warning("Laplacian scoring failed for %s: %s", fp, exc)
            quality_scores.append(50.0)

    return quality_scores


def _frame_timestamp_ms(frame_path: Path, fps: int) -> int:
    """Compute timestamp in ms from frame filename.

    Args:
        frame_path: Path like frame_000001.jpg (1-indexed).
        fps: Frame extraction rate.

    Returns:
        Timestamp in milliseconds.
    """
    stem = frame_path.stem
    frame_number = int(stem.split("_")[1])
    return int((frame_number - 1) * 1000 / fps)


async def run_quality(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute quality assessment on all frames and update scene records.

    Uses pyiqa BRISQUE if available, falls back to Laplacian variance.
    Updates each scene with quality_avg, quality_min, quality_classification,
    and quality_issues.

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
        frames_dir = project_dir / "frames"
        frame_paths = sorted(frames_dir.glob("frame_*.jpg"))

        if not frame_paths:
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message="No frames found for quality assessment",
            )

        extraction_fps = int(config.get("processing.frame_extraction_fps"))
        device = str(config.get("gpu.device"))

        logger.info(
            "Starting quality assessment: %d frames",
            len(frame_paths),
        )

        # Try pyiqa first, fall back to Laplacian
        model_name = "brisque"
        model_version = "pyiqa"

        try:
            quality_scores = await asyncio.to_thread(
                _run_pyiqa_scoring,
                frame_paths,
                device,
            )
            logger.info("Quality scoring completed with pyiqa BRISQUE")
        except ImportError:
            logger.warning("pyiqa not available, using Laplacian fallback")
            quality_scores = await asyncio.to_thread(
                _run_laplacian_fallback,
                frame_paths,
            )
            model_name = "laplacian_variance"
            model_version = "fallback"

        # Build frame -> quality mapping
        frame_quality: dict[int, float] = {}
        for fp, score in zip(frame_paths, quality_scores, strict=False):
            ts_ms = _frame_timestamp_ms(fp, extraction_fps)
            frame_quality[ts_ms] = score

        # Fetch scenes and update with quality metrics
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            scenes = fetch_all(
                conn,
                "SELECT scene_id, start_ms, end_ms FROM scenes "
                "WHERE project_id = ? ORDER BY start_ms",
                (project_id,),
            )

            if not scenes:
                logger.warning("No scenes found to update with quality scores")
            else:
                for scene in scenes:
                    scene_id = int(scene["scene_id"])  # type: ignore[arg-type]
                    start_ms = int(scene["start_ms"])  # type: ignore[arg-type]
                    end_ms = int(scene["end_ms"])  # type: ignore[arg-type]

                    # Collect quality scores for frames in this scene
                    scene_scores: list[float] = [
                        score for ts, score in frame_quality.items() if start_ms <= ts <= end_ms
                    ]

                    if not scene_scores:
                        continue

                    q_avg = sum(scene_scores) / len(scene_scores)
                    q_min = min(scene_scores)
                    classification = _classify_quality(q_avg)
                    issues = _detect_issues(scene_scores)

                    execute(
                        conn,
                        "UPDATE scenes SET quality_avg = ?, quality_min = ?, "
                        "quality_classification = ?, quality_issues = ? "
                        "WHERE scene_id = ?",
                        (
                            round(q_avg, 2),
                            round(q_min, 2),
                            classification,
                            json.dumps(issues) if issues else None,
                            scene_id,
                        ),
                    )

                conn.commit()
                logger.info("Updated %d scenes with quality metrics", len(scenes))
        finally:
            conn.close()

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

        content_hash = sha256_string(
            f"quality:frames={len(quality_scores)},avg={avg_quality:.2f}",
        )

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path=str(frames_dir),
                sha256=sha256_string(
                    "\n".join(f.name for f in frame_paths),
                ),
            ),
            output_info=OutputInfo(
                sha256=content_hash,
                record_count=len(quality_scores),
            ),
            model_info=ModelInfo(
                name=model_name,
                version=model_version,
                parameters={
                    "frames_scored": len(quality_scores),
                    "avg_quality": round(avg_quality, 2),
                },
            ),
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=(
                f"Quality assessment: {len(quality_scores)} frames, "
                f"avg={avg_quality:.1f} ({_classify_quality(avg_quality)})"
            ),
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Quality assessment failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
            duration_ms=elapsed_ms,
        )
