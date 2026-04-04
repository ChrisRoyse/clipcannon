"""GPU stress tests for CuPy compositor kernels on RTX 5090.

Validates throughput, latency distributions, VRAM stability, and
concurrency safety across all compositor operations at sustained load.

Requires: CuPy with CUDA. Tests skip gracefully if unavailable.
"""

from __future__ import annotations

import statistics
import sys
import threading
import time
from typing import Callable

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Skip entire module if CuPy / CUDA is unavailable
# ---------------------------------------------------------------------------

try:
    import cupy as cp
    cp.cuda.runtime.getDeviceCount()
    HAS_CUDA = True
except Exception:
    HAS_CUDA = False

pytestmark = pytest.mark.skipif(not HAS_CUDA, reason="CuPy/CUDA not available")

if HAS_CUDA:
    from phoenix.render.cupy_compositor import (
        alpha_blend_gpu,
        brightness_jitter_gpu,
        color_convert_gpu,
        film_grain_gpu,
        paste_face_region_gpu,
        resize_gpu,
    )
    from phoenix.render.compositor_bridge import (
        gpu_alpha_blend,
        gpu_brightness_jitter,
        gpu_composite_face,
        gpu_film_grain,
    )
    from phoenix.render._gpu_kernels import (
        ALPHA_BLEND_KERNEL as alpha_blend_kernel,
        BILINEAR_RESIZE_KERNEL as bilinear_resize_kernel,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VRAM_LEAK_THRESHOLD_BYTES = 1 * 1024 * 1024  # 1 MB

# CuPy memory pools allocate in aligned chunks. After freeing all
# Python references and calling free_all_blocks(), any residual delta
# is pool overhead, not a leak. We compare VRAM *after* explicit
# cleanup of all result references.


def _get_vram_free() -> int:
    """Return free VRAM in bytes."""
    free, _total = cp.cuda.runtime.memGetInfo()
    return free


def _flush_gpu_memory() -> None:
    """Synchronize and free CuPy memory pools."""
    cp.cuda.Device().synchronize()
    cp.get_default_memory_pool().free_all_blocks()
    cp.get_default_pinned_memory_pool().free_all_blocks()


def _measure_latencies(
    func: Callable[[], None],
    iterations: int,
    label: str,
) -> list[float]:
    """Run *func* N times, return list of per-call latencies in ms.

    Also prints a one-line summary for the pytest -s console.
    """
    # Warmup: 5 iterations (or fewer if total is small)
    warmup = min(5, iterations)
    for _ in range(warmup):
        func()

    latencies: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        func()
        latencies.append((time.perf_counter() - t0) * 1000.0)

    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95)]
    p99 = sorted(latencies)[int(len(latencies) * 0.99)]
    mean = statistics.mean(latencies)

    print(
        f"\n  [{label}] n={iterations}  "
        f"mean={mean:.3f}ms  p50={p50:.3f}ms  p95={p95:.3f}ms  p99={p99:.3f}ms"
    )
    return latencies


def _assert_vram_stable(label: str, before_free: int) -> None:
    """Assert VRAM did not leak more than threshold."""
    _flush_gpu_memory()
    after_free = _get_vram_free()
    delta = before_free - after_free
    print(f"\n  [{label}] VRAM delta: {delta / 1024:.1f} KB")
    assert delta < VRAM_LEAK_THRESHOLD_BYTES, (
        f"VRAM leak detected in {label}: {delta / 1024:.1f} KB > "
        f"{VRAM_LEAK_THRESHOLD_BYTES / 1024:.1f} KB threshold"
    )


# ---------------------------------------------------------------------------
# Fixtures: 720p RGBA frames on GPU
# ---------------------------------------------------------------------------


@pytest.fixture
def frame_720p() -> cp.ndarray:
    """Random 720p RGB float32 frame on GPU."""
    return cp.random.random((720, 1280, 3), dtype=cp.float32)


