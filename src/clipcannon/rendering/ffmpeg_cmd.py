"""FFmpeg command building for ClipCannon rendering.

Constructs FFmpeg commands for single-segment and multi-segment EDLs
with support for transitions, crop, scale, speed, subtitle filters,
split-screen layouts, and picture-in-picture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from clipcannon.editing.edl import CanvasRegion, SegmentCanvasSpec

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.editing.edl import (
        CanvasSpec,
        SegmentSpec,
    )
    from clipcannon.editing.smart_crop import (
        CropRegion,
        PipLayout,
        SplitScreenLayout,
    )
    from clipcannon.rendering.profiles import EncodingProfile

# Transition type mapping for FFmpeg xfade filter
_XFADE_MAP: dict[str, str] = {
    "fade": "fade",
    "crossfade": "fade",
    "dissolve": "dissolve",
    "wipe_left": "wipeleft",
    "wipe_right": "wiperight",
    "wipe_up": "wipeup",
    "wipe_down": "wipedown",
    "slide_left": "slideleft",
    "slide_right": "slideright",
    "zoom_in": "zoomin",
}


def _escape_subtitle_path(path: Path) -> str:
    """Escape a file path for use in FFmpeg subtitle filters.

    Args:
        path: Path to the ASS subtitle file.

    Returns:
        Escaped path string safe for FFmpeg filter syntax.
    """
    escaped = str(path).replace("\\", "\\\\")
    return escaped.replace(":", "\\:")


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

    Returns:
        FFmpeg command as a list of strings.
    """
    # Per-segment canvas: check if ANY segment has its own canvas override
    has_per_segment_canvas = any(seg.canvas is not None for seg in segments)

    # Route to per-segment canvas builder if:
    # 1. Any segment has a per-segment canvas override, OR
    # 2. Top-level canvas is enabled with regions
    if has_per_segment_canvas or (canvas is not None and canvas.enabled and canvas.regions):
        return _build_per_segment_canvas_cmd(
            source_path, output_path, segments,
            profile, canvas, ass_path, encoding_args,
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

    # Standard crop layout
    if len(segments) == 1:
        return _build_single_segment_cmd(
            source_path, output_path, segments[0],
            profile, crop_region, ass_path, encoding_args,
        )
    return _build_multi_segment_cmd(
        source_path, output_path, segments,
        profile, crop_region, ass_path, encoding_args,
    )


def _build_single_segment_cmd(
    source_path: Path,
    output_path: Path,
    segment: SegmentSpec,
    profile: EncodingProfile,
    crop_region: CropRegion | None,
    ass_path: Path | None,
    encoding_args: list[str],
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

    Returns:
        FFmpeg command as argument list.
    """
    start_s = segment.source_start_ms / 1000.0
    end_s = segment.source_end_ms / 1000.0

    # Build video filter chain
    vfilters: list[str] = []

    if crop_region is not None:
        vfilters.append(
            f"crop={crop_region.width}:{crop_region.height}"
            f":{crop_region.x}:{crop_region.y}"
        )

    vfilters.append(f"scale={profile.width}:{profile.height}")

    if segment.speed != 1.0:
        vfilters.append(f"setpts={1.0 / segment.speed}*PTS")

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

    Returns:
        FFmpeg command as argument list.
    """
    filter_parts: list[str] = []
    video_labels: list[str] = []
    audio_labels: list[str] = []

    for i, seg in enumerate(segments):
        start_s = seg.source_start_ms / 1000.0
        end_s = seg.source_end_ms / 1000.0

        # Video chain for this segment
        vchain = (
            f"[0:v]trim=start={start_s:.3f}:end={end_s:.3f},"
            f"setpts=PTS-STARTPTS"
        )

        if crop_region is not None:
            vchain += (
                f",crop={crop_region.width}:{crop_region.height}"
                f":{crop_region.x}:{crop_region.y}"
            )

        vchain += f",scale={profile.width}:{profile.height}"

        if seg.speed != 1.0:
            vchain += f",setpts={1.0 / seg.speed}*PTS"

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


def _build_concat_filters(
    filter_parts: list[str],
    video_labels: list[str],
    audio_labels: list[str],
) -> tuple[str, str]:
    """Build concat filter parts and return final stream labels.

    Args:
        filter_parts: Accumulating filter_complex parts (modified in place).
        video_labels: Current video stream labels.
        audio_labels: Current audio stream labels.

    Returns:
        Tuple of (final_video_label, final_audio_label).
    """
    if len(video_labels) > 1:
        concat_inputs = "".join(
            f"[{v}][{a}]"
            for v, a in zip(video_labels, audio_labels, strict=True)
        )
        n = len(video_labels)
        concat_filter = (
            f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]"
        )
        filter_parts.append(concat_filter)
        return "outv", "outa"

    final_video = video_labels[0]
    # Also concat audio if we had xfade on video
    if len(audio_labels) > 1:
        aconcat = "".join(f"[{a}]" for a in audio_labels)
        aconcat += (
            f"concat=n={len(audio_labels)}:v=0:a=1[outa]"
        )
        filter_parts.append(aconcat)
        return final_video, "outa"

    return final_video, audio_labels[0]


def _apply_xfade_transitions(
    filter_parts: list[str],
    video_labels: list[str],
    audio_labels: list[str],
    segments: list[SegmentSpec],
) -> tuple[list[str], list[str]]:
    """Apply xfade transitions between consecutive video segments.

    Merges video with xfade and audio with acrossfade in parallel,
    keeping both label lists the same length.

    Args:
        filter_parts: Accumulating filter_complex parts.
        video_labels: Current video stream labels.
        audio_labels: Current audio stream labels.
        segments: EDL segments with transition specs.

    Returns:
        Tuple of (updated video labels, updated audio labels).
    """
    v_labels = list(video_labels)
    a_labels = list(audio_labels)

    i = 0
    xf_counter = 0
    while i < len(v_labels) - 1 and i < len(segments) - 1:
        seg = segments[i + xf_counter] if i + xf_counter < len(segments) else None
        next_idx = i + xf_counter + 1
        next_seg = segments[next_idx] if next_idx < len(segments) else None

        if seg is None or next_seg is None:
            i += 1
            continue

        transition = seg.transition_out or next_seg.transition_in
        if transition is None or transition.type == "cut":
            i += 1
            continue

        xfade_type = _XFADE_MAP.get(transition.type, "fade")
        duration_s = transition.duration_ms / 1000.0
        offset_s = seg.output_duration_ms / 1000.0 - duration_s

        if offset_s < 0:
            i += 1
            continue

        # Video xfade
        v_out = f"xfv{xf_counter}"
        xfade_filter = (
            f"[{v_labels[i]}][{v_labels[i + 1]}]"
            f"xfade=transition={xfade_type}"
            f":duration={duration_s:.3f}"
            f":offset={offset_s:.3f}"
            f"[{v_out}]"
        )
        filter_parts.append(xfade_filter)

        # Audio acrossfade
        a_out = f"xfa{xf_counter}"
        acrossfade_filter = (
            f"[{a_labels[i]}][{a_labels[i + 1]}]"
            f"acrossfade=d={duration_s:.3f}"
            f"[{a_out}]"
        )
        filter_parts.append(acrossfade_filter)

        # Replace both entries with merged label
        v_labels[i] = v_out
        v_labels.pop(i + 1)
        a_labels[i] = a_out
        a_labels.pop(i + 1)

        xf_counter += 1
        # Don't increment i - the next pair is now at the same index

    return v_labels, a_labels


def build_encoding_args(
    profile: EncodingProfile,
    nvenc_preset: str | None = None,
) -> list[str]:
    """Build encoding-related FFmpeg arguments.

    Args:
        profile: Encoding profile with codec parameters.
        nvenc_preset: NVENC preset string, or None for non-NVENC codecs.

    Returns:
        List of FFmpeg encoding arguments.
    """
    args: list[str] = [
        "-c:v", profile.video_codec,
        "-b:v", profile.video_bitrate,
        "-maxrate", profile.max_bitrate,
        "-bufsize", profile.bufsize,
        "-r", str(profile.fps),
        "-c:a", profile.audio_codec,
        "-b:a", profile.audio_bitrate,
        "-ar", str(profile.audio_sample_rate),
        "-movflags", profile.movflags,
    ]

    if "nvenc" in profile.video_codec and nvenc_preset:
        args.extend(["-preset", nvenc_preset])

    return args


# ============================================================
# SPLIT-SCREEN LAYOUT
# ============================================================
def _build_vstack_filters(
    speaker_label: str,
    screen_label: str,
    bar_label: str | None,
    out_label: str,
    layout: SplitScreenLayout,
    filter_parts: list[str],
) -> None:
    """Append vstack filter(s) to combine speaker and screen regions.

    Handles separator bar and speaker position (top/bottom).
    Modifies filter_parts in place.

    Args:
        speaker_label: FFmpeg stream label for the speaker region.
        screen_label: FFmpeg stream label for the screen region.
        bar_label: FFmpeg stream label for separator bar, or None if no separator.
        out_label: Output stream label for the stacked result.
        layout: Split-screen layout config (for separator and position).
        filter_parts: Accumulating filter_complex parts (modified in place).
    """
    if layout.separator_px > 0 and bar_label is not None:
        hex_color = layout.separator_color.lstrip("#")
        filter_parts.append(
            f"color=c=0x{hex_color}:s={layout.output_w}x{layout.separator_px}"
            f":d=99999,setsar=1[{bar_label}]"
        )
        if layout.speaker_position == "top":
            filter_parts.append(
                f"[{speaker_label}][{bar_label}][{screen_label}]"
                f"vstack=inputs=3[{out_label}]"
            )
        else:
            filter_parts.append(
                f"[{screen_label}][{bar_label}][{speaker_label}]"
                f"vstack=inputs=3[{out_label}]"
            )
    else:
        if layout.speaker_position == "top":
            filter_parts.append(
                f"[{speaker_label}][{screen_label}]vstack=inputs=2[{out_label}]"
            )
        else:
            filter_parts.append(
                f"[{screen_label}][{speaker_label}]vstack=inputs=2[{out_label}]"
            )


def _build_split_screen_cmd(
    source_path: Path,
    output_path: Path,
    segments: list[SegmentSpec],
    profile: EncodingProfile,
    layout: SplitScreenLayout,
    ass_path: Path | None,
    encoding_args: list[str],
) -> list[str]:
    """Build FFmpeg command for split-screen vertical layout.

    Splits the source into speaker and screen regions, crops and
    scales each independently, then stacks them vertically with
    an optional separator bar.

    Speaker top + screen bottom (or reversed based on layout config).

    Args:
        source_path: Source video path.
        output_path: Output file path.
        segments: EDL segments.
        profile: Encoding profile.
        layout: Split-screen layout with computed regions.
        ass_path: Optional ASS subtitle path.
        encoding_args: Pre-built encoding arguments.

    Returns:
        FFmpeg command as argument list.
    """
    # For multi-segment, we trim first, then apply the split layout
    if len(segments) > 1:
        return _build_split_screen_multi_segment(
            source_path, output_path, segments,
            profile, layout, ass_path, encoding_args,
        )

    seg = segments[0]
    start_s = seg.source_start_ms / 1000.0
    end_s = seg.source_end_ms / 1000.0

    ow = layout.output_w
    sp_h = layout.speaker_out_h
    scr_h = layout.screen_out_h
    sep = layout.separator_px

    # Build filter_complex for split-screen
    filters: list[str] = []

    # Split input into two streams
    filters.append("[0:v]split=2[forspeaker][forscreen]")

    # Crop and scale the speaker region
    filters.append(
        f"[forspeaker]crop={layout.speaker_src_w}:{layout.speaker_src_h}"
        f":{layout.speaker_src_x}:{layout.speaker_src_y},"
        f"scale={ow}:{sp_h},setsar=1[speaker]"
    )

    # Crop and scale the screen region
    filters.append(
        f"[forscreen]crop={layout.screen_src_w}:{layout.screen_src_h}"
        f":{layout.screen_src_x}:{layout.screen_src_y},"
        f"scale={ow}:{scr_h},setsar=1[screen]"
    )

    # Stack speaker and screen regions with optional separator
    _build_vstack_filters(
        speaker_label="speaker",
        screen_label="screen",
        bar_label="bar" if sep > 0 else None,
        out_label="stacked",
        layout=layout,
        filter_parts=filters,
    )

    # Apply speed adjustment if needed
    final_v = "stacked"
    if seg.speed != 1.0:
        filters.append(
            f"[stacked]setpts={1.0 / seg.speed}*PTS[speeded]"
        )
        final_v = "speeded"

    # Apply subtitles if present
    if ass_path is not None:
        escaped = _escape_subtitle_path(ass_path)
        filters.append(
            f"[{final_v}]subtitles='{escaped}'[subbed]"
        )
        final_v = "subbed"

    # Audio filters
    afilters: list[str] = []
    if seg.speed != 1.0:
        afilters.append(f"atempo={seg.speed}")

    filter_complex = ";".join(filters)

    cmd: list[str] = [
        "ffmpeg", "-y",
        "-ss", f"{start_s:.3f}",
        "-to", f"{end_s:.3f}",
        "-i", str(source_path),
        "-filter_complex", filter_complex,
        "-map", f"[{final_v}]",
        "-map", "0:a",
    ]

    if afilters:
        cmd.extend(["-af", ",".join(afilters)])

    cmd.extend(encoding_args)
    cmd.append(str(output_path))

    return cmd


def _build_split_screen_multi_segment(
    source_path: Path,
    output_path: Path,
    segments: list[SegmentSpec],
    profile: EncodingProfile,
    layout: SplitScreenLayout,
    ass_path: Path | None,
    encoding_args: list[str],
) -> list[str]:
    """Build split-screen command for multi-segment EDLs.

    Each segment is trimmed, split into speaker+screen, stacked,
    then all segments are concatenated.

    Args:
        source_path: Source video path.
        output_path: Output file path.
        segments: Multiple EDL segments.
        profile: Encoding profile.
        layout: Split-screen layout.
        ass_path: Optional ASS subtitle path.
        encoding_args: Encoding arguments.

    Returns:
        FFmpeg command as argument list.
    """
    ow = layout.output_w
    sp_h = layout.speaker_out_h
    scr_h = layout.screen_out_h
    sep = layout.separator_px

    filter_parts: list[str] = []
    video_labels: list[str] = []
    audio_labels: list[str] = []

    for i, seg in enumerate(segments):
        start_s = seg.source_start_ms / 1000.0
        end_s = seg.source_end_ms / 1000.0

        # Trim and split for this segment
        filter_parts.append(
            f"[0:v]trim=start={start_s:.3f}:end={end_s:.3f},"
            f"setpts=PTS-STARTPTS,"
            f"split=2[sp{i}][sc{i}]"
        )

        # Speaker crop+scale
        filter_parts.append(
            f"[sp{i}]crop={layout.speaker_src_w}:{layout.speaker_src_h}"
            f":{layout.speaker_src_x}:{layout.speaker_src_y},"
            f"scale={ow}:{sp_h},setsar=1[spk{i}]"
        )

        # Screen crop+scale
        filter_parts.append(
            f"[sc{i}]crop={layout.screen_src_w}:{layout.screen_src_h}"
            f":{layout.screen_src_x}:{layout.screen_src_y},"
            f"scale={ow}:{scr_h},setsar=1[scn{i}]"
        )

        # Stack speaker and screen regions
        _build_vstack_filters(
            speaker_label=f"spk{i}",
            screen_label=f"scn{i}",
            bar_label=f"bar{i}" if sep > 0 else None,
            out_label=f"v{i}",
            layout=layout,
            filter_parts=filter_parts,
        )

        video_labels.append(f"v{i}")

        # Audio trim
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

    # Concatenate all segments
    final_video, final_audio = _build_concat_filters(
        filter_parts, video_labels, audio_labels,
    )

    # Apply subtitles
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


# ============================================================
# PIP (PICTURE-IN-PICTURE) LAYOUT
# ============================================================
def _build_pip_cmd(
    source_path: Path,
    output_path: Path,
    segments: list[SegmentSpec],
    profile: EncodingProfile,
    layout: PipLayout,
    ass_path: Path | None,
    encoding_args: list[str],
) -> list[str]:
    """Build FFmpeg command for picture-in-picture layout.

    Full-screen background with a small speaker overlay in a corner.

    Args:
        source_path: Source video path.
        output_path: Output file path.
        segments: EDL segments.
        profile: Encoding profile.
        layout: PIP layout with positions.
        ass_path: Optional ASS subtitle path.
        encoding_args: Encoding arguments.

    Returns:
        FFmpeg command as argument list.
    """
    seg = segments[0]
    start_s = seg.source_start_ms / 1000.0
    end_s = seg.source_end_ms / 1000.0

    ow = layout.output_w
    oh = layout.output_h

    filters: list[str] = []

    # Split input into background and PIP
    filters.append("[0:v]split=2[forbg][forpip]")

    # Background: scale full source to fill output
    filters.append(
        f"[forbg]scale={ow}:{oh},setsar=1[bg]"
    )

    # PIP: crop speaker region and scale to PIP size
    filters.append(
        f"[forpip]crop={layout.pip_src_w}:{layout.pip_src_h}"
        f":{layout.pip_src_x}:{layout.pip_src_y},"
        f"scale={layout.pip_out_w}:{layout.pip_out_h},setsar=1[pip]"
    )

    # Overlay PIP on background
    filters.append(
        f"[bg][pip]overlay=x={layout.pip_x}:y={layout.pip_y}[composed]"
    )

    final_v = "composed"

    # Speed
    if seg.speed != 1.0:
        filters.append(
            f"[composed]setpts={1.0 / seg.speed}*PTS[speeded]"
        )
        final_v = "speeded"

    # Subtitles
    if ass_path is not None:
        escaped = _escape_subtitle_path(ass_path)
        filters.append(
            f"[{final_v}]subtitles='{escaped}'[subbed]"
        )
        final_v = "subbed"

    filter_complex = ";".join(filters)

    afilters: list[str] = []
    if seg.speed != 1.0:
        afilters.append(f"atempo={seg.speed}")

    cmd: list[str] = [
        "ffmpeg", "-y",
        "-ss", f"{start_s:.3f}",
        "-to", f"{end_s:.3f}",
        "-i", str(source_path),
        "-filter_complex", filter_complex,
        "-map", f"[{final_v}]",
        "-map", "0:a",
    ]

    if afilters:
        cmd.extend(["-af", ",".join(afilters)])

    cmd.extend(encoding_args)
    cmd.append(str(output_path))

    return cmd




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
        if seg.canvas is not None and seg.canvas.zoom is not None:
            _build_segment_zoom_chain(filter_parts, seg, i, profile, cw, ch)
        elif seg.canvas is not None and seg.canvas.regions:
            _build_segment_canvas_chain(
                filter_parts, seg, i, profile, cw, ch, seg.canvas,
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
            )
        else:
            _build_segment_plain_chain(filter_parts, seg, i, profile)

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

    # Concatenate all segments
    if len(video_labels) == 1:
        final_video = video_labels[0]
        final_audio = audio_labels[0]
    else:
        concat_inputs = "".join(
            f"[{v}][{a}]"
            for v, a in zip(video_labels, audio_labels, strict=True)
        )
        n = len(video_labels)
        filter_parts.append(
            f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]"
        )
        final_video = "outv"
        final_audio = "outa"

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


