"""Transcript persistence and the run_transcribe stage entry point."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from clipcannon.db.connection import get_connection
from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.orchestrator import StageResult
from clipcannon.pipeline.source_resolution import resolve_audio_input
from clipcannon.pipeline.transcribe_audio_checks import (
    _compute_audio_diagnostics,
    _reject_if_silent,
)
from clipcannon.pipeline.transcribe_backends import (
    _check_faster_whisper_available,
    _check_whisperx_available,
    _transcribe_faster_whisper,
    _transcribe_whisperx,
)
from clipcannon.pipeline.transcribe_config import _VAD_OFFSET, _VAD_ONSET, OPERATION, STAGE
from clipcannon.pipeline.transcribe_hallucination import _filter_hallucinations
from clipcannon.provenance import (
    ExecutionInfo,
    InputInfo,
    ModelInfo,
    OutputInfo,
    record_provenance,
    sha256_file,
    sha256_string,
)

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)


# ============================================================
# DATABASE INSERT
# ============================================================
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
        segments: List of transcript segments (already filtered).
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

                    word_rows.append(
                        (
                            segment_id,
                            w_text,
                            int(w_start * 1000),
                            int(w_end * 1000),
                            w_conf_float,
                        )
                    )

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


# ============================================================
# MAIN PIPELINE STAGE
# ============================================================
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

    Applies post-transcription hallucination filtering to both
    backends before inserting into the database.

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

        # Fail fast on silent / near-silent audio BEFORE loading WhisperX.
        # Rationale: loading WhisperX + running VAD on a 40s silent clip
        # takes ~40s of GPU time and produces an opaque "no segments"
        # error. Measure first; produce a self-diagnosing error instead.
        diag = await asyncio.to_thread(_compute_audio_diagnostics, audio_path)
        logger.info(
            "Audio diagnostics: duration=%.2fs peak=%.1f dBFS rms=%.1f dBFS "
            "audible=%.2fs (%.2f%%) sr=%d ch=%d",
            diag["duration_s"],
            diag["peak_dbfs"],
            diag["rms_dbfs"],
            diag["audible_duration_s"],
            diag["audible_pct"],
            diag["sample_rate"],
            diag["channels"],
        )
        _reject_if_silent(audio_path, diag)

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
                model_name,
                compute_type,
                device,
            )
            result = await _transcribe_whisperx(
                audio_path,
                model_name,
                compute_type,
                device,
            )
        elif use_faster_whisper:
            logger.warning(
                "WhisperX not available, falling back to faster-whisper. "
                "Word alignment precision will be reduced."
            )
            backend_name = "faster-whisper"
            result = await _transcribe_faster_whisper(
                audio_path,
                model_name,
                compute_type,
                device,
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
            # Audio was NOT silent (we passed _reject_if_silent above) yet
            # WhisperX returned zero segments. This usually means non-speech
            # audio (music, ambient, tones) or an unsupported language.
            raise PipelineError(
                f"WhisperX/faster-whisper produced zero segments despite audible audio. "
                f"Audio diagnostics: peak={diag['peak_dbfs']:.1f} dBFS, "
                f"RMS={diag['rms_dbfs']:.1f} dBFS, "
                f"audible={diag['audible_duration_s']:.2f}s/"
                f"{diag['duration_s']:.2f}s ({diag['audible_pct']:.2f}%). "
                f"Likely causes: non-speech audio (music/ambient/noise), "
                f"unsupported language, or VAD rejected all frames. "
                f"Input audio: {audio_path}.",
                stage_name=STAGE,
                operation=OPERATION,
            )

        # Apply post-transcription hallucination filtering
        raw_count = len(segments)
        segments, removed_count = _filter_hallucinations(segments)

        if removed_count > 0:
            logger.info(
                "Hallucination filter: removed %d/%d segments (%.1f%%)",
                removed_count,
                raw_count,
                removed_count / raw_count * 100,
            )

        if not segments:
            raise PipelineError(
                f"All {raw_count} WhisperX segments were classified as "
                f"hallucinations by the post-filter (known phrases, repetition, "
                f"low confidence, or high compression ratio). "
                f"Audio diagnostics: peak={diag['peak_dbfs']:.1f} dBFS, "
                f"audible={diag['audible_duration_s']:.2f}s/"
                f"{diag['duration_s']:.2f}s. "
                f"This means the model produced only spurious output. "
                f"Input audio: {audio_path}.",
                stage_name=STAGE,
                operation=OPERATION,
            )

        # Insert into database
        segment_count, word_count = _insert_transcript(
            db_path,
            project_id,
            segments,
            language,
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
                    "beam_size": 1,
                    "vad_filter": True,
                    "vad_onset": _VAD_ONSET,
                    "vad_offset": _VAD_OFFSET,
                    "hallucination_filter": True,
                    "segments_removed": removed_count,
                    "language": language,
                },
            ),
            execution_info=ExecutionInfo(
                gpu_device=device if device == "cuda" else None,
            ),
            parent_record_id="prov_001",
            description=(
                f"Transcription ({backend_name}): {segment_count} segments, "
                f"{word_count} words, {removed_count} hallucinations removed, "
                f"language={language}"
            ),
        )

        logger.info(
            "Transcription complete: %d segments, %d words, "
            "%d hallucinations removed (backend=%s, lang=%s)",
            segment_count,
            word_count,
            removed_count,
            backend_name,
            language,
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
