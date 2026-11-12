"""RenderEngine: converts EDLs into rendered video files."""

from __future__ import annotations

import logging
import secrets
import time
from typing import TYPE_CHECKING

from clipcannon.editing.edl import compute_total_duration
from clipcannon.editing.speaker_framing import SpeakerTrackingMissingError
from clipcannon.exceptions import PipelineError
from clipcannon.provenance.hasher import sha256_file
from clipcannon.rendering.ffmpeg_cmd import build_encoding_args

from .audio_mix import _AudioMixMixin
from .helpers import RenderResult
from .inputs import _RenderInputsMixin
from .output import _RenderOutputMixin
from .segment_cache import _SegmentCacheMixin
from .segmented import _SegmentedRenderMixin

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.config import ClipCannonConfig
    from clipcannon.editing.edl import EditDecisionList

logger = logging.getLogger(__name__)


class RenderEngine(
    _RenderInputsMixin,
    _SegmentedRenderMixin,
    _SegmentCacheMixin,
    _AudioMixMixin,
    _RenderOutputMixin,
):
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
            self._apply_speaker_framing(edl, profile, db_path, source_path, render_id)
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

        except (PipelineError, SpeakerTrackingMissingError):
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