def _build_region_scale(region: CanvasRegion) -> str:
    """Build FFmpeg scale filter for a canvas region respecting fit_mode.

    - stretch: Force exact output dimensions (may distort aspect ratio)
    - contain: Fit inside output dimensions, pad with black (no distort)
    - cover: Fill output dimensions completely, center-crop excess (no distort)

    Args:
        region: Canvas region with source and output dimensions + fit_mode.

    Returns:
        FFmpeg filter expression string (scale + optional pad/crop).
    """
    ow = region.output_width
    oh = region.output_height
    fit = region.fit_mode

    if fit == "stretch":
        return f"scale={ow}:{oh},setsar=1"

    if fit == "contain":
        # Scale to fit inside output, preserving aspect ratio.
        # Then pad to exact output size (centered, black padding).
        return (
            f"scale={ow}:{oh}:force_original_aspect_ratio=decrease,"
            f"pad={ow}:{oh}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
        )

    # cover (default): Scale to fill output, preserving aspect ratio.
    # Then center-crop to exact output size.
    return (
        f"scale={ow}:{oh}:force_original_aspect_ratio=increase,"
        f"crop={ow}:{oh},setsar=1"
    )


def _build_segment_canvas_chain(
    filters: list[str],
    seg: SegmentSpec,
    idx: int,
    profile: EncodingProfile,
    cw: int,
    ch: int,
    canvas: SegmentCanvasSpec,
) -> None:
    """Build filter chain for one segment with canvas regions.

    Creates an independent compositing pipeline: trim source,
    create background, split into N copies, crop+scale each
    region, overlay onto background.

    Args:
        filters: Accumulating filter parts (modified in place).
        seg: Segment specification.
        idx: Segment index for label naming.
        profile: Encoding profile.
        cw: Canvas width.
        ch: Canvas height.
        canvas: Canvas spec with regions for this segment.
    """
    start_s = seg.source_start_ms / 1000.0
    end_s = seg.source_end_ms / 1000.0
    bg_hex = canvas.background_color.lstrip("#")
    regions = sorted(canvas.regions, key=lambda r: r.z_index)
    n_regions = len(regions)
    seg_dur_s = (end_s - start_s) / seg.speed

    # 1. Trim source
    filters.append(
        f"[0:v]trim=start={start_s:.3f}:end={end_s:.3f},"
        f"setpts=PTS-STARTPTS[seg{idx}_src]"
    )

    # 2. Per-segment background canvas
    filters.append(
        f"color=c=0x{bg_hex}:s={cw}x{ch}:d={seg_dur_s + 1:.1f}"
        f":r={profile.fps},setsar=1[seg{idx}_bg]"
    )

    # 3. Split trimmed source into N copies
    if n_regions == 1:
        filters.append(f"[seg{idx}_src]null[seg{idx}_r0]")
    else:
        split_out = "".join(f"[seg{idx}_r{j}]" for j in range(n_regions))
        filters.append(f"[seg{idx}_src]split={n_regions}{split_out}")

    # 4. Crop and scale each region (respecting fit_mode)
    for j, region in enumerate(regions):
        scale_filter = _build_region_scale(region)
        filters.append(
            f"[seg{idx}_r{j}]"
            f"crop={region.source_width}:{region.source_height}"
            f":{region.source_x}:{region.source_y},"
            f"{scale_filter}"
            f"[seg{idx}_cr{j}]"
        )

    # 5. Overlay each region onto canvas
    current = f"seg{idx}_bg"
    for j, region in enumerate(regions):
        out = f"seg{idx}_ov{j}" if j < n_regions - 1 else f"v{idx}"
        filters.append(
            f"[{current}][seg{idx}_cr{j}]"
            f"overlay=x={region.output_x}:y={region.output_y}"
            f":shortest=1[{out}]"
        )
        current = out


