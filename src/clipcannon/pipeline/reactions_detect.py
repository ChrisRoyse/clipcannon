"""Audio loading and reaction detection (SenseVoice and energy fallback)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

OPERATION = "reaction_detection"
STAGE = "sensevoice_reactions"
TARGET_SR = 16000
WINDOW_S = 3.0
STRIDE_S = 1.5
ENERGY_REACTION_THRESHOLD = 0.15


def _load_audio(audio_path: Path) -> tuple[np.ndarray, int]:
    """Load audio and resample to 16kHz mono.

    Args:
        audio_path: Path to the WAV file.

    Returns:
        Tuple of (mono float32 array, sample rate).
    """
    try:
        import torchaudio

        waveform, sr = torchaudio.load(str(audio_path))
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        if sr != TARGET_SR:
            resampler = torchaudio.transforms.Resample(sr, TARGET_SR)
            waveform = resampler(waveform)
        return waveform.squeeze(0).numpy(), TARGET_SR
    except ImportError:
        pass

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


def _check_sensevoice_funasr() -> bool:
    """Check if FunASR SenseVoice is available."""
    try:
        from funasr import AutoModel as FunASRModel  # noqa: F401

        return True
    except ImportError:
        return False


def _detect_reactions_funasr(
    audio: np.ndarray,
    sample_rate: int,
) -> list[dict[str, object]]:
    """Detect reactions using FunASR SenseVoice model.

    Args:
        audio: Mono audio array.
        sample_rate: Audio sample rate.

    Returns:
        List of reaction dicts.
    """
    from funasr import AutoModel as FunASRModel

    model = FunASRModel(model="iic/SenseVoiceSmall", trust_remote_code=True)
    window_samples = int(WINDOW_S * sample_rate)
    stride_samples = int(STRIDE_S * sample_rate)

    reactions: list[dict[str, object]] = []

    pos = 0
    while pos + window_samples <= len(audio):
        chunk = audio[pos : pos + window_samples]
        start_ms = int(pos / sample_rate * 1000)
        end_ms = int((pos + window_samples) / sample_rate * 1000)

        result = model.generate(input=chunk, cache={})

        if result and isinstance(result, list):
            text = str(result[0].get("text", "")) if isinstance(result[0], dict) else str(result[0])
            text_lower = text.lower()

            if "<laughter>" in text_lower or "laugh" in text_lower:
                reactions.append(
                    {
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "type": "laughter",
                        "confidence": 0.8,
                        "duration_ms": end_ms - start_ms,
                        "intensity": "moderate",
                    }
                )
            if "<applause>" in text_lower or "applause" in text_lower:
                reactions.append(
                    {
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "type": "applause",
                        "confidence": 0.8,
                        "duration_ms": end_ms - start_ms,
                        "intensity": "moderate",
                    }
                )

        pos += stride_samples

    del model
    import gc

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
    return reactions


def _detect_reactions_energy(
    audio: np.ndarray,
    sample_rate: int,
) -> list[dict[str, object]]:
    """Detect potential reactions from high-energy non-speech segments.

    Uses spectral characteristics to distinguish reactions from speech.
    High energy + high spectral spread = potential reaction.

    Args:
        audio: Mono audio array.
        sample_rate: Audio sample rate.

    Returns:
        List of reaction dicts.
    """
    window_samples = int(WINDOW_S * sample_rate)
    stride_samples = int(STRIDE_S * sample_rate)
    reactions: list[dict[str, object]] = []

    pos = 0
    while pos + window_samples <= len(audio):
        chunk = audio[pos : pos + window_samples]
        start_ms = int(pos / sample_rate * 1000)
        end_ms = int((pos + window_samples) / sample_rate * 1000)

        rms = float(np.sqrt(np.mean(chunk**2)))

        if rms > ENERGY_REACTION_THRESHOLD:
            # Compute spectral features to classify
            spectrum = np.abs(np.fft.rfft(chunk))
            if len(spectrum) > 0:
                # Spectral centroid (higher = more likely applause/laughter)
                freqs = np.fft.rfftfreq(len(chunk), 1.0 / sample_rate)
                centroid = float(np.sum(freqs * spectrum) / (np.sum(spectrum) + 1e-10))

                # Spectral spread
                spread = float(
                    np.sqrt(
                        np.sum(((freqs - centroid) ** 2) * spectrum) / (np.sum(spectrum) + 1e-10)
                    )
                )

                # Zero crossing rate
                zcr = float(np.mean(np.abs(np.diff(np.sign(chunk)))) / 2)

                # Classify based on features
                reaction_type = None
                confidence = 0.0

                if centroid > 1000 and spread > 500 and zcr > 0.1:
                    # High centroid + high spread + high ZCR = applause-like
                    reaction_type = "applause"
                    confidence = min(0.6, rms * 3)
                elif centroid > 500 and zcr > 0.05 and rms > 0.2:
                    # Moderate features with high energy = laughter-like
                    reaction_type = "laughter"
                    confidence = min(0.5, rms * 2)

                if reaction_type and confidence > 0.3:
                    intensity = "weak"
                    if rms > 0.3:
                        intensity = "strong"
                    elif rms > 0.2:
                        intensity = "moderate"

                    reactions.append(
                        {
                            "start_ms": start_ms,
                            "end_ms": end_ms,
                            "type": reaction_type,
                            "confidence": round(confidence, 3),
                            "duration_ms": end_ms - start_ms,
                            "intensity": intensity,
                        }
                    )

        pos += stride_samples

    return reactions
