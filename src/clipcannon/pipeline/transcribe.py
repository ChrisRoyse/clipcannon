"""WhisperX transcription pipeline stage for ClipCannon.

Transcribes audio using WhisperX with wav2vec2 forced alignment
for 20-50ms word-level precision. Falls back to faster-whisper
if WhisperX is not installed.

Per the constitution, WhisperX with forced alignment is MANDATORY
for production use. The faster-whisper fallback is for development
and testing only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from clipcannon.config import ClipCannonConfig
from clipcannon.db.connection import get_connection
from clipcannon.db.queries import batch_insert, execute
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.pipeline.source_resolution import resolve_audio_input
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_file,
    sha256_string,
)

logger = logging.getLogger(__name__)

OPERATION = "transcription"
STAGE = "whisperx"

# HuggingFace token for model downloads
_HF_TOKEN = "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"


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


async def _transcribe_whisperx(
    audio_path: Path,
    model_name: str,
    compute_type: str,
    device: str,
) -> dict[str, object]:
    """Transcribe using WhisperX with forced alignment.

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
        # Set HF token for wav2vec2 model downloads
        os.environ.setdefault("HF_TOKEN", _HF_TOKEN)

        # 1. Load model and transcribe
        model = whisperx.load_model(
            model_name,
            device=device,
            compute_type=compute_type,
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


async def _transcribe_faster_whisper(
    audio_path: Path,
    model_name: str,
    compute_type: str,
    device: str,
) -> dict[str, object]:
    """Fallback transcription using faster-whisper (no forced alignment).

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
        segments_iter, info = model.transcribe(
            str(audio_path),
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
        )

        detected_language = info.language
        logger.info("faster-whisper detected language: %s", detected_language)

        segments = []
        for seg in segments_iter:
            words = []
            if seg.words:
                for w in seg.words:
                    words.append({
                        "word": w.word.strip(),
                        "start": w.start,
                        "end": w.end,
                        "score": w.probability,
                    })

            segments.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
                "words": words,
            })

        del model
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return {
            "segments": segments,
            "language": detected_language,
        }

    return await asyncio.to_thread(_run)


def _insert_transcript(
    db_path: Path,
    project_id: str,
    segments: list[dict[str, object]],
    language: str,
) -> tuple[int, int]:
    """Insert transcript segments and words into the database.

    Args:
        db_path: Path to the project database.
        project_id: Project identifier.
        segments: List of transcript segments from WhisperX/faster-whisper.
        language: Detected language code.

    Returns:
        Tuple of (segment_count, word_count).
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        segment_count = 0
        word_count = 0

        for seg in segments:
            start_s = float(seg.get("start", 0))
            end_s = float(seg.get("end", 0))
            text = str(seg.get("text", ""))

            if not text.strip():
                continue

            start_ms = int(start_s * 1000)
            end_ms = int(end_s * 1000)
            words_in_text = len(text.split())

            # Insert segment
            cursor = conn.execute(
                "INSERT INTO transcript_segments "
                "(project_id, start_ms, end_ms, text, language, word_count) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, start_ms, end_ms, text, language, words_in_text),
            )
            segment_id = cursor.lastrowid
            segment_count += 1

            # Insert words
            words = seg.get("words", [])
            if isinstance(words, list):
                word_rows: list[tuple[object, ...]] = []
                for w in words:
                    if not isinstance(w, dict):
                        continue
                    w_text = str(w.get("word", "")).strip()
                    if not w_text:
                        continue
                    w_start = float(w.get("start", start_s))
                    w_end = float(w.get("end", end_s))
                    w_conf = w.get("score") or w.get("confidence")
                    w_conf_float = float(w_conf) if w_conf is not None else None

                    word_rows.append((
                        segment_id,
                        w_text,
                        int(w_start * 1000),
                        int(w_end * 1000),
                        w_conf_float,
                    ))

                if word_rows:
                    conn.executemany(
                        "INSERT INTO transcript_words "
                        "(segment_id, word, start_ms, end_ms, confidence) "
                        "VALUES (?, ?, ?, ?, ?)",
                        word_rows,
                    )
                    word_count += len(word_rows)

        conn.commit()
        return segment_count, word_count

    except Exception as exc:
        conn.rollback()
        raise PipelineError(
            f"Failed to insert transcript: {exc}",
            stage_name=STAGE,
            operation=OPERATION,
        ) from exc
    finally:
        conn.close()


async def run_transcribe(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the transcription pipeline stage.

    Uses WhisperX with wav2vec2 forced alignment for 20-50ms
    word-level precision. Falls back to faster-whisper if
    WhisperX is not installed.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    try:
        # Resolve audio input (vocals.wav preferred, audio_16k.wav fallback)
        audio_path = resolve_audio_input(project_dir)

        model_name = str(config.get("processing.whisper_model"))
        compute_type = str(config.get("processing.whisper_compute_type"))
        gpu_device = str(config.get("gpu.device"))
        device = "cuda" if "cuda" in gpu_device else "cpu"

        # Determine backend
        use_whisperx = _check_whisperx_available()
        use_faster_whisper = _check_faster_whisper_available()
        backend_name = "whisperx"

        if use_whisperx:
            logger.info(
                "Transcribing with WhisperX: model=%s, compute=%s, device=%s",
                model_name, compute_type, device,
            )
            result = await _transcribe_whisperx(
                audio_path, model_name, compute_type, device,
            )
        elif use_faster_whisper:
            logger.warning(
                "WhisperX not available, falling back to faster-whisper. "
                "Word alignment precision will be reduced."
            )
            backend_name = "faster-whisper"
            result = await _transcribe_faster_whisper(
                audio_path, model_name, compute_type, device,
            )
        else:
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message=(
                    "Neither whisperx nor faster-whisper is installed. "
                    "Install with: pip install whisperx  or  pip install faster-whisper"
                ),
            )

        segments = result.get("segments", [])
        language = str(result.get("language", "en"))

        if not isinstance(segments, list) or len(segments) == 0:
            return StageResult(
                success=False,
                operation=OPERATION,
                error_message="Transcription produced no segments",
            )

        # Insert into database
        segment_count, word_count = _insert_transcript(
            db_path, project_id, segments, language,
        )

        # Compute provenance hash
        transcript_json = json.dumps(segments, sort_keys=True, default=str)
        transcript_hash = sha256_string(transcript_json)
        input_sha256 = await asyncio.to_thread(sha256_file, audio_path)

        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=backend_name,
            input_info=InputInfo(
                file_path=str(audio_path),
                sha256=input_sha256,
                size_bytes=audio_path.stat().st_size,
            ),
            output_info=OutputInfo(
                sha256=transcript_hash,
                record_count=segment_count,
            ),
            model_info=ModelInfo(
                name=backend_name,
                version=model_name,
                quantization=compute_type,
                parameters={
                    "beam_size": 5,
                    "vad_filter": True,
                    "language": language,
                },
            ),
            execution_info=ExecutionInfo(
                gpu_device=device if device == "cuda" else None,
            ),
            parent_record_id="prov_001",
            description=(
                f"Transcription ({backend_name}): {segment_count} segments, "
                f"{word_count} words, language={language}"
            ),
        )

        logger.info(
            "Transcription complete: %d segments, %d words (backend=%s, lang=%s)",
            segment_count, word_count, backend_name, language,
        )

        return StageResult(
            success=True,
            operation=OPERATION,
            provenance_record_id=record_id,
        )

    except PipelineError:
        raise
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Transcription failed: %s", error_msg)
        raise PipelineError(
            f"Transcription failed: {error_msg}",
            stage_name=STAGE,
            operation=OPERATION,
        ) from exc
