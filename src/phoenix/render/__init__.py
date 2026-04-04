"""Phoenix render subsystem — GPU compositor and renderer.

Re-exports all compositor functions for convenient access.
"""

from phoenix.render.cupy_compositor import (
    alpha_blend_gpu,
    brightness_jitter_gpu,
    color_convert_gpu,
    film_grain_gpu,
    paste_face_region_gpu,
    resize_gpu,
)

from phoenix.render.compositor_bridge import (
    gpu_alpha_blend,
    gpu_brightness_jitter,
    gpu_composite_face,
    gpu_film_grain,
)

__all__ = [
    "alpha_blend_gpu",
    "brightness_jitter_gpu",
    "color_convert_gpu",
    "film_grain_gpu",
    "paste_face_region_gpu",
    "resize_gpu",
    "gpu_alpha_blend",
    "gpu_brightness_jitter",
    "gpu_composite_face",
    "gpu_film_grain",
]
