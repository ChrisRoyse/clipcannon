"""Preview frame FFmpeg commands (canvas and zoom previews)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .canvas_chains import _build_region_scale

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.editing.edl import CanvasRegion


# ============================================================
# PREVIEW -- Single frame preview for compositing validation
# ============================================================
def build_preview_cmd(
    source_path: Path,
    output_path: Path,
    timestamp_ms: int,
    canvas_width: int,
    canvas_height: int,
    background_color: str,
    regions: list[CanvasRegion],
    fps: int = 30,
) -> list[str]:
    """Build FFmpeg command to render a single preview frame.

    Generates one composited JPEG showing exactly what the canvas
    layout looks like at a specific timestamp. Used for rapid
    iteration on region coordinates before committing to a full
    video render.

    Uses -ss before -i for fast keyframe seeking. No audio.
    No trim filters. Color source d=0.1 (just enough for 1 frame).

    Args:
        source_path: Path to the source video.
        output_path: Path for the output JPEG/PNG.
        timestamp_ms: Timestamp in the source to preview (ms).
        canvas_width: Output canvas width (e.g., 1080).
        canvas_height: Output canvas height (e.g., 1920).
        background_color: Canvas background hex color.
        regions: Canvas regions to composite (sorted by z_index).
        fps: Frame rate for the color source.

    Returns:
        FFmpeg command as a list of strings.

    Raises:
        ValueError: If no regions are provided.
    """
    if not regions:
        msg = "Preview requires at least one canvas region"
        raise ValueError(msg)

    seek_s = timestamp_ms / 1000.0
    sorted_regions = sorted(regions, key=lambda r: r.z_index)
    n_regions = len(sorted_regions)
    use_blur = background_color.lower() == "blur"

    filters: list[str] = []

    if use_blur:
        # Blur background: split into N+1 copies (1 for bg, N for regions)
        total = n_regions + 1
        split_out = "[bgcopy]" + "".join(f"[r{j}]" for j in range(n_regions))
        filters.append(f"[0:v]split={total}{split_out}")
        filters.append(
            f"[bgcopy]scale={canvas_width}:{canvas_height}"
            f":force_original_aspect_ratio=increase,"
            f"crop={canvas_width}:{canvas_height},"
            f"gblur=sigma=40,setsar=1[bg]"
        )
    else:
        # Solid color background
        bg_hex = background_color.lstrip("#")
        filters.append(
            f"color=c=0x{bg_hex}:s={canvas_width}x{canvas_height}"
            f":d=0.1:r={fps},setsar=1[bg]"
        )
        # Split source into N copies
        if n_regions == 1:
            filters.append("[0:v]null[r0]")
        else:
            split_out = "".join(f"[r{j}]" for j in range(n_regions))
            filters.append(f"[0:v]split={n_regions}{split_out}")

    # Crop and scale each region
    for j, region in enumerate(sorted_regions):
        scale_filter = _build_region_scale(region)
        filters.append(
            f"[r{j}]"
            f"crop={region.source_width}:{region.source_height}"
            f":{region.source_x}:{region.source_y},"
            f"{scale_filter}"
            f"[cr{j}]"
        )

    # Overlay each region onto canvas
    current = "bg"
    for j, region in enumerate(sorted_regions):
        out = f"ov{j}" if j < n_regions - 1 else "out"
        filters.append(
            f"[{current}][cr{j}]"
            f"overlay=x={region.output_x}:y={region.output_y}"
            f":shortest=1[{out}]"
        )
        current = out

    filter_complex = ";".join(filters)

    cmd: list[str] = [
        "ffmpeg", "-y",
        "-ss", f"{seek_s:.3f}",
        "-i", str(source_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-frames:v", "1",
        "-update", "1",
        "-q:v", "2",
        str(output_path),
    ]

    return cmd


def build_zoom_preview_cmd(
    source_path: Path,
    output_path: Path,
    timestamp_ms: int,
    canvas_width: int,
    canvas_height: int,
    crop_x: int,
    crop_y: int,
    crop_w: int,
    crop_h: int,
) -> list[str]:
    """Build FFmpeg command to preview a zoom/crop at a timestamp.

    Shows exactly what a static crop at the given coordinates
    looks like, scaled to the canvas dimensions.

    Args:
        source_path: Source video path.
        output_path: Output JPEG path.
        timestamp_ms: Source timestamp in ms.
        canvas_width: Output width.
        canvas_height: Output height.
        crop_x: Crop X origin in source.
        crop_y: Crop Y origin in source.
        crop_w: Crop width in source.
        crop_h: Crop height in source.

    Returns:
        FFmpeg command as argument list.
    """
    seek_s = timestamp_ms / 1000.0

    cmd: list[str] = [
        "ffmpeg", "-y",
        "-ss", f"{seek_s:.3f}",
        "-i", str(source_path),
        "-vf",
        f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},"
        f"scale={canvas_width}:{canvas_height},setsar=1",
        "-frames:v", "1",
        "-update", "1",
        "-q:v", "2",
        str(output_path),
    ]

    return cmd
