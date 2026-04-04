"""Tests for the phoenix.expression embedding behavior engine.

All tests use real numpy arrays with known properties. NO mocks.
"""

from __future__ import annotations

import numpy as np
import pytest

from phoenix.errors import BehaviorError, ExpressionError
from phoenix.expression.emotion_fusion import (
    EmotionFusion,
    EmotionState,
    ProsodyFeatures,
)
from phoenix.expression.gesture_library import GestureClip, GestureLibrary
from phoenix.expression.speaker_tracker import SpeakerInfo, SpeakerTracker


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


# ===================================================================
# EmotionFusion tests
# ===================================================================

class TestEmotionFusion:
    """Tests for EmotionFusion cross-modal fusion."""

    def test_fuse_with_synthetic_embedding(self) -> None:
        """Synthetic 1024-dim embedding with known variance/mean/norm."""
        rng = np.random.default_rng(42)
        # Create embedding with known statistical properties.
        embedding = rng.standard_normal(1024).astype(np.float32)
        prosody = _make_prosody()

        fusion = EmotionFusion()
        state = fusion.fuse(embedding, prosody)

        assert isinstance(state, EmotionState)
        assert 0.0 <= state.arousal <= 1.0
        assert 0.0 <= state.valence <= 1.0
        assert 0.0 <= state.energy <= 1.0
        assert 0.0 <= state.dominance <= 1.0
        assert 0.0 <= state.confidence <= 1.0
        assert state.prosody_style in (
            "energetic", "calm", "emphatic", "varied", "question",
        )
        assert isinstance(state.is_sarcastic, bool)

    def test_fuse_high_variance_gives_high_arousal(self) -> None:
        """Embedding with high variance should produce higher arousal."""
        low_var = np.full(1024, 0.5, dtype=np.float32)  # variance ~0
        high_var = np.zeros(1024, dtype=np.float32)
        high_var[::2] = 10.0
        high_var[1::2] = -10.0  # variance = 100

        prosody = _make_prosody()
        fusion = EmotionFusion()

        state_low = fusion.fuse(low_var, prosody)
        fusion_hi = EmotionFusion()
        state_high = fusion_hi.fuse(high_var, prosody)

        assert state_high.arousal > state_low.arousal

    def test_fuse_all_zeros_valid_low_values(self) -> None:
        """All-zero embedding produces valid state with low values."""
        embedding = np.zeros(1024, dtype=np.float32)
        prosody = _make_prosody()
        fusion = EmotionFusion()

        state = fusion.fuse(embedding, prosody)

        assert state.arousal == 0.0
        assert state.valence == 0.5  # centered
        assert state.energy == 0.0
        assert state.confidence == 0.0  # zero norm means zero confidence

    def test_sarcasm_detection_positive_semantic_low_arousal(self) -> None:
        """Positive semantic + low arousal + falling F0 = sarcastic."""
        # Create embedding with low variance (low arousal).
        embedding = np.full(1024, 0.01, dtype=np.float32)

        # Positive semantic: mean > 0.
        semantic = np.full(768, 0.5, dtype=np.float32)

        prosody = _make_prosody(
            pitch_contour_type="falling",
            energy_mean=0.2,
            f0_range=30.0,
        )

        fusion = EmotionFusion(sarcasm_sensitivity=0.7)
        state = fusion.fuse(embedding, prosody, semantic)

        assert state.is_sarcastic is True

    def test_no_sarcasm_when_high_arousal(self) -> None:
        """High arousal should not trigger sarcasm even with positive semantic."""
        # High variance = high arousal.
        embedding = np.zeros(1024, dtype=np.float32)
        embedding[::2] = 50.0
        embedding[1::2] = -50.0

        semantic = np.full(768, 0.5, dtype=np.float32)
        prosody = _make_prosody(pitch_contour_type="falling")

        fusion = EmotionFusion(sarcasm_sensitivity=0.7)
        state = fusion.fuse(embedding, prosody, semantic)

        assert state.is_sarcastic is False

    def test_no_sarcasm_without_semantic(self) -> None:
        """No semantic embedding means no sarcasm detection possible."""
        embedding = np.full(1024, 0.01, dtype=np.float32)
        prosody = _make_prosody(pitch_contour_type="falling")

        fusion = EmotionFusion()
        state = fusion.fuse(embedding, prosody, semantic_embedding=None)

        assert state.is_sarcastic is False

    def test_ema_smoothing_produces_gradual_change(self) -> None:
        """Rapid state changes produce smoothed output via EMA."""
        fusion = EmotionFusion(ema_alpha=0.3)
        prosody = _make_prosody()

        # State 1: low energy (all zeros).
        emb_low = np.zeros(1024, dtype=np.float32)
        state_1 = fusion.fuse(emb_low, prosody)
        smoothed_1 = fusion.update(state_1)

        # State 2: high energy (large values).
        emb_high = np.full(1024, 5.0, dtype=np.float32)
        state_2 = fusion.fuse(emb_high, prosody)
        smoothed_2 = fusion.update(state_2)

        # Smoothed energy should be between the two raw values.
        assert smoothed_2.energy < state_2.energy
        assert smoothed_2.energy > smoothed_1.energy

    def test_ema_first_call_returns_raw(self) -> None:
        """First update call returns the state unchanged (no prior)."""
        fusion = EmotionFusion(ema_alpha=0.3)
        prosody = _make_prosody()
        embedding = np.ones(1024, dtype=np.float32)

        state = fusion.fuse(embedding, prosody)
        smoothed = fusion.update(state)

        assert smoothed.arousal == state.arousal
        assert smoothed.valence == state.valence
        assert smoothed.energy == state.energy

    def test_reset_clears_state(self) -> None:
        """Reset clears the internal smoothed state."""
        fusion = EmotionFusion()
        prosody = _make_prosody()
        embedding = np.ones(1024, dtype=np.float32)

        state = fusion.fuse(embedding, prosody)
        fusion.update(state)
        assert fusion.current_state is not None

        fusion.reset()
        assert fusion.current_state is None

    def test_invalid_ema_alpha_raises(self) -> None:
        """ema_alpha outside (0, 1] raises ExpressionError."""
        with pytest.raises(ExpressionError):
            EmotionFusion(ema_alpha=0.0)
        with pytest.raises(ExpressionError):
            EmotionFusion(ema_alpha=1.5)

    def test_invalid_embedding_shape_raises(self) -> None:
        """Non-1D embedding raises ExpressionError."""
        fusion = EmotionFusion()
        prosody = _make_prosody()

        with pytest.raises(ExpressionError):
            fusion.fuse(np.zeros((2, 512), dtype=np.float32), prosody)

    def test_invalid_semantic_shape_raises(self) -> None:
        """Non-1D semantic embedding raises ExpressionError."""
        fusion = EmotionFusion()
        prosody = _make_prosody()
        embedding = np.ones(1024, dtype=np.float32)

        with pytest.raises(ExpressionError):
            fusion.fuse(embedding, prosody, np.zeros((2, 384)))

    def test_prosody_style_question(self) -> None:
        """Rising pitch contour should classify as 'question'."""
        embedding = np.ones(1024, dtype=np.float32)
        prosody = _make_prosody(pitch_contour_type="rising")

        fusion = EmotionFusion()
        state = fusion.fuse(embedding, prosody)

        assert state.prosody_style == "question"

    def test_prosody_style_emphatic(self) -> None:
        """High energy peak + emphasis should classify as 'emphatic'."""
        embedding = np.ones(1024, dtype=np.float32)
        prosody = _make_prosody(
            has_emphasis=True,
            energy_peak=0.9,
            pitch_contour_type="flat",
        )

        fusion = EmotionFusion()
        state = fusion.fuse(embedding, prosody)

        assert state.prosody_style == "emphatic"

    def test_prosody_style_energetic(self) -> None:
        """High energy + fast speaking rate = energetic."""
        embedding = np.ones(1024, dtype=np.float32)
        prosody = _make_prosody(
            energy_mean=0.8,
            speaking_rate_wpm=200.0,
            pitch_contour_type="flat",
        )

        fusion = EmotionFusion()
        state = fusion.fuse(embedding, prosody)

        assert state.prosody_style == "energetic"

    def test_prosody_style_varied(self) -> None:
        """High F0 std + high F0 range = varied."""
        embedding = np.ones(1024, dtype=np.float32)
        prosody = _make_prosody(
            f0_std=50.0,
            f0_range=120.0,
            pitch_contour_type="flat",
        )

        fusion = EmotionFusion()
        state = fusion.fuse(embedding, prosody)

        assert state.prosody_style == "varied"


