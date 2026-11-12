"""Constants, audio loading and windowing for emotion_embed."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

OPERATION = "emotion_analysis"
STAGE = "wav2vec2_emotion"
# Dimensional speech-emotion model (arousal/dominance/valence + 1024-d states).
# This is a fine-tuned SER model, NOT an ASR model — its outputs are grounded
# in emotional state, satisfying the instrument differentiation contract.
MODEL_ID = "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim"
EMBEDDING_DIM = 1024
WINDOW_S = 5.0
STRIDE_S = 2.5
TARGET_SR = 16000


def _load_audio(audio_path: Path) -> tuple[np.ndarray, int]:
    """Load audio and resample to 16kHz mono.

    Args:
        audio_path: Path to the WAV file.

    Returns:
        Tuple of (mono audio as float32 array, sample rate).
    """
    try:
        import torchaudio

        waveform, sr = torchaudio.load(str(audio_path))
        # Convert to mono
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        # Resample if needed
        if sr != TARGET_SR:
            resampler = torchaudio.transforms.Resample(sr, TARGET_SR)
            waveform = resampler(waveform)
        audio = waveform.squeeze(0).numpy()
        return audio, TARGET_SR
    except ImportError:
        pass

    # Fallback to scipy
    from scipy.io import wavfile
    from scipy.signal import resample

    sr, data = wavfile.read(str(audio_path))
    if data.dtype == np.int16:
        audio = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        audio = data.astype(np.float32) / 2147483648.0
    else:
        audio = data.astype(np.float32)

    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)

    if sr != TARGET_SR:
        num_samples = int(len(audio) * TARGET_SR / sr)
        audio = resample(audio, num_samples).astype(np.float32)

    return audio, TARGET_SR


def _segment_audio(
    audio: np.ndarray,
    sample_rate: int,
    window_s: float = WINDOW_S,
    stride_s: float = STRIDE_S,
) -> list[tuple[int, int, np.ndarray]]:
    """Segment audio into overlapping windows.

    Args:
        audio: Mono audio array.
        sample_rate: Audio sample rate.
        window_s: Window duration in seconds.
        stride_s: Stride between windows in seconds.

    Returns:
        List of (start_ms, end_ms, audio_chunk) tuples.
    """
    window_samples = int(window_s * sample_rate)
    stride_samples = int(stride_s * sample_rate)
    segments: list[tuple[int, int, np.ndarray]] = []

    pos = 0
    while pos + window_samples <= len(audio):
        chunk = audio[pos : pos + window_samples]
        start_ms = int(pos / sample_rate * 1000)
        end_ms = int((pos + window_samples) / sample_rate * 1000)
        segments.append((start_ms, end_ms, chunk))
        pos += stride_samples

    # Handle trailing chunk
    if pos < len(audio) and len(audio) - pos > sample_rate:
        chunk = audio[pos:]
        start_ms = int(pos / sample_rate * 1000)
        end_ms = int(len(audio) / sample_rate * 1000)
        segments.append((start_ms, end_ms, chunk))

    return segments
