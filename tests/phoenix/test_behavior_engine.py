"""Integration tests for the BehaviorEngine orchestrator.

Verifies the full pipeline end-to-end: expression fusion, speaker
tracking, gesture selection, prosody matching, emotion mirroring,
and cross-modal social signal detection.

All tests use real numpy arrays. NO mocks.
"""

from __future__ import annotations

import numpy as np
import pytest

from phoenix.behavior.cross_modal_detector import SocialSignal
from phoenix.behavior.emotion_mirror import AvatarExpression
from phoenix.behavior.engine import BehaviorEngine, BehaviorOutput
from phoenix.config import PhoenixConfig
from phoenix.errors import BehaviorError, ExpressionError
from phoenix.expression.emotion_fusion import EmotionState, ProsodyFeatures
from phoenix.expression.gesture_library import GestureClip
from phoenix.expression.speaker_tracker import SpeakerInfo


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


def _emotion_1024(seed: int = 42) -> np.ndarray:
    """Create a 1024-dim emotion embedding."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal(1024).astype(np.float32)


def _speaker_512(seed: int = 99) -> np.ndarray:
    """Create a 512-dim speaker embedding."""
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(512).astype(np.float32)
    # Normalize for cosine similarity.
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


def _semantic_768(seed: int = 77) -> np.ndarray:
    """Create a 768-dim semantic embedding."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal(768).astype(np.float32)


def _high_arousal_emotion(seed: int = 10) -> np.ndarray:
    """Create an emotion embedding with high variance (high arousal).

    High variance in the embedding maps to high arousal in EmotionFusion.
    """
    rng = np.random.default_rng(seed)
    # Scale to have large variance.
    return (rng.standard_normal(1024) * 10.0).astype(np.float32)


def _sarcastic_semantic() -> np.ndarray:
    """Create a positive-mean semantic embedding (positive content).

    Positive mean + low arousal + falling pitch = sarcasm detection.
    """
    rng = np.random.default_rng(123)
    # Ensure positive mean.
    vec = np.abs(rng.standard_normal(768)).astype(np.float32)
    return vec


# ---------------------------------------------------------------------------
# Listening mode tests
# ---------------------------------------------------------------------------

