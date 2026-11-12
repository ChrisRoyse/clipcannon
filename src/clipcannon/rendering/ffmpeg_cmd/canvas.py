"""Per-segment canvas FFmpeg command builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from clipcannon.editing.edl import SegmentCanvasSpec

from .canvas_chains import (
    _build_segment_canvas_chain,
    _build_segment_plain_chain,
    _build_segment_track_chain,
    _build_segment_zoom_chain,
)
from .filters import (
    _apply_color_grading,
    _apply_xfade_transitions,
    _build_concat_filters,
    _escape_subtitle_path,
)

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.editing.edl import CanvasSpec, ColorSpec, OverlaySpec, SegmentSpec
    from clipcannon.rendering.profiles import EncodingProfile


# ============================================================
# PER-SEGMENT CANVAS -- Full AI creative control
# ============================================================
def _build_per_segment_canvas_cmd(
    source_path: Path,
    output_path: Path,
    segments: list[SegmentSpec],
    profile: EncodingProfile,
    top_level_canvas: CanvasSpec | None,
    ass_path: Path | None,
    encoding_args: list[str],
    global_color: ColorSpec | None = None,
    overlays: list[OverlaySpec] | None = None,
    removals: list | None = None,
) -> list[str]:
    """Build FFmpeg command with per-segment canvas compositing.

    Each segment gets its own independent filter chain based on its
    layout configuration. Segments are then concatenated.

    Resolution priority per segment:
      segment.canvas (if set)
        -> top-level canvas (if enabled)
          -> plain scale fallback

    Args:
        source_path: Source video path.
        output_path: Output file path.
        segments: EDL segments, each optionally with its own canvas.
        profile: Encoding profile.
        top_level_canvas: Global canvas spec (fallback).
        ass_path: Optional ASS subtitle path.
        encoding_args: Encoding arguments.
        global_color: Global color grading applied after compositing.
        overlays: Visual overlays applied after compositing.
        removals: Regions to remove via FFmpeg delogo filter.

    Returns:
        FFmpeg command as argument list.
    """
    cw = profile.width
    ch = profile.height

    # Use top-level canvas dimensions if available
    if top_level_canvas is not None and top_level_canvas.enabled:
        cw = top_level_canvas.canvas_width
        ch = top_level_canvas.canvas_height

    filter_parts: list[str] = []
    video_labels: list[str] = []
    audio_labels: list[str] = []

    for i, seg in enumerate(segments):
        # Build video chain for this segment based on its layout
        if seg.canvas is not None and seg.canvas.track is not None:
            _build_segment_track_chain(
                filter_parts, seg, i, cw, ch, removals=removals, fps=profile.fps,
            )
        elif seg.canvas is not None and seg.canvas.zoom is not None:
            _build_segment_zoom_chain(
                filter_parts, seg, i, profile, cw, ch,
                removals=removals,
            )
        elif seg.canvas is not None and seg.canvas.regions:
            _build_segment_canvas_chain(
                filter_parts, seg, i, profile, cw, ch, seg.canvas,
                removals=removals,
            )
        elif (
            top_level_canvas is not None
            and top_level_canvas.enabled
            and top_level_canvas.regions
        ):
            # Convert top-level CanvasSpec to SegmentCanvasSpec for reuse
            seg_canvas = SegmentCanvasSpec(
                regions=list(top_level_canvas.regions),
                background_color=top_level_canvas.background_color,
            )
            _build_segment_canvas_chain(
                filter_parts, seg, i, profile, cw, ch, seg_canvas,
                removals=removals,
            )
        else:
            _build_segment_plain_chain(
                filter_parts, seg, i, profile,
                removals=removals,
            )

        video_labels.append(f"v{i}")

        # Audio chain for this segment
        start_s = seg.source_start_ms / 1000.0
        end_s = seg.source_end_ms / 1000.0
        achain = (
            f"[0:a]atrim=start={start_s:.3f}:end={end_s:.3f},"
            f"asetpts=PTS-STARTPTS"
        )
        if seg.speed != 1.0:
            achain += f",atempo={seg.speed}"
        alabel = f"a{i}"
        achain += f"[{alabel}]"
        filter_parts.append(achain)
        audio_labels.append(alabel)

    # Apply xfade transitions between segments (if specified)
    if len(video_labels) > 1:
        video_labels, audio_labels = _apply_xfade_transitions(
            filter_parts, video_labels, audio_labels, segments,
        )

    # Concatenate remaining segments
    final_video, final_audio = _build_concat_filters(
        filter_parts, video_labels, audio_labels,
    )

    # Apply global color grading (after concat, before subtitles)
    if global_color is not None:
        final_video = _apply_color_grading(
            filter_parts, final_video, "color_graded", global_color,
        )

    # Apply overlay drawtext/drawbox filters
    if overlays:
        from clipcannon.editing.overlays import build_overlay_filters

        overlay_idx = 0
        for overlay in overlays:
            ov_filters = build_overlay_filters(
                overlay_type=overlay.overlay_type,
                text=overlay.text,
                subtitle=overlay.subtitle,
                position=overlay.position,
                start_ms=overlay.start_ms,
                end_ms=overlay.end_ms,
                opacity=overlay.opacity,
                font_size=overlay.font_size,
                text_color=overlay.text_color,
                bg_color=overlay.bg_color,
                bg_opacity=overlay.bg_opacity,
                animation=overlay.animation,
                animation_duration_ms=overlay.animation_duration_ms,
            )
            for filt in ov_filters:
                out_label = f"ov{overlay_idx}"
                filter_parts.append(
                    f"[{final_video}]{filt}[{out_label}]"
                )
                final_video = out_label
                overlay_idx += 1

    # Apply subtitles to final composited video
    if ass_path is not None:
        escaped = _escape_subtitle_path(ass_path)
        filter_parts.append(
            f"[{final_video}]subtitles='{escaped}'[subbed]"
        )
        final_video = "subbed"

    filter_complex = ";".join(filter_parts)

    cmd: list[str] = [
        "ffmpeg", "-y",
        "-i", str(source_path),
        "-filter_complex", filter_complex,
        "-map", f"[{final_video}]",
        "-map", f"[{final_audio}]",
    ]
    cmd.extend(encoding_args)
    cmd.append(str(output_path))

    return cmd
