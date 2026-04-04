"""Browser-based meeting bot for Google Meet and Microsoft Teams — Mode 2.

Uses Playwright with a PERSISTENT browser context (saved Google account
session) to join meetings as a signed-in participant. This is how every
production meeting bot works (tl;dv, Otter, Fireflies, Recall.ai).

Setup (one-time):
    python -m voiceagent meeting setup-account
    # Opens a real browser → user logs into a Google account → session saved

Join (automatic, uses saved session):
    python -m voiceagent meeting join --url https://meet.google.com/xxx --name "AI Notes"
    # Bot opens Meet as signed-in user → "AI Notes wants to join" → host admits

Requirements:
    pip install playwright
    playwright install chromium
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np

from voiceagent.meeting.config import BrowserBotConfig
from voiceagent.meeting.errors import MeetingDeviceError

logger = logging.getLogger(__name__)

SESSION_DIR = "~/.voiceagent/browser-session"

# Google Meet selectors — updated for current Meet UI (2025-2026)
_GOOGLE_MEET_SELECTORS = {
    # Pre-join lobby selectors
    "ask_to_join": ['button:has-text("Ask to join")', 'button:has-text("Join now")'],
    "leave_button": ['button[aria-label="Leave call"]', '[data-tooltip="Leave call"]'],
    "mic_off": ['[aria-label*="Turn off microphone"]', '[data-tooltip*="Turn off microphone"]'],
    "cam_off": ['[aria-label*="Turn off camera"]', '[data-tooltip*="Turn off camera"]'],
    # In-meeting indicators
    "in_meeting": ['[data-meeting-title]', '[aria-label="Leave call"]'],
    # Name change (for signed-in users, name comes from Google account)
    "got_kicked": ['text="You\'ve been removed from the meeting"'],
    "meeting_ended": ['text="The meeting has ended"', 'text="You left the meeting"'],
}

_TEAMS_SELECTORS = {
    "name_input": 'input[data-tid="prejoin-display-name-input"]',
    "join_button": 'button[data-tid="prejoin-join-button"]',
    "leave_button": 'button#hang-up-button',
    "mic_off": 'button[aria-label*="Mute"]',
    "cam_off": 'button[aria-label*="Camera"]',
}


class BrowserBotSession:
    """Active browser-based meeting bot session."""

    def __init__(
        self,
        page: object,
        context: object,
        pw: object,
        display_name: str,
        platform: str,
    ) -> None:
        self._page = page
        self._context = context
        self._pw = pw
        self._display_name = display_name
        self._platform = platform
        self._connected = True

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def platform(self) -> str:
        return self._platform

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get_audio_stream(self) -> AsyncIterator[bytes]:
        """Receive meeting audio via PulseAudio capture.

        Yields PCM 16-bit mono 16kHz chunks.
        """
        if not self.is_connected:
            raise MeetingDeviceError("Browser bot is not connected")

        cmd = [
            "parec",
            "--device=auto_null.monitor",
            "--format=s16le",
            "--rate=16000",
            "--channels=1",
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        try:
            while self.is_connected:
                chunk = await proc.stdout.read(3200)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.kill()
            await proc.wait()

    async def send_audio(self, audio: np.ndarray, sample_rate: int = 44100) -> None:
        """Send audio to the meeting via PulseAudio."""
        if not self.is_connected:
            raise MeetingDeviceError("Browser bot is not connected")

        pcm = (audio * 32767).astype(np.int16).tobytes()

        proc = await asyncio.create_subprocess_exec(
            "pacat",
            "--format=s16le",
            f"--rate={sample_rate}",
            "--channels=1",
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        proc.stdin.write(pcm)
        await proc.stdin.drain()
        proc.stdin.close()
        await proc.wait()

    async def send_video_frame(
        self, frame: np.ndarray, width: int, height: int,
    ) -> None:
        """Not supported for browser bots."""
        raise MeetingDeviceError(
            "Video frame injection not supported for browser bots. "
            "Use Zoom SDK for real-time video output."
        )

    async def leave(self) -> None:
        """Leave the meeting."""
        if not self._connected:
            return

        # Try clicking leave button
        for selector in _GOOGLE_MEET_SELECTORS["leave_button"]:
            try:
                btn = self._page.locator(selector).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await asyncio.sleep(1)
                    break
            except Exception:
                continue

        try:
            await self._context.close()
        except Exception:
            pass

        try:
            await self._pw.stop()
        except Exception:
            pass

        self._connected = False
        logger.info("Browser bot left %s meeting", self._platform)


def get_session_dir() -> Path:
    """Get the persistent browser session directory."""
    return Path(SESSION_DIR).expanduser()


def has_saved_session() -> bool:
    """Check if a saved Google session exists."""
    session_dir = get_session_dir()
    # Playwright persistent context stores cookies, localStorage etc in this dir
    return session_dir.exists() and any(session_dir.iterdir())


async def setup_google_account() -> None:
    """Interactive setup: open a real browser for user to log into Google.

    The user logs into their Google account (or a dedicated bot account).
    The session is saved to ~/.voiceagent/browser-session/ and reused
    for all future meeting joins.

    This is a ONE-TIME setup. Run again only if the session expires.

    Raises:
        MeetingDeviceError: If Playwright is not installed.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise MeetingDeviceError(
            "Playwright required. Install: pip install playwright && playwright install chromium"
        ) from e

    session_dir = get_session_dir()
    session_dir.mkdir(parents=True, exist_ok=True)

    print()
    print("=" * 60)
    print("  Google Account Setup for Meeting Bot")
    print("=" * 60)
    print()
    print("A browser window will open. Log into the Google account")
    print("you want the bot to use when joining meetings.")
    print()
    print("This can be:")
    print("  - A dedicated bot account (e.g., my-ai-bot@gmail.com)")
    print("  - Your own account (the bot joins as you)")
    print()
    print("After logging in, close the browser window or press")
    print("Ctrl+C. The session will be saved automatically.")
    print()
    print(f"Session saved to: {session_dir}")
    print("=" * 60)
    print()

    pw = await async_playwright().start()

    # Launch persistent context — this saves ALL browser state
    # (cookies, localStorage, sessionStorage) to the session_dir
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(session_dir),
        headless=False,  # MUST be visible for user to log in
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
        ],
        viewport={"width": 1280, "height": 720},
        locale="en-US",
    )

    page = context.pages[0] if context.pages else await context.new_page()

    # Remove automation detection
    await page.add_init_script(
        'Object.defineProperty(navigator, "webdriver", { get: () => false });'
    )

    # Navigate to Google sign-in
    await page.goto("https://accounts.google.com", wait_until="networkidle")

    print("Browser opened. Log into your Google account now.")
    print("When done, close the browser window.")

    # Wait for the browser to be closed by the user
    try:
        await context.pages[0].wait_for_event("close", timeout=300000)  # 5 min
    except Exception:
        pass

    try:
        await context.close()
    except Exception:
        pass

    await pw.stop()

    print()
    if has_saved_session():
        print("Session saved successfully!")
        print("You can now join meetings with:")
        print('  python -m voiceagent meeting join --url <meet_url> --name "AI Notes"')
    else:
        print("WARNING: No session data found. Login may not have completed.")
        print("Run setup-account again.")


