"""Split-screen and picture-in-picture FFmpeg command builders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .filters import _build_concat_filters, _escape_subtitle_path

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.editing.edl import SegmentSpec
    from clipcannon.editing.smart_crop import PipLayout, SplitScreenLayout
    from clipcannon.rendering.profiles import EncodingProfile


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
