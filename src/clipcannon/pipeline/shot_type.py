"""Shot type classification pipeline stage for ClipCannon.

Uses SigLIP zero-shot classification to identify shot types from
scene key frames. Classifies into: extreme_closeup, closeup, medium,
wide, establishing. Provides crop recommendations for vertical video.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import execute, fetch_all
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_string,
)

if TYPE_CHECKING:
    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)

OPERATION = "shot_type_classification"
STAGE = "siglip_zero_shot"
SIGLIP_MODEL_ID = "google/siglip-so400m-patch14-384"

# Zero-shot classification prompts mapped to shot types
SHOT_PROMPTS: list[tuple[str, str]] = [
    ("an extreme close-up shot of a face", "extreme_closeup"),
    ("a close-up shot", "closeup"),
    ("a medium shot showing waist up", "medium"),
    ("a wide shot showing full body", "wide"),
    ("an establishing shot of a location", "establishing"),
]

# Crop recommendations per shot type
CROP_RECOMMENDATIONS: dict[str, str] = {
    "extreme_closeup": "safe_for_vertical",
    "closeup": "safe_for_vertical",
    "medium": "needs_reframe",
    "wide": "keep_landscape",
    "establishing": "keep_landscape",
}


def _classify_shot_types(
    key_frame_paths: list[str],
    hf_token: str | None,
    device: str,
) -> list[tuple[str, float]]:
    """Classify shot types for key frames using SigLIP zero-shot.

    Args:
        key_frame_paths: Paths to scene key frame images.
        hf_token: HuggingFace API token.
        device: Torch device string.

    Returns:
        List of (shot_type, confidence) tuples for each key frame.
    """
    import torch
    from PIL import Image
    from transformers import AutoModel, AutoProcessor

    if hf_token:
        os.environ["HF_TOKEN"] = hf_token
        os.environ["HUGGING_FACE_HUB_TOKEN"] = hf_token

    logger.info("Loading SigLIP model for shot type classification")
    processor = AutoProcessor.from_pretrained(SIGLIP_MODEL_ID)
    model = AutoModel.from_pretrained(SIGLIP_MODEL_ID)

    if device != "cpu" and torch.cuda.is_available():
        model = model.to(device)
    else:
        device = "cpu"

    model.eval()

    text_prompts = [prompt for prompt, _ in SHOT_PROMPTS]
    shot_labels = [label for _, label in SHOT_PROMPTS]

    results: list[tuple[str, float]] = []

    for frame_path in key_frame_paths:
        try:
            image = Image.open(frame_path).convert("RGB")

            inputs = processor(
                text=text_prompts,
                images=image,
                return_tensors="pt",
                padding=True,
            )
            inputs = {k: v.to(device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = model(**inputs)

            # Get image-text similarity scores
            logits = outputs.logits_per_image[0]
            probs = torch.softmax(logits, dim=0)

            best_idx = int(torch.argmax(probs).item())
            best_label = shot_labels[best_idx]
            best_conf = float(probs[best_idx].item())

            results.append((best_label, round(best_conf, 4)))

        except Exception as exc:
            logger.warning(
                "Shot type classification failed for %s: %s",
                frame_path,
                exc,
            )
            results.append(("medium", 0.0))

    return results


async def run_shot_type(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute shot type classification on scene key frames.

    For each scene, classifies the key frame into a shot type and
    computes a crop recommendation for vertical video.

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
        device = str(config.get("gpu.device"))
        # Models are pre-cached locally. No HF token needed at runtime.
        hf_token = os.environ.get("HF_TOKEN")

        # Fetch scenes with key frames
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            scenes = fetch_all(
                conn,
                "SELECT scene_id, key_frame_path FROM scenes "
                "WHERE project_id = ? ORDER BY start_ms",
                (project_id,),
            )
        finally:
            conn.close()

        if not scenes:
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message="No scenes found for shot type classification",
            )

        # Collect key frame paths
        scene_ids: list[int] = []
        key_frame_paths: list[str] = []
        for scene in scenes:
            sid = int(scene["scene_id"])  # type: ignore[arg-type]
            kfp = str(scene["key_frame_path"])
            if Path(kfp).exists():
                scene_ids.append(sid)
                key_frame_paths.append(kfp)
            else:
                logger.warning(
                    "Key frame not found for scene %d: %s",
                    sid,
                    kfp,
                )

        if not key_frame_paths:
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message="No valid key frames found",
            )

        logger.info(
            "Classifying shot types for %d scenes",
            len(key_frame_paths),
        )

        # Run classification in thread pool
        classifications = await asyncio.to_thread(
            _classify_shot_types,
            key_frame_paths,
            hf_token,
            device,
        )

        # Update scenes with shot type info
        conn = get_connection(db_path, enable_vec=False, dict_rows=True)
        try:
            for scene_id, (shot_type, confidence) in zip(
                scene_ids,
                classifications,
                strict=False,
            ):
                crop_rec = CROP_RECOMMENDATIONS.get(shot_type, "needs_reframe")
                execute(
                    conn,
                    "UPDATE scenes SET shot_type = ?, "
                    "shot_type_confidence = ?, crop_recommendation = ? "
                    "WHERE scene_id = ?",
                    (shot_type, confidence, crop_rec, scene_id),
                )
            conn.commit()
            logger.info("Updated %d scenes with shot type info", len(scene_ids))
        finally:
            conn.close()

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Summary of shot type distribution
        type_counts: dict[str, int] = {}
        for shot_type, _ in classifications:
            type_counts[shot_type] = type_counts.get(shot_type, 0) + 1

        content_hash = sha256_string(
            f"shot_types:{len(classifications)},{type_counts}",
        )

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path=str(project_dir / "frames"),
                sha256=sha256_string(
                    "\n".join(key_frame_paths),
                ),
            ),
            output_info=OutputInfo(
                sha256=content_hash,
                record_count=len(classifications),
            ),
            model_info=ModelInfo(
                name="siglip-so400m-patch14-384",
                version="google/siglip-so400m-patch14-384",
                parameters={
                    "prompts_count": len(SHOT_PROMPTS),
                    "scenes_classified": len(classifications),
                },
            ),
            execution_info=ExecutionInfo(
                duration_ms=elapsed_ms,
                gpu_device=device,
            ),
            parent_record_id=None,
            description=(
                f"Shot type classification: {len(classifications)} scenes, "
                f"distribution={type_counts}"
            ),
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Shot type classification failed: %s", error_msg)
        return StageResult(
            success=False,
            operation=OPERATION,
            error_message=error_msg,
            duration_ms=elapsed_ms,
        )
