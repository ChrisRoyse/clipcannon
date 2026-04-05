"""Training script for the Clone Model.

Uses the meaning-aware pipeline that understands what each embedding space
represents. Instead of blind MSE on blendshapes, the model learns to produce
avatar control signals that are semantically coherent across modalities.

Usage:
    python -m phoenix.clone.train --npz ~/.clipcannon/models/santa/embeddings/all_embeddings.npz
    python -m phoenix.clone.train --name santa  # auto-discovers NPZ
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from phoenix.clone.meaning_trainer import TrainingConfig, train_meaning_aware

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Train Clone Model (meaning-aware)")
    parser.add_argument(
        "--npz", type=str,
        default="~/.clipcannon/models/santa/embeddings/all_embeddings.npz",
        help="Path to all_embeddings.npz",
    )
    parser.add_argument("--name", type=str, default="santa", help="Clone name")
    parser.add_argument("--epochs", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=5e-4)
    parser.add_argument("--save-dir", type=str, default="")
    parser.add_argument("--semantic-weight", type=float, default=0.3)
    parser.add_argument("--cross-modal-weight", type=float, default=0.2)
    args = parser.parse_args()

    config = TrainingConfig(
        npz_path=os.path.expanduser(args.npz),
        save_dir=args.save_dir,
        clone_name=args.name,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        semantic_weight=args.semantic_weight,
        cross_modal_weight=args.cross_modal_weight,
    )

    result = train_meaning_aware(config)
    logger.info("Done! Model at %s", result["model_path"])


if __name__ == "__main__":
    main()
