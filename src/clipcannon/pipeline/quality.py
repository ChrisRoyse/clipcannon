"""Quality assessment pipeline stage for ClipCannon.

Two instruments, never written to the same column:

- ``brisque`` (pyiqa, when installed): ``scenes.quality_avg/_min`` on a
  0-100 scale (100 - BRISQUE raw, higher = better), plus
  ``quality_classification`` from BRISQUE-calibrated thresholds.
- ``laplacian_variance`` (when pyiqa is not installed): raw variance of the
  4-neighbour Laplacian of 512 px luma in ``scenes.sharpness_avg/_min``.
  It is a blur measure, not a quality score, so no classification.

Every scored scene names its instrument in ``scenes.quality_instrument``;
the stage clears both column sets first so a re-run never leaves readings
from two instruments on one project.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import time
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all
from clipcannon.db.schema_migrations import migrate_to_v5
from clipcannon.pipeline.frame_utils import frame_timestamp_ms
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

BRISQUE = "brisque"
LAPLACIAN = "laplacian_variance"

# Quality classification thresholds (BRISQUE 0-100 scale only)
GOOD_THRESHOLD = 60.0
ACCEPTABLE_THRESHOLD = 40.0

# Issue thresholds per instrument, each on its own scale:
# (heavy_blur below, camera_shake when mean consecutive diff exceeds).
# Laplacian blur 300 is what the old /10 mapping applied (30 -> 300). Its raw
# variance is unbounded, so frame-to-frame diffs say nothing about shake: None.
ISSUE_THRESHOLDS: dict[str, tuple[float, float | None]] = {
    BRISQUE: (30.0, 20.0),
    LAPLACIAN: (300.0, None),
}


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
    if score > ACCEPTABLE_THRESHOLD:
        return "acceptable"
    return "poor"


def _detect_issues(scores: list[float], instrument: str) -> list[str]:
    """Detect blur/shake issues using the instrument's own thresholds."""
    issues: list[str] = []
    if not scores:
        return issues
    blur_below, shake_above = ISSUE_THRESHOLDS[instrument]
    if min(scores) < blur_below:
        issues.append("heavy_blur")
    if shake_above is not None and len(scores) >= 3:
        diffs = [abs(scores[i] - scores[i - 1]) for i in range(1, len(scores))]
        if sum(diffs) / len(diffs) > shake_above:
            issues.append("camera_shake")
    return issues


def _select_instrument() -> tuple[str, str]:
    """Pick the instrument by installation, before running anything.

    Deciding up front means an ImportError raised *inside* a BRISQUE run
    (torch, torchvision) fails the stage instead of switching instruments.
    """
    if importlib.util.find_spec("pyiqa") is not None:
        import pyiqa  # type: ignore[import-untyped]

        return BRISQUE, f"pyiqa-{getattr(pyiqa, '__version__', 'unknown')}"
    return LAPLACIAN, "4-neighbour-512px-luma"


def _write_scene_scores(
    db_path: Path,
    project_id: str,
    instrument: str,
    frame_scores: dict[int, float],
) -> int:
    """Clear both instruments' columns, then write this run's readings.

    Returns:
        Number of scenes that received a reading.

    Raises:
        RuntimeError: If scenes exist but no frame fell inside any of them.
    """
    migrate_to_v5(db_path)
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        scenes = fetch_all(
            conn,
            "SELECT scene_id, start_ms, end_ms FROM scenes WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        execute(
            conn,
            "UPDATE scenes SET quality_avg = NULL, quality_min = NULL,"
            " quality_classification = NULL, quality_issues = NULL,"
            " quality_instrument = NULL, sharpness_avg = NULL, sharpness_min = NULL"
            " WHERE project_id = ?",
            (project_id,),
        )
        scored = 0
        for scene in scenes:
            start_ms, end_ms = int(scene["start_ms"]), int(scene["end_ms"])  # type: ignore[arg-type]
            vals = [s for ts, s in sorted(frame_scores.items()) if start_ms <= ts <= end_ms]
            if not vals:
                continue
            avg, low = round(sum(vals) / len(vals), 2), round(min(vals), 2)
            issues = _detect_issues(vals, instrument)
            issues_json = json.dumps(issues) if issues else None
            if instrument == BRISQUE:
                sql = (
                    "UPDATE scenes SET quality_avg = ?, quality_min = ?,"
                    " quality_classification = ?, quality_issues = ?,"
                    " quality_instrument = ? WHERE scene_id = ?"
                )
                params: tuple[object, ...] = (
                    avg, low, _classify_quality(avg), issues_json, instrument, scene["scene_id"],
                )
            else:
                sql = (
                    "UPDATE scenes SET sharpness_avg = ?, sharpness_min = ?,"
                    " quality_issues = ?, quality_instrument = ? WHERE scene_id = ?"
                )
                params = (avg, low, issues_json, instrument, scene["scene_id"])
            execute(conn, sql, params)
            scored += 1
        if scenes and scored == 0:
            raise RuntimeError(
                f"{len(scenes)} scenes but no scored frame fell inside any scene; "
                "frame timestamps and scene ranges disagree"
            )
        conn.commit()
        return scored
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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

    transform = transforms.ToTensor()

    quality_scores: list[float] = []
    batch_size = 16
    total_frames = len(frame_paths)
    max_quality_dim = 512

    for batch_start in range(0, total_frames, batch_size):
        batch_paths = frame_paths[batch_start : batch_start + batch_size]
        batch_tensors: list[object] = []

        for fp in batch_paths:
            try:
                img = Image.open(fp).convert("RGB")
                # Downsample large frames for quality scoring
                # BRISQUE works fine at 512px - no need for 4K
                if max(img.size) > max_quality_dim:
                    ratio = max_quality_dim / max(img.size)
                    new_size = (int(img.width * ratio), int(img.height * ratio))
                    img = img.resize(new_size, Image.LANCZOS)
                tensor = transform(img).unsqueeze(0).to(device)
                batch_tensors.append(tensor)
            except Exception as exc:
                raise RuntimeError(f"Quality: cannot load frame {fp}: {exc}") from exc

        for tensor in batch_tensors:
            # No 50.0 placeholder (#68): a failed score fails the stage.
            with torch.no_grad():
                brisque_raw = metric(tensor).item()
            quality_scores.append(_brisque_to_quality(brisque_raw))

        # Progress logging every 100 frames
        scored_so_far = len(quality_scores)
        if scored_so_far % 100 < batch_size or scored_so_far == total_frames:
            logger.info(
                "Quality scoring progress: %d/%d frames (%.0f%%)",
                scored_so_far,
                total_frames,
                scored_so_far / total_frames * 100,
            )

    # Clean up GPU memory — model stays loaded otherwise
    del metric
    import gc

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    logger.info("BRISQUE model unloaded, GPU memory released")

    return quality_scores


