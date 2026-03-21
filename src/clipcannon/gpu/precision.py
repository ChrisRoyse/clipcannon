"""GPU precision auto-detection based on CUDA compute capability.

Maps GPU hardware generations to optimal quantization formats:
    - Blackwell (CC 12.0): nvfp4
    - Ada Lovelace (CC 8.9): int8
    - Ampere (CC 8.6): int8
    - Turing (CC 7.5): fp16
    - No GPU / unsupported: fp32 (CPU fallback)
"""

from __future__ import annotations

import logging

from clipcannon.exceptions import GPUError

logger = logging.getLogger(__name__)

PRECISION_MAP: dict[str, str] = {
    "12.0": "nvfp4",
    "8.9": "int8",
    "8.6": "int8",
    "7.5": "fp16",
}

DEFAULT_CPU_PRECISION = "fp32"


def _is_torch_available() -> bool:
    """Check whether PyTorch is importable.

    Returns:
        True if torch can be imported, False otherwise.
    """
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def _is_cuda_available() -> bool:
    """Check whether CUDA is available via PyTorch.

    Returns:
        True if CUDA is available, False otherwise.
    """
    if not _is_torch_available():
        return False
    import torch
    return torch.cuda.is_available()


def get_compute_capability(device_index: int = 0) -> str | None:
    """Get the CUDA compute capability string for a device.

    Args:
        device_index: CUDA device index (default 0).

    Returns:
        Compute capability as "major.minor" string, or None if no GPU.
    """
    if not _is_cuda_available():
        return None

    try:
        import torch
        major, minor = torch.cuda.get_device_capability(device_index)
        cc = f"{major}.{minor}"
        logger.info("Detected GPU compute capability: %s", cc)
        return cc
    except Exception as exc:
        logger.warning("Failed to get compute capability for device %d: %s", device_index, exc)
        return None


def auto_detect_precision(device_index: int = 0) -> str:
    """Auto-detect the optimal precision for the current GPU.

    Looks up the GPU compute capability in PRECISION_MAP. Falls back
    to fp32 (CPU mode) if no GPU is detected or the compute capability
    is not in the map.

    Args:
        device_index: CUDA device index (default 0).

    Returns:
        Precision string: "nvfp4", "int8", "fp16", or "fp32".
    """
    cc = get_compute_capability(device_index)

    if cc is None:
        logger.warning("No CUDA GPU detected. Using CPU mode with %s precision.", DEFAULT_CPU_PRECISION)
        return DEFAULT_CPU_PRECISION

    precision = PRECISION_MAP.get(cc)
    if precision is None:
        # Try matching just major.minor prefix for forward compatibility
        major = cc.split(".")[0]
        for map_cc, map_precision in sorted(PRECISION_MAP.items(), reverse=True):
            if map_cc.startswith(major + "."):
                precision = map_precision
                logger.info(
                    "CC %s not in precision map; using closest match %s -> %s",
                    cc, map_cc, precision,
                )
                break

    if precision is None:
        cc_float = float(cc)
        if cc_float >= 8.0:
            precision = "int8"
        elif cc_float >= 7.0:
            precision = "fp16"
        else:
            precision = DEFAULT_CPU_PRECISION
        logger.warning(
            "CC %s not recognized. Falling back to %s precision.",
            cc, precision,
        )

    logger.info("Selected precision: %s (CC %s)", precision, cc)
    return precision


def validate_gpu_for_pipeline(device_index: int = 0) -> dict[str, str | int | float | bool]:
    """Validate that the GPU meets minimum requirements for the pipeline.

    Args:
        device_index: CUDA device index (default 0).

    Returns:
        Dictionary with GPU validation results.

    Raises:
        GPUError: If torch is available but CUDA reports errors.
    """
    result: dict[str, str | int | float | bool] = {
        "torch_available": _is_torch_available(),
        "cuda_available": _is_cuda_available(),
        "cpu_only": True,
    }

    if not _is_torch_available():
        result["warning"] = "PyTorch not installed. Running in CPU-only mode."
        return result

    if not _is_cuda_available():
        result["warning"] = "No CUDA GPU detected. Running in CPU-only mode."
        return result

    try:
        import torch
        props = torch.cuda.get_device_properties(device_index)
        vram_gb = props.total_memory / (1024 ** 3)

        result.update({
            "cpu_only": False,
            "device_name": props.name,
            "compute_capability": f"{props.major}.{props.minor}",
            "vram_total_gb": round(vram_gb, 2),
            "precision": auto_detect_precision(device_index),
            "meets_minimum": vram_gb >= 8.0,
        })

        if vram_gb < 8.0:
            result["warning"] = (
                f"GPU {props.name} has only {vram_gb:.1f} GB VRAM. "
                "Minimum 8 GB recommended for sequential pipeline execution."
            )

    except Exception as exc:
        raise GPUError(
            f"Failed to validate GPU device {device_index}: {exc}",
            details={"device_index": device_index},
        ) from exc

    return result
