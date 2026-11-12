"""SigLIP embedding computation for visual_embed."""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from clipcannon.pipeline.visual_embed_scenes import SIGLIP_MODEL_ID

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def _run_embedding_pipeline(
    frame_paths: list[Path],
    batch_size: int,
    hf_token: str | None,
    device: str,
) -> list[list[float]]:
    """Run the full SigLIP embedding pipeline on all frames via subprocess.

    Spawns a fresh Python subprocess to load and run the SigLIP model.
    This avoids HuggingFace transformers 4.57 meta tensor errors that
    occur when loading models in long-running MCP server processes.
    The model loads cleanly in a fresh process every time.

    Args:
        frame_paths: All frame paths to process.
        batch_size: Number of frames per batch.
        hf_token: HuggingFace API token for model download.
        device: Torch device string.

    Returns:
        List of embedding vectors for all frames.
    """
    import subprocess
    import tempfile

    # Use larger batches in subprocess — 32GB VRAM handles it fine
    subprocess_batch_size = 128

    # Worker script runs in a clean Python process with no inherited state.
    # All imports happen fresh, avoiding meta tensor corruption.
    worker_script = r'''
import json
import os
import sys
import time

def main():
    frame_list_path = sys.argv[1]
    device = sys.argv[2]
    batch_size = int(sys.argv[3])
    model_id = sys.argv[4]

    # Read frame paths
    with open(frame_list_path, "r") as f:
        frame_paths = [line.strip() for line in f if line.strip()]

    total_frames = len(frame_paths)
    print(f"[siglip-worker] {total_frames} frames, batch_size={batch_size}, device={device}", file=sys.stderr)

    import torch
    from transformers import AutoModel, AutoProcessor
    from PIL import Image

    print(f"[siglip-worker] Loading model: {model_id}", file=sys.stderr)
    t0 = time.monotonic()

    processor = AutoProcessor.from_pretrained(model_id)

    use_fp16 = device != "cpu" and torch.cuda.is_available()
    if use_fp16:
        torch.cuda.empty_cache()
        model = AutoModel.from_pretrained(
            model_id,
            torch_dtype=torch.float16,
        ).to(device)
        print(f"[siglip-worker] Model loaded FP16 on {device} in {time.monotonic()-t0:.1f}s", file=sys.stderr)
    else:
        model = AutoModel.from_pretrained(model_id)
        device = "cpu"
        print(f"[siglip-worker] Model loaded FP32 on CPU in {time.monotonic()-t0:.1f}s", file=sys.stderr)

    model.eval()

    all_embeddings = []
    total_batches = (total_frames + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, total_frames)
        batch_paths = frame_paths[start:end]

        images = []
        for fp in batch_paths:
            img = Image.open(fp).convert("RGB")
            images.append(img)

        inputs = processor(images=images, return_tensors="pt", padding=True)
        inputs = {
            k: v.to(device, dtype=torch.float16) if v.is_floating_point() else v.to(device)
            for k, v in inputs.items()
        }

        with torch.no_grad():
            outputs = model.get_image_features(**inputs)

        # transformers 5.x: get_image_features returns BaseModelOutputWithPooling.
        # .pooler_output is the [batch, 1152] pooled SigLIP embedding.
        if not hasattr(outputs, "pooler_output"):
            raise RuntimeError(
                f"SigLIP get_image_features returned unexpected type "
                f"{type(outputs).__name__!s}; expected object with .pooler_output "
                f"(transformers API surface changed)."
            )
        features = outputs.pooler_output
        embeddings = features / features.norm(dim=-1, keepdim=True)
        all_embeddings.extend(embeddings.cpu().tolist())

        print(
            f"[siglip-worker] Batch {batch_idx+1}/{total_batches} done ({len(all_embeddings)}/{total_frames} frames)",
            file=sys.stderr,
        )

    print(f"[siglip-worker] Complete: {len(all_embeddings)} embeddings in {time.monotonic()-t0:.1f}s", file=sys.stderr)

    # Output embeddings as JSON to stdout
    json.dump(all_embeddings, sys.stdout)

if __name__ == "__main__":
    main()
'''

    # Write frame paths to a temp file to avoid command-line length limits
    tmp_frame_list = None
    try:
        tmp_frame_list = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            prefix="siglip_frames_",
            delete=False,
        )
        for fp in frame_paths:
            tmp_frame_list.write(f"{fp}\n")
        tmp_frame_list.close()

        # Build environment for subprocess
        env = os.environ.copy()
        if hf_token:
            env["HF_TOKEN"] = hf_token
            env["HUGGING_FACE_HUB_TOKEN"] = hf_token

        logger.info(
            "Launching SigLIP subprocess: %d frames, batch_size=%d, device=%s",
            len(frame_paths),
            subprocess_batch_size,
            device,
        )

        proc = subprocess.run(
            [
                "python3", "-c", worker_script,
                tmp_frame_list.name,
                device,
                str(subprocess_batch_size),
                SIGLIP_MODEL_ID,
            ],
            capture_output=True,
            text=True,
            timeout=580,  # Just under the 600s stage timeout
            env=env,
        )

        # Log stderr (progress messages)
        if proc.stderr:
            for line in proc.stderr.strip().splitlines():
                logger.info("subprocess: %s", line)

        if proc.returncode != 0:
            raise RuntimeError(
                f"SigLIP subprocess failed (rc={proc.returncode}): "
                f"{proc.stderr[-500:] if proc.stderr else 'no stderr'}"
            )

        if not proc.stdout.strip():
            raise RuntimeError("SigLIP subprocess produced no output")

        all_embeddings: list[list[float]] = json.loads(proc.stdout)

        if len(all_embeddings) != len(frame_paths):
            raise RuntimeError(
                f"Embedding count mismatch: got {len(all_embeddings)}, "
                f"expected {len(frame_paths)}"
            )

        logger.info("Computed %d visual embeddings via subprocess", len(all_embeddings))
        return all_embeddings

    finally:
        # Clean up temp file
        if tmp_frame_list is not None:
            try:
                os.unlink(tmp_frame_list.name)
            except OSError:
                pass
