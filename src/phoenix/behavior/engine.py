"""Top-level behavior orchestrator for the Phoenix avatar engine.

Composes all expression and behavior modules into a single entry point.
The meeting manager calls BehaviorEngine.process_listening() or
process_speaking() and gets back a complete BehaviorOutput that drives
the avatar renderer, TTS engine, and gesture player.

No CPU fallbacks. Errors propagate with full context.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from phoenix.behavior.cross_modal_detector import CrossModalDetector, SocialSignal
from phoenix.behavior.emotion_mirror import AvatarExpression, EmotionMirror
from phoenix.behavior.gesture_selector import GestureSelector
from phoenix.behavior.prosody_matcher import ProsodyMatch, ProsodyMatcher
from phoenix.config import PhoenixConfig
from phoenix.errors import BehaviorError, ExpressionError
from phoenix.expression.emotion_fusion import EmotionFusion, EmotionState, ProsodyFeatures
from phoenix.expression.gesture_library import GestureClip, GestureLibrary
from phoenix.expression.speaker_tracker import SpeakerInfo, SpeakerTracker

# Canonical embedding dimensions.
_EMOTION_DIM = 1024
_SPEAKER_DIM = 512
_SEMANTIC_DIM = 768


def _validate_embedding(
    name: str,
    embedding: np.ndarray,
    expected_dim: int,
) -> None:
    """Validate that an embedding has correct shape.

    Args:
        name: Human-readable name for error messages.
        embedding: The array to validate.
        expected_dim: Expected dimensionality.

    Raises:
        BehaviorError: If the array is not 1-D or has wrong size.
    """
    if embedding.ndim != 1:
        raise BehaviorError(
            f"{name} must be a 1-D array",
            {"name": name, "ndim": embedding.ndim, "expected_dim": expected_dim},
        )
    if embedding.size != expected_dim:
        raise BehaviorError(
            f"{name} must have {expected_dim} dimensions, got {embedding.size}",
            {"name": name, "size": embedding.size, "expected_dim": expected_dim},
        )


# Default expression returned when no emotion data is available.
_DEFAULT_EXPRESSION = AvatarExpression(
    jaw_open=0.0,
    brow_raise=0.0,
    brow_furrow=0.0,
    mouth_stretch=0.0,
    head_nod_intensity=0.0,
    head_tilt=0.0,
    eye_wide=0.0,
    squint=0.0,
)

# Default emotion returned when no emotion embedding is provided.
_DEFAULT_EMOTION = EmotionState(
    arousal=0.0,
    valence=0.5,
    energy=0.0,
    dominance=0.0,
    prosody_style="calm",
    is_sarcastic=False,
    confidence=0.0,
)

# Default social signal when detection cannot run.
_DEFAULT_SOCIAL_SIGNAL = SocialSignal(
    signal_type="neutral",
    confidence=0.0,
    sources=[],
)


@dataclass(frozen=True)
class BehaviorOutput:
    """Complete avatar behavior decision for one frame.

    Attributes:
        expression: Face blend shapes for the avatar renderer.
        gesture: Body gesture to play, or None if no gesture.
        tts_style: Prosody style string for the TTS engine.
        social_signal: Detected social context from cross-modal analysis.
        emotion: Current fused emotion state.
        active_speaker: Who is currently talking, or None.
        room_energy: Room energy level [0, 1].
    """

    expression: AvatarExpression
    gesture: GestureClip | None
    tts_style: str
    social_signal: SocialSignal
    emotion: EmotionState
    active_speaker: SpeakerInfo | None
    room_energy: float


class BehaviorEngine:
    """Orchestrates all embedding-driven behavior modules.

    Single entry point for all avatar behavior decisions. Call
    process_listening() when someone else is talking, or
    process_speaking() when the avatar is about to respond.

    Args:
        config: Optional PhoenixConfig for tuning behavior weights.
            If None, uses defaults.

    Raises:
        BehaviorError: If initialization of any sub-module fails.
    """

    def __init__(self, config: PhoenixConfig | None = None) -> None:
        self._config = config or PhoenixConfig()
        weights = self._config.behavior

        self._emotion_fusion = EmotionFusion(
            sarcasm_sensitivity=weights.sarcasm_sensitivity,
        )
        self._speaker_tracker = SpeakerTracker()
        self._gesture_library = GestureLibrary()
        self._gesture_library.build_default_library()
        self._gesture_selector = GestureSelector(self._gesture_library)
        self._prosody_matcher = ProsodyMatcher()
        self._emotion_mirror = EmotionMirror()
        self._cross_modal = CrossModalDetector(sensitivity=weights.sarcasm_sensitivity)

    def process_listening(
        self,
        emotion_embedding: np.ndarray | None = None,
        speaker_embedding: np.ndarray | None = None,
        prosody: ProsodyFeatures | None = None,
        semantic_embedding: np.ndarray | None = None,
        timestamp_ms: int = 0,
    ) -> BehaviorOutput:
        """Process embeddings during LISTENING mode.

        Runs the pipeline: validate inputs -> emotion fusion ->
        speaker tracking -> emotion mirroring -> social signal detection.

        Gracefully skips modules whose required inputs are missing.
        If an embedding IS provided but has wrong dimensions, raises
        immediately.

        Args:
            emotion_embedding: 1024-dim Wav2Vec2 emotion embedding.
            speaker_embedding: 512-dim WavLM speaker embedding.
            prosody: 12-field prosody feature set.
            semantic_embedding: 768-dim Nomic semantic embedding.
            timestamp_ms: Current timestamp in milliseconds.

        Returns:
            Complete BehaviorOutput for this frame.

        Raises:
            BehaviorError: If a provided embedding has wrong dimensions.
            ExpressionError: If emotion fusion encounters invalid data.
        """
        # --- Validate provided embeddings ---
        if emotion_embedding is not None:
            _validate_embedding("emotion_embedding", emotion_embedding, _EMOTION_DIM)
        if speaker_embedding is not None:
            _validate_embedding("speaker_embedding", speaker_embedding, _SPEAKER_DIM)
        if semantic_embedding is not None:
            _validate_embedding("semantic_embedding", semantic_embedding, _SEMANTIC_DIM)

        # --- Emotion Fusion ---
        emotion = _DEFAULT_EMOTION
        if emotion_embedding is not None and prosody is not None:
            raw_emotion = self._emotion_fusion.fuse(
                emotion_embedding, prosody, semantic_embedding,
            )
            emotion = self._emotion_fusion.update(raw_emotion)

        # --- Speaker Tracking ---
        active_speaker: SpeakerInfo | None = None
        if speaker_embedding is not None:
            self._speaker_tracker.track(speaker_embedding, timestamp_ms)
            active_speaker = self._speaker_tracker.get_active_speaker()

        # --- Prosody History ---
        room_energy = 0.0
        if prosody is not None:
            self._prosody_matcher.update(prosody)
            # Compute room energy from the prosody matcher's match.
            pm = self._prosody_matcher.match("")
            room_energy = pm.room_energy

        # --- Emotion Mirroring (listening) ---
        expression = _DEFAULT_EXPRESSION
        if emotion is not _DEFAULT_EMOTION:
            expression = self._emotion_mirror.mirror(emotion, is_speaking=False)

        # --- Social Signal Detection ---
        social_signal = _DEFAULT_SOCIAL_SIGNAL
        if emotion is not _DEFAULT_EMOTION and prosody is not None:
            social_signal = self._cross_modal.detect(
                emotion, prosody, semantic_embedding,
            )

        return BehaviorOutput(
            expression=expression,
            gesture=None,
            tts_style="calm",
            social_signal=social_signal,
            emotion=emotion,
            active_speaker=active_speaker,
            room_energy=room_energy,
        )

    def process_speaking(
        self,
        response_text: str,
        emotion_embedding: np.ndarray | None = None,
        prosody: ProsodyFeatures | None = None,
        semantic_embedding: np.ndarray | None = None,
    ) -> BehaviorOutput:
        """Process embeddings during SPEAKING mode.

        Runs the pipeline: validate inputs -> emotion fusion ->
        prosody matching -> gesture selection -> expression generation.

        Returns TTS style, gesture to play, and expression parameters.

        Args:
            response_text: The avatar's response text. Must not be empty.
            emotion_embedding: 1024-dim Wav2Vec2 emotion embedding.
            prosody: 12-field prosody feature set.
            semantic_embedding: 768-dim Nomic semantic embedding.

        Returns:
            Complete BehaviorOutput for the speaking turn.

        Raises:
            BehaviorError: If response_text is empty, or if a provided
                embedding has wrong dimensions.
            ExpressionError: If emotion fusion encounters invalid data.
        """
        if not response_text.strip():
            raise BehaviorError(
                "response_text must not be empty for speaking mode",
                {"response_text": response_text},
            )

        # --- Validate provided embeddings ---
        if emotion_embedding is not None:
            _validate_embedding("emotion_embedding", emotion_embedding, _EMOTION_DIM)
        if semantic_embedding is not None:
            _validate_embedding("semantic_embedding", semantic_embedding, _SEMANTIC_DIM)

        # --- Emotion Fusion ---
        emotion = _DEFAULT_EMOTION
        if emotion_embedding is not None and prosody is not None:
            raw_emotion = self._emotion_fusion.fuse(
                emotion_embedding, prosody, semantic_embedding,
            )
            emotion = self._emotion_fusion.update(raw_emotion)

        # --- Prosody Matching ---
        if prosody is not None:
            self._prosody_matcher.update(prosody)
        prosody_match = self._prosody_matcher.match(response_text)
        tts_style = prosody_match.target_style
        room_energy = prosody_match.room_energy

        # --- Gesture Selection ---
        emotion_for_gesture = emotion if emotion is not _DEFAULT_EMOTION else None
        gesture: GestureClip | None = self._gesture_selector.select_for_response(
            response_text, emotion_for_gesture,
        )

        # --- Expression ---
        expression = _DEFAULT_EXPRESSION
        if prosody is not None:
            expression = self._emotion_mirror.prosody_to_expression(prosody)
        elif emotion is not _DEFAULT_EMOTION:
            expression = self._emotion_mirror.mirror(emotion, is_speaking=True)

        # --- Social Signal ---
        social_signal = _DEFAULT_SOCIAL_SIGNAL
        if emotion is not _DEFAULT_EMOTION and prosody is not None:
            social_signal = self._cross_modal.detect(
                emotion, prosody, semantic_embedding,
            )

        return BehaviorOutput(
            expression=expression,
            gesture=gesture,
            tts_style=tts_style,
            social_signal=social_signal,
            emotion=emotion,
            active_speaker=None,
            room_energy=room_energy,
        )

    def reset(self) -> None:
        """Clear all state for a new meeting.

        Resets emotion fusion, prosody matcher, and reinitializes the
        speaker tracker. The gesture library is NOT cleared since it
        contains static gesture definitions.
        """
        self._emotion_fusion.reset()
        self._prosody_matcher.reset()
        # SpeakerTracker has no reset — reinitialize.
        self._speaker_tracker = SpeakerTracker()
