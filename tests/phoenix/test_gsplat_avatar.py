"""Tests for the 3D Gaussian Splatting avatar pipeline.

Validates FLAME model loading, Gaussian binding, mesh deformation,
and gsplat rendering at 720p with performance benchmarks.
"""

from __future__ import annotations

import time

import numpy as np
import pytest
import torch

# Skip all tests if CUDA is not available
pytestmark = pytest.mark.skipif(
    not torch.cuda.is_available(),
    reason="CUDA required for Gaussian Splatting avatar tests",
)


@pytest.fixture(scope="module")
def device():
    return torch.device("cuda:0")


class TestFlameModel:
    """Test FLAME parametric head model."""

    def test_flame_loads(self, device):
        """FLAME model loads from clean numpy data."""
        from phoenix.render.flame_model import FlameModel, FlameModelConfig

        config = FlameModelConfig()
        model = FlameModel(config).to(device)

        assert model.num_vertices == 5023
        assert model.num_faces == 9976
        assert model.num_shape == 300
        assert model.num_exp == 100

    def test_flame_forward_neutral(self, device):
        """FLAME forward pass produces valid neutral mesh."""
        from phoenix.render.flame_model import FlameModel, FlameModelConfig

        model = FlameModel(FlameModelConfig()).to(device)

        shape = torch.zeros(1, 300, device=device)
        expr = torch.zeros(1, 100, device=device)
        verts = model(shape, expr)

        assert verts.shape == (1, 5023, 3)
        assert not torch.isnan(verts).any()
        assert not torch.isinf(verts).any()

        # Mesh should have reasonable extent (head is ~0.2m across)
        extent = verts.max() - verts.min()
        assert 0.05 < extent.item() < 2.0, f"Unexpected mesh extent: {extent}"

    def test_flame_expression_deforms(self, device):
        """Expression parameters actually change the mesh."""
        from phoenix.render.flame_model import FlameModel, FlameModelConfig

        model = FlameModel(FlameModelConfig()).to(device)

        shape = torch.zeros(1, 300, device=device)
        expr_neutral = torch.zeros(1, 100, device=device)
        expr_open_jaw = torch.zeros(1, 100, device=device)
        expr_open_jaw[0, 0] = 2.0  # First expression param (related to jaw)

        v_neutral = model(shape, expr_neutral)
        v_open = model(shape, expr_open_jaw)

        # Vertices should differ
        diff = (v_neutral - v_open).norm(dim=-1).max()
        assert diff.item() > 0.001, "Expression change had no effect"

    def test_flame_jaw_pose(self, device):
        """Jaw pose parameter opens the mouth."""
        from phoenix.render.flame_model import FlameModel, FlameModelConfig

        model = FlameModel(FlameModelConfig()).to(device)

        shape = torch.zeros(1, 300, device=device)
        expr = torch.zeros(1, 100, device=device)

        v_closed = model(shape, expr)
        jaw_open = torch.tensor([[0.5, 0.0, 0.0]], device=device)  # Rotate jaw
        v_open = model(shape, expr, jaw_pose=jaw_open)

        diff = (v_closed - v_open).norm(dim=-1).max()
        assert diff.item() > 0.001, "Jaw pose had no effect"

    def test_flame_batch(self, device):
        """FLAME handles batch processing."""
        from phoenix.render.flame_model import FlameModel, FlameModelConfig

        model = FlameModel(FlameModelConfig()).to(device)

        B = 4
        shape = torch.zeros(B, 300, device=device)
        expr = torch.randn(B, 100, device=device) * 0.5
        verts = model(shape, expr)

        assert verts.shape == (B, 5023, 3)
        assert not torch.isnan(verts).any()

    def test_flame_uv_data(self, device):
        """FLAME UV data is available for Gaussian binding."""
        from phoenix.render.flame_model import FlameModel, FlameModelConfig

        model = FlameModel(FlameModelConfig()).to(device)

        assert model.uvs.shape[1] == 2
        assert model.uvs.shape[0] > 0
        assert model.uv_faces.shape[1] == 3
        assert model.uv_faces.shape[0] > 0


class TestGaussianAvatarModel:
    """Test Gaussian Splatting avatar model."""

    def test_binding_creates_gaussians(self, device):
        """UV-space binding creates thousands of Gaussians."""
        from phoenix.render.flame_model import FlameModel, FlameModelConfig
        from phoenix.render.gsplat_avatar import AvatarRenderConfig, GaussianAvatarModel

        flame = FlameModel(FlameModelConfig()).to(device)
        config = AvatarRenderConfig(tex_size=128)  # Smaller for fast test
        avatar = GaussianAvatarModel(flame, config).to(device)

        num_gs = avatar.bind_to_mesh()

        assert num_gs > 5000, f"Expected >5000 Gaussians, got {num_gs}"
        assert num_gs < 200000, f"Too many Gaussians: {num_gs}"
        assert avatar.binding_face_id.shape[0] == num_gs
        assert avatar.binding_face_bary.shape == (num_gs, 3)

    def test_deform_gaussians(self, device):
        """Gaussian deformation produces valid attributes."""
        from phoenix.render.flame_model import FlameModel, FlameModelConfig
        from phoenix.render.gsplat_avatar import AvatarRenderConfig, GaussianAvatarModel

        flame = FlameModel(FlameModelConfig()).to(device)
        config = AvatarRenderConfig(tex_size=64)
        avatar = GaussianAvatarModel(flame, config).to(device)
        avatar.bind_to_mesh()

        # Get neutral mesh
        shape = torch.zeros(1, 300, device=device)
        expr = torch.zeros(1, 100, device=device)
        verts = flame(shape, expr)

        # Deform Gaussians
        gs = avatar.deform_gaussians(verts)

        N = avatar.num_gaussians
        assert gs["means"].shape == (1, N, 3)
        assert gs["quats"].shape == (1, N, 4)
        assert gs["scales"].shape == (1, N, 3)
        assert gs["opacities"].shape == (1, N)
        assert gs["colors"].shape == (1, N, 3)

        # No NaN/Inf
        for k, v in gs.items():
            assert not torch.isnan(v).any(), f"NaN in {k}"
            assert not torch.isinf(v).any(), f"Inf in {k}"


