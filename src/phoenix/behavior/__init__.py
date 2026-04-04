"""Behavior intelligence layer for the Phoenix avatar engine.

Composes expression-layer outputs (EmotionState, ProsodyFeatures,
GestureLibrary) into complete avatar behavior decisions: gesture
selection, prosody matching, emotion mirroring, and social signal
detection.

Exports:
    BehaviorEngine: Top-level orchestrator for all behavior decisions.
    BehaviorOutput: Complete avatar behavior decision for one frame.
    GestureSelector: Selects gestures based on response text + emotion.
    ProsodyMatcher: Matches TTS style to room prosody context.
    ProsodyMatch: Frozen dataclass of prosody match results.
    EmotionMirror: Maps emotion to avatar facial expressions.
    AvatarExpression: Frozen dataclass of expression blend shapes.
    CrossModalDetector: Detects social signals from embedding analysis.
    SocialSignal: Frozen dataclass of detected social signals.
"""

from phoenix.behavior.cross_modal_detector import (
    CrossModalDetector,
    SocialSignal,
)
from phoenix.behavior.emotion_mirror import AvatarExpression, EmotionMirror
from phoenix.behavior.engine import BehaviorEngine, BehaviorOutput
from phoenix.behavior.gesture_selector import GestureSelector
from phoenix.behavior.prosody_matcher import ProsodyMatch, ProsodyMatcher

__all__ = [
    "AvatarExpression",
    "BehaviorEngine",
    "BehaviorOutput",
    "CrossModalDetector",
    "EmotionMirror",
    "GestureSelector",
    "ProsodyMatch",
    "ProsodyMatcher",
    "SocialSignal",
]
