"""Universal Clone Trainer — train identity models from any ClipCannon project.

Creates a clone model for ANY person from their ingested video project.
Extracts all available embeddings, computes the full North Star constellation,
trains the multi-embedding transformer, and saves a deployable model.

Usage:
    # Train from a ClipCannon project
    python -m phoenix.clone.universal_trainer --project proj_2ea7221d --name santa

    # Train from a video file (auto-ingests first)
    python -m phoenix.clone.universal_trainer --video /path/to/video.mp4 --name person

    # List available projects
    python -m phoenix.clone.universal_trainer --list
"""
from __future__ import annotations

import gc
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from phoenix.clone.data_pipeline import (
    build_training_dataset,
    extract_ground_truth_blendshapes,
    load_embeddings_from_db,
)
from phoenix.clone.model import CloneModel
from phoenix.clone.north_star import (
    NorthStarContrastiveLoss,
    compute_north_star_constellation,
    compute_north_stars,
)

logger = logging.getLogger(__name__)

MODELS_DIR = os.path.expanduser("~/.clipcannon/models")
PROJECTS_DIR = os.path.expanduser("~/.clipcannon/projects")


def list_available_projects() -> list[dict]:
    """List all ingested ClipCannon projects with their metadata."""
    projects = []
    for proj_id in os.listdir(PROJECTS_DIR):
        db_path = os.path.join(PROJECTS_DIR, proj_id, "analysis.db")
        if not os.path.exists(db_path):
            continue
        try:
            db = sqlite3.connect(db_path)
            c = db.cursor()
            c.execute("SELECT name, source_path, duration_ms FROM project LIMIT 1")
            row = c.fetchone()
            if row:
                projects.append({
                    "project_id": proj_id,
                    "name": row[0],
                    "source": row[1],
                    "duration_s": row[2] / 1000 if row[2] else 0,
                })
            db.close()
        except Exception:
            pass
    return projects


