"""GPU management for ClipCannon.

Provides auto-detection of GPU capabilities, precision selection,
VRAM monitoring, and model lifecycle management.
"""

from clipcannon.gpu.manager import GPUHealthReport, ModelManager
from clipcannon.gpu.precision import (
    PRECISION_MAP,
    auto_detect_precision,
    get_compute_capability,
)

__all__ = [
    "GPUHealthReport",
    "ModelManager",
    "PRECISION_MAP",
    "auto_detect_precision",
    "get_compute_capability",
]
