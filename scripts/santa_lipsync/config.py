"""Paths, training dimensions and loss weights for Santa lip-sync LoRA training."""
from pathlib import Path

# ============================================================
#  Paths
# ============================================================
MODEL_PATH = "/home/cabdru/echomimic_v3/pretrained_weights/Wan2.1-Fun-V1.1-1.3B-InP"
TRANSFORMER_PATH = "/home/cabdru/echomimic_v3/pretrained_weights/echomimicv3-flash-pro/diffusion_pytorch_model.safetensors"
WAV2VEC_DIR = "/home/cabdru/echomimic_v3/pretrained_weights/chinese-wav2vec2-base"
CONFIG_PATH = "/home/cabdru/echomimic_v3/config/config.yaml"

DATA_DIR = Path.home() / "echomimic_v3" / "datasets" / "santa_teleological"
COND_DIR = DATA_DIR / "conditioning"
LABELS_FILE = DATA_DIR / "labels.json"
SOURCE_VIDEO = Path.home() / ".clipcannon" / "projects" / "proj_2ea7221d" / "source" / "2026-04-03 04-23-11.mp4"
VOCALS_WAV = Path.home() / ".clipcannon" / "projects" / "proj_2ea7221d" / "stems" / "vocals.wav"
REFERENCE_IMAGE = Path.home() / ".clipcannon" / "models" / "santa" / "reference" / "santa_fullframe_600s.png"

OUTPUT_DIR = Path.home() / ".clipcannon" / "models" / "santa" / "echov3_lipsync"

# Training dimensions
VIDEO_LENGTH = 49           # frames at 25 fps
LATENT_T = 13               # (49-1)//4 + 1
RESOLUTION = 480            # 480x480 input
LATENT_SPATIAL = 60         # 480 / 8

# Loss weighting
MOUTH_WEIGHT = 10.0
FACE_WEIGHT = 2.0
BG_WEIGHT = 1.0
