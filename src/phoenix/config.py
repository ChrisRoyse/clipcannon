"""Phoenix configuration as frozen dataclasses.

All tunable parameters for the GPU-native avatar engine live here.
Frozen to prevent accidental mutation during pipeline execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CompositorConfig:
    """Settings for the CuPy GPU compositor.

    Attributes:
        film_grain_intensity: Strength of additive film grain noise [0, 1].
        brightness_jitter_amount: Max brightness shift per frame [0, 1].
        default_alpha: Default alpha for face paste when not specified.
        target_height: Default compositor output height in pixels.
        target_width: Default compositor output width in pixels.
        dtype: GPU array dtype string (always float32 for compositor).
    """

    film_grain_intensity: float = 0.02
    brightness_jitter_amount: float = 0.01
    default_alpha: float = 1.0
    target_height: int = 1080
    target_width: int = 1920
    dtype: str = "float32"


@dataclass(frozen=True)
class RenderConfig:
    """Settings for the 3D Gaussian Splat renderer.

    Attributes:
        fps: Target frames per second.
        resolution_h: Render height in pixels.
        resolution_w: Render width in pixels.
        gaussian_sh_degree: Spherical harmonics degree for color.
        rasterizer_backend: Which rasterizer to use.
        nvenc_preset: NVENC encoder preset string.
        nvenc_bitrate_mbps: Target bitrate in megabits per second.
        avatar_tex_size: UV texture resolution for Gaussian binding.
        avatar_num_basis: Number of blendshape bases for Gaussians.
        avatar_fov_y: Vertical field of view in degrees.
    """

    fps: int = 30
    resolution_h: int = 720
    resolution_w: int = 1280
    gaussian_sh_degree: int = 3
    rasterizer_backend: str = "gsplat"
    nvenc_preset: str = "p4"
    nvenc_bitrate_mbps: float = 8.0
    avatar_tex_size: int = 256
    avatar_num_basis: int = 20
    avatar_fov_y: float = 25.0


@dataclass(frozen=True)
class BehaviorWeights:
    """Tunable weights for the embedding-driven behavior system.

    Each weight controls how strongly that embedding signal influences
    avatar behavior. Range [0, 1] for each. Set to 0 to disable a signal.

    Attributes:
        emotion_weight: Influence of Wav2Vec2 emotion embedding.
        prosody_weight: Influence of prosody features (F0, energy, rate).
        semantic_weight: Influence of Nomic semantic embedding.
        speaker_weight: Influence of WavLM speaker embedding.
        gesture_weight: Influence of gesture selection from semantic search.
        gaze_weight: Influence of speaker-tracking gaze system.
        predictive_weight: Influence of predictive pre-rendering.
        sarcasm_sensitivity: Threshold for cross-modal sarcasm detection.
    """

    emotion_weight: float = 1.0
    prosody_weight: float = 0.8
    semantic_weight: float = 0.7
    speaker_weight: float = 0.9
    gesture_weight: float = 0.6
    gaze_weight: float = 0.8
    predictive_weight: float = 0.5
    sarcasm_sensitivity: float = 0.7


@dataclass(frozen=True)
class PhoenixConfig:
    """Top-level configuration for the Phoenix avatar engine.

    Aggregates all subsystem configs into a single frozen object.

    Attributes:
        compositor: GPU compositor settings.
        render: 3D Gaussian Splat renderer settings.
        behavior: Embedding-driven behavior weights.
        device_id: CUDA device index.
        log_timings: Whether to emit DEBUG timing logs.
    """

    compositor: CompositorConfig = field(default_factory=CompositorConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    behavior: BehaviorWeights = field(default_factory=BehaviorWeights)
    device_id: int = 0
    log_timings: bool = True
