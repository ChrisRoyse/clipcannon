"""FLAME parameter fitting from video using insightface 106 landmarks.

Extracts per-frame FLAME expression coefficients and jaw pose by:
1. Detecting 106 2D landmarks via insightface
2. Projecting FLAME mesh to 2D via weak-perspective camera
3. Minimizing reprojection error with Adam optimizer
4. Warm-starting each frame from previous solution

Processes batches of frames on GPU for speed.
Outputs: expression (N, 100), jaw_pose (N, 3), timestamps (N,).

Usage:
    fitter = FlameFitter(flame_model_path, video_path)
    fitter.fit(output_path="~/.clipcannon/models/<person>/flame_params.npz")
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F  # noqa: N812

from phoenix.render.flame_landmarks import FLAME_LMK_68 as FLAME_LMK_68
from phoenix.render.flame_landmarks import (
    INSIGHT106_TO_68,
    _get_flame_lmk_verts,
    _project_weak_perspective,
)

logger = logging.getLogger(__name__)


class FlameFitter:
    """Fits FLAME expression + jaw parameters to video using 2D landmarks.

    Processes the video at a configurable sampling rate, detects
    insightface 106 landmarks, maps them to 68-point scheme, and
    optimizes FLAME parameters to minimize reprojection error.

    Args:
        video_path: Path to the input video.
        flame_data_dir: Path to FLAME model data directory.
        sample_fps: Frames per second to sample from video.
        batch_size: Number of frames to optimize simultaneously.
        num_iters: Number of Adam iterations per batch.
        device_id: CUDA device index.
    """

    def __init__(
        self,
        video_path: str | Path,
        flame_data_dir: str | Path | None = None,
        sample_fps: float = 5.0,
        batch_size: int = 32,
        num_iters: int = 80,
        device_id: int = 0,
    ) -> None:
        self.video_path = Path(video_path)
        self.sample_fps = sample_fps
        self.batch_size = batch_size
        self.num_iters = num_iters
        self.device = torch.device(f"cuda:{device_id}")

        if flame_data_dir is None:
            flame_data_dir = Path(__file__).resolve().parents[3] / "models" / "FLAME2020"
        self.flame_data_dir = Path(flame_data_dir)

        self._flame = None
        self._face_app = None

    def _init_flame(self) -> None:
        """Initialize the FLAME model on GPU."""
        from phoenix.render.flame_model import FlameModel, FlameModelConfig

        config = FlameModelConfig(data_dir=self.flame_data_dir)
        self._flame = FlameModel(config).to(self.device)
        self._flame.eval()
        for p in self._flame.parameters():
            p.requires_grad_(False)
        logger.info("FLAME model loaded: %d verts", self._flame.num_vertices)

    def _init_insightface(self) -> None:
        """Initialize insightface face analysis."""
        from insightface.app import FaceAnalysis

        self._face_app = FaceAnalysis(providers=["CUDAExecutionProvider"])
        self._face_app.prepare(ctx_id=0, det_size=(640, 640))
        logger.info("InsightFace initialized")

    def _extract_landmarks(self) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
        """Extract 68 landmarks from video at sample_fps.

        Returns:
            landmarks_68: (N, 68, 2) normalized landmark coordinates.
            timestamps: (N,) timestamps in seconds.
            face_crops: List of (H, W, 3) face crop images.
        """
        cap = cv2.VideoCapture(str(self.video_path))
        video_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_interval = max(1, int(round(video_fps / self.sample_fps)))

        logger.info(
            "Video: %dfps, %d frames, sampling every %d frames (%.1f fps)",
            int(video_fps), total_frames, frame_interval, video_fps / frame_interval,
        )

        all_landmarks = []
        all_timestamps = []
        all_crops = []
        frame_idx = 0
        processed = 0
        skipped = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_interval == 0:
                faces = self._face_app.get(frame)
                if len(faces) > 0 and faces[0].landmark_2d_106 is not None:
                    lmk106 = faces[0].landmark_2d_106  # (106, 2)
                    # Map to 68 landmarks
                    lmk68 = lmk106[INSIGHT106_TO_68]  # (68, 2)

                    # Filter bad frames: face must be sufficiently visible
                    det_score = getattr(faces[0], "det_score", 1.0)
                    if det_score < 0.5:
                        skipped += 1
                        frame_idx += 1
                        continue

                    # Check face orientation via landmark spread
                    lmk_spread_x = lmk68[:, 0].max() - lmk68[:, 0].min()
                    lmk_spread_y = lmk68[:, 1].max() - lmk68[:, 1].min()
                    face_ratio = lmk_spread_x / max(lmk_spread_y, 1)
                    if face_ratio < 0.3 or face_ratio > 3.0:
                        # Face severely rotated or occluded
                        skipped += 1
                        frame_idx += 1
                        continue

                    # Get face bounding box for crop
                    bbox = faces[0].bbox.astype(int)
                    bw = bbox[2] - bbox[0]
                    bh = bbox[3] - bbox[1]
                    # Center on face using landmark centroid (more stable than bbox)
                    cx = int(lmk68[:, 0].mean())
                    cy = int(lmk68[:, 1].mean())
                    # Expand bbox by 80% (was 30%) to include full head + hair
                    half = int(max(bw, bh) * 0.9)
                    x1 = max(0, cx - half)
                    y1 = max(0, cy - half)
                    x2 = min(frame.shape[1], cx + half)
                    y2 = min(frame.shape[0], cy + half)
                    crop = frame[y1:y2, x1:x2]

                    # FIX: Convert BGR (OpenCV) to RGB for training
                    crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)

                    # Normalize landmarks to [-1, 1] relative to face center
                    # Use face bbox center and size for normalization
                    face_size = max(bw, bh)
                    lmk_norm = np.zeros_like(lmk68)
                    lmk_norm[:, 0] = (lmk68[:, 0] - cx) / (face_size * 0.5)
                    lmk_norm[:, 1] = (lmk68[:, 1] - cy) / (face_size * 0.5)

                    all_landmarks.append(lmk_norm)
                    all_timestamps.append(frame_idx / video_fps)
                    all_crops.append(crop)
                    processed += 1
                else:
                    skipped += 1

                if (processed + skipped) % 200 == 0:
                    logger.info(
                        "Landmark extraction: %d/%d frames (%.0f%%), %d valid, %d skipped",
                        frame_idx, total_frames,
                        100 * frame_idx / max(total_frames, 1),
                        processed, skipped,
                    )

            frame_idx += 1

        cap.release()
        logger.info(
            "Landmark extraction complete: %d valid frames, %d skipped",
            processed, skipped,
        )

        return (
            np.array(all_landmarks, dtype=np.float32),
            np.array(all_timestamps, dtype=np.float32),
            all_crops,
        )

    def _fit_batch(
        self,
        target_lmk: torch.Tensor,
        init_expr: torch.Tensor,
        init_jaw: torch.Tensor,
        init_scale: torch.Tensor,
        init_tx: torch.Tensor,
        init_ty: torch.Tensor,
        shape_params: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """Fit FLAME params to a batch of landmark targets.

        Args:
            target_lmk: (B, 68, 2) normalized target 2D landmarks.
            init_expr: (B, 100) initial expression params.
            init_jaw: (B, 3) initial jaw pose.
            init_scale: (B, 1) initial camera scale.
            init_tx: (B, 1) initial x-translation.
            init_ty: (B, 1) initial y-translation.
            shape_params: (B, 300) fixed shape params.

        Returns:
            Optimized (expr, jaw, scale, tx, ty).
        """
        # Optimizable parameters
        expr = init_expr.clone().detach().requires_grad_(True)
        jaw = init_jaw.clone().detach().requires_grad_(True)
        scale = init_scale.clone().detach().requires_grad_(True)
        tx = init_tx.clone().detach().requires_grad_(True)
        ty = init_ty.clone().detach().requires_grad_(True)

        optimizer = torch.optim.Adam(
            [
                {"params": [expr], "lr": 0.02},
                {"params": [jaw], "lr": 0.01},
                {"params": [scale], "lr": 0.005},
                {"params": [tx, ty], "lr": 0.005},
            ],
        )

        for _ in range(self.num_iters):
            optimizer.zero_grad()

            # Get FLAME 3D landmarks
            lmk3d = _get_flame_lmk_verts(
                self._flame, shape_params, expr, jaw,
            )  # (B, 68, 3)

            # Project to 2D
            lmk2d = _project_weak_perspective(lmk3d, scale, tx, ty)  # (B, 68, 2)

            # Reprojection loss
            loss_reproj = F.mse_loss(lmk2d, target_lmk)

            # Regularization: keep expression and jaw close to zero
            loss_reg_expr = 0.0005 * torch.mean(expr ** 2)
            loss_reg_jaw = 0.001 * torch.mean(jaw ** 2)

            loss = loss_reproj + loss_reg_expr + loss_reg_jaw
            loss.backward()
            optimizer.step()

        return (
            expr.detach(),
            jaw.detach(),
            scale.detach(),
            tx.detach(),
            ty.detach(),
        )

    def fit(
        self,
        output_path: str | Path,
        shape_params: torch.Tensor | None = None,
    ) -> dict[str, np.ndarray]:
        """Run full FLAME fitting pipeline on the video.

        Args:
            output_path: Path to save the fitted parameters as .npz.
            shape_params: Optional (300,) identity shape to use.
                If None, uses neutral (zero) shape.

        Returns:
            Dict with 'expression', 'jaw_pose', 'timestamps' arrays.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize models
        self._init_flame()
        self._init_insightface()

        # Extract landmarks
        logger.info("Extracting landmarks from video...")
        start = time.time()
        landmarks, timestamps, crops = self._extract_landmarks()
        logger.info(
            "Landmark extraction took %.1fs for %d frames",
            time.time() - start, len(landmarks),
        )

        if len(landmarks) == 0:
            raise RuntimeError("No face landmarks detected in video")

        N = len(landmarks)  # noqa: N806
        target_lmk = torch.from_numpy(landmarks).to(self.device)

        # Shape params (fixed)
        if shape_params is None:
            shape_params = torch.zeros(300, device=self.device, dtype=torch.float32)
        else:
            shape_params = shape_params.to(self.device)

        # Output buffers
        all_expr = torch.zeros(N, 100, device=self.device)
        all_jaw = torch.zeros(N, 3, device=self.device)

        # Initialize camera params from first frame rough estimation
        # Scale: FLAME head is ~0.2m wide, landmarks normalized to [-1,1]
        # So scale ~ 5-10 maps FLAME coords to normalized landmark space
        init_scale = torch.full((1, 1), 7.0, device=self.device)
        init_tx = torch.zeros(1, 1, device=self.device)
        # FLAME mesh center is slightly above center, shift down
        init_ty = torch.full((1, 1), 0.3, device=self.device)

        # Running camera params (warm-started)
        prev_expr = torch.zeros(1, 100, device=self.device)
        prev_jaw = torch.zeros(1, 3, device=self.device)
        prev_scale = init_scale.clone()
        prev_tx = init_tx.clone()
        prev_ty = init_ty.clone()

        logger.info("Starting FLAME fitting: %d frames, batch_size=%d", N, self.batch_size)
        fit_start = time.time()

        for batch_start in range(0, N, self.batch_size):
            batch_end = min(batch_start + self.batch_size, N)
            B = batch_end - batch_start  # noqa: N806

            # Target landmarks for this batch
            batch_target = target_lmk[batch_start:batch_end]

            # Warm-start from previous frame's solution
            batch_expr = prev_expr.expand(B, -1).clone()
            batch_jaw = prev_jaw.expand(B, -1).clone()
            batch_scale = prev_scale.expand(B, -1).clone()
            batch_tx = prev_tx.expand(B, -1).clone()
            batch_ty = prev_ty.expand(B, -1).clone()
            batch_shape = shape_params.unsqueeze(0).expand(B, -1)

            # Fit this batch
            expr, jaw, scale, tx, ty = self._fit_batch(
                batch_target, batch_expr, batch_jaw,
                batch_scale, batch_tx, batch_ty, batch_shape,
            )

            all_expr[batch_start:batch_end] = expr
            all_jaw[batch_start:batch_end] = jaw

            # Update warm-start from last frame in batch
            prev_expr = expr[-1:].clone()
            prev_jaw = jaw[-1:].clone()
            prev_scale = scale[-1:].clone()
            prev_tx = tx[-1:].clone()
            prev_ty = ty[-1:].clone()

            if (batch_start // self.batch_size) % 10 == 0 or batch_end == N:
                elapsed = time.time() - fit_start
                fps = batch_end / max(elapsed, 0.01)
                remaining = (N - batch_end) / max(fps, 0.01)
                logger.info(
                    "FLAME fit: %d/%d frames (%.0f%%), %.1f frames/sec, ~%.0fs remaining",
                    batch_end, N, 100 * batch_end / N, fps, remaining,
                )

        total_time = time.time() - fit_start
        logger.info(
            "FLAME fitting complete: %d frames in %.1fs (%.1f frames/sec)",
            N, total_time, N / max(total_time, 0.01),
        )

        # Save results
        result = {
            "expression": all_expr.cpu().numpy(),
            "jaw_pose": all_jaw.cpu().numpy(),
            "timestamps": timestamps,
        }
        np.savez_compressed(str(output_path), **result)
        logger.info("Saved FLAME params to %s", output_path)

        # Also save crops for training (already RGB from extraction)
        crops_path = output_path.parent / "face_crops_512.npz"
        crop_size = 512
        resized_crops = []
        for crop in crops:
            if crop.shape[0] > 0 and crop.shape[1] > 0:
                resized = cv2.resize(crop, (crop_size, crop_size))
                resized_crops.append(resized)
            else:
                resized_crops.append(np.zeros((crop_size, crop_size, 3), dtype=np.uint8))
        np.savez_compressed(str(crops_path), crops=np.array(resized_crops))
        logger.info("Saved %d face crops (RGB, %dx%d) to %s",
                     len(resized_crops), crop_size, crop_size, crops_path)

        return result


def main() -> None:
    """CLI entry point for FLAME fitting."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Fit FLAME to video")
    parser.add_argument("--video", type=str, required=True, help="Path to input video")
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output .npz path, e.g. ~/.clipcannon/models/<person>/flame_params.npz",
    )
    parser.add_argument("--sample-fps", type=float, default=5.0)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--num-iters", type=int, default=80)
    args = parser.parse_args()

    fitter = FlameFitter(
        video_path=args.video,
        sample_fps=args.sample_fps,
        batch_size=args.batch_size,
        num_iters=args.num_iters,
    )
    result = fitter.fit(output_path=args.output)
    print(f"Done: expression {result['expression'].shape}, jaw_pose {result['jaw_pose'].shape}")


if __name__ == "__main__":
    main()
