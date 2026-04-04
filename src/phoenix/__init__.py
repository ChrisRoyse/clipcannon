"""Phoenix — GPU-native avatar engine for ClipCannon.

This package provides zero-copy GPU compositing, 3D Gaussian Splat
rendering, and embedding-driven avatar behavior. All operations
run entirely on GPU via CuPy and CUDA kernels.

Exports:
    Error hierarchy: PhoenixError, CompositorError, RenderError,
        ExpressionError, BehaviorError
    Configuration: PhoenixConfig, CompositorConfig, RenderConfig,
        BehaviorWeights
    Expression engine: EmotionFusion, EmotionState, ProsodyFeatures,
        SpeakerTracker, SpeakerInfo, GestureLibrary, GestureClip
"""

from phoenix.config import (
    BehaviorWeights,
    CompositorConfig,
    PhoenixConfig,
    RenderConfig,
)
from phoenix.errors import (
    BehaviorError,
    CompositorError,
    ExpressionError,
    PhoenixError,
    RenderError,
)
from phoenix.expression import (
    EmotionFusion,
    EmotionState,
    GestureClip,
    GestureLibrary,
    ProsodyFeatures,
    SpeakerInfo,
    SpeakerTracker,
)

__all__ = [
    "BehaviorError",
    "BehaviorWeights",
    "CompositorConfig",
    "CompositorError",
    "EmotionFusion",
    "EmotionState",
    "ExpressionError",
    "GestureClip",
    "GestureLibrary",
    "PhoenixConfig",
    "PhoenixError",
    "ProsodyFeatures",
    "RenderConfig",
    "RenderError",
    "SpeakerInfo",
    "SpeakerTracker",
]