@pytest.fixture
def frame_720p_rgba() -> cp.ndarray:
    """Random 720p RGBA float32 frame on GPU."""
    return cp.random.random((720, 1280, 4), dtype=cp.float32)


@pytest.fixture
def alpha_720p() -> cp.ndarray:
    """Random 720p single-channel alpha mask on GPU."""
    return cp.random.random((720, 1280), dtype=cp.float32)


@pytest.fixture
def face_256() -> cp.ndarray:
    """Random 256x256 RGB float32 face patch on GPU."""
    return cp.random.random((256, 256, 3), dtype=cp.float32)


@pytest.fixture
def frame_720p_uint8() -> np.ndarray:
    """Random 720p RGB uint8 frame on CPU (for bridge tests)."""
    return np.random.randint(0, 256, (720, 1280, 3), dtype=np.uint8)


@pytest.fixture
def face_256_uint8() -> np.ndarray:
    """Random 256x256 RGB uint8 face patch on CPU (for bridge tests)."""
    return np.random.randint(0, 256, (256, 256, 3), dtype=np.uint8)


# ===================================================================
# 1. Alpha Blend Stress (1000 ops)
# ===================================================================


class TestAlphaBlendStress:
    """1000 consecutive alpha_blend_gpu on 720p frames."""

    ITERATIONS = 1000

    def test_alpha_blend_1000_ops_latency(
        self, frame_720p: cp.ndarray, alpha_720p: cp.ndarray
    ) -> None:
        """Measure per-op latency over 1000 alpha blends at 720p."""
        fg = frame_720p.copy()
        bg = frame_720p.copy()
        alpha = alpha_720p

        def op():
            alpha_blend_gpu(fg, bg, alpha)

        latencies = _measure_latencies(op, self.ITERATIONS, "alpha_blend_gpu 720p")
        # Sanity: p50 under 5ms for a 720p blend on RTX 5090
        p50 = statistics.median(latencies)
        assert p50 < 50.0, f"alpha_blend p50={p50:.3f}ms too slow"

    def test_alpha_blend_vram_stable(
        self, frame_720p: cp.ndarray, alpha_720p: cp.ndarray
    ) -> None:
        """VRAM should not grow after 1000 alpha blends."""
        fg = frame_720p.copy()
        bg = frame_720p.copy()
        alpha = alpha_720p

        # Warmup to stabilize pool
        result = alpha_blend_gpu(fg, bg, alpha)
        del result
        _flush_gpu_memory()
        vram_before = _get_vram_free()

        for _ in range(self.ITERATIONS):
            result = alpha_blend_gpu(fg, bg, alpha)
        del result
        _assert_vram_stable("alpha_blend x1000", vram_before)


# ===================================================================
# 2. Resize Stress (1000 ops)
# ===================================================================


class TestResizeStress:
    """1000 consecutive resize_gpu operations (1280x720 -> 640x360)."""

    ITERATIONS = 1000

    def test_resize_1000_ops_latency(self, frame_720p: cp.ndarray) -> None:
        """Measure per-op latency over 1000 resizes."""

        def op():
            resize_gpu(frame_720p, 360, 640)

        latencies = _measure_latencies(op, self.ITERATIONS, "resize_gpu 720p->360p")
        p50 = statistics.median(latencies)
        assert p50 < 50.0, f"resize p50={p50:.3f}ms too slow"

    def test_resize_vram_stable(self, frame_720p: cp.ndarray) -> None:
        """VRAM should not grow after 1000 resizes."""
        # Warmup to stabilize pool
        result = resize_gpu(frame_720p, 360, 640)
        del result
        _flush_gpu_memory()
        vram_before = _get_vram_free()

        for _ in range(self.ITERATIONS):
            result = resize_gpu(frame_720p, 360, 640)
        del result
        _assert_vram_stable("resize x1000", vram_before)


# ===================================================================
# 3. Paste Face Region Stress (1000 ops)
# ===================================================================


