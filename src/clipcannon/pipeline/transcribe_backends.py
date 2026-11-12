"""WhisperX and faster-whisper transcription backends."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from clipcannon.pipeline.transcribe_config import (
    _COMPRESSION_RATIO_THRESHOLD,
    _HALLUCINATION_SILENCE_THRESHOLD,
    _LOG_PROB_THRESHOLD,
    _NO_SPEECH_THRESHOLD,
    _VAD_OFFSET,
    _VAD_ONSET,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================
# BACKEND DETECTION
# ============================================================
def _check_whisperx_available() -> bool:
    """Check if WhisperX is importable."""
    try:
        import whisperx  # noqa: F401

        return True
    except ImportError:
        return False


def _check_faster_whisper_available() -> bool:
    """Check if faster-whisper is importable."""
    try:
        from faster_whisper import WhisperModel  # noqa: F401

        return True
    except ImportError:
        return False


# ============================================================
# WHISPERX TRANSCRIPTION
# ============================================================
async def _transcribe_whisperx(
    audio_path: Path,
    model_name: str,
    compute_type: str,
    device: str,
) -> dict[str, object]:
    """Transcribe using WhisperX with forced alignment.

    Configures VAD thresholds and anti-hallucination settings.
    Note: WhisperX batched mode ignores no_speech_threshold,
    log_prob_threshold, etc. -- post-transcription filtering
    handles hallucination prevention instead.

    Args:
        audio_path: Path to the audio file.
        model_name: Whisper model size (e.g., "large-v3").
        compute_type: Compute type (e.g., "int8", "float16").
        device: Device string ("cuda" or "cpu").

    Returns:
        Dictionary with 'segments' and 'language' keys.
    """
    import whisperx

    def _run() -> dict[str, object]:
        # 1. Load model with tuned VAD and anti-hallucination options
        model = whisperx.load_model(
            model_name,
            device=device,
            compute_type=compute_type,
            vad_options={
                "vad_onset": _VAD_ONSET,
                "vad_offset": _VAD_OFFSET,
            },
            asr_options={
                "suppress_blank": True,
                "condition_on_previous_text": False,
                "initial_prompt": None,
            },
        )

        audio = whisperx.load_audio(str(audio_path))
        result = model.transcribe(
            audio,
            batch_size=16,
        )

        detected_language = result.get("language", "en")
        logger.info("WhisperX detected language: %s", detected_language)

        # 2. Forced alignment with wav2vec2
        align_model, align_metadata = whisperx.load_align_model(
            language_code=detected_language,
            device=device,
        )
        aligned = whisperx.align(
            result["segments"],
            align_model,
            align_metadata,
            audio,
            device=device,
            return_char_alignments=False,
        )

        # Clean up models
        del model, align_model
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return {
            "segments": aligned.get("segments", result.get("segments", [])),
            "language": detected_language,
        }

    return await asyncio.to_thread(_run)


# ============================================================
# FASTER-WHISPER FALLBACK
# ============================================================
async def _transcribe_faster_whisper(
    audio_path: Path,
    model_name: str,
    compute_type: str,
    device: str,
) -> dict[str, object]:
    """Fallback transcription using faster-whisper.

    Includes full hallucination prevention parameters that
    faster-whisper supports (unlike WhisperX batched mode).

    Args:
        audio_path: Path to the audio file.
        model_name: Whisper model size.
        compute_type: Compute type.
        device: Device string.

    Returns:
        Dictionary with 'segments' and 'language' keys.
    """
    from faster_whisper import WhisperModel

    def _run() -> dict[str, object]:
        model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
        )
        # beam_size=1 (greedy) is ~3-5x faster than beam_size=5 with
        # minimal quality loss. Combined with vad_filter=True this
        # keeps transcription under 2 minutes for 8-minute videos.
        segments_iter, info = model.transcribe(
            str(audio_path),
            beam_size=1,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            no_speech_threshold=_NO_SPEECH_THRESHOLD,
            log_prob_threshold=_LOG_PROB_THRESHOLD,
            compression_ratio_threshold=_COMPRESSION_RATIO_THRESHOLD,
            condition_on_previous_text=False,
            hallucination_silence_threshold=_HALLUCINATION_SILENCE_THRESHOLD,
            temperature=0.0,
        )

        detected_language = info.language
        logger.info("faster-whisper detected language: %s", detected_language)

        segments = []
        for seg in segments_iter:
            words = [
                {
                    "word": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                    "score": w.probability,
                }
                for w in (seg.words or [])
            ]

            segments.append(
                {
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text.strip(),
                    "words": words,
                }
            )

        del model
        import gc
        import torch

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return {
            "segments": segments,
            "language": detected_language,
        }

    return await asyncio.to_thread(_run)
