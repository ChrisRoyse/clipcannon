"""Caption rendering output for ClipCannon.

Generates ASS subtitle files and FFmpeg drawtext filter strings
from caption chunks. Supports four styles: bold_centered,
word_highlight, subtitle_bar, and karaoke.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from .ass import (
    _escape_ass_text,
    _format_ass_time,
    _hex_to_ass_color,
    _highlight_dialogue_text,
    _karaoke_dialogue_text,
    _position_fields,
    generate_ass_file,
)
from .drawtext import (
    _append_basic_filter,
    _append_highlight_filters,
    _append_subtitle_bar,
    _escape_drawtext,
    generate_drawtext_filters,
)
from .styles import _ASS_STYLE_KEYS, ASS_STYLES, CaptionStyleLiteral

__all__: list[str] = [
    "ASS_STYLES", "CaptionStyleLiteral", "Literal", "TYPE_CHECKING", "_ASS_STYLE_KEYS",
    "_append_basic_filter", "_append_highlight_filters", "_append_subtitle_bar",
    "_escape_ass_text", "_escape_drawtext", "_format_ass_time", "_hex_to_ass_color",
    "_highlight_dialogue_text", "_karaoke_dialogue_text", "_position_fields", "generate_ass_file",
    "generate_drawtext_filters",
]
