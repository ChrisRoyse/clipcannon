"""Source, profile, caption and crop resolution for RenderEngine."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_one
from clipcannon.editing.caption_render import generate_ass_file
from clipcannon.editing.smart_crop import compute_crop_region
from clipcannon.exceptions import PipelineError
from clipcannon.rendering.profiles import get_profile, get_software_fallback

from .helpers import _probe_size

if TYPE_CHECKING:
    from clipcannon.editing.edl import EditDecisionList
    from clipcannon.editing.smart_crop import CropRegion
    from clipcannon.rendering.profiles import EncodingProfile

logger = logging.getLogger(__name__)


class _RenderInputsMixin:
    """Source, profile, caption and crop resolution for RenderEngine."""

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
            font_size=edl.captions.font_size,
            position=edl.captions.position,
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
    def _apply_speaker_framing(
        self,
        edl: EditDecisionList,
        profile: EncodingProfile,
        db_path: Path,
        source_path: Path,
        render_id: str,
    ) -> None:
        """Attach speaker-following framing to segments that want face tracking.

        Applies to crop mode "auto" with face_tracking and the plain "crop"
        layout, for segments without an explicit canvas (an agent's manual
        framing always wins). Needs the speaker_tracking stage's tables; if
        the stage never ran, compute_tracked_framing raises
        SpeakerTrackingMissingError (no centre crop stands in for it). A segment
        in which no face is visible has nothing to follow: it keeps the
        static crop and that is logged as a warning.
        """
        if not (edl.crop.mode == "auto" and edl.crop.face_tracking
                and edl.crop.layout == "crop"):
            return
        from clipcannon.editing.edl import SegmentCanvasSpec
        from clipcannon.editing.speaker_framing import compute_tracked_framing

        source_size = _probe_size(source_path)
        for seg in edl.segments:
            if seg.canvas is not None:
                continue
            framing = compute_tracked_framing(
                db_path, edl.project_id, seg.source_start_ms, seg.source_end_ms,
                source_size=source_size, canvas_size=(profile.width, profile.height),
            )
            if framing is not None:
                seg.canvas = SegmentCanvasSpec(track=framing)
                logger.info(
                    "Render %s: segment %d speaker framing, %d shot piece(s), speakers %s",
                    render_id, seg.segment_id, len(framing.pieces), framing.speakers,
                )
            else:
                logger.warning(
                    "Render %s: segment %d (%d-%d ms) shows no face; static crop kept",
                    render_id, seg.segment_id, seg.source_start_ms, seg.source_end_ms,
                )

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
