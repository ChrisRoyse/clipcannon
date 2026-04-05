"""Best-of-N frame selection using GPU-accelerated scoring.

Evaluates N candidate blendshape parameter sets, renders quick proxy
frames, and selects the best one based on perceptual quality metrics
computed entirely on GPU via CuPy kernels.

Scoring metrics:
  - Sharpness: Laplacian variance (higher = sharper)
  - Temporal coherence: L2 distance to previous frame (lower = smoother)
  - Symmetry: Left-right mirror difference (lower = more symmetric)

Usage:
    selector = FrameSelector(n_candidates=4)
    best_idx = selector.select_best(candidate_frames)
    best_frame = candidate_frames[best_idx]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cupy as cp

logger = logging.getLogger(__name__)

# Laplacian kernel for sharpness detection (3x3)
_LAPLACIAN_KERNEL = cp.array(
    [[0, 1, 0], [1, -4, 1], [0, 1, 0]],
    dtype=cp.float32,
)


@dataclass
class FrameScore:
    """Per-frame quality scores (all in [0, 1] after normalization)."""

    sharpness: float = 0.0
    temporal_coherence: float = 0.0
    symmetry: float = 0.0
    composite: float = 0.0


class FrameSelector:
    """Select the best frame from N candidates using GPU scoring.

    Quality metrics are computed entirely on GPU via CuPy. The
    composite score is a weighted sum of individual metrics.

    Args:
        n_candidates: Number of candidate frames to evaluate.
            1 = no selection (passthrough), 4 = moderate, 8 = high.
        sharpness_weight: Weight for sharpness in composite score.
        coherence_weight: Weight for temporal coherence.
        symmetry_weight: Weight for bilateral symmetry.
    """

    def __init__(
        self,
        n_candidates: int = 1,
        sharpness_weight: float = 0.4,
        coherence_weight: float = 0.35,
        symmetry_weight: float = 0.25,
    ) -> None:
        if n_candidates < 1:
            raise ValueError("n_candidates must be >= 1")

        self.n_candidates = n_candidates
        self.sharpness_weight = sharpness_weight
        self.coherence_weight = coherence_weight
        self.symmetry_weight = symmetry_weight

        # Cache previous frame for temporal coherence
        self._prev_frame: cp.ndarray | None = None

        # Stats
        self._total_selections = 0
        self._total_candidates_evaluated = 0

        logger.info(
            "FrameSelector: N=%d, weights=(sharp=%.2f, coher=%.2f, sym=%.2f)",
            n_candidates,
            sharpness_weight,
            coherence_weight,
            symmetry_weight,
        )

    def score_sharpness(self, frame: cp.ndarray) -> float:
        """Compute sharpness as Laplacian variance on GPU.

        Converts to grayscale, applies 3x3 Laplacian, returns variance.
        Higher values indicate sharper images.

        Args:
            frame: GPU array, float32, shape (H, W, 3).

        Returns:
            Sharpness score (unnormalized variance).
        """
        # Convert to grayscale: 0.299R + 0.587G + 0.114B
        gray = (
            frame[:, :, 0] * 0.299
            + frame[:, :, 1] * 0.587
            + frame[:, :, 2] * 0.114
        )

        h, w = gray.shape
        if h < 3 or w < 3:
            return 0.0

        # Manual 3x3 Laplacian convolution (avoids scipy dependency)
        # Pad with zeros
        padded = cp.zeros((h + 2, w + 2), dtype=cp.float32)
        padded[1:-1, 1:-1] = gray

        laplacian = (
            padded[0:-2, 1:-1]  # top
            + padded[2:, 1:-1]  # bottom
            + padded[1:-1, 0:-2]  # left
            + padded[1:-1, 2:]  # right
            - 4.0 * padded[1:-1, 1:-1]  # center
        )

        variance = float(cp.var(laplacian).get())
        return variance

    def score_temporal_coherence(self, frame: cp.ndarray) -> float:
        """Compute temporal coherence as inverse L2 distance to prev frame.

        Lower L2 distance means smoother motion. Returns a score where
        higher = more coherent. If no previous frame exists, returns 1.0.

        Args:
            frame: GPU array, float32, shape (H, W, 3).

        Returns:
            Coherence score in (0, 1]. 1.0 = identical to previous.
        """
        if self._prev_frame is None:
            return 1.0

        # Compute mean squared error
        if self._prev_frame.shape != frame.shape:
            return 1.0

        mse = float(cp.mean((frame - self._prev_frame) ** 2).get())
        # Convert to coherence: 1 / (1 + mse * scale)
        # Scale factor tuned for float32 [0, 1] images
        coherence = 1.0 / (1.0 + mse * 100.0)
        return coherence

    def score_symmetry(self, frame: cp.ndarray) -> float:
        """Compute bilateral symmetry as inverse mirror-difference.

        Flips the frame horizontally and computes the mean absolute
        difference. Lower difference = more symmetric face.

        Args:
            frame: GPU array, float32, shape (H, W, 3).

        Returns:
            Symmetry score in (0, 1]. 1.0 = perfectly symmetric.
        """
        flipped = frame[:, ::-1, :]
        mad = float(cp.mean(cp.abs(frame - flipped)).get())
        # Convert to symmetry score
        symmetry = 1.0 / (1.0 + mad * 10.0)
        return symmetry

    def score_frame(self, frame: cp.ndarray) -> FrameScore:
        """Compute all quality metrics for a single frame.

        Args:
            frame: GPU array, float32, shape (H, W, 3).

        Returns:
            FrameScore with individual and composite scores.
        """
        sharpness = self.score_sharpness(frame)
        coherence = self.score_temporal_coherence(frame)
        symmetry = self.score_symmetry(frame)

        # Normalize sharpness to [0, 1] range using sigmoid-like mapping
        # Typical Laplacian variance for face images: 0.001 - 0.1
        norm_sharpness = min(1.0, sharpness / 0.05)

        composite = (
            self.sharpness_weight * norm_sharpness
            + self.coherence_weight * coherence
            + self.symmetry_weight * symmetry
        )

        return FrameScore(
            sharpness=norm_sharpness,
            temporal_coherence=coherence,
            symmetry=symmetry,
            composite=composite,
        )

    def select_best(
        self,
        candidates: list[cp.ndarray],
    ) -> int:
        """Select the best frame from a list of candidates.

        Scores each candidate and returns the index of the frame with
        the highest composite score. Updates the internal previous-frame
        cache with the selected frame.

        Args:
            candidates: List of GPU arrays, each float32 (H, W, 3).

        Returns:
            Index of the best candidate frame.

        Raises:
            ValueError: If candidates list is empty.
        """
        if not candidates:
            raise ValueError("candidates list must not be empty")

        if len(candidates) == 1:
            self._prev_frame = candidates[0]
            self._total_selections += 1
            self._total_candidates_evaluated += 1
            return 0

        scores = []
        for i, frame in enumerate(candidates):
            score = self.score_frame(frame)
            scores.append(score)

        # Find best composite score
        best_idx = max(range(len(scores)), key=lambda i: scores[i].composite)

        # Update previous frame for temporal coherence
        self._prev_frame = candidates[best_idx]

        self._total_selections += 1
        self._total_candidates_evaluated += len(candidates)

        logger.debug(
            "FrameSelector: best=%d/%d (composite=%.3f, "
            "sharp=%.3f, coher=%.3f, sym=%.3f)",
            best_idx,
            len(candidates),
            scores[best_idx].composite,
            scores[best_idx].sharpness,
            scores[best_idx].temporal_coherence,
            scores[best_idx].symmetry,
        )

        return best_idx

    def select_best_blendshapes(
        self,
        blendshape_sets: list[cp.ndarray],
        render_fn: callable,
    ) -> int:
        """Score N blendshape parameter sets by rendering proxy frames.

        Higher-level API: takes blendshape parameters, renders each
        one, and returns the index of the best result.

        Args:
            blendshape_sets: List of (52,) blendshape parameter arrays.
            render_fn: Callable that takes blendshapes and returns a
                (H, W, 3) float32 GPU frame.

        Returns:
            Index of the best blendshape parameter set.
        """
        candidates = [render_fn(bs) for bs in blendshape_sets]
        return self.select_best(candidates)

    @property
    def avg_candidates_per_selection(self) -> float:
        if self._total_selections == 0:
            return 0.0
        return self._total_candidates_evaluated / self._total_selections
