"""Acoustic analysis and beat detection pipeline stage for ClipCannon.

Computes RMS energy envelope, silence gaps, spectral flatness for
music/speech discrimination, and beat positions. Uses numpy/scipy for
acoustic features (no GPU needed) and attempts librosa for beat
detection with fallback to scipy onset detection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

import numpy as np

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

if TYPE_CHECKING:
    from pathlib import Path

    from clipcannon.config import ClipCannonConfig

logger = logging.getLogger(__name__)
OPERATION = "acoustic_analysis"
STAGE = "acoustic"
SILENCE_RMS_THRESHOLD = 0.01
SILENCE_MIN_DURATION_MS = 500
HOP_LENGTH = 512
SPECTRAL_FLATNESS_THRESHOLD = 0.3
MUSIC_MIN_DURATION_MS = 3000


def _load_audio_scipy(audio_path: Path) -> tuple[np.ndarray, int]:
    """Load audio file and return mono float64 samples + sample rate."""
    from scipy.io import wavfile

    sample_rate, data = wavfile.read(str(audio_path))
    if data.dtype == np.int16:
        audio = data.astype(np.float64) / 32768.0
    elif data.dtype == np.int32:
        audio = data.astype(np.float64) / 2147483648.0
    elif data.dtype in (np.float32, np.float64):
        audio = data.astype(np.float64)
    else:
        audio = data.astype(np.float64) / np.iinfo(data.dtype).max
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    return audio, sample_rate


def _compute_rms_envelope(
    audio: np.ndarray,
    sample_rate: int,
    hop_length: int = HOP_LENGTH,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute RMS energy envelope. Returns (rms_values, time_ms)."""
    frame_length = hop_length * 2
    num_frames = max(1, (len(audio) - frame_length) // hop_length + 1)
    rms = np.zeros(num_frames, dtype=np.float64)
    time_ms = np.zeros(num_frames, dtype=np.float64)
    for i in range(num_frames):
        start = i * hop_length
        end = min(start + frame_length, len(audio))
        frame = audio[start:end]
        rms[i] = np.sqrt(np.mean(frame**2))
        time_ms[i] = (start + (end - start) / 2) / sample_rate * 1000
    return rms, time_ms


def _detect_silence_gaps(
    rms: np.ndarray,
    time_ms: np.ndarray,
    threshold: float = SILENCE_RMS_THRESHOLD,
    min_duration_ms: float = SILENCE_MIN_DURATION_MS,
) -> list[dict[str, int]]:
    """Detect silence gaps where RMS falls below threshold for min duration."""
    gaps: list[dict[str, int]] = []
    in_silence = False
    silence_start_ms = 0
    for val, t in zip(rms, time_ms, strict=False):
        if val < threshold:
            if not in_silence:
                in_silence = True
                silence_start_ms = int(t)
        elif in_silence:
            in_silence = False
            end_ms = int(t)
            duration = end_ms - silence_start_ms
            if duration >= min_duration_ms:
                gaps.append(
                    {"start_ms": silence_start_ms, "end_ms": end_ms, "duration_ms": duration}
                )
    if in_silence and len(time_ms) > 0:
        end_ms = int(time_ms[-1])
        duration = end_ms - silence_start_ms
        if duration >= min_duration_ms:
            gaps.append({"start_ms": silence_start_ms, "end_ms": end_ms, "duration_ms": duration})
    return gaps


def _compute_spectral_flatness(
    audio: np.ndarray,
    sample_rate: int,
    window_ms: int = 2000,
) -> list[dict[str, object]]:
    """Compute spectral flatness to detect music vs speech sections."""
    window_samples = int(sample_rate * window_ms / 1000)
    num_windows = max(1, len(audio) // window_samples)
    flatness_values: list[tuple[float, float]] = []
    for i in range(num_windows):
        start = i * window_samples
        end = min(start + window_samples, len(audio))
        frame = audio[start:end]
        if len(frame) < 256:
            continue
        spectrum = np.abs(np.fft.rfft(frame)) + 1e-10
        geo_mean = np.exp(np.mean(np.log(spectrum)))
        arith_mean = np.mean(spectrum)
        flatness = geo_mean / (arith_mean + 1e-10)
        t_ms = (start + end) / 2 / sample_rate * 1000
        flatness_values.append((t_ms, float(flatness)))
    music_sections: list[dict[str, object]] = []
    in_music = False
    music_start_ms = 0.0
    for t_ms, flatness in flatness_values:
        if flatness < SPECTRAL_FLATNESS_THRESHOLD and not in_music:
            in_music = True
            music_start_ms = t_ms - window_ms / 2
        elif flatness >= SPECTRAL_FLATNESS_THRESHOLD and in_music:
            in_music = False
            end_ms = t_ms - window_ms / 2
            if end_ms - music_start_ms >= MUSIC_MIN_DURATION_MS:
                music_sections.append(
                    {
                        "start_ms": int(max(0, music_start_ms)),
                        "end_ms": int(end_ms),
                        "type": "music",
                        "confidence": round(1.0 - float(flatness), 3),
                    }
                )
    if in_music and flatness_values:
        end_ms = flatness_values[-1][0] + window_ms / 2
        if end_ms - music_start_ms >= MUSIC_MIN_DURATION_MS:
            music_sections.append(
                {
                    "start_ms": int(max(0, music_start_ms)),
                    "end_ms": int(end_ms),
                    "type": "music",
                    "confidence": 0.5,
                }
            )
    return music_sections


def _compute_acoustic_stats(rms: np.ndarray) -> tuple[float, float]:
    """Compute (avg_volume_db, dynamic_range_db) from RMS values."""
    rms_nonzero = rms[rms > 1e-10]
    if len(rms_nonzero) == 0:
        return -60.0, 0.0
    rms_db = 20 * np.log10(rms_nonzero)
    return round(float(np.mean(rms_db)), 2), round(float(np.max(rms_db) - np.min(rms_db)), 2)


def _detect_beats_librosa(audio: np.ndarray, sample_rate: int) -> dict[str, object]:
    """Detect beats using librosa."""
    import librosa

    tempo_result, beat_frames = librosa.beat.beat_track(
        y=audio.astype(np.float32),
        sr=sample_rate,
        units="frames",
        hop_length=HOP_LENGTH,
    )
    tempo_bpm = (
        float(tempo_result[0])
        if isinstance(tempo_result, np.ndarray) and len(tempo_result) > 0
        else float(tempo_result)
    )
    beat_times = librosa.frames_to_time(beat_frames, sr=sample_rate, hop_length=HOP_LENGTH)
    beat_positions_ms = [int(t * 1000) for t in beat_times]
    has_music = len(beat_positions_ms) > 4 and tempo_bpm > 30
    return {
        "has_music": has_music,
        "source": "librosa",
        "tempo_bpm": round(tempo_bpm, 2) if has_music else None,
        "tempo_confidence": 0.7 if has_music else None,
        "beat_positions_ms": beat_positions_ms if has_music else [],
        "downbeat_positions_ms": beat_positions_ms[::4] if has_music else [],
        "beat_count": len(beat_positions_ms) if has_music else 0,
    }


def _detect_beats_scipy(audio: np.ndarray, sample_rate: int) -> dict[str, object]:
    """Fallback beat detection using scipy onset detection."""
    from scipy.signal import find_peaks

    hop = HOP_LENGTH
    num_frames = max(1, (len(audio) - hop * 2) // hop + 1)
    energy = np.zeros(num_frames)
    for i in range(num_frames):
        s = i * hop
        energy[i] = np.sum(audio[s : min(s + hop * 2, len(audio))] ** 2)
    flux = np.maximum(np.diff(energy), 0)
    if len(flux) < 4:
        return {
            "has_music": False,
            "source": "scipy_fallback",
            "tempo_bpm": None,
            "tempo_confidence": None,
            "beat_positions_ms": [],
            "downbeat_positions_ms": [],
            "beat_count": 0,
        }
    peaks, _ = find_peaks(
        flux, height=np.mean(flux) + np.std(flux), distance=int(sample_rate / hop * 0.3)
    )
    beat_times_ms = [int(p * hop / sample_rate * 1000) for p in peaks]
    tempo_bpm = 0.0
    if len(beat_times_ms) > 2:
        intervals = np.diff(beat_times_ms)
        valid = intervals[(intervals > 200) & (intervals < 2000)]
        if len(valid) > 0:
            tempo_bpm = round(60000.0 / np.mean(valid), 2)
    has_music = len(beat_times_ms) > 4 and tempo_bpm > 30
    return {
        "has_music": has_music,
        "source": "scipy_fallback",
        "tempo_bpm": tempo_bpm if has_music else None,
        "tempo_confidence": 0.4 if has_music else None,
        "beat_positions_ms": beat_times_ms if has_music else [],
        "downbeat_positions_ms": beat_times_ms[::4] if has_music else [],
        "beat_count": len(beat_times_ms) if has_music else 0,
    }


def _detect_beats(audio: np.ndarray, sample_rate: int) -> dict[str, object]:
    """Detect beats with cascading fallbacks: librosa -> scipy."""
    try:
        import librosa  # noqa: F401

        logger.info("Using librosa for beat detection")
        return _detect_beats_librosa(audio, sample_rate)
    except ImportError:
        pass
    logger.info("Using scipy fallback for beat detection")
    return _detect_beats_scipy(audio, sample_rate)


def _insert_results(
    db_path: Path,
    project_id: str,
    silence_gaps: list[dict[str, int]],
    avg_volume_db: float,
    dynamic_range_db: float,
    music_sections: list[dict[str, object]],
    beats: dict[str, object],
) -> dict[str, int]:
    """Insert all acoustic results into the database."""
    conn = get_connection(db_path, enable_vec=False, dict_rows=False)
    try:
        counts: dict[str, int] = {}
        if silence_gaps:
            batch_insert(
                conn,
                "silence_gaps",
                ["project_id", "start_ms", "end_ms", "duration_ms", "type"],
                [
                    (project_id, g["start_ms"], g["end_ms"], g["duration_ms"], "silence")
                    for g in silence_gaps
                ],
            )
        counts["silence_gaps"] = len(silence_gaps)
        execute(
            conn,
            "INSERT INTO acoustic (project_id, avg_volume_db, dynamic_range_db) VALUES (?, ?, ?)",
            (project_id, avg_volume_db, dynamic_range_db),
        )
        counts["acoustic"] = 1
        if music_sections:
            batch_insert(
                conn,
                "music_sections",
                ["project_id", "start_ms", "end_ms", "type", "confidence"],
                [
                    (
                        project_id,
                        int(s["start_ms"]),
                        int(s["end_ms"]),
                        str(s.get("type", "music")),
                        float(s.get("confidence", 0.5)),
                    )
                    for s in music_sections
                ],
            )
        counts["music_sections"] = len(music_sections)
        beat_positions = beats.get("beat_positions_ms", [])
        downbeats = beats.get("downbeat_positions_ms", [])
        execute(
            conn,
            "INSERT INTO beats (project_id, has_music, source, tempo_bpm, tempo_confidence, "
            "beat_positions_ms, downbeat_positions_ms, beat_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                bool(beats.get("has_music", False)),
                str(beats.get("source", "unknown")),
                beats.get("tempo_bpm"),
                beats.get("tempo_confidence"),
                json.dumps(beat_positions) if beat_positions else "[]",
                json.dumps(downbeats) if downbeats else "[]",
                int(beats.get("beat_count", 0)),
            ),
        )
        counts["beats"] = 1
        if beats.get("has_music") and beat_positions:
            positions = list(beat_positions)  # type: ignore[arg-type]
            if len(positions) >= 2:
                section_rows: list[tuple[object, ...]] = []
                ss = max(1, len(positions) // 4)
                for idx in range(0, len(positions), ss):
                    chunk = positions[idx : idx + ss]
                    if len(chunk) >= 2:
                        section_rows.append(
                            (
                                project_id,
                                int(chunk[0]),
                                int(chunk[-1]),
                                beats.get("tempo_bpm"),
                                "4/4",
                            )
                        )
                if section_rows:
                    batch_insert(
                        conn,
                        "beat_sections",
                        ["project_id", "start_ms", "end_ms", "tempo_bpm", "time_signature"],
                        section_rows,
                    )
                    counts["beat_sections"] = len(section_rows)
        conn.commit()
        return counts
    except Exception as exc:
        conn.rollback()
        raise PipelineError(
            f"Failed to insert acoustic results: {exc}", stage_name=STAGE, operation=OPERATION
        ) from exc
    finally:
        conn.close()


async def run_acoustic(
    project_id: str,
    db_path: Path,
    project_dir: Path,
    config: ClipCannonConfig,
) -> StageResult:
    """Execute the acoustic analysis pipeline stage.

    Computes RMS energy, silence gaps, music detection, and beats.

    Args:
        project_id: Project identifier.
        db_path: Path to the project database.
        project_dir: Path to the project directory.
        config: ClipCannon configuration.

    Returns:
        StageResult indicating success or failure.
    """
    start_time = time.monotonic()
    try:
        audio_path = resolve_audio_input(project_dir)
        logger.info("Acoustic analysis starting: %s", audio_path)
        audio, sample_rate = await asyncio.to_thread(_load_audio_scipy, audio_path)
        logger.info(
            "Audio loaded: %d samples, %d Hz, %.1fs",
            len(audio),
            sample_rate,
            len(audio) / sample_rate,
        )
        rms, time_ms_arr = await asyncio.to_thread(_compute_rms_envelope, audio, sample_rate)
        silence_gaps = await asyncio.to_thread(_detect_silence_gaps, rms, time_ms_arr)
        avg_volume_db, dynamic_range_db = await asyncio.to_thread(_compute_acoustic_stats, rms)
        music_sections = await asyncio.to_thread(_compute_spectral_flatness, audio, sample_rate)
        beats = await asyncio.to_thread(_detect_beats, audio, sample_rate)
        counts = await asyncio.to_thread(
            _insert_results,
            db_path,
            project_id,
            silence_gaps,
            avg_volume_db,
            dynamic_range_db,
            music_sections,
            beats,
        )
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        input_sha = await asyncio.to_thread(sha256_file, audio_path)
        summary = json.dumps(
            {
                "silence_gaps": counts.get("silence_gaps", 0),
                "avg_volume_db": avg_volume_db,
                "dynamic_range_db": dynamic_range_db,
                "music_sections": counts.get("music_sections", 0),
                "has_music": beats.get("has_music", False),
                "tempo_bpm": beats.get("tempo_bpm"),
            },
            sort_keys=True,
        )
        record_id = record_provenance(
            db_path=db_path,
            project_id=project_id,
            operation=OPERATION,
            stage=STAGE,
            input_info=InputInfo(
                file_path=str(audio_path), sha256=input_sha, size_bytes=audio_path.stat().st_size
            ),
            output_info=OutputInfo(
                sha256=sha256_string(summary), record_count=sum(counts.values())
            ),
            model_info=ModelInfo(
                name="acoustic_analysis",
                version="1.0",
                parameters={
                    "silence_threshold": SILENCE_RMS_THRESHOLD,
                    "hop_length": HOP_LENGTH,
                    "beat_source": str(beats.get("source", "unknown")),
                },
            ),
            execution_info=ExecutionInfo(duration_ms=elapsed_ms),
            parent_record_id=None,
            description=(
                f"Acoustic: {counts.get('silence_gaps', 0)} gaps, vol={avg_volume_db}dB, "
                f"range={dynamic_range_db}dB, music={beats.get('has_music')}, "
                f"tempo={beats.get('tempo_bpm')} BPM"
            ),
        )
        logger.info("Acoustic analysis complete in %d ms: %s", elapsed_ms, counts)
        return StageResult(
            success=True,
            operation=OPERATION,
            duration_ms=elapsed_ms,
            provenance_record_id=record_id,
        )
    except PipelineError:
        raise
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error("Acoustic analysis failed: %s", error_msg)
        return StageResult(success=False, operation=OPERATION, error_message=error_msg)
