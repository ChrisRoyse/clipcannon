"""Teleological Constellation Guardrail for generated video frames.

Validates every generated frame against Santa's 7-embedding identity
constellation before accepting it for output. Frames that deviate
too far from the known constellation centroids are REJECTED.

This is a runtime validator, NOT a training loss. It sits between
the video generation model and the output stream.

Architecture:
    Generated Frame -> Re-embed through frozen models -> Compare to constellation -> Accept/Reject

Uses cosine similarity against pre-computed constellation centroids
from the 7-modality embedding system (SigLIP visual, WavLM speaker,
emotion, prosody, sentiment, voice, FLAME expression).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from phoenix.video.constellation_embed import FRAME_RESIZE as FRAME_RESIZE
from phoenix.video.constellation_embed import SIGLIP_MODEL_ID as SIGLIP_MODEL_ID
from phoenix.video.constellation_embed import SIGLIP_VRAM_MB as SIGLIP_VRAM_MB
from phoenix.video.constellation_embed import _VisualEmbeddingMixin

logger = logging.getLogger(__name__)

# --- Offline mode BEFORE any transformers import ---
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

# Modality keys in all_embeddings.npz
MODALITY_KEYS = {
    "visual": "vis_emb",
    "semantic": "sem_emb",
    "emotion": "emo_emb",
    "speaker": "spk_emb",
    "prosody": "pro_data",
    "sentiment": "sent_emb",
    "voice": "voice_emb",
}


# Default thresholds per modality (cosine similarity minimums)
DEFAULT_THRESHOLDS = {
    "visual": 0.70,
    "emotion": 0.60,
    "speaker": 0.80,
    "voice": 0.85,
}

# Visual severity tiers
VISUAL_WARN = 0.80
VISUAL_STRONG = 0.90


@dataclass
class ValidationResult:
    """Result of validating a single frame against the constellation."""

    valid: bool
    visual_similarity: float
    details: dict[str, float] = field(default_factory=dict)
    rejection_reason: str | None = None


class ConstellationGuard(_VisualEmbeddingMixin):
    """Validates generated video frames against Santa's teleological constellation.

    Rejects frames that deviate too far from the known identity embeddings.
    Uses cosine similarity against pre-computed constellation centroids
    from the 7-embedding system.
    """

    def __init__(
        self,
        constellation_path: str,
        thresholds: dict[str, float] | None = None,
    ) -> None:
        """Load the constellation centroids from the all_embeddings.npz file.

        Computes mean centroids and spread (std) for each modality.
        Spread is used for adaptive threshold adjustment.

        Args:
            constellation_path: Path to all_embeddings.npz with 7 modalities.
            thresholds: Per-modality cosine similarity thresholds.
                        Default: visual=0.7, emotion=0.6, speaker=0.8, voice=0.85
        """
        if not os.path.isfile(constellation_path):
            raise FileNotFoundError(
                f"Constellation file not found: {constellation_path}"
            )

        self._constellation_path = constellation_path
        self._thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

        # Load and compute centroids
        data = np.load(constellation_path)
        self._centroids: dict[str, np.ndarray] = {}
        self._spreads: dict[str, float] = {}
        self._counts: dict[str, int] = {}

        for modality_name, npz_key in MODALITY_KEYS.items():
            if npz_key not in data:
                logger.warning(
                    "Modality '%s' (key '%s') not found in constellation",
                    modality_name,
                    npz_key,
                )
                continue

            emb = data[npz_key].astype(np.float32)
            if emb.ndim != 2:
                logger.warning(
                    "Skipping modality '%s': expected 2D array, got %dD",
                    modality_name,
                    emb.ndim,
                )
                continue

            # L2-normalize each embedding before computing centroid
            norms = np.linalg.norm(emb, axis=1, keepdims=True)
            norms = np.maximum(norms, 1e-8)
            normed = emb / norms

            # Centroid is the mean of normalized embeddings, then re-normalized
            centroid = np.mean(normed, axis=0)
            centroid_norm = np.linalg.norm(centroid)
            if centroid_norm < 1e-8:
                logger.warning(
                    "Zero centroid for modality '%s', skipping",
                    modality_name,
                )
                continue
            centroid = centroid / centroid_norm

            # Spread: mean of per-embedding cosine distances from centroid
            sims = normed @ centroid
            spread = float(np.std(sims))

            self._centroids[modality_name] = centroid
            self._spreads[modality_name] = spread
            self._counts[modality_name] = emb.shape[0]

            logger.info(
                "Constellation '%s': %d samples, dim=%d, "
                "cos_sim range=[%.4f, %.4f], mean=%.4f, std=%.4f",
                modality_name,
                emb.shape[0],
                emb.shape[1],
                float(np.min(sims)),
                float(np.max(sims)),
                float(np.mean(sims)),
                spread,
            )

        if "visual" not in self._centroids:
            raise RuntimeError(
                "Visual centroid is required but missing from constellation. "
                f"Available modalities: {list(self._centroids.keys())}"
            )

        logger.info(
            "ConstellationGuard loaded: %d modalities, thresholds=%s",
            len(self._centroids),
            self._thresholds,
        )

        # SigLIP encoder loaded lazily
        self._model = None
        self._processor = None
        self._device: str | None = None

    def validate_frame(self, frame_rgb: np.ndarray) -> ValidationResult:
        """Validate a single RGB frame against the constellation.

        Re-embeds the frame through frozen SigLIP and compares the
        resulting embedding to Santa's visual centroid via cosine
        similarity.

        Args:
            frame_rgb: HWC uint8 RGB numpy array.

        Returns:
            ValidationResult with:
            - valid: bool (True if visual similarity >= threshold)
            - visual_similarity: float (cosine sim to Santa's visual centroid)
            - details: dict with per-modality scores (visual only at runtime)
            - rejection_reason: str | None
        """
        emb = self._embed_frame(frame_rgb)
        vis_centroid = self._centroids["visual"]
        vis_sim = self._cosine_similarity(emb, vis_centroid)

        threshold = self._thresholds.get("visual", DEFAULT_THRESHOLDS["visual"])
        details: dict[str, float] = {"visual": vis_sim}

        # Determine validity
        valid = vis_sim >= threshold
        rejection_reason: str | None = None

        if not valid:
            rejection_reason = (
                f"Visual similarity {vis_sim:.4f} below threshold {threshold:.4f}"
            )
            logger.warning(
                "REJECTED frame: %s (visual_sim=%.4f, threshold=%.4f)",
                rejection_reason,
                vis_sim,
                threshold,
            )
        elif vis_sim < VISUAL_WARN:
            logger.info(
                "Frame ACCEPTED (borderline): visual_sim=%.4f "
                "(threshold=%.4f, warn=%.4f)",
                vis_sim,
                threshold,
                VISUAL_WARN,
            )
        elif vis_sim < VISUAL_STRONG:
            logger.info(
                "Frame ACCEPTED (good): visual_sim=%.4f", vis_sim
            )
        else:
            logger.info(
                "Frame ACCEPTED (strong): visual_sim=%.4f", vis_sim
            )

        return ValidationResult(
            valid=valid,
            visual_similarity=vis_sim,
            details=details,
            rejection_reason=rejection_reason,
        )

    def validate_batch(self, frames: list[np.ndarray]) -> list[ValidationResult]:
        """Validate a batch of frames efficiently.

        Embeds all frames in a single forward pass, then compares
        each to the constellation centroid.

        Args:
            frames: List of HWC uint8 RGB numpy arrays.

        Returns:
            List of ValidationResult, one per frame.
        """
        if not frames:
            return []

        embeddings = self._embed_batch(frames)
        vis_centroid = self._centroids["visual"]
        threshold = self._thresholds.get("visual", DEFAULT_THRESHOLDS["visual"])

        results: list[ValidationResult] = []
        accepted = 0
        rejected = 0

        for i, emb in enumerate(embeddings):
            vis_sim = self._cosine_similarity(emb, vis_centroid)
            details: dict[str, float] = {"visual": vis_sim}

            valid = vis_sim >= threshold
            rejection_reason: str | None = None

            if not valid:
                rejection_reason = (
                    f"Visual similarity {vis_sim:.4f} below threshold {threshold:.4f}"
                )
                rejected += 1
                logger.warning(
                    "REJECTED frame %d/%d: %s",
                    i + 1,
                    len(frames),
                    rejection_reason,
                )
            else:
                accepted += 1

            results.append(
                ValidationResult(
                    valid=valid,
                    visual_similarity=vis_sim,
                    details=details,
                    rejection_reason=rejection_reason,
                )
            )

        logger.info(
            "Batch validation: %d/%d accepted, %d/%d rejected "
            "(threshold=%.4f)",
            accepted,
            len(frames),
            rejected,
            len(frames),
            threshold,
        )

        return results

    def validate_audio(
        self,
        audio_embedding: np.ndarray,
        modality: str = "speaker",
    ) -> ValidationResult:
        """Validate an audio embedding against speaker/voice centroids.

        Used when TTS audio is available to verify the voice matches
        Santa's identity constellation.

        Args:
            audio_embedding: Pre-computed audio embedding (e.g. WavLM 512d
                            for speaker, or 192d for voice).
            modality: Which audio modality to check ("speaker" or "voice").

        Returns:
            ValidationResult with similarity scores.
        """
        if modality not in self._centroids:
            raise ValueError(
                f"Modality '{modality}' not available in constellation. "
                f"Available: {list(self._centroids.keys())}"
            )

        centroid = self._centroids[modality]

        # L2-normalize the input
        norm = np.linalg.norm(audio_embedding)
        if norm < 1e-8:
            return ValidationResult(
                valid=False,
                visual_similarity=0.0,
                details={modality: 0.0},
                rejection_reason=f"Zero-norm {modality} embedding",
            )
        normed = audio_embedding / norm

        sim = self._cosine_similarity(normed, centroid)
        threshold = self._thresholds.get(modality, 0.5)
        valid = sim >= threshold

        details: dict[str, float] = {modality: sim}
        rejection_reason: str | None = None

        if not valid:
            rejection_reason = (
                f"{modality} similarity {sim:.4f} below threshold {threshold:.4f}"
            )
            logger.warning("REJECTED audio: %s", rejection_reason)
        else:
            logger.info(
                "Audio ACCEPTED (%s): sim=%.4f (threshold=%.4f)",
                modality,
                sim,
                threshold,
            )

        return ValidationResult(
            valid=valid,
            visual_similarity=sim,
            details=details,
            rejection_reason=rejection_reason,
        )

    def get_constellation_stats(self) -> dict[str, Any]:
        """Return the constellation centroid statistics for debugging.

        Returns:
            Dict with per-modality centroid dimensions, sample counts,
            spread values, and configured thresholds.
        """
        stats: dict[str, Any] = {
            "constellation_path": self._constellation_path,
            "thresholds": dict(self._thresholds),
            "modalities": {},
        }

        for name, centroid in self._centroids.items():
            stats["modalities"][name] = {
                "dim": int(centroid.shape[0]),
                "samples": self._counts.get(name, 0),
                "spread_std": self._spreads.get(name, 0.0),
                "threshold": self._thresholds.get(name, "N/A"),
                "centroid_norm": float(np.linalg.norm(centroid)),
            }

        return stats

    def unload(self) -> None:
        """Unload the SigLIP model and free GPU memory."""
        if self._model is not None:
            from phoenix.video.gpu_guard import gpu_cleanup, log_vram, safe_del

            log_vram("before_siglip_unload")
            safe_del(self._model)
            self._model = None
            self._processor = None
            self._device = None
            gpu_cleanup()
            log_vram("after_siglip_unload")
            logger.info("SigLIP model unloaded")
