"""FFmpeg command building for ClipCannon rendering.

Constructs FFmpeg commands for single-segment and multi-segment EDLs
with support for transitions, crop, scale, speed, subtitle filters,
split-screen layouts, and picture-in-picture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.editing.edl import SegmentSpec
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

    Returns:
        FFmpeg command as a list of strings.
    """
    # Split-screen layout takes priority over single crop
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

    # Create separator bar (if any)
    if sep > 0:
        hex_color = layout.separator_color.lstrip("#")
        filters.append(
            f"color=c=0x{hex_color}:s={ow}x{sep}:d=99999,setsar=1[bar]"
        )
        # Stack based on speaker position
        if layout.speaker_position == "top":
            filters.append(
                "[speaker][bar][screen]vstack=inputs=3[stacked]"
            )
        else:
            filters.append(
                "[screen][bar][speaker]vstack=inputs=3[stacked]"
            )
    else:
        if layout.speaker_position == "top":
            filters.append("[speaker][screen]vstack=inputs=2[stacked]")
        else:
            filters.append("[screen][speaker]vstack=inputs=2[stacked]")

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

        # Stack
        if sep > 0:
            filter_parts.append(
                f"color=c=0x{layout.separator_color.lstrip('#')}"
                f":s={ow}x{sep}:d=99999,setsar=1[bar{i}]"
            )
            if layout.speaker_position == "top":
                filter_parts.append(
                    f"[spk{i}][bar{i}][scn{i}]vstack=inputs=3[v{i}]"
                )
            else:
                filter_parts.append(
                    f"[scn{i}][bar{i}][spk{i}]vstack=inputs=3[v{i}]"
                )
        else:
            if layout.speaker_position == "top":
                filter_parts.append(
                    f"[spk{i}][scn{i}]vstack=inputs=2[v{i}]"
                )
            else:
                filter_parts.append(
                    f"[scn{i}][spk{i}]vstack=inputs=2[v{i}]"
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
