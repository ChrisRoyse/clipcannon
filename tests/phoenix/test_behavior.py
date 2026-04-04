"""Tests for the phoenix.behavior intelligence layer.

All tests use real numpy arrays with known properties. NO mocks.
"""

from __future__ import annotations

import numpy as np
import pytest

from phoenix.errors import BehaviorError
from phoenix.expression.emotion_fusion import EmotionState, ProsodyFeatures
from phoenix.expression.gesture_library import GestureLibrary

from phoenix.behavior.cross_modal_detector import CrossModalDetector, SocialSignal
from phoenix.behavior.emotion_mirror import AvatarExpression, EmotionMirror
from phoenix.behavior.gesture_selector import GestureSelector
from phoenix.behavior.prosody_matcher import ProsodyMatch, ProsodyMatcher


# ---------------------------------------------------------------------------
# Helpers: build real data with known properties
# ---------------------------------------------------------------------------

def _make_prosody(
    *,
    f0_mean: float = 150.0,
    f0_std: float = 20.0,
    f0_min: float = 100.0,
    f0_max: float = 200.0,
    f0_range: float = 100.0,
    energy_mean: float = 0.5,
    energy_peak: float = 0.7,
    energy_std: float = 0.1,
    speaking_rate_wpm: float = 140.0,
    pitch_contour_type: str = "flat",
    has_emphasis: bool = False,
    has_breath: bool = False,
) -> ProsodyFeatures:
    """Build a ProsodyFeatures with configurable defaults."""
    return ProsodyFeatures(
        f0_mean=f0_mean,
        f0_std=f0_std,
        f0_min=f0_min,
        f0_max=f0_max,
        f0_range=f0_range,
        energy_mean=energy_mean,
        energy_peak=energy_peak,
        energy_std=energy_std,
        speaking_rate_wpm=speaking_rate_wpm,
        pitch_contour_type=pitch_contour_type,
        has_emphasis=has_emphasis,
        has_breath=has_breath,
    )


def _make_emotion(
    *,
    arousal: float = 0.5,
    valence: float = 0.5,
    energy: float = 0.5,
    dominance: float = 0.5,
    prosody_style: str = "calm",
    is_sarcastic: bool = False,
    confidence: float = 0.8,
) -> EmotionState:
    """Build an EmotionState with configurable defaults."""
    return EmotionState(
        arousal=arousal,
        valence=valence,
        energy=energy,
        dominance=dominance,
        prosody_style=prosody_style,
        is_sarcastic=is_sarcastic,
        confidence=confidence,
    )


def _build_library() -> GestureLibrary:
    """Build a default gesture library for testing."""
    lib = GestureLibrary()
    lib.build_default_library()
    return lib


# ===================================================================
# GestureSelector tests
# ===================================================================