def _build_segment_zoom_chain(
    filters: list[str],
    seg: SegmentSpec,
    idx: int,
    profile: EncodingProfile,
    cw: int,
    ch: int,
) -> None:
    """Build filter chain for one segment with animated zoom.

    Uses FFmpeg time-varying crop expressions to interpolate from
    the start crop region to the end crop region over the segment
    duration. After setpts=PTS-STARTPTS, t resets to 0 per segment.

    Args:
        filters: Accumulating filter parts (modified in place).
        seg: Segment specification with canvas.zoom set.
        idx: Segment index for label naming.
        profile: Encoding profile.
        cw: Canvas width.
        ch: Canvas height.
    """
    start_s = seg.source_start_ms / 1000.0
    end_s = seg.source_end_ms / 1000.0
    zoom = seg.canvas.zoom  # type: ignore[union-attr]
    seg_dur_s = (end_s - start_s) / seg.speed

    # Trim and reset PTS so t starts at 0
    filters.append(
        f"[0:v]trim=start={start_s:.3f}:end={end_s:.3f},"
        f"setpts=PTS-STARTPTS[seg{idx}_src]"
    )

    # Build easing progress expression
    d = f"{seg_dur_s:.3f}"
    p_raw = f"min(t/{d}\\,1)"

    if zoom.easing == "ease_in":
        progress = f"pow({p_raw}\\,2)"
    elif zoom.easing == "ease_out":
        progress = f"(2*{p_raw}-pow({p_raw}\\,2))"
    elif zoom.easing == "ease_in_out":
        progress = f"(3*pow({p_raw}\\,2)-2*pow({p_raw}\\,3))"
    else:  # linear
        progress = p_raw

    def lerp(start_val: int, end_val: int) -> str:
        delta = end_val - start_val
        if delta == 0:
            return str(start_val)
        return f"({start_val}+{delta}*{progress})"

    crop_w = lerp(zoom.start_w, zoom.end_w)
    crop_h = lerp(zoom.start_h, zoom.end_h)
    crop_x = lerp(zoom.start_x, zoom.end_x)
    crop_y = lerp(zoom.start_y, zoom.end_y)

    filters.append(
        f"[seg{idx}_src]"
        f"crop=w='{crop_w}':h='{crop_h}':x='{crop_x}':y='{crop_y}',"
        f"scale={cw}:{ch},setsar=1"
        f"[v{idx}]"
    )


