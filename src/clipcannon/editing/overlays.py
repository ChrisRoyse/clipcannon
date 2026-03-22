"""Overlay rendering helpers for FFmpeg drawtext and overlay filters.

Generates FFmpeg filter expressions for text-based overlays (lower thirds,
title cards, CTAs) and image-based overlays (logos, watermarks). Each
overlay type has specific positioning, styling, and animation behavior.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Position mapping to FFmpeg x:y expressions
# Assumes output resolution of canvas_w x canvas_h
_POSITION_MAP: dict[str, tuple[str, str]] = {
    "bottom_left": ("20", "h-th-40"),
    "bottom_center": ("(w-tw)/2", "h-th-40"),
    "bottom_right": ("w-tw-20", "h-th-40"),
    "top_left": ("20", "40"),
    "top_center": ("(w-tw)/2", "40"),
    "top_right": ("w-tw-20", "40"),
    "center": ("(w-tw)/2", "(h-th)/2"),
}


def _hex_to_ffmpeg_color(hex_color: str, opacity: float = 1.0) -> str:
    """Convert #RRGGBB to FFmpeg color with opacity.

    FFmpeg uses format: color@opacity (e.g., white@0.7)
    """
    hex_color = hex_color.lstrip("#")
    return f"0x{hex_color}@{opacity:.2f}"


def _escape_drawtext(text: str) -> str:
    """Escape special characters for FFmpeg drawtext filter."""
    # FFmpeg drawtext requires escaping of: ' : \ and newlines
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "'\\\\\\''")
    text = text.replace(":", "\\:")
    text = text.replace("%", "%%")
    return text


def _time_enable_expr(start_ms: int, end_ms: int) -> str:
    """Generate FFmpeg enable expression for timed overlay."""
    start_s = start_ms / 1000.0
    end_s = end_ms / 1000.0
    return f"enable='between(t,{start_s:.3f},{end_s:.3f})'"


def _fade_alpha_expr(
    start_ms: int,
    end_ms: int,
    animation: str,
    animation_duration_ms: int,
) -> str:
    """Generate FFmpeg alpha expression for fade animations."""
    start_s = start_ms / 1000.0
    end_s = end_ms / 1000.0
    fade_s = animation_duration_ms / 1000.0

    if animation == "fade_in":
        return (
            f"alpha='if(between(t,{start_s:.3f},{start_s + fade_s:.3f}),"
            f"(t-{start_s:.3f})/{fade_s:.3f},"
            f"if(between(t,{start_s:.3f},{end_s:.3f}),1,0))'"
        )
    elif animation == "fade_out":
        fade_start = end_s - fade_s
        return (
            f"alpha='if(between(t,{fade_start:.3f},{end_s:.3f}),"
            f"({end_s:.3f}-t)/{fade_s:.3f},"
            f"if(between(t,{start_s:.3f},{end_s:.3f}),1,0))'"
        )
    return ""


def build_lower_third_filter(
    text: str,
    subtitle: str,
    position: str,
    start_ms: int,
    end_ms: int,
    font: str,
    font_size: int,
    text_color: str,
    bg_color: str,
    bg_opacity: float,
    animation: str,
    animation_duration_ms: int,
) -> list[str]:
    """Build FFmpeg filters for a lower third overlay.

    A lower third consists of:
    1. Semi-transparent background bar
    2. Main text (name/title)
    3. Optional subtitle text (below main)

    Returns list of FFmpeg filter strings to chain.
    """
    filters: list[str] = []
    escaped_text = _escape_drawtext(text)
    time_enable = _time_enable_expr(start_ms, end_ms)

    # Background bar using drawbox
    bg_color_fmt = _hex_to_ffmpeg_color(bg_color, bg_opacity)
    bar_height = font_size * 3 if subtitle else font_size * 2

    # Position the bar
    if "bottom" in position:
        bar_y = f"h-{bar_height}-20"
    elif "top" in position:
        bar_y = "20"
    else:
        bar_y = f"(h-{bar_height})/2"

    filters.append(
        f"drawbox=x=0:y={bar_y}:w=iw:h={bar_height}"
        f":color={bg_color_fmt}:t=fill:{time_enable}"
    )

    # Main text
    text_y = f"{bar_y}+{int(font_size * 0.3)}"
    text_color_fmt = _hex_to_ffmpeg_color(text_color)
    filters.append(
        f"drawtext=text='{escaped_text}'"
        f":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        f":fontsize={font_size}"
        f":fontcolor={text_color_fmt}"
        f":x=30:y={text_y}"
        f":{time_enable}"
    )

    # Subtitle text
    if subtitle:
        escaped_sub = _escape_drawtext(subtitle)
        sub_y = f"{bar_y}+{int(font_size * 1.3)}"
        sub_size = max(int(font_size * 0.7), 12)
        filters.append(
            f"drawtext=text='{escaped_sub}'"
            f":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            f":fontsize={sub_size}"
            f":fontcolor={text_color_fmt}"
            f":x=30:y={sub_y}"
            f":{time_enable}"
        )

    return filters


def build_title_card_filter(
    text: str,
    start_ms: int,
    end_ms: int,
    font_size: int,
    text_color: str,
    bg_color: str,
    bg_opacity: float,
    animation: str,
    animation_duration_ms: int,
) -> list[str]:
    """Build FFmpeg filters for a centered title card."""
    filters: list[str] = []
    escaped_text = _escape_drawtext(text)
    time_enable = _time_enable_expr(start_ms, end_ms)
    bg_color_fmt = _hex_to_ffmpeg_color(bg_color, bg_opacity)
    text_color_fmt = _hex_to_ffmpeg_color(text_color)

    # Full-screen background
    filters.append(
        f"drawbox=x=0:y=0:w=iw:h=ih"
        f":color={bg_color_fmt}:t=fill:{time_enable}"
    )

    # Centered text
    filters.append(
        f"drawtext=text='{escaped_text}'"
        f":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        f":fontsize={font_size}"
        f":fontcolor={text_color_fmt}"
        f":x=(w-tw)/2:y=(h-th)/2"
        f":{time_enable}"
    )

    return filters


def build_watermark_filter(
    text: str,
    position: str,
    start_ms: int,
    end_ms: int,
    font_size: int,
    text_color: str,
    opacity: float,
) -> list[str]:
    """Build FFmpeg filter for a text watermark."""
    escaped_text = _escape_drawtext(text)
    time_enable = _time_enable_expr(start_ms, end_ms)
    text_color_fmt = _hex_to_ffmpeg_color(text_color, opacity)
    pos = _POSITION_MAP.get(position, _POSITION_MAP["bottom_right"])

    return [
        f"drawtext=text='{escaped_text}'"
        f":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        f":fontsize={font_size}"
        f":fontcolor={text_color_fmt}"
        f":x={pos[0]}:y={pos[1]}"
        f":{time_enable}"
    ]


def build_cta_filter(
    text: str,
    position: str,
    start_ms: int,
    end_ms: int,
    font_size: int,
    text_color: str,
    bg_color: str,
    bg_opacity: float,
) -> list[str]:
    """Build FFmpeg filter for a call-to-action button overlay."""
    escaped_text = _escape_drawtext(text)
    time_enable = _time_enable_expr(start_ms, end_ms)
    bg_color_fmt = _hex_to_ffmpeg_color(bg_color, bg_opacity)
    text_color_fmt = _hex_to_ffmpeg_color(text_color)
    pos = _POSITION_MAP.get(position, _POSITION_MAP["bottom_center"])

    # CTA button: background box + centered text
    btn_w = len(text) * font_size + 40
    btn_h = font_size + 20

    # drawbox needs pixel expressions, not drawtext variables like tw/th
    # For centered positions, calculate using btn_w directly
    box_x = f"(w-{btn_w})/2" if "center" in position else pos[0]
    box_y = f"h-{btn_h}-40" if "bottom" in position else pos[1]
    text_x = f"(w-{btn_w})/2+20" if "center" in position else f"{pos[0]}+20"
    text_y = f"h-{btn_h}-40+10" if "bottom" in position else f"{pos[1]}+10"

    return [
        f"drawbox=x={box_x}:y={box_y}:w={btn_w}:h={btn_h}"
        f":color={bg_color_fmt}:t=fill:{time_enable}",
        f"drawtext=text='{escaped_text}'"
        f":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        f":fontsize={font_size}"
        f":fontcolor={text_color_fmt}"
        f":x={text_x}:y={text_y}"
        f":{time_enable}",
    ]


def build_overlay_filters(
    overlay_type: str,
    text: str = "",
    subtitle: str = "",
    image_path: str | None = None,
    position: str = "bottom_left",
    start_ms: int = 0,
    end_ms: int = 5000,
    opacity: float = 1.0,
    font: str = "Montserrat",
    font_size: int = 36,
    text_color: str = "#FFFFFF",
    bg_color: str = "#000000",
    bg_opacity: float = 0.7,
    animation: str = "fade_in",
    animation_duration_ms: int = 500,
) -> list[str]:
    """Build FFmpeg filter strings for any overlay type.

    This is the main entry point. Routes to the appropriate
    type-specific builder based on overlay_type.

    Args:
        overlay_type: One of lower_third, title_card, logo, watermark, cta.
        (all other params match OverlaySpec fields)

    Returns:
        List of FFmpeg filter strings to chain into filter_complex.

    Raises:
        ValueError: If overlay_type is not recognized.
    """
    if overlay_type == "lower_third":
        return build_lower_third_filter(
            text, subtitle, position, start_ms, end_ms,
            font, font_size, text_color, bg_color, bg_opacity,
            animation, animation_duration_ms,
        )
    elif overlay_type == "title_card":
        return build_title_card_filter(
            text, start_ms, end_ms, font_size, text_color,
            bg_color, bg_opacity, animation, animation_duration_ms,
        )
    elif overlay_type == "watermark":
        return build_watermark_filter(
            text, position, start_ms, end_ms, font_size,
            text_color, opacity,
        )
    elif overlay_type == "cta":
        return build_cta_filter(
            text, position, start_ms, end_ms, font_size,
            text_color, bg_color, bg_opacity,
        )
    elif overlay_type == "logo":
        if image_path:
            # Logo uses overlay filter with image input
            time_enable = _time_enable_expr(start_ms, end_ms)
            pos = _POSITION_MAP.get(position, _POSITION_MAP["top_right"])
            return [f"overlay=x={pos[0]}:y={pos[1]}:{time_enable}"]
        return build_watermark_filter(
            text or "LOGO", position, start_ms, end_ms,
            font_size, text_color, opacity,
        )
    else:
        raise ValueError(f"Unknown overlay type: {overlay_type!r}")
