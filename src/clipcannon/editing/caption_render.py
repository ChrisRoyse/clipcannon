"""Caption rendering output for ClipCannon.

Generates ASS subtitle files and FFmpeg drawtext filter strings
from caption chunks. Supports four styles: bold_centered,
word_highlight, subtitle_bar, and karaoke.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from clipcannon.editing.edl import CaptionChunk

# ============================================================
# ASS SUBTITLE STYLE DEFINITIONS
# ============================================================
_ASS_STYLE_KEYS: list[str] = [
    "Name",
    "Fontname",
    "Fontsize",
    "PrimaryColour",
    "SecondaryColour",
    "OutlineColour",
    "BackColour",
    "Bold",
    "Italic",
    "Underline",
    "StrikeOut",
    "ScaleX",
    "ScaleY",
    "Spacing",
    "Angle",
    "BorderStyle",
    "Outline",
    "Shadow",
    "Alignment",
    "MarginL",
    "MarginR",
    "MarginV",
    "Encoding",
]

ASS_STYLES: dict[str, dict[str, str | int]] = {
    "bold_centered": {
        "Name": "BoldCentered",
        "Fontname": "Montserrat Bold",
        "Fontsize": 48,
        "PrimaryColour": "&H00FFFFFF",
        "SecondaryColour": "&H0000FFFF",
        "OutlineColour": "&H00000000",
        "BackColour": "&H80000000",
        "Bold": 1,
        "Italic": 0,
        "Underline": 0,
        "StrikeOut": 0,
        "ScaleX": 100,
        "ScaleY": 100,
        "Spacing": 0,
        "Angle": 0,
        "BorderStyle": 1,
        "Outline": 3,
        "Shadow": 2,
        "Alignment": 2,
        "MarginL": 10,
        "MarginR": 10,
        "MarginV": 400,
        "Encoding": 1,
    },
    "word_highlight": {
        "Name": "WordHighlight",
        "Fontname": "Montserrat Bold",
        "Fontsize": 44,
        "PrimaryColour": "&H00999999",
        "SecondaryColour": "&H0000FFFF",
        "OutlineColour": "&H00000000",
        "BackColour": "&H80000000",
        "Bold": 1,
        "Italic": 0,
        "Underline": 0,
        "StrikeOut": 0,
        "ScaleX": 100,
        "ScaleY": 100,
        "Spacing": 0,
        "Angle": 0,
        "BorderStyle": 1,
        "Outline": 2,
        "Shadow": 0,
        "Alignment": 2,
        "MarginL": 10,
        "MarginR": 10,
        "MarginV": 30,
        "Encoding": 1,
    },
    "subtitle_bar": {
        "Name": "SubtitleBar",
        "Fontname": "Inter",
        "Fontsize": 32,
        "PrimaryColour": "&H00FFFFFF",
        "SecondaryColour": "&H00FFFFFF",
        "OutlineColour": "&H00000000",
        "BackColour": "&HB4000000",
        "Bold": 0,
        "Italic": 0,
        "Underline": 0,
        "StrikeOut": 0,
        "ScaleX": 100,
        "ScaleY": 100,
        "Spacing": 0,
        "Angle": 0,
        "BorderStyle": 3,
        "Outline": 0,
        "Shadow": 0,
        "Alignment": 2,
        "MarginL": 20,
        "MarginR": 20,
        "MarginV": 50,
        "Encoding": 1,
    },
    "karaoke": {
        "Name": "Karaoke",
        "Fontname": "Montserrat Bold",
        "Fontsize": 40,
        "PrimaryColour": "&H99FFFFFF",
        "SecondaryColour": "&H00FFFF00",
        "OutlineColour": "&H00000000",
        "BackColour": "&H80000000",
        "Bold": 1,
        "Italic": 0,
        "Underline": 0,
        "StrikeOut": 0,
        "ScaleX": 100,
        "ScaleY": 100,
        "Spacing": 0,
        "Angle": 0,
        "BorderStyle": 1,
        "Outline": 2,
        "Shadow": 0,
        "Alignment": 2,
        "MarginL": 10,
        "MarginR": 10,
        "MarginV": 400,
        "Encoding": 1,
    },
}

# Valid caption style type
CaptionStyleLiteral = Literal[
    "bold_centered", "word_highlight", "subtitle_bar", "karaoke"
]


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
def generate_ass_file(
    chunks: list[CaptionChunk],
    style: CaptionStyleLiteral,
    resolution_w: int = 1080,
    resolution_h: int = 1920,
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
    scaled_font_size = int(int(style_def["Fontsize"]) * scale)

    style_fields = dict(style_def)
    style_fields["Fontsize"] = scaled_font_size

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


# ============================================================
# FFMPEG DRAWTEXT FILTERS
# ============================================================
def _escape_drawtext(text: str) -> str:
    """Escape text for FFmpeg drawtext filter.

    Args:
        text: Raw text to escape.

    Returns:
        Escaped text safe for drawtext filter.
    """
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "'\\''")
    text = text.replace(":", "\\:")
    text = text.replace(";", "\\;")
    return text


def generate_drawtext_filters(
    chunks: list[CaptionChunk],
    style: CaptionStyleLiteral,
) -> list[str]:
    """Generate FFmpeg drawtext filter strings as fallback.

    Each chunk produces one or more drawtext filter expressions.
    For highlight styles, per-word overlapping filters are generated.

    Args:
        chunks: Caption chunks from chunk_transcript_words().
        style: Caption style to apply.

    Returns:
        List of drawtext filter strings.
    """
    filters: list[str] = []

    style_def = ASS_STYLES.get(style, ASS_STYLES["bold_centered"])
    font_name = str(style_def["Fontname"])
    font_size = int(style_def["Fontsize"])

    for chunk in chunks:
        start_s = chunk.start_ms / 1000.0
        end_s = chunk.end_ms / 1000.0
        escaped_text = _escape_drawtext(chunk.text)

        if style == "subtitle_bar":
            _append_subtitle_bar(
                filters, escaped_text, font_name, font_size,
                start_s, end_s,
            )
        elif style in ("bold_centered", "word_highlight", "karaoke"):
            _append_highlight_filters(
                filters, chunk, escaped_text, font_name, font_size,
                start_s, end_s, style,
            )
        else:
            _append_basic_filter(
                filters, escaped_text, font_name, font_size,
                start_s, end_s,
            )

    return filters


def _append_subtitle_bar(
    filters: list[str],
    text: str,
    font_name: str,
    font_size: int,
    start_s: float,
    end_s: float,
) -> None:
    """Append a subtitle bar drawtext filter."""
    filt = (
        f"drawtext=text='{text}'"
        f":fontfile={font_name}"
        f":fontsize={font_size}"
        f":fontcolor=white"
        f":borderw=0"
        f":box=1:boxcolor=black@0.7:boxborderw=8"
        f":x=(w-tw)/2:y=h*0.90"
        f":enable='between(t,{start_s:.3f},{end_s:.3f})'"
    )
    filters.append(filt)


def _append_highlight_filters(
    filters: list[str],
    chunk: CaptionChunk,
    text: str,
    font_name: str,
    font_size: int,
    start_s: float,
    end_s: float,
    style: str,
) -> None:
    """Append highlight-style drawtext filters with per-word layers."""
    fontcolor = "0x999999" if style == "word_highlight" else "white"

    filt = (
        f"drawtext=text='{text}'"
        f":fontfile={font_name}"
        f":fontsize={font_size}"
        f":fontcolor={fontcolor}"
        f":borderw=3:bordercolor=black"
        f":x=(w-tw)/2:y=h*0.75"
        f":enable='between(t,{start_s:.3f},{end_s:.3f})'"
    )
    filters.append(filt)

    if chunk.words and style != "karaoke":
        for word in chunk.words:
            w_start = word.start_ms / 1000.0
            w_end = word.end_ms / 1000.0
            w_text = _escape_drawtext(word.word)
            hl_filt = (
                f"drawtext=text='{w_text}'"
                f":fontfile={font_name}"
                f":fontsize={font_size}"
                f":fontcolor=yellow"
                f":borderw=3:bordercolor=black"
                f":x=(w-tw)/2:y=h*0.75"
                f":enable='between(t,{w_start:.3f},{w_end:.3f})'"
            )
            filters.append(hl_filt)


def _append_basic_filter(
    filters: list[str],
    text: str,
    font_name: str,
    font_size: int,
    start_s: float,
    end_s: float,
) -> None:
    """Append a basic drawtext filter."""
    filt = (
        f"drawtext=text='{text}'"
        f":fontfile={font_name}"
        f":fontsize={font_size}"
        f":fontcolor=white"
        f":borderw=3:bordercolor=black"
        f":x=(w-tw)/2:y=h*0.75"
        f":enable='between(t,{start_s:.3f},{end_s:.3f})'"
    )
    filters.append(filt)