# ===================================================================
# SpeakerTracker tests
# ===================================================================

class TestSpeakerTracker:
    """Tests for SpeakerTracker speaker identification."""

    def test_new_speaker_registration(self) -> None:
        """First embedding creates speaker_0."""
        tracker = SpeakerTracker(similarity_threshold=0.7)
        embedding = np.random.default_rng(42).standard_normal(512).astype(
            np.float32
        )

        info = tracker.track(embedding, timestamp_ms=1000)

        assert info.speaker_id == "speaker_0"
        assert info.is_speaking is True
        assert info.turn_count == 1
        assert info.last_spoke_ms == 1000
        assert info.name == ""
        assert tracker.speaker_count == 1

    def test_same_speaker_reidentification(self) -> None:
        """Similar embedding (cosine > 0.7) matches same speaker."""
        tracker = SpeakerTracker(similarity_threshold=0.7)
        rng = np.random.default_rng(42)
        base = rng.standard_normal(512).astype(np.float32)
        base_normed = base / np.linalg.norm(base)

        # First observation.
        tracker.track(base_normed, timestamp_ms=1000)

        # Second observation: same vector + tiny noise (cosine ~ 0.99).
        noise = rng.standard_normal(512).astype(np.float32) * 0.01
        similar = base_normed + noise
        similar = similar / np.linalg.norm(similar)

        info = tracker.track(similar, timestamp_ms=2000)

        assert info.speaker_id == "speaker_0"
        assert info.turn_count == 2
        assert info.last_spoke_ms == 2000
        assert tracker.speaker_count == 1

    def test_different_speaker_creates_new(self) -> None:
        """Orthogonal embedding creates a new speaker."""
        tracker = SpeakerTracker(similarity_threshold=0.7)

        # Speaker A: first 256 dims positive.
        emb_a = np.zeros(512, dtype=np.float32)
        emb_a[:256] = 1.0
        emb_a = emb_a / np.linalg.norm(emb_a)

        # Speaker B: last 256 dims positive (orthogonal to A).
        emb_b = np.zeros(512, dtype=np.float32)
        emb_b[256:] = 1.0
        emb_b = emb_b / np.linalg.norm(emb_b)

        info_a = tracker.track(emb_a, timestamp_ms=1000)
        info_b = tracker.track(emb_b, timestamp_ms=2000)

        assert info_a.speaker_id == "speaker_0"
        assert info_b.speaker_id == "speaker_1"
        assert tracker.speaker_count == 2

    def test_name_assignment(self) -> None:
        """Assigning a name to a tracked speaker."""
        tracker = SpeakerTracker()
        embedding = np.ones(512, dtype=np.float32)
        embedding = embedding / np.linalg.norm(embedding)

        tracker.track(embedding, timestamp_ms=1000)
        tracker.assign_name("speaker_0", "Alice")

        speakers = tracker.get_all_speakers()
        assert len(speakers) == 1
        assert speakers[0].name == "Alice"

    def test_name_assignment_unknown_speaker_raises(self) -> None:
        """Assigning a name to an unknown speaker raises BehaviorError."""
        tracker = SpeakerTracker()

        with pytest.raises(BehaviorError):
            tracker.assign_name("speaker_999", "Ghost")

    def test_get_active_speaker(self) -> None:
        """Active speaker is the most recently tracked one."""
        tracker = SpeakerTracker(similarity_threshold=0.7)

        emb_a = np.zeros(512, dtype=np.float32)
        emb_a[:256] = 1.0
        emb_a = emb_a / np.linalg.norm(emb_a)

        emb_b = np.zeros(512, dtype=np.float32)
        emb_b[256:] = 1.0
        emb_b = emb_b / np.linalg.norm(emb_b)

        tracker.track(emb_a, timestamp_ms=1000)
        tracker.track(emb_b, timestamp_ms=2000)

        active = tracker.get_active_speaker()
        assert active is not None
        assert active.speaker_id == "speaker_1"

    def test_get_active_speaker_none_initially(self) -> None:
        """No active speaker before any tracking."""
        tracker = SpeakerTracker()
        assert tracker.get_active_speaker() is None

    def test_get_all_speakers_order(self) -> None:
        """Speakers are returned in registration order."""
        tracker = SpeakerTracker(similarity_threshold=0.7)
        rng = np.random.default_rng(100)

        for i in range(3):
            # Create clearly distinct embeddings.
            emb = np.zeros(512, dtype=np.float32)
            start = i * 170
            emb[start:start + 170] = 1.0
            emb = emb / np.linalg.norm(emb)
            tracker.track(emb, timestamp_ms=i * 1000)

        speakers = tracker.get_all_speakers()
        assert len(speakers) == 3
        assert speakers[0].speaker_id == "speaker_0"
        assert speakers[1].speaker_id == "speaker_1"
        assert speakers[2].speaker_id == "speaker_2"

    def test_invalid_threshold_raises(self) -> None:
        """Invalid similarity_threshold raises BehaviorError."""
        with pytest.raises(BehaviorError):
            SpeakerTracker(similarity_threshold=0.0)
        with pytest.raises(BehaviorError):
            SpeakerTracker(similarity_threshold=1.5)

    def test_invalid_embedding_shape_raises(self) -> None:
        """Non-1D embedding raises BehaviorError."""
        tracker = SpeakerTracker()
        with pytest.raises(BehaviorError):
            tracker.track(np.zeros((2, 256), dtype=np.float32), 1000)

    def test_deactivation_on_new_speaker(self) -> None:
        """When a new speaker is tracked, previous speaker is deactivated."""
        tracker = SpeakerTracker(similarity_threshold=0.7)

        emb_a = np.zeros(512, dtype=np.float32)
        emb_a[:256] = 1.0
        emb_a = emb_a / np.linalg.norm(emb_a)

        emb_b = np.zeros(512, dtype=np.float32)
        emb_b[256:] = 1.0
        emb_b = emb_b / np.linalg.norm(emb_b)

        tracker.track(emb_a, timestamp_ms=1000)
        tracker.track(emb_b, timestamp_ms=2000)

        speakers = tracker.get_all_speakers()
        speaker_a = [s for s in speakers if s.speaker_id == "speaker_0"][0]
        speaker_b = [s for s in speakers if s.speaker_id == "speaker_1"][0]

        assert speaker_a.is_speaking is False
        assert speaker_b.is_speaking is True


