"""FSV: per-segment render paths retime video with the audio, and tracked framing
puts the crop window where its keyframes say.

Source of truth: the rendered MP4 bytes, read back with ffprobe (stream
durations, codec) and by decoding frames to raw pixels (where the marker is).

Corpus: one synthetic 6 s 1920x1080 source with known truth: a white 100 px box
on black whose left edge is x(t) = 200 + 200 t, plus a sine tone. Position encodes
source time, so a decoded output frame says which source instant it shows. Nothing
smaller exercises timing, content and crop position at once; real footage adds no
proof for a geometry claim (the speaker-tracking probe covers real footage).

    python scripts/fsv/fsv_render_paths.py [--out DIR]
"""

from __future__ import annotations

import subprocess
import sys

import numpy as np
from kit import Run, ffprobe, require_tools, stream

from clipcannon.editing.edl import (
    CanvasRegion,
    SegmentCanvasSpec,
    SegmentSpec,
    TrackedFraming,
    TrackedPiece,
    ZoomSpec,
)
from clipcannon.rendering.ffmpeg_cmd import _build_per_segment_canvas_cmd
from clipcannon.rendering.inspector import normalize_codec_name
from clipcannon.rendering.profiles import get_profile

SRC_W, SRC_H, BOX = 1920, 1080, 100
START_MS, END_MS = 500, 4500
ENC = ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac"]


def box_left(t: float) -> float:
    return 200 + 200 * t


def make_source(run: Run) -> object:
    src = run.path("source.mp4")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
         f"color=black:size={SRC_W}x{SRC_H}:rate=30:duration=6", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=6", "-f", "lavfi", "-i",
         f"color=white:size={BOX}x{BOX}:rate=30:duration=6", "-filter_complex",
         "[0:v][2:v]overlay=x='200+200*t':y=490:eval=frame[v]", "-map", "[v]",
         "-map", "1:a", "-shortest", "-pix_fmt", "yuv420p", *ENC, str(src)], check=True)
    return src


def marker_x(path: object, t: float, w: int, h: int) -> float | None:
    """Column centroid of bright pixels in the output frame at time t."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    img = np.frombuffer(raw, np.uint8).reshape(h, w)
    cols = np.nonzero(img > 128)[1]
    return float(cols.mean()) if cols.size else None


def canvas(kind: str) -> SegmentCanvasSpec | None:
    if kind == "regions":
        return SegmentCanvasSpec(regions=[CanvasRegion(
            region_id="main", source_x=656, source_y=0, source_width=608, source_height=1080,
            output_x=0, output_y=0, output_width=1080, output_height=1920)])
    if kind == "zoom":
        return SegmentCanvasSpec(zoom=ZoomSpec(start_x=656, start_y=0, start_w=608,
                                               start_h=1080, end_x=756, end_y=100,
                                               end_w=456, end_h=810))
    if kind == "track":  # window centred on the moving box every 250 ms
        keys = [(ms, int(box_left(ms / 1000) + BOX / 2 - 304), 0)
                for ms in range(START_MS, END_MS + 1, 250)]
        return SegmentCanvasSpec(track=TrackedFraming(pieces=[TrackedPiece(
            start_ms=START_MS, end_ms=END_MS, width=608, height=1080, keyframes=keys)]))
    return None


def render(run: Run, src: object, kind: str, speed: float) -> object:
    seg = SegmentSpec(segment_id=1, source_start_ms=START_MS, source_end_ms=END_MS,
                      output_start_ms=0, speed=speed, canvas=canvas(kind))
    out = run.path(f"{kind}_x{speed}.mp4")
    cmd = _build_per_segment_canvas_cmd(src, out, [seg], get_profile("youtube_shorts"),
                                        None, None, ENC)
    run.path(f"{kind}_x{speed}.cmd.txt").write_text(" ".join(map(str, cmd)))
    subprocess.run(cmd, capture_output=True, check=True)
    return out


def main() -> int:
    require_tools("ffmpeg", "ffprobe")
    run = Run("render-paths", issue=67, source_of_truth="rendered MP4 bytes",
              claim="every per-segment render path retimes video by segment speed in step "
                    "with audio; tracked framing follows its keyframes",
              corpus="synthetic 6 s 1920x1080 moving-box source with sine audio",
              why_minimal="one source whose pixels encode source time proves duration, "
                          "content timing and crop position; more footage adds no proof")
    src = make_source(run)
    profile = get_profile("youtube_shorts")
    pw, ph = profile.width, profile.height
    span_s = (END_MS - START_MS) / 1000

    for kind in ("plain", "regions", "zoom", "track"):
        out = render(run, src, kind, 2.0)
        info = ffprobe(out)
        v, a = float(stream(info, "video")["duration"]), float(stream(info, "audio")["duration"])
        run.check(f"speed2_{kind}_durations", abs(v - span_s / 2) < 0.1 and abs(a - span_s / 2) < 0.1,
                  before={"source_span_s": span_s, "speed": 2.0},
                  after={"video_s": v, "audio_s": a, "expected_s": span_s / 2})

    # Content timing: output t=1.0 at 2x shows source t = 0.5 + 2.0 = 2.5 s.
    plain = run.path("plain_x2.0.mp4")
    got = marker_x(plain, 1.0, pw, ph)
    want = (box_left(2.5) + BOX / 2) * pw / SRC_W
    run.check("speed2_plain_shows_right_source_instant", got is not None and abs(got - want) < 12,
              action="decode output frame at 1.0 s", after={"marker_x": got, "expected_x": want,
              "wrong_if_unretimed_x": (box_left(1.5) + BOX / 2) * pw / SRC_W})

    track = run.path("track_x2.0.mp4")
    xs = [marker_x(track, t, pw, ph) for t in (0.2, 0.9, 1.6)]
    run.check("tracked_crop_keeps_marker_centred",
              all(x is not None and abs(x - pw / 2) < 30 for x in xs),
              after={"marker_x_at_0.2_0.9_1.6": xs, "expected_x": pw / 2})

    out1 = render(run, src, "plain", 1.0)
    v1 = float(stream(ffprobe(out1), "video")["duration"])
    run.check("speed1_control_keeps_duration", abs(v1 - span_s) < 0.1,
              after={"video_s": v1, "expected_s": span_s})

    run.refuses("speed_above_4_refused", lambda: SegmentSpec(
        segment_id=1, source_start_ms=0, source_end_ms=1000, output_start_ms=0, speed=5.0),
        "ValidationError")
    run.refuses("degenerate_track_window_refused", lambda: TrackedPiece(
        start_ms=0, end_ms=1000, width=1, height=1080, keyframes=[(0, 0, 0)]), "ValidationError")

    codec = stream(ffprobe(plain), "video")["codec_name"]
    run.check("inspector_codec_names", normalize_codec_name("h264_nvenc") == codec == "h264"
              and normalize_codec_name("hevc_nvenc") == "hevc"
              and normalize_codec_name("hevc_nvenc") != codec,
              after={"file_codec": codec, "h264_nvenc": normalize_codec_name("h264_nvenc"),
                     "hevc_nvenc": normalize_codec_name("hevc_nvenc")})
    return run.finish(limitations=[
        "libx264 encode, not NVENC: encoder choice does not affect retiming or crop math",
        "zoom path: duration only; its crop size is evaluated once by FFmpeg (open issue)"])


if __name__ == "__main__":
    sys.exit(main())
