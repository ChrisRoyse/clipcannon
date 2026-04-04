"""Emotion mirroring for avatar facial expression parameters.

Maps room emotion state and prosody features to avatar facial
expression blend shapes and head motion parameters. Supports both
listening mode (mirroring the room) and speaking mode (driven by
the avatar's own prosody).

No CPU fallbacks. Errors raise BehaviorError with full context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from phoenix.errors import BehaviorError
from phoenix.expression.emotion_fusion import ProsodyFeatures

if TYPE_CHECKING:
    from phoenix.expression.emotion_fusion import EmotionState


@dataclass(frozen=True)
class AvatarExpression:
    """Avatar facial expression parameters.

    All float fields are clamped to their stated ranges.

    Attributes:
        jaw_open: Jaw opening amount [0, 1].
        brow_raise: Brow raise amount [0, 1].
        brow_furrow: Brow furrow amount [0, 1].
        mouth_stretch: Smile / mouth stretch [0, 1].
        head_nod_intensity: Head nod strength [0, 1].
        head_tilt: Head tilt [-1, 1], negative=left, positive=right.
        eye_wide: Eye wideness / surprise [0, 1].
        squint: Eye squint amount [0, 1].
    """

    jaw_open: float
    brow_raise: float
    brow_furrow: float
    mouth_stretch: float
    head_nod_intensity: float
    head_tilt: float
    eye_wide: float
    squint: float


def _clamp01(value: float) -> float:
    """Clamp a value to [0, 1]."""
    return max(0.0, min(1.0, value))


def _clamp_sym(value: float) -> float:
    """Clamp a value to [-1, 1]."""
    return max(-1.0, min(1.0, value))


def _normalize_f0(f0: float, lo: float = 80.0, hi: float = 400.0) -> float:
    """Normalize F0 from Hz range to [0, 1].

    Args:
        f0: Fundamental frequency in Hz.
        lo: Low end of expected range.
        hi: High end of expected range.

    Returns:
        Normalized value in [0, 1].
    """
    if hi <= lo:
        return 0.0
    return _clamp01((f0 - lo) / (hi - lo))


class EmotionMirror:
    """Maps room emotion state to avatar facial expression parameters.

    Converts EmotionState (from the expression layer) into concrete
    blend shape and head motion values for the avatar renderer. Supports
    two modes:

    - Listening: mirrors the room's emotion (empathetic reactions).
    - Speaking: driven by the avatar's own prosody features.

    All output values are scaled by mirror_intensity to control how
    expressive the avatar is overall.

    Args:
        mirror_intensity: Global scaling factor for all expression
            parameters [0, 1]. Default 0.6 for natural subtlety.

    Raises:
        BehaviorError: If mirror_intensity is not in [0, 1].
    """

    def __init__(self, mirror_intensity: float = 0.6) -> None:
        if not (0.0 <= mirror_intensity <= 1.0):
            raise BehaviorError(
                "mirror_intensity must be in [0, 1]",
                {"mirror_intensity": mirror_intensity},
            )
        self._intensity = mirror_intensity

    def mirror(
        self,
        emotion: EmotionState,
        is_speaking: bool = False,
    ) -> AvatarExpression:
        """Convert emotion state to avatar expression parameters.

        When NOT speaking (listening):
        - Mirror room emotion: high arousal -> raised eyebrows, wide eyes.
        - Mirror valence: positive -> slight smile, negative -> furrow.
        - Sarcasm -> knowing smirk (one-sided smile analog via squint).

        When speaking:
        - Jaw opens proportional to energy.
        - Brows rise on high dominance.
        - Head nods on falling prosody style.
        - Head tilts on question prosody style.

        All values are smoothed via clamp and scaled by mirror_intensity.

        Args:
            emotion: Current fused emotion state.
            is_speaking: Whether the avatar is currently speaking.

        Returns:
            AvatarExpression with all parameters in valid ranges.
        """
        k = self._intensity

        if is_speaking:
            return self._speaking_expression(emotion, k)
        return self._listening_expression(emotion, k)

    def prosody_to_expression(
        self,
        prosody: ProsodyFeatures,
    ) -> AvatarExpression:
        """Direct prosody-to-expression mapping for avatar speaking.

        Used when the avatar is speaking and raw prosody features are
        available (instead of or in addition to EmotionState).

        Mapping:
        - F0 mean -> jaw opening (higher pitch = more open).
        - F0 peaks above mean -> brow raise.
        - Energy peaks -> mouth stretch.
        - Falling contour -> head nod.
        - Rising contour -> head tilt.
        - has_breath -> brief jaw close (reduce jaw_open).
        - has_emphasis -> brow furrow pulse.

        Args:
            prosody: Current prosody features.

        Returns:
            AvatarExpression driven by prosody.
        """
        k = self._intensity

        # F0 mean normalized to [0, 1] range (80-400 Hz typical).
        f0_norm = _normalize_f0(prosody.f0_mean)

        # Jaw opening: higher pitch -> more open.
        jaw_open = f0_norm * 0.8
        if prosody.has_breath:
            jaw_open *= 0.2  # Brief close on breath.

        # Brow raise: F0 peaks above mean indicate emphasis/surprise.
        f0_peak_ratio = (
            (prosody.f0_max - prosody.f0_mean) / max(prosody.f0_mean, 1.0)
        )
        brow_raise = _clamp01(f0_peak_ratio * 0.6)

        # Brow furrow: emphasis pulses.
        brow_furrow = 0.4 if prosody.has_emphasis else 0.0

        # Mouth stretch: driven by energy peaks.
        mouth_stretch = _clamp01(prosody.energy_peak * 0.7)

        # Head nod: falling contour.
        head_nod = 0.0
        if prosody.pitch_contour_type == "falling":
            head_nod = 0.5

        # Head tilt: rising contour (questions).
        head_tilt = 0.0
        if prosody.pitch_contour_type == "rising":
            head_tilt = 0.4

        # Eye wideness: correlated with high F0 std (expressive speech).
        eye_wide = _clamp01(prosody.f0_std / 80.0 * 0.5)

        # Squint: not typically driven by prosody, stays at baseline.
        squint = 0.0

        return AvatarExpression(
            jaw_open=_clamp01(jaw_open * k),
            brow_raise=_clamp01(brow_raise * k),
            brow_furrow=_clamp01(brow_furrow * k),
            mouth_stretch=_clamp01(mouth_stretch * k),
            head_nod_intensity=_clamp01(head_nod * k),
            head_tilt=_clamp_sym(head_tilt * k),
            eye_wide=_clamp01(eye_wide * k),
            squint=_clamp01(squint * k),
        )

    @staticmethod
    def _listening_expression(
        emotion: EmotionState,
        k: float,
    ) -> AvatarExpression:
        """Build expression for listening mode.

        Args:
            emotion: Current emotion state.
            k: Intensity scaling factor.

        Returns:
            AvatarExpression tuned for empathetic listening.
        """
        # Arousal drives alertness: raised brows, wide eyes.
        brow_raise = emotion.arousal * 0.6
        eye_wide = emotion.arousal * 0.5

        # Valence drives mouth: positive -> smile, negative -> furrow.
        mouth_stretch = 0.0
        brow_furrow = 0.0
        if emotion.valence > 0.55:
            mouth_stretch = (emotion.valence - 0.5) * 1.0
        elif emotion.valence < 0.45:
            brow_furrow = (0.5 - emotion.valence) * 0.8

        # Sarcasm: knowing smirk analog (asymmetric via squint).
        squint = 0.0
        if emotion.is_sarcastic:
            squint = 0.4
            mouth_stretch = max(mouth_stretch, 0.2)

        # Jaw stays mostly closed when listening.
        jaw_open = emotion.energy * 0.15

        # Head nod: gentle nodding during active listening.
        head_nod = 0.0
        if emotion.arousal > 0.4 and emotion.valence > 0.5:
            head_nod = 0.3

        # Head tilt: curiosity on moderate arousal.
        head_tilt = 0.0
        if emotion.prosody_style == "question":
            head_tilt = 0.3

        return AvatarExpression(
            jaw_open=_clamp01(jaw_open * k),
            brow_raise=_clamp01(brow_raise * k),
            brow_furrow=_clamp01(brow_furrow * k),
            mouth_stretch=_clamp01(mouth_stretch * k),
            head_nod_intensity=_clamp01(head_nod * k),
            head_tilt=_clamp_sym(head_tilt * k),
            eye_wide=_clamp01(eye_wide * k),
            squint=_clamp01(squint * k),
        )

    @staticmethod
    def _speaking_expression(
        emotion: EmotionState,
        k: float,
    ) -> AvatarExpression:
        """Build expression for speaking mode using emotion state.

        Args:
            emotion: Current emotion state (from avatar's own speech).
            k: Intensity scaling factor.

        Returns:
            AvatarExpression tuned for speaking.
        """
        # Jaw opens proportional to energy (louder = more open).
        jaw_open = emotion.energy * 0.7

        # Brows rise on high dominance (assertive speech).
        brow_raise = emotion.dominance * 0.5

        # Brow furrow on negative valence while speaking.
        brow_furrow = 0.0
        if emotion.valence < 0.4:
            brow_furrow = (0.5 - emotion.valence) * 0.6

        # Mouth stretch: positive emotion while speaking.
        mouth_stretch = 0.0
        if emotion.valence > 0.55:
            mouth_stretch = (emotion.valence - 0.5) * 0.8

        # Head nod on falling prosody (assertive statements).
        head_nod = 0.0
        if emotion.prosody_style in ("calm", "emphatic"):
            head_nod = 0.4

        # Head tilt on questions.
        head_tilt = 0.0
        if emotion.prosody_style == "question":
            head_tilt = 0.35

        # Eye wideness on high arousal while speaking.
        eye_wide = 0.0
        if emotion.arousal > 0.6:
            eye_wide = (emotion.arousal - 0.5) * 0.6

        # Squint on sarcasm.
        squint = 0.3 if emotion.is_sarcastic else 0.0

        return AvatarExpression(
            jaw_open=_clamp01(jaw_open * k),
            brow_raise=_clamp01(brow_raise * k),
            brow_furrow=_clamp01(brow_furrow * k),
            mouth_stretch=_clamp01(mouth_stretch * k),
            head_nod_intensity=_clamp01(head_nod * k),
            head_tilt=_clamp_sym(head_tilt * k),
            eye_wide=_clamp01(eye_wide * k),
            squint=_clamp01(squint * k),
        )
