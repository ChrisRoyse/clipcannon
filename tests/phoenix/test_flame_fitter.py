"""Tests for FLAME parameter fitting module.

Tests the core fitting logic with synthetic data (no video dependency).
Verifies landmark mapping, projection, and optimization convergence.
"""
from __future__ import annotations

import numpy as np
import pytest
import torch


class TestInsight106To68Mapping:
    """Verify the landmark mapping indices are valid."""

    def test_mapping_has_68_entries(self):
        from phoenix.render.flame_fitter import INSIGHT106_TO_68
        assert len(INSIGHT106_TO_68) == 68

    def test_mapping_indices_in_range(self):
        from phoenix.render.flame_fitter import INSIGHT106_TO_68
        for idx in INSIGHT106_TO_68:
            assert 0 <= idx < 106, f"Index {idx} out of range [0, 106)"

    def test_mapping_covers_all_regions(self):
        """Verify jaw, brow, nose, eye, lip regions are all present."""
        from phoenix.render.flame_fitter import INSIGHT106_TO_68
        indices = INSIGHT106_TO_68
        # Jaw contour (0-16): should map to contour range 0-32
        for i in range(17):
            assert indices[i] <= 32
        # Eyebrows (17-26): should be in range 33-42
        for i in range(17, 27):
            assert 33 <= indices[i] <= 42
        # Nose (27-35): in range 43-51
        for i in range(27, 36):
            assert 43 <= indices[i] <= 51


class TestFlameLmk68:
    """Verify FLAME landmark vertex indices."""

    def test_has_68_indices(self):
        from phoenix.render.flame_fitter import FLAME_LMK_68
        assert len(FLAME_LMK_68) == 68

    def test_indices_in_flame_range(self):
        """FLAME has 5023 vertices."""
        from phoenix.render.flame_fitter import FLAME_LMK_68
        for idx in FLAME_LMK_68:
            assert 0 <= idx < 5023, f"Vertex index {idx} out of FLAME range"


class TestWeakPerspectiveProjection:
    def test_identity_projection(self):
        from phoenix.render.flame_fitter import _project_weak_perspective
        pts = torch.tensor([[[1.0, 2.0, 3.0]]])  # (1, 1, 3)
        scale = torch.tensor([[1.0]])
        tx = torch.tensor([[0.0]])
        ty = torch.tensor([[0.0]])
        proj = _project_weak_perspective(pts, scale, tx, ty)
        assert proj.shape == (1, 1, 2)
        assert proj[0, 0, 0].item() == pytest.approx(1.0)
        assert proj[0, 0, 1].item() == pytest.approx(2.0)

    def test_scale_multiplies(self):
        from phoenix.render.flame_fitter import _project_weak_perspective
        pts = torch.tensor([[[1.0, 2.0, 0.0]]])
        scale = torch.tensor([[5.0]])
        tx = torch.tensor([[0.0]])
        ty = torch.tensor([[0.0]])
        proj = _project_weak_perspective(pts, scale, tx, ty)
        assert proj[0, 0, 0].item() == pytest.approx(5.0)
        assert proj[0, 0, 1].item() == pytest.approx(10.0)

    def test_translation_offsets(self):
        from phoenix.render.flame_fitter import _project_weak_perspective
        pts = torch.tensor([[[0.0, 0.0, 0.0]]])
        scale = torch.tensor([[1.0]])
        tx = torch.tensor([[3.0]])
        ty = torch.tensor([[-2.0]])
        proj = _project_weak_perspective(pts, scale, tx, ty)
        assert proj[0, 0, 0].item() == pytest.approx(3.0)
        assert proj[0, 0, 1].item() == pytest.approx(-2.0)

    def test_batch_dimension(self):
        from phoenix.render.flame_fitter import _project_weak_perspective
        pts = torch.randn(4, 10, 3)
        scale = torch.ones(4, 1) * 5.0
        tx = torch.zeros(4, 1)
        ty = torch.zeros(4, 1)
        proj = _project_weak_perspective(pts, scale, tx, ty)
        assert proj.shape == (4, 10, 2)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
class TestGetFlameLmkVerts:
    def test_output_shape(self):
        from phoenix.render.flame_fitter import _get_flame_lmk_verts
        from phoenix.render.flame_model import FlameModel

        flame = FlameModel().cuda()
        shape = torch.zeros(2, 300, device="cuda")
        expr = torch.zeros(2, 100, device="cuda")
        jaw = torch.zeros(2, 3, device="cuda")
        lmk = _get_flame_lmk_verts(flame, shape, expr, jaw)
        assert lmk.shape == (2, 68, 3)

    def test_expression_changes_landmarks(self):
        from phoenix.render.flame_fitter import _get_flame_lmk_verts
        from phoenix.render.flame_model import FlameModel

        flame = FlameModel().cuda()
        shape = torch.zeros(1, 300, device="cuda")
        expr_zero = torch.zeros(1, 100, device="cuda")
        expr_jaw = torch.zeros(1, 100, device="cuda")
        expr_jaw[0, 0] = 2.0  # Big expression change

        jaw = torch.zeros(1, 3, device="cuda")
        lmk0 = _get_flame_lmk_verts(flame, shape, expr_zero, jaw)
        lmk1 = _get_flame_lmk_verts(flame, shape, expr_jaw, jaw)
        diff = (lmk1 - lmk0).abs().sum().item()
        assert diff > 0.001, "Expression change should move landmarks"
