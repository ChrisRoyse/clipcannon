"""GPU-native video frame encoder using PyNvVideoCodec NVENC.

Replaces the CPU-bound Y4M pipe writer with hardware-accelerated
H.264 encoding. Performs BGR-to-NV12 color conversion on GPU via
CuPy, then encodes through NVENC's hardware encoder engine.

Two main classes:

  GPUEncoder: Low-level encoder that accepts CuPy/numpy BGR frames,
      converts to NV12 on GPU, and returns encoded NAL units (bytes).

  FramePipeline: Async wrapper that maintains a frame queue and runs
      a background encode loop for real-time frame delivery.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import cupy as cp
import numpy as np

from phoenix.errors import RenderError
from phoenix.render._gpu_kernels import bgr_to_nv12_gpu

logger = logging.getLogger(__name__)

# Minimum NVENC dimensions (from GetEncoderCaps)
_MIN_WIDTH = 146
_MIN_HEIGHT = 50

# Maximum NVENC dimensions
_MAX_WIDTH = 4096
_MAX_HEIGHT = 4096


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class EncoderStats:
    """Runtime statistics for the encoder."""

    frames_encoded: int = 0
    total_bytes: int = 0
    total_encode_time_ms: float = 0.0
    dropped_frames: int = 0
    last_frame_time_ms: float = 0.0

    @property
    def avg_encode_time_ms(self) -> float:
        if self.frames_encoded == 0:
            return 0.0
        return self.total_encode_time_ms / self.frames_encoded

    @property
    def avg_bytes_per_frame(self) -> float:
        if self.frames_encoded == 0:
            return 0.0
        return self.total_bytes / self.frames_encoded


# ---------------------------------------------------------------------------
# GPUEncoder
# ---------------------------------------------------------------------------


class GPUEncoder:
    """GPU-native H.264 encoder: CuPy BGR -> NV12 on GPU -> NVENC.

    Uses CPU input buffer path (D2H < 0.5ms for 720p NV12).
    """

    def __init__(
        self,
        width: int = 1280,
        height: int = 720,
        fps: int = 25,
        codec: str = "h264",
        preset: str = "P4",
        gpu_id: int = 0,
    ) -> None:
        self._validate_dimensions(width, height)

        self._width = width
        self._height = height
        self._fps = fps
        self._codec = codec
        self._gpu_id = gpu_id
        self._frame_interval = 1.0 / fps
        self._closed = False

        # Frame timing
        self._next_frame_time: float | None = None

        # Stats
        self.stats = EncoderStats()

        # Create NVENC encoder
        try:
            import PyNvVideoCodec

            self._encoder = PyNvVideoCodec.CreateEncoder(
                width,
                height,
                "NV12",
                True,  # usecpuinputbuffer: numpy/CPU arrays
                codec=codec,
                preset=preset,
                tuning_info="low_latency",
                rate_control="constqp",
            )
        except Exception as e:
            raise RenderError(
                f"Failed to create NVENC encoder: {e}",
                context={
                    "width": width,
                    "height": height,
                    "codec": codec,
                    "preset": preset,
                    "gpu_id": gpu_id,
                },
            ) from e

        logger.info(
            "GPUEncoder initialized: %dx%d @ %dfps, codec=%s, preset=%s",
            width,
            height,
            fps,
            codec,
            preset,
        )

    @staticmethod
    def _validate_dimensions(width: int, height: int) -> None:
        """Validate frame dimensions for NVENC."""
        if width < _MIN_WIDTH or height < _MIN_HEIGHT:
            raise RenderError(
                f"Dimensions too small for NVENC (min {_MIN_WIDTH}x{_MIN_HEIGHT})",
                context={"width": width, "height": height},
            )
        if width > _MAX_WIDTH or height > _MAX_HEIGHT:
            raise RenderError(
                f"Dimensions exceed NVENC maximum ({_MAX_WIDTH}x{_MAX_HEIGHT})",
                context={"width": width, "height": height},
            )
        if width % 2 != 0 or height % 2 != 0:
            raise RenderError(
                "NVENC requires even dimensions",
                context={"width": width, "height": height},
            )

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def fps(self) -> int:
        return self._fps

    @property
    def closed(self) -> bool:
        return self._closed

    def encode_frame(self, frame: cp.ndarray | np.ndarray) -> bytes:
        """Encode a single BGR uint8 (H,W,3) frame to H.264 NAL bytes."""
        if self._closed:
            raise RenderError("Encoder is closed")

        t0 = time.perf_counter()

        # Validate and normalize input
        bgr_gpu = self._to_gpu_bgr(frame)

        # BGR -> NV12 on GPU
        nv12_gpu = bgr_to_nv12_gpu(bgr_gpu)

        # D2H transfer (NV12 is H*3/2 * W bytes, ~1.3MB for 720p)
        nv12_cpu = nv12_gpu.get()

        # NVENC encode
        try:
            encoded = self._encoder.Encode(nv12_cpu)
        except Exception as e:
            raise RenderError(
                f"NVENC encode failed: {e}",
                context={"frame": self.stats.frames_encoded},
            ) from e

        # Update stats
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.stats.frames_encoded += 1
        self.stats.total_bytes += len(encoded)
        self.stats.total_encode_time_ms += elapsed_ms
        self.stats.last_frame_time_ms = elapsed_ms

        return encoded

    def encode_frame_paced(self, frame: cp.ndarray | np.ndarray) -> bytes:
        """Encode with fps pacing. Sleeps to maintain target frame rate."""
        now = time.monotonic()

        if self._next_frame_time is None:
            self._next_frame_time = now

        # Wait until it is time for the next frame
        sleep_time = self._next_frame_time - now
        if sleep_time > 0:
            time.sleep(sleep_time)

        encoded = self.encode_frame(frame)

        self._next_frame_time += self._frame_interval
        # If we are more than 2 frames behind, reset baseline
        if time.monotonic() > self._next_frame_time + self._frame_interval * 2:
            behind = time.monotonic() - self._next_frame_time
            self.stats.dropped_frames += int(behind / self._frame_interval)
            self._next_frame_time = time.monotonic()

        return encoded

    def flush(self) -> bytes:
        """Flush remaining buffered frames. Call before close()."""
        if self._closed:
            raise RenderError("Encoder is closed")
        try:
            return self._encoder.EndEncode()
        except Exception as e:
            raise RenderError(
                f"NVENC flush failed: {e}",
            ) from e

    def close(self) -> None:
        """Release NVENC resources. Safe to call multiple times."""
        if self._closed:
            return
        self._closed = True
        self._encoder = None  # type: ignore[assignment]
        logger.info(
            "GPUEncoder closed. Frames: %d, Avg: %.2fms, Bytes: %d",
            self.stats.frames_encoded,
            self.stats.avg_encode_time_ms,
            self.stats.total_bytes,
        )

    def __enter__(self) -> GPUEncoder:
        return self

    def __exit__(self, *exc: object) -> None:
        if not self._closed:
            try:
                self.flush()
            except RenderError:
                pass
        self.close()

    def _to_gpu_bgr(self, frame: cp.ndarray | np.ndarray) -> cp.ndarray:
        """Normalize input to CuPy uint8 BGR (H, W, 3) on GPU."""
        if not isinstance(frame, (np.ndarray, cp.ndarray)):
            raise RenderError(
                "Frame must be numpy or CuPy ndarray",
                context={"type": type(frame).__name__},
            )
        if frame.dtype != np.uint8:
            raise RenderError(
                "Frame must be uint8",
                context={"dtype": str(frame.dtype)},
            )
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise RenderError(
                "Frame must have shape (H, W, 3)",
                context={"shape": str(frame.shape)},
            )
        if frame.shape[0] != self._height or frame.shape[1] != self._width:
            raise RenderError(
                "Frame dimensions do not match encoder",
                context={
                    "frame": f"{frame.shape[1]}x{frame.shape[0]}",
                    "encoder": f"{self._width}x{self._height}",
                },
            )
        if isinstance(frame, np.ndarray):
            return cp.asarray(frame)
        return frame


# ---------------------------------------------------------------------------
# FramePipeline
# ---------------------------------------------------------------------------


class FramePipeline:
    """Async wrapper: frame queue -> background encode loop -> encoded queue."""

    def __init__(
        self,
        encoder: GPUEncoder,
        max_queue_size: int = 30,
        drop_on_overflow: bool = True,
    ) -> None:
        self._encoder = encoder
        self._max_queue_size = max_queue_size
        self._drop_on_overflow = drop_on_overflow

        self._frame_queue: asyncio.Queue[cp.ndarray | np.ndarray | None] = (
            asyncio.Queue(maxsize=max_queue_size)
        )
        self._encoded_queue: asyncio.Queue[bytes | None] = asyncio.Queue(
            maxsize=max_queue_size * 2
        )

        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._frames_dropped = 0

    @property
    def running(self) -> bool:
        return self._running

    @property
    def frames_dropped(self) -> int:
        return self._frames_dropped

    @property
    def frame_queue_size(self) -> int:
        return self._frame_queue.qsize()

    @property
    def encoded_queue_size(self) -> int:
        return self._encoded_queue.qsize()

    async def start(self) -> None:
        """Start the background encode loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._encode_loop())
        logger.info("FramePipeline started")

    async def stop(self) -> None:
        """Stop encode loop, flush encoder, signal end-of-stream."""
        if not self._running:
            return
        self._running = False

        # Drain the frame queue to make room for sentinel
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Send sentinel to unblock the encode loop
        try:
            self._frame_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None

        # Flush encoder — drain encoded queue first if needed
        try:
            flush_data = self._encoder.flush()
            if flush_data:
                # Make room in encoded queue if full
                while self._encoded_queue.full():
                    try:
                        self._encoded_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                try:
                    self._encoded_queue.put_nowait(flush_data)
                except asyncio.QueueFull:
                    pass
        except RenderError:
            pass

        # Signal end-of-stream — make room if needed
        while self._encoded_queue.full():
            try:
                self._encoded_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        try:
            self._encoded_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

        logger.info(
            "FramePipeline stopped. Dropped: %d", self._frames_dropped
        )

    async def put_frame(self, frame: cp.ndarray | np.ndarray) -> bool:
        """Submit a BGR uint8 (H,W,3) frame. Returns True if accepted."""
        if not self._running:
            return False

        if self._drop_on_overflow and self._frame_queue.full():
            # Drop the oldest frame to make room
            try:
                self._frame_queue.get_nowait()
                self._frames_dropped += 1
            except asyncio.QueueEmpty:
                pass

        try:
            self._frame_queue.put_nowait(frame)
            return True
        except asyncio.QueueFull:
            self._frames_dropped += 1
            return False

    async def get_encoded(self) -> bytes | None:
        """Get next encoded NAL packet, or None if pipeline stopped."""
        return await self._encoded_queue.get()

    async def _encode_loop(self) -> None:
        """Background loop: dequeue frames, encode, enqueue results."""
        logger.debug("Encode loop started")
        while self._running:
            try:
                frame = await asyncio.wait_for(
                    self._frame_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            if frame is None:
                break

            try:
                encoded = self._encoder.encode_frame(frame)
                if encoded:
                    try:
                        self._encoded_queue.put_nowait(encoded)
                    except asyncio.QueueFull:
                        # Drop oldest encoded packet
                        try:
                            self._encoded_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        self._encoded_queue.put_nowait(encoded)
            except RenderError as e:
                logger.warning("Encode error in pipeline: %s", e)

        logger.debug("Encode loop exited")
