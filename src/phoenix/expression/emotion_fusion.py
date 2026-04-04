"""Cross-modal emotion fusion from embedding streams.

Fuses Wav2Vec2 emotion embeddings (1024-dim), prosody features (12 scalars),
and optional Nomic semantic embeddings (768-dim) into a unified EmotionState
that drives avatar facial expressions and behavior.

No CPU fallbacks. Errors raise ExpressionError with full context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from phoenix.errors import ExpressionError

ProsodyStyle = Literal[
    "energetic", "calm", "emphatic", "varied", "question"
]


@dataclass(frozen=True)
class ProsodyFeatures:
    """Twelve scalar prosody features extracted from audio.

    Attributes:
        f0_mean: Mean fundamental frequency in Hz.
        f0_std: Standard deviation of F0 in Hz.
        f0_min: Minimum F0 in Hz.
        f0_max: Maximum F0 in Hz.
        f0_range: F0 range (max - min) in Hz.
        energy_mean: Mean RMS energy [0, 1].
        energy_peak: Peak RMS energy [0, 1].
        energy_std: Standard deviation of energy [0, 1].
        speaking_rate_wpm: Speaking rate in words per minute.
        pitch_contour_type: Contour shape: "rising", "falling", "flat",
            "varied".
        has_emphasis: Whether emphasis was detected.
        has_breath: Whether breath was detected.
    """

    f0_mean: float
    f0_std: float
    f0_min: float
    f0_max: float
    f0_range: float
    energy_mean: float
    energy_peak: float
    energy_std: float
    speaking_rate_wpm: float
    pitch_contour_type: str
    has_emphasis: bool
    has_breath: bool


@dataclass(frozen=True)
class EmotionState:
    """Fused cross-modal emotion state.

    All scalar fields are clamped to [0, 1].

    Attributes:
        arousal: Activation level derived from emotion embedding variance.
        valence: Positivity derived from emotion embedding mean.
        energy: Intensity derived from emotion embedding L2 norm.
        dominance: Assertiveness from prosody energy + F0 range.
        prosody_style: Detected prosody style label.
        is_sarcastic: True when semantic says positive but voice says
            negative.
        confidence: Fusion confidence [0, 1].
    """

    arousal: float
    valence: float
    energy: float
    dominance: float
    prosody_style: ProsodyStyle
    is_sarcastic: bool
    confidence: float


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a scalar to [lo, hi]."""
    return max(lo, min(hi, value))


def _classify_prosody_style(prosody: ProsodyFeatures) -> ProsodyStyle:
    """Determine prosody style from prosody features.

    Args:
        prosody: Prosody feature set.

    Returns:
        One of the five prosody style labels.
    """
    if prosody.pitch_contour_type == "rising":
        return "question"
    if prosody.has_emphasis and prosody.energy_peak > 0.7:
        return "emphatic"
    if prosody.energy_mean > 0.6 and prosody.speaking_rate_wpm > 160:
        return "energetic"
    if prosody.f0_std > 30.0 and prosody.f0_range > 80.0:
        return "varied"
    return "calm"


def _detect_sarcasm(
    semantic_embedding: np.ndarray | None,
    arousal: float,
    prosody: ProsodyFeatures,
    sensitivity: float,
) -> bool:
    """Detect sarcasm via cross-modal mismatch.

    Sarcasm occurs when semantic content is positive but vocal delivery
    is low-energy with falling pitch. Uses a simple positive-centroid
    heuristic on the semantic embedding.

    Args:
        semantic_embedding: 768-dim Nomic semantic embedding, or None.
        arousal: Computed arousal value [0, 1].
        prosody: Prosody feature set.
        sensitivity: Threshold for sarcasm detection [0, 1].

    Returns:
        True if sarcasm is detected.
    """
    if semantic_embedding is None:
        return False

    # Positive semantic heuristic: mean of embedding > 0 indicates
    # positive sentiment (simplified centroid comparison).
    semantic_mean = float(np.mean(semantic_embedding))
    semantic_positive = semantic_mean > 0.0

    vocal_negative = (
        arousal < (1.0 - sensitivity)
        and prosody.pitch_contour_type == "falling"
    )

    return semantic_positive and vocal_negative


