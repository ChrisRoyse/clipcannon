"""SigLIP visual embedding and scene detection pipeline stage.

Loads the SigLIP-SO400M model to compute 1152-dim visual embeddings
for all extracted frames, then detects scene boundaries by measuring
cosine similarity between consecutive frame embeddings.

Scenes are defined by boundaries where similarity drops below
SCENE_THRESHOLD (0.75). Each scene records its key frame, average
visual similarity, and dominant colors.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import time
from collections import Counter
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, execute
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

logger = logging.getLogger(__name__)

OPERATION = "visual_embedding"
STAGE = "siglip_visual"
SIGLIP_MODEL_ID = "google/siglip-so400m-patch14-384"
EMBEDDING_DIM = 1152
SCENE_THRESHOLD = 0.75
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


def _frame_timestamp_ms(frame_path: Path, fps: int) -> int:
    """Compute timestamp in ms from frame filename and extraction fps.

    Args:
        frame_path: Path like frame_000001.jpg (1-indexed).
        fps: Frame extraction rate (e.g. 2).

    Returns:
        Timestamp in milliseconds.
    """
    stem = frame_path.stem  # "frame_000001"
    frame_number = int(stem.split("_")[1])  # 1-indexed
    return int((frame_number - 1) * 1000 / fps)


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        vec_a: First embedding vector.
        vec_b: Second embedding vector.

    Returns:
        Cosine similarity in range [-1, 1].
    """
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
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


def _load_and_embed_batch(
    frame_paths: list[Path],
    model: object,
    processor: object,
    device: str,
) -> list[list[float]]:
    """Load a batch of frames and compute SigLIP embeddings.

    Args:
        frame_paths: Paths to frame JPEG files.
        model: SigLIP model instance.
        processor: SigLIP processor instance.
        device: Torch device string.

    Returns:
        List of embedding vectors (each 1152-dim).
    """
    import torch
    from PIL import Image

    images = []
    for fp in frame_paths:
        img = Image.open(fp).convert("RGB")
        images.append(img)

    inputs = processor(images=images, return_tensors="pt", padding=True)
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model.get_image_features(**inputs)

    # Normalize embeddings
    embeddings = outputs / outputs.norm(dim=-1, keepdim=True)
    return embeddings.cpu().tolist()


def _run_embedding_pipeline(
    frame_paths: list[Path],
    batch_size: int,
    hf_token: str | None,
    device: str,
) -> list[list[float]]:
    """Run the full SigLIP embedding pipeline on all frames.

    Args:
        frame_paths: All frame paths to process.
        batch_size: Number of frames per batch.
        hf_token: HuggingFace API token for model download.
        device: Torch device string.

    Returns:
        List of embedding vectors for all frames.
    """
    import torch
    from transformers import AutoModel, AutoProcessor

    # Set HF token for model download
    if hf_token:
        os.environ["HF_TOKEN"] = hf_token
        os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token

    logger.info("Loading SigLIP model: %s", SIGLIP_MODEL_ID)
    processor = AutoProcessor.from_pretrained(SIGLIP_MODEL_ID)
    model = AutoModel.from_pretrained(SIGLIP_MODEL_ID)

    if device != "cpu" and torch.cuda.is_available():
        model = model.to(device)
    else:
        device = "cpu"

    model.eval()

    all_embeddings: list[list[float]] = []
    total_batches = (len(frame_paths) + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, len(frame_paths))
        batch_paths = frame_paths[start:end]

        logger.info(
            "Processing visual embedding batch %d/%d (%d frames)",
            batch_idx + 1, total_batches, len(batch_paths),
        )

        batch_embeddings = _load_and_embed_batch(
            batch_paths, model, processor, device,
        )
        all_embeddings.extend(batch_embeddings)

    logger.info("Computed %d visual embeddings", len(all_embeddings))
    return all_embeddings


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

    scenes: list[dict[str, int | float | str]] = []
    for scene_idx in range(len(boundaries)):
        start_frame_idx = boundaries[scene_idx]
        if scene_idx + 1 < len(boundaries):
            end_frame_idx = boundaries[scene_idx + 1] - 1
        else:
            end_frame_idx = len(frame_paths) - 1

        start_ms = _frame_timestamp_ms(frame_paths[start_frame_idx], fps)
        end_ms = _frame_timestamp_ms(frame_paths[end_frame_idx], fps)

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

        scenes.append({
            "start_ms": start_ms,
            "end_ms": end_ms,
            "key_frame_path": key_frame_path,
            "key_frame_timestamp_ms": key_frame_ts,
            "visual_similarity_avg": round(sim_avg, 4),
            "dominant_colors": json.dumps(colors),
        })

    return scenes


