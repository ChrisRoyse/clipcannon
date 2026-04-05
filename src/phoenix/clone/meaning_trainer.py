"""Meaning-aware clone training pipeline.

Instead of blind MSE on blendshapes, this pipeline understands WHAT each
embedding space means and trains the model to produce avatar control signals
that are semantically coherent across all modalities.

Architecture:
  1. SemanticStateExtractor — classifies each frame into meaning labels
  2. MeaningAlignedDataset — loads NPZ embeddings + pre-computed labels
  3. MeaningAwareLoss — geometric + semantic consistency + cross-modal coherence
  4. MeaningTrainer — end-to-end training with the new loss landscape

The key insight: when emotion says "joy" AND prosody says "energetic",
the blendshapes MUST include smile + raised cheeks + wide eyes. The loss
function enforces these cross-modal constraints, not just per-frame MSE.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Meaning labels — the vocabulary of behavioral states
# ---------------------------------------------------------------------------
EMOTION_LABELS = [
    "neutral", "happy", "sad", "excited", "thoughtful",
    "amused", "concerned", "emphatic",
]
PROSODY_LABELS = [
    "calm", "energetic", "questioning", "emphatic",
    "varied", "slow", "fast",
]
CONTEXT_LABELS = [
    "storytelling", "answering", "greeting", "listening",
    "thinking", "laughing",
]
VISUAL_LABELS = [
    "animated", "still", "close_up", "looking_away",
    "smiling", "serious",
]


# ARKit blendshape indices for semantic enforcement
_BS_JAW_OPEN = 0
_BS_MOUTH_SMILE_L = 3
_BS_MOUTH_SMILE_R = 4
_BS_BROW_INNER_UP = 23
_BS_BROW_DOWN_L = 24
_BS_BROW_DOWN_R = 25
_BS_EYE_BLINK_L = 28
_BS_EYE_BLINK_R = 29
_BS_EYE_WIDE_L = 30
_BS_EYE_WIDE_R = 31


# ---------------------------------------------------------------------------
# Semantic State Extractor
# ---------------------------------------------------------------------------
@dataclass
class FrameMeaning:
    """Multi-label meaning vector for a single frame."""
    emotion: str = "neutral"
    prosody: str = "calm"
    context: str = "listening"
    visual: str = "still"
    # Soft probabilities for loss computation
    emotion_probs: np.ndarray = field(
        default_factory=lambda: np.zeros(len(EMOTION_LABELS), dtype=np.float32)
    )
    prosody_probs: np.ndarray = field(
        default_factory=lambda: np.zeros(len(PROSODY_LABELS), dtype=np.float32)
    )


class SemanticStateExtractor:
    """Extract meaning labels from raw embedding features.

    This is the bridge between raw numbers and behavioral semantics.
    Each modality's features are classified into human-interpretable
    states that the loss function can reason about.
    """

    def classify_emotion(self, arousal: float, valence: float, energy: float) -> tuple[str, np.ndarray]:
        """Classify emotion state from arousal/valence/energy scalars.

        Returns (label, soft_probs) where soft_probs sums to 1.
        """
        probs = np.zeros(len(EMOTION_LABELS), dtype=np.float32)

        # Map continuous dimensions to categorical emotions
        # Arousal range in data: [0.15, 0.22] — very compressed
        # Valence range: [0.504, 0.509] — extremely compressed
        # Energy range: [0.296, 0.347]
        # Normalize to [0, 1] within observed ranges
        a_norm = np.clip((arousal - 0.15) / 0.07, 0, 1)
        v_norm = np.clip((valence - 0.50) / 0.01, 0, 1)
        e_norm = np.clip((energy - 0.29) / 0.06, 0, 1)

        # Rule-based soft classification
        probs[0] = 0.3  # neutral baseline
        if v_norm > 0.6 and a_norm > 0.5:
            probs[1] += 0.4  # happy
            probs[3] += 0.2  # excited
        elif v_norm > 0.6:
            probs[1] += 0.3  # happy
            probs[5] += 0.2  # amused
        elif v_norm < 0.3:
            probs[2] += 0.3  # sad
            probs[6] += 0.2  # concerned
        if a_norm > 0.7:
            probs[3] += 0.3  # excited
            probs[7] += 0.2  # emphatic
        elif a_norm < 0.3:
            probs[4] += 0.3  # thoughtful
        if e_norm > 0.6:
            probs[3] += 0.2  # excited
        elif e_norm < 0.3:
            probs[4] += 0.2  # thoughtful

        # Normalize
        total = probs.sum()
        if total > 0:
            probs /= total

        label = EMOTION_LABELS[int(np.argmax(probs))]
        return label, probs

    def classify_prosody(self, features: np.ndarray) -> tuple[str, np.ndarray]:
        """Classify prosody style from 12 prosody features.

        Feature layout (from data_pipeline):
          0: f0_mean/300 (normalized pitch)
          1: f0_range/500 (pitch range)
          2: energy_rms
          3: speaking_rate_wpm/300
          4: has_emphasis (0/1)
          5: pitch_rising (0/1)
          6: prosody_score/100
          7-11: reserved (zeros)
        """
        probs = np.zeros(len(PROSODY_LABELS), dtype=np.float32)

        f0_norm = features[0]   # ~0.34-0.77
        f0_range = features[1]  # ~0.05-1.02
        energy = features[2]    # ~0.01-0.06
        rate = features[3]      # ~0.18-1.51
        emphasis = features[4]  # 0 or 1
        rising = features[5]    # 0 or 1
        score = features[6]     # ~0.36-1.0

        # Calm: low energy, low range, moderate rate
        if energy < 0.03 and f0_range < 0.3:
            probs[0] += 0.5  # calm
        # Energetic: high energy, wide range, fast rate
        if energy > 0.04 or f0_range > 0.5:
            probs[1] += 0.4  # energetic
        # Questioning: rising pitch
        if rising > 0.5:
            probs[2] += 0.4  # questioning
        # Emphatic: has emphasis, wide pitch range
        if emphasis > 0.5 and f0_range > 0.3:
            probs[3] += 0.5  # emphatic
        elif emphasis > 0.5:
            probs[3] += 0.3
        # Varied: wide pitch range but not emphatic
        if f0_range > 0.6 and emphasis < 0.5:
            probs[4] += 0.4  # varied
        # Slow/Fast speaking
        if rate < 0.4:
            probs[5] += 0.4  # slow
        elif rate > 0.7:
            probs[6] += 0.4  # fast

        # Add baseline
        probs += 0.1
        total = probs.sum()
        if total > 0:
            probs /= total

        label = PROSODY_LABELS[int(np.argmax(probs))]
        return label, probs

    def classify_visual_from_flame(self, flame_exp: np.ndarray) -> str:
        """Classify visual state from FLAME expression parameters.

        FLAME expression space is 100-dim. The first few params control:
          0-5: jaw + mouth
          6-9: cheeks + smile
          10-15: brows
          15-20: eyes
        """
        # Use expression magnitude as animation indicator
        exp_energy = np.abs(flame_exp[:20]).mean()
        smile_signal = flame_exp[6:10].mean() if len(flame_exp) > 10 else 0
        brow_signal = np.abs(flame_exp[10:16]).mean() if len(flame_exp) > 16 else 0

        if exp_energy > 2.0:
            return "animated"
        elif smile_signal > 1.0:
            return "smiling"
        elif brow_signal > 1.5:
            return "serious"
        elif exp_energy < 0.8:
            return "still"
        return "close_up"

    def classify_context_from_semantic(self, sem_emb: np.ndarray) -> str:
        """Classify semantic context from Nomic text embedding.

        Uses embedding norm and directional features as proxy for
        content type. In production, this would use a trained classifier.
        """
        norm = np.linalg.norm(sem_emb)
        # Embedding directions correlate with content types
        # Use PCA-like heuristics on first few dimensions
        first_quad = sem_emb[:192].mean()
        second_quad = sem_emb[192:384].mean()
        third_quad = sem_emb[384:576].mean()

        if norm < 0.1:
            return "listening"
        elif first_quad > 0.01:
            return "storytelling"
        elif second_quad < -0.01:
            return "answering"
        elif third_quad > 0.005:
            return "greeting"
        return "thinking"

    def extract_frame_meanings(
        self,
        emo_data: np.ndarray,
        emo_ts: np.ndarray,
        pro_data: np.ndarray,
        pro_ts: np.ndarray,
        sem_emb: np.ndarray | None,
        sem_ts: np.ndarray | None,
        flame_exp: np.ndarray | None,
        flame_ts_ms: np.ndarray | None,
        target_ts: np.ndarray,
    ) -> list[FrameMeaning]:
        """Extract meaning labels for each target timestamp.

        Performs temporal alignment: for each target frame, finds the
        nearest data point from each modality and classifies it.

        Args:
            emo_data: (N_emo, 3) arousal/valence/energy.
            emo_ts: (N_emo,) timestamps in ms.
            pro_data: (N_pro, 12) prosody features.
            pro_ts: (N_pro,) timestamps in ms.
            sem_emb: (N_sem, 768) semantic embeddings.
            sem_ts: (N_sem,) timestamps in ms.
            flame_exp: (N_flame, 100) FLAME expression params.
            flame_ts_ms: (N_flame,) timestamps in ms.
            target_ts: (N,) target timestamps in ms.

        Returns:
            List of FrameMeaning for each target timestamp.
        """
        n = len(target_ts)
        meanings = []

        for i in range(n):
            ts = target_ts[i]
            fm = FrameMeaning()

            # Emotion classification
            if len(emo_data) > 0 and len(emo_ts) > 0:
                idx = _nearest_idx(emo_ts, ts)
                a, v, e = emo_data[idx]
                fm.emotion, fm.emotion_probs = self.classify_emotion(a, v, e)

            # Prosody classification
            if len(pro_data) > 0 and len(pro_ts) > 0:
                idx = _nearest_idx(pro_ts, ts)
                fm.prosody, fm.prosody_probs = self.classify_prosody(pro_data[idx])

            # Visual classification from FLAME
            if flame_exp is not None and flame_ts_ms is not None and len(flame_exp) > 0:
                idx = _nearest_idx(flame_ts_ms, ts)
                fm.visual = self.classify_visual_from_flame(flame_exp[idx])

            # Context classification from semantic
            if sem_emb is not None and sem_ts is not None and len(sem_emb) > 0:
                idx = _nearest_idx(sem_ts, ts)
                fm.context = self.classify_context_from_semantic(sem_emb[idx])

            meanings.append(fm)

        return meanings


def _nearest_idx(timestamps: np.ndarray, target: float) -> int:
    """Find index of nearest timestamp using binary search."""
    idx = np.searchsorted(timestamps, target)
    if idx == 0:
        return 0
    if idx >= len(timestamps):
        return len(timestamps) - 1
    # Compare left and right neighbors
    if abs(timestamps[idx - 1] - target) <= abs(timestamps[idx] - target):
        return idx - 1
    return idx


# ---------------------------------------------------------------------------
# Meaning-Aligned Dataset
# ---------------------------------------------------------------------------
class MeaningAlignedDataset(Dataset):
    """Training dataset with multi-modal embeddings and meaning labels.

    Loads from all_embeddings.npz and aligns all modalities to a common
    timeline. Each sample contains raw embeddings (for the model) plus
    meaning labels (for the loss function).
    """

    def __init__(
        self,
        npz_path: str,
        target_fps: int = 2,
        max_frames: int = 5000,
    ) -> None:
        logger.info("Loading embeddings from %s", npz_path)
        data = np.load(npz_path, allow_pickle=True)

        # Raw embeddings
        self.vis_emb = data["vis_emb"]      # (N_vis, 1152)
        self.vis_ts = data["vis_ts"]         # (N_vis,) ms
        self.sem_emb = data["sem_emb"]      # (N_sem, 768)
        self.sem_ts = data["sem_ts"]         # (N_sem,) ms
        self.emo_data = data["emo_data"]    # (N_emo, 3)
        self.emo_ts = data["emo_ts"]         # (N_emo,) ms
        self.pro_data = data["pro_data"]    # (N_pro, 12)
        self.pro_ts = data["pro_ts"]         # (N_pro,) ms
        self.flame_exp = data["flame_exp"]  # (N_flame, 100)
        # FLAME timestamps are in seconds; convert to ms
        flame_ts_raw = data["flame_ts"]
        if flame_ts_raw.max() < 10000:
            self.flame_ts = (flame_ts_raw * 1000).astype(np.int64)
        else:
            self.flame_ts = flame_ts_raw.astype(np.int64)

        # Use visual timestamps as the master timeline (most frames)
        self.target_ts = self.vis_ts[:max_frames]
        self.n_frames = len(self.target_ts)

        logger.info(
            "Dataset: %d frames, vis=%d, sem=%d, emo=%d, pro=%d, flame=%d",
            self.n_frames, len(self.vis_emb), len(self.sem_emb),
            len(self.emo_data), len(self.pro_data), len(self.flame_exp),
        )

        # Pre-compute aligned indices for fast lookup
        self._sem_idx = np.array([_nearest_idx(self.sem_ts, t) for t in self.target_ts])
        self._emo_idx = np.array([_nearest_idx(self.emo_ts, t) for t in self.target_ts])
        self._pro_idx = np.array([_nearest_idx(self.pro_ts, t) for t in self.target_ts])
        self._flame_idx = np.array([_nearest_idx(self.flame_ts, t) for t in self.target_ts])

        # Extract meaning labels
        logger.info("Extracting semantic state labels...")
        extractor = SemanticStateExtractor()
        self.meanings = extractor.extract_frame_meanings(
            self.emo_data, self.emo_ts,
            self.pro_data, self.pro_ts,
            self.sem_emb, self.sem_ts,
            self.flame_exp, self.flame_ts,
            self.target_ts,
        )

        # Pre-encode labels as indices for loss computation
        self.emotion_indices = np.array([
            EMOTION_LABELS.index(m.emotion) for m in self.meanings
        ], dtype=np.int64)
        self.prosody_indices = np.array([
            PROSODY_LABELS.index(m.prosody) for m in self.meanings
        ], dtype=np.int64)
        self.emotion_probs = np.stack([m.emotion_probs for m in self.meanings])
        self.prosody_probs = np.stack([m.prosody_probs for m in self.meanings])

        # Log label distribution
        self._log_label_distribution()

    def _log_label_distribution(self) -> None:
        """Log the distribution of meaning labels."""
        from collections import Counter
        emo_counts = Counter(m.emotion for m in self.meanings)
        pro_counts = Counter(m.prosody for m in self.meanings)
        ctx_counts = Counter(m.context for m in self.meanings)
        vis_counts = Counter(m.visual for m in self.meanings)
        logger.info("Emotion distribution: %s", dict(emo_counts.most_common()))
        logger.info("Prosody distribution: %s", dict(pro_counts.most_common()))
        logger.info("Context distribution: %s", dict(ctx_counts.most_common()))
        logger.info("Visual distribution: %s", dict(vis_counts.most_common()))

    def __len__(self) -> int:
        return self.n_frames

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        """Get a single training sample with all modalities aligned."""
        return {
            # Raw embeddings (model input)
            "visual": torch.from_numpy(self.vis_emb[idx]),
            "semantic": torch.from_numpy(self.sem_emb[self._sem_idx[idx]]),
            "prosody": torch.from_numpy(self.pro_data[self._pro_idx[idx]]),
            "emotion_scalars": torch.tensor(self.emo_data[self._emo_idx[idx]]),
            # FLAME expression as ground truth for geometric loss
            "flame_exp": torch.from_numpy(self.flame_exp[self._flame_idx[idx]]),
            # Meaning labels for semantic loss
            "emotion_idx": torch.tensor(self.emotion_indices[idx]),
            "prosody_idx": torch.tensor(self.prosody_indices[idx]),
            "emotion_probs": torch.from_numpy(self.emotion_probs[idx]),
            "prosody_probs": torch.from_numpy(self.prosody_probs[idx]),
            # Timestamp for temporal smoothness
            "timestamp_ms": torch.tensor(self.target_ts[idx], dtype=torch.long),
        }


# ---------------------------------------------------------------------------
# Meaning-Aware Loss Function
# ---------------------------------------------------------------------------
# Semantic consistency rules: when emotion says X, blendshapes must show Y
# Format: emotion_label -> list of (blendshape_index, min_value, weight)
EMOTION_BLENDSHAPE_RULES: dict[str, list[tuple[int, float, float]]] = {
    "happy": [
        (_BS_MOUTH_SMILE_L, 0.3, 1.0),  # Must smile
        (_BS_MOUTH_SMILE_R, 0.3, 1.0),
        (_BS_BROW_INNER_UP, 0.2, 0.5),  # Raised brows
        (_BS_EYE_WIDE_L, 0.1, 0.3),     # Slightly wider eyes
    ],
    "excited": [
        (_BS_MOUTH_SMILE_L, 0.4, 1.0),
        (_BS_MOUTH_SMILE_R, 0.4, 1.0),
        (_BS_EYE_WIDE_L, 0.3, 0.8),
        (_BS_EYE_WIDE_R, 0.3, 0.8),
        (_BS_BROW_INNER_UP, 0.3, 0.7),
    ],
    "sad": [
        (_BS_BROW_DOWN_L, 0.2, 0.8),    # Furrowed brows
        (_BS_BROW_DOWN_R, 0.2, 0.8),
    ],
    "amused": [
        (_BS_MOUTH_SMILE_L, 0.2, 0.8),
        (_BS_MOUTH_SMILE_R, 0.2, 0.8),
        (_BS_EYE_WIDE_L, 0.05, 0.3),    # Slight squint
    ],
    "emphatic": [
        (_BS_BROW_INNER_UP, 0.3, 0.8),
        (_BS_JAW_OPEN, 0.2, 0.5),
        (_BS_EYE_WIDE_L, 0.2, 0.5),
        (_BS_EYE_WIDE_R, 0.2, 0.5),
    ],
    "thoughtful": [
        (_BS_BROW_DOWN_L, 0.1, 0.5),
        (_BS_BROW_DOWN_R, 0.1, 0.5),
    ],
    "concerned": [
        (_BS_BROW_INNER_UP, 0.2, 0.6),
        (_BS_BROW_DOWN_L, 0.1, 0.4),
    ],
}

# Cross-modal coherence rules: when prosody AND emotion align, enforce stronger
# Format: (prosody_label, emotion_label) -> list of (bs_index, min_val, weight)
CROSS_MODAL_RULES: dict[tuple[str, str], list[tuple[int, float, float]]] = {
    ("energetic", "excited"): [
        (_BS_MOUTH_SMILE_L, 0.5, 1.5),   # Strong smile
        (_BS_MOUTH_SMILE_R, 0.5, 1.5),
        (_BS_EYE_WIDE_L, 0.4, 1.0),      # Wide eyes
        (_BS_EYE_WIDE_R, 0.4, 1.0),
        (_BS_JAW_OPEN, 0.3, 0.8),         # More open mouth
    ],
    ("energetic", "happy"): [
        (_BS_MOUTH_SMILE_L, 0.4, 1.2),
        (_BS_MOUTH_SMILE_R, 0.4, 1.2),
        (_BS_BROW_INNER_UP, 0.3, 0.8),
    ],
    ("calm", "thoughtful"): [
        (_BS_BROW_DOWN_L, 0.15, 0.6),
        (_BS_BROW_DOWN_R, 0.15, 0.6),
    ],
    ("emphatic", "emphatic"): [
        (_BS_BROW_INNER_UP, 0.4, 1.2),
        (_BS_JAW_OPEN, 0.3, 1.0),
        (_BS_EYE_WIDE_L, 0.3, 0.8),
        (_BS_EYE_WIDE_R, 0.3, 0.8),
    ],
    ("questioning", "concerned"): [
        (_BS_BROW_INNER_UP, 0.3, 0.8),
    ],
}


class MeaningAwareLoss(nn.Module):
    """Three-component loss function for meaning-aligned training.

    1. Geometric loss: MSE on FLAME expression params (keeps face accurate)
    2. Semantic consistency: when emotion=happy, blendshapes must smile
    3. Cross-modal coherence: when prosody+emotion align, enforce stronger

    The semantic and cross-modal losses use soft hinge penalties:
    if blendshape[i] < required_min, penalty = weight * (required_min - bs[i])^2
    """

    def __init__(
        self,
        geometric_weight: float = 1.0,
        semantic_weight: float = 0.3,
        cross_modal_weight: float = 0.2,
        temporal_weight: float = 0.05,
    ) -> None:
        super().__init__()
        self.geometric_weight = geometric_weight
        self.semantic_weight = semantic_weight
        self.cross_modal_weight = cross_modal_weight
        self.temporal_weight = temporal_weight
        self.mse = nn.MSELoss()

    def forward(
        self,
        predicted_bs: torch.Tensor,
        gt_flame: torch.Tensor,
        emotion_idx: torch.Tensor,
        prosody_idx: torch.Tensor,
        emotion_probs: torch.Tensor,
        prev_bs: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, dict[str, float]]:
        """Compute the meaning-aware loss.

        Args:
            predicted_bs: (B, 52) predicted blendshapes.
            gt_flame: (B, 100) ground truth FLAME expression.
            emotion_idx: (B,) emotion label indices.
            prosody_idx: (B,) prosody label indices.
            emotion_probs: (B, n_emotions) soft emotion probabilities.
            prev_bs: (B, 52) previous frame's blendshapes for temporal smoothness.

        Returns:
            (total_loss, loss_dict) with breakdown for logging.
        """
        B = predicted_bs.shape[0]
        device = predicted_bs.device

        # 1. Geometric loss: MSE on first 52 FLAME params (mapped to blendshapes)
        # FLAME exp params are [-12, +12] range; our blendshapes are [0, 1] sigmoid
        # We compare against a normalized version of FLAME
        gt_normalized = torch.sigmoid(gt_flame[:, :52] * 0.2)
        loss_geo = self.mse(predicted_bs, gt_normalized)

        # 2. Semantic consistency loss
        loss_semantic = self._semantic_consistency_loss(
            predicted_bs, emotion_idx, emotion_probs, device,
        )

        # 3. Cross-modal coherence loss
        loss_cross = self._cross_modal_coherence_loss(
            predicted_bs, emotion_idx, prosody_idx, device,
        )

        # 4. Temporal smoothness loss
        loss_temporal = torch.tensor(0.0, device=device)
        if prev_bs is not None and prev_bs.shape[0] == B:
            loss_temporal = self.mse(predicted_bs, prev_bs)

        # Combine
        total = (
            self.geometric_weight * loss_geo
            + self.semantic_weight * loss_semantic
            + self.cross_modal_weight * loss_cross
            + self.temporal_weight * loss_temporal
        )

        breakdown = {
            "geometric": loss_geo.item(),
            "semantic": loss_semantic.item(),
            "cross_modal": loss_cross.item(),
            "temporal": loss_temporal.item(),
            "total": total.item(),
        }

        return total, breakdown

    def _semantic_consistency_loss(
        self,
        bs: torch.Tensor,
        emotion_idx: torch.Tensor,
        emotion_probs: torch.Tensor,
        device: torch.device,
    ) -> torch.Tensor:
        """Enforce that blendshapes match emotional meaning.

        Uses soft hinge: penalty when blendshape falls below required minimum.
        Weighted by the emotion probability (soft label), so uncertain
        classifications contribute less to the loss.
        """
        B = bs.shape[0]
        loss = torch.tensor(0.0, device=device)
        n_rules = 0

        for emo_label, rules in EMOTION_BLENDSHAPE_RULES.items():
            emo_idx = EMOTION_LABELS.index(emo_label)
            # Get probability of this emotion for each sample in batch
            prob = emotion_probs[:, emo_idx]  # (B,)

            for bs_idx, min_val, weight in rules:
                # Soft hinge: penalize when bs[i] < min_val
                shortfall = F.relu(min_val - bs[:, bs_idx])  # (B,)
                # Weight by emotion probability and rule weight
                penalty = weight * prob * shortfall ** 2
                loss = loss + penalty.mean()
                n_rules += 1

        if n_rules > 0:
            loss = loss / n_rules

        return loss

    def _cross_modal_coherence_loss(
        self,
        bs: torch.Tensor,
        emotion_idx: torch.Tensor,
        prosody_idx: torch.Tensor,
        device: torch.device,
    ) -> torch.Tensor:
        """Enforce cross-modal alignment between prosody and emotion.

        When prosody says "energetic" AND emotion says "excited",
        the blendshapes must be more intense than either alone.
        """
        B = bs.shape[0]
        loss = torch.tensor(0.0, device=device)
        n_rules = 0

        for (pro_label, emo_label), rules in CROSS_MODAL_RULES.items():
            pro_idx = PROSODY_LABELS.index(pro_label)
            emo_idx_val = EMOTION_LABELS.index(emo_label)

            # Binary mask for samples matching both labels
            mask = (prosody_idx == pro_idx) & (emotion_idx == emo_idx_val)
            mask_float = mask.float()

            if mask_float.sum() < 1:
                continue

            for bs_idx, min_val, weight in rules:
                shortfall = F.relu(min_val - bs[:, bs_idx])
                penalty = weight * mask_float * shortfall ** 2
                loss = loss + penalty.sum() / max(mask_float.sum(), 1.0)
                n_rules += 1

        if n_rules > 0:
            loss = loss / n_rules

        return loss


# ---------------------------------------------------------------------------
# Meaning Trainer
# ---------------------------------------------------------------------------
@dataclass
class TrainingConfig:
    """Configuration for meaning-aware training."""
    npz_path: str = ""
    save_dir: str = ""
    clone_name: str = "santa"
    epochs: int = 500
    batch_size: int = 64
    lr: float = 5e-4
    device: str = "cuda"
    geometric_weight: float = 1.0
    semantic_weight: float = 0.3
    cross_modal_weight: float = 0.2
    temporal_weight: float = 0.05
    use_constellation: bool = True
    num_workers: int = 0


def train_meaning_aware(config: TrainingConfig) -> dict:
    """Train the clone model with meaning-aware loss.

    End-to-end pipeline:
    1. Load embeddings from NPZ
    2. Extract semantic state labels
    3. Build meaning-aligned dataset
    4. Train with geometric + semantic + cross-modal loss
    5. Save model + constellation + metadata

    Args:
        config: Training configuration.

    Returns:
        Dict with training results.
    """
    t_start = time.time()
    device = config.device if torch.cuda.is_available() else "cpu"

    # Step 1: Build dataset
    logger.info("[1/4] Building meaning-aligned dataset...")
    dataset = MeaningAlignedDataset(config.npz_path)

    loader = DataLoader(
        dataset,
        batch_size=config.batch_size,
        shuffle=True,
        drop_last=False,
        num_workers=config.num_workers,
        pin_memory=(device == "cuda"),
    )

    # Step 2: Create model with all embedding spaces
    logger.info("[2/4] Creating model...")
    from phoenix.clone.model import CloneModel

    embedding_dims = {
        "visual": 1152,
        "semantic": 768,
        "prosody": 12,
        "emotion_scalars": 3,
    }
    model = CloneModel(
        embedding_dims=embedding_dims,
        shared_dim=512,
        num_latents=128,
        num_layers=4,
    )
    model = model.to(device)
    logger.info("Model: %.1fM params on %s", model.param_count / 1e6, device)

    # Step 3: Compute and fuse North Star constellation
    logger.info("[3/4] Computing North Star constellation...")
    from phoenix.clone.north_star import compute_north_stars

    # Build training embeddings for North Star computation
    training_embs = {
        "visual": dataset.vis_emb,
        "semantic": dataset.sem_emb,
        "prosody": dataset.pro_data,
        "emotion_scalars": dataset.emo_data,
    }
    global_centroids = compute_north_stars(training_embs)
    model.fuse_north_stars(global_centroids)
    logger.info("North Stars fused: %d modalities", len(global_centroids))

    # Step 4: Train
    logger.info("[4/4] Training with meaning-aware loss...")
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(
        optimizer, T_0=100, T_mult=2,
    )

    loss_fn = MeaningAwareLoss(
        geometric_weight=config.geometric_weight,
        semantic_weight=config.semantic_weight,
        cross_modal_weight=config.cross_modal_weight,
        temporal_weight=config.temporal_weight,
    )

    # North Star contrastive loss
    from phoenix.clone.north_star import NorthStarContrastiveLoss
    contrastive_loss = NorthStarContrastiveLoss(temperature=0.07)
    star_tensors = {
        name: torch.tensor(vec, device=device)
        for name, vec in global_centroids.items()
    }

    best_loss = float("inf")
    best_state = None
    loss_history: list[dict] = []
    t_train = time.time()

    for epoch in range(config.epochs):
        model.train()
        epoch_losses = {
            "geometric": 0.0, "semantic": 0.0,
            "cross_modal": 0.0, "temporal": 0.0,
            "contrastive": 0.0, "total": 0.0,
        }
        n_batches = 0
        prev_bs = None

        for batch in loader:
            optimizer.zero_grad()

            # Move to device
            embeddings = {
                "visual": batch["visual"].to(device),
                "semantic": batch["semantic"].to(device),
                "prosody": batch["prosody"].to(device),
                "emotion_scalars": batch["emotion_scalars"].to(device),
            }
            flame_gt = batch["flame_exp"].to(device)
            emo_idx = batch["emotion_idx"].to(device)
            pro_idx = batch["prosody_idx"].to(device)
            emo_probs = batch["emotion_probs"].to(device)

            # Forward
            out = model(
                embeddings=embeddings,
                prosody_scalars=batch["prosody"].to(device),
            )

            # Meaning-aware loss
            loss, breakdown = loss_fn(
                out["blendshapes"], flame_gt,
                emo_idx, pro_idx, emo_probs,
                prev_bs=prev_bs,
            )

            # Contrastive loss vs North Stars
            loss_contrast = torch.tensor(0.0, device=device)
            if "_pooled" in out and model.reverse_projections:
                projections = model.project_to_embedding_spaces(out["_pooled"])
                loss_contrast = contrastive_loss(projections, star_tensors)
                loss = loss + 0.1 * loss_contrast

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            # Track losses
            for k, v in breakdown.items():
                epoch_losses[k] += v
            epoch_losses["contrastive"] += loss_contrast.item()
            epoch_losses["total"] += loss.item()
            n_batches += 1

            # Store for temporal loss
            prev_bs = out["blendshapes"].detach()

        scheduler.step()

        # Average losses
        avg = {k: v / max(n_batches, 1) for k, v in epoch_losses.items()}
        loss_history.append(avg)

        if avg["total"] < best_loss:
            best_loss = avg["total"]
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        if (epoch + 1) % 50 == 0 or epoch == 0:
            elapsed = time.time() - t_train
            logger.info(
                "Epoch %d/%d: total=%.5f (geo=%.5f, sem=%.5f, cross=%.5f, "
                "contrast=%.5f) lr=%.2e, %.1fs",
                epoch + 1, config.epochs,
                avg["total"], avg["geometric"], avg["semantic"],
                avg["cross_modal"], avg["contrastive"],
                scheduler.get_last_lr()[0], elapsed,
            )

    train_time = time.time() - t_train
    logger.info("Training complete: %.1fs, best_loss=%.6f", train_time, best_loss)

    # Restore best model
    if best_state is not None:
        model.load_state_dict(best_state)

    # Save
    save_dir = config.save_dir or os.path.expanduser(
        f"~/.clipcannon/models/{config.clone_name}"
    )
    os.makedirs(save_dir, exist_ok=True)
    model_path = os.path.join(save_dir, "clone_model.pt")

    save_data = {
        "model_state_dict": model.state_dict(),
        "config": {
            "clone_name": config.clone_name,
            "embedding_dims": embedding_dims,
            "param_count": model.param_count,
            "training_samples": len(dataset),
            "epochs": config.epochs,
            "best_loss": best_loss,
            "train_time_s": train_time,
            "loss_weights": {
                "geometric": config.geometric_weight,
                "semantic": config.semantic_weight,
                "cross_modal": config.cross_modal_weight,
                "temporal": config.temporal_weight,
            },
            "pipeline": "meaning_aware_v1",
        },
        "global_centroids": {k: v.tolist() for k, v in global_centroids.items()},
        "meaning_labels": {
            "emotion": EMOTION_LABELS,
            "prosody": PROSODY_LABELS,
            "context": CONTEXT_LABELS,
            "visual": VISUAL_LABELS,
        },
        "loss_history": loss_history,
    }
    torch.save(save_data, model_path)
    logger.info("Model saved: %s", model_path)

    total_time = time.time() - t_start
    result = {
        "clone_name": config.clone_name,
        "training_samples": len(dataset),
        "param_count": model.param_count,
        "best_loss": best_loss,
        "train_time_s": round(train_time, 1),
        "total_time_s": round(total_time, 1),
        "model_path": model_path,
        "loss_components": loss_history[-1] if loss_history else {},
    }
    logger.info("=== Clone '%s' trained in %.1fs ===", config.clone_name, total_time)
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Meaning-Aware Clone Trainer")
    parser.add_argument(
        "--npz", type=str,
        default="~/.clipcannon/models/santa/embeddings/all_embeddings.npz",
        help="Path to all_embeddings.npz",
    )
    parser.add_argument("--name", type=str, default="santa", help="Clone name")
    parser.add_argument("--epochs", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=5e-4)
    parser.add_argument("--save-dir", type=str, default="")
    parser.add_argument(
        "--semantic-weight", type=float, default=0.3,
        help="Weight for semantic consistency loss",
    )
    parser.add_argument(
        "--cross-modal-weight", type=float, default=0.2,
        help="Weight for cross-modal coherence loss",
    )
    args = parser.parse_args()

    config = TrainingConfig(
        npz_path=os.path.expanduser(args.npz),
        save_dir=args.save_dir,
        clone_name=args.name,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        semantic_weight=args.semantic_weight,
        cross_modal_weight=args.cross_modal_weight,
    )

    result = train_meaning_aware(config)

    print(f"\n{'=' * 50}")
    print(f"  Clone '{result['clone_name']}' trained successfully!")
    print(f"  Samples: {result['training_samples']}")
    print(f"  Parameters: {result['param_count']:,}")
    print(f"  Best loss: {result['best_loss']:.6f}")
    print(f"  Loss breakdown: {result['loss_components']}")
    print(f"  Time: {result['total_time_s']}s")
    print(f"  Model: {result['model_path']}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
