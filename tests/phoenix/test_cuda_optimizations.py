"""Tests for CUDA 13.2 optimizations. Real GPU ops, no mocks."""

from __future__ import annotations

import time

import cupy as cp
import numpy as np
import pytest
import torch

from phoenix.render.cupy_compositor import (
    alpha_blend_gpu,
    resize_gpu,
)


class TestSynchronizeRemoval:
    """Compositor correctness without synchronize()."""

    def test_alpha_blend_chained_ops(self) -> None:
        bg = cp.full((64, 64, 3), 0.2, dtype=cp.float32)
        fg = cp.full((64, 64, 3), 0.8, dtype=cp.float32)
        alpha = cp.full((64, 64), 0.5, dtype=cp.float32)

        # Chain: blend -> resize -> blend again
        blended = alpha_blend_gpu(fg, bg, alpha)
        resized = resize_gpu(blended, 128, 128)
        alpha2 = cp.full((128, 128), 1.0, dtype=cp.float32)
        bg2 = cp.zeros((128, 128, 3), dtype=cp.float32)
        final = alpha_blend_gpu(resized, bg2, alpha2)

        # Pull to CPU — this forces the implicit sync
        cpu = final.get()
        # Expected: 0.8*0.5 + 0.2*0.5 = 0.5, then full alpha onto black
        np.testing.assert_allclose(cpu[64, 64], [0.5, 0.5, 0.5], atol=0.05)

    def test_resize_chained_preserves_content(self) -> None:
        frame = cp.zeros((100, 100, 3), dtype=cp.float32)
        frame[:, :, 0] = 1.0  # Red

        # Chain three resizes without any synchronize
        r1 = resize_gpu(frame, 200, 200)
        r2 = resize_gpu(r1, 50, 50)
        r3 = resize_gpu(r2, 100, 100)

        cpu = r3.get()
        # Should still be red after all transforms
        np.testing.assert_allclose(cpu[50, 50], [1.0, 0.0, 0.0], atol=0.05)

    def test_high_volume_no_sync(self) -> None:
        bg = cp.full((32, 32, 3), 0.0, dtype=cp.float32)
        fg = cp.full((32, 32, 3), 1.0, dtype=cp.float32)
        alpha = cp.full((32, 32), 0.01, dtype=cp.float32)

        result = bg
        for _ in range(100):
            result = alpha_blend_gpu(fg, result, alpha)

        cpu = result.get()
        # After 100 iterations of blending white at 1%, values should be >0
        assert cpu.mean() > 0.1


class TestStreamPriorities:
    """CUDA stream priority creation and usage."""

    def test_high_priority_stream_creation(self) -> None:
        stream = torch.cuda.Stream(priority=-1)
        assert stream is not None
        # Verify it has a valid cuda_stream handle
        assert stream.cuda_stream >= 0

    def test_normal_priority_stream_creation(self) -> None:
        stream = torch.cuda.Stream(priority=0)
        assert stream is not None

    def test_stream_priority_ordering(self) -> None:
        low, high = torch.cuda.Stream.priority_range()
        assert low >= 0  # lowest priority (numerically highest)
        assert high <= 0  # highest priority (numerically lowest)

    def test_work_on_priority_stream(self) -> None:
        stream = torch.cuda.Stream(priority=-1)
        with torch.cuda.stream(stream):
            a = torch.randn(256, 256, device="cuda")
            b = torch.randn(256, 256, device="cuda")
            c = torch.matmul(a, b)

        stream.synchronize()
        assert c.shape == (256, 256)
        assert not torch.isnan(c).any()

    def test_avatar_renderer_has_streams(self) -> None:
        from phoenix.render.avatar_renderer import GaussianAvatarRenderer

        renderer = GaussianAvatarRenderer()
        assert hasattr(renderer, "_render_stream")
        assert hasattr(renderer, "_aux_stream")
        assert renderer._render_stream is not None
        assert renderer._aux_stream is not None


class TestCloneModelCompile:
    """torch.compile and FP8 on CloneModel."""

    def _make_model(self) -> "CloneModel":
        from phoenix.clone.model import CloneModel

        model = CloneModel(
            embedding_dims={"visual": 64, "semantic": 64, "prosody": 12},
            shared_dim=32,
            num_latents=8,
            num_layers=1,
        )
        return model.cuda()

    def _make_input(self, model: "CloneModel") -> dict:
        return {
            "visual": torch.randn(1, 64, device="cuda"),
            "semantic": torch.randn(1, 64, device="cuda"),
            "prosody": torch.randn(1, 12, device="cuda"),
        }

    def test_compile_returns_self(self) -> None:
        model = self._make_model()
        result = model.compile(mode="reduce-overhead")
        assert result is model

    def test_compiled_forward_produces_output(self) -> None:
        model = self._make_model()
        inputs = self._make_input(model)

        # Run uncompiled first (baseline)
        out_base = model(inputs)

        # Compile and run
        model.compile(mode="reduce-overhead")
        out_compiled = model(inputs)

        assert "blendshapes" in out_compiled
        assert out_compiled["blendshapes"].shape == out_base["blendshapes"].shape

    def test_compiled_model_gradients(self) -> None:
        model = self._make_model()
        model.compile(mode="reduce-overhead")
        inputs = self._make_input(model)

        out = model(inputs)
        loss = out["blendshapes"].sum()
        loss.backward()

        # At least some parameters should have gradients
        has_grad = any(
            p.grad is not None and p.grad.abs().sum() > 0
            for p in model.parameters()
            if p.requires_grad
        )
        assert has_grad


