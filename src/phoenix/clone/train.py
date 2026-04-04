"""Training script for the Clone Model.

Stage 1: Supervised training on ground truth blendshapes.
  Loss = MSE(predicted_blendshapes, ground_truth_blendshapes)

Usage:
    python -m phoenix.clone.train --video /path/to/santa.mp4
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from phoenix.clone.model import CloneModel

logger = logging.getLogger(__name__)


def train_stage1(
    dataset: dict[str, torch.Tensor],
    epochs: int = 1000,
    batch_size: int = 128,
    lr: float = 1e-3,
    device: str = "cuda",
    save_path: str | None = None,
) -> CloneModel:
    """Stage 1: Supervised training on ground truth blendshapes.

    Args:
        dataset: Output from build_training_dataset().
        epochs: Number of training epochs.
        batch_size: Batch size.
        lr: Learning rate.
        device: "cuda" or "cpu".
        save_path: Where to save the trained model.

    Returns:
        Trained CloneModel.
    """
    n = dataset["n_samples"]
    logger.info("Stage 1 training: %d samples, %d epochs, batch=%d", n, epochs, batch_size)

    # Create model
    # Use only the embeddings we have data for
    model = CloneModel(
        embedding_dims={
            "prosody": 12,
            "emotion_scalars": 8,
        },
    )
    model = model.to(device)
    logger.info("Model: %.1fM params, device=%s", model.param_count / 1e6, device)

    # Prepare data
    prosody = dataset["prosody"].to(device)
    emotion = dataset["emotion_scalars"].to(device)
    gt = dataset["gt_blendshapes"].to(device)

    # Create simple dataloader
    ds = TensorDataset(prosody, emotion, gt)
    loader = DataLoader(ds, batch_size=batch_size, shuffle=True, drop_last=False)

    # Optimizer
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    # Loss: MSE on blendshapes + temporal smoothness
    mse_loss = nn.MSELoss()

    best_loss = float("inf")
    t_start = time.time()

    for epoch in range(epochs):
        model.train()
        epoch_loss = 0.0
        n_batches = 0

        for batch_prosody, batch_emotion, batch_gt in loader:
            optimizer.zero_grad()

            # Forward pass
            out = model(
                embeddings={
                    "prosody": batch_prosody,
                    "emotion_scalars": batch_emotion,
                },
                prosody_scalars=batch_prosody,
            )

            # Loss: MSE on blendshapes
            loss = mse_loss(out["blendshapes"], batch_gt)

            loss.backward()
            optimizer.step()

            epoch_loss += loss.item()
            n_batches += 1

        scheduler.step()
        avg_loss = epoch_loss / max(n_batches, 1)

        if avg_loss < best_loss:
            best_loss = avg_loss

        if (epoch + 1) % 100 == 0 or epoch == 0:
            elapsed = time.time() - t_start
            logger.info(
                "Epoch %d/%d: loss=%.6f, best=%.6f, lr=%.2e, time=%.1fs",
                epoch + 1, epochs, avg_loss, best_loss,
                scheduler.get_last_lr()[0], elapsed,
            )

    elapsed = time.time() - t_start
    logger.info("Training complete: %.1fs, final_loss=%.6f", elapsed, best_loss)

    # Save model
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        torch.save({
            "model_state_dict": model.state_dict(),
            "config": {
                "embedding_dims": {"prosody": 12, "emotion_scalars": 8},
                "param_count": model.param_count,
                "best_loss": best_loss,
                "epochs": epochs,
                "training_samples": n,
            },
        }, save_path)
        logger.info("Model saved to %s", save_path)

    return model


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    parser = argparse.ArgumentParser(description="Train Clone Model")
    parser.add_argument("--video", type=str, help="Source video path")
    parser.add_argument("--db", type=str, default="~/.clipcannon/projects/proj_2ea7221d/analysis.db")
    parser.add_argument("--epochs", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--fps", type=int, default=5, help="Frame extraction rate")
    parser.add_argument("--save", type=str, default="~/.clipcannon/models/santa_clone.pt")
    args = parser.parse_args()

    from phoenix.clone.data_pipeline import (
        build_training_dataset,
        extract_ground_truth_blendshapes,
        load_embeddings_from_db,
    )

    video = args.video or os.path.expanduser(
        "~/.clipcannon/projects/proj_2ea7221d/source/2026-04-03 04-23-11.mp4"
    )

    # Step 1: Extract ground truth blendshapes
    logger.info("Step 1: Extracting ground truth blendshapes...")
    blendshapes = extract_ground_truth_blendshapes(video, fps=args.fps)

    # Step 2: Load embeddings
    logger.info("Step 2: Loading embeddings from DB...")
    db_path = os.path.expanduser(args.db)
    embeddings = load_embeddings_from_db(db_path)

    # Step 3: Build dataset
    logger.info("Step 3: Building training dataset...")
    dataset = build_training_dataset(blendshapes, embeddings)

    # Step 4: Train
    logger.info("Step 4: Training...")
    model = train_stage1(
        dataset,
        epochs=args.epochs,
        batch_size=args.batch_size,
        save_path=os.path.expanduser(args.save),
    )

    logger.info("Done! Model at %s", os.path.expanduser(args.save))


if __name__ == "__main__":
    main()
