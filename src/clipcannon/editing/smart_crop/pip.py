"""Picture-in-picture layout computation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .split_screen import detect_speaker_region

if TYPE_CHECKING:
    from .faces import FaceDetection


# ============================================================
# PIP (PICTURE-IN-PICTURE) LAYOUT
# ============================================================
@dataclass
class PipLayout:
    """Computed picture-in-picture layout for FFmpeg overlay."""

    # Full-screen background (screen content, scaled to output)
    bg_src_x: int
    bg_src_y: int
    bg_src_w: int
    bg_src_h: int

    # PIP window (speaker, cropped from source)
    pip_src_x: int
    pip_src_y: int
    pip_src_w: int
    pip_src_h: int

    # Output dimensions
    output_w: int
    output_h: int
    pip_out_w: int
    pip_out_h: int
    pip_x: int  # PIP position in output frame
    pip_y: int
    pip_border_px: int
    pip_border_color: str


def compute_pip_layout(
    source_w: int,
    source_h: int,
    output_w: int,
    output_h: int,
    faces: list[FaceDetection],
    pip_size: float = 0.25,
    pip_position: str = "bottom_right",
    pip_margin_px: int = 20,
    pip_border_px: int = 3,
    pip_border_color: str = "#FFFFFF",
    manual_speaker_region: dict[str, int] | None = None,
) -> PipLayout:
    """Compute picture-in-picture layout.

    Full screen shows the screen content. A small PIP window
    shows the speaker, positioned in a corner.

    Args:
        source_w: Source frame width.
        source_h: Source frame height.
        output_w: Output width (e.g., 1080).
        output_h: Output height (e.g., 1920).
        faces: Detected faces for speaker region.
        pip_size: PIP window as fraction of output width.
        pip_position: Corner placement.
        pip_margin_px: Margin from edges.
        pip_border_px: Border width around PIP.
        pip_border_color: Border color hex.
        manual_speaker_region: Manual override for speaker region.

    Returns:
        PipLayout with computed positions.
    """
    # Speaker region
    if manual_speaker_region is not None:
        sp = (
            manual_speaker_region["x"],
            manual_speaker_region["y"],
            manual_speaker_region["width"],
            manual_speaker_region["height"],
        )
    else:
        sp = detect_speaker_region(source_w, source_h, faces)
        if sp is None:
            sp = (
                source_w * 2 // 3,
                source_h * 2 // 3,
                source_w // 3,
                source_h // 3,
            )

    # PIP output dimensions
    pip_out_w = int(output_w * pip_size)
    pip_out_h = int(pip_out_w * sp[3] / max(sp[2], 1))

    # PIP position in output frame
    margin = pip_margin_px + pip_border_px
    if pip_position == "top_left":
        pip_x = margin
        pip_y = margin
    elif pip_position == "top_right":
        pip_x = output_w - pip_out_w - margin
        pip_y = margin
    elif pip_position == "bottom_left":
        pip_x = margin
        pip_y = output_h - pip_out_h - margin
    else:  # bottom_right
        pip_x = output_w - pip_out_w - margin
        pip_y = output_h - pip_out_h - margin

    return PipLayout(
        bg_src_x=0,
        bg_src_y=0,
        bg_src_w=source_w,
        bg_src_h=source_h,
        pip_src_x=sp[0],
        pip_src_y=sp[1],
        pip_src_w=sp[2],
        pip_src_h=sp[3],
        output_w=output_w,
        output_h=output_h,
        pip_out_w=pip_out_w,
        pip_out_h=pip_out_h,
        pip_x=pip_x,
        pip_y=pip_y,
        pip_border_px=pip_border_px,
        pip_border_color=pip_border_color,
    )
