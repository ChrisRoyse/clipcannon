"""Shared frame utilities for ClipCannon pipeline stages.

Common helpers for working with extracted frame files.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def frame_timestamp_ms(frame_path: Path, fps: int) -> int:
    """Compute timestamp in ms from frame filename and extraction fps.

    Args:
        frame_path: Path like frame_000001.jpg (1-indexed).
        fps: Frame extraction rate (e.g. 2).

    Returns:
        Timestamp in milliseconds.
    """
    frame_number = int(frame_path.stem.split("_")[1])
    return int((frame_number - 1) * 1000 / fps)
