"""ASS subtitle file generation for captions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .styles import _ASS_STYLE_KEYS, ASS_STYLES

if TYPE_CHECKING:
    from clipcannon.editing.edl import CaptionChunk

    from .styles import CaptionStyleLiteral


# ============================================================
# ASS TIME FORMATTING
# ============================================================
def _format_ass_time(ms: int) -> str:
    """Format milliseconds as ASS time: H:MM:SS.cc (centiseconds).

    Args:
        ms: Time in milliseconds.

    Returns:
        Formatted ASS time string.
    """
    total_cs = round(ms / 10)
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _hex_to_ass_color(hex_color: str, alpha: int = 0) -> str:
    """Convert hex color #RRGGBB to ASS &HAABBGGRR format.

    Args:
        hex_color: Color in #RRGGBB format.
        alpha: Alpha value 0-255 (0 = opaque, 255 = transparent).

    Returns:
        ASS color string.
    """
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    else:
        r, g, b = 255, 255, 255
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


# ============================================================
# ASS TEXT HELPERS
# ============================================================
def _escape_ass_text(text: str) -> str:
    """Escape special characters for ASS dialogue text.

    Args:
        text: Raw text to escape.

    Returns:
        Escaped text safe for ASS format.
    """
    return text.replace("\\", "\\\\")


def _karaoke_dialogue_text(chunk: CaptionChunk) -> str:
    r"""Generate ASS karaoke dialogue text with \kf tags.

    Each word gets a \kf tag with duration in centiseconds.

    Args:
        chunk: Caption chunk with word timing.

    Returns:
        ASS dialogue text with karaoke tags.
    """
    parts: list[str] = []
    for word in chunk.words:
        duration_cs = max(1, (word.end_ms - word.start_ms) // 10)
        escaped = _escape_ass_text(word.word)
        parts.append(f"{{\\kf{duration_cs}}}{escaped}")
    return " ".join(parts)


def _highlight_dialogue_text(
    chunk: CaptionChunk,
    style: str,
) -> str:
    """Generate ASS dialogue text with word highlight.

    For bold_centered: highlights current word in yellow.
    For word_highlight: dims inactive words in gray.

    Args:
        chunk: Caption chunk with word timing.
        style: Caption style name.

    Returns:
        ASS dialogue text with inline color overrides.
    """
    if not chunk.words:
        return _escape_ass_text(chunk.text)

    highlight_color = "&H0000FFFF"  # Yellow in ASS BGR
    default_color = "&H00FFFFFF"  # White

    if style == "word_highlight":
        default_color = "&H00999999"  # Gray for inactive

    parts: list[str] = []
    for i, word in enumerate(chunk.words):
        escaped = _escape_ass_text(word.word)
        duration_cs = max(1, (word.end_ms - word.start_ms) // 10)
        if i == 0:
            parts.append(
                f"{{\\c{default_color}&\\kf{duration_cs}"
                f"\\1c{highlight_color}&}}{escaped}"
            )
        else:
            parts.append(f"{{\\kf{duration_cs}}}{escaped}")

    return " ".join(parts)


# ============================================================
# ASS FILE GENERATION
# ============================================================
def _position_fields(position: str, resolution_w: int, resolution_h: int) -> dict[str, int]:
    """ASS Alignment/MarginV for a caption position.

    ``bottom`` sits above the region platform UIs cover on vertical video
    (caption bar, buttons): 22% of the height on portrait canvases, 6% on
    landscape. ``center`` is true center; ``top`` is just below the top edge.
    """
    portrait = resolution_h > resolution_w
    if position == "top":
        return {"Alignment": 8, "MarginV": int(resolution_h * (0.12 if portrait else 0.05))}
    if position == "center":
        return {"Alignment": 5, "MarginV": 0}
    return {"Alignment": 2, "MarginV": int(resolution_h * (0.22 if portrait else 0.06))}


def generate_ass_file(
    chunks: list[CaptionChunk],
    style: CaptionStyleLiteral,
    resolution_w: int = 1080,
    resolution_h: int = 1920,
    *,
    font_size: int | None = None,
    position: str | None = None,
) -> str:
    """Generate a complete ASS subtitle file string.

    Supports all four caption styles with appropriate inline
    override tags for word highlighting and karaoke effects.

    Args:
        chunks: Caption chunks with timing and word data.
        style: One of the four supported caption styles.
        resolution_w: Output video width in pixels.
        resolution_h: Output video height in pixels.

    Returns:
        Complete ASS file content as a string.
    """
    style_def = ASS_STYLES.get(style, ASS_STYLES["bold_centered"])

    # Scale font size relative to 1080x1920 baseline
    base_h = 1920
    scale = resolution_h / base_h
    # font_size (from the EDL) is in 1080x1920-baseline pixels, like the
    # style defaults; scale it to the output resolution the same way.
    base_size = font_size if font_size is not None else int(style_def["Fontsize"])
    scaled_font_size = int(base_size * scale)

    style_fields = dict(style_def)
    style_fields["Fontsize"] = scaled_font_size
    if position is not None:
        style_fields.update(_position_fields(position, resolution_w, resolution_h))

    style_format = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, "
        "SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
        "MarginV, Encoding"
    )
    style_line = "Style: " + ",".join(
        str(style_fields[k]) for k in _ASS_STYLE_KEYS
    )

    lines: list[str] = [
        "[Script Info]",
        "Title: ClipCannon Captions",
        "ScriptType: v4.00+",
        f"PlayResX: {resolution_w}",
        f"PlayResY: {resolution_h}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        style_format,
        style_line,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text",
    ]

    style_name = str(style_def["Name"])

    for chunk in chunks:
        start = _format_ass_time(chunk.start_ms)
        end = _format_ass_time(chunk.end_ms)

        if style == "karaoke":
            text = _karaoke_dialogue_text(chunk)
        elif style in ("bold_centered", "word_highlight"):
            text = _highlight_dialogue_text(chunk, style)
        else:
            text = _escape_ass_text(chunk.text)

        dialogue = (
            f"Dialogue: 0,{start},{end},{style_name},,0,0,0,,{text}"
        )
        lines.append(dialogue)

    return "\n".join(lines) + "\n"
