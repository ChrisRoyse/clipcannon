#!/usr/bin/env python3
"""Santa lip sync LoRA training with mouth-weighted loss + viseme curriculum.

ALL BLOCKERS FROM SHERLOCK AUDIT FIXED:
  1. Video extraction now uses FFmpeg with explicit 25fps (was reading at native 60fps)
  2. Mouth bboxes come from precomputed YOLOv5-Face landmarks (was geometric nose)
  3. Flow matching target corrected: noise - latent (was latent - noise)
  4. q_audio removed from LoRA targets (dead upstream, overwritten)
  5. v2 LoRA merging removed — trains all needed LoRA targets from scratch
  6. Audio features streamed to disk, not accumulated in RAM
  7. Real WeightedRandomSampler based on viseme rarity

Hard-fails if any required input is missing instead of silently falling back.

Usage:
    python scripts/train_santa_lipsync.py --phase encode
    python scripts/train_santa_lipsync.py --phase train --steps 3000
"""
# Implementation lives in the sibling package scripts/santa_lipsync/ (split for the
# 500-line file limit). This file is the unchanged entry point: it performs the original
# import-time setup in the original order and re-exports every top-level name.

import argparse
import gc
import json
import logging
import math
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
sys.stdout.reconfigure(line_buffering=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/santa_lipsync_train.log"),
    ],
)
log = logging.getLogger("lipsync")

sys.path.insert(0, "/home/cabdru/echomimic_v3")

import librosa
import numpy as np
import torch
import torch.nn.functional as F
from einops import rearrange
from omegaconf import OmegaConf
from PIL import Image
from safetensors.torch import load_file
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True

from peft import LoraConfig, get_peft_model
from santa_lipsync.config import (  # noqa: E402
    BG_WEIGHT,
    COND_DIR,
    CONFIG_PATH,
    DATA_DIR,
    FACE_WEIGHT,
    LABELS_FILE,
    LATENT_SPATIAL,
    LATENT_T,
    MODEL_PATH,
    MOUTH_WEIGHT,
    OUTPUT_DIR,
    REFERENCE_IMAGE,
    RESOLUTION,
    SOURCE_VIDEO,
    TRANSFORMER_PATH,
    VIDEO_LENGTH,
    VOCALS_WAV,
    WAV2VEC_DIR,
)
from santa_lipsync.data import (  # noqa: E402
    compute_latent_mouth_mask,
    extract_audio_features,
    extract_clip_frames_ffmpeg,
    loudness_norm,
    preflight_check,
)
from santa_lipsync.encode import pre_encode_all  # noqa: E402
from santa_lipsync.train import VisemeWeightedDataset, train_lipsync  # noqa: E402

__all__ = [
    "argparse", "gc", "json", "logging", "math", "os", "subprocess", "sys", "tempfile", "time",
    "Counter", "Path", "np", "librosa", "torch", "F", "Dataset", "DataLoader",
    "WeightedRandomSampler", "load_file", "OmegaConf", "Image", "rearrange", "LoraConfig",
    "get_peft_model", "log", "MODEL_PATH", "TRANSFORMER_PATH", "WAV2VEC_DIR", "CONFIG_PATH",
    "DATA_DIR", "COND_DIR", "LABELS_FILE", "SOURCE_VIDEO", "VOCALS_WAV", "REFERENCE_IMAGE",
    "OUTPUT_DIR", "VIDEO_LENGTH", "LATENT_T", "RESOLUTION", "LATENT_SPATIAL", "MOUTH_WEIGHT",
    "FACE_WEIGHT", "BG_WEIGHT", "preflight_check", "extract_clip_frames_ffmpeg",
    "loudness_norm", "extract_audio_features", "compute_latent_mouth_mask", "pre_encode_all",
    "VisemeWeightedDataset", "train_lipsync",
]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["encode", "train", "all"], default="all")
    parser.add_argument("--steps", type=int, default=3000)
    # rank=256 doubles trainable LoRA parameters for higher-quality identity
    # and lip sync fidelity. Requires a bit more VRAM (~1GB extra) but still
    # fits comfortably in 32GB.
    parser.add_argument("--rank", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-4)
    args = parser.parse_args()

    if args.phase in ("encode", "all"):
        pre_encode_all()
    if args.phase in ("train", "all"):
        train_lipsync(steps=args.steps, rank=args.rank, lr=args.lr)