class TestGestureSelector:
    """Tests for GestureSelector behavior-level gesture selection."""

    def test_high_arousal_biases_toward_emphasis(self) -> None:
        """High arousal + positive valence emotion biases toward emphasis."""
        lib = _build_library()
        selector = GestureSelector(lib)

        emotion = _make_emotion(
            arousal=0.8,
            valence=0.7,
            energy=0.7,
        )

        clip = selector.select_for_response(
            "This is absolutely incredible!",
            emotion_state=emotion,
        )

        # With high arousal + positive valence + high energy, the
        # category should be biased to "emphasis".
        assert clip.category == "emphasis"

    def test_question_text_differs_from_statement(self) -> None:
        """Question text produces a different gesture than a statement."""
        lib = _build_library()
        selector = GestureSelector(lib)

        clip_question = selector.select_for_response(
            "What do you think about this?",
        )
        clip_statement = selector.select_for_response(
            "I think this is great.",
        )

        # The hash-based embedding produces different vectors for
        # different texts, so the cosine search should select
        # different gestures.
        assert clip_question.gesture_id != clip_statement.gesture_id

    def test_empty_text_raises(self) -> None:
        """Empty response text raises BehaviorError."""
        lib = _build_library()
        selector = GestureSelector(lib)

        with pytest.raises(BehaviorError, match="empty"):
            selector.select_for_response("")

    def test_whitespace_only_raises(self) -> None:
        """Whitespace-only response text raises BehaviorError."""
        lib = _build_library()
        selector = GestureSelector(lib)

        with pytest.raises(BehaviorError, match="empty"):
            selector.select_for_response("   \t\n  ")

    def test_empty_library_raises(self) -> None:
        """Constructing with empty library raises BehaviorError."""
        lib = GestureLibrary()
        with pytest.raises(BehaviorError, match="non-empty"):
            GestureSelector(lib)

    def test_sarcastic_emotion_biases_uncertainty(self) -> None:
        """Sarcastic emotion state biases toward uncertainty category."""
        lib = _build_library()
        selector = GestureSelector(lib)

        emotion = _make_emotion(is_sarcastic=True)

        clip = selector.select_for_response(
            "Oh sure, that is totally going to work.",
            emotion_state=emotion,
        )

        assert clip.category == "uncertainty"

    def test_low_arousal_biases_thinking(self) -> None:
        """Low arousal + neutral valence biases toward thinking."""
        lib = _build_library()
        selector = GestureSelector(lib)

        emotion = _make_emotion(arousal=0.1, valence=0.5)

        clip = selector.select_for_response(
            "Let me consider that for a moment.",
            emotion_state=emotion,
        )

        assert clip.category == "thinking"

    def test_no_emotion_uses_unfiltered_search(self) -> None:
        """Without emotion state, returns the best semantic match."""
        lib = _build_library()
        selector = GestureSelector(lib)

        clip = selector.select_for_response("Hello there, nice to meet you.")

        assert clip is not None
        assert isinstance(clip.gesture_id, str)
        assert len(clip.gesture_id) > 0


# ===================================================================
# ProsodyMatcher tests
# ===================================================================

