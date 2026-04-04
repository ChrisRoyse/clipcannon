"""Cross-modal social signal detection.

Detects complex social signals (sarcasm, humor, tension, enthusiasm,
boredom) from disagreement or agreement across embedding modalities:
emotion state, prosody features, and optional semantic embeddings.

No CPU fallbacks. Errors raise BehaviorError with full context.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from phoenix.errors import BehaviorError
from phoenix.expression.emotion_fusion import EmotionState, ProsodyFeatures

# Valid social signal types.
SIGNAL_TYPES = frozenset({
    "sarcasm", "humor", "tension", "enthusiasm", "boredom", "neutral",
})


@dataclass(frozen=True)
class SocialSignal:
    """Detected social signal from cross-modal analysis.

    Attributes:
        signal_type: One of "sarcasm", "humor", "tension",
            "enthusiasm", "boredom", "neutral".
        confidence: Detection confidence [0, 1].
        sources: Which modalities contributed to the detection.
    """

    signal_type: str
    confidence: float
    sources: list[str]

    def __post_init__(self) -> None:
        """Validate signal_type and confidence range."""
        if self.signal_type not in SIGNAL_TYPES:
            raise BehaviorError(
                f"Invalid signal_type: {self.signal_type}",
                {"signal_type": self.signal_type, "valid": list(SIGNAL_TYPES)},
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise BehaviorError(
                "confidence must be in [0, 1]",
                {"confidence": self.confidence},
            )


def _clamp01(value: float) -> float:
    """Clamp a value to [0, 1]."""
    return max(0.0, min(1.0, value))


class CrossModalDetector:
    """Detects complex social signals from cross-modal embedding analysis.

    Analyzes agreement and disagreement between emotion state, prosody
    features, and optional semantic embeddings to identify social cues
    that go beyond simple emotion classification.

    Detection rules (evaluated in priority order):
    - Sarcasm: positive semantic + low arousal + falling F0.
    - Humor: high arousal + high valence + varied F0 + fast rate.
    - Tension: high arousal + low valence + high energy.
    - Enthusiasm: high arousal + high valence + high energy + rising F0.
    - Boredom: low arousal + low energy + flat F0 + slow rate.
    - Neutral: none of the above.

    Args:
        sensitivity: Detection sensitivity [0, 1]. Higher values
            lower the thresholds for signal detection. Default 0.7.

    Raises:
        BehaviorError: If sensitivity is not in [0, 1].
    """

    def __init__(self, sensitivity: float = 0.7) -> None:
        if not (0.0 <= sensitivity <= 1.0):
            raise BehaviorError(
                "sensitivity must be in [0, 1]",
                {"sensitivity": sensitivity},
            )
        self._sensitivity = sensitivity

    def detect(
        self,
        emotion: EmotionState,
        prosody: ProsodyFeatures,
        semantic_embedding: np.ndarray | None = None,
    ) -> SocialSignal:
        """Detect social signals from cross-modal analysis.

        Evaluates multiple social signal hypotheses against the provided
        modalities and returns the highest-confidence detection.

        Args:
            emotion: Fused emotion state from EmotionFusion.
            prosody: Prosody features from the current speaker.
            semantic_embedding: Optional 768-dim semantic embedding of
                the speech content. Used for sarcasm detection.

        Returns:
            The detected SocialSignal. If no signal exceeds the
            sensitivity threshold, returns "neutral".

        Raises:
            BehaviorError: If semantic_embedding is provided but is not
                a non-empty 1-D array.
        """
        if semantic_embedding is not None:
            if semantic_embedding.ndim != 1 or semantic_embedding.size == 0:
                raise BehaviorError(
                    "semantic_embedding must be a non-empty 1-D array",
                    {
                        "ndim": semantic_embedding.ndim,
                        "size": semantic_embedding.size,
                    },
                )

        # Sensitivity adjusts thresholds: higher sensitivity = lower bar.
        # A sensitivity of 0.7 means thresholds are scaled by 0.3 of their
        # full range (i.e., easier to trigger).
        threshold_scale = 1.0 - self._sensitivity

        # Minimum score to consider a signal detected. Requires a
        # majority of indicator conditions to be met. Below this
        # threshold, the signal is too weak to report.
        min_score = 0.6

        # Evaluate each signal hypothesis. Each returns (confidence, sources).
        candidates: list[tuple[str, float, list[str]]] = []

        # Sarcasm: positive semantic + low arousal + falling F0.
        sarcasm_conf, sarcasm_src = self._check_sarcasm(
            emotion, prosody, semantic_embedding, threshold_scale,
        )
        if sarcasm_conf >= min_score:
            candidates.append(("sarcasm", sarcasm_conf, sarcasm_src))

        # Enthusiasm: high arousal + high valence + high energy + rising.
        enthusiasm_conf, enthusiasm_src = self._check_enthusiasm(
            emotion, prosody, threshold_scale,
        )
        if enthusiasm_conf >= min_score:
            candidates.append(("enthusiasm", enthusiasm_conf, enthusiasm_src))

        # Humor: high arousal + high valence + varied F0 + fast.
        humor_conf, humor_src = self._check_humor(
            emotion, prosody, threshold_scale,
        )
        if humor_conf >= min_score:
            candidates.append(("humor", humor_conf, humor_src))

        # Tension: high arousal + low valence + high energy.
        tension_conf, tension_src = self._check_tension(
            emotion, prosody, threshold_scale,
        )
        if tension_conf >= min_score:
            candidates.append(("tension", tension_conf, tension_src))

        # Boredom: low arousal + low energy + flat F0 + slow rate.
        boredom_conf, boredom_src = self._check_boredom(
            emotion, prosody, threshold_scale,
        )
        if boredom_conf >= min_score:
            candidates.append(("boredom", boredom_conf, boredom_src))

        if not candidates:
            return SocialSignal(
                signal_type="neutral",
                confidence=1.0 - emotion.arousal,
                sources=["emotion"],
            )

        # Return highest-confidence candidate.
        candidates.sort(key=lambda c: c[1], reverse=True)
        best_type, best_conf, best_src = candidates[0]
        return SocialSignal(
            signal_type=best_type,
            confidence=_clamp01(best_conf),
            sources=best_src,
        )

    @staticmethod
    def _check_sarcasm(
        emotion: EmotionState,
        prosody: ProsodyFeatures,
        semantic_embedding: np.ndarray | None,
        threshold_scale: float,
    ) -> tuple[float, list[str]]:
        """Check for sarcasm signal.

        Sarcasm = positive semantic content + low arousal + falling F0.

        Args:
            emotion: Current emotion state.
            prosody: Current prosody features.
            semantic_embedding: Optional semantic embedding.
            threshold_scale: Threshold scaling factor.

        Returns:
            Tuple of (confidence, contributing sources).
        """
        if semantic_embedding is None:
            return 0.0, []

        sources: list[str] = []
        score = 0.0

        # Positive semantic: mean > 0.
        semantic_mean = float(np.mean(semantic_embedding))
        if semantic_mean > 0.0:
            score += 0.3
            sources.append("semantic")

        # Low arousal.
        arousal_threshold = 0.4 + threshold_scale * 0.2
        if emotion.arousal < arousal_threshold:
            score += 0.3
            sources.append("emotion")

        # Falling F0 contour.
        if prosody.pitch_contour_type == "falling":
            score += 0.2
            sources.append("prosody")

        # Already flagged by EmotionFusion.
        if emotion.is_sarcastic:
            score += 0.2

        return score, sources

    @staticmethod
    def _check_enthusiasm(
        emotion: EmotionState,
        prosody: ProsodyFeatures,
        threshold_scale: float,
    ) -> tuple[float, list[str]]:
        """Check for enthusiasm signal.

        Enthusiasm = high arousal + high valence + high energy + rising.

        Args:
            emotion: Current emotion state.
            prosody: Current prosody features.
            threshold_scale: Threshold scaling factor.

        Returns:
            Tuple of (confidence, contributing sources).
        """
        sources: list[str] = []
        score = 0.0

        arousal_threshold = 0.6 - threshold_scale * 0.15
        valence_threshold = 0.55 - threshold_scale * 0.1
        energy_threshold = 0.5 - threshold_scale * 0.1

        if emotion.arousal > arousal_threshold:
            score += 0.25
            sources.append("emotion")

        if emotion.valence > valence_threshold:
            score += 0.25

        if emotion.energy > energy_threshold:
            score += 0.2

        if prosody.pitch_contour_type == "rising":
            score += 0.15
            if "prosody" not in sources:
                sources.append("prosody")

        if prosody.speaking_rate_wpm > 150.0:
            score += 0.15
            if "prosody" not in sources:
                sources.append("prosody")

        return score, sources

    @staticmethod
    def _check_humor(
        emotion: EmotionState,
        prosody: ProsodyFeatures,
        threshold_scale: float,
    ) -> tuple[float, list[str]]:
        """Check for humor signal.

        Humor = high arousal + high valence + varied F0 + fast rate.

        Args:
            emotion: Current emotion state.
            prosody: Current prosody features.
            threshold_scale: Threshold scaling factor.

        Returns:
            Tuple of (confidence, contributing sources).
        """
        sources: list[str] = []
        score = 0.0

        arousal_threshold = 0.5 - threshold_scale * 0.15
        valence_threshold = 0.6 - threshold_scale * 0.1

        if emotion.arousal > arousal_threshold:
            score += 0.25
            sources.append("emotion")

        if emotion.valence > valence_threshold:
            score += 0.25

        if prosody.f0_std > 30.0 and prosody.f0_range > 80.0:
            score += 0.25
            sources.append("prosody")

        if prosody.speaking_rate_wpm > 160.0:
            score += 0.25
            if "prosody" not in sources:
                sources.append("prosody")

        return score, sources

    @staticmethod
    def _check_tension(
        emotion: EmotionState,
        prosody: ProsodyFeatures,
        threshold_scale: float,
    ) -> tuple[float, list[str]]:
        """Check for tension signal.

        Tension = high arousal + low valence + high energy.

        Args:
            emotion: Current emotion state.
            prosody: Current prosody features.
            threshold_scale: Threshold scaling factor.

        Returns:
            Tuple of (confidence, contributing sources).
        """
        sources: list[str] = []
        score = 0.0

        arousal_threshold = 0.5 - threshold_scale * 0.15
        valence_threshold = 0.45 + threshold_scale * 0.1

        if emotion.arousal > arousal_threshold:
            score += 0.3
            sources.append("emotion")

        if emotion.valence < valence_threshold:
            score += 0.3

        if prosody.energy_mean > 0.5:
            score += 0.2
            sources.append("prosody")

        if prosody.has_emphasis:
            score += 0.2
            if "prosody" not in sources:
                sources.append("prosody")

        return score, sources

    @staticmethod
    def _check_boredom(
        emotion: EmotionState,
        prosody: ProsodyFeatures,
        threshold_scale: float,
    ) -> tuple[float, list[str]]:
        """Check for boredom signal.

        Boredom = low arousal + low energy + flat F0 + slow rate.

        Args:
            emotion: Current emotion state.
            prosody: Current prosody features.
            threshold_scale: Threshold scaling factor.

        Returns:
            Tuple of (confidence, contributing sources).
        """
        sources: list[str] = []
        score = 0.0

        arousal_threshold = 0.3 + threshold_scale * 0.15
        energy_threshold = 0.3 + threshold_scale * 0.1

        if emotion.arousal < arousal_threshold:
            score += 0.25
            sources.append("emotion")

        if emotion.energy < energy_threshold:
            score += 0.25

        if prosody.pitch_contour_type == "flat":
            score += 0.25
            sources.append("prosody")

        if prosody.speaking_rate_wpm < 120.0:
            score += 0.25
            if "prosody" not in sources:
                sources.append("prosody")

        return score, sources
