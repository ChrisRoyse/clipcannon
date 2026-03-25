"""Subject extraction via rembg for background removal/replacement.

Uses rembg with U2-Net or BRIA models running locally on GPU to
generate per-frame alpha masks. These masks are assembled into a
mask video that FFmpeg can use for alpha compositing.

All processing is LOCAL - no data leaves the machine.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result of subject extraction."""

    mask_video_path: Path
    frame_count: int
    duration_ms: int
    model_used: str
    elapsed_ms: int


async def extract_subject_masks(
    frames_dir: Path,
    output_dir: Path,
    fps: float = 2.0,
    model_name: str = "u2net",
) -> ExtractionResult:
    """Extract subject masks from video frames using rembg.

    Processes each frame through rembg to generate an alpha mask,
    then assembles all masks into a grayscale mask video.

    Args:
        frames_dir: Directory containing frame_NNNNNN.jpg files.
        output_dir: Directory to write mask frames and mask video.
        fps: Frame rate of the extracted frames.
        model_name: rembg model to use (u2net, u2net_human_seg,
            isnet-general-use).

    Returns:
        ExtractionResult with mask video path and metadata.

    Raises:
        FileNotFoundError: If frames_dir doesn't exist.
        ValueError: If no frames found.
        RuntimeError: If rembg or FFmpeg fails.
    """
    import time

    if not frames_dir.exists():
        raise FileNotFoundError(f"Frames directory not found: {frames_dir}")

    frame_files = sorted(frames_dir.glob("frame_*.jpg"))
    if not frame_files:
        raise ValueError(f"No frame files found in {frames_dir}")

    masks_dir = output_dir / "masks"
    masks_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()

    import numpy as np
    from PIL import Image
    from rembg import new_session, remove

    session = new_session(model_name)

    logger.info(
        "Extracting subject masks from %d frames using %s",
        len(frame_files),
        model_name,
    )

    # Process each frame
    for i, frame_path in enumerate(frame_files):
        frame_num = int(frame_path.stem.split("_")[1])
        mask_path = masks_dir / f"mask_{frame_num:06d}.png"

        if mask_path.exists():
            continue  # Skip already processed

        img = Image.open(frame_path).convert("RGB")

        # rembg returns RGBA image - extract alpha channel as mask
        result = remove(
            img,
            session=session,
            only_mask=True,  # Returns grayscale mask directly
        )

        # Save mask as grayscale PNG
        if isinstance(result, Image.Image):
            result.save(str(mask_path))
        else:
            mask_img = Image.fromarray(np.array(result))
            mask_img.save(str(mask_path))

        if (i + 1) % 10 == 0:
            logger.info("Processed %d/%d frames", i + 1, len(frame_files))

    logger.info("All %d masks generated", len(frame_files))

    # Assemble masks into a mask video
    mask_video_path = output_dir / f"mask_{secrets.token_hex(4)}.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(masks_dir / "mask_%06d.png"),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        str(mask_video_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode(errors="replace")[-500:]
        raise RuntimeError(f"Mask video assembly failed: {error_msg}")

    if not mask_video_path.exists():
        raise RuntimeError("Mask video not created")

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    total_frames = len(frame_files)
    duration_ms = int(total_frames / fps * 1000)

    return ExtractionResult(
        mask_video_path=mask_video_path,
        frame_count=total_frames,
        duration_ms=duration_ms,
        model_used=model_name,
        elapsed_ms=elapsed_ms,
    )


def build_background_replace_filters(
    mask_video_input_idx: int,
    background_type: str,
    background_value: str,
    output_w: int,
    output_h: int,
) -> list[str]:
    """Build FFmpeg filter chain for background replacement.

    Uses the mask video as an alpha channel to composite the
    subject over a new background.

    Args:
        mask_video_input_idx: FFmpeg input index for the mask video.
        background_type: 'color', 'blur', or 'image'.
        background_value: Hex color, blur sigma, or image input index.
        output_w: Output width.
        output_h: Output height.

    Returns:
        List of FFmpeg filter strings for the filter_complex.
    """
    filters: list[str] = []

    if background_type == "blur":
        sigma = int(background_value) if background_value else 40
        # Split source: one for subject, one for blurred bg
        filters.append("[0:v]split[subject_src][bg_src]")
        filters.append(f"[bg_src]gblur=sigma={sigma}[blurred_bg]")
        # Scale mask to match source
        filters.append(
            f"[{mask_video_input_idx}:v]"
            f"scale={output_w}:{output_h},"
            f"format=gray[mask_scaled]"
        )
        # Use mask to composite subject over blurred bg
        filters.append(
            "[subject_src][mask_scaled]alphamerge[subject_alpha]"
        )
        filters.append(
            "[blurred_bg][subject_alpha]overlay=0:0[composed]"
        )

    elif background_type == "color":
        color_hex = background_value.lstrip("#")
        # Create solid color background
        filters.append(
            f"color=c=0x{color_hex}:s={output_w}x{output_h}"
            f":d=999:r=30[color_bg]"
        )
        # Scale mask
        filters.append(
            f"[{mask_video_input_idx}:v]"
            f"scale={output_w}:{output_h},"
            f"format=gray[mask_scaled]"
        )
        # Composite
        filters.append("[0:v][mask_scaled]alphamerge[subject_alpha]")
        filters.append(
            "[color_bg][subject_alpha]overlay=0:0:shortest=1[composed]"
        )

    return filters