class TestProsodyMatcher:
    """Tests for ProsodyMatcher TTS style matching."""

    def test_high_energy_room_returns_energetic(self) -> None:
        """High-energy room prosody produces 'energetic' style."""
        matcher = ProsodyMatcher(history_window=5)

        # Add 5 high-energy, fast-speaking observations.
        for _ in range(5):
            matcher.update(_make_prosody(
                energy_mean=0.8,
                speaking_rate_wpm=180.0,
                f0_mean=200.0,
            ))

        result = matcher.match("I agree with that point.")

        assert result.target_style == "energetic"
        assert result.room_energy > 0.6
        assert result.confidence > 0.0

    def test_question_mark_overrides_style(self) -> None:
        """Question mark in text overrides to 'question' style."""
        matcher = ProsodyMatcher(history_window=5)

        # Even with high-energy room...
        for _ in range(5):
            matcher.update(_make_prosody(energy_mean=0.8))

        result = matcher.match("Do you really think so?")

        assert result.target_style == "question"

    def test_exclamation_overrides_to_emphatic(self) -> None:
        """Exclamation mark overrides to 'emphatic' style."""
        matcher = ProsodyMatcher(history_window=5)

        for _ in range(3):
            matcher.update(_make_prosody(energy_mean=0.3))

        result = matcher.match("That is amazing!")

        assert result.target_style == "emphatic"

    def test_empty_history_returns_varied(self) -> None:
        """Empty prosody history returns 'varied' with zero confidence."""
        matcher = ProsodyMatcher(history_window=10)

        result = matcher.match("Some text here.")

        assert result.target_style == "varied"
        assert result.confidence == 0.0
        assert result.room_energy == 0.0
        assert result.room_f0_mean == 0.0
        assert result.room_speaking_rate == 0.0

    def test_low_energy_room_returns_calm(self) -> None:
        """Low-energy room prosody produces 'calm' style."""
        matcher = ProsodyMatcher(history_window=5)

        for _ in range(5):
            matcher.update(_make_prosody(
                energy_mean=0.15,
                speaking_rate_wpm=120.0,
                f0_mean=130.0,
            ))

        result = matcher.match("That makes sense.")

        assert result.target_style == "calm"

    def test_confidence_increases_with_observations(self) -> None:
        """Confidence grows as more observations are added."""
        matcher = ProsodyMatcher(history_window=10)

        matcher.update(_make_prosody())
        result_1 = matcher.match("Test.")
        assert 0.0 < result_1.confidence < 0.5

        for _ in range(9):
            matcher.update(_make_prosody())

        result_10 = matcher.match("Test.")
        assert result_10.confidence > result_1.confidence
        assert result_10.confidence == pytest.approx(1.0)

    def test_reset_clears_history(self) -> None:
        """Reset clears all prosody history."""
        matcher = ProsodyMatcher(history_window=5)

        for _ in range(5):
            matcher.update(_make_prosody())

        matcher.reset()
        result = matcher.match("Test.")

        assert result.target_style == "varied"
        assert result.confidence == 0.0

    def test_invalid_window_raises(self) -> None:
        """Invalid history_window raises BehaviorError."""
        with pytest.raises(BehaviorError):
            ProsodyMatcher(history_window=0)

    def test_room_averages_computed_correctly(self) -> None:
        """Room averages reflect the actual prosody observations."""
        matcher = ProsodyMatcher(history_window=10)

        matcher.update(_make_prosody(energy_mean=0.4, f0_mean=100.0,
                                     speaking_rate_wpm=120.0))
        matcher.update(_make_prosody(energy_mean=0.6, f0_mean=200.0,
                                     speaking_rate_wpm=180.0))

        result = matcher.match("Test statement.")

        assert result.room_energy == pytest.approx(0.5)
        assert result.room_f0_mean == pytest.approx(150.0)
        assert result.room_speaking_rate == pytest.approx(150.0)


# ===================================================================
# EmotionMirror tests
# ===================================================================

