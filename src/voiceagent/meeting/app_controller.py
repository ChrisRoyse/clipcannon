"""Meeting app controller -- mute/unmute via xdotool keyboard shortcuts.

Detects which meeting app is running (Zoom, Google Meet, Teams) and
sends platform-specific keyboard shortcuts to toggle mute/unmute.

Layer 2 control -- Layer 1 is audio-level silence on the virtual mic.
If xdotool fails (e.g., Wayland), audio silence still prevents leaks.
"""
from __future__ import annotations

import logging
import subprocess

from voiceagent.meeting.errors import MeetingBehaviorError

logger = logging.getLogger(__name__)

# Platform-specific mute/unmute keyboard shortcuts
PLATFORM_SHORTCUTS: dict[str, str] = {
    "zoom": "alt+a",
    "google_meet": "ctrl+d",
    "teams": "ctrl+shift+m",
    "generic": "ctrl+m",
}

# Window title patterns for xdotool search
WINDOW_PATTERNS: dict[str, str] = {
    "zoom": "Zoom Meeting",
    "google_meet": "Meet -",
    "teams": "Microsoft Teams",
}


class MeetingAppController:
    """Control meeting app mute/unmute via keyboard shortcuts.

    Uses xdotool to find the meeting window and send keystrokes.
    Falls back gracefully when the meeting window is not found (Layer 1
    audio silence still prevents mic leaks).
    """

    def __init__(self, platform: str = "auto") -> None:
        """Initialize the controller.

        Args:
            platform: Meeting platform name ("zoom", "google_meet",
                "teams", "generic") or "auto" for auto-detection.
        """
        self._platform = (
            platform if platform != "auto" else self._detect_platform()
        )
        self._window_id: str | None = None
        logger.info("MeetingAppController: platform=%s", self._platform)

    @staticmethod
    def _detect_platform() -> str:
        """Auto-detect which meeting app is running.

        Returns:
            Platform identifier string, or "generic" if no known app
            is detected.
        """
        for platform, pattern in WINDOW_PATTERNS.items():
            try:
                result = subprocess.run(
                    ["xdotool", "search", "--name", pattern],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if result.stdout.strip():
                    logger.info(
                        "Detected meeting platform: %s", platform
                    )
                    return platform
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
        logger.warning(
            "No meeting app detected, using generic shortcuts"
        )
        return "generic"

    @property
    def platform(self) -> str:
        """The detected or configured meeting platform."""
        return self._platform

    def _find_window(self) -> str | None:
        """Find the meeting app window ID via xdotool.

        Returns:
            Window ID string, or None if not found.
        """
        pattern = WINDOW_PATTERNS.get(self._platform, "Meeting")
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", pattern],
                capture_output=True,
                text=True,
                timeout=3,
            )
            lines = result.stdout.strip().split("\n")
            if lines and lines[0]:
                return lines[0]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def _send_shortcut(self, shortcut: str) -> None:
        """Send a keyboard shortcut to the meeting window.

        Args:
            shortcut: X11 key combo string (e.g. "alt+a").

        Raises:
            MeetingBehaviorError: If xdotool is not installed.
        """
        window_id = self._find_window()
        if window_id is None:
            logger.warning(
                "Meeting window not found for %s -- skipping shortcut",
                self._platform,
            )
            return

        try:
            subprocess.run(
                [
                    "xdotool",
                    "windowactivate",
                    "--sync",
                    window_id,
                    "key",
                    "--clearmodifiers",
                    shortcut,
                ],
                capture_output=True,
                timeout=5,
            )
            logger.debug(
                "Sent shortcut '%s' to window %s", shortcut, window_id
            )
        except FileNotFoundError:
            raise MeetingBehaviorError(
                "xdotool not found. Install: apt install xdotool"
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "xdotool timed out sending '%s'", shortcut
            )

    def unmute(self) -> None:
        """Send unmute shortcut to meeting app."""
        shortcut = PLATFORM_SHORTCUTS.get(self._platform, "ctrl+m")
        self._send_shortcut(shortcut)

    def mute(self) -> None:
        """Send mute shortcut to meeting app (same toggle key)."""
        shortcut = PLATFORM_SHORTCUTS.get(self._platform, "ctrl+m")
        self._send_shortcut(shortcut)