def _build_segment_plain_chain(
    filters: list[str],
    seg: SegmentSpec,
    idx: int,
    profile: EncodingProfile,
) -> None:
    """Build filter chain for a segment with no canvas: trim + scale.

    Args:
        filters: Accumulating filter parts (modified in place).
        seg: Segment specification.
        idx: Segment index for label naming.
        profile: Encoding profile.
    """
    start_s = seg.source_start_ms / 1000.0
    end_s = seg.source_end_ms / 1000.0

    filters.append(
        f"[0:v]trim=start={start_s:.3f}:end={end_s:.3f},"
        f"setpts=PTS-STARTPTS,"
        f"scale={profile.width}:{profile.height},setsar=1"
        f"[v{idx}]"
    )


# ============================================================
# PREVIEW -- Single frame preview for compositing validation
# ============================================================
def build_preview_cmd(
    source_path: Path,
    output_path: Path,
    timestamp_ms: int,
    canvas_width: int,
    canvas_height: int,
    background_color: str,
    regions: list[CanvasRegion],
    fps: int = 30,
) -> list[str]:
    """Build FFmpeg command to render a single preview frame.

    Generates one composited JPEG showing exactly what the canvas
    layout looks like at a specific timestamp. Used for rapid
    iteration on region coordinates before committing to a full
    video render.

    Uses -ss before -i for fast keyframe seeking. No audio.
    No trim filters. Color source d=0.1 (just enough for 1 frame).

    Args:
        source_path: Path to the source video.
        output_path: Path for the output JPEG/PNG.
        timestamp_ms: Timestamp in the source to preview (ms).
        canvas_width: Output canvas width (e.g., 1080).
        canvas_height: Output canvas height (e.g., 1920).
        background_color: Canvas background hex color.
        regions: Canvas regions to composite (sorted by z_index).
        fps: Frame rate for the color source.

    Returns:
        FFmpeg command as a list of strings.

    Raises:
        ValueError: If no regions are provided.
    """
    if not regions:
        msg = "Preview requires at least one canvas region"
        raise ValueError(msg)

    seek_s = timestamp_ms / 1000.0
    bg_hex = background_color.lstrip("#")
    sorted_regions = sorted(regions, key=lambda r: r.z_index)
    n_regions = len(sorted_regions)

    filters: list[str] = []

    # Background canvas (short duration -- only need 1 frame)
    filters.append(
        f"color=c=0x{bg_hex}:s={canvas_width}x{canvas_height}"
        f":d=0.1:r={fps},setsar=1[bg]"
    )

    # Split source into N copies
    if n_regions == 1:
        filters.append("[0:v]null[r0]")
    else:
        split_out = "".join(f"[r{j}]" for j in range(n_regions))
        filters.append(f"[0:v]split={n_regions}{split_out}")

    # Crop and scale each region
    for j, region in enumerate(sorted_regions):
        scale_filter = _build_region_scale(region)
        filters.append(
            f"[r{j}]"
            f"crop={region.source_width}:{region.source_height}"
            f":{region.source_x}:{region.source_y},"
            f"{scale_filter}"
            f"[cr{j}]"
        )

    # Overlay each region onto canvas
    current = "bg"
    for j, region in enumerate(sorted_regions):
        out = f"ov{j}" if j < n_regions - 1 else "out"
        filters.append(
            f"[{current}][cr{j}]"
            f"overlay=x={region.output_x}:y={region.output_y}"
            f":shortest=1[{out}]"
        )
        current = out

    filter_complex = ";".join(filters)

    cmd: list[str] = [
        "ffmpeg", "-y",
        "-ss", f"{seek_s:.3f}",
        "-i", str(source_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-frames:v", "1",
        "-update", "1",
        "-q:v", "2",
        str(output_path),
    ]

    return cmd


def build_zoom_preview_cmd(
    source_path: Path,
    output_path: Path,
    timestamp_ms: int,
    canvas_width: int,
    canvas_height: int,
    crop_x: int,
    crop_y: int,
    crop_w: int,
    crop_h: int,
) -> list[str]:
    """Build FFmpeg command to preview a zoom/crop at a timestamp.

    Shows exactly what a static crop at the given coordinates
    looks like, scaled to the canvas dimensions.

    Args:
        source_path: Source video path.
        output_path: Output JPEG path.
        timestamp_ms: Source timestamp in ms.
        canvas_width: Output width.
        canvas_height: Output height.
        crop_x: Crop X origin in source.
        crop_y: Crop Y origin in source.
        crop_w: Crop width in source.
        crop_h: Crop height in source.

    Returns:
        FFmpeg command as argument list.
    """
    seek_s = timestamp_ms / 1000.0

    cmd: list[str] = [
        "ffmpeg", "-y",
        "-ss", f"{seek_s:.3f}",
        "-i", str(source_path),
        "-vf",
        f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},"
        f"scale={canvas_width}:{canvas_height},setsar=1",
        "-frames:v", "1",
        "-update", "1",
        "-q:v", "2",
        str(output_path),
    ]

    return cmd
