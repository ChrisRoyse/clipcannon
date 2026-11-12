"""FFmpeg command entry point plus standard single- and multi-segment builders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .canvas import _build_per_segment_canvas_cmd
from .filters import (
    _apply_xfade_transitions,
    _build_concat_filters,
    _build_delogo_chain,
    _escape_subtitle_path,
    _segment_pts,
    _speed_resample,
)
from .layouts import _build_pip_cmd, _build_split_screen_cmd

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.editing.edl import CanvasSpec, ColorSpec, OverlaySpec, SegmentSpec
    from clipcannon.editing.smart_crop import CropRegion, PipLayout, SplitScreenLayout
    from clipcannon.rendering.profiles import EncodingProfile


def build_ffmpeg_cmd(
    source_path: Path,
    output_path: Path,
    segments: list[SegmentSpec],
    profile: EncodingProfile,
    crop_region: CropRegion | None,
    ass_path: Path | None,
    encoding_args: list[str],
    split_layout: SplitScreenLayout | None = None,
    pip_layout: PipLayout | None = None,
    canvas: CanvasSpec | None = None,
    global_color: ColorSpec | None = None,
    overlays: list[OverlaySpec] | None = None,
    removals: list | None = None,
) -> list[str]:
    """Build the FFmpeg command as a list of arguments.

    Dispatches to the appropriate builder based on layout mode
    and segment count.

    Args:
        source_path: Path to the source video.
        output_path: Path for the rendered output.
        segments: EDL segments to render.
        profile: Encoding profile with codec parameters.
        crop_region: Optional crop region (for "crop" layout only).
        ass_path: Path to ASS subtitle file, or None.
        encoding_args: Pre-built encoding arguments.
        split_layout: Split-screen layout (for "split_screen" layout).
        pip_layout: PIP layout (for "pip" layout).
        canvas: Canvas compositing spec (full AI creative control).
        global_color: Global color grading applied after compositing.
        overlays: Visual overlays (lower thirds, titles, etc.).
        removals: Regions to remove via FFmpeg delogo filter.

    Returns:
        FFmpeg command as a list of strings.
    """
    # Per-segment canvas: check if ANY segment has its own canvas override
    has_per_segment_canvas = any(seg.canvas is not None for seg in segments)

    # Route to per-segment canvas builder if:
    # 1. Any segment has a per-segment canvas override, OR
    # 2. Top-level canvas is enabled with regions, OR
    # 3. Overlays are present (only the canvas path renders them), OR
    # 4. Global color grading is present (only the canvas path applies it)
    if (
        has_per_segment_canvas
        or (canvas is not None and canvas.enabled and canvas.regions)
        or overlays
        or global_color is not None
    ):
        return _build_per_segment_canvas_cmd(
            source_path, output_path, segments,
            profile, canvas, ass_path, encoding_args,
            global_color=global_color,
            overlays=overlays,
            removals=removals,
        )

    # Split-screen layout
    if split_layout is not None:
        return _build_split_screen_cmd(
            source_path, output_path, segments,
            profile, split_layout, ass_path, encoding_args,
        )

    # PIP layout
    if pip_layout is not None:
        return _build_pip_cmd(
            source_path, output_path, segments,
            profile, pip_layout, ass_path, encoding_args,
        )

    # Standard crop layout (no overlays, no color grading)
    if len(segments) == 1:
        return _build_single_segment_cmd(
            source_path, output_path, segments[0],
            profile, crop_region, ass_path, encoding_args,
            removals=removals,
        )
    return _build_multi_segment_cmd(
        source_path, output_path, segments,
        profile, crop_region, ass_path, encoding_args,
        removals=removals,
    )


def _build_single_segment_cmd(
    source_path: Path,
    output_path: Path,
    segment: SegmentSpec,
    profile: EncodingProfile,
    crop_region: CropRegion | None,
    ass_path: Path | None,
    encoding_args: list[str],
    removals: list | None = None,
) -> list[str]:
    """Build FFmpeg command for a single-segment EDL.

    Args:
        source_path: Source video path.
        output_path: Output file path.
        segment: The single segment to render.
        profile: Encoding profile.
        crop_region: Optional crop region.
        ass_path: Optional ASS subtitle path.
        encoding_args: Pre-built encoding arguments.
        removals: Regions to remove via FFmpeg delogo filter.

    Returns:
        FFmpeg command as argument list.
    """
    start_s = segment.source_start_ms / 1000.0
    end_s = segment.source_end_ms / 1000.0

    # Build video filter chain
    vfilters: list[str] = []

    # Apply delogo removals before crop/scale
    if removals:
        for rem in removals:
            vfilters.append(
                f"delogo=x={rem.x}:y={rem.y}:w={rem.width}:h={rem.height}:band=10"
            )

    if crop_region is not None:
        vfilters.append(
            f"crop={crop_region.width}:{crop_region.height}"
            f":{crop_region.x}:{crop_region.y}"
        )

    vfilters.append(f"scale={profile.width}:{profile.height}")

    if segment.speed != 1.0:
        # Speed adjustment via PTS rescale (separate pass for single-
        # segment path where trim/setpts is handled by -ss/-to seeking)
        vfilters.append(
            f"setpts={1.0 / segment.speed}*PTS"
            f"{_speed_resample(segment, profile.fps)}"
        )

    if ass_path is not None:
        escaped = _escape_subtitle_path(ass_path)
        vfilters.append(f"subtitles='{escaped}'")

    vfilter_str = ",".join(vfilters)

    # Build audio filter chain
    afilters: list[str] = []
    if segment.speed != 1.0:
        afilters.append(f"atempo={segment.speed}")

    cmd: list[str] = [
        "ffmpeg", "-y",
        "-ss", f"{start_s:.3f}",
        "-to", f"{end_s:.3f}",
        "-i", str(source_path),
        "-vf", vfilter_str,
    ]

    if afilters:
        cmd.extend(["-af", ",".join(afilters)])

    cmd.extend(encoding_args)
    cmd.append(str(output_path))

    return cmd


def _build_multi_segment_cmd(
    source_path: Path,
    output_path: Path,
    segments: list[SegmentSpec],
    profile: EncodingProfile,
    crop_region: CropRegion | None,
    ass_path: Path | None,
    encoding_args: list[str],
    removals: list | None = None,
) -> list[str]:
    """Build FFmpeg command for multi-segment EDL with concat.

    Uses filter_complex to trim, crop, scale each segment,
    apply xfade transitions, then concatenate.

    Args:
        source_path: Source video path.
        output_path: Output file path.
        segments: List of segments to render.
        profile: Encoding profile.
        crop_region: Optional crop region.
        ass_path: Optional ASS subtitle path.
        encoding_args: Pre-built encoding arguments.
        removals: Regions to remove via FFmpeg delogo filter.

    Returns:
        FFmpeg command as argument list.
    """
    filter_parts: list[str] = []
    video_labels: list[str] = []
    audio_labels: list[str] = []

    delogo_chain = _build_delogo_chain(removals)

    for i, seg in enumerate(segments):
        start_s = seg.source_start_ms / 1000.0
        end_s = seg.source_end_ms / 1000.0

        # Video chain for this segment
        # Combine PTS reset + speed into one expression to avoid
        # an intermediate PTS rounding step.
        pts_expr = _segment_pts(seg)

        vchain = (
            f"[0:v]trim=start={start_s:.3f}:end={end_s:.3f},"
            f"setpts={pts_expr}{_speed_resample(seg, profile.fps)}{delogo_chain}"
        )

        if crop_region is not None:
            vchain += (
                f",crop={crop_region.width}:{crop_region.height}"
                f":{crop_region.x}:{crop_region.y}"
            )

        vchain += f",scale={profile.width}:{profile.height}"

        vlabel = f"v{i}"
        vchain += f"[{vlabel}]"
        filter_parts.append(vchain)
        video_labels.append(vlabel)

        # Audio chain for this segment
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

    # Apply xfade transitions between video and audio segments
    if len(video_labels) > 1:
        video_labels, audio_labels = _apply_xfade_transitions(
            filter_parts, video_labels, audio_labels, segments,
        )

    # Concatenate remaining segments
    final_video, final_audio = _build_concat_filters(
        filter_parts, video_labels, audio_labels,
    )

    # Audio sync correction: force audio to resync with video PTS.
    # After concat, accumulated AAC codec frame padding (~23ms per
    # segment) causes progressive audio drift.  aresample=async=1
    # inserts/removes samples to re-align audio to the video timeline.
    if len(segments) > 1:
        sync_filter = (
            f"[{final_audio}]aresample=async=1:first_pts=0[async_a]"
        )
        filter_parts.append(sync_filter)
        final_audio = "async_a"

    # Apply subtitles to final video
    if ass_path is not None:
        escaped = _escape_subtitle_path(ass_path)
        sub_filter = (
            f"[{final_video}]subtitles='{escaped}'[subbed]"
        )
        filter_parts.append(sub_filter)
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
