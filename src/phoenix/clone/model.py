"""Clone Model: Perceiver-based multi-embedding avatar controller.

Takes 9+ embedding spaces as input conditioning and outputs complete
avatar control signals: blendshapes, voice parameters, body pose,
gaze direction, and behavior decisions.

Architecture:
  9 embeddings → Per-modality projection (→512-dim each)
               → Perceiver cross-attention (128 latents, 4 layers)
               → FiLM conditioning (prosody scalars)
               → Transformer decoder (4 layers)
               → Output heads (blendshape + voice + body + gaze + behavior)

~13M parameters. Inference <1ms on RTX 5090. Training <10 min.
"""
from __future__ import annotations

import logging
import math

import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
EMBEDDING_DIMS = {
    "visual": 1152,      # SigLIP
    "semantic": 768,      # Nomic
    "emotion": 1024,      # Wav2Vec2
    "speaker": 512,       # WavLM
    "voice": 2048,        # ECAPA-TDNN
    "prosody": 12,        # Scalar features
    "sentence": 384,      # MiniLM
    "ocr_context": 512,   # Projected OCR Provenance
    "memory_context": 512, # Projected RuFlo Memory
}

SHARED_DIM = 512
NUM_LATENTS = 128
NUM_LAYERS = 4
NUM_HEADS = 8

# Output dimensions
BLENDSHAPE_DIM = 52       # Full ARKit blendshapes
VOICE_DIM = 16            # Prosody style, rate, pitch, emotion
BODY_POSE_DIM = 12        # Head + upper body params
GAZE_DIM = 6              # Eye gaze direction
BEHAVIOR_DIM = 6          # Speak probability, intensity, gesture, etc.
TOTAL_OUTPUT_DIM = BLENDSHAPE_DIM + VOICE_DIM + BODY_POSE_DIM + GAZE_DIM + BEHAVIOR_DIM


# ---------------------------------------------------------------------------
# Sub-modules
# ---------------------------------------------------------------------------
class ModalityProjection(nn.Module):
    """Project a single embedding to shared dimension."""

    def __init__(self, input_dim: int, output_dim: int = SHARED_DIM) -> None:
        super().__init__()
        if input_dim < 32:
            # Small inputs (prosody) get an MLP
            self.proj = nn.Sequential(
                nn.Linear(input_dim, 128),
                nn.GELU(),
                nn.Linear(128, output_dim),
                nn.LayerNorm(output_dim),
            )
        else:
            self.proj = nn.Sequential(
                nn.Linear(input_dim, output_dim),
                nn.LayerNorm(output_dim),
            )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.proj(x)


class PerceiverCrossAttention(nn.Module):
    """Cross-attention from latent queries to input tokens."""

    def __init__(self, dim: int = SHARED_DIM, num_heads: int = NUM_HEADS) -> None:
        super().__init__()
        self.norm_latent = nn.LayerNorm(dim)
        self.norm_input = nn.LayerNorm(dim)
        self.attn = nn.MultiheadAttention(dim, num_heads, batch_first=True)
        self.ff = nn.Sequential(
            nn.Linear(dim, dim * 4),
            nn.GELU(),
            nn.Linear(dim * 4, dim),
        )
        self.ff_norm = nn.LayerNorm(dim)

    def forward(self, latents: torch.Tensor, inputs: torch.Tensor) -> torch.Tensor:
        # Cross-attention: latents attend to inputs
        normed_l = self.norm_latent(latents)
        normed_i = self.norm_input(inputs)
        attn_out, _ = self.attn(normed_l, normed_i, normed_i)
        latents = latents + attn_out
        # Feed-forward
        latents = latents + self.ff(self.ff_norm(latents))
        return latents


class FiLMLayer(nn.Module):
    """Feature-wise Linear Modulation from scalar conditioning."""

    def __init__(self, cond_dim: int, hidden_dim: int = SHARED_DIM) -> None:
        super().__init__()
        self.gamma = nn.Linear(cond_dim, hidden_dim)
        self.beta = nn.Linear(cond_dim, hidden_dim)

    def forward(self, x: torch.Tensor, cond: torch.Tensor) -> torch.Tensor:
        gamma = self.gamma(cond).unsqueeze(1)  # (B, 1, D)
        beta = self.beta(cond).unsqueeze(1)
        return x * (1 + gamma) + beta