class TestEmotionMirror:
    """Tests for EmotionMirror expression mapping."""

    def test_high_arousal_listening_raises_brows(self) -> None:
        """High arousal when listening produces raised eyebrows."""
        mirror = EmotionMirror(mirror_intensity=1.0)

        emotion = _make_emotion(arousal=0.9, valence=0.6)
        expr = mirror.mirror(emotion, is_speaking=False)

        assert isinstance(expr, AvatarExpression)
        assert expr.brow_raise > 0.3

    def test_speaking_with_falling_contour_nods(self) -> None:
        """Speaking with falling prosody style produces head nod."""
        mirror = EmotionMirror(mirror_intensity=1.0)

        # "calm" and "emphatic" prosody styles trigger head nod.
        emotion = _make_emotion(prosody_style="emphatic")
        expr = mirror.mirror(emotion, is_speaking=True)

        assert expr.head_nod_intensity > 0.0

    def test_speaking_with_rising_contour_tilts(self) -> None:
        """Speaking with question prosody style produces head tilt."""
        mirror = EmotionMirror(mirror_intensity=1.0)

        emotion = _make_emotion(prosody_style="question")
        expr = mirror.mirror(emotion, is_speaking=True)

        assert expr.head_tilt > 0.0

    def test_prosody_to_expression_high_f0_opens_jaw(self) -> None:
        """High F0 mean in prosody_to_expression opens the jaw."""
        mirror = EmotionMirror(mirror_intensity=1.0)

        prosody = _make_prosody(f0_mean=350.0)
        expr = mirror.prosody_to_expression(prosody)

        assert expr.jaw_open > 0.3

    def test_prosody_to_expression_falling_contour_nods(self) -> None:
        """Falling pitch contour in prosody_to_expression produces nod."""
        mirror = EmotionMirror(mirror_intensity=1.0)

        prosody = _make_prosody(pitch_contour_type="falling")
        expr = mirror.prosody_to_expression(prosody)

        assert expr.head_nod_intensity > 0.0

    def test_prosody_to_expression_rising_contour_tilts(self) -> None:
        """Rising pitch contour in prosody_to_expression produces tilt."""
        mirror = EmotionMirror(mirror_intensity=1.0)

        prosody = _make_prosody(pitch_contour_type="rising")
        expr = mirror.prosody_to_expression(prosody)

        assert expr.head_tilt > 0.0

    def test_prosody_to_expression_emphasis_furrows(self) -> None:
        """has_emphasis in prosody_to_expression produces brow furrow."""
        mirror = EmotionMirror(mirror_intensity=1.0)

        prosody = _make_prosody(has_emphasis=True)
        expr = mirror.prosody_to_expression(prosody)

        assert expr.brow_furrow > 0.0

    def test_prosody_to_expression_breath_reduces_jaw(self) -> None:
        """has_breath in prosody_to_expression reduces jaw opening."""
        mirror = EmotionMirror(mirror_intensity=1.0)

        prosody_normal = _make_prosody(f0_mean=250.0, has_breath=False)
        prosody_breath = _make_prosody(f0_mean=250.0, has_breath=True)

        expr_normal = mirror.prosody_to_expression(prosody_normal)
        expr_breath = mirror.prosody_to_expression(prosody_breath)

        assert expr_breath.jaw_open < expr_normal.jaw_open

    def test_mirror_intensity_scales_output(self) -> None:
        """Lower mirror_intensity produces smaller expression values."""
        mirror_full = EmotionMirror(mirror_intensity=1.0)
        mirror_half = EmotionMirror(mirror_intensity=0.5)

        emotion = _make_emotion(arousal=0.9, valence=0.7)

        expr_full = mirror_full.mirror(emotion, is_speaking=False)
        expr_half = mirror_half.mirror(emotion, is_speaking=False)

        assert expr_half.brow_raise < expr_full.brow_raise
        assert expr_half.eye_wide < expr_full.eye_wide

    def test_all_values_clamped(self) -> None:
        """All expression values stay within valid ranges."""
        mirror = EmotionMirror(mirror_intensity=1.0)

        # Extreme emotion state.
        emotion = _make_emotion(
            arousal=1.0, valence=1.0, energy=1.0, dominance=1.0,
        )

        expr = mirror.mirror(emotion, is_speaking=True)

        assert 0.0 <= expr.jaw_open <= 1.0
        assert 0.0 <= expr.brow_raise <= 1.0
        assert 0.0 <= expr.brow_furrow <= 1.0
        assert 0.0 <= expr.mouth_stretch <= 1.0
        assert 0.0 <= expr.head_nod_intensity <= 1.0
        assert -1.0 <= expr.head_tilt <= 1.0
        assert 0.0 <= expr.eye_wide <= 1.0
        assert 0.0 <= expr.squint <= 1.0

    def test_invalid_intensity_raises(self) -> None:
        """Invalid mirror_intensity raises BehaviorError."""
        with pytest.raises(BehaviorError):
            EmotionMirror(mirror_intensity=-0.1)
        with pytest.raises(BehaviorError):
            EmotionMirror(mirror_intensity=1.5)

    def test_listening_positive_valence_smiles(self) -> None:
        """Positive valence when listening produces mouth stretch (smile)."""
        mirror = EmotionMirror(mirror_intensity=1.0)

        emotion = _make_emotion(valence=0.8)
        expr = mirror.mirror(emotion, is_speaking=False)

        assert expr.mouth_stretch > 0.0

    def test_listening_negative_valence_furrows(self) -> None:
        """Negative valence when listening produces brow furrow."""
        mirror = EmotionMirror(mirror_intensity=1.0)

        emotion = _make_emotion(valence=0.2)
        expr = mirror.mirror(emotion, is_speaking=False)

        assert expr.brow_furrow > 0.0

    def test_sarcasm_produces_squint(self) -> None:
        """Sarcastic emotion produces squint (knowing smirk analog)."""
        mirror = EmotionMirror(mirror_intensity=1.0)

        emotion = _make_emotion(is_sarcastic=True)
        expr = mirror.mirror(emotion, is_speaking=False)

        assert expr.squint > 0.0


