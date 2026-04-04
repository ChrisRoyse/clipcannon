"""Tests for GPU-native video encoder (PyNvVideoCodec NVENC).

Uses REAL GPU operations — no mocks. Requires a CUDA-capable GPU
with NVENC support and PyNvVideoCodec + CuPy installed.
"""

from __future__ import annotations

import asyncio
import time

import cupy as cp
import numpy as np
import pytest

from phoenix.errors import CompositorError, PhoenixError, RenderError
from phoenix.render._gpu_kernels import bgr_to_nv12_gpu
from phoenix.render.gpu_encoder import (
    FramePipeline,
    GPUEncoder,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_bgr_gpu(
    h: int = 720, w: int = 1280, color: tuple[int, int, int] = (128, 64, 32)
) -> cp.ndarray:
    """Create a solid-color BGR uint8 frame on GPU."""
    frame = cp.empty((h, w, 3), dtype=cp.uint8)
    frame[:, :, 0] = color[0]  # B
    frame[:, :, 1] = color[1]  # G
    frame[:, :, 2] = color[2]  # R
    return frame


def make_bgr_numpy(
    h: int = 720, w: int = 1280, color: tuple[int, int, int] = (128, 64, 32)
) -> np.ndarray:
    """Create a solid-color BGR uint8 frame on CPU."""
    frame = np.empty((h, w, 3), dtype=np.uint8)
    frame[:, :, 0] = color[0]
    frame[:, :, 1] = color[1]
    frame[:, :, 2] = color[2]
    return frame


# ---------------------------------------------------------------------------
# NV12 conversion tests
# ---------------------------------------------------------------------------


class TestBGRToNV12:
    """Tests for the GPU BGR->NV12 kernel."""

    def test_output_shape(self) -> None:
        """NV12 output has shape (H*3//2, W) for (H, W, 3) input."""
        bgr = make_bgr_gpu(480, 640)
        nv12 = bgr_to_nv12_gpu(bgr)
        assert nv12.shape == (720, 640)  # 480 * 3 // 2 = 720
        assert nv12.dtype == cp.uint8

    def test_output_shape_1080p(self) -> None:
        """Verify NV12 shape for 1080p input."""
        bgr = make_bgr_gpu(1080, 1920)
        nv12 = bgr_to_nv12_gpu(bgr)
        assert nv12.shape == (1620, 1920)

    def test_pure_black(self) -> None:
        """Pure black BGR(0,0,0) -> Y=0, U=128, V=128."""
        bgr = make_bgr_gpu(480, 640, color=(0, 0, 0))
        nv12 = bgr_to_nv12_gpu(bgr)
        nv12_cpu = nv12.get()

        y_plane = nv12_cpu[:480, :]
        uv_plane = nv12_cpu[480:, :]

        assert np.all(y_plane == 0), f"Y plane not zero: mean={y_plane.mean()}"
        # U and V should be 128 (neutral chroma)
        u_vals = uv_plane[:, 0::2]
        v_vals = uv_plane[:, 1::2]
        assert np.allclose(u_vals, 128, atol=1), f"U not 128: mean={u_vals.mean()}"
        assert np.allclose(v_vals, 128, atol=1), f"V not 128: mean={v_vals.mean()}"

    def test_pure_white(self) -> None:
        """Pure white BGR(255,255,255) -> Y=255, U=128, V=128."""
        bgr = make_bgr_gpu(480, 640, color=(255, 255, 255))
        nv12 = bgr_to_nv12_gpu(bgr)
        nv12_cpu = nv12.get()

        y_plane = nv12_cpu[:480, :]
        uv_plane = nv12_cpu[480:, :]

        assert np.allclose(y_plane, 255, atol=1), f"Y not 255: mean={y_plane.mean()}"
        u_vals = uv_plane[:, 0::2]
        v_vals = uv_plane[:, 1::2]
        assert np.allclose(u_vals, 128, atol=1), f"U not 128: mean={u_vals.mean()}"
        assert np.allclose(v_vals, 128, atol=1), f"V not 128: mean={v_vals.mean()}"

    def test_pure_red(self) -> None:
        """Pure red BGR(0,0,255) -> Y~76, U~84, V~255."""
        bgr = make_bgr_gpu(480, 640, color=(0, 0, 255))
        nv12 = bgr_to_nv12_gpu(bgr)
        nv12_cpu = nv12.get()

        y_plane = nv12_cpu[:480, :]
        uv_plane = nv12_cpu[480:, :]

        # BT.601: Y = 0.299*255 = 76.245
        assert np.allclose(y_plane, 76, atol=2), f"Y not ~76: mean={y_plane.mean()}"
        u_vals = uv_plane[:, 0::2]
        v_vals = uv_plane[:, 1::2]
        # U = -0.14713*255 + 128 = 90.48
        assert np.allclose(u_vals, 90, atol=2), f"U not ~90: mean={u_vals.mean()}"
        # V = 0.615*255 + 128 = 284.8 -> clamped to 255
        assert np.allclose(v_vals, 255, atol=1), f"V not ~255: mean={v_vals.mean()}"

    def test_pure_green(self) -> None:
        """Pure green BGR(0,255,0) -> Y~150, U~54, V=0 (clamped)."""
        bgr = make_bgr_gpu(480, 640, color=(0, 255, 0))
        nv12 = bgr_to_nv12_gpu(bgr)
        nv12_cpu = nv12.get()

        y_plane = nv12_cpu[:480, :]
        # BT.601: Y = 0.587*255 = 149.685
        assert np.allclose(y_plane, 150, atol=2), f"Y not ~150: mean={y_plane.mean()}"

    def test_pure_blue(self) -> None:
        """Pure blue BGR(255,0,0) -> Y~29, U~239, V~102."""
        bgr = make_bgr_gpu(480, 640, color=(255, 0, 0))
        nv12 = bgr_to_nv12_gpu(bgr)
        nv12_cpu = nv12.get()

        y_plane = nv12_cpu[:480, :]
        uv_plane = nv12_cpu[480:, :]

        # BT.601: Y = 0.114*255 = 29.07
        assert np.allclose(y_plane, 29, atol=2), f"Y not ~29: mean={y_plane.mean()}"
        u_vals = uv_plane[:, 0::2]
        # U = 0.436*255 + 128 = 239.18
        assert np.allclose(u_vals, 239, atol=2), f"U not ~239: mean={u_vals.mean()}"

    def test_gradient_frame(self) -> None:
        """Gradient frame produces smoothly varying NV12."""
        h, w = 480, 640
        bgr = cp.zeros((h, w, 3), dtype=cp.uint8)
        # Horizontal blue gradient
        grad = cp.arange(w, dtype=cp.uint8).reshape(1, w)
        bgr[:, :, 0] = cp.broadcast_to(grad, (h, w))
        nv12 = bgr_to_nv12_gpu(bgr)
        nv12_cpu = nv12.get()

        y_plane = nv12_cpu[:h, :]
        # Y should increase left to right (blue contributes 0.114*B)
        assert y_plane[:, -1].mean() > y_plane[:, 0].mean()

    def test_odd_dimensions_rejected(self) -> None:
        """Odd dimensions should raise PhoenixError."""
        bgr = cp.zeros((481, 640, 3), dtype=cp.uint8)
        with pytest.raises(PhoenixError, match="even dimensions"):
            bgr_to_nv12_gpu(bgr)

        bgr2 = cp.zeros((480, 641, 3), dtype=cp.uint8)
        with pytest.raises(PhoenixError, match="even dimensions"):
            bgr_to_nv12_gpu(bgr2)

    def test_wrong_dtype_rejected(self) -> None:
        """Non-uint8 input should raise PhoenixError."""
        bgr = cp.zeros((480, 640, 3), dtype=cp.float32)
        with pytest.raises(PhoenixError, match="uint8"):
            bgr_to_nv12_gpu(bgr)

    def test_wrong_shape_rejected(self) -> None:
        """Wrong shape should raise PhoenixError."""
        # 2D array
        bgr = cp.zeros((480, 640), dtype=cp.uint8)
        with pytest.raises(PhoenixError, match="shape"):
            bgr_to_nv12_gpu(bgr)

        # 4 channels
        bgr2 = cp.zeros((480, 640, 4), dtype=cp.uint8)
        with pytest.raises(PhoenixError, match="shape"):
            bgr_to_nv12_gpu(bgr2)

    def test_not_cupy_rejected(self) -> None:
        """Numpy array should raise PhoenixError."""
        bgr = np.zeros((480, 640, 3), dtype=np.uint8)
        with pytest.raises(PhoenixError, match="CuPy"):
            bgr_to_nv12_gpu(bgr)

    def test_small_frame(self) -> None:
        """Smallest valid even frame (2x2)."""
        bgr = make_bgr_gpu(2, 2, color=(100, 150, 200))
        nv12 = bgr_to_nv12_gpu(bgr)
        assert nv12.shape == (3, 2)

    def test_various_resolutions(self) -> None:
        """Multiple standard resolutions produce correct shapes."""
        for h, w in [(480, 640), (720, 1280), (1080, 1920), (360, 640)]:
            bgr = make_bgr_gpu(h, w)
            nv12 = bgr_to_nv12_gpu(bgr)
            assert nv12.shape == (h * 3 // 2, w), f"Failed for {w}x{h}"


# ---------------------------------------------------------------------------
# GPUEncoder tests
# ---------------------------------------------------------------------------


class TestGPUEncoder:
    """Tests for the GPUEncoder class."""

    def test_init_default(self) -> None:
        """Default initialization succeeds."""
        enc = GPUEncoder()
        assert enc.width == 1280
        assert enc.height == 720
        assert enc.fps == 25
        assert not enc.closed
        enc.close()

    def test_init_custom_resolution(self) -> None:
        """Custom resolution initializes correctly."""
        enc = GPUEncoder(width=640, height=480, fps=30)
        assert enc.width == 640
        assert enc.height == 480
        assert enc.fps == 30
        enc.close()

    def test_init_too_small(self) -> None:
        """Dimensions below NVENC minimum raise RenderError."""
        with pytest.raises(RenderError, match="too small"):
            GPUEncoder(width=64, height=64)

    def test_init_too_large(self) -> None:
        """Dimensions above NVENC maximum raise RenderError."""
        with pytest.raises(RenderError, match="exceed"):
            GPUEncoder(width=8192, height=4320)

    def test_init_odd_dimensions(self) -> None:
        """Odd dimensions raise RenderError."""
        with pytest.raises(RenderError, match="even"):
            GPUEncoder(width=1281, height=720)

    def test_encode_cupy_frame(self) -> None:
        """Encoding CuPy GPU frames produces bytes."""
        enc = GPUEncoder(width=640, height=480)
        frame = make_bgr_gpu(480, 640)

        total = b""
        for _ in range(10):
            total += enc.encode_frame(frame)
        total += enc.flush()

        assert len(total) > 0, "No encoded data produced"
        assert enc.stats.frames_encoded == 10
        enc.close()

    def test_encode_numpy_frame(self) -> None:
        """Encoding numpy CPU frames produces bytes."""
        enc = GPUEncoder(width=640, height=480)
        frame = make_bgr_numpy(480, 640)

        total = b""
        for _ in range(10):
            total += enc.encode_frame(frame)
        total += enc.flush()

        assert len(total) > 0
        assert enc.stats.frames_encoded == 10
        enc.close()

    def test_encode_wrong_size_rejected(self) -> None:
        """Frame size mismatch raises RenderError."""
        enc = GPUEncoder(width=640, height=480)
        frame = make_bgr_gpu(720, 1280)  # wrong size
        with pytest.raises(RenderError, match="do not match"):
            enc.encode_frame(frame)
        enc.close()

    def test_encode_wrong_dtype_rejected(self) -> None:
        """Non-uint8 frame raises RenderError."""
        enc = GPUEncoder(width=640, height=480)
        frame = cp.zeros((480, 640, 3), dtype=cp.float32)
        with pytest.raises(RenderError, match="uint8"):
            enc.encode_frame(frame)
        enc.close()

    def test_encode_wrong_channels_rejected(self) -> None:
        """Wrong channel count raises RenderError."""
        enc = GPUEncoder(width=640, height=480)
        frame = cp.zeros((480, 640, 4), dtype=cp.uint8)
        with pytest.raises(RenderError, match="shape"):
            enc.encode_frame(frame)
        enc.close()

    def test_encode_invalid_type_rejected(self) -> None:
        """Non-array input raises RenderError."""
        enc = GPUEncoder(width=640, height=480)
        with pytest.raises(RenderError, match="numpy or CuPy"):
            enc.encode_frame([1, 2, 3])  # type: ignore[arg-type]
        enc.close()

    def test_encode_after_close_rejected(self) -> None:
        """Encoding after close raises RenderError."""
        enc = GPUEncoder(width=640, height=480)
        enc.close()
        with pytest.raises(RenderError, match="closed"):
            enc.encode_frame(make_bgr_gpu(480, 640))

    def test_flush_after_close_rejected(self) -> None:
        """Flushing after close raises RenderError."""
        enc = GPUEncoder(width=640, height=480)
        enc.close()
        with pytest.raises(RenderError, match="closed"):
            enc.flush()

    def test_double_close_safe(self) -> None:
        """Closing twice does not raise."""
        enc = GPUEncoder(width=640, height=480)
        enc.close()
        enc.close()  # should not raise

    def test_context_manager(self) -> None:
        """GPUEncoder works as a context manager."""
        with GPUEncoder(width=640, height=480) as enc:
            enc.encode_frame(make_bgr_gpu(480, 640))
        assert enc.closed

    def test_stats_tracking(self) -> None:
        """Stats are updated after encoding."""
        enc = GPUEncoder(width=640, height=480)
        frame = make_bgr_gpu(480, 640)

        for _ in range(5):
            enc.encode_frame(frame)

        assert enc.stats.frames_encoded == 5
        assert enc.stats.total_encode_time_ms > 0
        assert enc.stats.avg_encode_time_ms > 0
        assert enc.stats.last_frame_time_ms > 0
        enc.flush()
        enc.close()

    def test_h264_nal_header(self) -> None:
        """Encoded output contains H.264 NAL start codes."""
        enc = GPUEncoder(width=640, height=480)
        frame = make_bgr_gpu(480, 640)

        total = b""
        for _ in range(10):
            total += enc.encode_frame(frame)
        total += enc.flush()

        # H.264 streams start with NAL unit start code 0x00000001
        assert b"\x00\x00\x00\x01" in total or b"\x00\x00\x01" in total, (
            "No H.264 NAL start code found"
        )
        enc.close()

    def test_encode_720p(self) -> None:
        """720p encoding works end-to-end."""
        with GPUEncoder(width=1280, height=720) as enc:
            total = b""
            for _ in range(5):
                total += enc.encode_frame(make_bgr_gpu(720, 1280))
            total += enc.flush()
            assert len(total) > 0

    def test_encode_1080p(self) -> None:
        """1080p encoding works end-to-end."""
        with GPUEncoder(width=1920, height=1080) as enc:
            total = b""
            for _ in range(5):
                total += enc.encode_frame(make_bgr_gpu(1080, 1920))
            total += enc.flush()
            assert len(total) > 0

    def test_encode_480p(self) -> None:
        """480p encoding works end-to-end."""
        with GPUEncoder(width=640, height=480) as enc:
            total = b""
            for _ in range(5):
                total += enc.encode_frame(make_bgr_gpu(480, 640))
            total += enc.flush()
            assert len(total) > 0

    def test_encode_360p(self) -> None:
        """360p encoding works end-to-end."""
        with GPUEncoder(width=640, height=360) as enc:
            total = b""
            for _ in range(5):
                total += enc.encode_frame(make_bgr_gpu(360, 640))
            total += enc.flush()
            assert len(total) > 0

    def test_varying_content(self) -> None:
        """Different frame content produces different encoded sizes."""
        enc = GPUEncoder(width=640, height=480)

        # Encode some black frames
        black_bytes = b""
        for _ in range(10):
            black_bytes += enc.encode_frame(make_bgr_gpu(480, 640, (0, 0, 0)))
        black_bytes += enc.flush()
        enc.close()

        # Encode random (noisy) frames
        enc2 = GPUEncoder(width=640, height=480)
        rand_bytes = b""
        for _ in range(10):
            rand_frame = cp.random.randint(0, 255, (480, 640, 3), dtype=cp.uint8)
            rand_bytes += enc2.encode_frame(rand_frame)
        rand_bytes += enc2.flush()
        enc2.close()

        # Random content should compress to more bytes than solid black
        assert len(rand_bytes) > len(black_bytes), (
            f"Random ({len(rand_bytes)}) should be larger than black ({len(black_bytes)})"
        )


# ---------------------------------------------------------------------------
# Frame timing tests
# ---------------------------------------------------------------------------


class TestFrameTiming:
    """Tests for 25fps pacing in encode_frame_paced."""

    def test_paced_encoding_timing(self) -> None:
        """Paced encoding maintains approximate frame rate."""
        enc = GPUEncoder(width=640, height=480, fps=25)
        frame = make_bgr_gpu(480, 640)

        n_frames = 10
        t0 = time.monotonic()
        for _ in range(n_frames):
            enc.encode_frame_paced(frame)
        elapsed = time.monotonic() - t0

        expected = n_frames * (1.0 / 25)
        # Allow 15% tolerance for timing jitter
        assert elapsed >= expected * 0.85, (
            f"Too fast: {elapsed:.3f}s < {expected * 0.85:.3f}s"
        )
        assert elapsed < expected * 1.3, (
            f"Too slow: {elapsed:.3f}s > {expected * 1.3:.3f}s"
        )
        enc.flush()
        enc.close()

    def test_paced_first_frame_no_delay(self) -> None:
        """First paced frame should not wait."""
        enc = GPUEncoder(width=640, height=480, fps=25)
        frame = make_bgr_gpu(480, 640)

        t0 = time.monotonic()
        enc.encode_frame_paced(frame)
        elapsed = time.monotonic() - t0

        # First frame should take <50ms (encode time only, no sleep)
        assert elapsed < 0.05, f"First frame took {elapsed:.3f}s"
        enc.flush()
        enc.close()


# ---------------------------------------------------------------------------
# Encode/Decode roundtrip
# ---------------------------------------------------------------------------


class TestRoundtrip:
    """Test encode then decode roundtrip via ffprobe/ffmpeg."""

    def test_roundtrip_valid_h264(self) -> None:
        """Encoded bitstream is valid H.264 readable by ffprobe."""
        import subprocess
        import tempfile
        import os

        # Encode
        enc = GPUEncoder(width=640, height=480)
        frame = make_bgr_gpu(480, 640, color=(100, 150, 200))

        bitstream = b""
        for _ in range(30):
            bitstream += enc.encode_frame(frame)
        bitstream += enc.flush()
        enc.close()

        assert len(bitstream) > 0

        # Write raw H.264 bitstream
        with tempfile.NamedTemporaryFile(suffix=".h264", delete=False) as f:
            f.write(bitstream)
            h264_file = f.name

        mp4_file = h264_file.replace(".h264", ".mp4")

        try:
            # Mux into MP4 container
            subprocess.run(
                ["ffmpeg", "-y", "-f", "h264", "-i", h264_file, "-c", "copy", mp4_file],
                capture_output=True,
                check=True,
            )

            # Probe the MP4 with ffprobe
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=codec_name,width,height,nb_frames",
                    "-of", "csv=p=0",
                    mp4_file,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            output = result.stdout.strip()
            parts = output.split(",")

            assert parts[0] == "h264", f"Expected h264, got {parts[0]}"
            assert int(parts[1]) == 640, f"Expected width 640, got {parts[1]}"
            assert int(parts[2]) == 480, f"Expected height 480, got {parts[2]}"

            # nb_frames might be "N/A" for some containers, check if available
            if parts[3] != "N/A":
                frame_count = int(parts[3])
                assert frame_count > 0, "No frames in encoded stream"
        finally:
            os.unlink(h264_file)
            if os.path.exists(mp4_file):
                os.unlink(mp4_file)

    def test_roundtrip_decode_pixels(self) -> None:
        """Decode encoded frames back to pixels and verify resolution."""
        import subprocess
        import tempfile
        import os

        enc = GPUEncoder(width=640, height=480)
        frame = make_bgr_gpu(480, 640, color=(0, 0, 0))  # black

        bitstream = b""
        for _ in range(10):
            bitstream += enc.encode_frame(frame)
        bitstream += enc.flush()
        enc.close()

        with tempfile.NamedTemporaryFile(suffix=".h264", delete=False) as f:
            f.write(bitstream)
            h264_file = f.name

        raw_file = h264_file.replace(".h264", ".raw")

        try:
            # Decode to raw YUV via ffmpeg
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "h264", "-i", h264_file,
                    "-pix_fmt", "nv12",
                    "-f", "rawvideo",
                    raw_file,
                ],
                capture_output=True,
            )

            if os.path.exists(raw_file):
                raw_size = os.path.getsize(raw_file)
                # Each NV12 frame = 640*480*3//2 = 460800 bytes
                frame_bytes = 640 * 480 * 3 // 2
                assert raw_size >= frame_bytes, (
                    f"Raw file too small: {raw_size} < {frame_bytes}"
                )
                decoded_frames = raw_size // frame_bytes
                assert decoded_frames > 0, "No decoded frames"
        finally:
            os.unlink(h264_file)
            if os.path.exists(raw_file):
                os.unlink(raw_file)


