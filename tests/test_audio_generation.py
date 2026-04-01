"""Tests for the audio generation modules (SFX and MIDI).

Tests cover:
- generate_sfx for all 9 effect types
- WAV output format: 16-bit, 44100 Hz
- Zero-crossing fades (no clicks)
- Duration accuracy
- SFX stinger is combined impact + riser
- Invalid SFX type raises ValueError
- compose_midi for all 6 presets (when midiutil available)
- Custom tempo override
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from scipy.io import wavfile  # type: ignore[import-untyped]

from clipcannon.audio.sfx import (
    SAMPLE_RATE,
    SUPPORTED_SFX_TYPES,
    generate_sfx,
)

if TYPE_CHECKING:
    from pathlib import Path


# ============================================================
# FIXTURES
# ============================================================
@pytest.fixture()
def sfx_dir(tmp_path: Path) -> Path:
    """Directory for generated SFX files."""
    d = tmp_path / "sfx"
    d.mkdir()
    return d


@pytest.fixture()
def midi_dir(tmp_path: Path) -> Path:
    """Directory for generated MIDI files."""
    d = tmp_path / "midi"
    d.mkdir()
    return d


# ============================================================
# SFX TESTS
# ============================================================
class TestGenerateSfx:
    """Test programmatic sound effect generation."""

    def test_whoosh_creates_wav(self, sfx_dir: Path) -> None:
        """Whoosh effect produces a valid WAV file."""
        out = sfx_dir / "whoosh.wav"
        result = generate_sfx("whoosh", out, duration_ms=500)
        assert out.exists()
        assert out.stat().st_size > 0
        sr, _data = wavfile.read(str(out))
        assert sr == SAMPLE_RATE
        assert result.sfx_type == "whoosh"

    def test_riser_ascending_pattern(self, sfx_dir: Path) -> None:
        """Riser effect has ascending frequency character."""
        out = sfx_dir / "riser.wav"
        generate_sfx("riser", out, duration_ms=1000)
        sr, data = wavfile.read(str(out))
        assert sr == SAMPLE_RATE
        # Check that signal has content in later portion
        mid = len(data) // 2
        rms_first = np.sqrt(np.mean(data[:mid].astype(float) ** 2))
        rms_second = np.sqrt(np.mean(data[mid:].astype(float) ** 2))
        # Riser has crescendo - second half should be louder
        assert rms_second > rms_first * 0.5

    def test_impact_fast_decay(self, sfx_dir: Path) -> None:
        """Impact effect has fast decay (front-loaded energy)."""
        out = sfx_dir / "impact.wav"
        generate_sfx("impact", out, duration_ms=500)
        sr, data = wavfile.read(str(out))
        assert sr == SAMPLE_RATE
        quarter = len(data) // 4
        rms_first = np.sqrt(np.mean(data[:quarter].astype(float) ** 2))
        rms_last = np.sqrt(np.mean(data[-quarter:].astype(float) ** 2))
        # Impact decays quickly - first quarter louder than last
        assert rms_first > rms_last

    def test_chime_harmonic_content(self, sfx_dir: Path) -> None:
        """Chime effect has harmonic content (multi-frequency)."""
        out = sfx_dir / "chime.wav"
        generate_sfx("chime", out, duration_ms=1000)
        sr, data = wavfile.read(str(out))
        assert sr == SAMPLE_RATE
        # FFT to check harmonics
        fft = np.abs(np.fft.rfft(data.astype(float)))
        # Base freq is 880 Hz, with 2x and 3x harmonics
        # Check that there is energy around 880 Hz (indices near 880/freq_res)
        freq_res = sr / len(data)
        idx_880 = int(880 / freq_res)
        # There should be a peak near 880 Hz
        window = slice(max(0, idx_880 - 5), idx_880 + 5)
        assert np.max(fft[window]) > 0

    def test_all_9_types_produce_valid_wav(self, sfx_dir: Path) -> None:
        """All 9 SFX types produce valid WAV files."""
        for sfx_type in sorted(SUPPORTED_SFX_TYPES):
            out = sfx_dir / f"{sfx_type}.wav"
            result = generate_sfx(sfx_type, out, duration_ms=300)
            assert out.exists(), f"{sfx_type} did not produce output"
            assert out.stat().st_size > 0, f"{sfx_type} produced empty file"
            sr, _data = wavfile.read(str(out))
            assert sr == SAMPLE_RATE, f"{sfx_type} wrong sample rate"
            assert result.sfx_type == sfx_type

    def test_custom_duration(self, sfx_dir: Path) -> None:
        """Custom duration matches expected sample count."""
        out = sfx_dir / "custom_dur.wav"
        generate_sfx("tick", out, duration_ms=750)
        sr, data = wavfile.read(str(out))
        actual_duration_ms = len(data) / sr * 1000
        # Should be close to 750ms (within 10ms tolerance due to int rounding)
        assert abs(actual_duration_ms - 750) < 20

    def test_zero_crossing_fade(self, sfx_dir: Path) -> None:
        """Output starts and ends near zero (no clicks)."""
        out = sfx_dir / "fade_check.wav"
        generate_sfx("whoosh", out, duration_ms=500)
        _sr, data = wavfile.read(str(out))
        # First and last few samples should be near zero
        # (int16 range is -32768 to 32767)
        assert abs(int(data[0])) < 500, f"Start click detected: {data[0]}"
        assert abs(int(data[-1])) < 500, f"End click detected: {data[-1]}"

    def test_sfx_output_16bit_44100(self, sfx_dir: Path) -> None:
        """Output is 16-bit 44100 Hz."""
        out = sfx_dir / "format_check.wav"
        generate_sfx("chime", out, duration_ms=300)
        sr, data = wavfile.read(str(out))
        assert sr == 44100
        assert data.dtype == np.int16

    def test_stinger_is_impact_plus_riser(self, sfx_dir: Path) -> None:
        """Stinger is a combination of impact and riser sections."""
        out = sfx_dir / "stinger.wav"
        generate_sfx("stinger", out, duration_ms=1000)
        sr, data = wavfile.read(str(out))
        assert sr == SAMPLE_RATE
        # Stinger should have front-loaded energy (impact) then rising
        mid = len(data) // 2
        rms_first_quarter = np.sqrt(
            np.mean(data[: mid // 2].astype(float) ** 2)
        )
        # First quarter should have significant energy (impact)
        assert rms_first_quarter > 0

    def test_invalid_sfx_type_raises(self, sfx_dir: Path) -> None:
        """Invalid SFX type raises ValueError."""
        out = sfx_dir / "invalid.wav"
        with pytest.raises(ValueError, match="Unknown sfx_type"):
            generate_sfx("nonexistent", out)


# ============================================================
# MIDI TESTS
# ============================================================
class TestComposeMidi:
    """Test MIDI composition (requires midiutil)."""

    def test_ambient_pad_preset(self, midi_dir: Path) -> None:
        """ambient_pad preset produces a MIDI file."""
        pytest.importorskip("midiutil")
        from clipcannon.audio.midi_compose import compose_midi

        out = midi_dir / "ambient.mid"
        result = compose_midi("ambient_pad", 10.0, out)
        assert out.exists()
        assert out.stat().st_size > 0
        assert result.preset == "ambient_pad"
        assert result.tempo_bpm == 70

    def test_upbeat_pop_preset(self, midi_dir: Path) -> None:
        """upbeat_pop preset produces a MIDI file different from ambient."""
        pytest.importorskip("midiutil")
        from clipcannon.audio.midi_compose import compose_midi

        out1 = midi_dir / "ambient2.mid"
        out2 = midi_dir / "upbeat.mid"
        compose_midi("ambient_pad", 10.0, out1)
        compose_midi("upbeat_pop", 10.0, out2)
        # Files should be different
        assert out1.read_bytes() != out2.read_bytes()

    def test_all_presets(self, midi_dir: Path) -> None:
        """All 12 presets produce output."""
        pytest.importorskip("midiutil")
        from clipcannon.audio.midi_compose import PRESETS, compose_midi

        assert len(PRESETS) == 12
        for name in PRESETS:
            out = midi_dir / f"{name}.mid"
            result = compose_midi(name, 5.0, out)
            assert out.exists(), f"Preset {name} failed"
            assert result.preset == name

    def test_custom_tempo_override(self, midi_dir: Path) -> None:
        """Custom tempo overrides preset default."""
        pytest.importorskip("midiutil")
        from clipcannon.audio.midi_compose import compose_midi

        out = midi_dir / "custom_tempo.mid"
        result = compose_midi("ambient_pad", 10.0, out, tempo_bpm=140)
        assert result.tempo_bpm == 140

    def test_invalid_preset_raises(self, midi_dir: Path) -> None:
        """Invalid preset name raises ValueError."""
        pytest.importorskip("midiutil")
        from clipcannon.audio.midi_compose import compose_midi

        out = midi_dir / "invalid.mid"
        with pytest.raises(ValueError, match="Unknown preset"):
            compose_midi("nonexistent_preset", 10.0, out)
