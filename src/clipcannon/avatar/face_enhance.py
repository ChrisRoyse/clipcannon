"""CodeFormer face enhancement for lip-sync output.

Applies CodeFormer restoration to each face frame to fix:
- Blur in the mouth region from diffusion VAE encode/decode
- Skin texture artifacts from the latent space processing
- Minor mask boundary imperfections

Uses ~2GB additional VRAM. Processing: ~50ms per face frame.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

logger = logging.getLogger(__name__)

_CODEFORMER_DIR = Path.home() / ".clipcannon" / "models" / "codeformer"
_WEIGHTS_PATH = _CODEFORMER_DIR / "weights" / "CodeFormer" / "codeformer.pth"

_model: object | None = None


def _ensure_model(device: str = "cuda") -> tuple[object, str]:
    """Lazy-load CodeFormer model.

    Returns:
        (model, device) tuple.
    """
    global _model

    if _model is not None:
        return _model, device

    if not _WEIGHTS_PATH.exists():
        raise FileNotFoundError(
            f"CodeFormer weights not found at {_WEIGHTS_PATH}. "
            "Download from: https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth"
        )

    # Add CodeFormer repo to path for imports
    cf_str = str(_CODEFORMER_DIR)
    if cf_str not in sys.path:
        sys.path.insert(0, cf_str)

    from basicsr.archs.codeformer_arch import CodeFormer

    model = CodeFormer(
        dim_embd=512,
        codebook_size=1024,
        n_head=8,
        n_layers=9,
        connect_list=["32", "64", "128", "256"],
    )

    ckpt = torch.load(str(_WEIGHTS_PATH), map_location="cpu", weights_only=False)
    model.load_state_dict(ckpt["params_ema"])
    model.eval()
    model = model.to(device)

    _model = model
    logger.info("CodeFormer loaded on %s", device)
    return model, device


def enhance_face(
    face_bgr: np.ndarray,
    fidelity: float = 0.6,
    device: str = "cuda",
) -> np.ndarray:
    """Enhance a single face crop using CodeFormer.

    Args:
        face_bgr: Face image in BGR format, any resolution.
            Will be resized to 512x512 for processing and back.
        fidelity: Quality-fidelity tradeoff (0.0 = max restoration,
            1.0 = max fidelity to input). 0.5-0.7 recommended for
            lip-sync output.
        device: CUDA device.

    Returns:
        Enhanced face image in BGR format, same resolution as input.
    """
    model, device = _ensure_model(device)

    orig_h, orig_w = face_bgr.shape[:2]

    # Resize to 512x512 for CodeFormer
    face_input = cv2.resize(face_bgr, (512, 512), interpolation=cv2.INTER_LINEAR)

    # Normalize to [-1, 1] tensor
    face_t = torch.from_numpy(face_input.astype(np.float32) / 255.0)
    face_t = face_t.permute(2, 0, 1).unsqueeze(0)  # [1, 3, 512, 512]
    face_t = (face_t - 0.5) / 0.5  # normalize to [-1, 1]
    face_t = face_t.to(device)

    with torch.no_grad():
        output = model(face_t, w=fidelity, adain=True)[0]  # type: ignore[operator]

    # Back to numpy BGR
    output = (output.squeeze(0).clamp(-1, 1) + 1) / 2 * 255
    output = output.permute(1, 2, 0).cpu().numpy().astype(np.uint8)

    # Resize back to original resolution
    if orig_h != 512 or orig_w != 512:
        output = cv2.resize(output, (orig_w, orig_h), interpolation=cv2.INTER_LANCZOS4)

    return output


def enhance_face_batch(
    faces: list[np.ndarray],
    fidelity: float = 0.6,
    device: str = "cuda",
) -> list[np.ndarray]:
    """Enhance a batch of face crops.

    Processes one at a time to keep VRAM usage low.

    Args:
        faces: List of face images in BGR format.
        fidelity: Quality-fidelity tradeoff.
        device: CUDA device.

    Returns:
        List of enhanced face images.
    """
    return [enhance_face(f, fidelity, device) for f in faces]
