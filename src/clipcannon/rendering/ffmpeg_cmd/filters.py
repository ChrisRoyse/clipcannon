"""Shared FFmpeg filter helpers: escaping, delogo, grading, concat/xfade, encoding args."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.editing.edl import SegmentSpec
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


def _build_delogo_chain(removals: list | None) -> str:
    """Build a delogo filter chain string from removal specs.

    Args:
        removals: List of RemovalSpec objects, or None.

    Returns:
        Comma-prefixed delogo chain string, or empty string if no removals.
    """
    if not removals:
        return ""
    return "".join(
        f",delogo=x={rem.x}:y={rem.y}:w={rem.width}:h={rem.height}:band=10"
        for rem in removals
    )


def _apply_color_grading(
    filters: list[str],
    input_label: str,
    output_label: str,
    color: object,
) -> str:
    """Apply color grading filters to a labeled stream.

    If color grading produces filters, appends them and returns the
    new label. Otherwise returns the input label unchanged.

    Args:
        filters: Accumulating filter parts (modified in place).
        input_label: Current stream label to apply color to.
        output_label: Label for the color-graded output stream.
        color: ColorSpec with brightness, contrast, etc.

    Returns:
        The effective output label (may be input_label if no-op).
    """
    from clipcannon.editing.motion import build_color_filters

    color_filter = build_color_filters(
        brightness=color.brightness,
        contrast=color.contrast,
        saturation=color.saturation,
        gamma=color.gamma,
        hue_shift=color.hue_shift,
    )
    if color_filter:
        filters.append(f"[{input_label}]{color_filter}[{output_label}]")
        return output_label
    return input_label


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


def _segment_pts(seg: SegmentSpec) -> str:
    """setpts expression that restarts the segment at 0 and applies its speed.

    The audio side applies atempo=speed, so the video must be retimed by the
    same factor or the two drift apart (and the segment's duration is wrong).
    """
    if seg.speed != 1.0:
        return f"(PTS-STARTPTS)/{seg.speed}"
    return "PTS-STARTPTS"


def _speed_resample(seg: SegmentSpec, fps: int) -> str:
    """Filter suffix that puts a retimed segment back on the output frame grid.

    After setpts/speed the frames carry timestamps spaced 1/(fps*speed); left
    to the encoder's rate conversion, a 4 s span at 2x came out 62 frames
    (2.067 s) against 2.000 s of audio (#68, measured). Resampling to ``fps``
    and trimming to the exact retimed duration gives span/speed seconds.
    """
    if seg.speed == 1.0:
        return ""
    dur = (seg.source_end_ms - seg.source_start_ms) / 1000.0 / seg.speed
    return f",fps={fps},trim=duration={dur:.6f}"
