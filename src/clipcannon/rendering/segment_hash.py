"""Deterministic content hashing for rendered segments.

Computes a SHA-256 hash from all factors that affect the rendered
output of a segment. Used by the segment render cache to detect
unchanged segments and skip re-rendering.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clipcannon.editing.edl import (
        CanvasSpec,
        ColorSpec,
        OverlaySpec,
        SegmentSpec,
    )


def compute_segment_hash(
    source_sha256: str,
    segment: SegmentSpec,
    profile_name: str,
    canvas: CanvasSpec | None = None,
    global_color: ColorSpec | None = None,
    overlays: list[OverlaySpec] | None = None,
) -> str:
    """Compute a deterministic content hash for a rendered segment.

    Includes ALL factors that affect the rendered output: source
    identity, time range, speed, per-segment canvas/motion/color,
    global canvas/color fallbacks, encoding profile, and overlays
    that fall within this segment's time range.

    Args:
        source_sha256: SHA-256 hash of the source video file.
        segment: The SegmentSpec to hash.
        profile_name: Name of the encoding profile (affects output).
        canvas: Global CanvasSpec (used when segment has no override).
        global_color: Global ColorSpec (used when segment has no
            per-segment color override).
        overlays: Overlays that fall within this segment's output
            time range (already remapped to local times).

    Returns:
        Hex digest of the SHA-256 hash.
    """
    hash_input: dict[str, object] = {
        "source_sha256": source_sha256,
        "source_start_ms": segment.source_start_ms,
        "source_end_ms": segment.source_end_ms,
        "speed": segment.speed,
        "profile_name": profile_name,
    }

    # Per-segment canvas override
    if segment.canvas is not None:
        hash_input["segment_canvas"] = segment.canvas.model_dump()
    elif canvas is not None:
        hash_input["global_canvas"] = canvas.model_dump()

    # Per-segment motion
    if segment.motion is not None:
        hash_input["motion"] = segment.motion.model_dump()

    # Per-segment color override, or global fallback
    if segment.color is not None:
        hash_input["segment_color"] = segment.color.model_dump()
    elif global_color is not None:
        hash_input["global_color"] = global_color.model_dump()

    # Transitions
    if segment.transition_in is not None:
        hash_input["transition_in"] = segment.transition_in.model_dump()
    if segment.transition_out is not None:
        hash_input["transition_out"] = segment.transition_out.model_dump()

    # Overlays within this segment's time range
    if overlays:
        hash_input["overlays"] = [
            ov.model_dump() for ov in overlays
        ]

    canonical = json.dumps(hash_input, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