# ===================================================================
# CrossModalDetector tests
# ===================================================================

class TestCrossModalDetector:
    """Tests for CrossModalDetector social signal detection."""

    def test_sarcasm_detected(self) -> None:
        """Sarcasm: positive semantic + low arousal + falling F0."""
        detector = CrossModalDetector(sensitivity=0.7)

        emotion = _make_emotion(
            arousal=0.15,
            valence=0.3,
            energy=0.2,
            is_sarcastic=True,
        )
        prosody = _make_prosody(
            pitch_contour_type="falling",
            energy_mean=0.2,
        )
        # Positive semantic embedding (mean > 0).
        semantic = np.full(768, 0.5, dtype=np.float32)

        signal = detector.detect(emotion, prosody, semantic)

        assert signal.signal_type == "sarcasm"
        assert signal.confidence > 0.5
        assert "semantic" in signal.sources

    def test_enthusiasm_detected(self) -> None:
        """Enthusiasm: high arousal + high valence + high energy + rising."""
        detector = CrossModalDetector(sensitivity=0.7)

        emotion = _make_emotion(
            arousal=0.9,
            valence=0.85,
            energy=0.8,
        )
        prosody = _make_prosody(
            pitch_contour_type="rising",
            speaking_rate_wpm=180.0,
            energy_mean=0.8,
        )

        signal = detector.detect(emotion, prosody)

        assert signal.signal_type == "enthusiasm"
        assert signal.confidence > 0.5
        assert "emotion" in signal.sources

    def test_boredom_detected(self) -> None:
        """Boredom: low arousal + low energy + flat F0 + slow rate."""
        detector = CrossModalDetector(sensitivity=0.7)

        emotion = _make_emotion(
            arousal=0.1,
            valence=0.45,
            energy=0.1,
        )
        prosody = _make_prosody(
            pitch_contour_type="flat",
            speaking_rate_wpm=90.0,
            energy_mean=0.15,
        )

        signal = detector.detect(emotion, prosody)

        assert signal.signal_type == "boredom"
        assert signal.confidence > 0.5
        assert "emotion" in signal.sources
        assert "prosody" in signal.sources

    def test_neutral_when_no_signals_match(self) -> None:
        """Neutral when no strong social signals are detected."""
        detector = CrossModalDetector(sensitivity=0.0)

        # With sensitivity=0.0, threshold_scale=1.0, and min_score=0.6:
        # arousal=0.45 blocks boredom (<0.45 False) and enthusiasm
        # (>0.45 False). Valence=0.55 blocks tension (<0.55 False).
        # Humor only gets arousal (+0.25) + valence (+0.25) = 0.5 < 0.6.
        # No detector reaches the 0.6 threshold -> neutral.
        emotion = _make_emotion(
            arousal=0.45,
            valence=0.55,
            energy=0.35,
        )
        prosody = _make_prosody(
            pitch_contour_type="varied",
            speaking_rate_wpm=140.0,
            energy_mean=0.35,
            f0_std=15.0,
            f0_range=40.0,
        )

        signal = detector.detect(emotion, prosody)

        assert signal.signal_type == "neutral"
        assert signal.confidence >= 0.0

    def test_humor_detected(self) -> None:
        """Humor: high arousal + high valence + varied F0 + fast."""
        detector = CrossModalDetector(sensitivity=0.7)

        emotion = _make_emotion(
            arousal=0.8,
            valence=0.8,
            energy=0.6,
        )
        prosody = _make_prosody(
            f0_std=50.0,
            f0_range=120.0,
            speaking_rate_wpm=200.0,
        )

        signal = detector.detect(emotion, prosody)

        assert signal.signal_type in ("humor", "enthusiasm")
        assert signal.confidence > 0.5

    def test_tension_detected(self) -> None:
        """Tension: high arousal + low valence + high energy."""
        detector = CrossModalDetector(sensitivity=0.7)

        emotion = _make_emotion(
            arousal=0.8,
            valence=0.2,
            energy=0.7,
        )
        prosody = _make_prosody(
            energy_mean=0.7,
            has_emphasis=True,
        )

        signal = detector.detect(emotion, prosody)

        assert signal.signal_type == "tension"
        assert signal.confidence > 0.5

    def test_invalid_sensitivity_raises(self) -> None:
        """Invalid sensitivity raises BehaviorError."""
        with pytest.raises(BehaviorError):
            CrossModalDetector(sensitivity=-0.1)
        with pytest.raises(BehaviorError):
            CrossModalDetector(sensitivity=1.5)

    def test_invalid_semantic_shape_raises(self) -> None:
        """Non-1D semantic embedding raises BehaviorError."""
        detector = CrossModalDetector()
        emotion = _make_emotion()
        prosody = _make_prosody()

        with pytest.raises(BehaviorError):
            detector.detect(emotion, prosody, np.zeros((2, 384)))

    def test_signal_sources_populated(self) -> None:
        """Detected signals have non-empty source lists."""
        detector = CrossModalDetector(sensitivity=0.7)

        emotion = _make_emotion(arousal=0.9, valence=0.85, energy=0.8)
        prosody = _make_prosody(
            pitch_contour_type="rising",
            speaking_rate_wpm=180.0,
        )

        signal = detector.detect(emotion, prosody)

        assert len(signal.sources) > 0

    def test_confidence_clamped(self) -> None:
        """Signal confidence is always in [0, 1]."""
        detector = CrossModalDetector(sensitivity=1.0)

        # Extreme values to push confidence high.
        emotion = _make_emotion(
            arousal=1.0, valence=1.0, energy=1.0,
        )
        prosody = _make_prosody(
            pitch_contour_type="rising",
            speaking_rate_wpm=300.0,
            energy_mean=1.0,
        )

        signal = detector.detect(emotion, prosody)

        assert 0.0 <= signal.confidence <= 1.0


