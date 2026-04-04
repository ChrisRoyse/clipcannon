"""Audio2Face adapters for audio-to-blendshape conversion.

Provides both a gRPC client to NVIDIA Audio2Face-3D NIM and a local
signal-processing fallback that maps audio features to ARKit blendshapes.

Exports:
    BlendshapeFrame: 52 ARKit blendshape coefficients per frame.
    Audio2FaceAdapter: Abstract base for audio-to-blendshape conversion.
    Audio2FaceNIM: gRPC client to Audio2Face-3D NIM container.
    Audio2FaceLocal: Local audio-to-blendshape via signal processing.
    BlendshapeToFLAME: Maps ARKit blendshapes to FLAME expression coefficients.
    ARKIT_BLENDSHAPE_NAMES: Ordered list of 52 ARKit blendshape names.
"""

from phoenix.adapters.audio2face_adapter import (
    ARKIT_BLENDSHAPE_NAMES,
    Audio2FaceAdapter,
    Audio2FaceLocal,
    Audio2FaceNIM,
    BlendshapeFrame,
    BlendshapeToFLAME,
)

__all__ = [
    "ARKIT_BLENDSHAPE_NAMES",
    "Audio2FaceAdapter",
    "Audio2FaceLocal",
    "Audio2FaceNIM",
    "BlendshapeFrame",
    "BlendshapeToFLAME",
]
