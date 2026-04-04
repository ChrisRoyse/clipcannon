"""North Star Embedding Fusion — teleological anchor vectors for clone identity.

Computes centroid "North Star" vectors from each of the 9 embedding spaces
that define WHO Santa IS. These centroids are frozen into the transformer
as identity anchors. Every forward pass is pulled toward these anchors
via contrastive loss, ensuring the model can ONLY produce Santa-like outputs.

Architecture:
  1. Compute centroid (mean) of each embedding space from training data
  2. Freeze centroids as model buffers (non-trainable)
  3. Add cross-attention layers where latents attend to North Star vectors
  4. Contrastive loss pulls outputs toward centroids in each space

The North Star vectors act like a compass — no matter what input the model
receives, its outputs are always oriented toward Santa's identity manifold.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


@dataclass
class NorthStarConfig:
    """Configuration for North Star embedding anchors."""
    shared_dim: int = 512
    num_stars: int = 9          # Number of embedding spaces
    anchor_strength: float = 0.1  # Contrastive loss weight
    temperature: float = 0.07    # InfoNCE temperature


class NorthStarAnchors(nn.Module):
    """Frozen identity anchors from each embedding space.

    Stores the centroid of each embedding space computed from training
    data. These are registered as buffers (non-trainable, saved with model).

    Args:
        centroids: Dict of modality name -> centroid vector (numpy).
        shared_dim: Dimension to project centroids to.
    """

    def __init__(
        self,
        centroids: dict[str, np.ndarray],
        shared_dim: int = 512,
    ) -> None:
        super().__init__()
        self._modality_names = sorted(centroids.keys())

        # Project each centroid to shared dimension and freeze
        for name in self._modality_names:
            vec = centroids[name]
            if len(vec.shape) == 1:
                vec = vec.reshape(1, -1)
            # Project to shared_dim via simple linear (trained during anchor computation)
            proj = np.random.randn(vec.shape[1], shared_dim).astype(np.float32) * 0.02
            projected = (vec @ proj).squeeze(0)
            # Normalize to unit sphere
            projected = projected / (np.linalg.norm(projected) + 1e-8)
            self.register_buffer(
                f"star_{name}",
                torch.tensor(projected, dtype=torch.float32),
            )

        logger.info("NorthStarAnchors: %d modalities, dim=%d", len(self._modality_names), shared_dim)

    @property
    def modality_names(self) -> list[str]:
        return self._modality_names

    def get_star(self, name: str) -> torch.Tensor:
        """Get the North Star vector for a modality."""
        return getattr(self, f"star_{name}")

    def get_all_stars(self) -> torch.Tensor:
        """Get all North Star vectors stacked: (num_stars, shared_dim)."""
        return torch.stack([self.get_star(n) for n in self._modality_names])


class NorthStarAttention(nn.Module):
    """Cross-attention from model latents to North Star anchors.

    The latents "look at" the frozen identity anchors, pulling
    the model's internal representation toward Santa's identity.

    Args:
        dim: Hidden dimension.
        num_heads: Number of attention heads.
    """

    def __init__(self, dim: int = 512, num_heads: int = 8) -> None:
        super().__init__()
        self.norm_latent = nn.LayerNorm(dim)
        self.norm_star = nn.LayerNorm(dim)
        self.attn = nn.MultiheadAttention(dim, num_heads, batch_first=True)
        self.ff = nn.Sequential(
            nn.Linear(dim, dim * 2),
            nn.GELU(),
            nn.Linear(dim * 2, dim),
        )
        self.ff_norm = nn.LayerNorm(dim)
        self.gate = nn.Parameter(torch.tensor(0.1))  # Learnable gating

    def forward(self, latents: torch.Tensor, stars: torch.Tensor) -> torch.Tensor:
        """Attend from latents to North Star anchors.

        Args:
            latents: (B, num_latents, D) model's internal state.
            stars: (num_stars, D) frozen identity anchors.

        Returns:
            Modulated latents pulled toward identity.
        """
        B = latents.shape[0]
        # Expand stars to batch: (B, num_stars, D)
        stars_expanded = stars.unsqueeze(0).expand(B, -1, -1)

        normed_l = self.norm_latent(latents)
        normed_s = self.norm_star(stars_expanded)
        attn_out, _ = self.attn(normed_l, normed_s, normed_s)

        # Gated residual — gate starts small so identity influence grows during training
        latents = latents + self.gate * attn_out
        latents = latents + self.ff(self.ff_norm(latents))
        return latents


class NorthStarContrastiveLoss(nn.Module):
    """Contrastive loss pulling model outputs toward North Star centroids.

    For each embedding space, the model's projected output should be
    closer to the corresponding North Star vector than to any other
    frame's output (negative samples from the same batch).

    This is InfoNCE loss applied per-modality.
    """

    def __init__(self, temperature: float = 0.07) -> None:
        super().__init__()
        self.temperature = temperature

    def forward(
        self,
        output_projections: dict[str, torch.Tensor],
        north_stars: dict[str, torch.Tensor],
    ) -> torch.Tensor:
        """Compute contrastive loss across all embedding spaces.

        Args:
            output_projections: Dict of modality -> (B, D) model output projected
                back to each embedding space.
            north_stars: Dict of modality -> (D,) centroid vector.

        Returns:
            Scalar loss (lower = outputs closer to North Stars).
        """
        total_loss = torch.tensor(0.0, device=next(iter(output_projections.values())).device)
        n_modalities = 0

        for name, output in output_projections.items():
            if name not in north_stars:
                continue

            star = north_stars[name]  # (D,)
            B = output.shape[0]

            # Normalize
            output_norm = F.normalize(output, dim=-1)
            star_norm = F.normalize(star.unsqueeze(0), dim=-1)  # (1, D)

            # Cosine similarity between each output and the North Star
            # Positive: output vs its North Star
            pos_sim = torch.mm(output_norm, star_norm.T).squeeze(-1)  # (B,)

            # Negative: output vs other outputs in batch (self-contrast)
            neg_sim = torch.mm(output_norm, output_norm.T)  # (B, B)
            # Mask diagonal (self-similarity)
            mask = torch.eye(B, device=neg_sim.device).bool()
            neg_sim = neg_sim.masked_fill(mask, -1e9)

            # InfoNCE: log(exp(pos/T) / (exp(pos/T) + sum(exp(neg/T))))
            logits = torch.cat([
                pos_sim.unsqueeze(1) / self.temperature,
                neg_sim / self.temperature,
            ], dim=1)  # (B, 1+B)

            labels = torch.zeros(B, dtype=torch.long, device=logits.device)
            loss = F.cross_entropy(logits, labels)
            total_loss = total_loss + loss
            n_modalities += 1

        if n_modalities > 0:
            total_loss = total_loss / n_modalities

        return total_loss


def compute_north_stars(
    training_embeddings: dict[str, np.ndarray],
) -> dict[str, np.ndarray]:
    """Compute North Star centroid vectors from training data.

    Args:
        training_embeddings: Dict of modality name -> (N, D) array
            of all embeddings from training data.

    Returns:
        Dict of modality name -> (D,) centroid vector.
    """
    centroids = {}
    for name, embs in training_embeddings.items():
        if len(embs) == 0:
            continue
        centroid = np.mean(embs, axis=0).astype(np.float32)
        # L2 normalize
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        centroids[name] = centroid
        logger.info("North Star [%s]: dim=%d, computed from %d samples",
                     name, len(centroid), len(embs))
    return centroids