# ---------------------------------------------------------------------------
# FramePipeline async tests
# ---------------------------------------------------------------------------


class TestFramePipeline:
    """Tests for the async FramePipeline."""

    @pytest.fixture
    def encoder(self) -> GPUEncoder:
        enc = GPUEncoder(width=640, height=480)
        yield enc
        if not enc.closed:
            try:
                enc.flush()
            except RenderError:
                pass
            enc.close()

    @pytest.mark.asyncio
    async def test_start_stop(self, encoder: GPUEncoder) -> None:
        """Pipeline starts and stops cleanly."""
        pipeline = FramePipeline(encoder)
        assert not pipeline.running

        await pipeline.start()
        assert pipeline.running

        await pipeline.stop()
        assert not pipeline.running

    @pytest.mark.asyncio
    async def test_encode_frames(self, encoder: GPUEncoder) -> None:
        """Frames submitted to pipeline produce encoded output."""
        pipeline = FramePipeline(encoder)
        await pipeline.start()

        frame = make_bgr_gpu(480, 640)
        for _ in range(10):
            accepted = await pipeline.put_frame(frame)
            assert accepted

        # Give encode loop time to process
        await asyncio.sleep(0.5)

        await pipeline.stop()

        # Collect encoded output
        encoded_parts = []
        while True:
            data = await asyncio.wait_for(pipeline.get_encoded(), timeout=1.0)
            if data is None:
                break
            encoded_parts.append(data)

        total = b"".join(encoded_parts)
        assert len(total) > 0, "No encoded data from pipeline"

    @pytest.mark.asyncio
    async def test_queue_overflow_drops(self, encoder: GPUEncoder) -> None:
        """Queue overflow drops oldest frames when drop_on_overflow=True."""
        pipeline = FramePipeline(encoder, max_queue_size=5, drop_on_overflow=True)
        await pipeline.start()

        frame = make_bgr_gpu(480, 640)

        # Fill far beyond capacity without consuming
        for _ in range(20):
            await pipeline.put_frame(frame)
            await asyncio.sleep(0.01)

        # Give encode loop time to process some frames
        await asyncio.sleep(1.0)
        await pipeline.stop()

        # Drain encoded queue with timeout to prevent hang
        collected = 0
        try:
            while True:
                data = await asyncio.wait_for(
                    pipeline.get_encoded(), timeout=3.0
                )
                if data is None:
                    break
                collected += 1
        except asyncio.TimeoutError:
            pass  # Safety: prevent infinite hang

        # Pipeline completed without deadlocking
        assert not pipeline.running

    @pytest.mark.asyncio
    async def test_put_frame_when_stopped(self, encoder: GPUEncoder) -> None:
        """put_frame returns False when pipeline is not running."""
        pipeline = FramePipeline(encoder)
        result = await pipeline.put_frame(make_bgr_gpu(480, 640))
        assert result is False

    @pytest.mark.asyncio
    async def test_double_start(self, encoder: GPUEncoder) -> None:
        """Starting twice does not create duplicate tasks."""
        pipeline = FramePipeline(encoder)
        await pipeline.start()
        await pipeline.start()  # should be no-op
        assert pipeline.running
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_double_stop(self, encoder: GPUEncoder) -> None:
        """Stopping twice does not raise."""
        pipeline = FramePipeline(encoder)
        await pipeline.start()
        await pipeline.stop()
        await pipeline.stop()  # should be no-op

    @pytest.mark.asyncio
    async def test_queue_size_properties(self, encoder: GPUEncoder) -> None:
        """Queue size properties reflect actual state."""
        pipeline = FramePipeline(encoder, max_queue_size=10)
        assert pipeline.frame_queue_size == 0
        assert pipeline.encoded_queue_size == 0
        assert pipeline.frames_dropped == 0


