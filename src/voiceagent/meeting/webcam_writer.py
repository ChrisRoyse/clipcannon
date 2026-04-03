"""Virtual webcam frame writer.

Writes RGB frames to a v4l2loopback virtual webcam device (Mode 1)
or delivers frames to the Zoom SDK raw video interface (Mode 2).

Runs at a continuous 25 FPS -- feeds idle frames when not speaking,
lip-synced frames when speaking.
"""
from __future__ import annotations

import logging

import numpy as np

from voiceagent.meeting.errors import MeetingDeviceError

logger = logging.getLogger(__name__)


class WebcamWriter:
    """Write frames to a virtual webcam device.

    Args:
        device: v4l2loopback device path (e.g., "/dev/video20").
        width: Frame width in pixels.
        height: Frame height in pixels.
        fps: Target frame rate.
    """

    def __init__(
        self, device: str, width: int = 1280, height: int = 720, fps: int = 25,
    ):
        self._device = device
        self._width = width
        self._height = height
        self._fps = fps
        self._cam = None

    def start(self) -> None:
        """Open the virtual webcam device.

        Raises:
            MeetingDeviceError: If pyvirtualcam is not installed or device
                not available.
        """
        try:
            import pyvirtualcam
        except ImportError as e:
            raise MeetingDeviceError(
                "pyvirtualcam required. Install: pip install pyvirtualcam. "
                "Also need v4l2loopback: sudo modprobe v4l2loopback devices=1 "
                "exclusive_caps=1"
            ) from e

        try:
            self._cam = pyvirtualcam.Camera(
                width=self._width,
                height=self._height,
                fps=self._fps,
                device=self._device,
            )
            logger.info(
                "Webcam writer started: %s (%dx%d @ %dfps)",
                self._device,
                self._width,
                self._height,
                self._fps,
            )
        except Exception as e:
            raise MeetingDeviceError(
                f"Failed to open virtual webcam at {self._device}: {e}. "
                f"Ensure v4l2loopback is loaded: sudo modprobe v4l2loopback "
                f"devices=1 exclusive_caps=1 video_nr=20 card_label='Clone'"
            ) from e

    def write_frame(self, frame: np.ndarray) -> None:
        """Write a single RGB frame to the virtual webcam.

        Args:
            frame: RGB uint8 array [H, W, 3] matching configured resolution.

        Raises:
            MeetingDeviceError: If not started or frame dimensions mismatch.
        """
        if self._cam is None:
            raise MeetingDeviceError(
                "WebcamWriter not started. Call start() first."
            )
        if frame.shape != (self._height, self._width, 3):
            raise MeetingDeviceError(
                f"Frame shape mismatch: expected "
                f"({self._height}, {self._width}, 3), got {frame.shape}"
            )
        self._cam.send(frame)

    def stop(self) -> None:
        """Close the virtual webcam device."""
        if self._cam is not None:
            try:
                self._cam.close()
            except Exception:
                pass
            self._cam = None
            logger.info("Webcam writer stopped: %s", self._device)

    @property
    def is_running(self) -> bool:
        """Whether the virtual webcam device is currently open."""
        return self._cam is not None
