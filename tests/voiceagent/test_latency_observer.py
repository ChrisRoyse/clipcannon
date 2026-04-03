"""Tests for voiceagent.latency_observer module."""
import asyncio

import pytest

from voiceagent.latency_observer import LatencyObserver


@pytest.fixture
def observer():
    return LatencyObserver()


def test_observer_initializes():
    obs = LatencyObserver()
    assert obs._turn_count == 0
    assert obs._turn_active is False


@pytest.mark.asyncio
async def test_user_started_speaking_activates_turn(observer):
    from pipecat.frames.frames import UserStartedSpeakingFrame

    frame = UserStartedSpeakingFrame()
    await observer.on_push_frame(None, frame, None, None)
    assert observer._turn_active is True


@pytest.mark.asyncio
async def test_user_stopped_speaking_records_time(observer):
    from pipecat.frames.frames import (
        UserStartedSpeakingFrame,
        UserStoppedSpeakingFrame,
    )

    await observer.on_push_frame(None, UserStartedSpeakingFrame(), None, None)
    await observer.on_push_frame(None, UserStoppedSpeakingFrame(), None, None)
    assert observer._user_stop > 0
    assert observer._user_stop >= observer._user_start
