"""Integration tests for ClipCannonAdapter -- REAL boris profile, NO MOCKS."""
import asyncio
import glob
import tempfile

import numpy as np
import pytest

from voiceagent.adapters.clipcannon import ClipCannonAdapter
from voiceagent.errors import TTSError


def test_adapter_loads_profile(session_tts_adapter):
    """Profile and reference audio must be present."""
    assert session_tts_adapter._profile is not None
    assert session_tts_adapter._profile["name"] == "boris"
    assert session_tts_adapter._reference_audio.exists()


def test_adapter_raises_on_missing_profile():
    """Non-existent profile must raise TTSError."""
    with pytest.raises(TTSError, match="not found"):
        ClipCannonAdapter(voice_name="nonexistent_voice_xyz_12345")


def test_synthesize_returns_float32(session_tts_adapter):
    """Synthesized audio must be 1-D float32 with reasonable length."""
    audio = asyncio.get_event_loop().run_until_complete(
        session_tts_adapter.synthesize("Hello world")
    )
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert len(audio) > 12000, f"Too short: {len(audio)} samples"
    assert len(audio) < 240000, f"Too long: {len(audio)} samples"
    print(f"Synthesized {len(audio)} samples ({len(audio) / 24000:.2f}s)")


def test_synthesize_empty_raises(session_tts_adapter):
    """Empty string must raise TTSError."""
    with pytest.raises(TTSError, match="empty"):
        asyncio.get_event_loop().run_until_complete(session_tts_adapter.synthesize(""))


def test_synthesize_whitespace_raises(session_tts_adapter):
    """Whitespace-only string must raise TTSError."""
    with pytest.raises(TTSError, match="empty"):
        asyncio.get_event_loop().run_until_complete(session_tts_adapter.synthesize("   "))


def test_temp_wav_cleaned(session_tts_adapter):
    """Temporary WAV file must be cleaned up after synthesis."""
    before = set(glob.glob(f"{tempfile.gettempdir()}/*.wav"))
    asyncio.get_event_loop().run_until_complete(
        session_tts_adapter.synthesize("Testing cleanup")
    )
    after = set(glob.glob(f"{tempfile.gettempdir()}/*.wav"))
    new = after - before
    assert len(new) == 0, f"Temp WAV not cleaned: {new}"


def test_release_no_raise():
    """release() must not raise even on a fresh adapter."""
    a = ClipCannonAdapter(voice_name="boris")
    a.release()