class TestProcessListening:
    """Tests for BehaviorEngine.process_listening()."""

    def test_full_pipeline_returns_valid_output(self) -> None:
        """Feed all embeddings and get a valid BehaviorOutput."""
        engine = BehaviorEngine()
        result = engine.process_listening(
            emotion_embedding=_emotion_1024(),
            speaker_embedding=_speaker_512(),
            prosody=_make_prosody(),
            semantic_embedding=_semantic_768(),
            timestamp_ms=1000,
        )

        assert isinstance(result, BehaviorOutput)
        assert isinstance(result.expression, AvatarExpression)
        assert result.gesture is None  # Listening mode never selects gesture
        assert result.tts_style == "calm"
        assert isinstance(result.social_signal, SocialSignal)
        assert isinstance(result.emotion, EmotionState)
        assert result.active_speaker is not None
        assert isinstance(result.active_speaker, SpeakerInfo)
        assert 0.0 <= result.room_energy <= 1.0

    def test_high_arousal_raises_brows(self) -> None:
        """High-arousal emotion embedding produces raised eyebrows."""
        engine = BehaviorEngine()
        result = engine.process_listening(
            emotion_embedding=_high_arousal_emotion(),
            prosody=_make_prosody(),
            timestamp_ms=100,
        )

        # High variance -> high arousal -> brow_raise > 0.3 from
        # EmotionMirror._listening_expression: brow_raise = arousal * 0.6
        assert result.expression.brow_raise > 0.0

    def test_new_speaker_populates_active(self) -> None:
        """New speaker embedding produces a populated active_speaker."""
        engine = BehaviorEngine()
        result = engine.process_listening(
            speaker_embedding=_speaker_512(seed=200),
            timestamp_ms=500,
        )

        assert result.active_speaker is not None
        assert result.active_speaker.speaker_id == "speaker_0"
        assert result.active_speaker.is_speaking is True

    def test_same_speaker_twice_same_id(self) -> None:
        """Same speaker embedding twice returns the same speaker_id."""
        engine = BehaviorEngine()
        emb = _speaker_512(seed=300)

        r1 = engine.process_listening(
            speaker_embedding=emb.copy(),
            timestamp_ms=100,
        )
        r2 = engine.process_listening(
            speaker_embedding=emb.copy(),
            timestamp_ms=200,
        )

        assert r1.active_speaker is not None
        assert r2.active_speaker is not None
        assert r1.active_speaker.speaker_id == r2.active_speaker.speaker_id

    def test_different_speakers_get_different_ids(self) -> None:
        """Different speaker embeddings get different speaker_ids."""
        engine = BehaviorEngine()

        r1 = engine.process_listening(
            speaker_embedding=_speaker_512(seed=400),
            timestamp_ms=100,
        )
        r2 = engine.process_listening(
            speaker_embedding=_speaker_512(seed=401),
            timestamp_ms=200,
        )

        assert r1.active_speaker is not None
        assert r2.active_speaker is not None
        assert r1.active_speaker.speaker_id != r2.active_speaker.speaker_id

    def test_sarcasm_detection(self) -> None:
        """Sarcastic signals produce social_signal with sarcasm type.

        Sarcasm = positive semantic + low arousal + falling pitch.
        """
        engine = BehaviorEngine()

        # Low-variance emotion -> low arousal.
        rng = np.random.default_rng(55)
        low_emotion = (rng.standard_normal(1024) * 0.01).astype(np.float32)

        result = engine.process_listening(
            emotion_embedding=low_emotion,
            prosody=_make_prosody(pitch_contour_type="falling"),
            semantic_embedding=_sarcastic_semantic(),
            timestamp_ms=100,
        )

        assert result.social_signal.signal_type == "sarcasm"
        assert result.social_signal.confidence > 0.0

    def test_emotion_state_populated(self) -> None:
        """Emotion state has non-default values when embeddings given."""
        engine = BehaviorEngine()
        result = engine.process_listening(
            emotion_embedding=_emotion_1024(),
            prosody=_make_prosody(),
            timestamp_ms=100,
        )

        assert result.emotion.confidence > 0.0

    def test_room_energy_from_prosody(self) -> None:
        """Room energy reflects the prosody energy_mean."""
        engine = BehaviorEngine()
        result = engine.process_listening(
            prosody=_make_prosody(energy_mean=0.8),
            timestamp_ms=100,
        )

        # Room energy should be close to the prosody energy_mean.
        assert result.room_energy > 0.5


# ---------------------------------------------------------------------------
# Speaking mode tests
# ---------------------------------------------------------------------------

