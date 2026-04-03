"""Human meeting behavior simulation.

Controls:
1. Virtual mic silence/audio routing
2. App-level mute/unmute via xdotool
3. Comfort noise generation for mic keepalive
4. Natural speaking timing (pre/post pauses)
"""
from __future__ import annotations

import asyncio
import logging

import numpy as np

from voiceagent.meeting.app_controller import MeetingAppController
from voiceagent.meeting.config import BehaviorConfig
from voiceagent.meeting.errors import MeetingBehaviorError

logger = logging.getLogger(__name__)


class MeetingBehavior:
    """Manages clone's meeting behavior -- mute/unmute, comfort noise, timing.

    Two-layer mute control:

    Layer 1 (audio):
        Virtual mic receives silence by default. TTS audio only routed
        during active response.

    Layer 2 (app):
        xdotool sends mute/unmute shortcut to Zoom/Meet/Teams.
        If this fails, Layer 1 still prevents audio leaks.
    """

    def __init__(
        self,
        config: BehaviorConfig,
        platform: str = "auto",
    ) -> None:
        """Initialize meeting behavior controller.

        Args:
            config: Behavior configuration (mute timing, comfort noise, etc.).
            platform: Meeting platform name or "auto" for detection.
        """
        self._config = config
        self._app_controller = MeetingAppController(platform=platform)
        self._is_muted = config.default_muted

    @staticmethod
    def generate_comfort_noise(
        duration_ms: int = 100,
        sample_rate: int = 44100,
        dbfs: int = -60,
    ) -> np.ndarray:
        """Generate near-silent comfort noise for virtual mic keepalive.

        Prevents "no mic signal" warnings in meeting apps while being
        imperceptible to participants.

        Args:
            duration_ms: Noise duration in milliseconds.
            sample_rate: Audio sample rate in Hz.
            dbfs: Noise level in dBFS (-60 = imperceptible).

        Returns:
            Float32 numpy array of comfort noise samples.
        """
        samples = int(sample_rate * duration_ms / 1000)
        amplitude = 10 ** (dbfs / 20.0)  # dBFS to linear conversion
        return (np.random.randn(samples) * amplitude).astype(np.float32)

    async def unmute_and_speak(
        self,
        audio: np.ndarray,
        play_fn,
    ) -> None:
        """Full speaking sequence: unmute -> pause -> play -> pause -> mute.

        Args:
            audio: Float32 audio array to play through virtual mic.
            play_fn: Async callable that plays audio to the virtual mic
                sink. Signature: async play_fn(audio: np.ndarray) -> None.

        Raises:
            MeetingBehaviorError: If play_fn fails during audio playback.
        """
        # Pre-speech pause (natural delay before speaking)
        pre_ms = self._config.unmute_before_speak_ms

        # Unmute in meeting app (Layer 2)
        if self._is_muted:
            self._app_controller.unmute()
            self._is_muted = False
            await asyncio.sleep(pre_ms / 1000.0)

        # Play TTS audio through virtual mic (Layer 1)
        try:
            await play_fn(audio)
        except Exception as e:
            raise MeetingBehaviorError(
                f"Failed to play audio: {e}"
            ) from e

        # Post-speech pause (natural delay after finishing)
        post_ms = self._config.mute_after_speak_ms
        await asyncio.sleep(post_ms / 1000.0)

        # Re-mute (Layer 2)
        self._app_controller.mute()
        self._is_muted = True

        logger.debug(
            "Speak cycle complete: pre=%dms, post=%dms", pre_ms, post_ms
        )

    @property
    def is_muted(self) -> bool:
        """Whether the clone is currently muted."""
        return self._is_muted

    @property
    def platform(self) -> str:
        """The detected or configured meeting platform."""
        return self._app_controller.platform