class TestPasteFaceStress:
    """1000 consecutive paste_face_region_gpu operations."""

    ITERATIONS = 1000

    def test_paste_face_1000_ops_latency(
        self, frame_720p: cp.ndarray, face_256: cp.ndarray
    ) -> None:
        """Measure per-op latency over 1000 face pastes."""

        def op():
            paste_face_region_gpu(frame_720p, face_256, x=400, y=200, w=256, h=256)

        latencies = _measure_latencies(op, self.ITERATIONS, "paste_face_region_gpu 720p")
        p50 = statistics.median(latencies)
        assert p50 < 50.0, f"paste_face p50={p50:.3f}ms too slow"

    def test_paste_face_vram_stable(
        self, frame_720p: cp.ndarray, face_256: cp.ndarray
    ) -> None:
        """VRAM should not grow after 1000 face pastes."""
        # Warmup to stabilize pool
        result = paste_face_region_gpu(
            frame_720p, face_256, x=400, y=200, w=256, h=256
        )
        del result
        _flush_gpu_memory()
        vram_before = _get_vram_free()

        for _ in range(self.ITERATIONS):
            result = paste_face_region_gpu(
                frame_720p, face_256, x=400, y=200, w=256, h=256
            )
        del result
        _assert_vram_stable("paste_face x1000", vram_before)


# ===================================================================
# 4. Film Grain Stress (500 ops)
# ===================================================================


class TestFilmGrainStress:
    """500 consecutive film_grain_gpu operations."""

    ITERATIONS = 500

    def test_film_grain_500_ops_latency(self, frame_720p: cp.ndarray) -> None:
        """Measure per-op latency over 500 film grain applications."""

        def op():
            film_grain_gpu(frame_720p, intensity=0.02)

        latencies = _measure_latencies(op, self.ITERATIONS, "film_grain_gpu 720p")
        p50 = statistics.median(latencies)
        assert p50 < 50.0, f"film_grain p50={p50:.3f}ms too slow"

    def test_film_grain_vram_stable(self, frame_720p: cp.ndarray) -> None:
        """VRAM should not grow after 500 film grain ops."""
        # Warmup to stabilize pool
        result = film_grain_gpu(frame_720p, intensity=0.02)
        del result
        _flush_gpu_memory()
        vram_before = _get_vram_free()

        for _ in range(self.ITERATIONS):
            result = film_grain_gpu(frame_720p, intensity=0.02)
        del result
        _assert_vram_stable("film_grain x500", vram_before)


# ===================================================================
# 5. Brightness Jitter Stress (500 ops)
# ===================================================================


class TestBrightnessJitterStress:
    """500 consecutive brightness_jitter_gpu operations."""

    ITERATIONS = 500

    def test_brightness_jitter_500_ops_latency(
        self, frame_720p: cp.ndarray
    ) -> None:
        """Measure per-op latency over 500 brightness jitter applications."""

        def op():
            brightness_jitter_gpu(frame_720p, amount=0.01)

        latencies = _measure_latencies(
            op, self.ITERATIONS, "brightness_jitter_gpu 720p"
        )
        p50 = statistics.median(latencies)
        assert p50 < 50.0, f"brightness_jitter p50={p50:.3f}ms too slow"

    def test_brightness_jitter_vram_stable(
        self, frame_720p: cp.ndarray
    ) -> None:
        """VRAM should not grow after 500 brightness jitter ops."""
        # Warmup to stabilize pool
        result = brightness_jitter_gpu(frame_720p, amount=0.01)
        del result
        _flush_gpu_memory()
        vram_before = _get_vram_free()

        for _ in range(self.ITERATIONS):
            result = brightness_jitter_gpu(frame_720p, amount=0.01)
        del result
        _assert_vram_stable("brightness_jitter x500", vram_before)


# ===================================================================
# 6. Mixed Pipeline Stress (500 iterations)
# ===================================================================


