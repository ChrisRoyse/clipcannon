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
    from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_one
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
from clipcannon.rendering.ffmpeg_cmd import build_encoding_args, build_ffmpeg_cmd
from clipcannon.rendering.profiles import (
    EncodingProfile,
    get_profile,
    get_software_fallback,
)
from clipcannon.rendering.thumbnail import generate_thumbnail

logger = logging.getLogger(__name__)


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

            # Build and execute FFmpeg command
            nvenc_preset = (
                str(self.config.get("rendering.nvenc_preset"))
                if "nvenc" in profile.video_codec
                else None
            )
            encoding_args = build_encoding_args(profile, nvenc_preset)
            cmd = build_ffmpeg_cmd(
                source_path=source_path,
                output_path=output_path,
                segments=edl.segments,
                profile=profile,
                crop_region=crop_region,
                ass_path=ass_path,
                encoding_args=encoding_args,
            )
            await self._execute_ffmpeg(cmd, render_id)

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
