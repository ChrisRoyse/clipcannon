"""Frame listing, colour extraction and scene detection for visual_embed."""

from __future__ import annotations

import json
import logging
import struct
from collections import Counter
from typing import TYPE_CHECKING

from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.frame_utils import frame_timestamp_ms

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

OPERATION = "visual_embedding"
STAGE = "siglip_visual"
SIGLIP_MODEL_ID = "google/siglip-so400m-patch14-384"
EMBEDDING_DIM = 1152
SCENE_THRESHOLD = 0.85
MAX_SCENE_DURATION_MS = 30000  # Force scene break after 30 seconds
BATCH_SIZE = 64
FRAME_RESIZE = 384


def _get_sorted_frames(frames_dir: Path) -> list[Path]:
    """Return sorted list of extracted frame files.

    Args:
        frames_dir: Directory containing frame_NNNNNN.jpg files.

    Returns:
        Sorted list of frame file paths.
    """
    frames = sorted(frames_dir.glob("frame_*.jpg"))
    if not frames:
        raise PipelineError(
            "No frames found for visual embedding",
            stage_name=STAGE,
            operation=OPERATION,
        )
    return frames


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        vec_a: First embedding vector.
        vec_b: Second embedding vector.

    Returns:
        Cosine similarity in range [-1, 1].
    """
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _extract_dominant_colors(frame_path: Path, num_colors: int = 5) -> list[str]:
    """Extract dominant colors from a frame image.

    Quantizes the image to a small palette and returns the most
    common colors as hex strings.

    Args:
        frame_path: Path to the JPEG frame.
        num_colors: Number of dominant colors to extract.

    Returns:
        List of hex color strings (e.g. ["#3a5f8c", "#e2d4b7"]).
    """
    try:
        from PIL import Image

        img = Image.open(frame_path).convert("RGB")
        # Resize small for speed
        img = img.resize((64, 64), Image.Resampling.LANCZOS)
        # Quantize to palette
        quantized = img.quantize(colors=num_colors, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette()
        if palette is None:
            return []

        # Count pixel frequency
        pixel_counts: Counter[int] = Counter(quantized.getdata())
        top_indices = [idx for idx, _ in pixel_counts.most_common(num_colors)]

        colors: list[str] = []
        for idx in top_indices:
            r = palette[idx * 3]
            g = palette[idx * 3 + 1]
            b = palette[idx * 3 + 2]
            colors.append(f"#{r:02x}{g:02x}{b:02x}")
        return colors
    except Exception as exc:
        logger.warning("Failed to extract dominant colors from %s: %s", frame_path, exc)
        return []


def _serialize_embedding(embedding: list[float]) -> bytes:
    """Serialize a float embedding to bytes for sqlite-vec.

    Args:
        embedding: List of float values.

    Returns:
        Packed binary representation.
    """
    return struct.pack(f"{len(embedding)}f", *embedding)


def _detect_scenes(
    frame_paths: list[Path],
    embeddings: list[list[float]],
    fps: int,
    threshold: float,
) -> list[dict[str, int | float | str]]:
    """Detect scene boundaries from consecutive frame similarity.

    Args:
        frame_paths: Ordered frame file paths.
        embeddings: Corresponding embedding vectors.
        fps: Frame extraction rate.
        threshold: Cosine similarity threshold for scene change.

    Returns:
        List of scene dictionaries with start_ms, end_ms, key_frame info.
    """
    if not frame_paths:
        return []

    # Compute pairwise similarities
    similarities: list[float] = []
    for i in range(1, len(embeddings)):
        sim = _cosine_similarity(embeddings[i - 1], embeddings[i])
        similarities.append(sim)

    # Find scene boundaries (where similarity drops below threshold)
    boundaries: list[int] = [0]  # First frame is always a boundary
    for i, sim in enumerate(similarities):
        if sim < threshold:
            boundaries.append(i + 1)  # Index of the first frame in new scene
        else:
            # Force scene break if current scene exceeds max duration
            scene_start_ms = frame_timestamp_ms(frame_paths[boundaries[-1]], fps)
            current_ms = frame_timestamp_ms(frame_paths[i + 1], fps)
            if current_ms - scene_start_ms > MAX_SCENE_DURATION_MS:
                boundaries.append(i + 1)

    scenes: list[dict[str, int | float | str]] = []
    for scene_idx in range(len(boundaries)):
        start_frame_idx = boundaries[scene_idx]
        if scene_idx + 1 < len(boundaries):
            end_frame_idx = boundaries[scene_idx + 1] - 1
        else:
            end_frame_idx = len(frame_paths) - 1

        start_ms = frame_timestamp_ms(frame_paths[start_frame_idx], fps)
        end_ms = frame_timestamp_ms(frame_paths[end_frame_idx], fps)

        # Key frame is the first frame of the scene
        key_frame_path = str(frame_paths[start_frame_idx])
        key_frame_ts = start_ms

        # Compute average similarity within the scene
        scene_sims: list[float] = []
        for i in range(start_frame_idx, min(end_frame_idx, len(similarities))):
            scene_sims.append(similarities[i])
        sim_avg = sum(scene_sims) / len(scene_sims) if scene_sims else 1.0

        # Extract dominant colors from key frame
        colors = _extract_dominant_colors(frame_paths[start_frame_idx])

        scenes.append(
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "key_frame_path": key_frame_path,
                "key_frame_timestamp_ms": key_frame_ts,
                "visual_similarity_avg": round(sim_avg, 4),
                "dominant_colors": json.dumps(colors),
            }
        )

    return scenes
