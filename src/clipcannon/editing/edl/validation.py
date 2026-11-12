"""EDL validation against the project database and duration computation."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from .model import EditDecisionList
    from .segments import SegmentSpec


# ============================================================
# VALIDATION
# ============================================================
def validate_edl(
    edl: EditDecisionList,
    project_db_path: Path,
) -> list[str]:
    """Validate an EDL against project data and platform constraints.

    Checks source hash, segment ordering, overlap, transition limits,
    and speed range.

    Args:
        edl: The EditDecisionList to validate.
        project_db_path: Path to the project SQLite database.

    Returns:
        List of validation error strings. Empty means valid.
    """
    errors: list[str] = []

    # --- Source hash validation ---
    try:
        conn = sqlite3.connect(str(project_db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT source_sha256, duration_ms FROM project "
                "WHERE project_id = ?",
                (edl.project_id,),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            errors.append(
                f"Project {edl.project_id!r} not found in database"
            )
            return errors

        db_sha256 = str(row["source_sha256"])
        source_duration_ms = int(row["duration_ms"])

        if edl.source_sha256 and edl.source_sha256 != db_sha256:
            errors.append(
                f"source_sha256 mismatch: EDL has {edl.source_sha256!r}, "
                f"DB has {db_sha256!r}"
            )
    except sqlite3.Error as exc:
        errors.append(f"Database error during validation: {exc}")
        return errors

    # --- Segment validation ---
    segments = edl.segments
    if not segments:
        errors.append("EDL must have at least one segment")
        return errors

    for seg in segments:
        # Time range within source bounds
        if seg.source_start_ms < 0:
            errors.append(
                f"Segment {seg.segment_id}: source_start_ms < 0"
            )
        if seg.source_end_ms > source_duration_ms:
            errors.append(
                f"Segment {seg.segment_id}: source_end_ms "
                f"({seg.source_end_ms}) > source duration "
                f"({source_duration_ms})"
            )
        if seg.source_end_ms <= seg.source_start_ms:
            errors.append(
                f"Segment {seg.segment_id}: source_end_ms must be > "
                f"source_start_ms"
            )

        # Minimum segment duration (500ms before speed)
        if seg.source_duration_ms < 500:
            errors.append(
                f"Segment {seg.segment_id}: source duration "
                f"({seg.source_duration_ms}ms) < minimum 500ms"
            )

        # Speed range
        if not (0.25 <= seg.speed <= 4.0):
            errors.append(
                f"Segment {seg.segment_id}: speed {seg.speed} "
                f"outside [0.25, 4.0]"
            )

    # --- Segment ordering ---
    for i in range(1, len(segments)):
        if segments[i].output_start_ms < segments[i - 1].output_start_ms:
            errors.append(
                f"Segments not ordered by output_start_ms: "
                f"segment {segments[i].segment_id} at "
                f"{segments[i].output_start_ms} < segment "
                f"{segments[i - 1].segment_id} at "
                f"{segments[i - 1].output_start_ms}"
            )

    # --- Overlap detection (accounting for transitions) ---
    for i in range(1, len(segments)):
        prev = segments[i - 1]
        curr = segments[i]
        prev_end = prev.output_start_ms + prev.output_duration_ms

        # Allow transition overlap
        overlap_allowance = 0
        if prev.transition_out:
            overlap_allowance += prev.transition_out.duration_ms
        if curr.transition_in:
            overlap_allowance += curr.transition_in.duration_ms

        if curr.output_start_ms < prev_end - overlap_allowance:
            errors.append(
                f"Segments {prev.segment_id} and {curr.segment_id} "
                f"overlap in output timeline beyond transition allowance"
            )

    # --- Transition duration constraints ---
    for i, seg in enumerate(segments):
        seg_dur = seg.output_duration_ms

        if (
            seg.transition_in
            and seg.transition_in.type != "cut"
            and i > 0
        ):
            prev_dur = segments[i - 1].output_duration_ms
            shorter = min(seg_dur, prev_dur)
            if seg.transition_in.duration_ms > shorter * 0.5:
                errors.append(
                    f"Segment {seg.segment_id}: transition_in "
                    f"duration ({seg.transition_in.duration_ms}ms) "
                    f"exceeds 50% of shorter adjacent segment "
                    f"({shorter}ms)"
                )

        if (
            seg.transition_out
            and seg.transition_out.type != "cut"
            and i < len(segments) - 1
        ):
            next_dur = segments[i + 1].output_duration_ms
            shorter = min(seg_dur, next_dur)
            if seg.transition_out.duration_ms > shorter * 0.5:
                errors.append(
                    f"Segment {seg.segment_id}: transition_out "
                    f"duration ({seg.transition_out.duration_ms}ms) "
                    f"exceeds 50% of shorter adjacent segment "
                    f"({shorter}ms)"
                )

    return errors


# ============================================================
# DURATION COMPUTATION
# ============================================================
def compute_total_duration(segments: list[SegmentSpec]) -> int:
    """Calculate total output duration in milliseconds.

    Accounts for speed adjustments and transition overlaps between
    adjacent segments.

    Args:
        segments: Ordered list of EDL segments.

    Returns:
        Total output duration in milliseconds.
    """
    if not segments:
        return 0

    # Find the maximum extent of the output timeline
    max_end = 0
    for seg in segments:
        seg_end = seg.output_start_ms + seg.output_duration_ms
        if seg_end > max_end:
            max_end = seg_end

    return max_end