class EmotionFusion:
    """Cross-modal emotion fusion engine.

    Fuses Wav2Vec2 emotion embeddings with prosody features and optional
    semantic embeddings to produce a unified EmotionState. Maintains an
    internal state with exponential moving average smoothing.

    Args:
        ema_alpha: Smoothing factor for exponential moving average.
            Range (0, 1]. Higher values favor new observations.
        sarcasm_sensitivity: Sensitivity threshold for cross-modal
            sarcasm detection [0, 1].
        norm_ceiling: Expected max L2 norm for emotion embeddings,
            used to normalize energy to [0, 1].

    Raises:
        ExpressionError: If ema_alpha is not in (0, 1].
    """

    def __init__(
        self,
        ema_alpha: float = 0.3,
        sarcasm_sensitivity: float = 0.7,
        norm_ceiling: float = 50.0,
    ) -> None:
        if not (0.0 < ema_alpha <= 1.0):
            raise ExpressionError(
                "ema_alpha must be in (0, 1]",
                {"ema_alpha": ema_alpha},
            )
        self._alpha = ema_alpha
        self._sarcasm_sensitivity = sarcasm_sensitivity
        self._norm_ceiling = norm_ceiling
        self._state: EmotionState | None = None

    @property
    def current_state(self) -> EmotionState | None:
        """Return the current smoothed emotion state, or None if unset."""
        return self._state

    def fuse(
        self,
        emotion_embedding: np.ndarray,
        prosody: ProsodyFeatures,
        semantic_embedding: np.ndarray | None = None,
    ) -> EmotionState:
        """Fuse embedding streams into an EmotionState.

        Args:
            emotion_embedding: 1024-dim Wav2Vec2 emotion embedding.
            prosody: 12-field prosody feature set.
            semantic_embedding: Optional 768-dim Nomic semantic embedding.

        Returns:
            Fused EmotionState with all fields clamped to [0, 1].

        Raises:
            ExpressionError: If emotion_embedding is not 1-D or empty.
        """
        if emotion_embedding.ndim != 1 or emotion_embedding.size == 0:
            raise ExpressionError(
                "emotion_embedding must be a non-empty 1-D array",
                {
                    "ndim": emotion_embedding.ndim,
                    "size": emotion_embedding.size,
                },
            )
        if emotion_embedding.shape[0] != 1024:
            raise ExpressionError(
                f"emotion_embedding must be 1024-dim, got {emotion_embedding.shape[0]}",
                {
                    "expected": 1024,
                    "got": emotion_embedding.shape[0],
                },
            )
        if (
            semantic_embedding is not None
            and (semantic_embedding.ndim != 1 or semantic_embedding.size == 0)
        ):
            raise ExpressionError(
                "semantic_embedding must be a non-empty 1-D array",
                {
                    "ndim": semantic_embedding.ndim,
                    "size": semantic_embedding.size,
                },
            )
        if (
            semantic_embedding is not None
            and semantic_embedding.shape[0] != 768
        ):
            raise ExpressionError(
                f"semantic_embedding must be 768-dim, got {semantic_embedding.shape[0]}",
                {
                    "expected": 768,
                    "got": semantic_embedding.shape[0],
                },
            )

        # Arousal: variance of embedding (higher variance = more activated).
        raw_variance = float(np.var(emotion_embedding))
        arousal = _clamp(raw_variance / (raw_variance + 1.0))

        # Valence: centered mean (shift to [0, 1] range).
        raw_mean = float(np.mean(emotion_embedding))
        valence = _clamp(0.5 + raw_mean * 0.1)

        # Energy: L2 norm normalized by ceiling.
        raw_norm = float(np.linalg.norm(emotion_embedding))
        energy = _clamp(raw_norm / self._norm_ceiling)

        # Dominance: from prosody energy + F0 range.
        f0_dominance = _clamp(prosody.f0_range / 200.0)
        energy_dominance = prosody.energy_mean
        dominance = _clamp(0.6 * energy_dominance + 0.4 * f0_dominance)

        # Prosody style classification.
        prosody_style = _classify_prosody_style(prosody)

        # Sarcasm detection.
        is_sarcastic = _detect_sarcasm(
            semantic_embedding, arousal, prosody, self._sarcasm_sensitivity,
        )

        # Confidence: based on embedding magnitude and prosody consistency.
        has_semantic = semantic_embedding is not None
        base_confidence = 0.6 if not has_semantic else 0.8
        norm_factor = min(1.0, raw_norm / (self._norm_ceiling * 0.5))
        confidence = _clamp(base_confidence * norm_factor)

        return EmotionState(
            arousal=arousal,
            valence=valence,
            energy=energy,
            dominance=dominance,
            prosody_style=prosody_style,
            is_sarcastic=is_sarcastic,
            confidence=confidence,
        )

    def update(self, new_state: EmotionState) -> EmotionState:
        """Apply exponential moving average smoothing.

        Blends the new state with the internal state using alpha weighting.
        On the first call (no prior state), the new state is returned
        unchanged.

        Args:
            new_state: Freshly fused EmotionState.

        Returns:
            Smoothed EmotionState.
        """
        if self._state is None:
            self._state = new_state
            return new_state

        a = self._alpha
        prev = self._state

        smoothed = EmotionState(
            arousal=_clamp(a * new_state.arousal + (1 - a) * prev.arousal),
            valence=_clamp(a * new_state.valence + (1 - a) * prev.valence),
            energy=_clamp(a * new_state.energy + (1 - a) * prev.energy),
            dominance=_clamp(
                a * new_state.dominance + (1 - a) * prev.dominance
            ),
            prosody_style=new_state.prosody_style,
            is_sarcastic=new_state.is_sarcastic,
            confidence=_clamp(
                a * new_state.confidence + (1 - a) * prev.confidence
            ),
        )

        self._state = smoothed
        return smoothed

    def reset(self) -> None:
        """Clear the internal smoothed state."""
        self._state = None
