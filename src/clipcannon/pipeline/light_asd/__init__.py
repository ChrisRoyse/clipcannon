"""Light-ASD active speaker detection (vendored model definition).

Upstream: https://github.com/Junhua-Liao/Light-ASD (MIT, see LICENSE in this
directory), commit ed38c232de5efe0261dbd68627c0ade7cdfe14eb.
Liao et al., "A Light Weight Model for Active Speaker Detection", CVPR 2023.

Only the inference path is vendored. Layer names are unchanged so the
published ``pretrain_AVA_CVPR.model`` state dict loads directly.
"""
from clipcannon.pipeline.light_asd.model import LightASD, load_light_asd

__all__ = ["LightASD", "load_light_asd"]
