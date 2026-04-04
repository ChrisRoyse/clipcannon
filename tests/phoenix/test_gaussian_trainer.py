"""Tests for Gaussian avatar trainer module.

Tests SSIM loss, data loading, and basic training loop initialization.
"""
from __future__ import annotations

import pytest
import torch


class TestSSIMloss:
    def test_identical_images_zero_loss(self):
        from phoenix.render.gaussian_trainer import _ssim_loss
        img = torch.rand(1, 3, 64, 64)
        loss = _ssim_loss(img, img)
        assert loss.item() == pytest.approx(0.0, abs=0.01)

    def test_different_images_positive_loss(self):
        from phoenix.render.gaussian_trainer import _ssim_loss
        img1 = torch.zeros(1, 3, 64, 64)
        img2 = torch.ones(1, 3, 64, 64)
        loss = _ssim_loss(img1, img2)
        assert loss.item() > 0.5

    def test_batch_dimension(self):
        from phoenix.render.gaussian_trainer import _ssim_loss
        img1 = torch.rand(4, 3, 32, 32)
        img2 = torch.rand(4, 3, 32, 32)
        loss = _ssim_loss(img1, img2)
        assert loss.shape == ()  # Scalar
        assert loss.item() > 0.0

    def test_gradient_flows(self):
        from phoenix.render.gaussian_trainer import _ssim_loss
        img1 = torch.rand(1, 3, 32, 32, requires_grad=True)
        img2 = torch.rand(1, 3, 32, 32)
        loss = _ssim_loss(img1, img2)
        loss.backward()
        assert img1.grad is not None
        assert img1.grad.abs().sum().item() > 0


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
class TestSSIMlossGPU:
    def test_gpu_identical_images(self):
        from phoenix.render.gaussian_trainer import _ssim_loss
        img = torch.rand(1, 3, 64, 64, device="cuda")
        loss = _ssim_loss(img, img)
        assert loss.item() == pytest.approx(0.0, abs=0.01)
