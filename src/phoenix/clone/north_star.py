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

    Supports both single-centroid mode (basic) and full constellation
    mode (per-state anchors for every prosody/emotion/behavior state).

    Args:
        centroids: Dict of modality name -> centroid vector (numpy).
        shared_dim: Dimension to project centroids to.
        constellation: Optional NorthStarConstellation for per-state anchors.
    """

    def __init__(
        self,
        centroids: dict[str, np.ndarray],
        shared_dim: int = 512,
        constellation: "NorthStarConstellation | None" = None,
    ) -> None:
        super().__init__()
        self._modality_names = sorted(centroids.keys())
        self._has_constellation = constellation is not None
        self._state_names: list[str] = []

        # Learned projection matrices (trained, not random)
        self._projectors = nn.ModuleDict()
        for name in self._modality_names:
            dim = len(centroids[name])
            self._projectors[name] = nn.Linear(dim, shared_dim, bias=False)

        # Register global centroid stars
        for name in self._modality_names:
            vec = centroids[name]
            self.register_buffer(f"star_{name}", torch.tensor(vec, dtype=torch.float32))

        # Register per-state constellation stars
        if constellation is not None:
            all_states = set()
            for modality_stars in constellation.stars.values():
                all_states.update(modality_stars.keys())
            self._state_names = sorted(all_states)

            for modality_name, state_dict in constellation.stars.items():
                for state_name, vec in state_dict.items():
                    safe_name = f"constellation_{modality_name}_{state_name}"
                    self.register_buffer(safe_name, torch.tensor(vec, dtype=torch.float32))

            logger.info(
                "NorthStarAnchors: %d modalities, %d states, %d total constellation vectors",
                len(self._modality_names), len(self._state_names),
                sum(len(s) for s in constellation.stars.values()),
            )
        else:
            logger.info("NorthStarAnchors: %d modalities (global centroids only)", len(self._modality_names))

    @property
    def modality_names(self) -> list[str]:
        return self._modality_names

    @property
    def state_names(self) -> list[str]:
        return self._state_names

    @property
    def has_constellation(self) -> bool:
        return self._has_constellation

    def get_star(self, name: str) -> torch.Tensor:
        """Get the global North Star vector for a modality."""
        return getattr(self, f"star_{name}")

    def get_constellation_star(self, modality: str, state: str) -> torch.Tensor | None:
        """Get a per-state constellation star."""
        safe_name = f"constellation_{modality}_{state}"
        if hasattr(self, safe_name):
            return getattr(self, safe_name)
        return None

    def get_all_stars(self) -> torch.Tensor:
        """Get all anchor vectors stacked for cross-attention.

        In constellation mode, includes per-state vectors (many more anchors).
        The model can attend to the specific state it needs.
        """
        stars = []
        # Global centroids
        for name in self._modality_names:
            star = self.get_star(name)
            projected = self._projectors[name](star.unsqueeze(0)).squeeze(0)
            stars.append(projected)

        # Per-state constellation (if available)
        if self._has_constellation:
            for modality in self._modality_names:
                if modality not in self._projectors:
                    continue
                for state in self._state_names:
                    vec = self.get_constellation_star(modality, state)
                    if vec is not None:
                        projected = self._projectors[modality](vec.unsqueeze(0)).squeeze(0)
                        stars.append(projected)

        return torch.stack(stars) if stars else torch.zeros(1, 512)


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
    """Compute single centroid North Star per modality (basic version).

    For the full constellation with per-state stars, use
    compute_north_star_constellation() instead.
    """
    centroids = {}
    for name, embs in training_embeddings.items():
        if len(embs) == 0:
            continue
        centroid = np.mean(embs, axis=0).astype(np.float32)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        centroids[name] = centroid
        logger.info("North Star [%s]: dim=%d, from %d samples", name, len(centroid), len(embs))
    return centroids


# ---------------------------------------------------------------------------
# North Star Constellation — per-state anchor vectors
# ---------------------------------------------------------------------------

# Every behavioral/emotional state that Santa can be in
SANTA_STATES = [
    # Emotional states
    "neutral", "happy", "warm", "amused", "excited", "emphatic",
    "thoughtful", "sad", "surprised", "concerned",
    # Prosody states
    "high_energy", "low_energy", "fast_speaking", "slow_speaking",
    "rising_pitch", "falling_pitch", "varied_pitch",
    # Behavioral states
    "listening", "thinking", "speaking", "laughing", "nodding",
    "greeting", "farewell",
    # Mouth states
    "mouth_open_wide", "mouth_slightly_open", "mouth_closed", "smile",
    # Eye states
    "eyes_open", "eyes_squint", "blink", "looking_left", "looking_right",
    # Head states
    "head_neutral", "head_tilt_left", "head_tilt_right", "head_nod",
]


@dataclass
class NorthStarConstellation:
    """Complete set of per-state North Star vectors for all modalities.

    Instead of a single centroid per modality, this stores vectors for
    every behavioral state — so the model can navigate to the EXACT
    region of embedding space for "Santa laughing" vs "Santa thinking."
    """
    # modality_name -> state_name -> centroid_vector
    stars: dict[str, dict[str, np.ndarray]]
    # Global centroid (average across all states)
    global_centroids: dict[str, np.ndarray]
    # Per-state sample counts
    state_counts: dict[str, int]


def compute_north_star_constellation(
    training_embeddings: dict[str, np.ndarray],
    prosody_segments: list[dict],
    emotion_data: list[dict],
    blendshape_data: list[dict],
    timestamps_ms: list[int],
) -> NorthStarConstellation:
    """Compute the full North Star constellation — per-state anchors.

    For each behavioral state (happy, thinking, speaking, etc.), computes
    the centroid of embeddings that correspond to that state. This gives
    the model a complete map of Santa's identity manifold.

    Args:
        training_embeddings: Dict of modality -> (N, D) embeddings.
        prosody_segments: Prosody data with energy_level, pitch_contour, etc.
        emotion_data: Emotion curve entries with arousal, valence.
        blendshape_data: Ground truth blendshapes per frame.
        timestamps_ms: Timestamp for each training sample.

    Returns:
        NorthStarConstellation with per-state anchors.
    """
    n = len(timestamps_ms)
    stars: dict[str, dict[str, np.ndarray]] = {}
    state_counts: dict[str, int] = {}

    # Classify each training frame into states
    frame_states: list[set[str]] = [set() for _ in range(n)]

    for i in range(n):
        ts = timestamps_ms[i]
        states = frame_states[i]
        states.add("neutral")  # Every frame is at least neutral

        # Classify from prosody
        nearest_prosody = _find_nearest_by_ts(prosody_segments, ts)
        if nearest_prosody:
            energy = nearest_prosody.get("energy_level", "medium")
            contour = nearest_prosody.get("pitch_contour", "flat")
            rate = nearest_prosody.get("speaking_rate_wpm", 0)
            emphasis = nearest_prosody.get("has_emphasis", False)

            if energy == "high":
                states.update({"high_energy", "excited"})
            elif energy == "low":
                states.update({"low_energy", "thoughtful"})

            if contour == "rising":
                states.add("rising_pitch")
            elif contour == "falling":
                states.update({"falling_pitch", "warm"})
            elif contour == "varied":
                states.update({"varied_pitch", "emphatic"})

            if rate and rate > 170:
                states.add("fast_speaking")
            elif rate and rate < 130:
                states.add("slow_speaking")

            if emphasis:
                states.add("emphatic")

            if rate and rate > 0:
                states.add("speaking")
            else:
                states.add("listening")

        # Classify from emotion data
        nearest_emotion = _find_nearest_by_ts(emotion_data, ts)
        if nearest_emotion:
            arousal = nearest_emotion.get("arousal", 0.5)
            valence = nearest_emotion.get("valence", 0.5)
            if arousal > 0.7:
                states.add("excited")
            if valence > 0.7:
                states.add("happy")
            if valence < 0.3:
                states.add("sad")

        # Classify from blendshapes
        if i < len(blendshape_data):
            bs = blendshape_data[i].get("blendshapes", [0] * 52)
            jaw_open = bs[0] if len(bs) > 0 else 0
            smile = (bs[3] + bs[4]) / 2 if len(bs) > 4 else 0
            blink = (bs[28] + bs[29]) / 2 if len(bs) > 29 else 0
            eye_wide = (bs[30] + bs[31]) / 2 if len(bs) > 31 else 0

            if jaw_open > 0.6:
                states.add("mouth_open_wide")
            elif jaw_open > 0.2:
                states.add("mouth_slightly_open")
            else:
                states.add("mouth_closed")

            if smile > 0.5:
                states.update({"smile", "happy", "amused"})

            if blink > 0.7:
                states.add("blink")

            if eye_wide > 0.5:
                states.update({"eyes_open", "surprised"})

    # Compute per-state centroids for each modality
    for modality_name, embs in training_embeddings.items():
        if len(embs) != n:
            # Skip modalities that don't align frame-by-frame
            continue

        stars[modality_name] = {}
        for state in SANTA_STATES:
            # Find all frames in this state
            indices = [i for i in range(n) if state in frame_states[i]]
            if len(indices) < 3:
                continue  # Need at least 3 samples

            state_embs = embs[indices]
            centroid = np.mean(state_embs, axis=0).astype(np.float32)
            norm = np.linalg.norm(centroid)
            if norm > 0:
                centroid = centroid / norm
            stars[modality_name][state] = centroid
            state_counts[state] = state_counts.get(state, 0) + len(indices)

    # Global centroids (average across all states)
    global_centroids = compute_north_stars(training_embeddings)

    # Log constellation stats
    total_stars = sum(len(s) for s in stars.values())
    logger.info(
        "North Star Constellation: %d modalities x %d states = %d anchor vectors",
        len(stars), len(set().union(*(s.keys() for s in stars.values())) if stars else set()),
        total_stars,
    )
    for state, count in sorted(state_counts.items(), key=lambda x: -x[1])[:10]:
        logger.info("  %s: %d frame-modality samples", state, count)

    return NorthStarConstellation(
        stars=stars,
        global_centroids=global_centroids,
        state_counts=state_counts,
    )


def _find_nearest_by_ts(items: list[dict], target_ms: int) -> dict | None:
    """Find item nearest to timestamp."""
    if not items:
        return None
    best = None
    best_dist = float("inf")
    for item in items:
        ts = item.get("start_ms", item.get("timestamp_ms", 0))
        dist = abs(ts - target_ms)
        if dist < best_dist:
            best_dist = dist
            best = item
    return best if best_dist < 10000 else None  # Within 10s
