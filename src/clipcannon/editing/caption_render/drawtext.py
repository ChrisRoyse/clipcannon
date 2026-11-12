"""FFmpeg drawtext caption filter generation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .styles import ASS_STYLES

if TYPE_CHECKING:
    from clipcannon.editing.edl import CaptionChunk

    from .styles import CaptionStyleLiteral


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