# ===================================================================
# GestureLibrary tests
# ===================================================================

class TestGestureLibrary:
    """Tests for GestureLibrary semantic gesture selection."""

    def test_build_default_library(self) -> None:
        """Default library has 20+ gestures."""
        lib = GestureLibrary()
        lib.build_default_library()

        assert lib.size >= 20

    def test_default_library_categories(self) -> None:
        """Default library covers all expected categories."""
        lib = GestureLibrary()
        lib.build_default_library()

        categories = {g.category for g in lib.get_by_category("agreement")}
        categories.update(
            g.category for g in lib.get_by_category("disagreement")
        )
        categories.update(
            g.category for g in lib.get_by_category("uncertainty")
        )
        categories.update(
            g.category for g in lib.get_by_category("emphasis")
        )

        assert "agreement" in categories
        assert "disagreement" in categories
        assert "uncertainty" in categories
        assert "emphasis" in categories

    def test_select_returns_best_match(self) -> None:
        """Select returns the gesture with highest cosine similarity."""
        lib = GestureLibrary()

        # Add two gestures with known embeddings.
        emb_a = np.zeros(768, dtype=np.float32)
        emb_a[:384] = 1.0
        emb_a = emb_a / np.linalg.norm(emb_a)

        emb_b = np.zeros(768, dtype=np.float32)
        emb_b[384:] = 1.0
        emb_b = emb_b / np.linalg.norm(emb_b)

        lib.add_gesture("gesture_a", "agreement", "Nod", emb_a, 500,
                        ["head"], 0.5)
        lib.add_gesture("gesture_b", "emphasis", "Chop", emb_b, 600,
                        ["hands"], 0.8)

        # Query embedding close to gesture_a.
        query = np.zeros(768, dtype=np.float32)
        query[:384] = 1.0
        query = query / np.linalg.norm(query)

        result = lib.select(query)
        assert result.gesture_id == "gesture_a"

    def test_select_with_category_filter(self) -> None:
        """Category filter restricts search to matching gestures."""
        lib = GestureLibrary()
        lib.build_default_library()

        # Get the embedding of an agreement gesture.
        agreement_gestures = lib.get_by_category("agreement")
        assert len(agreement_gestures) > 0

        query = agreement_gestures[0].embedding.copy()
        result = lib.select(query, category="agreement")

        assert result.category == "agreement"

    def test_select_category_filter_excludes_others(self) -> None:
        """Filtering by category only returns gestures from that category."""
        lib = GestureLibrary()

        emb_agree = np.ones(768, dtype=np.float32) * 0.5
        emb_agree = emb_agree / np.linalg.norm(emb_agree)

        emb_emphasis = np.ones(768, dtype=np.float32) * 0.5
        emb_emphasis = emb_emphasis / np.linalg.norm(emb_emphasis)

        lib.add_gesture("nod", "agreement", "Nod", emb_agree, 500,
                        ["head"], 0.5)
        lib.add_gesture("chop", "emphasis", "Chop", emb_emphasis, 600,
                        ["hands"], 0.8)

        # Even though both have similar embeddings, filter should
        # restrict to agreement only.
        result = lib.select(emb_agree, category="agreement")
        assert result.gesture_id == "nod"

    def test_empty_library_raises(self) -> None:
        """Select on empty library raises BehaviorError."""
        lib = GestureLibrary()
        query = np.ones(768, dtype=np.float32)

        with pytest.raises(BehaviorError, match="empty"):
            lib.select(query)

    def test_no_matching_category_raises(self) -> None:
        """Select with non-existent category raises BehaviorError."""
        lib = GestureLibrary()
        lib.build_default_library()
        query = np.ones(768, dtype=np.float32)

        with pytest.raises(BehaviorError, match="No gestures found"):
            lib.select(query, category="nonexistent_category")

    def test_add_gesture_duplicate_raises(self) -> None:
        """Adding a gesture with existing ID raises BehaviorError."""
        lib = GestureLibrary()
        emb = np.ones(768, dtype=np.float32)

        lib.add_gesture("test_1", "agreement", "Test", emb, 500,
                        ["head"], 0.5)

        with pytest.raises(BehaviorError, match="already exists"):
            lib.add_gesture("test_1", "emphasis", "Test2", emb, 600,
                            ["hands"], 0.8)

    def test_add_gesture_invalid_embedding_raises(self) -> None:
        """Non-1D embedding raises BehaviorError."""
        lib = GestureLibrary()

        with pytest.raises(BehaviorError):
            lib.add_gesture(
                "bad", "agreement", "Bad", np.zeros((2, 384)),
                500, ["head"], 0.5,
            )

    def test_select_invalid_embedding_raises(self) -> None:
        """Invalid query embedding raises BehaviorError."""
        lib = GestureLibrary()
        lib.build_default_library()

        with pytest.raises(BehaviorError):
            lib.select(np.zeros((2, 384)))

    def test_sqlite_persistence(self, tmp_path: pytest.TempPathFactory) -> None:
        """Gestures persist across library instances via SQLite."""
        db_file = str(tmp_path / "gestures.db")

        # Write gestures.
        lib1 = GestureLibrary(db_path=db_file)
        emb = np.ones(768, dtype=np.float32)
        emb = emb / np.linalg.norm(emb)
        lib1.add_gesture("test_persist", "agreement", "Persist test",
                         emb, 500, ["head"], 0.6)
        assert lib1.size == 1

        # Read back from new instance.
        lib2 = GestureLibrary(db_path=db_file)
        assert lib2.size == 1

        gestures = lib2.get_by_category("agreement")
        assert len(gestures) == 1
        assert gestures[0].gesture_id == "test_persist"

    def test_default_library_idempotent(self) -> None:
        """Calling build_default_library twice does not duplicate gestures."""
        lib = GestureLibrary()
        lib.build_default_library()
        count_1 = lib.size

        lib.build_default_library()
        count_2 = lib.size

        assert count_1 == count_2

    def test_gesture_clip_body_parts(self) -> None:
        """GestureClip body_parts are preserved correctly."""
        lib = GestureLibrary()
        emb = np.ones(768, dtype=np.float32)
        lib.add_gesture(
            "multi_part", "emphasis", "Multi part gesture",
            emb, 700, ["head", "shoulders", "hands"], 0.9,
        )

        gestures = lib.get_by_category("emphasis")
        assert gestures[0].body_parts == ["head", "shoulders", "hands"]


