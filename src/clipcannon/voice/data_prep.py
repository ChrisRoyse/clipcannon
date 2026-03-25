"""Voice training data preparation for ClipCannon.

Splits vocal stems at silence boundaries, matches transcript text,
normalizes audio, phonemizes, and writes train/val splits.
"""

from __future__ import annotations

import asyncio
import logging
import random
import secrets
from dataclasses import dataclass
from pathlib import Path

from clipcannon.db.connection import get_connection
from clipcannon.db.queries import fetch_all

logger = logging.getLogger(__name__)


@dataclass
class VoiceDataResult:
    """Result of voice training data preparation."""

    total_clips: int
    total_duration_s: float
    train_count: int
    val_count: int
    output_dir: Path


@dataclass
class _ClipInfo:
    """Internal clip metadata before writing."""

    wav_path: Path
    text: str
    phonemes: str
    duration_s: float
    speaker_label: str


def _load_silence_gaps_and_words(
    db_path: Path, project_id: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Load silence gaps and transcript words in a single connection.

    Returns:
        Tuple of (silence_gaps, transcript_words), both ordered by start_ms.
    """
    conn = get_connection(db_path, enable_vec=False, dict_rows=True)
    try:
        gaps = fetch_all(
            conn,
            "SELECT start_ms, end_ms, duration_ms FROM silence_gaps "
            "WHERE project_id = ? ORDER BY start_ms",
            (project_id,),
        )
        words = fetch_all(
            conn,
            "SELECT word, start_ms, end_ms FROM transcript_words ORDER BY start_ms",
        )
        return gaps, words
    finally:
        conn.close()


def _compute_speech_segments(
    silence_gaps: list[dict[str, object]],
    audio_duration_ms: int,
    min_clip_ms: int,
    max_clip_ms: int,
) -> list[tuple[int, int]]:
    """Compute speech segments by splitting at silence midpoints.

    Merges short segments, filters by min/max duration.
    """
    if not silence_gaps:
        return [(0, audio_duration_ms)] if audio_duration_ms <= max_clip_ms else []

    boundaries = [0]
    for gap in silence_gaps:
        boundaries.append((int(gap["start_ms"]) + int(gap["end_ms"])) // 2)
    boundaries.append(audio_duration_ms)

    raw = [(boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)
           if boundaries[i + 1] - boundaries[i] > 0]

    merged: list[tuple[int, int]] = []
    a_start: int | None = None
    a_end: int | None = None

    for start, end in raw:
        if a_start is None:
            a_start, a_end = start, end
            continue
        assert a_end is not None
        if end - a_start <= max_clip_ms and a_end - a_start < min_clip_ms:
            a_end = end
        else:
            if a_end - a_start >= min_clip_ms:
                merged.append((a_start, a_end))
            a_start, a_end = start, end

    if a_start is not None and a_end is not None and a_end - a_start >= min_clip_ms:
        merged.append((a_start, a_end))

    return [(s, e) for s, e in merged if min_clip_ms <= (e - s) <= max_clip_ms]


def _match_words_to_segment(
    words: list[dict[str, object]], seg_start_ms: int, seg_end_ms: int,
) -> str:
    """Extract transcript text for words overlapping a time range."""
    matched = []
    for w in words:
        if int(w["end_ms"]) <= seg_start_ms:
            continue
        if int(w["start_ms"]) >= seg_end_ms:
            break
        matched.append(str(w["word"]))
    return " ".join(matched)


def _normalize_audio_segment(audio_seg: object) -> object:
    """Normalize AudioSegment to -20 dBFS target loudness."""
    from pydub import AudioSegment
    seg = audio_seg
    assert isinstance(seg, AudioSegment)
    return seg.apply_gain(-20.0 - seg.dBFS)


def _phonemize_text(text: str) -> str:
    """Phonemize English text using espeak-ng backend."""
    from phonemizer import phonemize  # type: ignore[import-untyped]
    return str(phonemize(
        text, language="en-us", backend="espeak",
        strip=True, preserve_punctuation=True,
    )).strip()


async def prepare_voice_training_data(
    project_ids: list[str],
    speaker_label: str,
    output_dir: Path,
    projects_base: Path,
    min_clip_duration_ms: int = 1000,
    max_clip_duration_ms: int = 12000,
    val_split: float = 0.05,
) -> VoiceDataResult:
    """Prepare voice training data from one or more projects.

    Args:
        project_ids: Project identifiers to process.
        speaker_label: Speaker label for training data.
        output_dir: Directory for output clips and manifests.
        projects_base: Base directory containing project folders.
        min_clip_duration_ms: Minimum clip duration in ms.
        max_clip_duration_ms: Maximum clip duration in ms.
        val_split: Fraction of clips for validation holdout.

    Returns:
        VoiceDataResult with counts and output path.

    Raises:
        FileNotFoundError: If vocals.wav or analysis.db is missing.
        RuntimeError: If no valid clips are produced.
    """
    wavs_dir = output_dir / "wavs"
    wavs_dir.mkdir(parents=True, exist_ok=True)
    all_clips: list[_ClipInfo] = []

    for project_id in project_ids:
        proj_dir = projects_base / project_id
        vocals_path = proj_dir / "stems" / "vocals.wav"
        if not vocals_path.exists():
            raise FileNotFoundError(
                f"vocals.wav not found for project {project_id} at {vocals_path}"
            )
        db_path = proj_dir / "analysis.db"
        if not db_path.exists():
            raise FileNotFoundError(
                f"analysis.db not found for project {project_id} at {db_path}"
            )

        clips = await asyncio.to_thread(
            _process_single_project,
            project_id=project_id, vocals_path=vocals_path, db_path=db_path,
            wavs_dir=wavs_dir, speaker_label=speaker_label,
            min_clip_ms=min_clip_duration_ms, max_clip_ms=max_clip_duration_ms,
        )
        all_clips.extend(clips)
        logger.info("Project %s: produced %d clips", project_id, len(clips))

    if not all_clips:
        raise RuntimeError(
            "No valid clips produced. Check vocals.wav content and silence_gaps."
        )

    random.shuffle(all_clips)
    val_count = max(1, int(len(all_clips) * val_split))
    val_clips, train_clips = all_clips[:val_count], all_clips[val_count:]

    _write_manifest(output_dir / "train_list.txt", train_clips)
    _write_manifest(output_dir / "val_list.txt", val_clips)
    total_duration = sum(c.duration_s for c in all_clips)

    logger.info(
        "Voice data prepared: %d clips (%.1fs), %d train, %d val",
        len(all_clips), total_duration, len(train_clips), len(val_clips),
    )
    return VoiceDataResult(
        total_clips=len(all_clips),
        total_duration_s=round(total_duration, 2),
        train_count=len(train_clips),
        val_count=len(val_clips),
        output_dir=output_dir,
    )


def _process_single_project(
    project_id: str, vocals_path: Path, db_path: Path,
    wavs_dir: Path, speaker_label: str, min_clip_ms: int, max_clip_ms: int,
) -> list[_ClipInfo]:
    """Process a single project's vocals into training clips."""
    from pydub import AudioSegment

    audio = AudioSegment.from_wav(str(vocals_path))
    silence_gaps, words = _load_silence_gaps_and_words(db_path, project_id)
    segments = _compute_speech_segments(silence_gaps, len(audio), min_clip_ms, max_clip_ms)

    clips: list[_ClipInfo] = []
    for seg_start, seg_end in segments:
        text = _match_words_to_segment(words, seg_start, seg_end)
        if not text.strip():
            continue

        clip_audio = _normalize_audio_segment(audio[seg_start:seg_end])
        clip_path = wavs_dir / f"clip_{secrets.token_hex(4)}.wav"
        clip_audio.export(str(clip_path), format="wav")  # type: ignore[union-attr]

        clips.append(_ClipInfo(
            wav_path=clip_path, text=text,
            phonemes=_phonemize_text(text),
            duration_s=(seg_end - seg_start) / 1000.0,
            speaker_label=speaker_label,
        ))
    return clips


def _write_manifest(path: Path, clips: list[_ClipInfo]) -> None:
    """Write manifest in path|phonemes|speaker format."""
    with open(path, "w", encoding="utf-8") as f:
        for clip in clips:
            f.write(f"{clip.wav_path}|{clip.phonemes}|{clip.speaker_label}\n")
