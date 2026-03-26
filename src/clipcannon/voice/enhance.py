"""Post-processing audio enhancement for TTS output.

Removes metallic vocoder artifacts from Qwen3-TTS codec output and
extends bandwidth from 24kHz to 44.1kHz broadcast quality using
Resemble Enhance (denoise + latent conditional flow matching).

The enhancement pipeline:
  1. Denoise — removes broadband codec quantization noise
  2. Enhance — restores missing high-frequency content and smooths
     harmonic ringing via latent flow matching (44.1kHz output)
"""

from __future__ import annotations

import logging
from pathlib import Path

import torch
import torchaudio

logger = logging.getLogger(__name__)

# Module-level singleton for the enhancer (lazy loaded)
_enhancer_loaded = False

# NVRTC library path needed for torch.stft on RTX 5090
_NVRTC_PATHS = [
    "/usr/local/cuda-13.1/targets/x86_64-linux/lib/libnvrtc-builtins.so.13.0",
    "/usr/local/cuda-13.2/targets/x86_64-linux/lib/libnvrtc-builtins.so.13.2",
    "/usr/local/cuda/lib64/libnvrtc-builtins.so",
]
_nvrtc_loaded = False


def _ensure_nvrtc() -> None:
    """Preload NVRTC builtins into the current process.

    torch.stft uses NVRTC JIT compilation which needs libnvrtc-builtins.
    On WSL2 with multiple CUDA toolkits, the library isn't always on
    the default search path. We force-load it via ctypes.CDLL with
    RTLD_GLOBAL so all subsequent dlopen calls can find it.
    """
    global _nvrtc_loaded
    if _nvrtc_loaded:
        return
    import ctypes
    import os
    for path in _NVRTC_PATHS:
        if os.path.exists(path):
            try:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                _nvrtc_loaded = True
                logger.debug("Preloaded NVRTC: %s", path)
                return
            except OSError:
                continue
    # Fallback: set LD_LIBRARY_PATH for child processes
    cuda_lib = "/usr/local/cuda-13.1/targets/x86_64-linux/lib"
    if os.path.isdir(cuda_lib):
        ld = os.environ.get("LD_LIBRARY_PATH", "")
        if cuda_lib not in ld:
            os.environ["LD_LIBRARY_PATH"] = f"{cuda_lib}:{ld}"
    logger.warning("Could not preload NVRTC builtins, torch.stft may fail")


def enhance_speech(
    input_path: Path,
    output_path: Path | None = None,
    nfe: int = 64,
    lambd: float = 0.9,
    tau: float = 0.5,
    denoise_first: bool = True,
) -> Path:
    """Enhance TTS audio to broadcast quality.

    Removes metallic vocoder artifacts and extends bandwidth from
    24kHz to 44.1kHz using Resemble Enhance.

    Args:
        input_path: Path to input WAV (typically 24kHz from Qwen3-TTS).
        output_path: Where to write enhanced WAV. If None, writes next
            to input with ``_enhanced`` suffix.
        nfe: Number of function evaluations for the flow matching solver.
            Higher = better quality, slower. 64 is high quality, 32 is fast.
        lambd: Latent blending strength (0.0-1.0). Higher values apply
            stronger artifact removal. 0.9 is aggressive (recommended
            for TTS), 0.5 for light touch.
        tau: Enhancement strength (0.0-1.0). Controls how much the model
            restores vs preserves. 0.5 is balanced.
        denoise_first: Run the denoiser stage before enhancement.
            Recommended for TTS output.

    Returns:
        Path to the enhanced WAV file (44.1kHz).
    """
    _ensure_nvrtc()

    from resemble_enhance.enhancer.inference import denoise, enhance

    if output_path is None:
        output_path = input_path.parent / f"{input_path.stem}_enhanced.wav"

    device = "cuda" if torch.cuda.is_available() else "cpu"

    dwav, sr = torchaudio.load(str(input_path))
    dwav = dwav.mean(dim=0).float()  # mono, float32
    input_dur = len(dwav) / sr

    logger.info(
        "Enhancing %s (%.1fs, %dHz) -> %dHz",
        input_path.name, input_dur, sr, 44100,
    )

    if denoise_first:
        dwav, sr = denoise(dwav, sr, device)

    hwav, new_sr = enhance(
        dwav, sr, device,
        nfe=nfe,
        solver="midpoint",
        lambd=lambd,
        tau=tau,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(output_path), hwav.unsqueeze(0).cpu(), new_sr)

    logger.info(
        "Enhanced: %dHz -> %dHz, %.1fs -> %s",
        sr, new_sr, input_dur, output_path.name,
    )
    return output_path
