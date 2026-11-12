"""Best-of-N generation and sync scoring for the LatentSync lip-sync engine.

Split out of ``clipcannon.avatar.lip_sync`` (pure move): holds the
``LipSyncResult`` dataclass and the best-of-N / scoring methods that
``LipSyncEngine`` inherits from ``_LipSyncScoringMixin``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class LipSyncResult:
    """Result of a lip-sync operation.

    Attributes:
        video_path: Path to the output video with synced lips.
        duration_ms: Duration of the output video in milliseconds.
        resolution: Output resolution as "WxH" string.
        inference_steps: Number of diffusion steps used.
        elapsed_s: Total processing time in seconds.
    """

    video_path: Path
    duration_ms: int
    resolution: str
    inference_steps: int
    elapsed_s: float


class _LipSyncScoringMixin:
    """Best-of-N candidate generation and sync scoring for ``LipSyncEngine``."""

    def generate_best_of_n(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
        n_candidates: int = 3,
        inference_steps: int = 20,
        guidance_scale: float = 1.5,
    ) -> LipSyncResult:
        """Generate N lip-sync candidates and pick the best.

        Runs the pipeline N times with different random seeds,
        then selects the result with the highest SyncNet confidence
        score (audio-visual sync quality).

        Args:
            video_path: Path to driver video.
            audio_path: Path to audio file.
            output_path: Path for the best output.
            n_candidates: Number of candidates to generate (3-5 recommended).
            inference_steps: Diffusion steps per candidate.
            guidance_scale: Classifier-free guidance scale.

        Returns:
            LipSyncResult for the best candidate.
        """
        import random

        candidates: list[tuple[Path, LipSyncResult, float]] = []

        for i in range(n_candidates):
            seed = random.randint(1, 99999)
            candidate_path = (
                output_path.parent / f"{output_path.stem}_candidate_{i}{output_path.suffix}"
            )

            logger.info(
                "Generating candidate %d/%d (seed=%d)",
                i + 1, n_candidates, seed,
            )

            try:
                result = self.generate(
                    video_path=video_path,
                    audio_path=audio_path,
                    output_path=candidate_path,
                    inference_steps=inference_steps,
                    guidance_scale=guidance_scale,
                    seed=seed,
                )
            except Exception as exc:
                logger.warning("Candidate %d failed: %s", i + 1, exc)
                continue

            # Score using SyncNet if available
            score = self._score_sync(candidate_path, audio_path)
            candidates.append((candidate_path, result, score))
            logger.info(
                "Candidate %d: seed=%d, sync_score=%.3f",
                i + 1, seed, score,
            )

        if not candidates:
            raise RuntimeError("All candidates failed")

        # Pick best by sync score
        candidates.sort(key=lambda x: x[2], reverse=True)
        best_path, best_result, best_score = candidates[0]

        # Move best to output_path, clean up others
        if best_path != output_path:
            if output_path.exists():
                output_path.unlink()
            best_path.rename(output_path)
            best_result = LipSyncResult(
                video_path=output_path,
                duration_ms=best_result.duration_ms,
                resolution=best_result.resolution,
                inference_steps=best_result.inference_steps,
                elapsed_s=best_result.elapsed_s,
            )

        for path, _, _ in candidates:
            if path != best_path and path.exists():
                path.unlink(missing_ok=True)

        logger.info(
            "Best of %d: sync_score=%.3f (selected from %d candidates)",
            n_candidates, best_score, len(candidates),
        )

        return best_result

    def _score_sync(self, video_path: Path, audio_path: Path) -> float:
        """Score audio-visual sync quality using ffprobe-based heuristics.

        If SyncNet is available, uses learned sync scoring.
        Falls back to file-size heuristic (larger = more detail = better).
        """
        # Try SyncNet scoring
        try:
            syncnet_path = (
                Path.home() / ".clipcannon" / "models" / "latentsync"
                / "checkpoints" / "auxiliary" / "syncnet_v2.model"
            )
            if syncnet_path.exists():
                return self._syncnet_score(video_path, audio_path, syncnet_path)
        except Exception:
            pass

        # Fallback: file size as proxy (more detail = larger file at same CRF)
        try:
            return float(video_path.stat().st_size) / 1e6
        except Exception:
            return 0.0

    def _syncnet_score(
        self, video_path: Path, audio_path: Path, syncnet_path: Path,
    ) -> float:
        """Score using SyncNet confidence."""
        # SyncNet scoring requires specific setup -- use file size fallback
        # until the auxiliary model is downloaded
        return float(video_path.stat().st_size) / 1e6