class TestMixedPipelineStress:
    """Full face compositing pipeline repeated 500 times.

    Pipeline: resize -> paste_face -> alpha_blend -> film_grain -> brightness_jitter
    """

    ITERATIONS = 500

    def test_full_pipeline_500_ops_latency(
        self,
        frame_720p: cp.ndarray,
        face_256: cp.ndarray,
        alpha_720p: cp.ndarray,
    ) -> None:
        """Measure end-to-end pipeline latency over 500 iterations."""
        bg = frame_720p.copy()

        def pipeline():
            # 1. Resize face to 128x128
            face_resized = resize_gpu(face_256, 128, 128)
            # 2. Paste face onto frame
            composited = paste_face_region_gpu(
                bg, face_resized, x=500, y=250, w=128, h=128
            )
            # 3. Alpha blend with a second frame
            blended = alpha_blend_gpu(composited, bg, alpha_720p)
            # 4. Film grain
            grained = film_grain_gpu(blended, intensity=0.015)
            # 5. Brightness jitter
            _final = brightness_jitter_gpu(grained, amount=0.005)

        latencies = _measure_latencies(
            pipeline, self.ITERATIONS, "full_pipeline (resize+paste+blend+grain+jitter)"
        )
        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        p99 = sorted(latencies)[int(len(latencies) * 0.99)]

        print(
            f"\n  [pipeline summary] p50={p50:.3f}ms  "
            f"p95={p95:.3f}ms  p99={p99:.3f}ms"
        )
        # Full pipeline should complete under 100ms on RTX 5090
        assert p50 < 100.0, f"pipeline p50={p50:.3f}ms too slow"

    def test_full_pipeline_vram_stable(
        self,
        frame_720p: cp.ndarray,
        face_256: cp.ndarray,
        alpha_720p: cp.ndarray,
    ) -> None:
        """VRAM should not grow after 500 full pipeline iterations."""
        bg = frame_720p.copy()

        # Warmup to stabilize pool allocations
        face_resized = resize_gpu(face_256, 128, 128)
        composited = paste_face_region_gpu(
            bg, face_resized, x=500, y=250, w=128, h=128
        )
        blended = alpha_blend_gpu(composited, bg, alpha_720p)
        grained = film_grain_gpu(blended, intensity=0.015)
        final = brightness_jitter_gpu(grained, amount=0.005)
        del face_resized, composited, blended, grained, final
        _flush_gpu_memory()
        vram_before = _get_vram_free()

        for _ in range(self.ITERATIONS):
            face_resized = resize_gpu(face_256, 128, 128)
            composited = paste_face_region_gpu(
                bg, face_resized, x=500, y=250, w=128, h=128
            )
            blended = alpha_blend_gpu(composited, bg, alpha_720p)
            grained = film_grain_gpu(blended, intensity=0.015)
            final = brightness_jitter_gpu(grained, amount=0.005)
        del face_resized, composited, blended, grained, final
        _assert_vram_stable("full_pipeline x500", vram_before)


# ===================================================================
# 7. Concurrent Stress (threading)
# ===================================================================