# ===================================================================
# Integration: imports from phoenix.behavior
# ===================================================================

class TestBehaviorPackageExports:
    """Verify that all public types are re-exported from the package."""

    def test_gesture_selector_importable(self) -> None:
        """GestureSelector is importable from phoenix.behavior."""
        from phoenix.behavior import GestureSelector as GS
        assert GS is GestureSelector

    def test_prosody_matcher_importable(self) -> None:
        """ProsodyMatcher is importable from phoenix.behavior."""
        from phoenix.behavior import ProsodyMatcher as PM
        assert PM is ProsodyMatcher

    def test_prosody_match_importable(self) -> None:
        """ProsodyMatch is importable from phoenix.behavior."""
        from phoenix.behavior import ProsodyMatch as PMR
        assert PMR is ProsodyMatch

    def test_emotion_mirror_importable(self) -> None:
        """EmotionMirror is importable from phoenix.behavior."""
        from phoenix.behavior import EmotionMirror as EM
        assert EM is EmotionMirror

    def test_avatar_expression_importable(self) -> None:
        """AvatarExpression is importable from phoenix.behavior."""
        from phoenix.behavior import AvatarExpression as AE
        assert AE is AvatarExpression

    def test_cross_modal_detector_importable(self) -> None:
        """CrossModalDetector is importable from phoenix.behavior."""
        from phoenix.behavior import CrossModalDetector as CMD
        assert CMD is CrossModalDetector

    def test_social_signal_importable(self) -> None:
        """SocialSignal is importable from phoenix.behavior."""
        from phoenix.behavior import SocialSignal as SS
        assert SS is SocialSignal
