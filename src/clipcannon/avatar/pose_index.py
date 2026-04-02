"""Pose indexer for RAD-NeRF semantic gesture control.

Analyzes training video frames to classify body poses and create
a searchable pose atlas. The AI selects poses based on script
semantics, and RAD-NeRF renders with the selected pose sequence.

This bridges ClipCannon's semantic understanding (emotion, prosody,
beats, narrative) with RAD-NeRF's pose-driven rendering.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Pose categories based on common talking-head body language
POSE_CATEGORIES = {
    "neutral_idle": "Relaxed sitting, minimal movement",
    "leaning_forward": "Engaged, leaning toward camera",
    "leaning_back": "Relaxed, leaning away",
    "emphatic_gesture": "Wide movement, emphasis with hands/body",
    "pointing": "Direct address, pointing or gesturing at viewer",
    "nodding": "Head nodding, agreement",
    "head_shake": "Head movement side to side",
    "thinking_pause": "Slight pause, head tilt, contemplative",
    "energetic": "High energy, fast movement, animated",
    "calm_steady": "Low energy, measured, authoritative",
}


def build_pose_atlas(
    transforms_path: Path,
    transcript_words: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Build a pose atlas from RAD-NeRF training transforms.

    Reads the head pose parameters from transforms_train.json and
    classifies each frame's body language based on pose dynamics.

    Args:
        transforms_path: Path to transforms_train.json from RAD-NeRF preprocessing.
        transcript_words: Optional word-level transcript for context tagging.

    Returns:
        List of pose entries with classifications.
    """
    with open(transforms_path, encoding="utf-8") as f:
        transforms = json.load(f)

    frames = transforms.get("frames", [])
    if not frames:
        return []

    # Extract head pose parameters per frame
    poses: list[dict[str, object]] = []

    for i, frame in enumerate(frames):
        # RAD-NeRF stores 4x4 transform matrix per frame
        matrix = np.array(frame.get("transform_matrix", np.eye(4).tolist()))

        # Extract translation (head position)
        head_x = float(matrix[0][3])
        head_y = float(matrix[1][3])
        head_z = float(matrix[2][3])

        # Extract rotation (simplified: use euler angle approximation)
        head_rotation = float(np.arctan2(matrix[1][0], matrix[0][0]))

        timestamp_ms = int(i * 40)  # 25fps = 40ms per frame

        poses.append({
            "frame_id": i,
            "timestamp_ms": timestamp_ms,
            "head_x": round(head_x, 4),
            "head_y": round(head_y, 4),
            "head_z": round(head_z, 4),
            "head_rotation": round(head_rotation, 4),
        })

    # Compute motion dynamics (velocity between consecutive frames)
    for i in range(1, len(poses)):
        prev = poses[i - 1]
        curr = poses[i]
        dx = float(curr["head_x"]) - float(prev["head_x"])
        dy = float(curr["head_y"]) - float(prev["head_y"])
        motion = np.sqrt(dx * dx + dy * dy)
        curr["motion_magnitude"] = round(float(motion), 6)

    if poses:
        poses[0]["motion_magnitude"] = poses[1].get("motion_magnitude", 0) if len(poses) > 1 else 0

    # Classify energy levels and pose categories
    motions = [float(p.get("motion_magnitude", 0)) for p in poses]
    if motions:
        motion_arr = np.array(motions)
        p25 = np.percentile(motion_arr, 25)
        p75 = np.percentile(motion_arr, 75)

        mean_y = float(np.mean([float(pp["head_y"]) for pp in poses]))

        for p in poses:
            m = float(p.get("motion_magnitude", 0))
            if m > p75:
                p["energy_level"] = "high"
                p["pose_category"] = "energetic"
            elif m < p25:
                p["energy_level"] = "low"
                p["pose_category"] = "calm_steady"
            else:
                p["energy_level"] = "medium"
                p["pose_category"] = "neutral_idle"

            # Detect transitions (large motion between frames)
            p["is_transition"] = 1 if m > p75 * 1.5 else 0

            # Detect leaning from head position
            hy = float(p.get("head_y", 0))
            if hy > mean_y + 0.01:
                p["pose_category"] = "leaning_forward"
            elif hy < mean_y - 0.01:
                p["pose_category"] = "leaning_back"

    # Tag with transcript text if available
    if transcript_words:
        for p in poses:
            ts = int(p["timestamp_ms"])
            matching_words = [
                str(w["word"]) for w in transcript_words
                if int(w["start_ms"]) <= ts <= int(w["end_ms"])
            ]
            p["transcript_text"] = " ".join(matching_words)

    return poses


