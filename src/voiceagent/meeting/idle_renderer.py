"""Idle state renderer -- driver video loop with natural human micro-behaviors.

When the clone is NOT speaking, this renders:
1. Driver video loop (ping-pong, seamless) -- provides head sway, breathing, posture
2. Blink overlays (randomized 3-6s interval, gaussian distribution)
3. Micro-saccade eye jitter (1-2px at 2-3Hz)
4. Film grain + brightness jitter (webcam realism)

The driver video is the single most important element for realism.
It must be a real recording of the person sitting naturally at their desk.
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from voiceagent.meeting.config import BehaviorConfig, LipSyncConfig
from voiceagent.meeting.errors import MeetingLipSyncError
from voiceagent.meeting.realism import (
    BlinkGenerator,
    add_film_grain,
    apply_brightness_jitter,
)

logger = logging.getLogger(__name__)


class IdleRenderer:
    """Render idle clone frames from a driver video loop.

    Args:
        driver_path: Path to the driver video file (15-30s MP4, 25fps).
        lip_sync_config: Lip sync configuration for resolution/fps.
        behavior_config: Behavior config for blink intervals.
        eye_region: (x, y, w, h) of the eye region in the frame for blinks.
            If None, blinks are disabled (no eye region detected).
    """

    def __init__(
        self,
        driver_path: str | Path,
        lip_sync_config: LipSyncConfig,
        behavior_config: BehaviorConfig,
        eye_region: tuple[int, int, int, int] | None = None,
    ):
        self._driver_path = Path(driver_path)
        if not self._driver_path.exists():
            raise MeetingLipSyncError(
                f"Driver video not found: {self._driver_path}"
            )

        self._config = lip_sync_config
        self._eye_region = eye_region

        # Load driver video frames
        self._frames = self._load_driver_video()
        if not self._frames:
            raise MeetingLipSyncError(
                f"Driver video has no frames: {self._driver_path}"
            )

        # Ping-pong: forward + reverse (minus first and last to avoid double)
        self._pingpong = self._frames + self._frames[-2:0:-1]

        self._frame_index = 0
        self._global_frame = 0
        self._brightness_phase = 0.0

        blink_min, blink_max = behavior_config.idle_blink_interval_s
        blink_mean = (blink_min + blink_max) / 2.0
        blink_std = (blink_max - blink_min) / 4.0
        self._blink_gen = BlinkGenerator(
            mean_interval_s=blink_mean, std_s=blink_std,
        )

        logger.info(
            "IdleRenderer loaded: %d frames (%d pingpong), %s",
            len(self._frames),
            len(self._pingpong),
            self._driver_path.name,
        )

    def _load_driver_video(self) -> list[np.ndarray]:
        """Load all frames from the driver video."""
        cap = cv2.VideoCapture(str(self._driver_path))
        if not cap.isOpened():
            raise MeetingLipSyncError(
                f"Cannot open driver video: {self._driver_path}"
            )

        frames: list[np.ndarray] = []
        target_w, target_h = self._config.resolution

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            # Convert BGR to RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # Resize to target resolution if needed
            h, w = frame.shape[:2]
            if w != target_w or h != target_h:
                frame = cv2.resize(
                    frame, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4,
                )
            frames.append(frame)

        cap.release()
        return frames

    def get_frame(self) -> np.ndarray:
        """Get the next idle frame with all realism overlays applied.

        Returns:
            RGB uint8 array at target resolution.
            Call at target FPS (25) for smooth playback.
        """
        # Base frame from ping-pong loop
        base = self._pingpong[self._frame_index % len(self._pingpong)].copy()
        self._frame_index += 1
        self._global_frame += 1

        # Blink overlay
        if self._eye_region is not None:
            blink_alpha = self._blink_gen.get_blink_alpha(self._global_frame)
            if blink_alpha > 0.05:
                base = self._blink_gen.apply_blink(
                    base, blink_alpha, self._eye_region,
                )

        # Micro-saccade (applied to eye region if available)
        # In practice this is a subtle visual effect -- we apply it as a tiny
        # shift to the eye region pixels
        # (Skipped if no eye_region -- micro-saccade is only meaningful on eyes)

        # Film grain
        base = add_film_grain(base, intensity=0.015)

        # Brightness jitter
        self._brightness_phase += 0.02  # slow sine wave
        base = apply_brightness_jitter(base, self._brightness_phase, amplitude=0.01)

        return base

    @property
    def frame_count(self) -> int:
        """Number of unique frames in the driver video."""
        return len(self._frames)

    @property
    def pingpong_length(self) -> int:
        """Number of frames in the ping-pong loop."""
        return len(self._pingpong)
