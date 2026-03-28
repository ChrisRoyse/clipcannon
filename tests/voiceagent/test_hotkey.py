"""Tests for hotkey activator."""
import logging
import os

import pytest

pynput = pytest.importorskip("pynput", reason="pynput not installed")

from voiceagent.activation.hotkey import HotkeyActivator  # noqa: E402

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def test_hotkey_instantiates():
    activator = HotkeyActivator()
    assert activator._key_combo == "<ctrl>+<space>"
    assert activator.callback is None
    assert activator._listener is None


def test_hotkey_with_callback():
    flag = []
    activator = HotkeyActivator(callback=lambda: flag.append(True))
    assert activator.callback is not None


def test_hotkey_custom_key_combo():
    activator = HotkeyActivator(key_combo="<ctrl>+<alt>+p")
    assert activator._key_combo == "<ctrl>+<alt>+p"


def test_stop_without_start_is_noop():
    activator = HotkeyActivator()
    activator.stop()
    assert activator._listener is None


def test_stop_called_twice_is_safe():
    activator = HotkeyActivator()
    activator.stop()
    activator.stop()


def test_on_activate_with_callback():
    flag = []
    activator = HotkeyActivator(callback=lambda: flag.append(True))
    activator._on_activate()
    assert flag == [True]


def test_on_activate_with_none_callback(caplog):
    activator = HotkeyActivator(callback=None)
    with caplog.at_level(logging.WARNING):
        activator._on_activate()
    assert "callback is None" in caplog.text


def test_on_activate_callback_exception_handled(caplog):
    def bad_callback():
        raise RuntimeError("boom")
    activator = HotkeyActivator(callback=bad_callback)
    with caplog.at_level(logging.ERROR):
        activator._on_activate()
    assert "callback raised exception" in caplog.text


@pytest.mark.skipif(not HAS_DISPLAY, reason="No display available")
def test_start_does_not_block():
    activator = HotkeyActivator()
    try:
        activator.start()
        assert activator._listener is not None
    finally:
        activator.stop()


@pytest.mark.skipif(HAS_DISPLAY, reason="Test only in headless")
def test_start_headless_raises():
    from voiceagent.errors import ActivationError
    activator = HotkeyActivator()
    with pytest.raises(ActivationError):
        activator.start()
