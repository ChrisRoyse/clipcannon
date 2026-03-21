#!/usr/bin/env python3
"""Validate GPU capabilities for ClipCannon.

Reports GPU name, VRAM, compute capability, CUDA version,
selected precision tier, and estimated model loading strategy.
"""

import sys
import warnings

warnings.filterwarnings("ignore")


def main() -> None:
    """Run GPU validation and print report."""
    print("=" * 60)
    print("  ClipCannon GPU Validation")
    print("=" * 60)
    print()

    try:
        import torch
    except ImportError:
        print("ERROR: PyTorch not installed.")
        print("  Install with: pip install torch")
        sys.exit(1)

    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available:  {torch.cuda.is_available()}")

    if not torch.cuda.is_available():
        print()
        print("WARNING: No CUDA GPU detected.")
        print("  ClipCannon will run in CPU-only mode.")
        print("  Pipeline stages will be significantly slower.")
        print("  Minimum recommended: NVIDIA RTX 2000 series (Turing)")
        sys.exit(0)

    print(f"CUDA version:    {torch.version.cuda}")
    print()

    device_count = torch.cuda.device_count()
    print(f"GPU count: {device_count}")
    print()

    for i in range(device_count):
        props = torch.cuda.get_device_properties(i)
        cc = f"{props.major}.{props.minor}"
        vram_gb = props.total_memory / (1024 ** 3)

        # Precision selection
        precision_map = {
            "12.0": ("nvfp4", "Blackwell"),
            "8.9": ("int8", "Ada Lovelace"),
            "8.6": ("int8", "Ampere"),
            "7.5": ("fp16", "Turing"),
        }
        precision, arch = precision_map.get(cc, ("fp16", "Unknown"))

        # Model loading strategy
        if vram_gb >= 16:
            strategy = "concurrent (all models loaded at once)"
        else:
            strategy = "sequential (load/unload per stage, ~3x slower)"

        print(f"  GPU {i}: {props.name}")
        print(f"    Compute capability: {cc} ({arch})")
        print(f"    VRAM:               {vram_gb:.1f} GB")
        print(f"    CUDA cores:         {props.multi_processor_count} SMs")
        print(f"    Selected precision: {precision}")
        print(f"    Loading strategy:   {strategy}")

        if vram_gb < 8:
            print(f"    WARNING: VRAM < 8GB. Some stages may fail.")
        print()

    print("=" * 60)
    print("  Validation complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
