"""Tests for voiceagent.filler_audio module."""
import pytest

from voiceagent.filler_audio import (
    ALL_PHRASES,
    FILLER_PHRASES,
    FillerAudioCache,
    FillerClip,
)


def test_filler_phrases_has_all_categories():
    assert "question" in FILLER_PHRASES
    assert "command" in FILLER_PHRASES
    assert "generic" in FILLER_PHRASES


def test_all_phrases_flattened():
    total = sum(len(v) for v in FILLER_PHRASES.values())
    assert len(ALL_PHRASES) == total


def test_filler_clip_dataclass():
    clip = FillerClip(
        phrase="Sure.",
        audio_int16=b"\x00" * 100,
        duration_ms=500,
        category="command",
    )
    assert clip.phrase == "Sure."
    assert clip.duration_ms == 500
    assert clip.category == "command"


def test_cache_not_ready_initially():
    cache = FillerAudioCache()
    assert not cache.ready
    assert cache.get_filler() is None


def test_classify_question():
    cache = FillerAudioCache()
    assert cache.classify_context("What time is it?") == "question"
    assert cache.classify_context("how are you doing") == "question"
    assert cache.classify_context("Can you help me?") == "question"
    assert cache.classify_context("Is it raining?") == "question"


def test_classify_command():
    cache = FillerAudioCache()
    assert cache.classify_context("tell me a joke") == "command"
    assert cache.classify_context("play some music") == "command"
    assert cache.classify_context("search for restaurants") == "command"


def test_classify_generic():
    cache = FillerAudioCache()
    assert cache.classify_context("I had a good day") == "generic"
    assert cache.classify_context("yeah that makes sense") == "generic"


def test_each_category_has_at_least_two_phrases():
    for category, phrases in FILLER_PHRASES.items():
        assert len(phrases) >= 2, f"{category} needs >= 2 phrases"
