"""LatentSync 1.6 lip-sync pipeline for ClipCannon.

Maps audio onto a driver video to produce a talking-head video
where the speaker's lips match the audio content. Uses ByteDance's
LatentSync diffusion-based approach with Whisper audio conditioning.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import torch

logger = logging.getLogger(__name__)

_LATENTSYNC_DIR = Path.home() / ".clipcannon" / "models" / "latentsync"
_CHECKPOINT_PATH = _LATENTSYNC_DIR / "checkpoints" / "latentsync_unet.pt"
_CONFIG_PATH = _LATENTSYNC_DIR / "configs" / "unet" / "stage2_512.yaml"
_WHISPER_TINY = _LATENTSYNC_DIR / "checkpoints" / "whisper" / "tiny.pt"
_MASK_PATH = _LATENTSYNC_DIR / "latentsync" / "utils" / "mask.png"


@dataclass
class LipSyncResult:
    """Result of a lip-sync operation.

    Attributes:
        video_path: Path to the output video with synced lips.
        duration_ms: Duration of the output video in milliseconds.
        resolution: Output resolution as "WxH" string.
        inference_steps: Number of diffusion steps used.
        elapsed_s: Total processing time in seconds.
    """

    video_path: Path
    duration_ms: int
    resolution: str
    inference_steps: int
    elapsed_s: float


def _validate_prerequisites() -> None:
    """Verify LatentSync repo and checkpoints exist.

    Raises:
        FileNotFoundError: If any required file is missing.
    """
    if not _LATENTSYNC_DIR.exists():
        raise FileNotFoundError(
            f"LatentSync not found at {_LATENTSYNC_DIR}. "
            "Clone with: git clone https://github.com/bytedance/LatentSync.git "
            f"{_LATENTSYNC_DIR}"
        )
    if not _CHECKPOINT_PATH.exists():
        raise FileNotFoundError(
            f"LatentSync UNet checkpoint not found at {_CHECKPOINT_PATH}. "
            "Download from: https://huggingface.co/ByteDance/LatentSync-1.6"
        )
    if not _WHISPER_TINY.exists():
        raise FileNotFoundError(
            f"Whisper tiny checkpoint not found at {_WHISPER_TINY}. "
            "Download from: https://huggingface.co/ByteDance/LatentSync-1.6"
        )


def _add_latentsync_to_path() -> None:
    """Add LatentSync repo to Python path for imports."""
    repo_str = str(_LATENTSYNC_DIR)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)


class LipSyncEngine:
    """LatentSync 1.6 lip-sync engine.

    Loads the diffusion pipeline once and reuses across calls.
    Requires ~18GB VRAM for inference at 512x512.
    """

    def __init__(self) -> None:
        """Initialize the engine. Pipeline loads on first use."""
        self._pipeline: object | None = None

    def _ensure_pipeline(self) -> object:
        """Lazy-load the LatentSync pipeline."""
        if self._pipeline is not None:
            return self._pipeline

        _validate_prerequisites()
        _add_latentsync_to_path()

        from diffusers import AutoencoderKL, DDIMScheduler
        from omegaconf import OmegaConf

        from latentsync.models.unet import UNet3DConditionModel
        from latentsync.pipelines.lipsync_pipeline import LipsyncPipeline
        from latentsync.whisper.audio2feature import Audio2Feature

        logger.info("Loading LatentSync 1.6 pipeline...")
        start = time.monotonic()

        config = OmegaConf.load(str(_CONFIG_PATH))

        is_fp16 = torch.cuda.is_available() and torch.cuda.get_device_capability()[0] > 7
        dtype = torch.float16 if is_fp16 else torch.float32

        scheduler = DDIMScheduler.from_pretrained(str(_LATENTSYNC_DIR / "configs"))

        audio_encoder = Audio2Feature(
            model_path=str(_WHISPER_TINY),
            device="cuda",
            num_frames=config.data.num_frames,
            audio_feat_length=config.data.get("audio_feat_length", 2),
        )

        vae = AutoencoderKL.from_pretrained(
            "stabilityai/sd-vae-ft-mse", torch_dtype=dtype,
        )
        vae.config.scaling_factor = 0.18215
        vae.config.shift_factor = 0

        unet = UNet3DConditionModel.from_config(config.model)
        unet.load_state_dict(
            torch.load(str(_CHECKPOINT_PATH), map_location="cpu", weights_only=False),
            strict=False,
        )

        pipeline = LipsyncPipeline(
            vae=vae,
            audio_encoder=audio_encoder,
            unet=unet,
            scheduler=scheduler,
        ).to("cuda", dtype=dtype)

        elapsed = time.monotonic() - start
        logger.info("LatentSync loaded in %.1fs", elapsed)

        self._pipeline = pipeline
        return pipeline

    def generate(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
        inference_steps: int = 20,
        guidance_scale: float = 1.5,
        seed: int | None = None,
    ) -> LipSyncResult:
        """Generate lip-synced video from driver video + audio.

        Args:
            video_path: Path to driver video (face visible, any length).
            audio_path: Path to audio WAV (the speech to lip-sync).
            output_path: Path for the output video.
            inference_steps: Diffusion denoising steps (20 = good quality).
            guidance_scale: Classifier-free guidance scale.
            seed: Random seed for reproducibility.

        Returns:
            LipSyncResult with output video details.

        Raises:
            FileNotFoundError: If video_path or audio_path doesn't exist.
            RuntimeError: If lip-sync generation fails.
        """
        if not video_path.exists():
            raise FileNotFoundError(f"Driver video not found: {video_path}")
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        pipeline = self._ensure_pipeline()

        generator = None
        if seed is not None:
            generator = torch.Generator(device="cuda").manual_seed(seed)

        logger.info(
            "Generating lip-sync: video=%s, audio=%s, steps=%d",
            video_path.name, audio_path.name, inference_steps,
        )

        start = time.monotonic()

        # LatentSync expects a temp dir for intermediate frames
        temp_dir = output_path.parent / f"_lipsync_temp_{output_path.stem}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            pipeline(  # type: ignore[operator]
                video_path=str(video_path),
                audio_path=str(audio_path),
                video_out_path=str(output_path),
                num_inference_steps=inference_steps,
                guidance_scale=guidance_scale,
                generator=generator,
                temp_dir=str(temp_dir),
                mask_image_path=str(_MASK_PATH),
            )
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

        elapsed = time.monotonic() - start

        if not output_path.exists():
            raise RuntimeError(
                f"LatentSync completed but output not found at {output_path}"
            )

        # Probe output for metadata
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", str(output_path)],
            capture_output=True, text=True,
        )
        duration_ms = 0
        resolution = "512x512"
        if probe.returncode == 0:
            data = json.loads(probe.stdout)
            for s in data.get("streams", []):
                if s.get("codec_type") == "video":
                    duration_ms = int(float(s.get("duration", 0)) * 1000)
                    resolution = f"{s.get('width', 512)}x{s.get('height', 512)}"
                    break

        logger.info(
            "Lip-sync complete: %s, %dms, %s, %.1fs",
            output_path.name, duration_ms, resolution, elapsed,
        )

        return LipSyncResult(
            video_path=output_path,
            duration_ms=duration_ms,
            resolution=resolution,
            inference_steps=inference_steps,
            elapsed_s=round(elapsed, 2),
        )


# Module-level singleton so the VRAM-heavy pipeline survives across calls.
_engine: LipSyncEngine | None = None


def get_engine() -> LipSyncEngine:
    """Return a shared LipSyncEngine singleton.

    Avoids re-instantiating the engine (and potentially reloading
    the ~18GB pipeline) on every tool call.
    """
    global _engine  # noqa: PLW0603
    if _engine is None:
        _engine = LipSyncEngine()
    return _engine
