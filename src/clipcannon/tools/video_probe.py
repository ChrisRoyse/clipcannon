"""Video probing and metadata extraction for ClipCannon.

Provides FFprobe-based metadata extraction and VFR detection
for use by the project management tools.
"""

from __future__ import annotations

import json
import logging
import subprocess

from clipcannon.exceptions import ClipCannonError

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS: set[str] = {"mp4", "mov", "mkv", "webm", "avi", "ts", "mts"}


def run_ffprobe(video_path: str) -> dict[str, object]:
    """Run ffprobe and parse JSON output for video metadata.

    Args:
        video_path: Path to the video file.

    Returns:
        Parsed ffprobe JSON output.

    Raises:
        ClipCannonError: If ffprobe fails.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            raise ClipCannonError(
                f"ffprobe failed with code {result.returncode}: {result.stderr[:200]}",
            )
        return json.loads(result.stdout)
    except FileNotFoundError:
        raise ClipCannonError("ffprobe not found. Install ffmpeg to use ClipCannon.")
    except json.JSONDecodeError as exc:
        raise ClipCannonError(f"Failed to parse ffprobe output: {exc}")
    except subprocess.TimeoutExpired:
        raise ClipCannonError("ffprobe timed out after 60 seconds")


def extract_video_metadata(probe_data: dict[str, object]) -> dict[str, object]:
    """Extract structured metadata from ffprobe output.

    Args:
        probe_data: Parsed ffprobe JSON.

    Returns:
        Dictionary with duration_ms, resolution, fps, codec, etc.

    Raises:
        ClipCannonError: If no video stream is found.
    """
    streams = probe_data.get("streams", [])
    fmt = probe_data.get("format", {})

    video_stream: dict[str, object] | None = None
    audio_stream: dict[str, object] | None = None

    if isinstance(streams, list):
        for stream in streams:
            if isinstance(stream, dict):
                codec_type = stream.get("codec_type", "")
                if codec_type == "video" and video_stream is None:
                    video_stream = stream
                elif codec_type == "audio" and audio_stream is None:
                    audio_stream = stream

    if video_stream is None:
        raise ClipCannonError("No video stream found in file")

    # Duration
    duration_str = str(fmt.get("duration", video_stream.get("duration", "0")))
    duration_s = float(duration_str) if duration_str else 0.0
    duration_ms = int(duration_s * 1000)

    # Resolution
    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))
    resolution = f"{width}x{height}"

    # FPS
    fps_str = str(video_stream.get("r_frame_rate", "30/1"))
    if "/" in fps_str:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 30.0
    else:
        fps = float(fps_str) if fps_str else 30.0

    # Codec
    codec = str(video_stream.get("codec_name", "unknown"))

    # Audio info
    audio_codec = str(audio_stream.get("codec_name", "")) if audio_stream else None
    audio_channels = int(audio_stream.get("channels", 0)) if audio_stream else None

    # File size
    size_str = str(fmt.get("size", "0"))
    file_size_bytes = int(size_str) if size_str.isdigit() else 0

    return {
        "duration_ms": duration_ms,
        "resolution": resolution,
        "width": width,
        "height": height,
        "fps": round(fps, 3),
        "codec": codec,
        "audio_codec": audio_codec,
        "audio_channels": audio_channels,
        "file_size_bytes": file_size_bytes,
    }


def detect_vfr(video_path: str) -> bool:
    """Detect variable frame rate using ffmpeg vfrdet filter.

    Args:
        video_path: Path to the video file.

    Returns:
        True if VFR is detected.
    """
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-i", video_path,
                "-vf", "vfrdet",
                "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        stderr = result.stderr
        for line in stderr.splitlines():
            if "VFR:" in line:
                parts = line.split("VFR:")
                if len(parts) > 1:
                    ratio_str = parts[1].strip().split()[0]
                    try:
                        ratio = float(ratio_str)
                        return ratio > 0.0
                    except ValueError:
                        pass
        return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