class BrowserBotJoin:
    """Join a Google Meet or Teams meeting using a saved browser session.

    The bot uses a persistent Playwright context with a previously
    saved Google account session. This is how production meeting bots
    (tl;dv, Otter, Fireflies) work.

    Setup required: python -m voiceagent meeting setup-account

    Args:
        config: Browser bot configuration.
    """

    def __init__(self, config: BrowserBotConfig) -> None:
        self._config = config

    async def join(
        self,
        url: str,
        display_name: str = "AI Notes",
        platform: str = "google_meet",
    ) -> BrowserBotSession:
        """Join a meeting using the saved Google session.

        Args:
            url: Meeting URL.
            display_name: Display name (for Google Meet, this is the
                Google account name unless the meeting allows name changes).
            platform: 'google_meet' or 'teams'.

        Returns:
            BrowserBotSession for audio I/O.

        Raises:
            MeetingDeviceError: If no saved session, Playwright not installed,
                or join fails.
        """
        if not has_saved_session():
            raise MeetingDeviceError(
                "No saved Google session found. Run setup first:\n"
                "  python -m voiceagent meeting setup-account\n"
                "This opens a browser for you to log into a Google account. "
                "The session is saved and reused for all future joins."
            )

        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise MeetingDeviceError(
                "Playwright required. Install: pip install playwright && "
                "playwright install chromium"
            ) from e

        session_dir = get_session_dir()
        pw = await async_playwright().start()

        logger.info("Launching browser with saved session from %s", session_dir)

        # Launch with saved session — bot is already signed into Google
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(session_dir),
            headless=self._config.headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
            ],
            viewport={"width": 1280, "height": 720},
            locale="en-US",
            permissions=["camera", "microphone"],
        )

        page = context.pages[0] if context.pages else await context.new_page()

        # Anti-detection
        await page.add_init_script(
            'Object.defineProperty(navigator, "webdriver", { get: () => false });'
        )

        # Navigate to the meeting
        logger.info("Navigating to %s: %s", platform, url)
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for page to settle
        await asyncio.sleep(3)

        # Screenshot for debugging
        debug_path = Path("/tmp/meet_bot_debug.png")
        await page.screenshot(path=str(debug_path))
        logger.info("Debug screenshot: %s", debug_path)

        if platform == "google_meet":
            await self._join_google_meet(page, display_name)
        else:
            await self._join_teams(page, display_name)

        logger.info("Bot joined %s as '%s'", platform, display_name)

        return BrowserBotSession(
            page=page,
            context=context,
            pw=pw,
            display_name=display_name,
            platform=platform,
        )

    async def _join_google_meet(self, page: object, display_name: str) -> None:
        """Handle the Google Meet join flow for a signed-in user."""

        # Turn off camera and mic before joining
        for selector_list in [
            _GOOGLE_MEET_SELECTORS["cam_off"],
            _GOOGLE_MEET_SELECTORS["mic_off"],
        ]:
            for sel in selector_list:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        logger.info("Toggled off: %s", sel)
                        await asyncio.sleep(0.5)
                        break
                except Exception:
                    continue

        # Click "Ask to join" or "Join now"
        joined = False
        for sel in _GOOGLE_MEET_SELECTORS["ask_to_join"]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=5000):
                    await btn.click()
                    logger.info("Clicked join: %s", sel)
                    joined = True
                    break
            except Exception:
                continue

        if not joined:
            # Take screenshot for debugging
            await page.screenshot(path="/tmp/meet_bot_join_failed.png")
            page_text = await page.inner_text("body")
            raise MeetingDeviceError(
                f"Could not find join button on Google Meet. "
                f"Page text: {page_text[:300]}. "
                f"Screenshot: /tmp/meet_bot_join_failed.png. "
                f"Make sure setup-account was completed and the Google "
                f"session is still valid."
            )

        # Wait to be admitted (host needs to click "Admit")
        logger.info("Waiting to be admitted to the meeting...")
        print("Bot clicked 'Ask to join'. Waiting for host to admit...")

        # Wait up to 60s for the meeting to load (host admits the bot)
        admitted = False
        for _ in range(60):
            await asyncio.sleep(1)
            for sel in _GOOGLE_MEET_SELECTORS["in_meeting"]:
                try:
                    elem = page.locator(sel).first
                    if await elem.is_visible(timeout=500):
                        admitted = True
                        break
                except Exception:
                    continue
            if admitted:
                break

            # Check if we got kicked
            for sel in _GOOGLE_MEET_SELECTORS.get("got_kicked", []):
                try:
                    if await page.locator(sel).first.is_visible(timeout=200):
                        raise MeetingDeviceError(
                            "Bot was removed from the meeting by the host."
                        )
                except MeetingDeviceError:
                    raise
                except Exception:
                    continue

        if not admitted:
            await page.screenshot(path="/tmp/meet_bot_not_admitted.png")
            raise MeetingDeviceError(
                "Bot was not admitted to the meeting within 60 seconds. "
                "The host needs to click 'Admit' in Google Meet. "
                "Screenshot: /tmp/meet_bot_not_admitted.png"
            )

        logger.info("Bot admitted to the meeting!")
        print("Bot is in the meeting!")

    async def _join_teams(self, page: object, display_name: str) -> None:
        """Handle the Microsoft Teams join flow."""
        try:
            name_input = page.locator(_TEAMS_SELECTORS["name_input"])
            await name_input.wait_for(state="visible", timeout=15000)
            await name_input.clear()
            await name_input.fill(display_name)

            join_btn = page.locator(_TEAMS_SELECTORS["join_button"])
            await join_btn.click(timeout=10000)

            await asyncio.sleep(5)
        except Exception as e:
            await page.screenshot(path="/tmp/teams_bot_join_failed.png")
            raise MeetingDeviceError(
                f"Failed to join Teams meeting: {e}. "
                f"Screenshot: /tmp/teams_bot_join_failed.png"
            ) from e
