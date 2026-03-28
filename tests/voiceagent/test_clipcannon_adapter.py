"""Integration tests for ClipCannonAdapter -- REAL boris profile, NO MOCKS."""
import asyncio
import glob
import tempfile

import numpy as np
import pytest

from voiceagent.adapters.clipcannon import ClipCannonAdapter
from voiceagent.errors import TTSError


@pytest.fixture(scope="module")
def adapter():
    """Create a shared adapter for the module (loads model once)."""
    a = ClipCannonAdapter(voice_name="boris")
    yield a
    a.release()


def test_adapter_loads_profile(adapter):
    """Profile and reference audio must be present."""
    assert adapter._profile is not None
    assert adapter._profile["name"] == "boris"
    assert adapter._reference_audio.exists()


def test_adapter_raises_on_missing_profile():
    """Non-existent profile must raise TTSError."""
    with pytest.raises(TTSError, match="not found"):
        ClipCannonAdapter(voice_name="nonexistent_voice_xyz_12345")


def test_synthesize_returns_float32(adapter):
    """Synthesized audio must be 1-D float32 with reasonable length."""
    audio = asyncio.get_event_loop().run_until_complete(
        adapter.synthesize("Hello world")
    )
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert len(audio) > 12000, f"Too short: {len(audio)} samples"
    assert len(audio) < 240000, f"Too long: {len(audio)} samples"
    print(f"Synthesized {len(audio)} samples ({len(audio) / 24000:.2f}s)")


def test_synthesize_empty_raises(adapter):
    """Empty string must raise TTSError."""
    with pytest.raises(TTSError, match="empty"):
        asyncio.get_event_loop().run_until_complete(adapter.synthesize(""))


def test_synthesize_whitespace_raises(adapter):
    """Whitespace-only string must raise TTSError."""
    with pytest.raises(TTSError, match="empty"):
        asyncio.get_event_loop().run_until_complete(adapter.synthesize("   "))


def test_temp_wav_cleaned(adapter):
    """Temporary WAV file must be cleaned up after synthesis."""
    before = set(glob.glob(f"{tempfile.gettempdir()}/*.wav"))
    asyncio.get_event_loop().run_until_complete(
        adapter.synthesize("Testing cleanup")
    )
    after = set(glob.glob(f"{tempfile.gettempdir()}/*.wav"))
    new = after - before
    assert len(new) == 0, f"Temp WAV not cleaned: {new}"


def test_release_no_raise():
    """release() must not raise even on a fresh adapter."""
    a = ClipCannonAdapter(voice_name="boris")
    a.release()