async def run_visual_embed(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute SigLIP visual embedding and scene detection.

    Processes all extracted frames through SigLIP to produce 1152-dim
    embeddings, inserts them into vec_frames, detects scene boundaries,
    and inserts scene records.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    start_time = time.monotonic()

    try:
        frames_dir = project_dir / "frames"
        frame_paths = _get_sorted_frames(frames_dir)
        extraction_fps = int(config.get("processing.frame_extraction_fps"))
        batch_size = int(config.get("processing.batch_size_visual"))
        threshold = float(config.get("processing.scene_change_threshold"))
        device = str(config.get("gpu.device"))
        hf_token = os.environ.get("HF_TOKEN", os.environ.get(
            "HUGGING_FACE_HUB_TOKEN", "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",
        ))

        logger.info(
            "Starting visual embedding: %d frames, batch_size=%d, device=%s",
            len(frame_paths), batch_size, device,
        )

        # Run model inference in thread pool
        embeddings = await asyncio.to_thread(
            _run_embedding_pipeline,
            frame_paths, batch_size, hf_token, device,
        )

        # Insert embeddings into vec_frames
        conn = get_connection(db_path, enable_vec=True, dict_rows=True)
        try:
            vec_rows: list[tuple[object, ...]] = []
            for idx, (fp, emb) in enumerate(zip(frame_paths, embeddings)):
                ts_ms = _frame_timestamp_ms(fp, extraction_fps)
                vec_rows.append((
                    idx + 1,
                    project_id,
                    ts_ms,
                    str(fp),
                    _serialize_embedding(emb),
                ))

            batch_insert(
                conn,
                "vec_frames",
                ["frame_id", "project_id", "timestamp_ms", "frame_path",
                 "visual_embedding"],
                vec_rows,
            )
            conn.commit()
            logger.info("Inserted %d frame embeddings into vec_frames", len(vec_rows))
        finally:
            conn.close()

        # Detect scenes
        scenes = _detect_scenes(frame_paths, embeddings, extraction_fps, threshold)
        logger.info("Detected %d scenes (threshold=%.2f)", len(scenes), threshold)

        # Insert scenes
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            scene_rows: list[tuple[object, ...]] = []
            for scene in scenes:
                scene_rows.append((
                    project_id,
                    scene["start_ms"],
                    scene["end_ms"],
                    scene["key_frame_path"],
                    scene["key_frame_timestamp_ms"],
                    scene["visual_similarity_avg"],
                    scene["dominant_colors"],
                ))

            batch_insert(
                conn,
                "scenes",
                ["project_id", "start_ms", "end_ms", "key_frame_path",
                 "key_frame_timestamp_ms", "visual_similarity_avg",
                 "dominant_colors"],
                scene_rows,
            )
            conn.commit()
            logger.info("Inserted %d scenes", len(scene_rows))
        finally:
            conn.close()

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Build content hash for provenance
        content_repr = f"frames:{len(frame_paths)},scenes:{len(scenes)}"
        content_hash = sha256_string(content_repr)

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path=str(frames_dir),
                sha256=sha256_string(
                    "\n".join(f.name for f in frame_paths),
                ),
            ),
            output_info=OutputInfo(
                sha256=content_hash,
                record_count=len(frame_paths),
            ),
            model_info=ModelInfo(
                name="siglip-so400m-patch14-384",
                version="google/siglip-so400m-patch14-384",
                parameters={
                    "embedding_dim": EMBEDDING_DIM,
                    "batch_size": batch_size,
                    "scene_threshold": threshold,
                },
            ),
            execution_info=ExecutionInfo(
                duration_ms=elapsed_ms,
                gpu_device=device,
            ),
            parent_record_id=None,
            description=(
                f"Computed {len(frame_paths)} SigLIP embeddings, "
                f"detected {len(scenes)} scenes"
            ),
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )

    except PipelineError:
        raise
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Visual embedding failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
            duration_ms=elapsed_ms,
        )
