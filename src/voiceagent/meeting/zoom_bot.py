"""Zoom Meeting SDK headless Linux bot — Mode 2.

Joins a Zoom meeting as a participant using the official Meeting SDK
for Linux. Runs headless (no GUI). Receives raw audio from all
participants and can send raw audio/video frames.

The Zoom Meeting SDK is free for joining meetings. Get credentials
at https://marketplace.zoom.us (free developer account).

SDK provides:
- IZoomSDKAudioRawDataHelper: receive/send raw PCM audio
- IZoomSDKVideoSource: send raw I420 video frames
- Custom display name at join time
- Headless Docker support

This module wraps the C++ SDK via subprocess (the SDK runs as a
separate process, communicating via stdin/stdout JSON protocol).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np

from voiceagent.meeting.errors import MeetingDeviceError

logger = logging.getLogger(__name__)

SDK_BINARY = "zoom-meeting-bot"  # Expected in PATH after SDK installation


def parse_zoom_url(url: str) -> tuple[str, str]:
    """Extract meeting ID and password from a Zoom URL.

    Args:
        url: Zoom meeting URL (e.g., https://zoom.us/j/123456789?pwd=abc).

    Returns:
        Tuple of (meeting_id, password). Password may be empty.

    Raises:
        MeetingDeviceError: If URL cannot be parsed.
    """
    match = re.search(r"/j/(\d+)", url)
    if not match:
        raise MeetingDeviceError(
            f"Cannot extract meeting ID from Zoom URL: {url}. "
            f"Expected format: https://zoom.us/j/MEETING_ID?pwd=PASSWORD"
        )
    meeting_id = match.group(1)

    pwd_match = re.search(r"[?&]pwd=([^&]+)", url)
    password = pwd_match.group(1) if pwd_match else ""

    return meeting_id, password


class ZoomBotSession:
    """Active Zoom meeting bot session.

    Communicates with the Zoom SDK process via stdin/stdout JSON lines.
    """

    def __init__(
        self,
        process: subprocess.Popen,
        display_name: str,
        meeting_id: str,
    ) -> None:
        self._process = process
        self._display_name = display_name
        self._meeting_id = meeting_id
        self._connected = True

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def platform(self) -> str:
        return "zoom"

    @property
    def is_connected(self) -> bool:
        return self._connected and self._process.poll() is None

    async def get_audio_stream(self) -> AsyncIterator[bytes]:
        """Receive mixed audio from the meeting.

        Yields PCM 16-bit mono 16kHz chunks read from the SDK process stdout.
        """
        if not self.is_connected:
            raise MeetingDeviceError("Zoom bot is not connected")

        loop = asyncio.get_event_loop()
        while self.is_connected:
            try:
                line = await loop.run_in_executor(
                    None, self._process.stdout.readline,
                )
                if not line:
                    break
                msg = json.loads(line)
                if msg.get("type") == "audio":
                    yield bytes.fromhex(msg["data"])
            except (json.JSONDecodeError, KeyError):
                continue

    async def send_audio(self, audio: np.ndarray, sample_rate: int = 44100) -> None:
        """Send audio to the meeting.

        Args:
            audio: Float32 audio array.
            sample_rate: Audio sample rate.
        """
        if not self.is_connected:
            raise MeetingDeviceError("Zoom bot is not connected")

        # Convert to 16-bit PCM
        pcm = (audio * 32767).astype(np.int16).tobytes()
        msg = json.dumps({
            "type": "send_audio",
            "data": pcm.hex(),
            "sample_rate": sample_rate,
        }) + "\n"

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._process.stdin.write, msg.encode(),
        )
        await loop.run_in_executor(None, self._process.stdin.flush)

    async def send_video_frame(
        self, frame: np.ndarray, width: int, height: int,
    ) -> None:
        """Send a video frame to the meeting (I420 format via SDK)."""
        if not self.is_connected:
            raise MeetingDeviceError("Zoom bot is not connected")

        msg = json.dumps({
            "type": "send_video",
            "data": frame.tobytes().hex(),
            "width": width,
            "height": height,
        }) + "\n"

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._process.stdin.write, msg.encode(),
        )
        await loop.run_in_executor(None, self._process.stdin.flush)

    async def leave(self) -> None:
        """Leave the meeting gracefully."""
        if not self.is_connected:
            return

        try:
            msg = json.dumps({"type": "leave"}) + "\n"
            self._process.stdin.write(msg.encode())
            self._process.stdin.flush()
            self._process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self._process.kill()
        finally:
            self._connected = False
            logger.info("Zoom bot left meeting %s", self._meeting_id)


class ZoomBotJoin:
    """Join a Zoom meeting as a headless bot participant.

    Requires the Zoom Meeting SDK for Linux to be installed.
    The SDK binary must be available as 'zoom-meeting-bot' in PATH.

    Args:
        client_id: Zoom Meeting SDK client ID.
        client_secret: Zoom Meeting SDK client secret.
    """

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret

    async def join(
        self,
        url: str,
        display_name: str = "AI Notes",
        send_video: bool = True,
    ) -> ZoomBotSession:
        """Join a Zoom meeting.

        Args:
            url: Zoom meeting URL.
            display_name: Name shown in participant list.
            send_video: Whether to enable video output.

        Returns:
            ZoomBotSession for audio/video I/O.

        Raises:
            MeetingDeviceError: If SDK not installed or join fails.
        """
        # Verify SDK binary exists
        sdk_path = self._find_sdk_binary()

        meeting_id, password = parse_zoom_url(url)

        cmd = [
            str(sdk_path),
            "--client-id", self._client_id,
            "--client-secret", self._client_secret,
            "--meeting-id", meeting_id,
            "--password", password,
            "--display-name", display_name,
            "--json-protocol",  # Use JSON lines on stdin/stdout
        ]

        if send_video:
            cmd.append("--enable-video")

        logger.info(
            "Joining Zoom meeting %s as '%s'...", meeting_id, display_name,
        )

        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
            )
        except FileNotFoundError:
            raise MeetingDeviceError(
                f"Zoom Meeting SDK binary not found: {sdk_path}. "
                f"Install the Zoom Meeting SDK for Linux: "
                f"https://github.com/zoom/meetingsdk-headless-linux-sample"
            )

        # Wait for the "joined" signal from the SDK process
        loop = asyncio.get_event_loop()
        try:
            line = await asyncio.wait_for(
                loop.run_in_executor(None, process.stdout.readline),
                timeout=30.0,
            )
            msg = json.loads(line)
            if msg.get("status") != "joined":
                stderr = process.stderr.read().decode(errors="replace")
                raise MeetingDeviceError(
                    f"Zoom SDK failed to join meeting: {msg}. stderr: {stderr[:500]}"
                )
        except asyncio.TimeoutError:
            process.kill()
            raise MeetingDeviceError(
                f"Zoom SDK timed out joining meeting {meeting_id} (30s). "
                f"Check credentials and meeting URL."
            )
        except (json.JSONDecodeError, ValueError) as e:
            process.kill()
            raise MeetingDeviceError(
                f"Zoom SDK returned invalid response: {e}"
            ) from e

        logger.info("Joined Zoom meeting %s as '%s'", meeting_id, display_name)
        return ZoomBotSession(
            process=process,
            display_name=display_name,
            meeting_id=meeting_id,
        )

    @staticmethod
    def _find_sdk_binary() -> Path:
        """Find the Zoom Meeting SDK binary.

        Raises:
            MeetingDeviceError: If not found.
        """
        import shutil
        path = shutil.which(SDK_BINARY)
        if path:
            return Path(path)

        # Check common install locations
        candidates = [
            Path.home() / ".zoom-sdk" / SDK_BINARY,
            Path("/usr/local/bin") / SDK_BINARY,
            Path("/opt/zoom-sdk") / SDK_BINARY,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate

        raise MeetingDeviceError(
            f"Zoom Meeting SDK binary '{SDK_BINARY}' not found. "
            f"Install the SDK: https://github.com/zoom/meetingsdk-headless-linux-sample "
            f"and ensure '{SDK_BINARY}' is in your PATH."
        )
