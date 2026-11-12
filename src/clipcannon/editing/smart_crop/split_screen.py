"""Split-screen layout computation (speaker and screen regions)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .faces import FaceDetection


# ============================================================
# SPLIT-SCREEN LAYOUT
# ============================================================
@dataclass
class SplitScreenLayout:
    """Computed split-screen regions for FFmpeg vstack."""

    # Region in the SOURCE frame to use as screen content
    screen_src_x: int
    screen_src_y: int
    screen_src_w: int
    screen_src_h: int

    # Region in the SOURCE frame to use as speaker
    speaker_src_x: int
    speaker_src_y: int
    speaker_src_w: int
    speaker_src_h: int

    # Dimensions in the OUTPUT frame
    output_w: int
    output_h: int
    screen_out_h: int
    speaker_out_h: int
    separator_px: int
    separator_color: str
    speaker_position: str  # "top" or "bottom"


def detect_speaker_region(
    source_w: int,
    source_h: int,
    faces: list[FaceDetection],
) -> tuple[int, int, int, int] | None:
    """Detect the webcam/speaker region in a composited frame.

    Heuristic: the speaker webcam overlay is typically in a corner
    of the source frame. Look for a face and estimate the webcam
    region as a bounding box around it with padding.

    If no faces detected, returns None (can't auto-detect).

    Args:
        source_w: Source frame width.
        source_h: Source frame height.
        faces: Detected faces from detect_faces().

    Returns:
        (x, y, width, height) of the speaker region, or None.
    """
    if not faces:
        return None

    # Use the largest face (closest to camera)
    face = faces[0]

    # Estimate webcam region: expand face bbox by 2x in each direction
    # and snap to the nearest corner quadrant
    pad_x = face.width
    pad_y = int(face.height * 1.5)

    cam_x = max(0, face.x - pad_x)
    cam_y = max(0, face.y - pad_y)
    cam_w = min(face.width + 2 * pad_x, source_w - cam_x)
    cam_h = min(face.height + 2 * pad_y, source_h - cam_y)

    # Determine which quadrant the face is in
    cx = face.center_x
    cy = face.center_y

    # If face is in the bottom-right quadrant, likely a PIP overlay
    in_right_half = cx > source_w * 0.5
    in_bottom_half = cy > source_h * 0.5

    if in_right_half and in_bottom_half:
        # Bottom-right PIP — common in OBS/screen recordings
        cam_w = min(cam_w, source_w // 3)
        cam_h = min(cam_h, source_h // 3)
        cam_x = max(source_w - cam_w, face.x - pad_x)
        cam_y = max(source_h - cam_h, face.y - pad_y)
    elif not in_right_half and in_bottom_half:
        # Bottom-left PIP
        cam_w = min(cam_w, source_w // 3)
        cam_h = min(cam_h, source_h // 3)
        cam_x = 0
        cam_y = max(source_h - cam_h, face.y - pad_y)
    else:
        # Face is prominently placed — likely half the frame is speaker
        # Use the half of the frame containing the face
        if in_right_half:
            cam_x = source_w // 2
            cam_w = source_w // 2
            cam_y = 0
            cam_h = source_h
        else:
            cam_x = 0
            cam_w = source_w // 2
            cam_y = 0
            cam_h = source_h

    return (cam_x, cam_y, cam_w, cam_h)


def compute_screen_region(
    source_w: int,
    source_h: int,
    speaker_region: tuple[int, int, int, int] | None,
) -> tuple[int, int, int, int]:
    """Compute the screen content region (everything NOT the speaker).

    If no speaker region is known, returns the full frame.

    Args:
        source_w: Source frame width.
        source_h: Source frame height.
        speaker_region: (x, y, w, h) of the speaker region, or None.

    Returns:
        (x, y, width, height) of the screen content region.
    """
    if speaker_region is None:
        return (0, 0, source_w, source_h)

    sp_x, sp_y, sp_w, sp_h = speaker_region

    # If the speaker is in a small corner overlay, the screen is the full frame
    sp_area = sp_w * sp_h
    frame_area = source_w * source_h
    if sp_area < frame_area * 0.2:
        # Speaker is a small PIP — screen is the full frame
        return (0, 0, source_w, source_h)

    # If the speaker takes a significant portion, use the OTHER half
    if sp_x > source_w * 0.4:
        # Speaker is on the right — screen is on the left
        return (0, 0, sp_x, source_h)
    # Speaker is on the left — screen is on the right
    return (sp_x + sp_w, 0, source_w - sp_x - sp_w, source_h)


def compute_split_screen_layout(
    source_w: int,
    source_h: int,
    output_w: int,
    output_h: int,
    faces: list[FaceDetection],
    speaker_position: str = "top",
    split_ratio: float = 0.35,
    separator_px: int = 4,
    separator_color: str = "#FFFFFF",
    manual_speaker_region: dict[str, int] | None = None,
    manual_screen_region: dict[str, int] | None = None,
) -> SplitScreenLayout:
    """Compute split-screen layout for vertical video.

    Divides the output into two stacked regions:
    - Speaker region (from webcam/face area of source)
    - Screen content region (the rest of the source)

    Args:
        source_w: Source frame width in pixels.
        source_h: Source frame height in pixels.
        output_w: Output frame width (e.g., 1080).
        output_h: Output frame height (e.g., 1920).
        faces: Detected faces for auto speaker region detection.
        speaker_position: "top" or "bottom".
        split_ratio: Speaker region as fraction of output height.
        separator_px: Height of separator bar between regions.
        separator_color: Separator bar color hex.
        manual_speaker_region: Manual {x, y, width, height} override.
        manual_screen_region: Manual {x, y, width, height} override.

    Returns:
        SplitScreenLayout with computed source and output regions.
    """
    # Resolve speaker region
    if manual_speaker_region is not None:
        sp_region = (
            manual_speaker_region["x"],
            manual_speaker_region["y"],
            manual_speaker_region["width"],
            manual_speaker_region["height"],
        )
    else:
        sp_region = detect_speaker_region(source_w, source_h, faces)

    # If no speaker found, fall back to bottom-right quadrant guess
    if sp_region is None:
        sp_region = (
            source_w * 2 // 3,
            source_h * 2 // 3,
            source_w // 3,
            source_h // 3,
        )

    # Resolve screen region
    if manual_screen_region is not None:
        scr_region = (
            manual_screen_region["x"],
            manual_screen_region["y"],
            manual_screen_region["width"],
            manual_screen_region["height"],
        )
    else:
        scr_region = compute_screen_region(source_w, source_h, sp_region)

    # Compute output dimensions
    speaker_out_h = int(output_h * split_ratio) - separator_px // 2
    screen_out_h = output_h - speaker_out_h - separator_px

    return SplitScreenLayout(
        screen_src_x=scr_region[0],
        screen_src_y=scr_region[1],
        screen_src_w=scr_region[2],
        screen_src_h=scr_region[3],
        speaker_src_x=sp_region[0],
        speaker_src_y=sp_region[1],
        speaker_src_w=sp_region[2],
        speaker_src_h=sp_region[3],
        output_w=output_w,
        output_h=output_h,
        screen_out_h=screen_out_h,
        speaker_out_h=speaker_out_h,
        separator_px=separator_px,
        separator_color=separator_color,
        speaker_position=speaker_position,
    )