class TestProcessSpeaking:
    """Tests for BehaviorEngine.process_speaking()."""

    def test_full_pipeline_returns_gesture_and_style(self) -> None:
        """Speaking with all inputs returns gesture and tts_style."""
        engine = BehaviorEngine()
        result = engine.process_speaking(
            response_text="I think that's a great idea.",
            emotion_embedding=_emotion_1024(),
            prosody=_make_prosody(),
            semantic_embedding=_semantic_768(),
        )

        assert isinstance(result, BehaviorOutput)
        assert result.gesture is not None
        assert isinstance(result.gesture, GestureClip)
        assert isinstance(result.tts_style, str)
        assert len(result.tts_style) > 0

    def test_question_mark_produces_question_style(self) -> None:
        """Response ending with '?' produces tts_style='question'."""
        engine = BehaviorEngine()
        # Seed the prosody history first.
        engine.process_listening(
            prosody=_make_prosody(),
            timestamp_ms=100,
        )

        result = engine.process_speaking(
            response_text="Do you think this will work?",
            prosody=_make_prosody(),
        )

        assert result.tts_style == "question"

    def test_high_energy_room_energetic_style(self) -> None:
        """High room energy produces 'energetic' tts_style."""
        engine = BehaviorEngine()

        # Feed multiple high-energy prosody observations.
        high_energy_prosody = _make_prosody(
            energy_mean=0.8,
            speaking_rate_wpm=180.0,
        )
        for ts in range(0, 500, 50):
            engine.process_listening(
                prosody=high_energy_prosody,
                timestamp_ms=ts,
            )

        result = engine.process_speaking(
            response_text="Absolutely, let us go for it.",
            prosody=high_energy_prosody,
        )

        assert result.tts_style == "energetic"

    def test_response_text_selects_gesture(self) -> None:
        """Any non-empty response text selects a gesture."""
        engine = BehaviorEngine()
        result = engine.process_speaking(
            response_text="Welcome everyone to the meeting.",
        )

        assert result.gesture is not None
        assert isinstance(result.gesture, GestureClip)
        assert len(result.gesture.gesture_id) > 0

    def test_gesture_with_emotion_bias(self) -> None:
        """Emotion state biases the gesture category selection."""
        engine = BehaviorEngine()
        result = engine.process_speaking(
            response_text="I completely agree with that point.",
            emotion_embedding=_emotion_1024(seed=42),
            prosody=_make_prosody(),
        )

        assert result.gesture is not None

    def test_prosody_drives_expression(self) -> None:
        """When prosody is provided, expression comes from prosody."""
        engine = BehaviorEngine()
        prosody = _make_prosody(
            f0_mean=300.0,
            energy_peak=0.9,
        )
        result = engine.process_speaking(
            response_text="This is really important.",
            prosody=prosody,
        )

        # Higher f0 -> more jaw opening.
        assert result.expression.jaw_open > 0.0

    def test_speaking_active_speaker_is_none(self) -> None:
        """Speaking mode does not track speakers (avatar is speaking)."""
        engine = BehaviorEngine()
        result = engine.process_speaking(
            response_text="Hello there.",
        )

        assert result.active_speaker is None

    def test_exclamation_produces_emphatic(self) -> None:
        """Response ending with '!' produces tts_style='emphatic'."""
        engine = BehaviorEngine()
        engine.process_listening(prosody=_make_prosody(), timestamp_ms=0)

        result = engine.process_speaking(
            response_text="That is amazing!",
            prosody=_make_prosody(),
        )

        assert result.tts_style == "emphatic"


# ---------------------------------------------------------------------------
# Reset tests
# ---------------------------------------------------------------------------

