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
    fitter.fit(output_path="~/.clipcannon/models/santa/flame_params.npz")
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# FLAME 68-landmark vertex indices (standard from FLAME codebase)
# These map the 68 Multi-PIE landmarks to FLAME mesh vertex indices
# --------------------------------------------------------------------------- #
FLAME_LMK_68 = [
    # Jaw contour (0-16)
    3572, 2643, 2585, 2546, 2510, 3636, 3503, 3410, 3336,
    3270, 3206, 3144, 3075, 2989, 2905, 2832, 2774,
    # Right eyebrow (17-21)
    3862, 3854, 3848, 3839, 3820,
    # Left eyebrow (22-26)
    2437, 2383, 2345, 2315, 2286,
    # Nose bridge (27-30)
    1610, 1647, 1691, 1731,
    # Nose bottom (31-35)
    2162, 2173, 2188, 1830, 1803,
    # Right eye (36-41)
    3712, 3716, 3721, 3726, 3727, 3718,
    # Left eye (42-47)
    2210, 2214, 2219, 2224, 2225, 2216,
    # Outer lip (48-59)
    3543, 3509, 3466, 3423, 3390, 3380, 3354, 3362,
    3378, 3395, 3437, 3490,
    # Inner lip (60-67)
    3502, 3456, 3410, 3372, 3361, 3373, 3411, 3457,
]

# --------------------------------------------------------------------------- #
# Mapping from insightface 106 landmarks to FLAME 68 landmarks
# InsightFace 106 layout (approx):
#   0-32:  face contour (33 points)
#   33-37: right eyebrow (5 points)
#   38-42: left eyebrow (5 points)
#   43-46: nose bridge (4 points)
#   47-51: nose bottom (5 points)
#   52-57: right eye (6 points)
#   58-63: left eye (6 points)
#   64-71: outer lip upper (8 points)
#   72-75: outer lip lower (4 points)
#   76-83: inner lip upper (8 points)
#   84-87: inner lip lower (4 points)
#   88-95: more points
#   96-103: pupil/extra
#   104-105: extra
# --------------------------------------------------------------------------- #

# We select a subset of insightface-106 that aligns well with the 68 scheme.
# The mapping is: INSIGHT106_TO_68[i] = index in the 106 array
# corresponding to the i-th 68-landmark.
INSIGHT106_TO_68 = [
    # Jaw contour (0-16): 106-format uses 0-32 for contour (33 pts)
    # We pick every 2nd point from the 33-pt contour
    0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32,
    # Right eyebrow (17-21): indices 33-37
    33, 34, 35, 36, 37,
    # Left eyebrow (22-26): indices 38-42
    42, 41, 40, 39, 38,
    # Nose bridge (27-30): indices 43-46
    43, 44, 45, 46,
    # Nose bottom (31-35): indices 47-51
    47, 48, 49, 50, 51,
    # Right eye (36-41): indices 52-57
    52, 53, 54, 55, 56, 57,
    # Left eye (42-47): indices 58-63
    58, 59, 60, 61, 62, 63,
    # Outer lip (48-59):
    # upper: 64,65,66,67,68,69,70,71 (8 pts)
    # lower: 72,73,74,75 (4 pts)
    # We need 12 pts for outer lip in 68 scheme
    64, 65, 66, 67, 68, 69, 70, 71, 75, 74, 73, 72,
    # Inner lip (60-67):
    # upper: 76,77,78,79 (pick 4 from 8)
    # lower: 84,85,86,87 (pick 4 from 4)
    76, 78, 80, 82, 87, 85, 83, 81,
]


def _get_flame_lmk_verts(
    flame_model: torch.nn.Module,
    shape_params: torch.Tensor,
    expression_params: torch.Tensor,
    jaw_pose: torch.Tensor,
) -> torch.Tensor:
    """Get FLAME 68-landmark 3D positions.

    Args:
        flame_model: FLAME model instance.
        shape_params: (B, 300) shape coefficients.
        expression_params: (B, 100) expression coefficients.
        jaw_pose: (B, 3) jaw rotation axis-angle.

    Returns:
        (B, 68, 3) landmark 3D positions.
    """
    verts = flame_model(shape_params, expression_params, jaw_pose=jaw_pose)
    lmk_idx = torch.tensor(FLAME_LMK_68, device=verts.device, dtype=torch.long)
    return verts[:, lmk_idx]


def _project_weak_perspective(
    pts3d: torch.Tensor,
    scale: torch.Tensor,
    tx: torch.Tensor,
    ty: torch.Tensor,
) -> torch.Tensor:
    """Weak-perspective projection: 2D = scale * (x, y) + (tx, ty).

    Args:
        pts3d: (B, N, 3) 3D points.
        scale: (B, 1) scale factor.
        tx: (B, 1) x-translation.
        ty: (B, 1) y-translation.

    Returns:
        (B, N, 2) projected 2D points.
    """
    xy = pts3d[:, :, :2]  # (B, N, 2)
    proj = scale.unsqueeze(1) * xy  # (B, N, 2)
    proj[:, :, 0] = proj[:, :, 0] + tx
    proj[:, :, 1] = proj[:, :, 1] + ty
    return proj


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

                    # Get face bounding box for crop
                    bbox = faces[0].bbox.astype(int)
                    # Expand bbox by 30%
                    bw = bbox[2] - bbox[0]
                    bh = bbox[3] - bbox[1]
                    cx = (bbox[0] + bbox[2]) // 2
                    cy = (bbox[1] + bbox[3]) // 2
                    half = int(max(bw, bh) * 0.65)
                    x1 = max(0, cx - half)
                    y1 = max(0, cy - half)
                    x2 = min(frame.shape[1], cx + half)
                    y2 = min(frame.shape[0], cy + half)
                    crop = frame[y1:y2, x1:x2]

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
        B = target_lmk.shape[0]

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

        for i in range(self.num_iters):
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

        N = len(landmarks)
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
            B = batch_end - batch_start

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

        # Also save crops for training (sample every 4th to save space)
        crops_path = output_path.parent / "face_crops.npz"
        # Resize crops to consistent size for training
        crop_size = 256
        resized_crops = []
        for crop in crops:
            if crop.shape[0] > 0 and crop.shape[1] > 0:
                resized = cv2.resize(crop, (crop_size, crop_size))
                resized_crops.append(resized)
            else:
                resized_crops.append(np.zeros((crop_size, crop_size, 3), dtype=np.uint8))
        np.savez_compressed(str(crops_path), crops=np.array(resized_crops))
        logger.info("Saved %d face crops to %s", len(resized_crops), crops_path)

        return result


def main() -> None:
    """CLI entry point for FLAME fitting."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Fit FLAME to video")
    parser.add_argument(
        "--video",
        type=str,
        default=str(
            Path.home()
            / ".clipcannon/projects/proj_2ea7221d/source/2026-04-03 04-23-11.mp4"
        ),
        help="Path to input video",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(Path.home() / ".clipcannon/models/santa/flame_params.npz"),
        help="Output path for FLAME parameters",
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
