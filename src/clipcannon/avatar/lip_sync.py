"""LatentSync 1.6 lip-sync pipeline for ClipCannon.

Maps audio onto a driver video to produce a talking-head video
where the speaker's lips match the audio content. Uses ByteDance's
LatentSync diffusion-based approach with Whisper audio conditioning.

The pipeline preserves the original video resolution -- faces are
cropped and aligned to 512x512 internally, processed through the
diffusion UNet, then pasted back into the original frames with
soft mask blending.

Requirements:
    - LatentSync repo cloned to ~/.clipcannon/models/latentsync/
    - Checkpoints: latentsync_unet.pt + whisper/tiny.pt
    - ~18GB VRAM for inference (fp16 on compute capability > 7)
    - insightface, kornia, einops, decord, omegaconf, diffusers
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

logger = logging.getLogger(__name__)

_LATENTSYNC_DIR = Path.home() / ".clipcannon" / "models" / "latentsync"
_CHECKPOINT_PATH = _LATENTSYNC_DIR / "checkpoints" / "latentsync_unet.pt"
_CONFIG_PATH = _LATENTSYNC_DIR / "configs" / "unet" / "stage2_512.yaml"
_SCHEDULER_DIR = _LATENTSYNC_DIR / "configs"
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
            "Download with: huggingface-cli download ByteDance/LatentSync-1.6 "
            f"latentsync_unet.pt --local-dir {_LATENTSYNC_DIR / 'checkpoints'}"
        )
    if not _WHISPER_TINY.exists():
        raise FileNotFoundError(
            f"Whisper tiny checkpoint not found at {_WHISPER_TINY}. "
            "Download with: huggingface-cli download ByteDance/LatentSync-1.6 "
            f"whisper/tiny.pt --local-dir {_LATENTSYNC_DIR / 'checkpoints'}"
        )
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"LatentSync config not found at {_CONFIG_PATH}. "
            "Ensure the LatentSync repo is fully cloned."
        )
    if not _MASK_PATH.exists():
        raise FileNotFoundError(
            f"LatentSync mask image not found at {_MASK_PATH}. "
            "Ensure the LatentSync repo is fully cloned."
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

    The pipeline preserves original video resolution by:
    1. Detecting faces with InsightFace (106-point landmarks)
    2. Affine-transforming face crops to 512x512
    3. Running diffusion UNet on face crops
    4. Restoring processed faces back into original frames
    """

    def __init__(self, enable_deepcache: bool = True) -> None:
        """Initialize the engine. Pipeline loads on first use.

        Args:
            enable_deepcache: Enable DeepCache for ~1.5-2x speedup
                with minimal quality degradation.
        """
        self._pipeline: object | None = None
        self._deepcache_helper: object | None = None
        self._enable_deepcache = enable_deepcache
        self._config: object | None = None

    def _ensure_pipeline(self) -> object:
        """Lazy-load the LatentSync pipeline.

        Follows the official inference.py loading sequence exactly:
        1. Load config from stage2_512.yaml
        2. Create DDIMScheduler from configs/scheduler_config.json
        3. Create Audio2Feature with Whisper tiny
        4. Load VAE from stabilityai/sd-vae-ft-mse
        5. Load UNet via from_pretrained (handles state_dict extraction)
        6. Assemble LipsyncPipeline and move to GPU
        7. Optionally enable DeepCache
        """
        if self._pipeline is not None:
            return self._pipeline

        import torch

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
        self._config = config

        is_fp16 = (
            torch.cuda.is_available()
            and torch.cuda.get_device_capability()[0] > 7
        )
        dtype = torch.float16 if is_fp16 else torch.float32

        # Scheduler from configs/scheduler_config.json
        scheduler = DDIMScheduler.from_pretrained(str(_SCHEDULER_DIR))

        # Whisper audio encoder -- cross_attention_dim=384 -> tiny.pt
        audio_encoder = Audio2Feature(
            model_path=str(_WHISPER_TINY),
            device="cuda",
            num_frames=config.data.num_frames,
            audio_feat_length=config.data.audio_feat_length,
        )

        # SD VAE
        vae = AutoencoderKL.from_pretrained(
            "stabilityai/sd-vae-ft-mse", torch_dtype=dtype,
        )
        vae.config.scaling_factor = 0.18215
        vae.config.shift_factor = 0

        # UNet -- use from_pretrained which handles state_dict extraction
        unet, _ = UNet3DConditionModel.from_pretrained(
            OmegaConf.to_container(config.model),
            str(_CHECKPOINT_PATH),
            device="cpu",
        )
        unet = unet.to(dtype=dtype)

        pipeline = LipsyncPipeline(
            vae=vae,
            audio_encoder=audio_encoder,
            unet=unet,
            scheduler=scheduler,
        ).to("cuda")

        # DeepCache: caches intermediate UNet features every 3 steps
        if self._enable_deepcache:
            try:
                from DeepCache import DeepCacheSDHelper

                helper = DeepCacheSDHelper(pipe=pipeline)
                helper.set_params(cache_interval=3, cache_branch_id=0)
                helper.enable()
                self._deepcache_helper = helper
                logger.info("DeepCache enabled (cache_interval=3)")
            except ImportError:
                logger.info(
                    "DeepCache not installed -- running without cache. "
                    "Install with: pip install DeepCache"
                )

        elapsed = time.monotonic() - start
        logger.info(
            "LatentSync loaded in %.1fs (dtype=%s, deepcache=%s)",
            elapsed, dtype, self._deepcache_helper is not None,
        )

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

        The driver video is automatically looped (ping-pong) if the
        audio is longer than the video. Face detection, alignment,
        and restoration are handled internally by the pipeline.

        Output preserves the original video resolution and FPS (25).

        Args:
            video_path: Path to driver video (face visible, any length).
            audio_path: Path to audio file (any format FFmpeg can decode).
            output_path: Path for the output video.
            inference_steps: Diffusion denoising steps (20 = good, 30-40 = better).
            guidance_scale: Classifier-free guidance (1.5 = balanced, 2.0 = stronger sync).
            seed: Random seed for reproducibility.

        Returns:
            LipSyncResult with output video details.

        Raises:
            FileNotFoundError: If video_path or audio_path doesn't exist.
            RuntimeError: If lip-sync generation fails (e.g., face not detected).
        """
        import torch

        if not video_path.exists():
            raise FileNotFoundError(f"Driver video not found: {video_path}")
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        pipeline = self._ensure_pipeline()

        if seed is not None:
            from accelerate.utils import set_seed
            set_seed(seed)
        else:
            torch.seed()

        # Determine dtype from GPU capability
        is_fp16 = (
            torch.cuda.is_available()
            and torch.cuda.get_device_capability()[0] > 7
        )
        weight_dtype = torch.float16 if is_fp16 else torch.float32

        config = self._config

        logger.info(
            "Generating lip-sync: video=%s, audio=%s, steps=%d, guidance=%.1f",
            video_path.name, audio_path.name, inference_steps, guidance_scale,
        )

        start = time.monotonic()

        # LatentSync uses a temp dir for intermediate frames/audio
        temp_dir = output_path.parent / f"_lipsync_temp_{output_path.stem}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            pipeline(  # type: ignore[operator]
                video_path=str(video_path),
                audio_path=str(audio_path),
                video_out_path=str(output_path),
                num_frames=config.data.num_frames,
                num_inference_steps=inference_steps,
                guidance_scale=guidance_scale,
                weight_dtype=weight_dtype,
                width=config.data.resolution,
                height=config.data.resolution,
                mask_image_path=str(_MASK_PATH),
                temp_dir=str(temp_dir),
            )
        except RuntimeError as exc:
            if "Face not detected" in str(exc):
                raise RuntimeError(
                    f"Face not detected in driver video '{video_path.name}'. "
                    "Ensure the video contains a clearly visible, "
                    "well-lit face that is not occluded or at extreme angles."
                ) from exc
            raise
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
        resolution = "unknown"
        if probe.returncode == 0:
            data = json.loads(probe.stdout)
            for s in data.get("streams", []):
                if s.get("codec_type") == "video":
                    duration_ms = int(float(s.get("duration", 0)) * 1000)
                    resolution = f"{s.get('width', 0)}x{s.get('height', 0)}"
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

    def unload(self) -> None:
        """Release the pipeline and free GPU memory."""
        import gc

        if self._deepcache_helper is not None:
            try:
                self._deepcache_helper.disable()
            except Exception:
                pass
            self._deepcache_helper = None

        self._pipeline = None
        self._config = None
        gc.collect()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass


# Module-level singleton so the VRAM-heavy pipeline survives across calls.
_engine: LipSyncEngine | None = None


def get_engine(enable_deepcache: bool = True) -> LipSyncEngine:
    """Return a shared LipSyncEngine singleton.

    Avoids re-instantiating the engine (and potentially reloading
    the ~18GB pipeline) on every tool call.
    """
    global _engine  # noqa: PLW0603
    if _engine is None:
        _engine = LipSyncEngine(enable_deepcache=enable_deepcache)
    return _engine