class TestGaussianAvatarRenderer:
    """Test the high-level avatar renderer."""

    def test_initialize(self, device):
        """Renderer initializes without error."""
        from phoenix.render.gsplat_avatar import AvatarRenderConfig, GaussianAvatarRenderer

        config = AvatarRenderConfig(tex_size=64, width=320, height=240)
        renderer = GaussianAvatarRenderer(config)
        renderer.initialize()

        assert renderer.ready
        assert renderer._avatar.num_gaussians > 0

    def test_render_neutral(self, device):
        """Render neutral face produces valid image."""
        from phoenix.render.gsplat_avatar import AvatarRenderConfig, GaussianAvatarRenderer

        config = AvatarRenderConfig(tex_size=64, width=320, height=240)
        renderer = GaussianAvatarRenderer(config)
        renderer.initialize()

        result = renderer.render_frame()

        assert result["image"].shape == (240, 320, 3)
        assert result["alpha"].shape == (240, 320, 1)
        assert result["render_time_ms"] > 0
        assert result["fps"] > 0

    def test_render_with_expression(self, device):
        """Render with expression parameters works."""
        from phoenix.render.gsplat_avatar import AvatarRenderConfig, GaussianAvatarRenderer

        config = AvatarRenderConfig(tex_size=64, width=320, height=240)
        renderer = GaussianAvatarRenderer(config)
        renderer.initialize()

        # 53 expression params (FLAME subset)
        expr = torch.randn(53) * 0.5
        jaw = torch.tensor([0.3, 0.0, 0.0])

        result = renderer.render_frame(
            expression_params=expr,
            jaw_pose=jaw,
        )

        assert result["image"].shape == (240, 320, 3)
        assert not torch.isnan(result["image"]).any()

    def test_render_720p_fps(self, device):
        """Render at 720p achieves target framerate (25+ FPS)."""
        from phoenix.render.gsplat_avatar import AvatarRenderConfig, GaussianAvatarRenderer

        config = AvatarRenderConfig(tex_size=128, width=1280, height=720)
        renderer = GaussianAvatarRenderer(config)
        renderer.initialize()

        # Warmup
        for _ in range(3):
            renderer.render_frame()

        # Benchmark
        N = 20
        start = time.perf_counter()
        for _ in range(N):
            result = renderer.render_frame(
                expression_params=torch.randn(53) * 0.3,
                jaw_pose=torch.randn(3) * 0.1,
            )
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - start

        fps = N / elapsed
        print(f"\n720p rendering: {fps:.1f} FPS ({1000*elapsed/N:.1f}ms/frame)")
        print(f"  Gaussians: {renderer._avatar.num_gaussians}")
        print(f"  VRAM: {torch.cuda.memory_allocated(device)/1e6:.0f}MB")

        assert fps > 25, f"Below 25 FPS target: {fps:.1f} FPS"


class TestBlendshapeIntegration:
    """Test integration with Phoenix blendshape types."""

    def test_arkit_to_flame_to_avatar(self, device):
        """Full pipeline: ARKit blendshapes -> FLAME -> Gaussian Avatar."""
        from phoenix.adapters.blendshape_types import (
            BlendshapeFrame,
            BlendshapeToFLAME,
        )
        from phoenix.render.gsplat_avatar import AvatarRenderConfig, GaussianAvatarRenderer

        # Create ARKit blendshape frame (52 coefficients)
        coeffs = np.zeros(52, dtype=np.float32)
        coeffs[17] = 0.7  # jawOpen
        coeffs[23] = 0.5  # mouthSmileLeft
        coeffs[24] = 0.5  # mouthSmileRight
        frame = BlendshapeFrame(coefficients=coeffs)

        # Convert to FLAME expression
        converter = BlendshapeToFLAME()
        flame_expr = converter.convert(frame)

        assert flame_expr.shape == (53,)

        # Render with these parameters
        config = AvatarRenderConfig(tex_size=64, width=320, height=240)
        renderer = GaussianAvatarRenderer(config)
        renderer.initialize()

        result = renderer.render_frame(
            expression_params=torch.from_numpy(flame_expr),
        )

        assert result["image"].shape == (240, 320, 3)
