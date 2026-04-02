"""Core rendering engine for ClipCannon.

Translates an EDL (Edit Decision List) into FFmpeg commands and
executes them as subprocesses. Handles source validation, caption
generation, crop computation, and provenance recording.
Enforces generation loss prevention and source integrity checks.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

    from clipcannon.config import ClipCannonConfig
    from clipcannon.editing.edl import SegmentSpec
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all, fetch_one
from clipcannon.editing.caption_render import generate_ass_file
from clipcannon.editing.edl import (
    EditDecisionList,
    compute_total_duration,
)
from clipcannon.editing.smart_crop import CropRegion, compute_crop_region
from clipcannon.exceptions import PipelineError
from clipcannon.provenance.hasher import sha256_file
from clipcannon.provenance.recorder import (
    ExecutionInfo,
    InputInfo,
    OutputInfo,
    record_provenance,
)
from clipcannon.rendering.ffmpeg_cmd import (
    _escape_subtitle_path,
    build_encoding_args,
    build_ffmpeg_cmd,
)
from clipcannon.rendering.profiles import (
    EncodingProfile,
    get_profile,
    get_software_fallback,
)
from clipcannon.rendering.segment_hash import compute_segment_hash
from clipcannon.rendering.thumbnail import generate_thumbnail

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


class RenderEngine:
    """Rendering engine that converts EDLs into rendered video files.

    Builds FFmpeg commands from EDL specifications and executes them
    as async subprocesses. Handles source validation, caption
    generation, crop computation, and provenance recording.

    Attributes:
        config: ClipCannon configuration instance.
    """

    def __init__(self, config: ClipCannonConfig) -> None:
        """Initialize the render engine.

        Args:
            config: ClipCannon configuration instance.
        """
        self.config = config

    async def render(
        self,
        edl: EditDecisionList,
        project_dir: Path,
        db_path: Path,
    ) -> RenderResult:
        """Render an EDL to a video file.

        Validates source integrity, generates captions and crop
        regions, builds and executes the FFmpeg command, generates
        a thumbnail, and records provenance.

        Args:
            edl: The Edit Decision List to render.
            project_dir: Path to the project directory.
            db_path: Path to the project SQLite database.

        Returns:
            RenderResult with render outcome details.
        """
        render_id = f"render_{secrets.token_hex(6)}"
        start_time = time.monotonic()

        log_ctx = {
            "project_id": edl.project_id,
            "edit_id": edl.edit_id,
            "render_id": render_id,
        }

        try:
            source_path = self._resolve_source(edl, project_dir, db_path)
            profile = self._resolve_profile(edl)

            render_dir = project_dir / "renders" / render_id
            render_dir.mkdir(parents=True, exist_ok=True)
            output_path = render_dir / "output.mp4"

            ass_path = self._write_captions(edl, profile, render_dir, render_id)
            crop_region = self._compute_crop(edl, profile)

            # Build and execute FFmpeg — segmented rendering to prevent OOM
            nvenc_preset = (
                str(self.config.get("rendering.nvenc_preset"))
                if "nvenc" in profile.video_codec
                else None
            )
            encoding_args = build_encoding_args(profile, nvenc_preset)

            await self._render_segmented(
                edl=edl,
                source_path=source_path,
                output_path=output_path,
                profile=profile,
                crop_region=crop_region,
                ass_path=ass_path,
                encoding_args=encoding_args,
                render_id=render_id,
                render_dir=render_dir,
                db_path=db_path,
            )

            if not output_path.exists():
                raise PipelineError(
                    "FFmpeg completed but output file not found",
                    stage_name="rendering",
                    operation="render",
                    details={"output_path": str(output_path)},
                )

            file_size = output_path.stat().st_size
            output_hash = sha256_file(output_path)
            total_duration = compute_total_duration(edl.segments)
            render_duration_ms = int(
                (time.monotonic() - start_time) * 1000
            )

            thumb_path = await self._generate_thumb(
                source_path, edl, profile, crop_region,
                total_duration, render_dir, render_id,
            )

            prov_id = self._record_provenance(
                db_path, edl, source_path, output_path,
                output_hash, file_size, render_duration_ms,
                render_id, profile,
            )

            self._update_db(
                db_path=db_path,
                render_id=render_id,
                edl=edl,
                profile=profile,
                output_path=output_path,
                output_hash=output_hash,
                file_size=file_size,
                duration_ms=total_duration,
                render_duration_ms=render_duration_ms,
                thumb_path=thumb_path,
                prov_id=prov_id,
            )

            logger.info(
                "Render %s completed in %dms (%d bytes)",
                render_id, render_duration_ms, file_size,
            )

            return RenderResult(
                render_id=render_id,
                success=True,
                output_path=output_path,
                thumbnail_path=thumb_path,
                output_sha256=output_hash,
                file_size_bytes=file_size,
                duration_ms=total_duration,
                render_duration_ms=render_duration_ms,
                provenance_record_id=prov_id,
            )

        except PipelineError:
            raise
        except Exception as exc:
            elapsed = int((time.monotonic() - start_time) * 1000)
            error_msg = str(exc)
            logger.exception(
                "Render %s failed after %dms: %s",
                render_id, elapsed, error_msg,
                extra=log_ctx,
            )
            return RenderResult(
                render_id=render_id,
                success=False,
                error_message=error_msg,
                render_duration_ms=elapsed,
            )

    # ----------------------------------------------------------------
    # Source validation
    # ----------------------------------------------------------------
    def _resolve_source(
        self,
        edl: EditDecisionList,
        project_dir: Path,
        db_path: Path,
    ) -> Path:
        """Resolve and validate the source video file.

        Checks that source SHA-256 matches and that the source is
        NOT from a renders directory (generation loss prevention).

        Args:
            edl: The EDL containing source_sha256.
            project_dir: Project directory path.
            db_path: Path to the project database.

        Returns:
            Resolved path to the source video.

        Raises:
            PipelineError: On validation failure.
        """
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            row = fetch_one(
                conn,
                "SELECT source_path, source_sha256, source_cfr_path "
                "FROM project WHERE project_id = ?",
                (edl.project_id,),
            )
        finally:
            conn.close()

        if row is None:
            raise PipelineError(
                f"Project not found: {edl.project_id}",
                stage_name="rendering",
                operation="resolve_source",
            )

        db_sha256 = str(row["source_sha256"])
        if edl.source_sha256 and edl.source_sha256 != db_sha256:
            raise PipelineError(
                f"Source SHA-256 mismatch: EDL={edl.source_sha256!r}, "
                f"DB={db_sha256!r}",
                stage_name="rendering",
                operation="source_validation",
            )

        # Prefer CFR path if available
        cfr_path = row.get("source_cfr_path")
        if cfr_path and Path(str(cfr_path)).exists():
            source_path = Path(str(cfr_path))
        else:
            source_path = Path(str(row["source_path"]))

        # Generation loss prevention: reject renders as source
        source_str = str(source_path.resolve())
        if "/renders/" in source_str:
            raise PipelineError(
                "Generation loss prevention: cannot render from a "
                "previously rendered file. Use the original source.",
                stage_name="rendering",
                operation="generation_loss_check",
                details={"source_path": source_str},
            )

        if not source_path.exists():
            raise PipelineError(
                f"Source file not found: {source_path}",
                stage_name="rendering",
                operation="resolve_source",
                details={"source_path": str(source_path)},
            )

        return source_path

    # ----------------------------------------------------------------
    # Profile resolution
    # ----------------------------------------------------------------
    def _resolve_profile(self, edl: EditDecisionList) -> EncodingProfile:
        """Resolve encoding profile, falling back to software codec.

        Args:
            edl: EDL with render settings.

        Returns:
            Resolved EncodingProfile.
        """
        profile_name = edl.render_settings.profile or edl.target_profile
        if not profile_name:
            profile_name = "tiktok_vertical"

        profile = get_profile(profile_name)

        if not edl.render_settings.use_nvenc:
            profile = get_software_fallback(profile)

        return profile

    # ----------------------------------------------------------------
    # Captions
    # ----------------------------------------------------------------
    def _write_captions(
        self,
        edl: EditDecisionList,
        profile: EncodingProfile,
        render_dir: Path,
        render_id: str,
    ) -> Path | None:
        """Generate and write captions ASS file if enabled.

        Args:
            edl: EDL with caption specification.
            profile: Encoding profile for resolution.
            render_dir: Directory to write the ASS file.
            render_id: Render ID for logging.

        Returns:
            Path to the ASS file, or None if captions disabled.
        """
        if not edl.captions.enabled or not edl.captions.chunks:
            return None

        ass_content = generate_ass_file(
            edl.captions.chunks,
            edl.captions.style,  # type: ignore[arg-type]
            resolution_w=profile.width,
            resolution_h=profile.height,
        )
        ass_path = render_dir / "captions.ass"
        ass_path.write_text(ass_content, encoding="utf-8")
        logger.info(
            "Render %s: wrote captions ASS (%d chunks)",
            render_id, len(edl.captions.chunks),
        )
        return ass_path

    # ----------------------------------------------------------------
    # Crop computation
    # ----------------------------------------------------------------
    def _compute_crop(
        self,
        edl: EditDecisionList,
        profile: EncodingProfile,
    ) -> CropRegion | None:
        """Compute crop region if aspect ratio conversion is needed.

        Args:
            edl: EDL with crop specification.
            profile: Target encoding profile.

        Returns:
            CropRegion or None if no cropping needed.
        """
        if edl.crop.mode == "none":
            return None

        # Default center crop for the target aspect ratio
        # Assume 1920x1080 source for crop calculation
        # Actual source dimensions would be read from probe data
        source_w, source_h = 1920, 1080
        return compute_crop_region(
            source_w=source_w,
            source_h=source_h,
            target_aspect=edl.crop.aspect_ratio,
            face_position_x=0.5,
            face_position_y=0.5,
            safe_area_pct=edl.crop.safe_area_pct,
        )

    # ----------------------------------------------------------------
    # Segmented rendering (OOM prevention)
    # ----------------------------------------------------------------
    async def _render_segmented(
        self,
        edl: EditDecisionList,
        source_path: Path,
        output_path: Path,
        profile: EncodingProfile,
        crop_region: CropRegion | None,
        ass_path: Path | None,
        encoding_args: list[str],
        render_id: str,
        render_dir: Path,
        db_path: Path | None = None,
    ) -> None:
        """Render each segment independently then concatenate.

        This limits peak memory to ONE segment at a time instead of
        holding all segments in a single filter_complex. Critical for
        4K source videos in WSL2 where GPU paravirtualization limits
        memory allocation.

        Args:
            edl: The Edit Decision List to render.
            source_path: Path to the source video.
            output_path: Path for the final output file.
            profile: Encoding profile to use.
            crop_region: Optional crop region.
            ass_path: Path to ASS captions file, or None.
            encoding_args: Encoding arguments for FFmpeg.
            render_id: Unique render identifier.
            render_dir: Directory for render artifacts.
            db_path: Path to the project database (for audio assets).
        """
        segments = edl.segments
        canvas_spec = edl.canvas if edl.canvas.enabled else None

        if len(segments) <= 1:
            # Single segment: direct render (no concat needed).
            # When db_path is available, render to a temp file first
            # so we can mix audio assets in a second pass.
            if db_path is not None:
                import shutil
                import tempfile

                with tempfile.TemporaryDirectory(
                    prefix="cc_single_"
                ) as tmpdir:
                    single_temp = Path(tmpdir)
                    raw_output = single_temp / "raw.mp4"

                    cmd = build_ffmpeg_cmd(
                        source_path=source_path,
                        output_path=raw_output,
                        segments=segments,
                        profile=profile,
                        crop_region=crop_region,
                        ass_path=ass_path,
                        encoding_args=encoding_args,
                        canvas=canvas_spec,
                        global_color=edl.color,
                        overlays=edl.overlays or None,
                        removals=edl.removals or None,
                    )
                    await self._execute_ffmpeg(cmd, render_id)

                    mixed = await self._prepare_mixed_audio(
                        edl, db_path, raw_output, single_temp,
                        render_id,
                    )
                    if mixed is not None:
                        audio_cmd: list[str] = [
                            "ffmpeg", "-y",
                            "-i", str(raw_output),
                            "-i", str(mixed),
                            "-map", "0:v", "-map", "1:a",
                            "-c:v", "copy",
                            "-c:a", "aac", "-b:a", "192k",
                            str(output_path),
                        ]
                        await self._execute_ffmpeg(
                            audio_cmd, f"{render_id}_audio_mix"
                        )
                    else:
                        shutil.move(str(raw_output), str(output_path))
            else:
                cmd = build_ffmpeg_cmd(
                    source_path=source_path,
                    output_path=output_path,
                    segments=segments,
                    profile=profile,
                    crop_region=crop_region,
                    ass_path=ass_path,
                    encoding_args=encoding_args,
                    canvas=canvas_spec,
                    global_color=edl.color,
                    overlays=edl.overlays or None,
                    removals=edl.removals or None,
                )
                await self._execute_ffmpeg(cmd, render_id)
            return

        # Multi-segment: render each independently with cache
        import shutil
        from copy import deepcopy

        temp_dir = render_dir / "segments"
        temp_dir.mkdir(parents=True, exist_ok=True)
        segment_files: list[Path] = []

        # Set up segment cache directory and DB table
        project_dir = render_dir.parent.parent
        cache_dir = project_dir / "segment_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_conn = None
        if db_path is not None:
            import sqlite3
            cache_conn = sqlite3.connect(str(db_path))
            ensure_segment_cache_table(cache_conn)

        source_hash = edl.source_sha256

        try:
            for i, seg in enumerate(segments):
                seg_output = temp_dir / f"seg_{i:03d}.mp4"

                # Overlays: only include overlays that fall within this
                # segment's output time range, remapped to local times
                seg_start_output_ms = sum(
                    s.output_duration_ms for s in segments[:i]
                )
                seg_end_output_ms = (
                    seg_start_output_ms + seg.output_duration_ms
                )
                seg_overlays = None
                if edl.overlays:
                    matching = [
                        ov
                        for ov in edl.overlays
                        if ov.start_ms < seg_end_output_ms
                        and ov.end_ms > seg_start_output_ms
                    ]
                    if matching:
                        remapped = []
                        for ov in matching:
                            ov_copy = deepcopy(ov)
                            ov_copy.start_ms = max(
                                0, ov.start_ms - seg_start_output_ms
                            )
                            ov_copy.end_ms = min(
                                seg_end_output_ms - seg_start_output_ms,
                                ov.end_ms - seg_start_output_ms,
                            )
                            remapped.append(ov_copy)
                        seg_overlays = remapped if remapped else None

                # Compute content hash for cache lookup
                seg_hash = compute_segment_hash(
                    source_sha256=source_hash,
                    segment=seg,
                    profile_name=profile.name,
                    canvas=canvas_spec,
                    global_color=edl.color,
                    overlays=seg_overlays,
                )

                # Check segment cache
                cache_hit = False
                if cache_conn is not None:
                    cache_hit = self._check_segment_cache(
                        conn=cache_conn,
                        cache_hash=seg_hash,
                        seg_output=seg_output,
                        render_id=render_id,
                        seg_index=i,
                        seg_count=len(segments),
                    )

                if not cache_hit:
                    logger.info(
                        "Render %s: segment %d/%d CACHE MISS, "
                        "rendering (%d-%dms)",
                        render_id,
                        i + 1,
                        len(segments),
                        seg.source_start_ms,
                        seg.source_end_ms,
                    )

                    # Build command for this single segment
                    single_seg_list = [seg]
                    seg_ass_path = None

                    cmd = build_ffmpeg_cmd(
                        source_path=source_path,
                        output_path=seg_output,
                        segments=single_seg_list,
                        profile=profile,
                        crop_region=crop_region,
                        ass_path=seg_ass_path,
                        encoding_args=encoding_args,
                        canvas=canvas_spec,
                        global_color=edl.color,
                        overlays=seg_overlays,
                        removals=edl.removals or None,
                    )
                    await self._execute_ffmpeg(
                        cmd, f"{render_id}_seg{i}"
                    )

                    if (
                        not seg_output.exists()
                        or seg_output.stat().st_size == 0
                    ):
                        raise PipelineError(
                            f"Segment {i} render produced no output",
                            stage_name="rendering",
                            operation="segment_render",
                            details={
                                "segment": i,
                                "path": str(seg_output),
                            },
                        )

                    # Store in cache
                    if cache_conn is not None:
                        self._store_segment_cache(
                            conn=cache_conn,
                            cache_hash=seg_hash,
                            project_id=edl.project_id,
                            source_hash=source_hash,
                            segment=seg,
                            seg_output=seg_output,
                            cache_dir=cache_dir,
                            render_id=render_id,
                            seg_index=i,
                            seg_count=len(segments),
                        )

                segment_files.append(seg_output)
                logger.info(
                    "Render %s: segment %d/%d complete (%.1f MB)",
                    render_id,
                    i + 1,
                    len(segments),
                    seg_output.stat().st_size / 1024 / 1024,
                )

            # Concatenate all segments
            concat_list = temp_dir / "concat.txt"
            with open(concat_list, "w") as f:
                for sf in segment_files:
                    f.write(f"file '{sf}'\n")

            logger.info(
                "Render %s: concatenating %d segments",
                render_id,
                len(segment_files),
            )

            # Always concat to temp file first — both the caption
            # and audio-mixing paths need the intermediate output.
            concat_raw = temp_dir / "concat_raw.mp4"
            concat_cmd: list[str] = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c", "copy",
                str(concat_raw),
            ]
            await self._execute_ffmpeg(
                concat_cmd, f"{render_id}_concat"
            )

            # Mix audio assets (music, SFX) into the output if any
            mixed_audio = await self._prepare_mixed_audio(
                edl, db_path, concat_raw, temp_dir, render_id,
            )

            if ass_path is not None:
                # Two-pass caption approach:
                # 1. Concat with stream copy (done above)
                # 2. Probe actual duration for drift correction
                # 3. Scale ASS timestamps if needed
                # 4. Burn captions (+ mixed audio) in second pass
                actual_ms = _probe_duration_ms(concat_raw)
                expected_ms = compute_total_duration(edl.segments)
                drift_ms = actual_ms - expected_ms

                caption_ass = ass_path
                if abs(drift_ms) > 50:
                    scale = actual_ms / expected_ms
                    logger.info(
                        "Render %s: caption drift %+dms detected, "
                        "scaling ASS by %.5f",
                        render_id, drift_ms, scale,
                    )
                    caption_ass = _scale_ass_file(
                        ass_path,
                        scale,
                        render_dir / "captions_scaled.ass",
                    )

                escaped_ass = _escape_subtitle_path(caption_ass)

                if mixed_audio is not None:
                    # Burn captions + replace audio with mix
                    caption_cmd: list[str] = [
                        "ffmpeg", "-y",
                        "-i", str(concat_raw),
                        "-i", str(mixed_audio),
                        "-vf", f"subtitles='{escaped_ass}'",
                        "-map", "0:v", "-map", "1:a",
                        "-c:v", profile.video_codec,
                        "-b:v", str(profile.video_bitrate),
                        "-c:a", "aac", "-b:a", "192k",
                        str(output_path),
                    ]
                else:
                    # Burn captions, copy audio as-is
                    caption_cmd = [
                        "ffmpeg", "-y",
                        "-i", str(concat_raw),
                        "-vf", f"subtitles='{escaped_ass}'",
                        "-c:v", profile.video_codec,
                        "-b:v", str(profile.video_bitrate),
                        "-c:a", "copy",
                        str(output_path),
                    ]
                await self._execute_ffmpeg(
                    caption_cmd, f"{render_id}_captions"
                )
            else:
                if mixed_audio is not None:
                    # No captions but mix audio in (copy video stream)
                    audio_cmd: list[str] = [
                        "ffmpeg", "-y",
                        "-i", str(concat_raw),
                        "-i", str(mixed_audio),
                        "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k",
                        str(output_path),
                    ]
                    await self._execute_ffmpeg(
                        audio_cmd, f"{render_id}_audio_mix"
                    )
                else:
                    # No captions, no audio mix: move concat to output
                    shutil.move(str(concat_raw), str(output_path))

            concat_raw.unlink(missing_ok=True)

        finally:
            # Close cache connection
            if cache_conn is not None:
                cache_conn.close()
            # Clean up temp segment files
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.debug(
                    "Cleaned up temp segments: %s", temp_dir
                )

    # ----------------------------------------------------------------
    # Segment cache methods
    # ----------------------------------------------------------------
    def _check_segment_cache(
        self,
        conn: sqlite3.Connection,
        cache_hash: str,
        seg_output: Path,
        render_id: str,
        seg_index: int,
        seg_count: int,
    ) -> bool:
        """Check if a rendered segment exists in the cache.

        Queries the segment_cache table for the hash, verifies the
        cached file still exists on disk, copies it to the segment
        output path, and updates last_used_at.

        Args:
            conn: SQLite connection.
            cache_hash: Content hash of the segment.
            seg_output: Path where the segment file should be placed.
            render_id: Render ID for logging.
            seg_index: Zero-based segment index.
            seg_count: Total number of segments.

        Returns:
            True if cache hit and file was copied, False otherwise.
        """
        import shutil

        row = conn.execute(
            "SELECT file_path FROM segment_cache WHERE cache_hash = ?",
            (cache_hash,),
        ).fetchone()

        if row is None:
            return False

        cached_path = Path(row[0])
        if not cached_path.exists() or cached_path.stat().st_size == 0:
            # Cached file is missing or empty; treat as miss
            conn.execute(
                "DELETE FROM segment_cache WHERE cache_hash = ?",
                (cache_hash,),
            )
            conn.commit()
            logger.info(
                "Render %s: segment %d/%d cache file missing, "
                "removed stale entry (hash=%s...)",
                render_id, seg_index + 1, seg_count,
                cache_hash[:12],
            )
            return False

        # Copy cached file to segment output
        shutil.copy2(str(cached_path), str(seg_output))
        conn.execute(
            "UPDATE segment_cache SET last_used_at = datetime('now') "
            "WHERE cache_hash = ?",
            (cache_hash,),
        )
        conn.commit()

        file_mb = cached_path.stat().st_size / 1024 / 1024
        logger.info(
            "Render %s: segment %d/%d CACHE HIT "
            "(hash=%s..., %.1f MB)",
            render_id, seg_index + 1, seg_count,
            cache_hash[:12], file_mb,
        )
        return True

    def _store_segment_cache(
        self,
        conn: sqlite3.Connection,
        cache_hash: str,
        project_id: str,
        source_hash: str,
        segment: SegmentSpec,
        seg_output: Path,
        cache_dir: Path,
        render_id: str,
        seg_index: int,
        seg_count: int,
    ) -> None:
        """Store a rendered segment in the cache.

        Copies the rendered segment file to the cache directory and
        inserts a record into the segment_cache table.

        Args:
            conn: SQLite connection.
            cache_hash: Content hash of the segment.
            project_id: Project identifier.
            source_hash: SHA-256 of the source video.
            segment: The SegmentSpec (for storing spec JSON).
            seg_output: Path to the rendered segment file.
            cache_dir: Directory for cached segment files.
            render_id: Render ID for logging.
            seg_index: Zero-based segment index.
            seg_count: Total number of segments.
        """
        import shutil

        cached_path = cache_dir / f"{cache_hash}.mp4"
        shutil.copy2(str(seg_output), str(cached_path))

        file_size = cached_path.stat().st_size
        spec_json = segment.model_dump_json()

        conn.execute(
            "INSERT OR REPLACE INTO segment_cache "
            "(cache_hash, project_id, file_path, source_hash, "
            "segment_spec_json, file_size_bytes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                cache_hash,
                project_id,
                str(cached_path),
                source_hash,
                spec_json,
                file_size,
            ),
        )
        conn.commit()

        file_mb = file_size / 1024 / 1024
        logger.info(
            "Render %s: segment %d/%d cached "
            "(hash=%s..., %.1f MB)",
            render_id, seg_index + 1, seg_count,
            cache_hash[:12], file_mb,
        )

    # ----------------------------------------------------------------
    # Audio mixing
    # ----------------------------------------------------------------
    async def _prepare_mixed_audio(
        self,
        edl: EditDecisionList,
        db_path: Path,
        concat_path: Path,
        temp_dir: Path,
        render_id: str,
    ) -> Path | None:
        """Mix audio assets (music, SFX) into the concatenated audio.

        Queries audio_assets for the edit, extracts source audio from
        the concat video, calls the mixer, and returns the mixed WAV.

        Args:
            edl: EDL with edit_id for asset lookup.
            db_path: Path to the project database.
            concat_path: Path to the concatenated video.
            temp_dir: Temporary directory for intermediate files.
            render_id: Render ID for logging.

        Returns:
            Path to the mixed WAV file, or None if no audio assets.
        """
        from clipcannon.audio.mixer import mix_audio

        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            rows = fetch_all(
                conn,
                "SELECT asset_id, type, file_path, volume_db, "
                "generation_params "
                "FROM audio_assets WHERE edit_id = ? ORDER BY type",
                (edl.edit_id,),
            )
        finally:
            conn.close()

        if not rows:
            return None

        music_path: Path | None = None
        music_volume_db = -18.0
        cleanup_path: Path | None = None
        sfx_entries: list[dict[str, object]] = []

        for row in rows:
            asset_type = str(row["type"])
            file_path = Path(str(row["file_path"]))
            volume_db = float(row["volume_db"] or 0)

            if not file_path.exists():
                logger.warning(
                    "Render %s: audio asset missing: %s",
                    render_id, file_path,
                )
                continue

            if asset_type == "music":
                # Render MIDI to WAV if needed (compose_music outputs .mid)
                if file_path.suffix.lower() in (".mid", ".midi"):
                    try:
                        from clipcannon.audio.midi_render import render_midi_to_wav
                        wav_path = temp_dir / f"{file_path.stem}_rendered.wav"
                        await render_midi_to_wav(file_path, wav_path)
                        if wav_path.exists():
                            file_path = wav_path
                            logger.info(
                                "Render %s: MIDI rendered to WAV: %s",
                                render_id, wav_path,
                            )
                    except Exception as exc:
                        logger.warning(
                            "Render %s: MIDI render failed (%s), "
                            "continuing without music",
                            render_id, exc,
                        )
                music_path = file_path
                music_volume_db = volume_db
            elif asset_type == "sfx":
                offset_ms = _parse_sfx_offset_ms(
                    row["generation_params"]
                )
                sfx_entries.append({
                    "path": str(file_path),
                    "offset_ms": offset_ms,
                    "volume_db": volume_db,
                })
            elif asset_type == "cleaned":
                cleanup_path = file_path

        if music_path is None and not sfx_entries and cleanup_path is None:
            logger.debug(
                "Render %s: no audio assets found, skipping mix",
                render_id,
            )
            return None

        # Extract audio from concatenated video
        source_audio = temp_dir / "source_audio.wav"
        extract_cmd: list[str] = [
            "ffmpeg", "-y",
            "-i", str(concat_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "44100",
            str(source_audio),
        ]
        await self._execute_ffmpeg(
            extract_cmd, f"{render_id}_extract_audio"
        )

        if not source_audio.exists():
            logger.warning(
                "Render %s: audio extraction failed", render_id,
            )
            return None

        # Use cleanup audio as source when available
        mix_source = source_audio
        if cleanup_path is not None and cleanup_path.exists():
            logger.info(
                "Render %s: using cleaned audio as source: %s",
                render_id, cleanup_path,
            )
            mix_source = cleanup_path

        # Mix source speech with background music and SFX
        mixed_output = temp_dir / "mixed_audio.wav"
        try:
            result = await mix_audio(
                source_audio_path=mix_source,
                output_path=mixed_output,
                background_music_path=music_path,
                sfx_entries=sfx_entries or None,
                music_volume_db=music_volume_db,
                duck_under_speech=True,
            )
            logger.info(
                "Render %s: audio mixed (%d layers, %dms)",
                render_id, result.layers_mixed, result.duration_ms,
            )
        except Exception:
            logger.exception(
                "Render %s: audio mixing failed, continuing without",
                render_id,
            )
            return None
        finally:
            source_audio.unlink(missing_ok=True)

        return mixed_output

    # ----------------------------------------------------------------
    # FFmpeg execution
    # ----------------------------------------------------------------
    async def _execute_ffmpeg(
        self,
        cmd: list[str],
        render_id: str,
    ) -> None:
        """Execute an FFmpeg command as an async subprocess.

        Args:
            cmd: FFmpeg command as argument list.
            render_id: Render ID for logging context.

        Raises:
            PipelineError: If FFmpeg exits with non-zero code.
        """
        logger.info(
            "Render %s: executing FFmpeg (%d args)",
            render_id, len(cmd),
        )
        logger.debug("FFmpeg command: %s", " ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace")
            logger.error(
                "Render %s: FFmpeg failed (exit %d): %s",
                render_id, proc.returncode, stderr_text[-500:],
            )
            raise PipelineError(
                f"FFmpeg render failed (exit {proc.returncode})",
                stage_name="rendering",
                operation="ffmpeg_exec",
                details={
                    "render_id": render_id,
                    "exit_code": proc.returncode,
                    "stderr": stderr_text[:500],
                },
            )

        logger.info("Render %s: FFmpeg completed successfully", render_id)

    # ----------------------------------------------------------------
    # Thumbnail
    # ----------------------------------------------------------------
    async def _generate_thumb(
        self,
        source_path: Path,
        edl: EditDecisionList,
        profile: EncodingProfile,
        crop_region: CropRegion | None,
        total_duration: int,
        render_dir: Path,
        render_id: str,
    ) -> Path | None:
        """Generate a thumbnail for the rendered clip.

        Args:
            source_path: Source video path.
            edl: EDL with metadata containing thumbnail timestamp.
            profile: Encoding profile for dimensions.
            crop_region: Optional crop region.
            total_duration: Total clip duration in ms.
            render_dir: Directory for the thumbnail file.
            render_id: Render ID for logging.

        Returns:
            Path to the thumbnail, or None on failure.
        """
        thumb_ts = edl.metadata.thumbnail_timestamp_ms
        if thumb_ts is None:
            thumb_ts = min(1000, total_duration // 2)
        thumb_path = render_dir / "thumbnail.jpg"

        try:
            await generate_thumbnail(
                source_path=source_path,
                timestamp_ms=thumb_ts,
                output_path=thumb_path,
                width=profile.width,
                height=profile.height,
                crop_region=crop_region,
            )
            return thumb_path
        except PipelineError:
            logger.warning(
                "Render %s: thumbnail generation failed",
                render_id,
                exc_info=True,
            )
            return None

    # ----------------------------------------------------------------
    # Provenance
    # ----------------------------------------------------------------
    def _record_provenance(
        self,
        db_path: Path,
        edl: EditDecisionList,
        source_path: Path,
        output_path: Path,
        output_hash: str,
        file_size: int,
        render_duration_ms: int,
        render_id: str,
        profile: EncodingProfile,
    ) -> str | None:
        """Record provenance for the render operation.

        Args:
            db_path: Database path.
            edl: The rendered EDL.
            source_path: Source video path.
            output_path: Output video path.
            output_hash: SHA-256 of the output.
            file_size: Output file size in bytes.
            render_duration_ms: Render wall time in ms.
            render_id: Render identifier.
            profile: Encoding profile used.

        Returns:
            Provenance record ID, or None on failure.
        """
        try:
            return record_provenance(
                db_path=db_path,
                project_id=edl.project_id,
                operation="render",
                stage="ffmpeg",
                input_info=InputInfo(
                    file_path=str(source_path),
                    sha256=edl.source_sha256,
                ),
                output_info=OutputInfo(
                    file_path=str(output_path),
                    sha256=output_hash,
                    size_bytes=file_size,
                ),
                model_info=None,
                execution_info=ExecutionInfo(
                    duration_ms=render_duration_ms,
                ),
                parent_record_id=None,
                description=(
                    f"Rendered edit {edl.edit_id} with profile "
                    f"{profile.name}"
                ),
            )
        except Exception:
            logger.warning(
                "Render %s: provenance recording failed",
                render_id,
                exc_info=True,
            )
            return None

    # ----------------------------------------------------------------
    # Database updates
    # ----------------------------------------------------------------
    def _update_db(
        self,
        db_path: Path,
        render_id: str,
        edl: EditDecisionList,
        profile: EncodingProfile,
        output_path: Path,
        output_hash: str,
        file_size: int,
        duration_ms: int,
        render_duration_ms: int,
        thumb_path: Path | None,
        prov_id: str | None,
    ) -> None:
        """Update renders table and edit status in database.

        Args:
            db_path: Database path.
            render_id: Render identifier.
            edl: The rendered EDL.
            profile: Encoding profile used.
            output_path: Path to output file.
            output_hash: SHA-256 of output.
            file_size: Output file size in bytes.
            duration_ms: Clip duration in ms.
            render_duration_ms: Render wall time in ms.
            thumb_path: Thumbnail path or None.
            prov_id: Provenance record ID or None.
        """
        conn = get_connection(db_path, enable_vec=False, dict_rows=False)
        try:
            execute(
                conn,
                """INSERT INTO renders (
                    render_id, edit_id, project_id, status, profile,
                    output_path, output_sha256, file_size_bytes,
                    duration_ms, resolution, codec, thumbnail_path,
                    render_duration_ms, provenance_record_id,
                    completed_at
                ) VALUES (
                    ?, ?, ?, 'completed', ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    datetime('now')
                )""",
                (
                    render_id,
                    edl.edit_id,
                    edl.project_id,
                    profile.name,
                    str(output_path),
                    output_hash,
                    file_size,
                    duration_ms,
                    f"{profile.width}x{profile.height}",
                    profile.video_codec,
                    str(thumb_path) if thumb_path else None,
                    render_duration_ms,
                    prov_id,
                ),
            )

            execute(
                conn,
                "UPDATE edits SET status = 'rendered', "
                "updated_at = datetime('now') "
                "WHERE edit_id = ? AND project_id = ?",
                (edl.edit_id, edl.project_id),
            )

            conn.commit()
        except Exception as exc:
            logger.error(
                "Failed to update DB for render %s: %s",
                render_id, exc,
            )
            raise
        finally:
            conn.close()
