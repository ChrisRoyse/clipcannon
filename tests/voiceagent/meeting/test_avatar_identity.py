"""The meeting avatar answers to its own name, and the bot server only
takes Google Meet URLs from the Chrome extension or local tools."""

from __future__ import annotations

import pytest

from voiceagent.meeting import bot_server
from voiceagent.meeting.reasoning_controller import ReasoningController


def _addressed(controller, text):
    controller.observe(text)
    return controller.awareness.speaker_is_addressing_me


def test_avatar_answers_to_configured_name():
    c = ReasoningController(character_name="Nova")
    assert _addressed(c, "Nova, what do you think?")
    assert not _addressed(c, "Santa, what do you think?")


def test_aliases_count_as_address():
    c = ReasoningController(character_name="Santa", aliases=("mr. claus",))
    assert _addressed(c, "thanks Mr. Claus")


def test_name_must_be_a_whole_word():
    c = ReasoningController(character_name="Santa", aliases=("claus",))
    assert not _addressed(c, "this clause is fine")
    assert not _addressed(c, "santana is playing")


@pytest.mark.parametrize("url,ok", [
    ("https://meet.google.com/abc-defg-hij", True),
    ("https://meet.google.com/abc-defg-hij?authuser=1", True),
    ("http://meet.google.com/abc-defg-hij", False),
    ("https://meet.google.com.evil.com/abc-defg-hij", False),
    ("https://evil.com/abc-defg-hij", False),
    ("file:///etc/passwd", False),
])
def test_only_meet_urls_accepted(url, ok):
    assert bot_server.is_meet_url(url) is ok


@pytest.mark.parametrize("origin,ok", [
    (None, True),
    ("chrome-extension://abcdefghijklmnop", True),
    ("https://evil.com", False),
    ("null", False),
])
def test_only_extension_or_local_origins(origin, ok):
    assert bot_server.is_allowed_origin(origin) is ok
