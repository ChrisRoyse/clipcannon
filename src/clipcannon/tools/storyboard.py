"""Storyboard contact sheet generation for AI video understanding.

Generates a single contact sheet image containing ALL extracted frames
at thumbnail resolution. Designed for AI consumption - resolution is
optimized for machine vision models, not human viewing. Each frame
includes a timestamp label for speech-to-visual alignment.

A 210-second video at 2fps = 420 frames fits in one ~9K token image.
"""

from __future__ import annotations

import logging
from pathlib import Path  # noqa: TC003 (used at runtime)

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Thumbnail dimensions - large enough for AI to read UI text
THUMB_W = 256
THUMB_H = 144
LABEL_H = 12
COLS = 10  # 10 columns = 5 seconds per row at 2fps


def _format_ts(ms: int) -> str:
    """Format milliseconds as M:SS."""
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def build_contact_sheet(
    frames_dir: Path,
    output_path: Path,
    fps: float = 2.0,
    cols: int = COLS,
    thumb_w: int = THUMB_W,
    thumb_h: int = THUMB_H,
    start_frame: int | None = None,
    end_frame: int | None = None,
) -> dict[str, object]:
    """Build a contact sheet image from extracted frames.

    Creates one image with frames as thumbnails arranged in a grid.
    Each cell has a timestamp label. Can show all frames or a subset.

    Args:
        frames_dir: Directory containing frame_NNNNNN.jpg files.
        output_path: Path to write the contact sheet image.
        fps: Frame extraction rate (frames per second).
        cols: Number of columns in the grid.
        thumb_w: Thumbnail width in pixels.
        start_frame: First frame to include (1-based). None = all.
        end_frame: Last frame to include. None = all.
        thumb_h: Thumbnail height in pixels.

    Returns:
        Dict with sheet_path, frame_count, dimensions, duration info,
        and a frame_index mapping frame numbers to timestamps.

    Raises:
        FileNotFoundError: If frames_dir doesn't exist.
        ValueError: If no frames found.
    """
    if not frames_dir.exists():
        raise FileNotFoundError(f"Frames directory not found: {frames_dir}")

    frame_files = sorted(frames_dir.glob("frame_*.jpg"))
    if not frame_files:
        raise ValueError(f"No frame files found in {frames_dir}")

    # Filter by frame range if specified
    if start_frame is not None or end_frame is not None:
        sf = start_frame or 1
        ef = end_frame or 999999
        frame_files = [
            f for f in frame_files
            if sf <= int(f.stem.split("_")[1]) <= ef
        ]
        if not frame_files:
            raise ValueError(f"No frames in range {sf}-{ef}")

    total_frames = len(frame_files)
    rows = (total_frames + cols - 1) // cols
    cell_h = thumb_h + LABEL_H
    sheet_w = cols * thumb_w
    sheet_h = rows * cell_h

    logger.info(
        "Building contact sheet: %d frames, %dx%d grid, %dx%d px",
        total_frames, cols, rows, sheet_w, sheet_h,
    )

    sheet = Image.new("RGB", (sheet_w, sheet_h), (13, 13, 13))
    draw = ImageDraw.Draw(sheet)

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9,
        )
    except OSError:
        font = ImageFont.load_default()

    frame_index: list[dict[str, object]] = []

    for i, frame_path in enumerate(frame_files):
        col = i % cols
        row = i // cols

        frame_num = int(frame_path.stem.split("_")[1])
        timestamp_ms = int((frame_num - 1) / fps * 1000)

        # Load and resize
        frame = Image.open(frame_path)
        frame = frame.resize((thumb_w, thumb_h), Image.LANCZOS)

        # Place on sheet
        x = col * thumb_w
        y = row * cell_h
        sheet.paste(frame, (x, y))

        # Timestamp label
        label_y = y + thumb_h
        draw.rectangle(
            [(x, label_y), (x + thumb_w, label_y + LABEL_H)],
            fill=(0, 0, 0),
        )
        draw.text(
            (x + 2, label_y + 1),
            f"{_format_ts(timestamp_ms)}",
            fill=(255, 255, 0),
            font=font,
        )

        frame_index.append({
            "frame": frame_num,
            "ms": timestamp_ms,
            "ts": _format_ts(timestamp_ms),
            "col": col,
            "row": row,
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(output_path), "JPEG", quality=80)

    return {
        "sheet_path": str(output_path),
        "total_frames": total_frames,
        "grid": f"{cols}x{rows}",
        "image_size": f"{sheet_w}x{sheet_h}",
        "duration_ms": frame_index[-1]["ms"] if frame_index else 0,
        "fps": fps,
        "seconds_per_row": cols / fps,
        "frame_index": frame_index,
    }
