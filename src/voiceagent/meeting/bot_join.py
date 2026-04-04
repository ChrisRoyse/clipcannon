"""Unified meeting bot join interface — Mode 2.

Detects the meeting platform from the URL and routes to the
appropriate bot implementation (Zoom SDK or Playwright browser).

The bot joins the meeting as a separate participant with a custom
display name. No virtual webcam or audio devices needed on the host.

Usage:
    bot = MeetingBotJoiner(config)
    session = await bot.join(url="https://zoom.us/j/123", display_name="AI Notes")
    async for audio_chunk in session.get_audio_stream():
        process(audio_chunk)
    await session.send_audio(tts_output)
    await session.leave()
"""
from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

import numpy as np

from voiceagent.meeting.config import BotJoinConfig
from voiceagent.meeting.errors import MeetingDeviceError

logger = logging.getLogger(__name__)


@runtime_checkable
class MeetingBotSession(Protocol):
    """Protocol for a connected meeting bot session.

    Both ZoomBotSession and BrowserBotSession implement this interface.
    """

    @property
    def display_name(self) -> str:
        """The display name shown in the meeting participant list."""
        ...

    @property
    def platform(self) -> str:
        """The meeting platform: 'zoom', 'google_meet', 'teams'."""
        ...

    @property
    def is_connected(self) -> bool:
        """Whether the bot is currently in the meeting."""
        ...

    async def get_audio_stream(self) -> AsyncIterator[bytes]:
        """Receive mixed audio from all participants.

        Yields PCM 16-bit mono 16kHz audio chunks.
        """
        ...

    async def send_audio(self, audio: np.ndarray, sample_rate: int = 44100) -> None:
        """Send audio to the meeting (TTS output).

        Args:
            audio: Float32 audio array.
            sample_rate: Audio sample rate in Hz.
        """
        ...

    async def send_video_frame(
        self, frame: np.ndarray, width: int, height: int,
    ) -> None:
        """Send a video frame to the meeting.

        Args:
            frame: RGB uint8 array [H, W, 3].
            width: Frame width.
            height: Frame height.

        Not supported on all platforms (Playwright has limited video support).
        Raises MeetingDeviceError if not supported.
        """
        ...

    async def leave(self) -> None:
        """Leave the meeting gracefully."""
        ...


def detect_platform(url: str) -> str:
    """Detect meeting platform from URL.

    Args:
        url: Meeting URL (e.g., https://zoom.us/j/123, https://meet.google.com/abc).

    Returns:
        Platform string: 'zoom', 'google_meet', 'teams', or 'unknown'.
    """
    url_lower = url.lower()

    if re.search(r"zoom\.(us|com)", url_lower):
        return "zoom"
    if "meet.google.com" in url_lower:
        return "google_meet"
    if "teams.microsoft.com" in url_lower or "teams.live.com" in url_lower:
        return "teams"

    return "unknown"


class MeetingBotJoiner:
    """Join a meeting as a bot participant with a custom display name.

    Auto-detects the platform from the meeting URL and routes to
    the appropriate bot implementation.

    Args:
        config: Bot join configuration with SDK credentials.
    """

    def __init__(self, config: BotJoinConfig):
        self._config = config

    async def join(
        self,
        url: str,
        display_name: str | None = None,
        send_video: bool = True,
    ) -> MeetingBotSession:
        """Join a meeting and return a session handle.

        Args:
            url: Meeting URL.
            display_name: Name to show in participant list.
                Defaults to config.default_display_name.
            send_video: Whether to send video frames (Zoom SDK only).

        Returns:
            MeetingBotSession for audio/video I/O.

        Raises:
            MeetingDeviceError: If platform not supported or SDK not available.
        """
        name = display_name or self._config.default_display_name
        platform = detect_platform(url)

        if platform == "zoom":
            return await self._join_zoom(url, name, send_video)
        if platform in ("google_meet", "teams"):
            return await self._join_browser(url, name, platform)

        raise MeetingDeviceError(
            f"Cannot detect meeting platform from URL: {url}. "
            f"Supported: Zoom (zoom.us), Google Meet (meet.google.com), "
            f"Teams (teams.microsoft.com)"
        )

    async def _join_zoom(
        self, url: str, display_name: str, send_video: bool,
    ) -> MeetingBotSession:
        """Join a Zoom meeting via Meeting SDK."""
        from voiceagent.meeting.zoom_bot import ZoomBotJoin

        client_id = self._config.zoom_sdk.client_id
        client_secret = self._config.zoom_sdk.client_secret

        if not client_id or not client_secret:
            raise MeetingDeviceError(
                "Zoom Meeting SDK credentials not configured. "
                "Set bot_join.zoom_sdk.client_id and client_secret in "
                "~/.voiceagent/meeting.json. Get free credentials at "
                "https://marketplace.zoom.us"
            )

        bot = ZoomBotJoin(client_id=client_id, client_secret=client_secret)
        return await bot.join(url=url, display_name=display_name, send_video=send_video)

    async def _join_browser(
        self, url: str, display_name: str, platform: str,
    ) -> MeetingBotSession:
        """Join a Google Meet or Teams meeting via Playwright browser."""
        from voiceagent.meeting.browser_bot import BrowserBotJoin

        bot = BrowserBotJoin(config=self._config.browser_bot)
        return await bot.join(url=url, display_name=display_name, platform=platform)
