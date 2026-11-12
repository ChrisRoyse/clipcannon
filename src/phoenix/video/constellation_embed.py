"""Frozen SigLIP visual embedding for the constellation guard.

Split out of ``phoenix.video.constellation_guard`` (pure move): the SigLIP
constants and the encoder-load / frame-embedding / cosine methods that
``ConstellationGuard`` inherits from ``_VisualEmbeddingMixin``.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


SIGLIP_MODEL_ID = "google/siglip-so400m-patch14-384"
SIGLIP_VRAM_MB = 2048
FRAME_RESIZE = 384


class _VisualEmbeddingMixin:
    """SigLIP loading and frame embedding for ``ConstellationGuard``."""

    def load_visual_encoder(self) -> None:
        """Load frozen SigLIP for visual re-embedding of generated frames.

        Must use HF_HUB_OFFLINE=1. Raises RuntimeError if model not cached.
        Uses gpu_guard for VRAM management.
        """
        if self._model is not None:
            logger.debug("SigLIP already loaded, skipping")
            return

        import torch
        from transformers import AutoModel, AutoProcessor

        from phoenix.video.gpu_guard import check_vram, gpu_cleanup, log_vram

        check_vram(SIGLIP_VRAM_MB, "ConstellationGuard.load_visual_encoder")
        log_vram("before_siglip_load")

        logger.info("Loading frozen SigLIP: %s", SIGLIP_MODEL_ID)

        try:
            self._processor = AutoProcessor.from_pretrained(SIGLIP_MODEL_ID)
        except OSError as exc:
            gpu_cleanup()
            raise RuntimeError(
                f"SigLIP processor not found in cache. "
                f"HF_HUB_OFFLINE=1 requires pre-cached models. "
                f"Model: {SIGLIP_MODEL_ID}. Error: {exc}"
            ) from exc

        device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            if device == "cuda":
                self._model = AutoModel.from_pretrained(
                    SIGLIP_MODEL_ID,
                    torch_dtype=torch.float16,
                ).to(device)
            else:
                self._model = AutoModel.from_pretrained(SIGLIP_MODEL_ID)
        except OSError as exc:
            gpu_cleanup()
            raise RuntimeError(
                f"SigLIP model not found in cache. "
                f"HF_HUB_OFFLINE=1 requires pre-cached models. "
                f"Model: {SIGLIP_MODEL_ID}. Error: {exc}"
            ) from exc

        self._model.eval()
        self._device = device

        log_vram("after_siglip_load")
        logger.info("SigLIP loaded on %s (frozen, eval mode)", device)

    def _embed_frame(self, frame_rgb: np.ndarray) -> np.ndarray:
        """Embed a single RGB frame through frozen SigLIP.

        Args:
            frame_rgb: HWC uint8 RGB numpy array.

        Returns:
            L2-normalized 1152-d embedding as float32 numpy array.
        """
        if self._model is None or self._processor is None:
            raise RuntimeError(
                "Visual encoder not loaded. Call load_visual_encoder() first."
            )

        import torch
        from PIL import Image

        # Convert numpy array to PIL Image
        if frame_rgb.dtype != np.uint8:
            frame_rgb = np.clip(frame_rgb, 0, 255).astype(np.uint8)
        pil_img = Image.fromarray(frame_rgb)

        # Process through SigLIP
        inputs = self._processor(images=[pil_img], return_tensors="pt", padding=True)
        device = self._device or "cpu"
        inputs = {
            k: v.to(device, dtype=torch.float16)
            if v.is_floating_point()
            else v.to(device)
            for k, v in inputs.items()
        }

        with torch.no_grad():
            outputs = self._model.get_image_features(**inputs)

        # L2 normalize
        emb = outputs / outputs.norm(dim=-1, keepdim=True)
        emb_np = emb.cpu().numpy().astype(np.float32).flatten()

        return emb_np

    def _embed_batch(self, frames: list[np.ndarray]) -> list[np.ndarray]:
        """Embed a batch of RGB frames through frozen SigLIP.

        Args:
            frames: List of HWC uint8 RGB numpy arrays.

        Returns:
            List of L2-normalized 1152-d embeddings.
        """
        if self._model is None or self._processor is None:
            raise RuntimeError(
                "Visual encoder not loaded. Call load_visual_encoder() first."
            )

        import torch
        from PIL import Image

        pil_images = []
        for frame in frames:
            if frame.dtype != np.uint8:
                frame = np.clip(frame, 0, 255).astype(np.uint8)
            pil_images.append(Image.fromarray(frame))

        inputs = self._processor(
            images=pil_images, return_tensors="pt", padding=True
        )
        device = self._device or "cpu"
        inputs = {
            k: v.to(device, dtype=torch.float16)
            if v.is_floating_point()
            else v.to(device)
            for k, v in inputs.items()
        }

        with torch.no_grad():
            outputs = self._model.get_image_features(**inputs)

        emb = outputs / outputs.norm(dim=-1, keepdim=True)
        emb_np = emb.cpu().numpy().astype(np.float32)

        return [emb_np[i] for i in range(emb_np.shape[0])]

    def _cosine_similarity(self, vec: np.ndarray, centroid: np.ndarray) -> float:
        """Cosine similarity between a vector and a centroid.

        Both are assumed to already be L2-normalized.

        Args:
            vec: L2-normalized embedding vector.
            centroid: L2-normalized centroid vector.

        Returns:
            Cosine similarity in [-1, 1].
        """
        return float(np.dot(vec, centroid))
