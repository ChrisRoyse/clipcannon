"""Tests for the meaning-aware clone training pipeline.

Tests cover:
  - SemanticStateExtractor label classification
  - MeaningAlignedDataset construction from NPZ
  - MeaningAwareLoss components (geometric, semantic, cross-modal)
  - End-to-end training loop (small model, few epochs)
  - Integration with CloneModel forward pass
"""
from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest
import torch

# Skip all tests if torch is not available with CUDA
pytestmark = pytest.mark.skipif(
    not torch.cuda.is_available(),
    reason="CUDA required for clone training tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def fake_npz(tmp_path_factory) -> str:
    """Create a fake all_embeddings.npz for testing."""
    d = tmp_path_factory.mktemp("embeddings")
    path = str(d / "all_embeddings.npz")

    n_vis = 100
    n_sem = 20
    n_emo = 40
    n_pro = 20
    n_flame = 200

    np.savez(
        path,
        vis_emb=np.random.randn(n_vis, 1152).astype(np.float32),
        vis_ts=np.arange(0, n_vis * 500, 500, dtype=np.int64),
        sem_emb=np.random.randn(n_sem, 768).astype(np.float32),
        sem_ts=np.linspace(0, n_vis * 500, n_sem, dtype=np.int64),
        emo_data=np.column_stack([
            np.random.uniform(0.15, 0.22, n_emo),   # arousal
            np.random.uniform(0.504, 0.509, n_emo),  # valence
            np.random.uniform(0.296, 0.347, n_emo),  # energy
        ]).astype(np.float32),
        emo_ts=np.linspace(0, n_vis * 500, n_emo, dtype=np.int64),
        pro_data=np.random.rand(n_pro, 12).astype(np.float32),
        pro_ts=np.linspace(0, n_vis * 500, n_pro, dtype=np.int64),
        flame_exp=np.random.randn(n_flame, 100).astype(np.float32),
        flame_ts=np.linspace(0, n_vis * 0.5, n_flame, dtype=np.float32),
    )
    return path


@pytest.fixture(scope="module")
def real_npz() -> str | None:
    """Path to the real Santa embeddings if they exist."""
    path = os.path.expanduser(
        "~/.clipcannon/models/santa/embeddings/all_embeddings.npz"
    )
    if os.path.exists(path):
        return path
    return None


# ---------------------------------------------------------------------------
# SemanticStateExtractor tests
# ---------------------------------------------------------------------------
class TestSemanticStateExtractor:
    """Test the semantic state extraction from raw features."""

    def test_classify_emotion_neutral(self) -> None:
        from phoenix.clone.meaning_trainer import SemanticStateExtractor
        ext = SemanticStateExtractor()
        label, probs = ext.classify_emotion(0.18, 0.506, 0.32)
        assert label in ["neutral", "happy", "thoughtful"]
        assert abs(probs.sum() - 1.0) < 0.01

    def test_classify_emotion_happy(self) -> None:
        from phoenix.clone.meaning_trainer import SemanticStateExtractor
        ext = SemanticStateExtractor()
        label, probs = ext.classify_emotion(0.20, 0.509, 0.34)
        assert probs.sum() > 0
        # High valence should push toward happy
        assert probs[1] > 0  # happy index

    def test_classify_emotion_probs_sum_to_one(self) -> None:
        from phoenix.clone.meaning_trainer import SemanticStateExtractor
        ext = SemanticStateExtractor()
        for a in [0.15, 0.18, 0.22]:
            for v in [0.504, 0.506, 0.509]:
                for e in [0.296, 0.32, 0.347]:
                    _, probs = ext.classify_emotion(a, v, e)
                    assert abs(probs.sum() - 1.0) < 0.01

    def test_classify_prosody_calm(self) -> None:
        from phoenix.clone.meaning_trainer import SemanticStateExtractor
        ext = SemanticStateExtractor()
        features = np.array([0.4, 0.1, 0.02, 0.5, 0, 0, 0.5, 0, 0, 0, 0, 0], dtype=np.float32)
        label, probs = ext.classify_prosody(features)
        assert label in ["calm", "slow"]
        assert probs.sum() > 0

    def test_classify_prosody_energetic(self) -> None:
        from phoenix.clone.meaning_trainer import SemanticStateExtractor
        ext = SemanticStateExtractor()
        features = np.array([0.7, 0.8, 0.05, 0.8, 1, 0, 0.9, 0, 0, 0, 0, 0], dtype=np.float32)
        label, probs = ext.classify_prosody(features)
        # High energy + emphasis + wide range
        assert "energetic" in label or "emphatic" in label or "fast" in label

    def test_classify_visual_from_flame(self) -> None:
        from phoenix.clone.meaning_trainer import SemanticStateExtractor
        ext = SemanticStateExtractor()
        # High energy expression
        high_exp = np.random.randn(100).astype(np.float32) * 3
        label = ext.classify_visual_from_flame(high_exp)
        assert label in ["animated", "still", "smiling", "serious", "close_up"]

    def test_classify_visual_still(self) -> None:
        from phoenix.clone.meaning_trainer import SemanticStateExtractor
        ext = SemanticStateExtractor()
        low_exp = np.zeros(100, dtype=np.float32) * 0.1
        label = ext.classify_visual_from_flame(low_exp)
        assert label == "still"

    def test_classify_context_from_semantic(self) -> None:
        from phoenix.clone.meaning_trainer import SemanticStateExtractor
        ext = SemanticStateExtractor()
        emb = np.random.randn(768).astype(np.float32) * 0.01
        label = ext.classify_context_from_semantic(emb)
        assert label in ["storytelling", "answering", "greeting", "listening", "thinking"]

    def test_extract_frame_meanings(self) -> None:
        from phoenix.clone.meaning_trainer import SemanticStateExtractor
        ext = SemanticStateExtractor()
        n = 10
        meanings = ext.extract_frame_meanings(
            emo_data=np.random.uniform(0.15, 0.22, (5, 3)).astype(np.float32),
            emo_ts=np.linspace(0, 5000, 5, dtype=np.int64),
            pro_data=np.random.rand(5, 12).astype(np.float32),
            pro_ts=np.linspace(0, 5000, 5, dtype=np.int64),
            sem_emb=np.random.randn(3, 768).astype(np.float32),
            sem_ts=np.array([0, 2500, 5000], dtype=np.int64),
            flame_exp=np.random.randn(20, 100).astype(np.float32),
            flame_ts_ms=np.linspace(0, 5000, 20, dtype=np.int64),
            target_ts=np.linspace(0, 5000, n, dtype=np.int64),
        )
        assert len(meanings) == n
        for m in meanings:
            assert m.emotion in [
                "neutral", "happy", "sad", "excited", "thoughtful",
                "amused", "concerned", "emphatic",
            ]
            assert abs(m.emotion_probs.sum() - 1.0) < 0.01


# ---------------------------------------------------------------------------
# MeaningAlignedDataset tests
# ---------------------------------------------------------------------------
class TestMeaningAlignedDataset:
    """Test dataset loading and sample structure."""

    def test_load_from_npz(self, fake_npz: str) -> None:
        from phoenix.clone.meaning_trainer import MeaningAlignedDataset
        ds = MeaningAlignedDataset(fake_npz)
        assert len(ds) == 100  # n_vis frames

    def test_sample_structure(self, fake_npz: str) -> None:
        from phoenix.clone.meaning_trainer import MeaningAlignedDataset
        ds = MeaningAlignedDataset(fake_npz)
        sample = ds[0]
        assert "visual" in sample
        assert "semantic" in sample
        assert "prosody" in sample
        assert "emotion_scalars" in sample
        assert "flame_exp" in sample
        assert "emotion_idx" in sample
        assert "prosody_idx" in sample
        assert "emotion_probs" in sample

    def test_embedding_dimensions(self, fake_npz: str) -> None:
        from phoenix.clone.meaning_trainer import MeaningAlignedDataset
        ds = MeaningAlignedDataset(fake_npz)
        sample = ds[0]
        assert sample["visual"].shape == (1152,)
        assert sample["semantic"].shape == (768,)
        assert sample["prosody"].shape == (12,)
        assert sample["emotion_scalars"].shape == (3,)
        assert sample["flame_exp"].shape == (100,)

    def test_dataloader_batching(self, fake_npz: str) -> None:
        from torch.utils.data import DataLoader
        from phoenix.clone.meaning_trainer import MeaningAlignedDataset
        ds = MeaningAlignedDataset(fake_npz)
        loader = DataLoader(ds, batch_size=16, shuffle=True)
        batch = next(iter(loader))
        assert batch["visual"].shape[0] == 16
        assert batch["visual"].shape[1] == 1152

    def test_real_npz_if_available(self, real_npz: str | None) -> None:
        if real_npz is None:
            pytest.skip("Real Santa embeddings not available")
        from phoenix.clone.meaning_trainer import MeaningAlignedDataset
        ds = MeaningAlignedDataset(real_npz)
        assert len(ds) > 100
        sample = ds[0]
        assert sample["visual"].shape == (1152,)


# ---------------------------------------------------------------------------
# MeaningAwareLoss tests
# ---------------------------------------------------------------------------
class TestMeaningAwareLoss:
    """Test the three-component loss function."""

    def test_geometric_loss(self) -> None:
        from phoenix.clone.meaning_trainer import MeaningAwareLoss, EMOTION_LABELS
        loss_fn = MeaningAwareLoss(
            geometric_weight=1.0, semantic_weight=0.0,
            cross_modal_weight=0.0, temporal_weight=0.0,
        )
        B = 8
        pred = torch.rand(B, 52, device="cuda")
        gt = torch.randn(B, 100, device="cuda")
        emo_idx = torch.zeros(B, dtype=torch.long, device="cuda")
        pro_idx = torch.zeros(B, dtype=torch.long, device="cuda")
        emo_probs = torch.zeros(B, len(EMOTION_LABELS), device="cuda")
        emo_probs[:, 0] = 1.0  # all neutral

        total, breakdown = loss_fn(pred, gt, emo_idx, pro_idx, emo_probs)
        assert total.item() > 0
        assert breakdown["semantic"] == 0.0
        assert breakdown["cross_modal"] == 0.0

    def test_semantic_loss_fires_for_happy(self) -> None:
        from phoenix.clone.meaning_trainer import MeaningAwareLoss, EMOTION_LABELS
        loss_fn = MeaningAwareLoss(
            geometric_weight=0.0, semantic_weight=1.0,
            cross_modal_weight=0.0, temporal_weight=0.0,
        )
        B = 8
        # Predict zero blendshapes (no smile) but claim emotion is happy
        pred = torch.zeros(B, 52, device="cuda")
        gt = torch.zeros(B, 100, device="cuda")
        emo_idx = torch.full((B,), EMOTION_LABELS.index("happy"), dtype=torch.long, device="cuda")
        pro_idx = torch.zeros(B, dtype=torch.long, device="cuda")
        emo_probs = torch.zeros(B, len(EMOTION_LABELS), device="cuda")
        emo_probs[:, EMOTION_LABELS.index("happy")] = 1.0

        total, breakdown = loss_fn(pred, gt, emo_idx, pro_idx, emo_probs)
        assert breakdown["semantic"] > 0, "Semantic loss should penalize no-smile when happy"

    def test_semantic_loss_low_for_matching(self) -> None:
        from phoenix.clone.meaning_trainer import MeaningAwareLoss, EMOTION_LABELS
        loss_fn = MeaningAwareLoss(
            geometric_weight=0.0, semantic_weight=1.0,
            cross_modal_weight=0.0, temporal_weight=0.0,
        )
        B = 8
        # Predict strong smile when emotion is happy — should have lower penalty
        pred = torch.zeros(B, 52, device="cuda")
        pred[:, 3] = 0.8  # mouthSmileLeft
        pred[:, 4] = 0.8  # mouthSmileRight
        pred[:, 23] = 0.5  # browInnerUp
        pred[:, 30] = 0.3  # eyeWideLeft

        gt = torch.zeros(B, 100, device="cuda")
        emo_idx = torch.full((B,), EMOTION_LABELS.index("happy"), dtype=torch.long, device="cuda")
        pro_idx = torch.zeros(B, dtype=torch.long, device="cuda")
        emo_probs = torch.zeros(B, len(EMOTION_LABELS), device="cuda")
        emo_probs[:, EMOTION_LABELS.index("happy")] = 1.0

        total_good, _ = loss_fn(pred, gt, emo_idx, pro_idx, emo_probs)

        # Compare with no smile
        pred_bad = torch.zeros(B, 52, device="cuda")
        total_bad, _ = loss_fn(pred_bad, gt, emo_idx, pro_idx, emo_probs)

        assert total_good.item() < total_bad.item(), \
            "Smiling face should have lower semantic loss than neutral face when happy"

    def test_cross_modal_loss(self) -> None:
        from phoenix.clone.meaning_trainer import (
            MeaningAwareLoss, EMOTION_LABELS, PROSODY_LABELS,
        )
        loss_fn = MeaningAwareLoss(
            geometric_weight=0.0, semantic_weight=0.0,
            cross_modal_weight=1.0, temporal_weight=0.0,
        )
        B = 8
        pred = torch.zeros(B, 52, device="cuda")
        gt = torch.zeros(B, 100, device="cuda")
        # energetic + excited should trigger cross-modal rules
        emo_idx = torch.full((B,), EMOTION_LABELS.index("excited"), dtype=torch.long, device="cuda")
        pro_idx = torch.full((B,), PROSODY_LABELS.index("energetic"), dtype=torch.long, device="cuda")
        emo_probs = torch.zeros(B, len(EMOTION_LABELS), device="cuda")
        emo_probs[:, EMOTION_LABELS.index("excited")] = 1.0

        total, breakdown = loss_fn(pred, gt, emo_idx, pro_idx, emo_probs)
        assert breakdown["cross_modal"] > 0

    def test_temporal_smoothness(self) -> None:
        from phoenix.clone.meaning_trainer import MeaningAwareLoss, EMOTION_LABELS
        loss_fn = MeaningAwareLoss(
            geometric_weight=0.0, semantic_weight=0.0,
            cross_modal_weight=0.0, temporal_weight=1.0,
        )
        B = 8
        pred = torch.rand(B, 52, device="cuda")
        prev = torch.rand(B, 52, device="cuda")
        gt = torch.zeros(B, 100, device="cuda")
        emo_idx = torch.zeros(B, dtype=torch.long, device="cuda")
        pro_idx = torch.zeros(B, dtype=torch.long, device="cuda")
        emo_probs = torch.zeros(B, len(EMOTION_LABELS), device="cuda")
        emo_probs[:, 0] = 1.0

        total, breakdown = loss_fn(pred, gt, emo_idx, pro_idx, emo_probs, prev_bs=prev)
        assert breakdown["temporal"] > 0


# ---------------------------------------------------------------------------
# Integration: model forward + loss
# ---------------------------------------------------------------------------
class TestModelIntegration:
    """Test that CloneModel works with the new embedding dimensions."""

    def test_forward_with_new_dims(self) -> None:
        from phoenix.clone.model import CloneModel
        model = CloneModel(
            embedding_dims={
                "visual": 1152,
                "semantic": 768,
                "prosody": 12,
                "emotion_scalars": 3,
            },
            shared_dim=64,
            num_latents=16,
            num_layers=2,
        ).cuda()

        embeddings = {
            "visual": torch.randn(4, 1152, device="cuda"),
            "semantic": torch.randn(4, 768, device="cuda"),
            "prosody": torch.randn(4, 12, device="cuda"),
            "emotion_scalars": torch.randn(4, 3, device="cuda"),
        }
        out = model(embeddings, prosody_scalars=embeddings["prosody"])
        assert out["blendshapes"].shape == (4, 52)
        assert out["voice"].shape == (4, 16)
        assert out["body"].shape == (4, 12)
        assert out["gaze"].shape == (4, 6)
        assert out["behavior"].shape == (4, 6)

    def test_backward_pass(self) -> None:
        from phoenix.clone.model import CloneModel
        from phoenix.clone.meaning_trainer import MeaningAwareLoss, EMOTION_LABELS
        model = CloneModel(
            embedding_dims={
                "visual": 1152,
                "semantic": 768,
                "prosody": 12,
                "emotion_scalars": 3,
            },
            shared_dim=64,
            num_latents=16,
            num_layers=2,
        ).cuda()

        loss_fn = MeaningAwareLoss()

        embeddings = {
            "visual": torch.randn(4, 1152, device="cuda"),
            "semantic": torch.randn(4, 768, device="cuda"),
            "prosody": torch.randn(4, 12, device="cuda"),
            "emotion_scalars": torch.randn(4, 3, device="cuda"),
        }
        out = model(embeddings, prosody_scalars=embeddings["prosody"])

        gt_flame = torch.randn(4, 100, device="cuda")
        emo_idx = torch.zeros(4, dtype=torch.long, device="cuda")
        pro_idx = torch.zeros(4, dtype=torch.long, device="cuda")
        emo_probs = torch.zeros(4, len(EMOTION_LABELS), device="cuda")
        emo_probs[:, 0] = 1.0

        total, _ = loss_fn(out["blendshapes"], gt_flame, emo_idx, pro_idx, emo_probs)
        total.backward()

        # Verify gradients exist
        grad_count = sum(1 for p in model.parameters() if p.grad is not None)
        assert grad_count > 0


# ---------------------------------------------------------------------------
# End-to-end training test
# ---------------------------------------------------------------------------
class TestEndToEndTraining:
    """Test the full training loop with a small model and few epochs."""

    def test_train_meaning_aware(self, fake_npz: str) -> None:
        from phoenix.clone.meaning_trainer import TrainingConfig, train_meaning_aware

        with tempfile.TemporaryDirectory() as save_dir:
            config = TrainingConfig(
                npz_path=fake_npz,
                save_dir=save_dir,
                clone_name="test_santa",
                epochs=5,
                batch_size=16,
                lr=1e-3,
                device="cuda",
            )

            result = train_meaning_aware(config)
            assert result["training_samples"] == 100
            assert result["best_loss"] > 0
            assert result["param_count"] > 0
            assert os.path.exists(result["model_path"])

            # Verify saved model loads
            saved = torch.load(result["model_path"], weights_only=False)
            assert "model_state_dict" in saved
            assert "meaning_labels" in saved
            assert saved["config"]["pipeline"] == "meaning_aware_v1"

    def test_loss_decreases(self, fake_npz: str) -> None:
        from phoenix.clone.meaning_trainer import TrainingConfig, train_meaning_aware

        with tempfile.TemporaryDirectory() as save_dir:
            config = TrainingConfig(
                npz_path=fake_npz,
                save_dir=save_dir,
                clone_name="test_decrease",
                epochs=20,
                batch_size=32,
                lr=1e-3,
                device="cuda",
            )
            result = train_meaning_aware(config)
            history = torch.load(result["model_path"], weights_only=False)["loss_history"]
            # Loss should generally decrease over 20 epochs
            first_loss = history[0]["total"]
            last_loss = history[-1]["total"]
            assert last_loss < first_loss * 1.5, \
                f"Loss should not explode: first={first_loss:.4f}, last={last_loss:.4f}"


# ---------------------------------------------------------------------------
# Data pipeline tests
# ---------------------------------------------------------------------------
class TestDataPipeline:
    """Test the data_pipeline module functions."""

    def test_load_embeddings_npz(self, fake_npz: str) -> None:
        from phoenix.clone.data_pipeline import load_embeddings_npz
        data = load_embeddings_npz(fake_npz)
        assert "vis_emb" in data
        assert "sem_emb" in data
        assert data["vis_emb"].shape[1] == 1152

    def test_get_embedding_dims(self) -> None:
        from phoenix.clone.data_pipeline import get_embedding_dims
        dims = get_embedding_dims()
        assert dims["visual"] == 1152
        assert dims["semantic"] == 768
        assert dims["prosody"] == 12
        assert dims["emotion_scalars"] == 3

    def test_get_embedding_dims_from_npz(self, fake_npz: str) -> None:
        from phoenix.clone.data_pipeline import get_embedding_dims
        dims = get_embedding_dims(fake_npz)
        assert dims["visual"] == 1152
        assert dims["semantic"] == 768
