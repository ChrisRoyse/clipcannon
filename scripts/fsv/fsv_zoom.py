"""FSV (#69): an animated zoom changes the crop window's size over time, not just its position.

Source of truth: the rendered MP4 bytes, decoded to raw gray pixels; the
measured quantity is the marker's bounding box in output frames.

Corpus: one synthetic 5 s 1920x1080 source with known geometry: a static white
100x100 box centred at (960, 540) on black. With a centred zoom window of width
w(t), the box must appear 100*1920/w(t) px wide in a 1920x1080 output, so the
box size alone measures the window size at that instant. Nothing smaller tests
size animation; real footage has no known geometry to compare against.

    python scripts/fsv/fsv_zoom.py
"""

from __future__ import annotations

import subprocess
import sys

import numpy as np
from kit import Run, ffprobe, require_tools, stream

from clipcannon.editing.edl import SegmentCanvasSpec, SegmentSpec, ZoomSpec
from clipcannon.rendering.ffmpeg_cmd import _build_per_segment_canvas_cmd
from clipcannon.rendering.profiles import get_profile

W, H, BOX, DUR_MS = 1920, 1080, 100, 4000
ENC = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-c:a", "aac"]
ZOOM = dict(start_x=0, start_y=0, start_w=1920, start_h=1080,
            end_x=480, end_y=270, end_w=960, end_h=540)


def make_source(run: Run) -> object:
    src = run.path("source.mp4")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=black:size={W}x{H}:rate=30:duration=5",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=5", "-vf",
         f"drawbox=x={960 - BOX // 2}:y={540 - BOX // 2}:w={BOX}:h={BOX}:color=white:t=fill",
         "-shortest", "-pix_fmt", "yuv420p", *ENC, str(src)], check=True)
    return src


def box_size(path: object, t: float, w: int, h: int) -> tuple[float, float] | None:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    img = np.frombuffer(raw, np.uint8).reshape(h, w) > 128
    ys, xs = np.nonzero(img)
    if xs.size == 0:
        return None
    return float(xs.max() - xs.min() + 1), float(ys.max() - ys.min() + 1)


def expected(t: float, easing: str) -> float:
    p = min(t / (DUR_MS / 1000), 1.0)
    p = {"linear": p, "ease_in_out": 3 * p * p - 2 * p ** 3}[easing]
    win_w = ZOOM["start_w"] + (ZOOM["end_w"] - ZOOM["start_w"]) * p
    return BOX * W / win_w


def render(run: Run, src: object, easing: str) -> object:
    seg = SegmentSpec(segment_id=1, source_start_ms=0, source_end_ms=DUR_MS, output_start_ms=0,
                      canvas=SegmentCanvasSpec(zoom=ZoomSpec(**ZOOM, easing=easing)))
    out = run.path(f"zoom_{easing}.mp4")
    cmd = _build_per_segment_canvas_cmd(src, out, [seg], get_profile("youtube_standard"),
                                        None, None, ENC)
    run.path(f"zoom_{easing}.cmd.txt").write_text(" ".join(map(str, cmd)))
    subprocess.run(cmd, capture_output=True, check=True)
    return out


def main() -> int:
    require_tools("ffmpeg", "ffprobe")
    run = Run("zoom-size", issue=69, source_of_truth="rendered MP4 bytes (decoded pixels)",
              claim="an animated zoom interpolates the crop window size as well as its "
                    "position, following the requested easing",
              corpus="synthetic 5 s 1920x1080 source, static 100 px box at centre",
              why_minimal="box size in the output measures window size directly; one "
                          "source and two easings cover the size path")
    src = make_source(run)
    prof = get_profile("youtube_standard")
    assert (prof.width, prof.height) == (W, H)
    for easing in ("linear", "ease_in_out"):
        out = render(run, src, easing)
        times = (0.05, 1.0, 2.0, 3.0, 3.95)
        got = [box_size(out, t, W, H) for t in times]
        want = [expected(t, easing) for t in times]
        ok = all(g is not None and abs(g[0] - e) <= 4 and abs(g[1] - e) <= 4
                 for g, e in zip(got, want, strict=True))
        run.check(f"zoom_{easing}_box_size_follows_window", ok,
                  before={"box_px": BOX, "window": ZOOM},
                  action=f"render 4 s zoom ({easing}), decode frames at {list(times)}",
                  after={"measured_wh": got, "expected_w": [round(e, 1) for e in want],
                         "wrong_if_static_w": BOX * W / ZOOM["start_w"]})
        if easing == "linear":
            info = ffprobe(out)
            vs = stream(info, "video")
            run.check("zoom_output_geometry_and_duration",
                      (vs["width"], vs["height"]) == (W, H)
                      and abs(float(vs["duration"]) - DUR_MS / 1000) < 0.1,
                      after={"w": vs["width"], "h": vs["height"], "duration": vs["duration"]})
            # Centre stays centred: the zoom target is the frame centre.
            raw = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", "3.0", "-i", str(out), "-frames:v", "1",
                 "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
            ys, xs = np.nonzero(np.frombuffer(raw, np.uint8).reshape(H, W) > 128)
            run.check("zoom_keeps_target_centred",
                      abs(xs.mean() - W / 2) < 3 and abs(ys.mean() - H / 2) < 3,
                      after={"centroid": [float(xs.mean()), float(ys.mean())]})
    run.refuses("zoom_window_zero_width_refused",
                lambda: ZoomSpec(**{**ZOOM, "end_w": 0}), "ValidationError")
    return run.finish(limitations=["libx264 encode; crop/scale math is encoder-independent",
                                   "aspect-preserving windows only (the common zoom case)"])


if __name__ == "__main__":
    sys.exit(main())