# ===================================================================
# Integration: imports from phoenix.expression
# ===================================================================

class TestExpressionPackageExports:
    """Verify that all public types are re-exported from the package."""

    def test_emotion_fusion_importable(self) -> None:
        """EmotionFusion is importable from phoenix.expression."""
        from phoenix.expression import EmotionFusion as EF
        assert EF is EmotionFusion

    def test_emotion_state_importable(self) -> None:
        """EmotionState is importable from phoenix.expression."""
        from phoenix.expression import EmotionState as ES
        assert ES is EmotionState

    def test_prosody_features_importable(self) -> None:
        """ProsodyFeatures is importable from phoenix.expression."""
        from phoenix.expression import ProsodyFeatures as PF
        assert PF is ProsodyFeatures

    def test_speaker_tracker_importable(self) -> None:
        """SpeakerTracker is importable from phoenix.expression."""
        from phoenix.expression import SpeakerTracker as ST
        assert ST is SpeakerTracker

    def test_speaker_info_importable(self) -> None:
        """SpeakerInfo is importable from phoenix.expression."""
        from phoenix.expression import SpeakerInfo as SI
        assert SI is SpeakerInfo

    def test_gesture_library_importable(self) -> None:
        """GestureLibrary is importable from phoenix.expression."""
        from phoenix.expression import GestureLibrary as GL
        assert GL is GestureLibrary

    def test_gesture_clip_importable(self) -> None:
        """GestureClip is importable from phoenix.expression."""
        from phoenix.expression import GestureClip as GC
        assert GC is GestureClip