def _run_laplacian_scoring(frame_paths: list[Path]) -> list[float]:
    """Laplacian variance (blur measure) per frame.

    Args:
        frame_paths: Paths to frame files.

    Returns:
        Raw Laplacian variance of each frame's 512 px luma.
    """
    import numpy as np
    from PIL import Image

    logger.info("pyiqa not installed: measuring sharpness (Laplacian variance), not BRISQUE")

    quality_scores: list[float] = []
    total_frames = len(frame_paths)
    max_quality_dim = 512

    for idx, fp in enumerate(frame_paths):
        try:
            img = Image.open(fp).convert("L")
            # Downsample large frames - Laplacian works fine at 512px
            if max(img.size) > max_quality_dim:
                ratio = max_quality_dim / max(img.size)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
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

            # Raw variance, unclamped: blurry ~0-100, sharp 500+. Not a
            # 0-100 quality score, so it is stored in sharpness_* only.
            quality_scores.append(float(np.var(laplacian)))

        except Exception as exc:
            raise RuntimeError(f"Laplacian scoring failed for {fp}: {exc}") from exc

        # Progress logging every 100 frames
        scored_so_far = idx + 1
        if scored_so_far % 100 == 0 or scored_so_far == total_frames:
            logger.info(
                "Laplacian scoring progress: %d/%d frames (%.0f%%)",
                scored_so_far,
                total_frames,
                scored_so_far / total_frames * 100,
            )

    return quality_scores


async def run_quality(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute quality assessment on all frames and update scene records.

    BRISQUE when pyiqa is installed (scenes.quality_*), otherwise Laplacian
    variance (scenes.sharpness_*); see the module docstring.

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

        model_name, model_version = _select_instrument()
        if model_name == BRISQUE:
            quality_scores = await asyncio.to_thread(_run_pyiqa_scoring, frame_paths, device)
        else:
            quality_scores = await asyncio.to_thread(_run_laplacian_scoring, frame_paths)

        frame_quality = {
            frame_timestamp_ms(fp, extraction_fps): score
            for fp, score in zip(frame_paths, quality_scores, strict=True)
        }
        scenes_scored = await asyncio.to_thread(
            _write_scene_scores, db_path, project_id, model_name, frame_quality
        )
        logger.info("Wrote %s readings to %d scenes", model_name, scenes_scored)

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
        columns = "quality_*" if model_name == BRISQUE else "sharpness_*"
        verdict = f" ({_classify_quality(avg_quality)})" if model_name == BRISQUE else ""

        content_hash = sha256_string(
            f"quality:{model_name}:frames={len(quality_scores)},avg={avg_quality:.2f}",
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
                    "scenes_scored": scenes_scored,
                    "columns": columns,
                    "frame_avg": round(avg_quality, 2),
                },
            ),
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=(
                f"Quality assessment [{model_name} -> scenes.{columns}]: "
                f"{len(quality_scores)} frames, {scenes_scored} scenes, "
                f"avg={avg_quality:.1f}{verdict}"
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
