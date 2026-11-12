"""Preflight, FFmpeg/Wav2Vec clip extraction and latent mouth masks (lip-sync training)."""
import logging
import math
import subprocess
import tempfile
from pathlib import Path

import librosa
import numpy as np
import torch
from einops import rearrange

from .config import (
    BG_WEIGHT,
    CONFIG_PATH,
    FACE_WEIGHT,
    LABELS_FILE,
    MODEL_PATH,
    MOUTH_WEIGHT,
    REFERENCE_IMAGE,
    SOURCE_VIDEO,
    TRANSFORMER_PATH,
    VOCALS_WAV,
    WAV2VEC_DIR,
)

log = logging.getLogger("lipsync")


# ============================================================
#  Utility: fail-fast preflight
# ============================================================

def preflight_check():
    """Verify every required input exists before starting."""
    required = {
        "MODEL_PATH": Path(MODEL_PATH),
        "TRANSFORMER_PATH": Path(TRANSFORMER_PATH),
        "WAV2VEC_DIR": Path(WAV2VEC_DIR),
        "CONFIG_PATH": Path(CONFIG_PATH),
        "SOURCE_VIDEO": SOURCE_VIDEO,
        "VOCALS_WAV": VOCALS_WAV,
        "REFERENCE_IMAGE": REFERENCE_IMAGE,
        "LABELS_FILE": LABELS_FILE,
    }
    errors = []
    for name, path in required.items():
        if not path.exists():
            errors.append(f"{name}: {path}")
    if errors:
        log.error("Missing required files:")
        for e in errors:
            log.error("  %s", e)
        raise FileNotFoundError(
            "Preflight failed. Run precompute_face_landmarks.py and "
            "label_training_clips.py first."
        )
    log.info("Preflight OK — all required inputs present")


# ============================================================
#  Video extraction (BLOCKER 1 FIX: use FFmpeg at explicit 25fps)
# ============================================================

def extract_clip_frames_ffmpeg(source_video: Path, start_ms: int, n_frames: int,
                                resolution: int) -> torch.Tensor:
    """Extract exactly n_frames starting at start_ms, at 25fps, sized to resolution.

    FIX: Previous version used cv2.VideoCapture which reads at source FPS (60).
    This made clips 2.4x shorter than intended in time. FFmpeg with -r 25 forces
    25fps output regardless of source FPS.

    Uses a scale+crop pipeline to produce resolution x resolution square output
    with the face centered as much as possible. The scene_map face is ROUGHLY
    centered horizontally in the source, so we just do a center crop.
    """
    import cv2

    start_s = start_ms / 1000.0
    duration_s = n_frames / 25.0  # 25fps target

    with tempfile.TemporaryDirectory(prefix="clip_frames_") as tmp:
        tmp_path = Path(tmp)
        frame_pattern = tmp_path / "f_%04d.jpg"

        # FFmpeg:
        #   -ss seek
        #   -t duration
        #   -r 25 force output fps
        #   -vf scale to short-edge=resolution, then center crop
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{start_s:.3f}",
            "-i", str(source_video),
            "-t", f"{duration_s:.3f}",
            "-r", "25",
            "-vf", f"scale=-2:{resolution},crop={resolution}:{resolution}",
            "-q:v", "3",
            str(frame_pattern),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg failed for clip at {start_ms}ms: {result.stderr}"
            )

        frame_files = sorted(tmp_path.glob("f_*.jpg"))
        if len(frame_files) < n_frames:
            raise RuntimeError(
                f"Expected {n_frames} frames but FFmpeg produced {len(frame_files)}"
            )

        frames = []
        for i in range(n_frames):
            frame = cv2.imread(str(frame_files[i]))
            if frame is None:
                raise RuntimeError(f"Failed to read extracted frame {i}")
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(frame)

        video = np.stack(frames)  # (T, H, W, C)
        video = torch.from_numpy(video).permute(3, 0, 1, 2).float()  # (C, T, H, W)
        video = video / 127.5 - 1.0
        return video.unsqueeze(0)  # (1, C, T, H, W)


# ============================================================
#  Audio extraction (unchanged, already correct)
# ============================================================

def loudness_norm(audio, sr, target=-23.0):
    import pyloudnorm as pyln
    meter = pyln.Meter(sr)
    loudness = meter.integrated_loudness(audio)
    if loudness == float("-inf"):
        return audio
    return pyln.normalize.loudness(audio, loudness, target)


