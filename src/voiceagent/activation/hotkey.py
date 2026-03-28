"""Global hotkey activation for push-to-talk.

IMPORTANT: pynput requires X11 or Wayland on Linux. In headless environments
(CI, WSL2 without X server, Docker), this module will raise ActivationError
on start().
"""
import logging
from collections.abc import Callable

from voiceagent.errors import ActivationError

logger = logging.getLogger(__name__)


class HotkeyActivator:
    """Global hotkey listener for push-to-talk activation."""

    def __init__(
        self,
        key_combo: str = "<ctrl>+<space>",
        callback: Callable[[], None] | None = None,
    ) -> None:
        try:
            import pynput  # noqa: F401
        except ImportError as err:
            raise ImportError(
                "pynput is required for hotkey activation. "
                "Install with: pip install pynput"
            ) from err
        self.callback = callback
        self._key_combo = key_combo
        self._listener = None
        logger.info("HotkeyActivator created: key_combo=%s", key_combo)

    def _on_activate(self) -> None:
        logger.info("Hotkey activated: %s", self._key_combo)
        if self.callback is None:
            logger.warning(
                "Hotkey fired but callback is None. "
                "Fix: pass callback= to constructor or set activator.callback = func"
            )
            return
        try:
            self.callback()
        except Exception as e:
            logger.error("Hotkey callback raised exception: %s", e)

    def start(self) -> None:
        if self._listener is not None:
            logger.warning("start() called while already running. Stopping old listener.")
            self.stop()
        try:
            from pynput.keyboard import GlobalHotKeys
            self._listener = GlobalHotKeys({self._key_combo: self._on_activate})
            self._listener.daemon = True
            self._listener.start()
            logger.info("Hotkey listener started: %s", self._key_combo)
        except Exception as e:
            self._listener = None
            raise ActivationError(
                f"Failed to start hotkey listener. "
                f"What: pynput could not initialize keyboard listener. "
                f"Why: {e}. "
                f"Fix: pynput requires X11 or Wayland on Linux. "
                f"In WSL2, install an X server and set DISPLAY=:0."
            ) from e

    def stop(self) -> None:
        if self._listener is None:
            return
        try:
            self._listener.stop()
            logger.info("Hotkey listener stopped")
        except Exception as e:
            logger.warning("Error stopping hotkey listener: %s", e)
        finally:
            self._listener = None
