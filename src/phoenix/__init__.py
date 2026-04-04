"""Phoenix — GPU-native avatar engine for ClipCannon.

This package provides zero-copy GPU compositing, 3D Gaussian Splat
rendering, and embedding-driven avatar behavior. All operations
run entirely on GPU via CuPy and CUDA kernels.

Exports:
    Error hierarchy: PhoenixError, CompositorError, RenderError,
        ExpressionError, BehaviorError
    Configuration: PhoenixConfig, CompositorConfig, RenderConfig,
        BehaviorWeights
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

__all__ = [
    "BehaviorError",
    "BehaviorWeights",
    "CompositorConfig",
    "CompositorError",
    "ExpressionError",
    "PhoenixConfig",
    "PhoenixError",
    "RenderConfig",
    "RenderError",
]
