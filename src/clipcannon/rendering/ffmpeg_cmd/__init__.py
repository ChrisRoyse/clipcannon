"""FFmpeg command building for ClipCannon rendering.

Constructs FFmpeg commands for single-segment and multi-segment EDLs
with support for transitions, crop, scale, speed, subtitle filters,
split-screen layouts, and picture-in-picture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from clipcannon.editing.edl import CanvasRegion, SegmentCanvasSpec

from .canvas import _build_per_segment_canvas_cmd
from .canvas_chains import (
    _build_region_scale,
    _build_segment_canvas_chain,
    _build_segment_plain_chain,
    _build_segment_track_chain,
    _build_segment_zoom_chain,
    _piecewise_expr,
)
from .filters import (
    _XFADE_MAP,
    _apply_color_grading,
    _apply_xfade_transitions,
    _build_concat_filters,
    _build_delogo_chain,
    _escape_subtitle_path,
    _segment_pts,
    build_encoding_args,
)
from .layouts import (
    _build_pip_cmd,
    _build_split_screen_cmd,
    _build_split_screen_multi_segment,
    _build_vstack_filters,
)
from .preview import build_preview_cmd, build_zoom_preview_cmd
from .standard import _build_multi_segment_cmd, _build_single_segment_cmd, build_ffmpeg_cmd

__all__: list[str] = [
    "CanvasRegion", "SegmentCanvasSpec", "TYPE_CHECKING", "_XFADE_MAP", "_apply_color_grading",
    "_apply_xfade_transitions", "_build_concat_filters", "_build_delogo_chain",
    "_build_multi_segment_cmd", "_build_per_segment_canvas_cmd", "_build_pip_cmd",
    "_build_region_scale", "_build_segment_canvas_chain", "_build_segment_plain_chain",
    "_build_segment_track_chain", "_build_segment_zoom_chain", "_build_single_segment_cmd",
    "_build_split_screen_cmd", "_build_split_screen_multi_segment", "_build_vstack_filters",
    "_escape_subtitle_path", "_piecewise_expr", "_segment_pts", "build_encoding_args",
    "build_ffmpeg_cmd", "build_preview_cmd", "build_zoom_preview_cmd",
]