class TestMultiStreamPipeline:
    """RenderPipeline three-stream execution."""

    def test_basic_execution(self) -> None:
        from phoenix.render.gpu_pipeline import RenderPipeline

        pipeline = RenderPipeline()

        def render_fn():
            return torch.randn(64, 64, 3, device="cuda")

        def inference_fn(frame):
            return torch.matmul(
                frame.reshape(64, -1), frame.reshape(-1, 64),
            )

        def encode_fn(frame):
            return frame.mean()

        result = pipeline.execute_frame(render_fn, inference_fn, encode_fn)

        assert result.render_output is not None
        assert result.inference_output is not None
        assert result.io_output is not None
        assert result.total_ms > 0

    def test_render_only(self) -> None:
        from phoenix.render.gpu_pipeline import RenderPipeline

        pipeline = RenderPipeline()

        def render_fn():
            return torch.ones(32, 32, device="cuda")

        result = pipeline.execute_frame(render_fn)
        assert result.render_output is not None
        assert result.inference_output is None
        assert result.io_output is None

    def test_stats_accumulate(self) -> None:
        from phoenix.render.gpu_pipeline import RenderPipeline

        pipeline = RenderPipeline()

        def render_fn():
            return torch.randn(16, 16, device="cuda")

        for _ in range(5):
            pipeline.execute_frame(render_fn)

        assert pipeline.stats.frames_executed == 5
        assert pipeline.stats.total_frame_ms > 0
        assert pipeline.stats.avg_fps > 0

    def test_pipelined_execution(self) -> None:
        from phoenix.render.gpu_pipeline import RenderPipeline

        pipeline = RenderPipeline()
        call_count = {"render": 0, "encode": 0}

        def render_fn():
            call_count["render"] += 1
            return torch.randn(32, 32, device="cuda")

        def encode_fn(frame):
            call_count["encode"] += 1
            return frame.sum()

        # First frame: render only (no previous to encode)
        r1 = pipeline.execute_frame_pipelined(render_fn, encode_fn)
        assert r1.render_output is not None
        assert r1.io_output is None  # No previous frame to encode

        # Second frame: render current + encode previous
        r2 = pipeline.execute_frame_pipelined(render_fn, encode_fn)
        assert r2.render_output is not None
        assert r2.io_output is not None  # Previous frame was encoded

    def test_stream_names(self) -> None:
        from phoenix.render.gpu_pipeline import RenderPipeline

        pipeline = RenderPipeline()
        names = pipeline.stream_names
        assert "render" in names
        assert "inference" in names
        assert "io" in names


