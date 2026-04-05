"""Multi-stream GPU render pipeline for CUDA 13.2.

Manages three CUDA streams with priority-based scheduling:
  - render_stream (priority=-1): gsplat + compositor (latency-critical)
  - inference_stream (priority=0): clone model + audio2face
  - io_stream (priority=0): ASR input, NVENC output

Uses CUDA events for inter-stream synchronization and enables
frame pipelining: render frame N while encoding frame N-1.

Usage:
    pipeline = RenderPipeline(device_id=0)
    result = pipeline.execute_frame(
        render_fn=my_render,
        inference_fn=my_inference,
        encode_fn=my_encode,
    )
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import torch

logger = logging.getLogger(__name__)


@dataclass
class PipelineStats:
    """Runtime statistics for the multi-stream pipeline."""

    frames_executed: int = 0
    total_render_ms: float = 0.0
    total_inference_ms: float = 0.0
    total_io_ms: float = 0.0
    total_frame_ms: float = 0.0
    overlap_ratio: float = 0.0

    @property
    def avg_frame_ms(self) -> float:
        if self.frames_executed == 0:
            return 0.0
        return self.total_frame_ms / self.frames_executed

    @property
    def avg_fps(self) -> float:
        ms = self.avg_frame_ms
        return 1000.0 / ms if ms > 0 else 0.0


@dataclass
class FrameResult:
    """Result of a single pipeline frame execution."""

    render_output: Any = None
    inference_output: Any = None
    io_output: Any = None
    render_ms: float = 0.0
    inference_ms: float = 0.0
    io_ms: float = 0.0
    total_ms: float = 0.0


class RenderPipeline:
    """Three-stream GPU pipeline with priority scheduling.

    Streams:
        render_stream:    priority=-1 (high) for gsplat + compositor
        inference_stream: priority=0  (normal) for clone model + audio2face
        io_stream:        priority=0  (normal) for ASR, NVENC

    The render stream gets hardware-level priority on the GPU SMs,
    ensuring the display path always meets its frame deadline even
    when inference or I/O work is queued.

    Frame pipelining:
        Frame N:   [render] -> [inference]
        Frame N-1:                          [io/encode]

        The io_stream encodes the previous frame while the current
        frame is being rendered, hiding encode latency.

    Args:
        device_id: CUDA device index.
    """

    def __init__(self, device_id: int = 0) -> None:
        self.device = torch.device(f"cuda:{device_id}")

        # Three streams with priority levels
        self.render_stream = torch.cuda.Stream(
            device=self.device, priority=-1,
        )
        self.inference_stream = torch.cuda.Stream(
            device=self.device, priority=0,
        )
        self.io_stream = torch.cuda.Stream(
            device=self.device, priority=0,
        )

        # Inter-stream synchronization events
        self._render_done = torch.cuda.Event(enable_timing=True)
        self._inference_done = torch.cuda.Event(enable_timing=True)
        self._io_done = torch.cuda.Event(enable_timing=True)
        self._frame_start = torch.cuda.Event(enable_timing=True)

        # Previous frame's encode result for pipelining
        self._prev_io_output: Any = None
        self._prev_encode_fn: Callable[..., Any] | None = None
        self._prev_render_output: Any = None

        self.stats = PipelineStats()

        logger.info(
            "RenderPipeline initialized: 3 streams on cuda:%d "
            "(render=-1, inference=0, io=0)",
            device_id,
        )

    def execute_frame(
        self,
        render_fn: Callable[[], Any],
        inference_fn: Callable[[Any], Any] | None = None,
        encode_fn: Callable[[Any], Any] | None = None,
    ) -> FrameResult:
        """Execute one frame across the three-stream pipeline.

        The execution order is:
        1. render_stream: render_fn() produces the raw frame
        2. inference_stream: inference_fn(render_output) runs after
           render completes (waits on render_done event)
        3. io_stream: encode_fn(render_output) runs in parallel with
           inference, or encodes the PREVIOUS frame for pipelining

        Args:
            render_fn: Callable that produces the rendered frame.
                Runs on the high-priority render stream.
            inference_fn: Optional callable that takes render output
                and produces inference results (e.g. blendshapes).
                Runs on the inference stream.
            encode_fn: Optional callable that encodes the frame
                (e.g. NVENC). Runs on the io stream.

        Returns:
            FrameResult with outputs and per-stage timing.
        """
        result = FrameResult()
        t0 = time.perf_counter()

        # Record frame start on default stream
        self._frame_start.record()

        # Stage 1: Render on high-priority stream
        with torch.cuda.stream(self.render_stream):
            render_t0 = time.perf_counter()
            result.render_output = render_fn()
            self._render_done.record(self.render_stream)
            result.render_ms = (time.perf_counter() - render_t0) * 1000

        # Stage 2: Inference waits for render, then runs
        if inference_fn is not None:
            with torch.cuda.stream(self.inference_stream):
                self.inference_stream.wait_event(self._render_done)
                inf_t0 = time.perf_counter()
                result.inference_output = inference_fn(result.render_output)
                self._inference_done.record(self.inference_stream)
                result.inference_ms = (time.perf_counter() - inf_t0) * 1000

        # Stage 3: IO/encode — can run the PREVIOUS frame in parallel
        # with current render, or encode current frame after render.
        if encode_fn is not None:
            with torch.cuda.stream(self.io_stream):
                self.io_stream.wait_event(self._render_done)
                io_t0 = time.perf_counter()
                result.io_output = encode_fn(result.render_output)
                self._io_done.record(self.io_stream)
                result.io_ms = (time.perf_counter() - io_t0) * 1000

        # Synchronize all streams before returning
        # (caller needs the result on CPU or for the next frame)
        self.render_stream.synchronize()
        if inference_fn is not None:
            self.inference_stream.synchronize()
        if encode_fn is not None:
            self.io_stream.synchronize()

        result.total_ms = (time.perf_counter() - t0) * 1000

        # Update stats
        self.stats.frames_executed += 1
        self.stats.total_render_ms += result.render_ms
        self.stats.total_inference_ms += result.inference_ms
        self.stats.total_io_ms += result.io_ms
        self.stats.total_frame_ms += result.total_ms

        # Compute overlap ratio: if stages ran in parallel, total < sum
        stage_sum = result.render_ms + result.inference_ms + result.io_ms
        if stage_sum > 0:
            self.stats.overlap_ratio = 1.0 - (result.total_ms / stage_sum)

        return result

    def execute_frame_pipelined(
        self,
        render_fn: Callable[[], Any],
        encode_fn: Callable[[Any], Any] | None = None,
    ) -> FrameResult:
        """Execute with frame pipelining: encode N-1 while rendering N.

        This method overlaps the encode of the previous frame with
        the render of the current frame, hiding encode latency.

        Args:
            render_fn: Callable that produces the rendered frame.
            encode_fn: Optional callable that encodes a frame.

        Returns:
            FrameResult. The io_output is from the PREVIOUS frame.
        """
        result = FrameResult()
        t0 = time.perf_counter()

        # Kick off encoding of previous frame on io_stream
        if (
            encode_fn is not None
            and self._prev_render_output is not None
        ):
            prev_output = self._prev_render_output
            with torch.cuda.stream(self.io_stream):
                io_t0 = time.perf_counter()
                result.io_output = encode_fn(prev_output)
                self._io_done.record(self.io_stream)
                result.io_ms = (time.perf_counter() - io_t0) * 1000

        # Render current frame on high-priority stream (parallel with IO)
        with torch.cuda.stream(self.render_stream):
            render_t0 = time.perf_counter()
            result.render_output = render_fn()
            self._render_done.record(self.render_stream)
            result.render_ms = (time.perf_counter() - render_t0) * 1000

        # Sync both streams
        self.render_stream.synchronize()
        if encode_fn is not None and self._prev_render_output is not None:
            self.io_stream.synchronize()

        # Stash current render output for next frame's encode
        self._prev_render_output = result.render_output

        result.total_ms = (time.perf_counter() - t0) * 1000
        self.stats.frames_executed += 1
        self.stats.total_frame_ms += result.total_ms

        return result

    @property
    def stream_names(self) -> dict[str, torch.cuda.Stream]:
        """Return stream name -> stream mapping for external use."""
        return {
            "render": self.render_stream,
            "inference": self.inference_stream,
            "io": self.io_stream,
        }