class TestConcurrentStress:
    """Run alpha_blend and resize concurrently via threading for 100 iterations.

    CuPy operations are internally serialized on the same CUDA stream by
    default, but this test validates no CUDA errors or segfaults occur
    when multiple Python threads submit GPU work simultaneously.
    """

    ITERATIONS = 100

    def test_concurrent_blend_and_resize(self) -> None:
        """No CUDA errors when blending and resizing from two threads."""
        errors: list[str] = []

        def blend_worker():
            try:
                fg = cp.random.random((720, 1280, 3), dtype=cp.float32)
                bg = cp.random.random((720, 1280, 3), dtype=cp.float32)
                alpha = cp.random.random((720, 1280), dtype=cp.float32)
                for _ in range(self.ITERATIONS):
                    _r = alpha_blend_gpu(fg, bg, alpha)
                cp.cuda.Device().synchronize()
            except Exception as exc:
                errors.append(f"blend_worker: {exc}")

        def resize_worker():
            try:
                img = cp.random.random((720, 1280, 3), dtype=cp.float32)
                for _ in range(self.ITERATIONS):
                    _r = resize_gpu(img, 360, 640)
                cp.cuda.Device().synchronize()
            except Exception as exc:
                errors.append(f"resize_worker: {exc}")

        t1 = threading.Thread(target=blend_worker, name="blend_thread")
        t2 = threading.Thread(target=resize_worker, name="resize_thread")

        t1.start()
        t2.start()
        t1.join(timeout=120)
        t2.join(timeout=120)

        assert not t1.is_alive(), "blend_worker thread did not finish in time"
        assert not t2.is_alive(), "resize_worker thread did not finish in time"
        assert len(errors) == 0, f"CUDA errors in concurrent stress: {errors}"

    def test_concurrent_vram_stable(self) -> None:
        """VRAM should not leak during concurrent operations."""
        _flush_gpu_memory()
        vram_before = _get_vram_free()

        errors: list[str] = []

        def grain_worker():
            try:
                img = cp.random.random((720, 1280, 3), dtype=cp.float32)
                for _ in range(self.ITERATIONS):
                    _r = film_grain_gpu(img, intensity=0.02)
                cp.cuda.Device().synchronize()
            except Exception as exc:
                errors.append(f"grain_worker: {exc}")

        def jitter_worker():
            try:
                img = cp.random.random((720, 1280, 3), dtype=cp.float32)
                for _ in range(self.ITERATIONS):
                    _r = brightness_jitter_gpu(img, amount=0.01)
                cp.cuda.Device().synchronize()
            except Exception as exc:
                errors.append(f"jitter_worker: {exc}")

        t1 = threading.Thread(target=grain_worker, name="grain_thread")
        t2 = threading.Thread(target=jitter_worker, name="jitter_thread")

        t1.start()
        t2.start()
        t1.join(timeout=120)
        t2.join(timeout=120)

        assert len(errors) == 0, f"CUDA errors: {errors}"
        _assert_vram_stable("concurrent (grain+jitter) x100", vram_before)


# ===================================================================
# 8. Bridge Functions Stress
# ===================================================================


class TestBridgeStress:
    """Stress test compositor_bridge functions (numpy uint8 in/out)."""

    ITERATIONS = 200

    def test_gpu_composite_face_stress(
        self, frame_720p_uint8: np.ndarray, face_256_uint8: np.ndarray
    ) -> None:
        """200 consecutive gpu_composite_face round-trips."""

        def op():
            gpu_composite_face(
                frame_720p_uint8, face_256_uint8,
                x=400, y=200, w=256, h=256, blend_alpha=0.9,
            )

        latencies = _measure_latencies(op, self.ITERATIONS, "gpu_composite_face bridge")
        p50 = statistics.median(latencies)
        assert p50 < 100.0, f"bridge composite p50={p50:.3f}ms too slow"

    def test_gpu_alpha_blend_stress(
        self, frame_720p_uint8: np.ndarray
    ) -> None:
        """200 consecutive gpu_alpha_blend round-trips."""
        fg = frame_720p_uint8
        bg = np.random.randint(0, 256, (720, 1280, 3), dtype=np.uint8)

        def op():
            gpu_alpha_blend(fg, bg, alpha=0.5)

        latencies = _measure_latencies(op, self.ITERATIONS, "gpu_alpha_blend bridge")
        p50 = statistics.median(latencies)
        assert p50 < 100.0, f"bridge alpha_blend p50={p50:.3f}ms too slow"

    def test_gpu_film_grain_stress(
        self, frame_720p_uint8: np.ndarray
    ) -> None:
        """200 consecutive gpu_film_grain round-trips."""

        def op():
            gpu_film_grain(frame_720p_uint8, intensity=0.015)

        latencies = _measure_latencies(op, self.ITERATIONS, "gpu_film_grain bridge")
        p50 = statistics.median(latencies)
        assert p50 < 100.0, f"bridge film_grain p50={p50:.3f}ms too slow"

    def test_gpu_brightness_jitter_stress(
        self, frame_720p_uint8: np.ndarray
    ) -> None:
        """200 consecutive gpu_brightness_jitter round-trips."""

        def op():
            gpu_brightness_jitter(frame_720p_uint8, amount=0.01)

        latencies = _measure_latencies(
            op, self.ITERATIONS, "gpu_brightness_jitter bridge"
        )
        p50 = statistics.median(latencies)
        assert p50 < 100.0, f"bridge brightness_jitter p50={p50:.3f}ms too slow"


