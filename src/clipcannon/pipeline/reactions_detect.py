"""Audio loading and the SenseVoice reaction instrument.

``sensevoice_funasr`` (when FunASR is installed) emits event tags with no
confidence. Without FunASR the stage uses ``reactions_ast`` (AST AudioSet).
"""

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
SENSEVOICE = "sensevoice_funasr"


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
    """Whether FunASR is installed (checked by spec, not by a swallowed import).

    An installed FunASR that fails to import or run fails the stage; it
    does not switch the stage to the AST instrument.
    """
    import importlib.util

    return importlib.util.find_spec("funasr") is not None


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
    # SenseVoice emits event tags without a score: confidence is None, not a
    # constant. intensity is likewise unmeasured.

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
                        "confidence": None,
                        "duration_ms": end_ms - start_ms,
                        "intensity": None,
                    }
                )
            if "<applause>" in text_lower or "applause" in text_lower:
                reactions.append(
                    {
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "type": "applause",
                        "confidence": None,
                        "duration_ms": end_ms - start_ms,
                        "intensity": None,
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
