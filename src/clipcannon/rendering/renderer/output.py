"""FFmpeg execution, thumbnails, provenance and DB updates for RenderEngine."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute
from clipcannon.exceptions import PipelineError
from clipcannon.provenance.recorder import ExecutionInfo, InputInfo, OutputInfo, record_provenance
from clipcannon.rendering.thumbnail import generate_thumbnail

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.editing.edl import EditDecisionList
    from clipcannon.editing.smart_crop import CropRegion
    from clipcannon.rendering.profiles import EncodingProfile

logger = logging.getLogger(__name__)


class _RenderOutputMixin:
    """FFmpeg execution, thumbnails, provenance and DB updates for RenderEngine."""

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
