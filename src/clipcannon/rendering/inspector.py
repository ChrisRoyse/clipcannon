"""Render output inspection and quality verification.

Extracts frames from rendered output at key timestamps and
compares actual metadata against expected values from the
renders database table.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class InspectionResult:
    """Result of render output inspection."""
    render_id: str
    output_path: str
    frames: list[dict[str, object]] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    checks: list[dict[str, object]] = field(default_factory=list)
    all_passed: bool = True
    elapsed_ms: int = 0


async def extract_frames(
    video_path: Path,
    timestamps_ms: list[int],
    output_dir: Path,
) -> list[dict[str, object]]:
    """Extract frames from video at specified timestamps.

    Returns list of dicts with: timestamp_ms, frame_path, base64_image.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, object]] = []

    for ts_ms in timestamps_ms:
        ts_s = ts_ms / 1000.0
        frame_path = output_dir / f"inspect_{ts_ms}ms.jpg"

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{ts_s:.3f}",
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(frame_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        b64 = ""
        if frame_path.exists():
            b64 = base64.b64encode(
                frame_path.read_bytes()
            ).decode("ascii")

        frames.append({
            "timestamp_ms": ts_ms,
            "frame_path": str(frame_path),
            "_image": b64,
        })

    return frames


async def probe_video(video_path: Path) -> dict[str, object]:
    """Get video metadata via ffprobe.

    Returns dict with: duration_ms, width, height, codec, bitrate_kbps,
    audio_codec, file_size_bytes.
    """
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()

    try:
        data = json.loads(stdout.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"error": "ffprobe output parse failed"}

    # Extract video stream info
    video_stream = None
    audio_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and video_stream is None:
            video_stream = stream
        elif stream.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = stream

    fmt = data.get("format", {})
    duration_s = float(fmt.get("duration", 0))

    result: dict[str, object] = {
        "duration_ms": int(duration_s * 1000),
        "file_size_bytes": int(fmt.get("size", 0)),
        "bitrate_kbps": int(int(fmt.get("bit_rate", 0)) / 1000),
    }

    if video_stream:
        result["width"] = int(video_stream.get("width", 0))
        result["height"] = int(video_stream.get("height", 0))
        result["codec"] = str(video_stream.get("codec_name", "unknown"))
        result["fps"] = _parse_fps(
            str(video_stream.get("r_frame_rate", "0/1"))
        )

    if audio_stream:
        result["audio_codec"] = str(
            audio_stream.get("codec_name", "unknown")
        )
        result["audio_sample_rate"] = int(
            audio_stream.get("sample_rate", 0)
        )

    return result


def _parse_fps(fps_str: str) -> float:
    """Parse FFmpeg rational fps like '30/1' or '30000/1001'."""
    parts = fps_str.split("/")
    if len(parts) == 2:
        try:
            return round(int(parts[0]) / int(parts[1]), 2)
        except (ValueError, ZeroDivisionError):
            pass
    try:
        return float(fps_str)
    except ValueError:
        return 0.0


async def inspect_render(
    render_output_path: Path,
    expected_duration_ms: int | None = None,
    expected_width: int | None = None,
    expected_height: int | None = None,
    expected_codec: str | None = None,
) -> InspectionResult:
    """Inspect a rendered video output.

    Extracts frames at 5 points (start, 25%, 50%, 75%, end),
    probes metadata, and runs quality checks.

    Args:
        render_output_path: Path to rendered video file.
        expected_duration_ms: Expected duration for verification.
        expected_width: Expected width for verification.
        expected_height: Expected height for verification.
        expected_codec: Expected codec for verification.

    Returns:
        InspectionResult with frames, metadata, and check results.
    """
    t0 = time.monotonic()

    if not render_output_path.exists():
        raise FileNotFoundError(
            f"Render output not found: {render_output_path}"
        )

    # Probe metadata
    metadata = await probe_video(render_output_path)
    actual_duration = int(metadata.get("duration_ms", 0))

    # Calculate frame extraction timestamps
    if actual_duration > 0:
        timestamps = [
            0,
            actual_duration // 4,
            actual_duration // 2,
            3 * actual_duration // 4,
            max(0, actual_duration - 100),
        ]
    else:
        timestamps = [0]

    # Extract frames
    inspect_dir = render_output_path.parent / "inspect"
    frames = await extract_frames(render_output_path, timestamps, inspect_dir)

    # Run quality checks
    checks: list[dict[str, object]] = []
    all_passed = True

    # Check: file exists and has content
    fsize = int(metadata.get("file_size_bytes", 0))
    passed = fsize > 1000
    checks.append({
        "check": "file_size_above_1kb", "passed": passed, "actual": fsize,
    })
    if not passed:
        all_passed = False

    # Check: duration matches expected
    if expected_duration_ms is not None:
        tolerance_ms = max(500, expected_duration_ms * 0.05)  # 5% or 500ms
        diff = abs(actual_duration - expected_duration_ms)
        passed = diff <= tolerance_ms
        checks.append({
            "check": "duration_match",
            "passed": passed,
            "expected_ms": expected_duration_ms,
            "actual_ms": actual_duration,
            "diff_ms": diff,
        })
        if not passed:
            all_passed = False

    # Check: resolution matches
    if expected_width is not None and expected_height is not None:
        actual_w = int(metadata.get("width", 0))
        actual_h = int(metadata.get("height", 0))
        passed = actual_w == expected_width and actual_h == expected_height
        checks.append({
            "check": "resolution_match",
            "passed": passed,
            "expected": f"{expected_width}x{expected_height}",
            "actual": f"{actual_w}x{actual_h}",
        })
        if not passed:
            all_passed = False

    # Check: codec matches
    if expected_codec is not None:
        actual_codec = str(metadata.get("codec", ""))
        # h264 = libx264, h265 = libx265
        codec_aliases = {
            "h264": "h264", "libx264": "h264",
            "h265": "hevc", "libx265": "hevc",
        }
        norm_expected = codec_aliases.get(expected_codec, expected_codec)
        norm_actual = codec_aliases.get(actual_codec, actual_codec)
        passed = norm_expected == norm_actual
        checks.append({
            "check": "codec_match",
            "passed": passed,
            "expected": expected_codec,
            "actual": actual_codec,
        })
        if not passed:
            all_passed = False

    # Check: has audio
    has_audio = "audio_codec" in metadata
    checks.append({"check": "has_audio", "passed": has_audio})

    elapsed = int((time.monotonic() - t0) * 1000)

    return InspectionResult(
        render_id="",
        output_path=str(render_output_path),
        frames=frames,
        metadata=metadata,
        checks=checks,
        all_passed=all_passed,
        elapsed_ms=elapsed,
    )
