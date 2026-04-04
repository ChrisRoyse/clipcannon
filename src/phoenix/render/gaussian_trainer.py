"""Gaussian avatar trainer for Santa.

Trains a GaussianAvatarModel using fitted FLAME parameters and
corresponding video face crops via photometric loss (L1 + SSIM).

Pipeline:
1. Load fitted FLAME params (expression, jaw_pose, timestamps)
2. Load corresponding face crops from video
3. Create GaussianAvatarModel bound to FLAME mesh
4. Train with L1 + SSIM photometric loss
5. Save trained model checkpoint

Usage:
    trainer = GaussianTrainer(
        flame_params_path="~/.clipcannon/models/santa/flame_params.npz",
        output_path="~/.clipcannon/models/santa/gaussian_avatar.pt",
    )
    trainer.train()
"""

from __future__ import annotations

import logging
import math
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


def _ssim_loss(
    img1: torch.Tensor,
    img2: torch.Tensor,
    window_size: int = 11,
) -> torch.Tensor:
    """Compute SSIM loss between two images.

    Args:
        img1: (B, C, H, W) predicted image.
        img2: (B, C, H, W) target image.
        window_size: Size of the Gaussian window.

    Returns:
        Scalar SSIM loss (1 - SSIM).
    """
    C = img1.shape[1]

    # Create Gaussian window
    sigma = 1.5
    coords = torch.arange(window_size, dtype=img1.dtype, device=img1.device)
    coords -= window_size // 2
    g = torch.exp(-(coords ** 2) / (2 * sigma ** 2))
    g = g / g.sum()
    window = g.unsqueeze(1) * g.unsqueeze(0)
    window = window.unsqueeze(0).unsqueeze(0).expand(C, 1, -1, -1).contiguous()

    pad = window_size // 2
    mu1 = F.conv2d(img1, window, padding=pad, groups=C)
    mu2 = F.conv2d(img2, window, padding=pad, groups=C)
    mu1_sq = mu1 ** 2
    mu2_sq = mu2 ** 2
    mu1_mu2 = mu1 * mu2

    sigma1_sq = F.conv2d(img1 * img1, window, padding=pad, groups=C) - mu1_sq
    sigma2_sq = F.conv2d(img2 * img2, window, padding=pad, groups=C) - mu2_sq
    sigma12 = F.conv2d(img1 * img2, window, padding=pad, groups=C) - mu1_mu2

    C1 = 0.01 ** 2
    C2 = 0.03 ** 2

    ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / (
        (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)
    )
    return 1 - ssim_map.mean()


