"""Training data extraction pipeline for the clone model.

Extracts ground truth blendshapes and aligns all 9 embeddings
to frame-level timestamps from the Santa source video + analysis DB.

Pipeline:
  1. Extract frames from source video
  2. Run insightface on each frame → 106 landmarks → blendshapes
  3. Load pre-computed embeddings from analysis.db
  4. Align all embeddings to frame timestamps (interpolation)
  5. Package into training-ready tensors
"""
from __future__ import annotations

import logging
import sqlite3
import subprocess
from pathlib import Path

import cv2
import numpy as np
import torch

logger = logging.getLogger(__name__)


def extract_ground_truth_blendshapes(
    video_path: str,
    fps: int = 5,
    max_frames: int = 5000,
) -> list[dict]:
    """Extract ground truth face blendshapes from every frame.

    Uses insightface 106-point landmarks to compute blendshape-like
    parameters for each frame. These become the training targets.

    Args:
        video_path: Path to source video.
        fps: Frame extraction rate (lower = faster, less data).
        max_frames: Maximum frames to extract.

    Returns:
        List of dicts with: timestamp_ms, blendshapes (52 floats),
        landmarks_106 (106x2), face_bbox (4 ints).
    """
    from insightface.app import FaceAnalysis

    logger.info("Extracting ground truth blendshapes at %dfps from %s", fps, video_path)

    app = FaceAnalysis(providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))

    cap = cv2.VideoCapture(video_path)
    src_fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    skip = max(1, int(src_fps / fps))

    samples = []
    frame_idx = 0

    while cap.isOpened() and len(samples) < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % skip != 0:
            frame_idx += 1
            continue

        timestamp_ms = int(frame_idx / src_fps * 1000)

        # Resize for faster detection
        h, w = frame.shape[:2]
        if w > 1280:
            scale = 1280 / w
            frame = cv2.resize(frame, (1280, int(h * scale)))

        faces = app.get(frame)
        if faces:
            face = faces[0]
            if hasattr(face, "landmark_2d_106") and face.landmark_2d_106 is not None:
                lm = face.landmark_2d_106
                blendshapes = _landmarks_to_blendshapes(lm, frame.shape[:2])
                samples.append({
                    "timestamp_ms": timestamp_ms,
                    "blendshapes": blendshapes,
                    "landmarks_106": lm.tolist(),
                    "face_bbox": face.bbox.astype(int).tolist(),
                })

        frame_idx += 1
        if len(samples) % 100 == 0 and len(samples) > 0:
            logger.info("  Extracted %d/%d frames", len(samples), max_frames)

    cap.release()
    logger.info("Extracted %d ground truth frames", len(samples))
    return samples


def _landmarks_to_blendshapes(lm: np.ndarray, frame_shape: tuple) -> list[float]:
    """Convert 106 face landmarks to 52 ARKit-style blendshape values.

    This is an approximation — maps geometric relationships between
    landmarks to blendshape activation values [0, 1].
    """
    h, w = frame_shape[:2]

    # Normalize landmarks to [0, 1]
    lm_norm = lm.copy()
    lm_norm[:, 0] /= w
    lm_norm[:, 1] /= h

    # Mouth landmarks (52-71 in 106 model)
    mouth = lm_norm[52:72]
    mouth_h = np.max(mouth[:, 1]) - np.min(mouth[:, 1])
    mouth_w = np.max(mouth[:, 0]) - np.min(mouth[:, 0])

    # Upper lip (52-59), lower lip (60-67)
    upper_lip = lm_norm[52:60]
    lower_lip = lm_norm[60:68]
    lip_sep = np.mean(lower_lip[:, 1]) - np.mean(upper_lip[:, 1])

    # Brow landmarks (33-37 = left brow, 38-42 = right brow in 106)
    left_brow = lm_norm[33:38]
    right_brow = lm_norm[38:43]
    left_eye = lm_norm[43:48]
    right_eye = lm_norm[48:53]

    brow_left_h = np.mean(left_eye[:, 1]) - np.mean(left_brow[:, 1])
    brow_right_h = np.mean(right_eye[:, 1]) - np.mean(right_brow[:, 1])

    # Eye openness
    left_eye_h = np.max(left_eye[:, 1]) - np.min(left_eye[:, 1])
    right_eye_h = np.max(right_eye[:, 1]) - np.min(right_eye[:, 1])

    # Mouth corners (smile detection)
    mouth_left = lm_norm[52]
    mouth_right = lm_norm[58]
    mouth_center_y = (lm_norm[55][1] + lm_norm[63][1]) / 2
    smile_left = mouth_center_y - mouth_left[1]
    smile_right = mouth_center_y - mouth_right[1]

    # Head pose from face geometry
    nose = lm_norm[86]  # Nose tip
    chin = lm_norm[0]   # Chin
    face_center_x = (lm_norm[33][0] + lm_norm[42][0]) / 2
    head_yaw = (nose[0] - face_center_x) * 5  # rough degrees

    # Build 52 ARKit blendshapes (simplified — many set to 0)
    bs = [0.0] * 52

    # Jaw and mouth (indices 0-22)
    bs[0] = float(np.clip(lip_sep * 8, 0, 1))    # jawOpen
    bs[1] = float(np.clip(1 - lip_sep * 8, 0, 1))  # mouthClose
    bs[2] = float(np.clip(mouth_w * 3, 0, 1))     # mouthFunnel
    bs[3] = float(np.clip(smile_left * 10, 0, 1))   # mouthSmileLeft
    bs[4] = float(np.clip(smile_right * 10, 0, 1))  # mouthSmileRight

    # Brows (indices 23-27)
    bs[23] = float(np.clip(brow_left_h * 8, 0, 1))   # browInnerUp
    bs[24] = float(np.clip(1 - brow_left_h * 8, 0, 1))  # browDownLeft
    bs[25] = float(np.clip(1 - brow_right_h * 8, 0, 1))  # browDownRight

    # Eyes (indices 28-41)
    bs[28] = float(np.clip(1 - left_eye_h * 15, 0, 1))   # eyeBlinkLeft
    bs[29] = float(np.clip(1 - right_eye_h * 15, 0, 1))  # eyeBlinkRight
    bs[30] = float(np.clip(left_eye_h * 15 - 0.5, 0, 1))  # eyeWideLeft
    bs[31] = float(np.clip(right_eye_h * 15 - 0.5, 0, 1))  # eyeWideRight

    # Head (indices 46-51)
    bs[46] = float(np.clip(head_yaw / 30 + 0.5, 0, 1))  # headYaw (normalized)

    return bs


