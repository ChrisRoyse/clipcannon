"""Real-time Y4M frame writer for dynamic avatar rendering.

Writes YUV420 frames to a FIFO pipe that Chrome reads via
--use-file-for-fake-video-capture. Manages three avatar states:

  IDLE: Subtle breathing motion (slight scale oscillation)
  LISTENING: Attentive, mostly still, occasional micro-nods
  SPEAKING: Lip-synced mouth animation driven by TTS audio

The writer runs in a background thread at 25fps. The main thread
controls state transitions and feeds audio for lip sync.
"""
from __future__ import annotations

import enum
import logging
import os
import queue
import threading
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class AvatarState(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    SPEAKING = "speaking"


class Y4MWriter:
    """Continuous Y4M frame writer for Chrome fake video capture.

    Args:
        pipe_path: Path to the FIFO pipe (created if not exists).
        reference_frame: BGR uint8 base frame with Santa's face.
        fps: Frame rate (default 25).
        width: Output width (default 1280).
        height: Output height (default 720).
    """

    def __init__(
        self,
        pipe_path: str,
        reference_frame: np.ndarray,
        fps: int = 25,
        width: int = 1280,
        height: int = 720,
    ) -> None:
        self._pipe_path = pipe_path
        self._fps = fps
        self._w = width
        self._h = height
        self._frame_interval = 1.0 / fps

        # Resize reference frame if needed
        if reference_frame.shape[:2] != (height, width):
            reference_frame = cv2.resize(reference_frame, (width, height))
        self._ref_bgr = reference_frame

        # Pre-convert reference to YUV420 planes for fast writing
        self._ref_yuv = cv2.cvtColor(reference_frame, cv2.COLOR_BGR2YUV_I420)

        # State
        self._state = AvatarState.IDLE
        self._state_lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

        # Lip sync queue: list of LipFrame params for speaking state
        self._lip_queue: queue.Queue = queue.Queue(maxsize=500)
        self._current_mouth_open = 0.0

        # Face warper (lazy init)
        self._warper = None

        # Frame counter for idle animation
        self._frame_count = 0

        # Stats
        self._frames_written = 0
        self._write_errors = 0

    def _init_warper(self) -> None:
        """Lazy-init the face warper."""
        if self._warper is None:
            from phoenix.render.face_warper import FaceWarper
            self._warper = FaceWarper(self._ref_bgr, max_pixel_shift=20)
            if self._warper.ready:
                logger.info("Face warper initialized")
            else:
                logger.warning("Face warper: no face detected, lip sync disabled")

    def start(self) -> None:
        """Start the frame writer thread."""
        if self._running:
            return

        # Create FIFO pipe if it doesn't exist
        if os.path.exists(self._pipe_path):
            os.remove(self._pipe_path)
        os.mkfifo(self._pipe_path)
        logger.info("Created FIFO pipe: %s", self._pipe_path)

        # Init warper in main thread (uses GPU)
        self._init_warper()

        self._running = True
        self._thread = threading.Thread(target=self._write_loop, daemon=True)
        self._thread.start()
        logger.info("Y4M writer started at %dfps", self._fps)

    def stop(self) -> None:
        """Stop the frame writer."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        # Clean up FIFO
        try:
            os.remove(self._pipe_path)
        except OSError:
            pass
        logger.info("Y4M writer stopped. Frames: %d, Errors: %d",
                     self._frames_written, self._write_errors)

    def set_state(self, state: AvatarState) -> None:
        """Transition to a new avatar state."""
        with self._state_lock:
            if self._state != state:
                logger.info("Avatar: %s -> %s", self._state.value, state.value)
                self._state = state
                if state != AvatarState.SPEAKING:
                    # Clear lip queue when not speaking
                    while not self._lip_queue.empty():
                        try:
                            self._lip_queue.get_nowait()
                        except queue.Empty:
                            break
                    self._current_mouth_open = 0.0

    def feed_lip_frames(self, lip_frames: list) -> None:
        """Feed lip sync parameters for speaking state.

        Args:
            lip_frames: List of LipFrame from LipSync.from_audio().
        """
        for lf in lip_frames:
            try:
                self._lip_queue.put_nowait(lf)
            except queue.Full:
                break

    def _generate_frame(self) -> np.ndarray:
        """Generate the next BGR frame based on current state."""
        with self._state_lock:
            state = self._state

        if state == AvatarState.SPEAKING:
            return self._generate_speaking_frame()
        elif state == AvatarState.LISTENING:
            return self._generate_listening_frame()
        else:
            return self._generate_idle_frame()

    def _generate_idle_frame(self) -> np.ndarray:
        """Idle: subtle breathing motion via slight vertical oscillation."""
        self._frame_count += 1
        # Subtle breathing: 0.3px vertical shift at ~0.25Hz (15 breaths/min)
        t = self._frame_count / self._fps
        breath_shift = np.sin(2 * np.pi * 0.25 * t) * 0.3

        if abs(breath_shift) < 0.1:
            return self._ref_bgr

        # Apply tiny vertical translation
        M = np.float32([[1, 0, 0], [0, 1, breath_shift]])
        return cv2.warpAffine(
            self._ref_bgr, M, (self._w, self._h),
            borderMode=cv2.BORDER_REPLICATE,
        )

    def _generate_listening_frame(self) -> np.ndarray:
        """Listening: mostly still with occasional micro-nods."""
        self._frame_count += 1
        t = self._frame_count / self._fps

        # Micro-nod every ~4 seconds (subtle 0.5 degree tilt)
        nod_phase = (t % 4.0) / 4.0
        if 0.4 < nod_phase < 0.6:
            tilt = np.sin((nod_phase - 0.4) / 0.2 * np.pi) * 0.5
            if self._warper and self._warper.ready:
                return self._warper.warp_mouth(0.0, head_tilt=tilt)

        return self._ref_bgr

    def _generate_speaking_frame(self) -> np.ndarray:
        """Speaking: lip-synced mouth animation from audio."""
        # Get next lip frame from queue
        try:
            lf = self._lip_queue.get_nowait()
            self._current_mouth_open = lf.mouth_open
        except queue.Empty:
            # Queue exhausted — smoothly close mouth
            self._current_mouth_open *= 0.7
            if self._current_mouth_open < 0.02:
                self._current_mouth_open = 0.0

        if self._warper and self._warper.ready:
            return self._warper.warp_mouth(self._current_mouth_open)

        return self._ref_bgr

    def _bgr_to_yuv420_planes(self, bgr: np.ndarray) -> bytes:
        """Convert BGR frame to YUV420 planar bytes for Y4M."""
        yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420)
        return yuv.tobytes()

    def _write_loop(self) -> None:
        """Main loop: opens FIFO, writes Y4M header, then frames at fps."""
        logger.info("Y4M writer: waiting for reader to open pipe...")

        try:
            # This blocks until Chrome opens the pipe for reading
            pipe_fd = os.open(self._pipe_path, os.O_WRONLY)
        except OSError as e:
            logger.error("Failed to open FIFO: %s", e)
            return

        try:
            # Write Y4M header
            header = f"YUV4MPEG2 W{self._w} H{self._h} F{self._fps}:1 Ip A1:1 C420\n"
            os.write(pipe_fd, header.encode())

            frame_time = time.monotonic()
            while self._running:
                # Generate frame
                bgr = self._generate_frame()

                # Convert to YUV420 and write
                try:
                    os.write(pipe_fd, b"FRAME\n")
                    os.write(pipe_fd, self._bgr_to_yuv420_planes(bgr))
                    self._frames_written += 1
                except BrokenPipeError:
                    logger.warning("Y4M pipe broken (reader closed)")
                    break
                except OSError as e:
                    self._write_errors += 1
                    if self._write_errors > 100:
                        logger.error("Too many write errors: %s", e)
                        break
                    continue

                # Frame rate control
                frame_time += self._frame_interval
                sleep_time = frame_time - time.monotonic()
                if sleep_time > 0:
                    time.sleep(sleep_time)
                else:
                    # Falling behind — skip to catch up
                    frame_time = time.monotonic()

        except Exception as e:
            logger.error("Y4M writer error: %s", e)
        finally:
            try:
                os.close(pipe_fd)
            except OSError:
                pass
            logger.info("Y4M writer loop exited")
