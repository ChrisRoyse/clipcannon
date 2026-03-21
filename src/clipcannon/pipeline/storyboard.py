"""Storyboard grid generation pipeline stage for ClipCannon.

Selects up to 720 frames at adaptive intervals, groups them into
3x3 grids (9 frames per grid), and generates composite JPEG images
with timestamp overlays. Produces at most 80 grid images.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, fetch_one
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

if TYPE_CHECKING:
    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)

OPERATION = "storyboard_generation"
STAGE = "storyboard_grids"
MAX_GRIDS = 80
MAX_SELECTED_FRAMES = 720
GRID_COLS = 3
GRID_ROWS = 3
CELLS_PER_GRID = GRID_COLS * GRID_ROWS  # 9
CELL_SIZE = 348
GRID_SIZE = CELL_SIZE * GRID_COLS  # 1044
JPEG_QUALITY = 80
TIMESTAMP_BAR_HEIGHT = 20


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


def _format_timestamp(ms: int) -> str:
    """Format milliseconds as HH:MM:SS.

    Args:
        ms: Timestamp in milliseconds.

    Returns:
        Formatted timestamp string.
    """
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"


def _select_frames(
    all_frames: list[Path],
    duration_ms: int,
    fps: int,
) -> list[Path]:
    """Select frames at adaptive intervals for storyboard.

    Computes an interval to cover the full video with at most
    MAX_SELECTED_FRAMES frames. Minimum interval is 0.5 seconds.

    Args:
        all_frames: All available frame files (sorted).
        duration_ms: Video duration in milliseconds.
        fps: Frame extraction rate.

    Returns:
        Selected subset of frame paths.
    """
    if len(all_frames) <= MAX_SELECTED_FRAMES:
        return all_frames

    duration_s = duration_ms / 1000.0
    interval_s = max(duration_s / MAX_SELECTED_FRAMES, 0.5)
    interval_frames = max(1, int(interval_s * fps))

    selected: list[Path] = []
    for i in range(0, len(all_frames), interval_frames):
        selected.append(all_frames[i])
        if len(selected) >= MAX_SELECTED_FRAMES:
            break

    return selected


def _generate_grid(
    frame_paths: list[Path],
    timestamps_ms: list[int],
    output_path: Path,
) -> bool:
    """Generate a single 3x3 storyboard grid image.

    Creates a 1044x1044 composite with 348x348 cells. Each cell
    shows a frame with a timestamp overlay bar in the top-left.

    Args:
        frame_paths: Up to 9 frame paths for this grid.
        timestamps_ms: Corresponding timestamps for each frame.
        output_path: Path to save the grid JPEG.

    Returns:
        True if the grid was generated successfully.
    """
    from PIL import Image, ImageDraw, ImageFont

    grid = Image.new("RGB", (GRID_SIZE, GRID_SIZE), color=(0, 0, 0))

    for idx, (fp, ts_ms) in enumerate(zip(frame_paths, timestamps_ms, strict=False)):
        row = idx // GRID_COLS
        col = idx % GRID_COLS

        try:
            cell_img = Image.open(fp).convert("RGB")
            cell_img = cell_img.resize(
                (CELL_SIZE, CELL_SIZE),
                Image.Resampling.LANCZOS,
            )
        except Exception as exc:
            logger.warning("Failed to load frame %s for grid: %s", fp, exc)
            # Create black cell for missing frames
            cell_img = Image.new("RGB", (CELL_SIZE, CELL_SIZE), color=(32, 32, 32))

        x_offset = col * CELL_SIZE
        y_offset = row * CELL_SIZE
        grid.paste(cell_img, (x_offset, y_offset))

        # Draw timestamp overlay
        draw = ImageDraw.Draw(grid)
        ts_text = _format_timestamp(ts_ms)

        # Try to get a small font; fall back to default
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except OSError:
            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 14
                )
            except OSError:
                font = ImageFont.load_default()

        # Measure text
        text_bbox = draw.textbbox((0, 0), ts_text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        # Semi-transparent bar background
        bar_width = text_width + 8
        bar_height = max(TIMESTAMP_BAR_HEIGHT, text_height + 6)
        bar_x = x_offset + 2
        bar_y = y_offset + 2

        # Draw bar overlay (dark semi-transparent)
        overlay = Image.new("RGBA", (bar_width, bar_height), (0, 0, 0, 160))
        grid_rgba = grid.convert("RGBA")
        grid_rgba.paste(overlay, (bar_x, bar_y), overlay)
        grid = grid_rgba.convert("RGB")

        # Redraw on the composited image
        draw = ImageDraw.Draw(grid)
        draw.text(
            (bar_x + 4, bar_y + 2),
            ts_text,
            fill=(255, 255, 255),
            font=font,
        )

    grid.save(str(output_path), "JPEG", quality=JPEG_QUALITY)
    return True


def _generate_storyboards(
    selected_frames: list[Path],
    timestamps_ms: list[int],
    storyboard_dir: Path,
) -> list[dict[str, object]]:
    """Generate all storyboard grid images.

    Args:
        selected_frames: Selected frame paths (up to 720).
        timestamps_ms: Timestamps for each selected frame.
        storyboard_dir: Output directory for grid images.

    Returns:
        List of grid metadata dicts with grid_number, path, timestamps.
    """
    storyboard_dir.mkdir(parents=True, exist_ok=True)

    grids: list[dict[str, object]] = []
    total_grids = min(
        MAX_GRIDS,
        (len(selected_frames) + CELLS_PER_GRID - 1) // CELLS_PER_GRID,
    )

    for grid_idx in range(total_grids):
        start = grid_idx * CELLS_PER_GRID
        end = min(start + CELLS_PER_GRID, len(selected_frames))
        batch_frames = selected_frames[start:end]
        batch_timestamps = timestamps_ms[start:end]

        grid_filename = f"grid_{grid_idx + 1:03d}.jpg"
        grid_path = storyboard_dir / grid_filename

        logger.info(
            "Generating storyboard grid %d/%d (%d frames)",
            grid_idx + 1,
            total_grids,
            len(batch_frames),
        )

        success = _generate_grid(batch_frames, batch_timestamps, grid_path)
        if success:
            grids.append(
                {
                    "grid_number": grid_idx + 1,
                    "grid_path": str(grid_path),
                    "cell_timestamps_ms": json.dumps(batch_timestamps),
                }
            )

    return grids


async def run_storyboard(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute storyboard grid generation.

    Selects up to 720 frames at adaptive intervals, generates 3x3
    composite grid images with timestamp overlays, and inserts grid
    metadata into the storyboard_grids table.

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
        storyboard_dir = project_dir / "storyboards"
        all_frames = sorted(frames_dir.glob("frame_*.jpg"))

        if not all_frames:
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message="No frames found for storyboard generation",
            )

        extraction_fps = int(config.get("processing.frame_extraction_fps"))

        # Get video duration from database
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(
                conn,
                "SELECT duration_ms FROM project WHERE project_id = ?",
                (project_id,),
            )
        finally:
            conn.close()

        duration_ms = int(row.get("duration_ms", 0)) if row else 0
        if duration_ms == 0:
            # Estimate from frame count
            duration_ms = int(len(all_frames) * 1000 / extraction_fps)

        # Select frames at adaptive intervals
        selected = _select_frames(all_frames, duration_ms, extraction_fps)

        # Compute timestamps for selected frames
        timestamps = [_frame_timestamp_ms(fp, extraction_fps) for fp in selected]

        logger.info(
            "Generating storyboards: %d frames selected from %d total (duration=%d ms, fps=%d)",
            len(selected),
            len(all_frames),
            duration_ms,
            extraction_fps,
        )

        # Generate grids in thread pool (PIL operations)
        grids = await asyncio.to_thread(
            _generate_storyboards,
            selected,
            timestamps,
            storyboard_dir,
        )

        if not grids:
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message="Failed to generate any storyboard grids",
            )

        # Insert grid metadata into database
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            grid_rows: list[tuple[object, ...]] = [
                (
                    project_id,
                    grid["grid_number"],
                    grid["grid_path"],
                    grid["cell_timestamps_ms"],
                )
                for grid in grids
            ]

            batch_insert(
                conn,
                "storyboard_grids",
                ["project_id", "grid_number", "grid_path", "cell_timestamps_ms"],
                grid_rows,
            )
            conn.commit()
            logger.info("Inserted %d storyboard grid records", len(grids))
        finally:
            conn.close()

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Compute total output size
        total_size = sum(
            Path(g["grid_path"]).stat().st_size  # type: ignore[arg-type]
            for g in grids
            if Path(g["grid_path"]).exists()  # type: ignore[arg-type]
        )

        content_hash = sha256_string(
            f"grids:{len(grids)},frames:{len(selected)},size:{total_size}",
        )

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path=str(frames_dir),
                sha256=sha256_string(
                    "\n".join(f.name for f in selected),
                ),
            ),
            output_info=OutputInfo(
                file_path=str(storyboard_dir),
                sha256=content_hash,
                size_bytes=total_size,
                record_count=len(grids),
            ),
            model_info=None,
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=(
                f"Generated {len(grids)} storyboard grids from "
                f"{len(selected)} frames ({total_size} bytes)"
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
        logger.error("Storyboard generation failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
            duration_ms=elapsed_ms,
        )
