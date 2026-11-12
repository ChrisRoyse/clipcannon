"""Rendered-segment cache lookup and storage for RenderEngine."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

    from clipcannon.editing.edl import SegmentSpec

logger = logging.getLogger(__name__)


class _SegmentCacheMixin:
    """Rendered-segment cache lookup and storage for RenderEngine."""

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