def extract_audio_features(vocals_path: Path, start_ms: int,
                           wav2vec_model, feature_extractor,
                           video_length: int, device) -> torch.Tensor:
    """Extract Wav2Vec features for a clip."""
    start_s = start_ms / 1000.0
    duration_s = video_length / 25.0  # match video duration
    audio, sr = librosa.load(str(vocals_path), sr=16000, offset=start_s,
                             duration=duration_s)
    audio = loudness_norm(audio, sr)
    audio = audio[: int(video_length / 25 * sr)]
    audio_feature = np.squeeze(
        feature_extractor(audio, sampling_rate=16000).input_values
    )
    audio_feature = torch.from_numpy(audio_feature).float().unsqueeze(0).to(device)
    with torch.no_grad():
        embeddings = wav2vec_model(audio_feature, seq_len=video_length,
                                   output_hidden_states=True)
        audio_emb = torch.stack(embeddings.hidden_states[1:], dim=1).squeeze(0)
        audio_emb = rearrange(audio_emb, "b s d -> s b d")

    indices = (torch.arange(2 * 2 + 1) - 2) * 1
    center_indices = (torch.arange(0, video_length, 1).unsqueeze(1)
                      + indices.unsqueeze(0))
    center_indices = torch.clamp(center_indices, min=0, max=audio_emb.shape[0] - 1)
    return audio_emb[center_indices].unsqueeze(0).cpu()  # (1, F, 5, 12, 768)


# ============================================================
#  Mouth mask computation (FIXED: uses real per-frame mouth bboxes)
# ============================================================

def compute_latent_mouth_mask(label: dict, latent_t: int, latent_s: int,
                              resolution: int) -> torch.Tensor:
    """Build weight mask in latent space from per-frame mouth bboxes.

    Mouth bboxes come from YOLOv5-Face landmarks (precomputed), expressed
    in source pixel coordinates (2560x1440). We map them through the same
    scale+crop transform that extract_clip_frames_ffmpeg uses:
        scale = resolution / src_h   (480/1440 = 0.333)
        new_w = src_w * scale        (853)
        new_h = resolution           (480)
        x_off = (new_w - resolution) / 2  (186.5 — horizontal center crop)
        y_off = 0

    Then map to latent space by dividing by 8 (VAE spatial compression).
    """
    mask = torch.ones(1, 1, latent_t, latent_s, latent_s, dtype=torch.float32) * BG_WEIGHT

    src_w, src_h = 2560, 1440
    scale = resolution / src_h  # 0.333
    new_w = src_w * scale        # 853
    x_off = (new_w - resolution) / 2  # 186.5
    y_off = 0                    # top-aligned (new_h == resolution)

    face_bboxes = label.get("face_bbox_per_frame", [])
    mouth_bboxes = label.get("mouth_bbox_per_frame", [])
    n_frames = len(face_bboxes)
    if n_frames == 0:
        return mask

    def src_to_latent(bb_src):
        x1 = bb_src[0] * scale - x_off
        y1 = bb_src[1] * scale - y_off
        x2 = bb_src[2] * scale - x_off
        y2 = bb_src[3] * scale - y_off
        # Clamp to resolution window
        x1 = max(0.0, min(resolution, x1))
        x2 = max(0.0, min(resolution, x2))
        y1 = max(0.0, min(resolution, y1))
        y2 = max(0.0, min(resolution, y2))
        # To latent (divide by 8)
        lx1 = int(x1 / 8)
        lx2 = max(lx1 + 1, int(math.ceil(x2 / 8)))
        ly1 = int(y1 / 8)
        ly2 = max(ly1 + 1, int(math.ceil(y2 / 8)))
        return (max(0, lx1), max(0, ly1),
                min(latent_s, lx2), min(latent_s, ly2))

    # WAN VAE is causal: latent[0] comes from pixel[0] alone, then
    # latent[k] for k>=1 comes from pixel frames [4k-3 : 4k+1]. We sample
    # the middle of each latent time step's pixel range.
    for t in range(latent_t):
        if t == 0:
            pix_idx = 0
        else:
            # pixel range [4t-3, 4t+1], take middle = 4t-1
            pix_idx = min(n_frames - 1, max(0, 4 * t - 1))

        fx1, fy1, fx2, fy2 = src_to_latent(face_bboxes[pix_idx])
        mx1, my1, mx2, my2 = src_to_latent(mouth_bboxes[pix_idx])

        if fx2 > fx1 and fy2 > fy1:
            mask[0, 0, t, fy1:fy2, fx1:fx2] = FACE_WEIGHT
        if mx2 > mx1 and my2 > my1:
            mask[0, 0, t, my1:my2, mx1:mx2] = MOUTH_WEIGHT

    return mask
