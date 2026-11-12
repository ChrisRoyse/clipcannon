"""Pre-transcription audio diagnostics and silence rejection."""

from __future__ import annotations

import math
import wave
from typing import TYPE_CHECKING

import numpy as np

from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.transcribe_config import (
    _AUDIBLE_FRAME_DBFS,
    _MIN_AUDIBLE_PCT,
    _SILENCE_PEAK_DBFS,
    OPERATION,
    STAGE,
)

if TYPE_CHECKING:
    from pathlib import Path


def _amp_to_dbfs(amp: float) -> float:
    """Convert a linear amplitude (0..1) to dBFS; clamp -infinity to -120."""
    if amp <= 0.0:
        return -120.0
    return 20.0 * math.log10(amp)


def _compute_audio_diagnostics(audio_path: Path) -> dict[str, object]:
    """Measure silence/level statistics of a PCM WAV file.

    Returns duration, peak dBFS, RMS dBFS, audible duration and audible
    percentage. Used to fail fast (with a precise diagnostic) when the
    input is effectively silent, before we waste ~40s on WhisperX.

    Args:
        audio_path: Path to a PCM WAV file (as produced by audio_extract).

    Raises:
        PipelineError: if the file cannot be read as PCM WAV.
    """
    try:
        with wave.open(str(audio_path), "rb") as wf:
            n_frames = wf.getnframes()
            sample_rate = wf.getframerate()
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            raw = wf.readframes(n_frames)
    except wave.Error as exc:
        raise PipelineError(
            f"Cannot read audio diagnostics from {audio_path}: {exc}. "
            f"Upstream audio_extract stage may have produced a corrupt WAV.",
            stage_name=STAGE,
            operation=OPERATION,
        ) from exc

    if sample_width == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2_147_483_648.0
    elif sample_width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise PipelineError(
            f"Unsupported PCM sample width {sample_width} bytes in {audio_path}.",
            stage_name=STAGE,
            operation=OPERATION,
        )

    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    duration_s = float(len(samples)) / sample_rate if sample_rate else 0.0

    if len(samples) == 0:
        return {
            "duration_s": 0.0,
            "peak_dbfs": -120.0,
            "rms_dbfs": -120.0,
            "audible_duration_s": 0.0,
            "audible_pct": 0.0,
            "sample_rate": sample_rate,
            "channels": channels,
        }

    peak = float(np.abs(samples).max())
    rms = float(np.sqrt(np.mean(samples * samples)))

    frame_size = max(1, sample_rate // 20)  # 50 ms frames
    n_full_frames = len(samples) // frame_size
    if n_full_frames > 0:
        trimmed = samples[: n_full_frames * frame_size].reshape(n_full_frames, frame_size)
        frame_rms = np.sqrt(np.mean(trimmed * trimmed, axis=1))
        threshold = 10.0 ** (_AUDIBLE_FRAME_DBFS / 20.0)
        audible_frames = int((frame_rms > threshold).sum())
    else:
        audible_frames = 0
    audible_duration_s = audible_frames * (frame_size / sample_rate)
    audible_pct = 100.0 * audible_duration_s / duration_s if duration_s > 0 else 0.0

    return {
        "duration_s": duration_s,
        "peak_dbfs": _amp_to_dbfs(peak),
        "rms_dbfs": _amp_to_dbfs(rms),
        "audible_duration_s": audible_duration_s,
        "audible_pct": audible_pct,
        "sample_rate": sample_rate,
        "channels": channels,
    }


def _reject_if_silent(audio_path: Path, diag: dict[str, object]) -> None:
    """Raise PipelineError with a full, self-diagnosing message if the
    audio is silent or near-silent. Does NOT try to recover — this is a
    required stage and silence is not transcribable.
    """
    peak_dbfs = float(diag["peak_dbfs"])
    rms_dbfs = float(diag["rms_dbfs"])
    duration_s = float(diag["duration_s"])
    audible_duration_s = float(diag["audible_duration_s"])
    audible_pct = float(diag["audible_pct"])

    def _msg(reason: str) -> str:
        return (
            f"{reason}\n"
            f"  audio: {audio_path}\n"
            f"  duration: {duration_s:.2f}s\n"
            f"  peak: {peak_dbfs:.1f} dBFS (silence threshold: "
            f"{_SILENCE_PEAK_DBFS:.0f} dBFS)\n"
            f"  RMS: {rms_dbfs:.1f} dBFS\n"
            f"  audible: {audible_duration_s:.2f}s / {duration_s:.2f}s "
            f"({audible_pct:.2f}%, threshold: {_MIN_AUDIBLE_PCT:.1f}%)\n"
            f"  sample_rate: {diag['sample_rate']} Hz, channels: {diag['channels']}\n"
            f"Resolution: supply a source video whose audio track contains "
            f"audible speech. This source contains no speech to transcribe; "
            f"clipcannon's ingest pipeline requires speech for downstream "
            f"semantic, speaker, prosody, narrative, chronemic and highlight stages."
        )

    if peak_dbfs < _SILENCE_PEAK_DBFS:
        raise PipelineError(
            _msg("Audio is digital silence; transcription is impossible."),
            stage_name=STAGE,
            operation=OPERATION,
        )
    if audible_pct < _MIN_AUDIBLE_PCT:
        raise PipelineError(
            _msg("Audio has too little audible content to transcribe."),
            stage_name=STAGE,
            operation=OPERATION,
        )
