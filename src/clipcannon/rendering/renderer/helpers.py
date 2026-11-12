"""Render helpers: ffprobe probes, ASS scaling, SFX offsets, segment cache table, result."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from clipcannon.exceptions import PipelineError

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================
# CAPTION SYNC HELPERS
# ============================================================
def _probe_duration_ms(video_path: Path) -> int:
    """Probe the actual duration of a video file via ffprobe.

    Returns the container-reported duration in milliseconds.
    Used to detect concat demuxer timestamp drift.

    Args:
        video_path: Path to the video file to probe.

    Returns:
        Duration in milliseconds.

    Raises:
        PipelineError: If ffprobe fails or returns unexpected output.
    """
    import json
    import subprocess

    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise PipelineError(
            f"ffprobe failed (exit {result.returncode}) for {video_path}",
            stage_name="rendering",
            operation="probe_duration",
            details={"stderr": result.stderr[:500]},
        )

    try:
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        raise PipelineError(
            f"ffprobe returned unexpected output for {video_path}: {exc}",
            stage_name="rendering",
            operation="probe_duration",
            details={"stdout": result.stdout[:500]},
        ) from exc

    return round(duration * 1000)


def _probe_size(video_path: Path) -> tuple[int, int]:
    """(width, height) of the first video stream, via ffprobe."""
    import json
    import subprocess

    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "json", str(video_path)],
        capture_output=True, text=True, timeout=30,
    )
    try:
        s = json.loads(result.stdout)["streams"][0]
        return int(s["width"]), int(s["height"])
    except (json.JSONDecodeError, KeyError, IndexError, ValueError) as exc:
        raise PipelineError(
            f"ffprobe could not read the frame size of {video_path}: {exc}",
            stage_name="rendering", operation="probe_size",
            details={"stderr": result.stderr[:500]},
        ) from exc


def _scale_ass_file(
    ass_path: Path,
    scale: float,
    output_path: Path,
) -> Path:
    """Scale all timestamps in an ASS file by a factor.

    Adjusts Dialogue start/end times (H:MM:SS.cc format) and
    karaoke tag durations (\\kf centiseconds) proportionally.
    Used to align pre-computed caption timestamps with the actual
    rendered output duration when concat demuxer drift is detected.

    Args:
        ass_path: Path to the original ASS file.
        scale: Multiplicative factor (e.g., 1.018 = 1.8% stretch).
        output_path: Where to write the scaled ASS file.

    Returns:
        Path to the scaled ASS file.
    """
    import re

    time_re = re.compile(r"(\d+):(\d{2}):(\d{2})\.(\d{2})")
    kf_re = re.compile(r"\\kf(\d+)")

    def scale_time(match: re.Match[str]) -> str:
        h = int(match.group(1))
        m = int(match.group(2))
        s = int(match.group(3))
        cs = int(match.group(4))
        total_cs = h * 360000 + m * 6000 + s * 100 + cs
        scaled_cs = round(total_cs * scale)
        nh = scaled_cs // 360000
        nm = (scaled_cs % 360000) // 6000
        ns = (scaled_cs % 6000) // 100
        ncs = scaled_cs % 100
        return f"{nh}:{nm:02d}:{ns:02d}.{ncs:02d}"

    def scale_kf(match: re.Match[str]) -> str:
        cs = int(match.group(1))
        return f"\\kf{max(1, round(cs * scale))}"

    lines = ass_path.read_text().splitlines()
    scaled_lines: list[str] = []
    for line in lines:
        if line.startswith("Dialogue:"):
            line = time_re.sub(scale_time, line)
            line = kf_re.sub(scale_kf, line)
        scaled_lines.append(line)

    output_path.write_text("\n".join(scaled_lines) + "\n")
    logger.info(
        "Scaled ASS timestamps by %.5f: %s -> %s",
        scale, ass_path.name, output_path.name,
    )
    return output_path


# ============================================================
# AUDIO ASSET HELPERS
# ============================================================
def _parse_sfx_offset_ms(raw_params: object) -> int:
    """Extract start_ms offset from an SFX asset's generation_params.

    Expects JSON shaped like ``{"params": {"start_ms": 1200}}``.
    Returns 0 when the value is missing, malformed, or not parseable.

    Args:
        raw_params: The generation_params column value (str or dict).

    Returns:
        Offset in milliseconds, defaulting to 0.
    """
    if not raw_params:
        return 0

    import json

    try:
        parsed = json.loads(raw_params) if isinstance(
            raw_params, str
        ) else raw_params
        return int(parsed.get("params", {}).get("start_ms", 0))
    except (ValueError, TypeError, AttributeError):
        return 0


# ============================================================
# SEGMENT RENDER CACHE HELPERS
# ============================================================
_SEGMENT_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS segment_cache (
    cache_hash TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    segment_spec_json TEXT NOT NULL,
    file_size_bytes INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES project(project_id)
);
CREATE INDEX IF NOT EXISTS idx_segment_cache_project
    ON segment_cache(project_id);
"""


def ensure_segment_cache_table(conn: sqlite3.Connection) -> None:
    """Ensure the segment_cache table exists, creating it if needed.

    Handles migration for existing databases created before the
    segment render cache was added.

    Args:
        conn: SQLite connection.
    """
    import sqlite3 as _sqlite3

    try:
        conn.execute("SELECT 1 FROM segment_cache LIMIT 1")
    except _sqlite3.OperationalError:
        conn.executescript(_SEGMENT_CACHE_DDL)
        logger.info("Created segment_cache table (migration).")


@dataclass
class RenderResult:
    """Result of a render operation.

    Attributes:
        render_id: Unique render identifier.
        success: Whether the render completed successfully.
        output_path: Path to the rendered output file.
        thumbnail_path: Path to the generated thumbnail.
        output_sha256: SHA-256 hash of the output file.
        file_size_bytes: Size of the output file in bytes.
        duration_ms: Duration of the rendered clip in milliseconds.
        render_duration_ms: Wall-clock time for the render in ms.
        error_message: Error description if render failed.
        provenance_record_id: ID of the provenance record created.
    """

    render_id: str = ""
    success: bool = False
    output_path: Path | None = None
    thumbnail_path: Path | None = None
    output_sha256: str | None = None
    file_size_bytes: int = 0
    duration_ms: int = 0
    render_duration_ms: int = 0
    error_message: str | None = None
    provenance_record_id: str | None = None