def load_embeddings_from_db(
    db_path: str,
    project_id: str = "proj_2ea7221d",
) -> dict[str, list[dict]]:
    """Load pre-computed embeddings from analysis.db.

    Returns:
        Dict with keys: transcripts, emotions, prosody.
        Each value is a list of dicts with timestamp + data.
    """
    db = sqlite3.connect(db_path)
    c = db.cursor()
    result = {}

    # Transcripts with timestamps
    c.execute("SELECT start_ms, end_ms, text FROM transcript_segments ORDER BY start_ms")
    result["transcripts"] = [
        {"start_ms": r[0], "end_ms": r[1], "text": r[2]}
        for r in c.fetchall()
    ]

    # Emotion curve
    c.execute("SELECT * FROM emotion_curve ORDER BY rowid")
    cols = [d[0] for d in c.description]
    result["emotions"] = [dict(zip(cols, r)) for r in c.fetchall()]

    # Prosody segments
    c.execute("SELECT * FROM prosody_segments ORDER BY rowid")
    cols = [d[0] for d in c.description]
    result["prosody"] = [dict(zip(cols, r)) for r in c.fetchall()]

    db.close()
    logger.info("Loaded: %d transcripts, %d emotions, %d prosody",
                len(result["transcripts"]), len(result["emotions"]),
                len(result["prosody"]))
    return result


def build_training_dataset(
    blendshape_samples: list[dict],
    embeddings: dict[str, list[dict]],
) -> dict[str, torch.Tensor]:
    """Align blendshapes with embeddings and build tensors.

    Performs temporal alignment: for each blendshape frame,
    finds the nearest embedding from each modality.

    Returns:
        Dict of training tensors ready for DataLoader.
    """
    n = len(blendshape_samples)
    logger.info("Building dataset: %d frames", n)

    # Target blendshapes
    gt_blendshapes = torch.tensor(
        [s["blendshapes"] for s in blendshape_samples],
        dtype=torch.float32,
    )

    # Timestamps
    timestamps = [s["timestamp_ms"] for s in blendshape_samples]

    # Prosody features (12 scalars) — nearest match
    prosody_data = torch.zeros(n, 12, dtype=torch.float32)
    if embeddings.get("prosody"):
        for i, ts in enumerate(timestamps):
            nearest = _find_nearest(embeddings["prosody"], ts, "start_ms")
            if nearest:
                prosody_data[i] = _extract_prosody_features(nearest)

    # Emotion data — nearest match (placeholder — would need raw embeddings)
    # For now use emotion curve scalars as proxy
    emotion_scalars = torch.zeros(n, 8, dtype=torch.float32)
    if embeddings.get("emotions"):
        for i, ts in enumerate(timestamps):
            nearest = _find_nearest(embeddings["emotions"], ts, "start_ms")
            if nearest:
                emotion_scalars[i] = _extract_emotion_features(nearest)

    return {
        "gt_blendshapes": gt_blendshapes,  # (N, 52)
        "prosody": prosody_data,            # (N, 12)
        "emotion_scalars": emotion_scalars,  # (N, 8)
        "timestamps_ms": torch.tensor(timestamps, dtype=torch.long),
        "n_samples": n,
    }


def _find_nearest(items: list[dict], target_ms: int, key: str = "start_ms") -> dict | None:
    """Find the item nearest to target_ms."""
    if not items:
        return None
    best = None
    best_dist = float("inf")
    for item in items:
        dist = abs(item.get(key, 0) - target_ms)
        if dist < best_dist:
            best_dist = dist
            best = item
    return best


def _extract_prosody_features(seg: dict) -> torch.Tensor:
    """Extract 12 prosody scalar features from a prosody segment."""
    return torch.tensor([
        seg.get("f0_mean", 0) / 300,       # Normalized F0
        seg.get("f0_range", 0) / 500,      # F0 range
        1.0 if seg.get("energy_level") == "high" else (0.5 if seg.get("energy_level") == "medium" else 0.0),
        seg.get("speaking_rate_wpm", 0) / 300,
        seg.get("prosody_score", 0) / 100,
        1.0 if seg.get("has_emphasis") else 0.0,
        1.0 if seg.get("pitch_contour") == "rising" else 0.0,
        1.0 if seg.get("pitch_contour") == "falling" else 0.0,
        1.0 if seg.get("pitch_contour") == "varied" else 0.0,
        0.0, 0.0, 0.0,  # Reserved
    ], dtype=torch.float32)


def _extract_emotion_features(emo: dict) -> torch.Tensor:
    """Extract emotion features from an emotion curve entry."""
    return torch.tensor([
        emo.get("arousal", 0.5),
        emo.get("valence", 0.5),
        emo.get("energy", 0.5),
        emo.get("dominance", 0.5),
        0.0, 0.0, 0.0, 0.0,  # Reserved
    ], dtype=torch.float32)
