"""Tests for ContextManager."""
from voiceagent.brain.context import ContextManager


def test_empty_history():
    cm = ContextManager()
    msgs = cm.build_messages("You are helpful.", [], "Hello")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"


def test_short_history_all_included():
    cm = ContextManager()
    history = [
        {"role": "user", "content": "Hi there"},
        {"role": "assistant", "content": "Hello! How can I help?"},
        {"role": "user", "content": "Tell me a joke"},
        {"role": "assistant", "content": "Why did the chicken cross the road?"},
    ]
    msgs = cm.build_messages("System prompt", history, "Another question")
    assert len(msgs) == 6
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["content"] == "Another question"
    assert msgs[1]["content"] == "Hi there"


def test_truncates_oldest():
    cm = ContextManager()
    long_turn = "A" * 600
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": long_turn}
        for i in range(210)
    ]
    msgs = cm.build_messages("test", history, "Hi")
    assert len(msgs) < 212
    assert len(msgs) >= 3
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["content"] == "Hi"


def test_50_turns_fit():
    cm = ContextManager()
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": "Hello"}
        for i in range(50)
    ]
    msgs = cm.build_messages("You are a helpful voice assistant.", history, "Hi")
    assert len(msgs) == 52


def test_count_tokens_fallback():
    cm = ContextManager()
    assert cm._count_tokens("") == 0
    assert cm._count_tokens("test") == 1
    assert cm._count_tokens("a" * 100) == 25


def test_message_order():
    cm = ContextManager()
    history = [
        {"role": "user", "content": "First"},
        {"role": "assistant", "content": "Second"},
    ]
    msgs = cm.build_messages("sys", history, "Third")
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1] == {"role": "user", "content": "First"}
    assert msgs[2] == {"role": "assistant", "content": "Second"}
    assert msgs[3] == {"role": "user", "content": "Third"}


def test_single_huge_turn_dropped():
    cm = ContextManager()
    history = [{"role": "assistant", "content": "X" * 200000}]
    msgs = cm.build_messages("a", history, "b")
    assert len(msgs) == 2


def test_newest_preserved_oldest_dropped():
    cm = ContextManager()
    history = [{"role": "user", "content": f"Turn {i}: " + "X" * 600} for i in range(210)]
    msgs = cm.build_messages("test", history, "end")
    history_msgs = msgs[1:-1]
    assert "Turn 209" in history_msgs[-1]["content"]
    assert "Turn 0" not in history_msgs[0]["content"]


def test_constants():
    cm = ContextManager()
    assert cm.MAX_TOKENS == 32000
    assert cm.SYSTEM_RESERVE == 2000
    assert cm.RESPONSE_RESERVE == 512
    assert cm.HISTORY_BUDGET == 29488
