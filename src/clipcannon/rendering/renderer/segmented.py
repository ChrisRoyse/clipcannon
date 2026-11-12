"""Segment-by-segment rendering path for RenderEngine."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from clipcannon.editing.edl import compute_total_duration
from clipcannon.exceptions import PipelineError
from clipcannon.rendering.ffmpeg_cmd import _escape_subtitle_path, build_ffmpeg_cmd
from clipcannon.rendering.segment_hash import compute_segment_hash

from .helpers import _probe_duration_ms, _scale_ass_file, ensure_segment_cache_table

if TYPE_CHECKING:
    from clipcannon.editing.edl import EditDecisionList
    from clipcannon.editing.smart_crop import CropRegion
    from clipcannon.rendering.profiles import EncodingProfile

logger = logging.getLogger(__name__)


class _SegmentedRenderMixin:
    """Segment-by-segment rendering path for RenderEngine."""

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