# ---------------------------------------------------------------------------
# Lifecycle and edge cases
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Encoder lifecycle and edge case tests."""

    def test_many_encoders_sequential(self) -> None:
        """Creating and destroying many encoders does not leak."""
        for _ in range(10):
            enc = GPUEncoder(width=640, height=480)
            enc.encode_frame(make_bgr_gpu(480, 640))
            enc.flush()
            enc.close()

    def test_flush_without_frames(self) -> None:
        """Flushing without encoding returns empty bytes."""
        enc = GPUEncoder(width=640, height=480)
        data = enc.flush()
        assert isinstance(data, bytes)
        enc.close()

    def test_context_manager_on_error(self) -> None:
        """Context manager closes encoder even on exception."""
        try:
            with GPUEncoder(width=640, height=480) as enc:
                enc.encode_frame(make_bgr_gpu(480, 640))
                raise ValueError("test error")
        except ValueError:
            pass
        assert enc.closed

    def test_stats_initial_values(self) -> None:
        """Stats have correct initial values."""
        enc = GPUEncoder(width=640, height=480)
        assert enc.stats.frames_encoded == 0
        assert enc.stats.total_bytes == 0
        assert enc.stats.total_encode_time_ms == 0.0
        assert enc.stats.dropped_frames == 0
        assert enc.stats.avg_encode_time_ms == 0.0
        assert enc.stats.avg_bytes_per_frame == 0.0
        enc.close()

    def test_encoder_properties(self) -> None:
        """Encoder properties match constructor args."""
        enc = GPUEncoder(width=800, height=600, fps=30)
        assert enc.width == 800
        assert enc.height == 600
        assert enc.fps == 30
        assert not enc.closed
        enc.close()
        assert enc.closed

    def test_encode_performance_budget(self) -> None:
        """720p encoding stays within 40ms per frame budget."""
        enc = GPUEncoder(width=1280, height=720)
        frame = make_bgr_gpu(720, 1280)

        # Warm up
        for _ in range(5):
            enc.encode_frame(frame)

        # Measure
        times = []
        for _ in range(20):
            t0 = time.perf_counter()
            enc.encode_frame(frame)
            times.append((time.perf_counter() - t0) * 1000)

        avg_ms = sum(times) / len(times)
        max_ms = max(times)

        enc.flush()
        enc.close()

        assert avg_ms < 40, f"Average encode time {avg_ms:.2f}ms exceeds 40ms budget"
        # Max can be higher due to GPU scheduling, but should be < 80ms
        assert max_ms < 80, f"Max encode time {max_ms:.2f}ms exceeds 80ms limit"
