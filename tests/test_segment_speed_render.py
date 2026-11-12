"""Segment speed must apply on every per-segment render path.

The audio chain always applies atempo=speed. The canvas, zoom and plain video
chains used to skip the matching setpts, so a 2x segment came out with 2 s of
audio and 4 s of video. Each case renders a real file and checks both streams.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from clipcannon.editing.edl import (
    CanvasRegion,
    SegmentCanvasSpec,
    SegmentSpec,
    TrackedFraming,
    TrackedPiece,
    ZoomSpec,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg not installed",
)

SPEED = 2.0
SRC_START, SRC_END = 500, 4500  # 4 s of source -> 2 s of output at 2x


def _canvas(kind: str) -> SegmentCanvasSpec | None:
    if kind == "plain":
        return None
    if kind == "regions":
        return SegmentCanvasSpec(regions=[CanvasRegion(
            region_id="main", source_x=656, source_y=0, source_width=608,
            source_height=1080, output_x=0, output_y=0, output_width=1080,
            output_height=1920,
        )])
    if kind == "zoom":
        return SegmentCanvasSpec(zoom=ZoomSpec(
            start_x=656, start_y=0, start_w=608, start_h=1080,
            end_x=756, end_y=100, end_w=456, end_h=810,
        ))
    return SegmentCanvasSpec(track=TrackedFraming(pieces=[TrackedPiece(
        start_ms=SRC_START, end_ms=SRC_END, width=608, height=1080,
        keyframes=[(SRC_START, 0, 0), (SRC_END, 1300, 0)],
    )]))


def _stream_durations(path: Path) -> dict[str, float]:
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout)
    return {s["codec_type"]: float(s["duration"]) for s in probe["streams"]}


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    src = tmp_path_factory.mktemp("speed") / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
         "testsrc2=size=1920x1080:rate=30:duration=6", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=6", "-shortest", "-c:v", "libx264",
         "-preset", "ultrafast", "-c:a", "aac", str(src)],
        check=True,
    )
    return src


@pytest.mark.parametrize("kind", ["plain", "regions", "zoom", "track"])
def test_speed_applies_to_video_and_audio(kind: str, source: Path, tmp_path: Path) -> None:
    from clipcannon.rendering.ffmpeg_cmd import _build_per_segment_canvas_cmd
    from clipcannon.rendering.profiles import get_profile

    seg = SegmentSpec(segment_id=1, source_start_ms=SRC_START, source_end_ms=SRC_END,
                      output_start_ms=0, speed=SPEED, canvas=_canvas(kind))
    profile = get_profile("youtube_shorts")
    out = tmp_path / f"{kind}.mp4"
    cmd = _build_per_segment_canvas_cmd(
        source, out, [seg], profile, None, None,
        ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac"],
    )
    run = subprocess.run(cmd, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[-2000:]

    expected = (SRC_END - SRC_START) / 1000.0 / SPEED
    durations = _stream_durations(out)
    assert durations["video"] == pytest.approx(expected, abs=0.1)
    assert durations["audio"] == pytest.approx(expected, abs=0.1)
