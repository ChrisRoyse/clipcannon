"""Thumbnail generation for ClipCannon rendered clips.

Extracts a single frame at a given timestamp from a video file,
optionally applies a crop region, and saves as JPEG at quality 95.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from clipcannon.exceptions import PipelineError

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.editing.smart_crop import CropRegion

logger = logging.getLogger(__name__)


async def generate_thumbnail(
    source_path: Path,
    timestamp_ms: int,
    output_path: Path,
    width: int,
    height: int,
    crop_region: CropRegion | None = None,
) -> Path:
    """Extract a frame from a video and save as JPEG thumbnail.

    Uses FFmpeg to seek to the specified timestamp, optionally crop,
    scale to the target dimensions, and write a single JPEG frame.

    Args:
        source_path: Path to the source video file.
        timestamp_ms: Timestamp in milliseconds to extract.
        output_path: Where to write the thumbnail JPEG.
        width: Target thumbnail width in pixels.
        height: Target thumbnail height in pixels.
        crop_region: Optional crop region to apply before scaling.

    Returns:
        The output_path on success.

    Raises:
        PipelineError: If FFmpeg fails or source file is missing.
    """
    if not source_path.exists():
        raise PipelineError(
            f"Source file not found for thumbnail: {source_path}",
            stage_name="thumbnail",
            operation="generate_thumbnail",
            details={"source_path": str(source_path)},
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    timestamp_s = timestamp_ms / 1000.0

    # Build filter chain
    filters: list[str] = []
    if crop_region is not None:
        filters.append(
            f"crop={crop_region.width}:{crop_region.height}"
            f":{crop_region.x}:{crop_region.y}"
        )
    filters.append(f"scale={width}:{height}")

    filter_str = ",".join(filters)

    cmd: list[str] = [
        "ffmpeg",
        "-y",
        "-ss", f"{timestamp_s:.3f}",
        "-i", str(source_path),
        "-vf", filter_str,
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]

    logger.debug(
        "Generating thumbnail at %dms: %s",
        timestamp_ms,
        " ".join(cmd),
    )

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace")
        raise PipelineError(
            f"Thumbnail generation failed (exit {proc.returncode})",
            stage_name="thumbnail",
            operation="generate_thumbnail",
            details={
                "source_path": str(source_path),
                "timestamp_ms": timestamp_ms,
                "stderr": stderr_text[:500],
            },
        )

    if not output_path.exists():
        raise PipelineError(
            "Thumbnail file was not created by FFmpeg",
            stage_name="thumbnail",
            operation="generate_thumbnail",
            details={"output_path": str(output_path)},
        )

    logger.info(
        "Generated thumbnail at %dms -> %s",
        timestamp_ms,
        output_path,
    )
    return output_path