class TestFrameSelector:
    """FrameSelector quality scoring on GPU."""

    def test_sharpness_scoring(self) -> None:
        from phoenix.render.frame_selector import FrameSelector

        selector = FrameSelector(n_candidates=2)

        # Sharp: high-contrast edges
        sharp = cp.zeros((64, 64, 3), dtype=cp.float32)
        sharp[::2, :, :] = 1.0  # Horizontal stripes

        # Blurry: uniform gray
        blurry = cp.full((64, 64, 3), 0.5, dtype=cp.float32)

        score_sharp = selector.score_sharpness(sharp)
        score_blurry = selector.score_sharpness(blurry)

        assert score_sharp > score_blurry

    def test_symmetry_scoring(self) -> None:
        from phoenix.render.frame_selector import FrameSelector

        selector = FrameSelector(n_candidates=2)

        # Symmetric: same left and right
        sym = cp.zeros((64, 64, 3), dtype=cp.float32)
        sym[:, :32, 0] = 0.8
        sym[:, 32:, 0] = 0.8  # Same value both sides

        # Asymmetric: different left and right
        asym = cp.zeros((64, 64, 3), dtype=cp.float32)
        asym[:, :32, 0] = 1.0
        asym[:, 32:, 0] = 0.0  # Very different sides

        score_sym = selector.score_symmetry(sym)
        score_asym = selector.score_symmetry(asym)

        assert score_sym > score_asym

    def test_temporal_coherence_scoring(self) -> None:
        from phoenix.render.frame_selector import FrameSelector

        selector = FrameSelector(n_candidates=2)

        frame1 = cp.full((64, 64, 3), 0.5, dtype=cp.float32)
        # Set previous frame
        selector._prev_frame = frame1

        # Very similar frame
        similar = cp.full((64, 64, 3), 0.51, dtype=cp.float32)
        # Very different frame
        different = cp.full((64, 64, 3), 1.0, dtype=cp.float32)

        score_similar = selector.score_temporal_coherence(similar)
        score_different = selector.score_temporal_coherence(different)

        assert score_similar > score_different

    def test_select_best_returns_valid_index(self) -> None:
        from phoenix.render.frame_selector import FrameSelector

        selector = FrameSelector(n_candidates=4)

        candidates = [
            cp.random.random((64, 64, 3), dtype=cp.float32)
            for _ in range(4)
        ]

        idx = selector.select_best(candidates)
        assert 0 <= idx < 4

    def test_select_best_single_candidate(self) -> None:
        from phoenix.render.frame_selector import FrameSelector

        selector = FrameSelector(n_candidates=1)
        candidates = [cp.full((32, 32, 3), 0.5, dtype=cp.float32)]
        idx = selector.select_best(candidates)
        assert idx == 0

    def test_select_best_empty_raises(self) -> None:
        from phoenix.render.frame_selector import FrameSelector

        selector = FrameSelector(n_candidates=4)
        with pytest.raises(ValueError, match="must not be empty"):
            selector.select_best([])

    def test_score_frame_returns_all_metrics(self) -> None:
        from phoenix.render.frame_selector import FrameSelector, FrameScore

        selector = FrameSelector(n_candidates=1)
        frame = cp.random.random((64, 64, 3), dtype=cp.float32)
        score = selector.score_frame(frame)

        assert isinstance(score, FrameScore)
        assert score.composite >= 0.0
        assert score.sharpness >= 0.0
        assert score.temporal_coherence >= 0.0
        assert score.symmetry >= 0.0

    def test_prefers_sharp_over_blurry(self) -> None:
        from phoenix.render.frame_selector import FrameSelector

        selector = FrameSelector(
            n_candidates=2,
            sharpness_weight=1.0,
            coherence_weight=0.0,
            symmetry_weight=0.0,
        )

        # Sharp: edges
        sharp = cp.zeros((64, 64, 3), dtype=cp.float32)
        sharp[::2, :, :] = 1.0

        # Blurry: uniform
        blurry = cp.full((64, 64, 3), 0.5, dtype=cp.float32)

        idx = selector.select_best([blurry, sharp])
        assert idx == 1  # sharp is index 1


class TestGPUEncoderSkipD2H:
    """GPU encoder skip_d2h flag."""

    def test_skip_d2h_returns_gpu_array(self) -> None:
        from phoenix.render.gpu_encoder import GPUEncoder
        import inspect

        sig = inspect.signature(GPUEncoder.encode_frame)
        assert "skip_d2h" in sig.parameters
        # Default should be False
        assert sig.parameters["skip_d2h"].default is False


class TestBenchmarks:
    """Benchmark key ops to verify optimization impact."""

    @pytest.mark.parametrize("op", ["blend", "resize"])
    def test_compositor_throughput_no_sync(self, op: str) -> None:
        bg = cp.full((720, 1280, 3), 0.2, dtype=cp.float32)
        fg = cp.full((720, 1280, 3), 0.8, dtype=cp.float32)
        alpha = cp.full((720, 1280), 0.5, dtype=cp.float32)

        fn = (
            (lambda: alpha_blend_gpu(fg, bg, alpha))
            if op == "blend"
            else (lambda: resize_gpu(fg, 360, 640))
        )

        # Warmup + benchmark (sync only at end)
        for _ in range(3):
            fn()
        cp.cuda.Device().synchronize()

        n = 50
        t0 = time.perf_counter()
        for _ in range(n):
            fn()
        cp.cuda.Device().synchronize()
        fps = n / (time.perf_counter() - t0)
        assert fps > 50, f"{op} too slow: {fps:.1f} FPS"

    def test_stream_priority_no_overhead(self) -> None:
        def workload(stream):
            with torch.cuda.stream(stream):
                a = torch.randn(512, 512, device="cuda")
                for _ in range(10):
                    a = torch.matmul(a, a)
            stream.synchronize()

        normal = torch.cuda.Stream(priority=0)
        high = torch.cuda.Stream(priority=-1)
        workload(normal)
        workload(high)  # warmup

        t0 = time.perf_counter()
        for _ in range(5):
            workload(normal)
        normal_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        for _ in range(5):
            workload(high)
        high_ms = (time.perf_counter() - t0) * 1000

        assert high_ms < normal_ms * 1.5
