"""Motion effect helpers for FFmpeg zoompan filter generation.

Generates FFmpeg filter expressions for zoom, pan, and Ken Burns
effects applied per-segment during video rendering.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Easing functions as FFmpeg expressions
# t goes from 0 to 1 over the segment duration
_EASING_EXPRS: dict[str, str] = {
    "linear": "{t}",
    "ease_in": "({t})*({t})",
    "ease_out": "(1-(1-{t})*(1-{t}))",
    "ease_in_out": "if(lt({t},0.5),2*({t})*({t}),1-2*(1-{t})*(1-{t}))",
}


def build_color_filters(
    brightness: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    gamma: float = 1.0,
    hue_shift: float = 0.0,
) -> str:
    """Generate FFmpeg filter string for color adjustments.

    Args:
        brightness: -1.0 to 1.0 (0 = no change)
        contrast: 0.0 to 3.0 (1.0 = no change)
        saturation: 0.0 to 3.0 (1.0 = no change)
        gamma: 0.1 to 10.0 (1.0 = no change)
        hue_shift: -180 to 180 degrees (0 = no change)

    Returns:
        FFmpeg filter string like "eq=brightness=0.1:contrast=1.2,hue=h=30"
        Returns empty string if all values are defaults (no adjustment needed).
    """
    parts: list[str] = []

    # eq filter for brightness, contrast, saturation, gamma
    eq_parts: list[str] = []
    if abs(brightness) > 0.001:
        eq_parts.append(f"brightness={brightness:.3f}")
    if abs(contrast - 1.0) > 0.001:
        eq_parts.append(f"contrast={contrast:.3f}")
    if abs(saturation - 1.0) > 0.001:
        eq_parts.append(f"saturation={saturation:.3f}")
    if abs(gamma - 1.0) > 0.001:
        eq_parts.append(f"gamma={gamma:.3f}")

    if eq_parts:
        parts.append("eq=" + ":".join(eq_parts))

    # hue filter for hue shift
    if abs(hue_shift) > 0.1:
        parts.append(f"hue=h={hue_shift:.1f}")

    return ",".join(parts)


def build_motion_filter(
    effect: str,
    start_scale: float,
    end_scale: float,
    easing: str,
    output_width: int,
    output_height: int,
    source_width: int,
    source_height: int,
    fps: int = 30,
    duration_s: float = 10.0,
) -> str:
    """Generate FFmpeg zoompan filter for motion effects.

    Args:
        effect: Motion type (zoom_in, zoom_out, pan_left, etc.)
        start_scale: Starting zoom factor (1.0 = no zoom)
        end_scale: Ending zoom factor
        easing: Easing function name
        output_width: Output video width
        output_height: Output video height
        source_width: Source video width
        source_height: Source video height
        fps: Output frame rate
        duration_s: Segment duration in seconds

    Returns:
        FFmpeg zoompan filter string.
    """
    total_frames = int(fps * duration_s)
    if total_frames < 1:
        total_frames = 1

    # Time variable: on/duration goes from 0 to 1
    t_expr = f"on/{total_frames}"
    easing_template = _EASING_EXPRS.get(easing, _EASING_EXPRS["linear"])
    progress = easing_template.format(t=t_expr)

    # Zoom expression: interpolate between start and end scale
    if effect == "zoom_out":
        # Swap start/end for zoom out
        zoom_expr = f"({end_scale}+({start_scale}-{end_scale})*({progress}))"
    else:
        zoom_expr = f"({start_scale}+({end_scale}-{start_scale})*({progress}))"

    # Pan expressions based on effect type
    if effect in ("zoom_in", "zoom_out"):
        # Center zoom: pan keeps center fixed
        x_expr = f"(iw-iw/{zoom_expr})/2"
        y_expr = f"(ih-ih/{zoom_expr})/2"
    elif effect == "pan_left":
        # Pan from right to left
        x_expr = f"(iw-iw/zoom)*(1-{progress})"
        y_expr = "(ih-ih/zoom)/2"
        zoom_expr = str(start_scale)
    elif effect == "pan_right":
        # Pan from left to right
        x_expr = f"(iw-iw/zoom)*({progress})"
        y_expr = "(ih-ih/zoom)/2"
        zoom_expr = str(start_scale)
    elif effect == "pan_up":
        x_expr = "(iw-iw/zoom)/2"
        y_expr = f"(ih-ih/zoom)*(1-{progress})"
        zoom_expr = str(start_scale)
    elif effect == "pan_down":
        x_expr = "(iw-iw/zoom)/2"
        y_expr = f"(ih-ih/zoom)*({progress})"
        zoom_expr = str(start_scale)
    elif effect == "ken_burns":
        # Ken Burns: zoom + diagonal pan simultaneously
        zoom_expr = f"({start_scale}+({end_scale}-{start_scale})*({progress}))"
        x_expr = f"(iw-iw/{zoom_expr})*({progress})*0.3"
        y_expr = f"(ih-ih/{zoom_expr})*({progress})*0.2"
    else:
        # Default: center zoom
        x_expr = f"(iw-iw/{zoom_expr})/2"
        y_expr = f"(ih-ih/{zoom_expr})/2"

    return (
        f"zoompan=z='{zoom_expr}'"
        f":x='{x_expr}'"
        f":y='{y_expr}'"
        f":d={total_frames}"
        f":s={output_width}x{output_height}"
        f":fps={fps}"
    )