class GaussianTrainer:
    """Trains a Gaussian avatar model from FLAME params + face crops.

    Args:
        flame_params_path: Path to fitted FLAME params (.npz).
        face_crops_path: Path to face crops (.npz). If None, derived from flame_params_path.
        output_path: Path to save trained model (.pt).
        num_iters: Number of training iterations.
        batch_size: Frames per iteration.
        lr: Base learning rate.
        tex_size: UV texture resolution (determines Gaussian count).
        render_size: Render resolution for training (square).
        ssim_weight: Weight for SSIM loss component.
        device_id: CUDA device index.
    """

    def __init__(
        self,
        flame_params_path: str | Path,
        face_crops_path: str | Path | None = None,
        output_path: str | Path | None = None,
        num_iters: int = 5000,
        batch_size: int = 4,
        lr: float = 5e-4,
        tex_size: int = 128,
        render_size: int = 512,
        ssim_weight: float = 0.2,
        device_id: int = 0,
    ) -> None:
        self.flame_params_path = Path(flame_params_path)
        if face_crops_path is None:
            self.face_crops_path = self.flame_params_path.parent / "face_crops.npz"
        else:
            self.face_crops_path = Path(face_crops_path)
        if output_path is None:
            self.output_path = self.flame_params_path.parent / "gaussian_avatar.pt"
        else:
            self.output_path = Path(output_path)

        self.num_iters = num_iters
        self.batch_size = batch_size
        self.lr = lr
        self.tex_size = tex_size
        self.render_size = render_size
        self.ssim_weight = ssim_weight
        self.device = torch.device(f"cuda:{device_id}")

        self._flame = None
        self._avatar = None
        self._expressions = None
        self._jaw_poses = None
        self._target_images = None

    def _load_data(self) -> None:
        """Load FLAME params and face crop images."""
        # Load FLAME params
        params = np.load(str(self.flame_params_path))
        self._expressions = torch.from_numpy(params["expression"]).to(
            self.device, torch.float32,
        )
        self._jaw_poses = torch.from_numpy(params["jaw_pose"]).to(
            self.device, torch.float32,
        )
        logger.info(
            "Loaded FLAME params: %d frames, expr %s, jaw %s",
            len(self._expressions),
            tuple(self._expressions.shape),
            tuple(self._jaw_poses.shape),
        )

        # Load face crops
        crops_data = np.load(str(self.face_crops_path))
        crops = crops_data["crops"]  # (N, H, W, 3) uint8
        logger.info("Loaded %d face crops: %s", len(crops), crops.shape)

        # Resize crops to render_size and convert to float [0, 1]
        resized = []
        for crop in crops:
            r = cv2.resize(crop, (self.render_size, self.render_size))
            resized.append(r)
        images = np.array(resized, dtype=np.float32) / 255.0
        # BGR to RGB
        images = images[:, :, :, ::-1].copy()
        self._target_images = torch.from_numpy(images).to(self.device)
        logger.info("Target images: %s", tuple(self._target_images.shape))

    def _init_models(self) -> None:
        """Initialize FLAME and Gaussian avatar models."""
        from phoenix.render.flame_model import FlameModel, FlameModelConfig
        from phoenix.render.gsplat_avatar import AvatarRenderConfig, GaussianAvatarModel

        # FLAME model
        flame_config = FlameModelConfig()
        self._flame = FlameModel(flame_config).to(self.device)
        self._flame.eval()
        for p in self._flame.parameters():
            p.requires_grad_(False)

        # Gaussian avatar with training config
        avatar_config = AvatarRenderConfig(
            width=self.render_size,
            height=self.render_size,
            tex_size=self.tex_size,
            num_expression_in=100,  # FLAME expression dim
            num_basis=20,
            fov_y=25.0,
            bg_color=(0.0, 0.0, 0.0),
        )
        self._avatar = GaussianAvatarModel(self._flame, avatar_config)
        self._avatar = self._avatar.to(self.device)
        num_gs = self._avatar.bind_to_mesh()
        logger.info(
            "Gaussian avatar initialized: %d Gaussians (tex_size=%d)",
            num_gs, self.tex_size,
        )

    def _sample_batch(self) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Sample a random batch of frames for training.

        Returns:
            expressions: (B, 100) expression params.
            jaw_poses: (B, 3) jaw pose params.
            target_images: (B, H, W, 3) target face crops.
        """
        N = len(self._expressions)
        indices = torch.randint(0, N, (self.batch_size,), device=self.device)

        return (
            self._expressions[indices],
            self._jaw_poses[indices],
            self._target_images[indices],
        )

    def train(self) -> None:
        """Run the full training loop.

        Trains the Gaussian avatar model using L1 + SSIM loss
        between rendered images and target face crops.
        """
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Loading training data...")
        self._load_data()

        logger.info("Initializing models...")
        self._init_models()

        # Shape params (neutral)
        shape_params = torch.zeros(
            1, 300, device=self.device, dtype=torch.float32,
        )

        # Optimizer: all Gaussian parameters
        optimizer = torch.optim.Adam(self._avatar.parameters(), lr=self.lr)

        # Cosine annealing scheduler
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=self.num_iters, eta_min=self.lr * 0.01,
        )

        logger.info(
            "Starting training: %d iters, batch_size=%d, lr=%.1e",
            self.num_iters, self.batch_size, self.lr,
        )
        train_start = time.time()
        best_loss = float("inf")

        for step in range(1, self.num_iters + 1):
            optimizer.zero_grad()

            # Sample batch
            expr, jaw, target = self._sample_batch()
            B = expr.shape[0]

            # Get FLAME mesh vertices
            batch_shape = shape_params.expand(B, -1)
            verts = self._flame(batch_shape, expr, jaw_pose=jaw)

            # Render Gaussian avatar
            result = self._avatar.render(
                verts,
                expression_weights=expr,
            )
            rendered = result["image"]  # (B, H, W, 3)

            # Photometric loss
            # Convert to (B, C, H, W) for SSIM
            rendered_bchw = rendered.permute(0, 3, 1, 2)
            target_bchw = target.permute(0, 3, 1, 2)

            loss_l1 = F.l1_loss(rendered_bchw, target_bchw)
            loss_ssim = _ssim_loss(rendered_bchw, target_bchw)

            loss = loss_l1 + self.ssim_weight * loss_ssim

            loss.backward()
            optimizer.step()
            scheduler.step()

            if loss.item() < best_loss:
                best_loss = loss.item()

            if step % 100 == 0 or step == 1:
                elapsed = time.time() - train_start
                it_per_sec = step / max(elapsed, 0.01)
                remaining = (self.num_iters - step) / max(it_per_sec, 0.01)
                lr_now = scheduler.get_last_lr()[0]
                logger.info(
                    "Step %d/%d | L1=%.4f SSIM=%.4f Total=%.4f | "
                    "Best=%.4f | LR=%.2e | %.1f it/s | ~%.0fs left",
                    step, self.num_iters,
                    loss_l1.item(), loss_ssim.item(), loss.item(),
                    best_loss, lr_now, it_per_sec, remaining,
                )

            # Save checkpoint every 1000 steps
            if step % 1000 == 0:
                self._save_checkpoint(step)

        total_time = time.time() - train_start
        logger.info(
            "Training complete: %d iters in %.1fs (%.1f it/s), best_loss=%.4f",
            self.num_iters, total_time, self.num_iters / total_time, best_loss,
        )

        # Save final model
        self._save_checkpoint(self.num_iters, final=True)

    def _save_checkpoint(self, step: int, final: bool = False) -> None:
        """Save model checkpoint.

        Args:
            step: Current training step.
            final: If True, save to the final output path.
        """
        checkpoint = {
            "step": step,
            "avatar_state_dict": self._avatar.state_dict(),
            "config": self._avatar.config,
            "tex_size": self.tex_size,
            "render_size": self.render_size,
            "num_gaussians": self._avatar.num_gaussians,
        }

        if final:
            path = self.output_path
        else:
            path = self.output_path.parent / f"gaussian_avatar_step{step}.pt"

        torch.save(checkpoint, str(path))
        logger.info("Saved checkpoint to %s (step %d)", path, step)


def main() -> None:
    """CLI entry point for Gaussian avatar training."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Train Gaussian avatar")
    parser.add_argument(
        "--flame-params",
        type=str,
        default=str(Path.home() / ".clipcannon/models/santa/flame_params.npz"),
        help="Path to fitted FLAME parameters",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(Path.home() / ".clipcannon/models/santa/gaussian_avatar.pt"),
        help="Output path for trained model",
    )
    parser.add_argument("--num-iters", type=int, default=5000)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--lr", type=float, default=5e-4)
    parser.add_argument("--tex-size", type=int, default=128)
    parser.add_argument("--render-size", type=int, default=512)
    parser.add_argument("--ssim-weight", type=float, default=0.2)
    args = parser.parse_args()

    trainer = GaussianTrainer(
        flame_params_path=args.flame_params,
        output_path=args.output,
        num_iters=args.num_iters,
        batch_size=args.batch_size,
        lr=args.lr,
        tex_size=args.tex_size,
        render_size=args.render_size,
        ssim_weight=args.ssim_weight,
    )
    trainer.train()


if __name__ == "__main__":
    main()
