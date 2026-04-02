"""Mouth-region-only CodeFormer enhancement for lip-sync output.

Applies CodeFormer face restoration but ONLY composites the mouth
region back, preserving lip sync positions while sharpening texture.

This is the "Wav2Lip-HD trick": the lip POSITIONS from LatentSync are
correct (the mouth opens/closes at the right times), but the TEXTURE
is blurry from the VAE round-trip. CodeFormer sharpens the texture
without moving the lip contours at fidelity=0.5.

Uses InsightFace 106-point landmarks to create a tight lip-contour
mask. Points 52-71 cover the outer and inner lip boundary.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

logger = logging.getLogger(__name__)

_CODEFORMER_DIR = Path.home() / ".clipcannon" / "models" / "codeformer"
_WEIGHTS_PATH = _CODEFORMER_DIR / "weights" / "CodeFormer" / "codeformer.pth"

_model: object | None = None
_face_analyzer: object | None = None


def _ensure_model(device: str = "cuda") -> tuple[object, str]:
    """Lazy-load CodeFormer model."""
    global _model

    if _model is not None:
        return _model, device

    if not _WEIGHTS_PATH.exists():
        raise FileNotFoundError(
            f"CodeFormer weights not found at {_WEIGHTS_PATH}. "
            "Download from: https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth"
        )

    cf_str = str(_CODEFORMER_DIR)
    if cf_str not in sys.path:
        sys.path.insert(0, cf_str)

    from basicsr.archs.codeformer_arch import CodeFormer

    model = CodeFormer(
        dim_embd=512, codebook_size=1024, n_head=8, n_layers=9,
        connect_list=["32", "64", "128", "256"],
    )
    ckpt = torch.load(str(_WEIGHTS_PATH), map_location="cpu", weights_only=False)
    model.load_state_dict(ckpt["params_ema"])
    model.eval()
    model = model.to(device)

    _model = model
    logger.info("CodeFormer loaded on %s", device)
    return model, device


def _ensure_face_analyzer() -> object:
    """Lazy-load InsightFace for landmark detection."""
    global _face_analyzer

    if _face_analyzer is not None:
        return _face_analyzer

    from insightface.app import FaceAnalysis

    app = FaceAnalysis(
        name="buffalo_l",
        root=str(Path.home() / ".clipcannon" / "models" / "latentsync" / "checkpoints" / "auxiliary"),
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    app.prepare(ctx_id=0, det_size=(512, 512))

    _face_analyzer = app
    logger.info("InsightFace face analyzer loaded")
    return app


def _get_lip_mask(
    landmarks_106: np.ndarray,
    frame_shape: tuple[int, int],
    dilate_px: int = 8,
    blur_px: int = 7,
) -> np.ndarray:
    """Create a soft mask around the lip region from 106-point landmarks.

    Points 52-71 in the InsightFace 106-landmark set cover the
    outer lip contour (52-65) and inner lip contour (66-71).

    Args:
        landmarks_106: 106x2 array of facial landmark coordinates.
        frame_shape: (height, width) of the frame.
        dilate_px: Pixels to dilate the lip mask outward.
        blur_px: Gaussian blur kernel size for soft edges.

    Returns:
        Soft mask (0-1 float) same size as frame, 1.0 at lips.
    """
    h, w = frame_shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)

    # Outer lip: points 52-65, inner lip: 66-71
    lip_points = landmarks_106[52:72].astype(np.int32)

    # Draw filled polygon for outer lip contour
    outer_lip = landmarks_106[52:66].astype(np.int32)
    cv2.fillPoly(mask, [outer_lip], 255)

    # Dilate to include surrounding skin for better blending
    if dilate_px > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_px * 2, dilate_px * 2))
        mask = cv2.dilate(mask, kernel)

    # Gaussian blur for soft edges
    if blur_px > 0:
        blur_size = blur_px * 2 + 1
        mask = cv2.GaussianBlur(mask, (blur_size, blur_size), 0)

    return mask.astype(np.float32) / 255.0


def enhance_mouth_region(
    frame_bgr: np.ndarray,
    fidelity: float = 0.5,
    device: str = "cuda",
) -> np.ndarray:
    """Enhance ONLY the mouth region using CodeFormer.

    Applies CodeFormer to the full face for quality restoration,
    but only composites the mouth region back. This preserves
    lip sync positions (from LatentSync) while sharpening the
    texture (teeth edges, lip detail).

    Args:
        frame_bgr: Full frame in BGR format.
        fidelity: CodeFormer quality-fidelity tradeoff.
            0.5 = balanced (recommended for lip-sync).
        device: CUDA device.

    Returns:
        Frame with enhanced mouth region, same size as input.
    """
    model, device = _ensure_model(device)
    app = _ensure_face_analyzer()

    # Detect face and get 106-point landmarks
    faces = app.get(frame_bgr)
    if not faces:
        return frame_bgr  # No face detected, return as-is

    face = faces[0]  # Use largest face
    if not hasattr(face, "landmark_2d_106") or face.landmark_2d_106 is None:
        return frame_bgr

    landmarks = face.landmark_2d_106

    # Create lip mask from landmarks
    lip_mask = _get_lip_mask(landmarks, frame_bgr.shape, dilate_px=8, blur_px=7)

    # Get face bounding box for CodeFormer crop
    bbox = face.bbox.astype(int)
    x1, y1, x2, y2 = bbox
    # Expand bbox for CodeFormer context
    h, w = frame_bgr.shape[:2]
    pad = int((x2 - x1) * 0.3)
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(w, x2 + pad)
    y2 = min(h, y2 + pad)

    face_crop = frame_bgr[y1:y2, x1:x2]
    crop_h, crop_w = face_crop.shape[:2]

    # Run CodeFormer on the face crop
    face_input = cv2.resize(face_crop, (512, 512), interpolation=cv2.INTER_LINEAR)
    face_t = torch.from_numpy(face_input.astype(np.float32) / 255.0)
    face_t = face_t.permute(2, 0, 1).unsqueeze(0)
    face_t = (face_t - 0.5) / 0.5
    face_t = face_t.to(device)

    with torch.no_grad():
        output = model(face_t, w=fidelity, adain=True)[0]

    enhanced_crop = (output.squeeze(0).clamp(-1, 1) + 1) / 2 * 255
    enhanced_crop = enhanced_crop.permute(1, 2, 0).cpu().numpy().astype(np.uint8)
    enhanced_crop = cv2.resize(enhanced_crop, (crop_w, crop_h), interpolation=cv2.INTER_LANCZOS4)

    # Composite: enhanced mouth + original everything else
    result = frame_bgr.copy()

    # Paste enhanced face crop into full frame
    enhanced_full = frame_bgr.copy()
    enhanced_full[y1:y2, x1:x2] = enhanced_crop

    # Use lip mask to blend: lip region from enhanced, rest from original
    lip_mask_3d = np.stack([lip_mask] * 3, axis=-1)
    result = (enhanced_full * lip_mask_3d + frame_bgr * (1 - lip_mask_3d)).astype(np.uint8)

    return result


def enhance_video_mouths(
    input_path: Path,
    output_path: Path,
    fidelity: float = 0.5,
    device: str = "cuda",
) -> Path:
    """Post-process a lip-synced video to sharpen mouth regions.

    Reads each frame, applies mouth-only CodeFormer enhancement,
    and writes the result. Preserves audio track.

    Args:
        input_path: Path to lip-synced video.
        output_path: Path for enhanced output.
        fidelity: CodeFormer fidelity (0.5 recommended).
        device: CUDA device.

    Returns:
        Path to enhanced video.
    """
    cap = cv2.VideoCapture(str(input_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Write video without audio first
    temp_video = output_path.parent / f"{output_path.stem}_noaudio.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(temp_video), fourcc, fps, (w, h))

    frame_idx = 0
    logger.info("Enhancing mouth regions: %d frames at %dx%d", total, w, h)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        enhanced = enhance_mouth_region(frame, fidelity=fidelity, device=device)
        writer.write(enhanced)

        frame_idx += 1
        if frame_idx % 100 == 0:
            logger.info("Enhanced %d/%d frames", frame_idx, total)

    cap.release()
    writer.release()

    # Mux audio from original video
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-nostdin",
        "-i", str(temp_video),
        "-i", str(input_path),
        "-map", "0:v:0",
        "-map", "1:a:0?",
        "-c:v", "libx264", "-crf", "18",
        "-c:a", "copy",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    temp_video.unlink(missing_ok=True)

    if proc.returncode != 0:
        logger.warning("Audio mux failed: %s", proc.stderr[:200])
        # Fall back to video without audio
        if not output_path.exists():
            temp_video2 = output_path.parent / f"{output_path.stem}_noaudio.mp4"
            if temp_video2.exists():
                temp_video2.rename(output_path)

    logger.info("Mouth enhancement complete: %d frames processed", frame_idx)
    return output_path