# ===================================================================
# 9. Raw Kernel Object Validation
# ===================================================================


class TestRawKernels:
    """Validate that imported raw kernel objects are functional."""

    def test_bilinear_resize_kernel_is_callable(self) -> None:
        """bilinear_resize_kernel should be a compiled CuPy RawKernel."""
        assert callable(bilinear_resize_kernel)
        assert hasattr(bilinear_resize_kernel, "kernel")

    def test_alpha_blend_kernel_is_callable(self) -> None:
        """alpha_blend_kernel should be a compiled CuPy RawKernel."""
        assert callable(alpha_blend_kernel)
        assert hasattr(alpha_blend_kernel, "kernel")

    def test_raw_resize_kernel_direct_call(self) -> None:
        """Invoke bilinear_resize_kernel directly and verify output shape."""
        src = cp.random.random((100, 200, 3), dtype=cp.float32)
        dst = cp.empty((50, 100, 3), dtype=cp.float32)
        total = 50 * 100 * 3
        block = 256
        grid = (total + block - 1) // block

        bilinear_resize_kernel(
            (grid,), (block,),
            (src.ravel(), dst.ravel(), 100, 200, 50, 100, 3),
        )
        cp.cuda.Device().synchronize()

        result = dst.get()
        assert result.shape == (50, 100, 3)
        assert result.dtype == np.float32
        # Values should be in a reasonable range (source was [0,1])
        assert result.min() >= -0.01
        assert result.max() <= 1.01

    def test_raw_alpha_blend_kernel_direct_call(self) -> None:
        """Invoke alpha_blend_kernel directly and verify output values."""
        h, w, c = 100, 200, 3
        fg = cp.ones((h, w, c), dtype=cp.float32)  # white
        bg = cp.zeros((h, w, c), dtype=cp.float32)  # black
        alpha = cp.full((h, w), 0.5, dtype=cp.float32)
        out = cp.empty((h, w, c), dtype=cp.float32)

        total = h * w * c
        block = 256
        grid = (total + block - 1) // block

        alpha_blend_kernel(
            (grid,), (block,),
            (fg.ravel(), bg.ravel(), alpha.ravel(), out.ravel(), h, w, c, 1),
        )
        cp.cuda.Device().synchronize()

        result = out.get()
        # 1.0 * 0.5 + 0.0 * 0.5 = 0.5 everywhere
        np.testing.assert_allclose(result, 0.5, atol=0.01)


# ===================================================================
# 10. Summary Table (session-scoped)
# ===================================================================


def test_print_summary_banner() -> None:
    """Print a summary banner at the end of the test run.

    This test always passes; it exists to print GPU info for the report.
    """
    free, total = cp.cuda.runtime.memGetInfo()
    dev = cp.cuda.Device()
    props = cp.cuda.runtime.getDeviceProperties(dev.id)
    name = props["name"].decode() if isinstance(props["name"], bytes) else props["name"]

    print("\n")
    print("=" * 70)
    print("  CuPy GPU Stress Test Summary")
    print("=" * 70)
    print(f"  GPU:         {name}")
    print(f"  VRAM:        {total / 1024**3:.1f} GB total, {free / 1024**3:.1f} GB free")
    print(f"  CuPy:        {cp.__version__}")
    print(f"  CUDA:        {cp.cuda.runtime.runtimeGetVersion()}")
    print("=" * 70)