class TransformerBlock(nn.Module):
    """Standard transformer self-attention block."""

    def __init__(self, dim: int = SHARED_DIM, num_heads: int = NUM_HEADS) -> None:
        super().__init__()
        self.norm1 = nn.LayerNorm(dim)
        self.attn = nn.MultiheadAttention(dim, num_heads, batch_first=True)
        self.norm2 = nn.LayerNorm(dim)
        self.ff = nn.Sequential(
            nn.Linear(dim, dim * 4),
            nn.GELU(),
            nn.Linear(dim * 4, dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        normed = self.norm1(x)
        attn_out, _ = self.attn(normed, normed, normed)
        x = x + attn_out
        x = x + self.ff(self.norm2(x))
        return x


# ---------------------------------------------------------------------------
# Main Model
# ---------------------------------------------------------------------------
class CloneModel(nn.Module):
    """Multi-embedding avatar clone controller.

    Takes 9+ embedding spaces as input conditioning and outputs
    complete avatar control signals in a single forward pass.

    Args:
        embedding_dims: Dict of modality name → input dimension.
        shared_dim: Dimension of the shared latent space.
        num_latents: Number of Perceiver latent queries.
        num_layers: Number of cross-attention and decoder layers.
    """

    def __init__(
        self,
        embedding_dims: dict[str, int] | None = None,
        shared_dim: int = SHARED_DIM,
        num_latents: int = NUM_LATENTS,
        num_layers: int = NUM_LAYERS,
    ) -> None:
        super().__init__()
        dims = embedding_dims or EMBEDDING_DIMS

        # Per-modality projection heads
        self.projections = nn.ModuleDict({
            name: ModalityProjection(dim, shared_dim)
            for name, dim in dims.items()
        })

        # Learned modality type embeddings
        self.modality_embeddings = nn.Embedding(len(dims), shared_dim)

        # Learnable latent queries
        self.latents = nn.Parameter(torch.randn(1, num_latents, shared_dim) * 0.02)

        # Perceiver cross-attention layers
        self.cross_attn_layers = nn.ModuleList([
            PerceiverCrossAttention(shared_dim) for _ in range(num_layers)
        ])

        # FiLM conditioning for prosody scalars
        self.film = FiLMLayer(
            cond_dim=dims.get("prosody", 12),
            hidden_dim=shared_dim,
        )

        # North Star identity anchors (set via fuse_north_stars())
        self._north_star_anchors = None
        self._north_star_attn = None

        # Transformer decoder (self-attention on latents)
        # Interleaves self-attention with North Star cross-attention
        self.decoder_layers = nn.ModuleList([
            TransformerBlock(shared_dim) for _ in range(num_layers)
        ])

        # Output heads
        self.head_blendshape = nn.Linear(shared_dim, BLENDSHAPE_DIM)
        self.head_voice = nn.Linear(shared_dim, VOICE_DIM)
        self.head_body = nn.Linear(shared_dim, BODY_POSE_DIM)
        self.head_gaze = nn.Linear(shared_dim, GAZE_DIM)
        self.head_behavior = nn.Linear(shared_dim, BEHAVIOR_DIM)

        # Reverse projection heads: shared_dim → each embedding space
        # Used for cycle consistency / contrastive loss evaluation
        self.reverse_projections = nn.ModuleDict()

        # Store modality order for consistent indexing
        self._modality_order = list(dims.keys())

        logger.info(
            "CloneModel: %d modalities, %d latents, %d layers, %.1fM params",
            len(dims), num_latents, num_layers,
            sum(p.numel() for p in self.parameters()) / 1e6,
        )

    def fuse_north_stars(self, centroids: dict[str, "np.ndarray"]) -> None:
        """Fuse North Star identity anchors into the transformer.

        This is the key architectural innovation: embedding Santa's identity
        directly into the transformer as frozen cross-attention targets.
        After this call, every forward pass is pulled toward Santa.

        Args:
            centroids: Dict of modality name → centroid vector (numpy).
        """
        import numpy as np
        from phoenix.clone.north_star import NorthStarAnchors, NorthStarAttention

        shared_dim = self.latents.shape[-1]

        # Create frozen anchor module
        self._north_star_anchors = NorthStarAnchors(centroids, shared_dim)
        self._north_star_anchors = self._north_star_anchors.to(self.latents.device)

        # Create North Star cross-attention layers (one per decoder layer)
        self._north_star_attn = nn.ModuleList([
            NorthStarAttention(shared_dim) for _ in range(len(self.decoder_layers))
        ]).to(self.latents.device)

        # Create reverse projection heads for contrastive loss
        for name in centroids:
            dim = len(centroids[name])
            self.reverse_projections[name] = nn.Linear(shared_dim, dim).to(self.latents.device)

        total_new = sum(p.numel() for p in self._north_star_attn.parameters())
        total_new += sum(p.numel() for p in self.reverse_projections.parameters())
        logger.info(
            "North Stars fused: %d anchors, %d new params (%.1fM), total %.1fM",
            len(centroids), total_new, total_new / 1e6,
            self.param_count / 1e6,
        )

    def project_to_embedding_spaces(self, pooled: torch.Tensor) -> dict[str, torch.Tensor]:
        """Project the model's pooled output back to each embedding space.

        Used for contrastive loss: compare projected outputs against
        North Star centroids to measure identity fidelity.

        Args:
            pooled: (B, shared_dim) model output after pooling.

        Returns:
            Dict of modality name → (B, D_m) projected vectors.
        """
        projections = {}
        for name, proj in self.reverse_projections.items():
            projections[name] = proj(pooled)
        return projections

    def forward(
        self,
        embeddings: dict[str, torch.Tensor],
        prosody_scalars: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        """Forward pass: embeddings → avatar control signals.

        If North Stars are fused, the decoder interleaves self-attention
        with North Star cross-attention, pulling outputs toward identity.

        Args:
            embeddings: Dict of modality name → tensor (B, D_m).
            prosody_scalars: Optional prosody features (B, 12) for FiLM.

        Returns:
            Dict with keys: blendshapes, voice, body, gaze, behavior.
            Each value is (B, output_dim) tensor with values in appropriate ranges.
        """
        batch_size = next(iter(embeddings.values())).shape[0]
        device = next(iter(embeddings.values())).device

        # Project each modality to shared space and add modality embedding
        tokens = []
        for i, name in enumerate(self._modality_order):
            if name in embeddings:
                proj = self.projections[name](embeddings[name])  # (B, D)
                proj = proj + self.modality_embeddings.weight[i]  # Add modality ID
                tokens.append(proj.unsqueeze(1))  # (B, 1, D)

        if not tokens:
            # No embeddings provided — return zeros
            return self._zero_output(batch_size, device)

        # Stack all projected tokens: (B, num_modalities, D)
        input_tokens = torch.cat(tokens, dim=1)

        # Expand learnable latents to batch: (B, num_latents, D)
        latents = self.latents.expand(batch_size, -1, -1)

        # Perceiver cross-attention: latents attend to input tokens
        for layer in self.cross_attn_layers:
            latents = layer(latents, input_tokens)

        # FiLM conditioning from prosody scalars
        if prosody_scalars is not None:
            latents = self.film(latents, prosody_scalars)

        # Transformer decoder: interleave self-attention with North Star cross-attention
        # Each layer: self-attend → cross-attend to identity anchors
        north_stars = None
        if self._north_star_anchors is not None:
            north_stars = self._north_star_anchors.get_all_stars()

        for i, layer in enumerate(self.decoder_layers):
            latents = layer(latents)
            # North Star injection: pull latents toward Santa's identity
            if north_stars is not None and self._north_star_attn is not None:
                latents = self._north_star_attn[i](latents, north_stars)

        # Pool latents → single vector per sample
        pooled = latents.mean(dim=1)  # (B, D)

        # Output heads with appropriate activations
        output = {
            "blendshapes": torch.sigmoid(self.head_blendshape(pooled)),  # [0, 1]
            "voice": self.head_voice(pooled),  # Unconstrained
            "body": torch.tanh(self.head_body(pooled)),  # [-1, 1]
            "gaze": torch.tanh(self.head_gaze(pooled)) * 30.0,  # [-30, 30] degrees
            "behavior": torch.sigmoid(self.head_behavior(pooled)),  # [0, 1] probabilities
        }

        # Include pooled vector for contrastive loss computation
        output["_pooled"] = pooled

        return output

    def _zero_output(self, batch_size: int, device: torch.device) -> dict[str, torch.Tensor]:
        return {
            "blendshapes": torch.zeros(batch_size, BLENDSHAPE_DIM, device=device),
            "voice": torch.zeros(batch_size, VOICE_DIM, device=device),
            "body": torch.zeros(batch_size, BODY_POSE_DIM, device=device),
            "gaze": torch.zeros(batch_size, GAZE_DIM, device=device),
            "behavior": torch.zeros(batch_size, BEHAVIOR_DIM, device=device),
        }

    # ------------------------------------------------------------------
    # CUDA 13.2 Optimizations
    # ------------------------------------------------------------------

    def compile(self, mode: str = "max-autotune") -> "CloneModel":
        """Wrap the forward pass with torch.compile for kernel fusion.

        Call after model loading / warmup to let the compiler trace
        and optimize the graph. The first forward pass after compile()
        will be slower (tracing), subsequent passes benefit from fused
        CUDA kernels and reduced launch overhead.

        Args:
            mode: torch.compile mode. "max-autotune" gives best
                throughput at the cost of longer first-run compilation.
                Use "reduce-overhead" for faster compilation.

        Returns:
            self, for chaining.
        """
        self.forward = torch.compile(self.forward, mode=mode)  # type: ignore[method-assign]
        logger.info("CloneModel compiled with mode=%s", mode)
        return self

    def quantize_fp8(self) -> "CloneModel":
        """Apply FP8 dynamic quantization to all Linear layers.

        Uses torchao Float8DynamicActivationFloat8WeightConfig for
        near-lossless 2x memory reduction and faster matmul on
        Ada/Hopper GPUs. Call BEFORE compile() for best results.

        Returns:
            self, for chaining.

        Raises:
            ImportError: If torchao is not installed.
        """
        try:
            from torchao.quantization import (
                Float8DynamicActivationFloat8WeightConfig,
                quantize_,
            )
        except ImportError as exc:
            raise ImportError(
                "torchao is required for FP8 quantization. "
                "Install with: pip install torchao"
            ) from exc

        config = Float8DynamicActivationFloat8WeightConfig()
        quantize_(self, config)

        logger.info(
            "CloneModel quantized to FP8: %.1fM params",
            self.param_count / 1e6,
        )
        return self

    @property
    def param_count(self) -> int:
        return sum(p.numel() for p in self.parameters())

    @property
    def param_count_trainable(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
