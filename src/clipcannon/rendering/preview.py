"""Low-quality clip preview rendering.

Renders a short (2-5 second) preview of an edit at low quality
for rapid validation before committing to a full render.
No credits charged for previews.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Preview encoding settings (low quality for speed)
PREVIEW_WIDTH = 540
PREVIEW_HEIGHT = 960
PREVIEW_BITRATE = "1M"
PREVIEW_PRESET = "ultrafast"


@dataclass
class PreviewResult:
    """Result of a preview render."""
    preview_path: Path
    duration_ms: int
    file_size_bytes: int
    elapsed_ms: int
    thumbnail_base64: str


async def render_preview(
    source_path: Path,
    output_dir: Path,
    start_ms: int,
    duration_ms: int,
    crop_filter: str | None = None,
) -> PreviewResult:
    """Render a low-quality preview clip from source video.

    Args:
        source_path: Path to source video file.
        output_dir: Directory to write preview file.
        start_ms: Start time in the source video (ms).
        duration_ms: Duration to preview (ms), capped at 5000.
        crop_filter: Optional FFmpeg crop/scale filter string.

    Returns:
        PreviewResult with path, metadata, and base64 thumbnail.

    Raises:
        FileNotFoundError: If source video doesn't exist.
        RuntimeError: If FFmpeg fails.
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    # Cap preview duration at 5 seconds
    duration_ms = min(duration_ms, 5000)
    if duration_ms < 100:
        raise ValueError("Preview duration must be at least 100ms")

    output_dir.mkdir(parents=True, exist_ok=True)
    preview_id = secrets.token_hex(4)
    preview_path = output_dir / f"preview_{preview_id}.mp4"
    thumb_path = output_dir / f"preview_{preview_id}_thumb.jpg"

    start_s = start_ms / 1000.0
    dur_s = duration_ms / 1000.0

    # Build filter chain
    filters: list[str] = []
    if crop_filter:
        filters.append(crop_filter)
    filters.append(
        f"scale={PREVIEW_WIDTH}:{PREVIEW_HEIGHT}"
        f":force_original_aspect_ratio=decrease"
    )
    filters.append(
        f"pad={PREVIEW_WIDTH}:{PREVIEW_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black"
    )
    filter_str = ",".join(filters)

    # Render preview
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_s:.3f}",
        "-i", str(source_path),
        "-t", f"{dur_s:.3f}",
        "-vf", filter_str,
        "-c:v", "libx264",
        "-preset", PREVIEW_PRESET,
        "-b:v", PREVIEW_BITRATE,
        "-c:a", "aac",
        "-b:a", "64k",
        "-movflags", "+faststart",
        str(preview_path),
    ]

    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if proc.returncode != 0:
        err = stderr.decode(errors="replace")[-500:]
        raise RuntimeError(
            f"Preview render failed (exit {proc.returncode}): {err}"
        )

    if not preview_path.exists():
        raise RuntimeError("Preview render completed but output file missing")

    # Generate thumbnail (first frame)
    thumb_cmd = [
        "ffmpeg", "-y",
        "-i", str(preview_path),
        "-frames:v", "1",
        "-q:v", "5",
        str(thumb_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *thumb_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    thumb_b64 = ""
    if thumb_path.exists():
        thumb_b64 = base64.b64encode(
            thumb_path.read_bytes()
        ).decode("ascii")

    return PreviewResult(
        preview_path=preview_path,
        duration_ms=duration_ms,
        file_size_bytes=preview_path.stat().st_size,
        elapsed_ms=elapsed_ms,
        thumbnail_base64=thumb_b64,
    )
