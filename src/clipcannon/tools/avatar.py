"""Avatar/lip-sync MCP tool dispatch for ClipCannon.

Handles dispatch for lip-sync video generation and webcam extraction tools.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import subprocess
import time
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.exceptions import ClipCannonError

logger = logging.getLogger(__name__)


def _error(
    code: str, message: str, details: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build standardized error response dict."""
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _projects_dir() -> Path:
    """Resolve projects base directory."""
    try:
        config = ClipCannonConfig.load()
        return config.resolve_path("directories.projects")
    except ClipCannonError:
        return Path.home() / ".clipcannon" / "projects"


async def _handle_lip_sync(arguments: dict[str, object]) -> dict[str, object]:
    """Handle clipcannon_lip_sync tool call."""
    project_id = str(arguments.get("project_id", ""))
    audio_path_str = str(arguments.get("audio_path", ""))
    driver_path_str = str(arguments.get("driver_video_path", ""))
    inference_steps = int(arguments.get("inference_steps", 20))
    guidance_scale = float(arguments.get("guidance_scale", 1.5))
    seed = arguments.get("seed")
    n_candidates = int(arguments.get("n_candidates", 1))

    if not project_id:
        return _error("MISSING_PARAMETER", "project_id is required")
    if not audio_path_str:
        return _error("MISSING_PARAMETER", "audio_path is required")
    if not driver_path_str:
        return _error("MISSING_PARAMETER", "driver_video_path is required")

    audio_path = Path(audio_path_str)
    driver_path = Path(driver_path_str)

    if not audio_path.exists():
        return _error("FILE_NOT_FOUND", f"Audio file not found: {audio_path}")
    if not driver_path.exists():
        return _error("FILE_NOT_FOUND", f"Driver video not found: {driver_path}")

    # Output path
    projects_dir = _projects_dir()
    project_dir = projects_dir / project_id
    if not project_dir.exists():
        return _error("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    avatar_dir = project_dir / "avatar"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    output_id = f"avatar_{secrets.token_hex(6)}"
    output_path = avatar_dir / f"{output_id}.mp4"

    start = time.monotonic()

    try:
        from clipcannon.avatar.lip_sync import get_engine

        engine = get_engine()

        if n_candidates > 1:
            result = engine.generate_best_of_n(
                video_path=driver_path,
                audio_path=audio_path,
                output_path=output_path,
                n_candidates=n_candidates,
                inference_steps=inference_steps,
                guidance_scale=guidance_scale,
            )
        else:
            result = engine.generate(
                video_path=driver_path,
                audio_path=audio_path,
                output_path=output_path,
                inference_steps=inference_steps,
                guidance_scale=guidance_scale,
                seed=int(seed) if seed is not None else None,
            )
    except FileNotFoundError as exc:
        return _error("PREREQUISITE_MISSING", str(exc))
    except RuntimeError as exc:
        if "Face not detected" in str(exc):
            return _error("FACE_NOT_DETECTED", str(exc))
        logger.exception("Lip sync failed for project %s", project_id)
        return _error("LIP_SYNC_FAILED", str(exc))
    except Exception as exc:
        logger.exception("Lip sync failed for project %s", project_id)
        return _error("LIP_SYNC_FAILED", str(exc))

    elapsed_ms = int((time.monotonic() - start) * 1000)

    return {
        "output_id": output_id,
        "video_path": str(result.video_path),
        "duration_ms": result.duration_ms,
        "resolution": result.resolution,
        "inference_steps": result.inference_steps,
        "elapsed_ms": elapsed_ms,
    }


def _get_webcam_region(
    db_path: Path, project_id: str,
) -> dict[str, int] | None:
    """Get the stable webcam region from scene_map data.

    Returns the median webcam bounding box across all scenes,
    or the median face region expanded to a webcam crop if no
    explicit webcam region was stored.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Try webcam regions first (from scene_analysis)
        rows = conn.execute(
            "SELECT webcam_x, webcam_y, webcam_w, webcam_h, "
            "face_x, face_y, face_w, face_h "
            "FROM scene_map WHERE project_id = ? "
            "AND (webcam_x IS NOT NULL OR face_x IS NOT NULL)",
            (project_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()

    if not rows:
        return None

    # Collect webcam or face regions
    webcam_xs, webcam_ys, webcam_ws, webcam_hs = [], [], [], []

    for row in rows:
        if row["webcam_x"] is not None:
            webcam_xs.append(int(row["webcam_x"]))
            webcam_ys.append(int(row["webcam_y"]))
            webcam_ws.append(int(row["webcam_w"]))
            webcam_hs.append(int(row["webcam_h"]))
        elif row["face_x"] is not None:
            # Expand face bbox to a reasonable webcam crop
            fx, fy = int(row["face_x"]), int(row["face_y"])
            fw, fh = int(row["face_w"]), int(row["face_h"])
            expand_w = int(fw * 2.0)
            expand_h = int(fh * 2.8)
            wx = max(0, fx - (expand_w - fw) // 2)
            wy = max(0, fy - int(fh * 0.4))
            webcam_xs.append(wx)
            webcam_ys.append(wy)
            webcam_ws.append(expand_w)
            webcam_hs.append(expand_h)

    if not webcam_xs:
        return None

    import statistics

    return {
        "x": int(statistics.median(webcam_xs)),
        "y": int(statistics.median(webcam_ys)),
        "w": int(statistics.median(webcam_ws)),
        "h": int(statistics.median(webcam_hs)),
    }


def _get_source_info(
    db_path: Path, project_id: str,
) -> dict[str, object] | None:
    """Get source video path and resolution from project DB."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT source_path, source_cfr_path, resolution, duration_ms "
            "FROM project WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    source = row["source_cfr_path"] or row["source_path"]
    res = str(row["resolution"]).split("x")

    return {
        "source_path": str(source),
        "width": int(res[0]),
        "height": int(res[1]),
        "duration_ms": int(row["duration_ms"]),
    }


async def _handle_extract_webcam(
    arguments: dict[str, object],
) -> dict[str, object]:
    """Handle clipcannon_extract_webcam tool call.

    Extracts the webcam/face region from an ingested video using
    scene_map data and FFmpeg crop.
    """
    project_id = str(arguments.get("project_id", ""))
    start_ms = arguments.get("start_ms")
    end_ms = arguments.get("end_ms")
    padding_pct = float(arguments.get("padding_pct", 0.15))

    if not project_id:
        return _error("MISSING_PARAMETER", "project_id is required")

    projects_dir = _projects_dir()
    project_dir = projects_dir / project_id
    if not project_dir.exists():
        return _error("PROJECT_NOT_FOUND", f"Project not found: {project_id}")

    db_path = project_dir / "analysis.db"
    if not db_path.exists():
        return _error("NOT_INGESTED", "Project has no analysis.db -- run clipcannon_ingest first")

    # Get source video info
    source_info = _get_source_info(db_path, project_id)
    if source_info is None:
        return _error("PROJECT_NOT_FOUND", f"No project record for {project_id}")

    source_path = Path(str(source_info["source_path"]))
    if not source_path.exists():
        return _error("FILE_NOT_FOUND", f"Source video not found: {source_path}")

    src_w = int(source_info["width"])
    src_h = int(source_info["height"])
    duration_ms = int(source_info["duration_ms"])

    # Get webcam/face region from scene_map
    region = _get_webcam_region(db_path, project_id)
    if region is None:
        return _error(
            "NO_FACE_DETECTED",
            "No face or webcam region found in scene_map. "
            "Ensure the video contains a visible face and has been ingested.",
        )

    # Apply padding
    pad_x = int(region["w"] * padding_pct)
    pad_y = int(region["h"] * padding_pct)

    crop_x = max(0, region["x"] - pad_x)
    crop_y = max(0, region["y"] - pad_y)
    crop_w = min(region["w"] + 2 * pad_x, src_w - crop_x)
    crop_h = min(region["h"] + 2 * pad_y, src_h - crop_y)

    # Ensure even dimensions (required by most codecs)
    crop_w = crop_w - (crop_w % 2)
    crop_h = crop_h - (crop_h % 2)

    if crop_w < 64 or crop_h < 64:
        return _error(
            "REGION_TOO_SMALL",
            f"Detected webcam region is too small: {crop_w}x{crop_h}. "
            "The face may be too small in the source video.",
        )

    # Time range
    ss_arg = []
    to_arg = []
    if start_ms is not None:
        ss_arg = ["-ss", f"{int(start_ms) / 1000:.3f}"]
    if end_ms is not None:
        to_arg = ["-to", f"{int(end_ms) / 1000:.3f}"]
    elif start_ms is None:
        # Default: use full duration
        pass

    # Output path
    avatar_dir = project_dir / "avatar"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    output_id = f"webcam_{secrets.token_hex(6)}"
    output_path = avatar_dir / f"{output_id}.mp4"

    # FFmpeg crop + force 25fps (LatentSync is hardcoded to 25fps;
    # feeding 60fps causes audio-visual sync drift)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-nostdin",
        *ss_arg,
        "-i", str(source_path),
        *to_arg,
        "-vf", f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
        "-r", "25",
        "-c:v", "libx264", "-crf", "18",
        "-c:a", "aac",
        "-movflags", "+faststart",
        str(output_path),
    ]

    start = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    if proc.returncode != 0:
        return _error(
            "FFMPEG_FAILED",
            f"FFmpeg crop failed: {proc.stderr.strip()[:500]}",
        )

    if not output_path.exists():
        return _error("OUTPUT_MISSING", "FFmpeg completed but output not found")

    # Probe output
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", str(output_path)],
        capture_output=True, text=True,
    )
    out_duration_ms = 0
    out_resolution = f"{crop_w}x{crop_h}"
    if probe.returncode == 0:
        data = json.loads(probe.stdout)
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                out_duration_ms = int(float(s.get("duration", 0)) * 1000)
                out_resolution = f"{s.get('width', crop_w)}x{s.get('height', crop_h)}"
                break

    logger.info(
        "Webcam extracted: %s, %dx%d at (%d,%d), %dms, took %dms",
        output_path.name, crop_w, crop_h, crop_x, crop_y,
        out_duration_ms, elapsed_ms,
    )

    return {
        "output_id": output_id,
        "video_path": str(output_path),
        "duration_ms": out_duration_ms,
        "resolution": out_resolution,
        "crop_region": {
            "x": crop_x, "y": crop_y,
            "width": crop_w, "height": crop_h,
        },
        "source_resolution": f"{src_w}x{src_h}",
        "elapsed_ms": elapsed_ms,
    }


async def dispatch_avatar_tool(
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    """Dispatch an avatar tool call by name."""
    if name == "clipcannon_lip_sync":
        return await _handle_lip_sync(arguments)
    if name == "clipcannon_extract_webcam":
        return await _handle_extract_webcam(arguments)
    return _error("INTERNAL_ERROR", f"Unknown avatar tool: {name}")