def train_clone(
    project_id: str,
    clone_name: str,
    fps: int = 3,
    max_frames: int = 2000,
    epochs: int = 1000,
    batch_size: int = 128,
    lr: float = 1e-3,
    use_constellation: bool = True,
    device: str = "cuda",
) -> dict:
    """Train a complete clone model from a ClipCannon project.

    End-to-end pipeline:
    1. Extract ground truth blendshapes from video
    2. Load all embeddings from analysis.db
    3. Compute North Star constellation
    4. Train model with supervised + contrastive loss
    5. Save model + constellation + metadata

    Args:
        project_id: ClipCannon project ID.
        clone_name: Name for the clone (e.g., "santa", "chris").
        fps: Frame extraction rate for blendshape ground truth.
        max_frames: Maximum training frames.
        epochs: Training epochs.
        batch_size: Batch size.
        lr: Learning rate.
        use_constellation: Whether to compute full constellation.
        device: "cuda" or "cpu".

    Returns:
        Dict with training results and model path.
    """
    t_total_start = time.time()

    project_dir = os.path.join(PROJECTS_DIR, project_id)
    db_path = os.path.join(project_dir, "analysis.db")

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"No analysis.db for project {project_id}")

    # Get source video path
    db = sqlite3.connect(db_path)
    c = db.cursor()
    c.execute("SELECT source_path, name FROM project LIMIT 1")
    row = c.fetchone()
    db.close()
    if not row:
        raise ValueError(f"Empty project: {project_id}")

    source_video = row[0]
    project_name = row[1]
    logger.info("=== Training clone '%s' from '%s' ===", clone_name, project_name)

    # Step 1: Extract ground truth blendshapes
    logger.info("[1/5] Extracting ground truth blendshapes at %dfps...", fps)
    t0 = time.time()
    blendshape_data = extract_ground_truth_blendshapes(
        source_video, fps=fps, max_frames=max_frames,
    )
    logger.info("  %d frames extracted in %.1fs", len(blendshape_data), time.time() - t0)

    if len(blendshape_data) < 10:
        raise ValueError(f"Too few frames extracted ({len(blendshape_data)}). Check video.")

    # Step 2: Load embeddings from analysis.db
    logger.info("[2/5] Loading embeddings from analysis.db...")
    embeddings = load_embeddings_from_db(db_path)

    # Step 3: Build training dataset
    logger.info("[3/5] Building training dataset...")
    dataset = build_training_dataset(blendshape_data, embeddings)
    n_samples = dataset["n_samples"]
    logger.info("  Dataset: %d samples", n_samples)

    # Step 4: Compute North Star constellation
    logger.info("[4/5] Computing North Star constellation...")
    timestamps = dataset["timestamps_ms"].tolist()

    prosody_list = embeddings.get("prosody", [])
    emotion_list = embeddings.get("emotions", [])

    # Build numpy arrays for constellation computation
    prosody_np = dataset["prosody"].numpy()
    emotion_np = dataset["emotion_scalars"].numpy()

    training_embs = {
        "prosody": prosody_np,
        "emotion": emotion_np,
    }

    if use_constellation:
        constellation = compute_north_star_constellation(
            training_embs, prosody_list, emotion_list, blendshape_data, timestamps,
        )
        global_centroids = constellation.global_centroids
        total_stars = sum(len(s) for s in constellation.stars.values())
        logger.info("  Constellation: %d stars across %d states",
                     total_stars, len(constellation.state_counts))
    else:
        constellation = None
        global_centroids = compute_north_stars(training_embs)

    # Step 5: Train model
    logger.info("[5/5] Training model...")
    t_train_start = time.time()

    # Create model with the embeddings we have
    model = CloneModel(
        embedding_dims={"prosody": 12, "emotion_scalars": 8},
    )
    model = model.to(device)

    # Fuse North Stars into transformer
    model.fuse_north_stars(global_centroids)

    logger.info("  Model: %.1fM params on %s", model.param_count / 1e6, device)

    # Prepare tensors
    prosody_t = dataset["prosody"].to(device)
    emotion_t = dataset["emotion_scalars"].to(device)
    gt_t = dataset["gt_blendshapes"].to(device)

    ds = TensorDataset(prosody_t, emotion_t, gt_t)
    loader = DataLoader(ds, batch_size=batch_size, shuffle=True, drop_last=False)

    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    mse_loss = nn.MSELoss()
    contrastive_loss = NorthStarContrastiveLoss(temperature=0.07)

    # Training stars as tensors for contrastive loss
    star_tensors = {
        name: torch.tensor(vec, device=device)
        for name, vec in global_centroids.items()
    }

    best_loss = float("inf")
    losses = []

    for epoch in range(epochs):
        model.train()
        epoch_loss = 0.0
        n_batches = 0

        for batch_p, batch_e, batch_gt in loader:
            optimizer.zero_grad()

            out = model(
                embeddings={"prosody": batch_p, "emotion_scalars": batch_e},
                prosody_scalars=batch_p,
            )

            # Supervised loss on blendshapes
            loss_supervised = mse_loss(out["blendshapes"], batch_gt)

            # Contrastive loss vs North Stars
            if "_pooled" in out and model.reverse_projections:
                projections = model.project_to_embedding_spaces(out["_pooled"])
                loss_contrast = contrastive_loss(projections, star_tensors)
                loss = loss_supervised + 0.1 * loss_contrast
            else:
                loss = loss_supervised

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            epoch_loss += loss.item()
            n_batches += 1

        scheduler.step()
        avg_loss = epoch_loss / max(n_batches, 1)
        losses.append(avg_loss)

        if avg_loss < best_loss:
            best_loss = avg_loss

        if (epoch + 1) % 100 == 0 or epoch == 0:
            elapsed = time.time() - t_train_start
            logger.info("  Epoch %d/%d: loss=%.6f (best=%.6f), %.1fs",
                        epoch + 1, epochs, avg_loss, best_loss, elapsed)

    train_time = time.time() - t_train_start
    logger.info("  Training complete: %.1fs, final_loss=%.6f", train_time, best_loss)

    # Save model + metadata
    save_dir = os.path.join(MODELS_DIR, clone_name)
    os.makedirs(save_dir, exist_ok=True)
    model_path = os.path.join(save_dir, "clone_model.pt")

    save_data = {
        "model_state_dict": model.state_dict(),
        "config": {
            "clone_name": clone_name,
            "project_id": project_id,
            "project_name": project_name,
            "embedding_dims": {"prosody": 12, "emotion_scalars": 8},
            "param_count": model.param_count,
            "training_samples": n_samples,
            "epochs": epochs,
            "best_loss": best_loss,
            "train_time_s": train_time,
            "fps": fps,
            "has_constellation": use_constellation,
        },
    }

    if constellation:
        # Save constellation as numpy arrays
        constellation_data = {}
        for mod, states in constellation.stars.items():
            constellation_data[mod] = {s: v.tolist() for s, v in states.items()}
        save_data["constellation"] = constellation_data
        save_data["state_counts"] = constellation.state_counts

    torch.save(save_data, model_path)
    logger.info("Model saved: %s", model_path)

    # Save human-readable metadata
    meta = {
        "clone_name": clone_name,
        "project_id": project_id,
        "project_name": project_name,
        "training_samples": n_samples,
        "param_count": model.param_count,
        "best_loss": best_loss,
        "train_time_s": round(train_time, 1),
        "total_time_s": round(time.time() - t_total_start, 1),
        "constellation_stars": sum(len(s) for s in constellation.stars.values()) if constellation else 0,
        "constellation_states": len(constellation.state_counts) if constellation else 0,
    }
    with open(os.path.join(save_dir, "metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)

    # Cleanup
    del model, optimizer, scheduler
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    total_time = time.time() - t_total_start
    logger.info("=== Clone '%s' trained in %.1fs ===", clone_name, total_time)

    return meta


def main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Universal Clone Trainer")
    parser.add_argument("--project", type=str, help="ClipCannon project ID")
    parser.add_argument("--name", type=str, required=True, help="Clone name (e.g., 'santa')")
    parser.add_argument("--fps", type=int, default=3, help="Frame extraction rate")
    parser.add_argument("--max-frames", type=int, default=2000)
    parser.add_argument("--epochs", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--no-constellation", action="store_true")
    parser.add_argument("--list", action="store_true", help="List available projects")
    args = parser.parse_args()

    if args.list:
        projects = list_available_projects()
        print(f"\n{'ID':<20} {'Name':<35} {'Duration':>10}")
        print("-" * 65)
        for p in projects:
            print(f"{p['project_id']:<20} {p['name']:<35} {p['duration_s']:>8.0f}s")
        return

    if not args.project:
        parser.error("--project is required (use --list to see available)")

    result = train_clone(
        project_id=args.project,
        clone_name=args.name,
        fps=args.fps,
        max_frames=args.max_frames,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        use_constellation=not args.no_constellation,
    )

    print(f"\n{'='*50}")
    print(f"  Clone '{result['clone_name']}' trained successfully!")
    print(f"  Samples: {result['training_samples']}")
    print(f"  Parameters: {result['param_count']:,}")
    print(f"  Best loss: {result['best_loss']:.6f}")
    print(f"  Constellation: {result['constellation_stars']} stars, {result['constellation_states']} states")
    print(f"  Time: {result['total_time_s']}s")
    print(f"  Model: ~/.clipcannon/models/{result['clone_name']}/clone_model.pt")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
