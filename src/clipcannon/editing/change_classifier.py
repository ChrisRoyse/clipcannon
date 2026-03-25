"""Change impact classification for iterative editing.

Compares two EDL snapshots (old vs new) and produces a RenderHint
describing exactly what needs re-rendering. This enables the renderer
to skip unchanged segments and avoid redundant caption/audio work.

Pure functions -- no DB access, no side effects.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from clipcannon.editing.edl import EditDecisionList, SegmentSpec


class RenderHint(BaseModel):
    """Describes what needs re-rendering after an edit modification.

    Returned by classify_changes() and stored on the edit row so the
    render tool can pass it to the renderer for optimisation.
    """

    segments_invalidated: list[int] = Field(
        default_factory=list,
        description="1-based segment IDs to re-render.",
    )
    all_segments_invalidated: bool = Field(
        default=False,
        description="True if all segments need re-rendering.",
    )
    captions_invalidated: bool = Field(
        default=False,
        description="True if caption burn-in needed.",
    )
    audio_invalidated: bool = Field(
        default=False,
        description="True if audio re-mix needed.",
    )


def _segments_match_by_id(
    old_edl: EditDecisionList, new_edl: EditDecisionList,
) -> bool:
    """Return True if old and new EDLs have the same segment IDs in order."""
    if len(old_edl.segments) != len(new_edl.segments):
        return False
    return all(
        o.segment_id == n.segment_id
        for o, n in zip(old_edl.segments, new_edl.segments)
    )


def _timing_changed(old: SegmentSpec, new: SegmentSpec) -> bool:
    """Return True if any timing field differs between two segments."""
    return (
        old.source_start_ms != new.source_start_ms
        or old.source_end_ms != new.source_end_ms
        or old.output_start_ms != new.output_start_ms
        or old.speed != new.speed
        or old.transition_in != new.transition_in
        or old.transition_out != new.transition_out
    )


def _overlays_changed_for_segment(
    old_edl: EditDecisionList, new_edl: EditDecisionList, segment_id: int,
) -> bool:
    """Return True if overlays affecting *segment_id* differ between EDLs."""
    def _seg_range(edl: EditDecisionList, sid: int) -> tuple[int, int] | None:
        for seg in edl.segments:
            if seg.segment_id == sid:
                return seg.output_start_ms, seg.output_start_ms + seg.output_duration_ms
        return None

    def _overlapping(edl: EditDecisionList, start: int, end: int) -> list[dict[str, object]]:
        return [
            ov.model_dump() for ov in edl.overlays
            if ov.start_ms < end and ov.end_ms > start
        ]

    old_r = _seg_range(old_edl, segment_id)
    new_r = _seg_range(new_edl, segment_id)
    if old_r is None or new_r is None:
        return True
    return _overlapping(old_edl, *old_r) != _overlapping(new_edl, *new_r)


def classify_changes(
    old_edl: EditDecisionList,
    new_edl: EditDecisionList,
) -> RenderHint:
    """Classify differences between two EDL snapshots.

    Compares every aspect of the old and new EDLs and produces a
    RenderHint telling the renderer exactly what work is needed.

    Classification matrix:
    - name only: nothing invalidated
    - captions (style, enabled): captions_invalidated only
    - global color: all segments + captions
    - per-segment color (seg N): [N] + captions
    - segment timing/speed/order: changed IDs + captions + audio
    - segments added/removed: all + captions + audio
    - audio spec: audio only
    - overlays changed: affected segment IDs
    - canvas (global): all + captions
    - per-segment canvas (seg N): [N] + captions
    - motion changed (seg N): [N] only
    - metadata only: nothing invalidated

    Args:
        old_edl: The EDL snapshot before modification.
        new_edl: The EDL snapshot after modification.

    Returns:
        RenderHint describing what needs re-rendering.
    """
    hint = RenderHint()
    invalidated: set[int] = set()

    # 1. Segments added or removed => ALL invalidated
    if not _segments_match_by_id(old_edl, new_edl):
        hint.all_segments_invalidated = True
        hint.captions_invalidated = True
        hint.audio_invalidated = True
        return hint

    # 2. Global canvas changed => ALL segments + captions
    if old_edl.canvas != new_edl.canvas:
        hint.all_segments_invalidated = True
        hint.captions_invalidated = True

    # 3. Global color changed => ALL segments + captions
    if old_edl.color != new_edl.color:
        hint.all_segments_invalidated = True
        hint.captions_invalidated = True

    # 4. Crop changed => ALL segments + captions
    if old_edl.crop != new_edl.crop:
        hint.all_segments_invalidated = True
        hint.captions_invalidated = True

    # 5. Removals changed => ALL segments + captions
    if old_edl.removals != new_edl.removals:
        hint.all_segments_invalidated = True
        hint.captions_invalidated = True

    # 6. Per-segment comparison (skip if already all-invalidated)
    if not hint.all_segments_invalidated:
        for old_seg, new_seg in zip(old_edl.segments, new_edl.segments):
            sid = old_seg.segment_id

            if _timing_changed(old_seg, new_seg):
                invalidated.add(sid)
                hint.captions_invalidated = True
                hint.audio_invalidated = True

            if old_seg.color != new_seg.color:
                invalidated.add(sid)
                hint.captions_invalidated = True

            if old_seg.canvas != new_seg.canvas:
                invalidated.add(sid)
                hint.captions_invalidated = True

            if old_seg.motion != new_seg.motion:
                invalidated.add(sid)

        # Overlay comparison per-segment
        for seg in old_edl.segments:
            if _overlays_changed_for_segment(old_edl, new_edl, seg.segment_id):
                invalidated.add(seg.segment_id)

    # 7. Captions changed => captions_invalidated only
    if old_edl.captions != new_edl.captions:
        hint.captions_invalidated = True

    # 8. Audio spec changed => audio_invalidated only
    if old_edl.audio != new_edl.audio:
        hint.audio_invalidated = True

    # 9. Render settings changed => ALL segments
    if old_edl.render_settings != new_edl.render_settings:
        hint.all_segments_invalidated = True

    # 10. Name, metadata, status, timestamps -- no invalidation
    # (implicitly handled: no flags set for these changes)

    # Build the sorted segments_invalidated list
    if not hint.all_segments_invalidated:
        hint.segments_invalidated = sorted(invalidated)

    return hint