def find_pose_range(
    poses: list[dict[str, object]],
    target_energy: str = "medium",
    target_category: str | None = None,
    min_duration_frames: int = 25,
) -> tuple[int, int] | None:
    """Find a contiguous range of frames matching the target criteria.

    Args:
        poses: The pose atlas.
        target_energy: "low", "medium", or "high".
        target_category: Specific pose category or None for any.
        min_duration_frames: Minimum number of contiguous frames.

    Returns:
        (start_frame, end_frame) tuple or None if no match.
    """
    best_start = None
    best_length = 0
    current_start = None
    current_length = 0

    for p in poses:
        energy_ok = p.get("energy_level") == target_energy
        category_ok = target_category is None or p.get("pose_category") == target_category

        if energy_ok and category_ok:
            if current_start is None:
                current_start = int(p["frame_id"])
            current_length += 1
        else:
            if current_length > best_length:
                best_length = current_length
                best_start = current_start
            current_start = None
            current_length = 0

    if current_length > best_length:
        best_length = current_length
        best_start = current_start

    if best_start is not None and best_length >= min_duration_frames:
        return (best_start, best_start + best_length)

    return None


def build_pose_timeline(
    poses: list[dict[str, object]],
    script_segments: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Build a pose timeline that maps script segments to pose ranges.

    The AI provides script_segments with semantic annotations:
    [
        {"text": "Ninety-seven percent!", "start_ms": 0, "end_ms": 3000,
         "energy": "high", "gesture": "emphatic"},
        {"text": "Here's what it does.", "start_ms": 3000, "end_ms": 8000,
         "energy": "medium", "gesture": "neutral"},
        ...
    ]

    This function finds the best matching pose range for each segment.

    Args:
        poses: The pose atlas.
        script_segments: AI-annotated script with energy/gesture tags.

    Returns:
        List of pose assignments per segment.
    """
    timeline: list[dict[str, object]] = []

    for seg in script_segments:
        energy = str(seg.get("energy", "medium"))
        raw_gesture = seg.get("gesture")
        gesture = str(raw_gesture) if raw_gesture is not None else None
        duration_ms = int(seg.get("end_ms", 0)) - int(seg.get("start_ms", 0))
        min_frames = max(10, duration_ms // 40)  # 25fps

        # Find best matching pose range
        best_range = None

        # Try exact category match first
        if gesture:
            best_range = find_pose_range(
                poses, energy, gesture, min_frames,
            )

        # Fall back to energy-only match
        if best_range is None:
            best_range = find_pose_range(
                poses, energy, None, min_frames,
            )

        # Fall back to any available range
        if best_range is None:
            best_range = find_pose_range(
                poses, "medium", None, min_frames,
            )

        if best_range is None:
            best_range = (0, min(len(poses), min_frames))

        timeline.append({
            "text": str(seg.get("text", "")),
            "start_ms": int(seg.get("start_ms", 0)),
            "end_ms": int(seg.get("end_ms", 0)),
            "pose_start_frame": best_range[0],
            "pose_end_frame": best_range[1],
            "energy": energy,
            "gesture": gesture,
        })

    return timeline


def export_pose_sequence(
    timeline: list[dict[str, object]],
    output_path: Path,
    fps: int = 25,
) -> Path:
    """Export a pose sequence file for RAD-NeRF inference.

    Converts the timeline into a frame-by-frame data_range mapping
    that RAD-NeRF can use during inference.

    Args:
        timeline: Pose timeline from build_pose_timeline.
        output_path: Where to save the pose sequence.
        fps: Target frame rate.

    Returns:
        Path to the exported sequence file.
    """
    sequence: list[dict[str, int]] = []

    for seg in timeline:
        start_ms = int(seg["start_ms"])
        end_ms = int(seg["end_ms"])
        pose_start = int(seg["pose_start_frame"])
        pose_end = int(seg["pose_end_frame"])

        n_output_frames = (end_ms - start_ms) * fps // 1000
        n_pose_frames = pose_end - pose_start

        for i in range(n_output_frames):
            # Map output frame to pose frame (with wrapping)
            pose_frame = pose_start + (i % n_pose_frames)
            sequence.append({
                "output_frame": len(sequence),
                "pose_frame": pose_frame,
            })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sequence, f, indent=2)

    logger.info("Exported pose sequence: %d frames to %s", len(sequence), output_path)
    return output_path
