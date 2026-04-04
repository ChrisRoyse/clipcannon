"""Embedding-driven expression and behavior engine.

This package provides emotional intelligence for the Phoenix avatar
by fusing multiple embedding streams (emotion, prosody, semantic,
speaker) into actionable behavior signals.

Exports:
    EmotionFusion: Cross-modal emotion state from multiple embeddings.
    EmotionState: Frozen dataclass of fused emotion parameters.
    ProsodyFeatures: Frozen dataclass of 12 prosody scalar features.
    SpeakerTracker: Speaker identification via WavLM embeddings.
    SpeakerInfo: Frozen dataclass of tracked speaker metadata.
    GestureLibrary: Semantic-indexed gesture selection library.
    GestureClip: Frozen dataclass of gesture clip metadata.
"""

from phoenix.expression.emotion_fusion import (
    EmotionFusion,
    EmotionState,
    ProsodyFeatures,
)
from phoenix.expression.gesture_library import GestureClip, GestureLibrary
from phoenix.expression.speaker_tracker import SpeakerInfo, SpeakerTracker

__all__ = [
    "EmotionFusion",
    "EmotionState",
    "GestureClip",
    "GestureLibrary",
    "ProsodyFeatures",
    "SpeakerInfo",
    "SpeakerTracker",
]