class TestReset:
    """Tests for BehaviorEngine.reset()."""

    def test_reset_clears_all_state(self) -> None:
        """After reset, all state is cleared."""
        engine = BehaviorEngine()

        # Build up state.
        engine.process_listening(
            emotion_embedding=_emotion_1024(),
            speaker_embedding=_speaker_512(),
            prosody=_make_prosody(),
            timestamp_ms=100,
        )

        engine.reset()

        # After reset, a fresh process should start clean.
        result = engine.process_listening(
            speaker_embedding=_speaker_512(seed=500),
            timestamp_ms=200,
        )

        # New speaker should get speaker_0 again (counter reset).
        assert result.active_speaker is not None
        assert result.active_speaker.speaker_id == "speaker_0"

    def test_reset_clears_emotion_smoothing(self) -> None:
        """After reset, emotion EMA starts fresh."""
        engine = BehaviorEngine()

        # Feed some data to build EMA state.
        engine.process_listening(
            emotion_embedding=_emotion_1024(seed=1),
            prosody=_make_prosody(),
            timestamp_ms=100,
        )

        engine.reset()

        # Next emotion should not be smoothed against prior.
        r = engine.process_listening(
            emotion_embedding=_emotion_1024(seed=2),
            prosody=_make_prosody(),
            timestamp_ms=200,
        )
        # Confidence > 0 proves fusion ran.
        assert r.emotion.confidence > 0.0

    def test_reset_clears_prosody_history(self) -> None:
        """After reset, prosody history is empty (varied style at 0 conf)."""
        engine = BehaviorEngine()

        # Build prosody history.
        for i in range(5):
            engine.process_listening(
                prosody=_make_prosody(energy_mean=0.9),
                timestamp_ms=i * 100,
            )

        engine.reset()

        # Speaking without prosody should get "varied" at 0 confidence.
        result = engine.process_speaking(
            response_text="Hello after reset.",
        )
        assert result.tts_style == "varied"


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_all_none_inputs_returns_valid_defaults(self) -> None:
        """All None inputs produce a valid BehaviorOutput with defaults."""
        engine = BehaviorEngine()
        result = engine.process_listening()

        assert isinstance(result, BehaviorOutput)
        assert result.expression.jaw_open == 0.0
        assert result.expression.brow_raise == 0.0
        assert result.gesture is None
        assert result.tts_style == "calm"
        assert result.social_signal.signal_type == "neutral"
        assert result.emotion.arousal == 0.0
        assert result.active_speaker is None
        assert result.room_energy == 0.0

    def test_wrong_emotion_dim_raises_error(self) -> None:
        """Wrong emotion embedding dimensions raise BehaviorError."""
        engine = BehaviorEngine()
        wrong_dim = np.zeros(256, dtype=np.float32)

        with pytest.raises(BehaviorError, match="1024 dimensions"):
            engine.process_listening(emotion_embedding=wrong_dim)

    def test_wrong_speaker_dim_raises_error(self) -> None:
        """Wrong speaker embedding dimensions raise BehaviorError."""
        engine = BehaviorEngine()
        wrong_dim = np.zeros(768, dtype=np.float32)

        with pytest.raises(BehaviorError, match="512 dimensions"):
            engine.process_listening(speaker_embedding=wrong_dim)

    def test_wrong_semantic_dim_raises_error(self) -> None:
        """Wrong semantic embedding dimensions raise BehaviorError."""
        engine = BehaviorEngine()
        wrong_dim = np.zeros(1024, dtype=np.float32)

        with pytest.raises(BehaviorError, match="768 dimensions"):
            engine.process_listening(semantic_embedding=wrong_dim)

    def test_empty_response_text_raises_error(self) -> None:
        """Empty response text in speaking mode raises BehaviorError."""
        engine = BehaviorEngine()

        with pytest.raises(BehaviorError, match="response_text must not be empty"):
            engine.process_speaking(response_text="")

    def test_whitespace_response_text_raises_error(self) -> None:
        """Whitespace-only response text raises BehaviorError."""
        engine = BehaviorEngine()

        with pytest.raises(BehaviorError, match="response_text must not be empty"):
            engine.process_speaking(response_text="   ")

    def test_2d_emotion_embedding_raises_error(self) -> None:
        """2-D emotion embedding raises BehaviorError (must be 1-D)."""
        engine = BehaviorEngine()
        bad_shape = np.zeros((2, 512), dtype=np.float32)

        with pytest.raises(BehaviorError, match="1-D array"):
            engine.process_listening(emotion_embedding=bad_shape)

    def test_speaking_wrong_embedding_dim_raises(self) -> None:
        """Wrong embedding dims in speaking mode also raise."""
        engine = BehaviorEngine()
        wrong = np.zeros(256, dtype=np.float32)

        with pytest.raises(BehaviorError, match="1024 dimensions"):
            engine.process_speaking(
                response_text="Test",
                emotion_embedding=wrong,
            )

    def test_speaking_wrong_semantic_dim_raises(self) -> None:
        """Wrong semantic dim in speaking mode raises."""
        engine = BehaviorEngine()
        wrong = np.zeros(512, dtype=np.float32)

        with pytest.raises(BehaviorError, match="768 dimensions"):
            engine.process_speaking(
                response_text="Test",
                semantic_embedding=wrong,
            )

    def test_partial_inputs_emotion_only(self) -> None:
        """Emotion without prosody uses defaults (skips fusion)."""
        engine = BehaviorEngine()
        result = engine.process_listening(
            emotion_embedding=_emotion_1024(),
            timestamp_ms=100,
        )

        # Without prosody, fusion is skipped -> default emotion.
        assert result.emotion.confidence == 0.0

    def test_partial_inputs_prosody_only(self) -> None:
        """Prosody without emotion embedding still records room energy."""
        engine = BehaviorEngine()
        result = engine.process_listening(
            prosody=_make_prosody(energy_mean=0.6),
            timestamp_ms=100,
        )

        assert result.room_energy > 0.0
        assert result.emotion.confidence == 0.0

    def test_partial_inputs_speaker_only(self) -> None:
        """Speaker embedding alone still tracks the speaker."""
        engine = BehaviorEngine()
        result = engine.process_listening(
            speaker_embedding=_speaker_512(),
            timestamp_ms=100,
        )

        assert result.active_speaker is not None
        assert result.emotion.confidence == 0.0


