"""Universal Clone Trainer — train identity models from any ClipCannon project.

Creates a clone model for ANY person from their ingested video project.
Uses the meaning-aware pipeline that understands what each embedding space
represents, producing avatar control signals that match behavioral intent.

Usage:
    # Train from pre-extracted embeddings (preferred)
    python -m phoenix.clone.universal_trainer --npz ~/.clipcannon/models/santa/embeddings/all_embeddings.npz --name santa

    # Train from a ClipCannon project (looks for embeddings in project dir)
    python -m phoenix.clone.universal_trainer --project proj_2ea7221d --name santa
"""
from __future__ import annotations

import gc
import json
import logging
import os
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from phoenix.clone.meaning_trainer import TrainingConfig, train_meaning_aware

logger = logging.getLogger(__name__)

MODELS_DIR = os.path.expanduser("~/.clipcannon/models")
PROJECTS_DIR = os.path.expanduser("~/.clipcannon/projects")


def find_embeddings_npz(
    project_id: str | None = None,
    clone_name: str | None = None,
) -> str | None:
    """Locate the embeddings NPZ file for a project or clone.

    Searches in order:
    1. ~/.clipcannon/models/{clone_name}/embeddings/all_embeddings.npz
    2. ~/.clipcannon/projects/{project_id}/embeddings/all_embeddings.npz

    Returns:
        Path to NPZ file or None.
    """
    candidates = []
    if clone_name:
        candidates.append(
            os.path.join(MODELS_DIR, clone_name, "embeddings", "all_embeddings.npz")
        )
    if project_id:
        candidates.append(
            os.path.join(PROJECTS_DIR, project_id, "embeddings", "all_embeddings.npz")
        )

    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def train_clone(
    clone_name: str,
    npz_path: str | None = None,
    project_id: str | None = None,
    epochs: int = 500,
    batch_size: int = 64,
    lr: float = 5e-4,
    device: str = "cuda",
    semantic_weight: float = 0.3,
    cross_modal_weight: float = 0.2,
) -> dict:
    """Train a complete clone model using meaning-aware pipeline.

    Args:
        clone_name: Name for the clone (e.g., "santa", "chris").
        npz_path: Explicit path to all_embeddings.npz.
        project_id: ClipCannon project ID (used to find NPZ).
        epochs: Training epochs.
        batch_size: Batch size.
        lr: Learning rate.
        device: "cuda" or "cpu".
        semantic_weight: Weight for semantic consistency loss.
        cross_modal_weight: Weight for cross-modal coherence loss.

    Returns:
        Dict with training results and model path.
    """
    # Find NPZ
    if not npz_path:
        npz_path = find_embeddings_npz(project_id, clone_name)
    if not npz_path or not os.path.exists(npz_path):
        raise FileNotFoundError(
            f"No embeddings found. Provide --npz or ensure "
            f"~/.clipcannon/models/{clone_name}/embeddings/all_embeddings.npz exists."
        )

    save_dir = os.path.join(MODELS_DIR, clone_name)

    config = TrainingConfig(
        npz_path=npz_path,
        save_dir=save_dir,
        clone_name=clone_name,
        epochs=epochs,
        batch_size=batch_size,
        lr=lr,
        device=device,
        geometric_weight=1.0,
        semantic_weight=semantic_weight,
        cross_modal_weight=cross_modal_weight,
    )

    result = train_meaning_aware(config)

    # Save human-readable metadata
    meta_path = os.path.join(save_dir, "metadata.json")
    with open(meta_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    # Cleanup
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # Optional: Train Gaussian avatar if FLAME params exist
    flame_params_path = os.path.join(save_dir, "flame_params.npz")
    gaussian_model_path = os.path.join(save_dir, "gaussian_avatar.pt")
    if os.path.exists(flame_params_path):
        logger.info("Training Gaussian avatar...")
        try:
            from phoenix.render.gaussian_trainer import GaussianTrainer
            g_trainer = GaussianTrainer(
                flame_params_path=flame_params_path,
                output_path=gaussian_model_path,
                num_iters=5000,
                batch_size=4,
                tex_size=128,
            )
            g_trainer.train()
            result["gaussian_avatar"] = gaussian_model_path
        except Exception as e:
            logger.warning("Gaussian avatar training failed: %s", e)

    return result


def main() -> None:
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Universal Clone Trainer")
    parser.add_argument("--npz", type=str, help="Path to all_embeddings.npz")
    parser.add_argument("--project", type=str, help="ClipCannon project ID")
    parser.add_argument("--name", type=str, required=True, help="Clone name")
    parser.add_argument("--epochs", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=5e-4)
    parser.add_argument("--semantic-weight", type=float, default=0.3)
    parser.add_argument("--cross-modal-weight", type=float, default=0.2)
    args = parser.parse_args()

    npz = args.npz
    if npz:
        npz = os.path.expanduser(npz)

    result = train_clone(
        clone_name=args.name,
        npz_path=npz,
        project_id=args.project,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        semantic_weight=args.semantic_weight,
        cross_modal_weight=args.cross_modal_weight,
    )

    print(f"\n{'=' * 50}")
    print(f"  Clone '{result['clone_name']}' trained successfully!")
    print(f"  Samples: {result['training_samples']}")
    print(f"  Parameters: {result['param_count']:,}")
    print(f"  Best loss: {result['best_loss']:.6f}")
    print(f"  Time: {result['total_time_s']}s")
    print(f"  Model: {result['model_path']}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
