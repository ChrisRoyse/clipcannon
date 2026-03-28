"""Tests for build_system_prompt()."""
from datetime import datetime

import pytest

from voiceagent.brain.prompts import build_system_prompt


def test_prompt_contains_identity():
    assert "Chris Royse" in build_system_prompt("boris")

def test_prompt_contains_voice_name():
    assert "boris" in build_system_prompt("boris")

def test_prompt_contains_custom_voice():
    p = build_system_prompt("echo")
    assert "echo" in p
    assert "boris" not in p

def test_prompt_contains_datetime_auto():
    today = datetime.now().strftime("%Y-%m-%d")
    assert today in build_system_prompt("boris")

def test_prompt_contains_datetime_injected():
    p = build_system_prompt("boris", datetime_str="2026-03-28T14:30:00")
    assert "2026-03-28T14:30:00" in p

def test_prompt_contains_brevity_rule():
    assert "1-3 sentences" in build_system_prompt("boris")

def test_prompt_contains_clarifying_rule():
    assert "clarifying questions" in build_system_prompt("boris")

def test_prompt_contains_honesty_rule():
    assert "I don't know" in build_system_prompt("boris")

def test_prompt_contains_security_rule():
    assert "never disclose" in build_system_prompt("boris").lower()

def test_prompt_returns_string():
    assert isinstance(build_system_prompt("boris"), str)

def test_empty_voice_name_raises():
    with pytest.raises(ValueError, match="voice_name must be a non-empty string"):
        build_system_prompt("")

def test_none_voice_name_raises():
    with pytest.raises(ValueError, match="voice_name must be a non-empty string"):
        build_system_prompt(None)

def test_deterministic_with_fixed_datetime():
    dt = "2026-01-01T00:00:00"
    assert build_system_prompt("boris", datetime_str=dt) == build_system_prompt("boris", datetime_str=dt)