# ---------------------------------------------------------------------------
# Config integration tests
# ---------------------------------------------------------------------------

class TestConfigIntegration:
    """Tests for BehaviorEngine with custom PhoenixConfig."""

    def test_custom_config_used(self) -> None:
        """Custom sarcasm_sensitivity flows through to sub-modules."""
        from phoenix.config import BehaviorWeights

        config = PhoenixConfig(
            behavior=BehaviorWeights(sarcasm_sensitivity=0.9),
        )
        engine = BehaviorEngine(config=config)

        # Should not crash; the engine is usable.
        result = engine.process_listening(
            emotion_embedding=_emotion_1024(),
            prosody=_make_prosody(),
            timestamp_ms=100,
        )
        assert isinstance(result, BehaviorOutput)

    def test_default_config(self) -> None:
        """Default PhoenixConfig produces a working engine."""
        engine = BehaviorEngine()
        result = engine.process_listening()
        assert isinstance(result, BehaviorOutput)


# ---------------------------------------------------------------------------
# Multi-turn integration tests
# ---------------------------------------------------------------------------

class TestMultiTurn:
    """Tests for multi-turn conversation scenarios."""

    def test_listen_then_speak_flow(self) -> None:
        """Simulate a listen -> speak turn."""
        engine = BehaviorEngine()

        # Listen phase.
        listen_result = engine.process_listening(
            emotion_embedding=_emotion_1024(),
            speaker_embedding=_speaker_512(),
            prosody=_make_prosody(),
            timestamp_ms=1000,
        )
        assert listen_result.active_speaker is not None
        assert listen_result.gesture is None

        # Speak phase.
        speak_result = engine.process_speaking(
            response_text="That is a good point, let me add to that.",
            emotion_embedding=_emotion_1024(seed=50),
            prosody=_make_prosody(),
        )
        assert speak_result.gesture is not None
        assert len(speak_result.tts_style) > 0

    def test_multiple_speakers_tracked(self) -> None:
        """Multiple speakers in sequence are all tracked."""
        engine = BehaviorEngine()

        speakers_seen: set[str] = set()
        for i in range(3):
            result = engine.process_listening(
                speaker_embedding=_speaker_512(seed=600 + i),
                timestamp_ms=i * 1000,
            )
            if result.active_speaker is not None:
                speakers_seen.add(result.active_speaker.speaker_id)

        assert len(speakers_seen) == 3

    def test_emotion_smoothing_across_turns(self) -> None:
        """Emotion EMA smoothing works across multiple listen turns."""
        engine = BehaviorEngine()

        emotions: list[EmotionState] = []
        for i in range(5):
            result = engine.process_listening(
                emotion_embedding=_emotion_1024(seed=700 + i),
                prosody=_make_prosody(),
                timestamp_ms=i * 100,
            )
            emotions.append(result.emotion)

        # All should have non-zero confidence (fusion ran).
        for e in emotions:
            assert e.confidence > 0.0
