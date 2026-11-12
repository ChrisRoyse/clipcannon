"""Visemes, precomputed face landmarks and ClipCannon analysis-DB lookups for labeling."""
import logging
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np

from .schema import CLIP_DURATION_MS, LANDMARKS_FILE, PHONEME_TO_VISEME

log = logging.getLogger("label")


def load_cmu_dict():
    """Load CMU pronunciation dictionary."""
    import nltk
    from nltk.corpus import cmudict
    try:
        return cmudict.dict()
    except LookupError:
        nltk.download("cmudict", quiet=True)
        return cmudict.dict()


def word_to_visemes(word: str, cmu: dict, word_start: int, word_end: int) -> list:
    """Convert a word to (viseme, start_ms, end_ms) tuples."""
    word_clean = word.lower().strip(".,!?;:\"'()[]")
    phones = cmu.get(word_clean, [])
    if not phones:
        return [("SIL", word_start, word_end)]
    phoneme_list = phones[0]
    if not phoneme_list:
        return [("SIL", word_start, word_end)]
    duration = word_end - word_start
    step = duration / len(phoneme_list)
    visemes = []
    for i, phoneme in enumerate(phoneme_list):
        viseme = PHONEME_TO_VISEME.get(phoneme, "SIL")
        p_start = int(word_start + i * step)
        p_end = int(word_start + (i + 1) * step)
        visemes.append((viseme, p_start, p_end))
    return visemes


def build_frame_viseme_sequence(visemes: list, clip_start_ms: int, n_frames: int) -> list:
    """Convert (viseme, start_ms, end_ms) to per-frame viseme labels."""
    frame_duration_ms = CLIP_DURATION_MS / n_frames
    sequence = []
    for frame_idx in range(n_frames):
        frame_ms = clip_start_ms + frame_idx * frame_duration_ms
        active = "SIL"
        for viseme, v_start, v_end in visemes:
            if v_start <= frame_ms < v_end:
                active = viseme
                break
        sequence.append(active)
    return sequence


def load_precomputed_landmarks():
    """Load the precomputed face landmarks file.

    This is the single source of truth for face positions and mouth bboxes.
    Produced by precompute_face_landmarks.py using YOLOv5-Face.
    """
    if not LANDMARKS_FILE.exists():
        raise FileNotFoundError(
            f"Face landmarks file not found: {LANDMARKS_FILE}\n"
            f"Run: python scripts/precompute_face_landmarks.py"
        )
    data = np.load(LANDMARKS_FILE)
    log.info("Loaded landmarks: %d frames at %dfps",
             len(data["frame_idx"]), int(data["fps"]))
    log.info("Detection rate: %d/%d (%.1f%%)",
             int(data["detected"].sum()), len(data["detected"]),
             data["detected"].mean() * 100)
    return {
        "timestamp_ms": data["timestamp_ms"],
        "detected": data["detected"],
        "bboxes": data["bboxes"],
        "keypoints": data["keypoints"],
        "mouth_bboxes": data["mouth_bboxes"],
        "scores": data["scores"],
        "fps": int(data["fps"]),
    }


def get_landmarks_for_frame(landmarks: dict, ms: int):
    """Look up the nearest landmark entry for a given timestamp (ms).

    Uses simple nearest-neighbor matching on the timestamp array.
    """
    ts = landmarks["timestamp_ms"]
    # Find nearest frame index
    idx = int(np.searchsorted(ts, ms))
    if idx >= len(ts):
        idx = len(ts) - 1
    elif idx > 0 and (ms - ts[idx - 1]) < (ts[idx] - ms):
        idx -= 1

    return {
        "idx": idx,
        "detected": bool(landmarks["detected"][idx]),
        "bbox": landmarks["bboxes"][idx].tolist(),
        "mouth_bbox": landmarks["mouth_bboxes"][idx].tolist(),
        "keypoints": landmarks["keypoints"][idx].tolist(),
        "score": float(landmarks["scores"][idx]),
    }


def load_analysis_data(db_path: Path, project_id: str) -> dict:
    """Load words, prosody, emotion, silence gaps from ClipCannon DB.

    Note: the diarization in this particular project collapsed all speakers
    into speaker_id=1, so we cannot filter by speaker. Instead, we filter
    out words that fall inside silence_gaps longer than 1 second (those
    are likely non-speech regions).
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    data = {}

    rows = conn.execute(
        """SELECT w.word, w.start_ms, w.end_ms, w.confidence,
                  s.text as segment_text, s.start_ms as seg_start, s.end_ms as seg_end
           FROM transcript_words w
           JOIN transcript_segments s ON w.segment_id = s.segment_id
           WHERE s.project_id=?
           ORDER BY w.start_ms""",
        (project_id,),
    ).fetchall()
    data["words"] = [dict(r) for r in rows]
    log.info("Loaded %d words", len(data["words"]))

    rows = conn.execute(
        """SELECT start_ms, end_ms, f0_mean, f0_std, energy_mean, energy_peak,
                  speaking_rate_wpm, energy_level, pitch_contour_type,
                  has_emphasis, has_breath, transcript_text
           FROM prosody_segments WHERE project_id=?
           ORDER BY start_ms""",
        (project_id,),
    ).fetchall()
    data["prosody"] = [dict(r) for r in rows]
    log.info("Loaded %d prosody segments", len(data["prosody"]))

    rows = conn.execute(
        """SELECT start_ms, end_ms, AVG(arousal) as arousal,
                  AVG(valence) as valence, AVG(energy) as energy
           FROM emotion_curve WHERE project_id=?
           GROUP BY start_ms, end_ms ORDER BY start_ms""",
        (project_id,),
    ).fetchall()
    data["emotion"] = [dict(r) for r in rows]
    log.info("Loaded %d emotion windows", len(data["emotion"]))

    rows = conn.execute(
        """SELECT start_ms, end_ms, duration_ms, type
           FROM silence_gaps WHERE project_id=?
           ORDER BY start_ms""",
        (project_id,),
    ).fetchall()
    data["silence_gaps"] = [dict(r) for r in rows]
    log.info("Loaded %d silence gaps", len(data["silence_gaps"]))

    conn.close()
    return data


def get_prosody_for_range(start_ms: int, end_ms: int, prosody: list) -> Optional[dict]:
    """Find the prosody segment that most overlaps this range."""
    best = None
    best_overlap = 0
    for p in prosody:
        overlap = min(end_ms, p["end_ms"]) - max(start_ms, p["start_ms"])
        if overlap > best_overlap:
            best_overlap = overlap
            best = p
    return best


def get_emotion_for_range(start_ms: int, end_ms: int, emotion: list) -> tuple:
    """Average emotion across overlapping windows."""
    arousal_vals = []
    valence_vals = []
    energy_vals = []
    for e in emotion:
        overlap = min(end_ms, e["end_ms"]) - max(start_ms, e["start_ms"])
        if overlap > 0:
            arousal_vals.append(e["arousal"])
            valence_vals.append(e["valence"])
            energy_vals.append(e.get("energy", 0))
    if not arousal_vals:
        return 0.19, 0.51, 0.0
    return (float(np.mean(arousal_vals)),
            float(np.mean(valence_vals)),
            float(np.mean(energy_vals)))


def is_in_long_silence(center_ms: int, silence_gaps: list) -> bool:
    """Is this moment inside a long silence (>1s)?

    Since diarization failed, we use silence gaps as a proxy to filter out
    interviewer speech and long pauses where Santa isn't speaking.
    """
    for s in silence_gaps:
        duration = s.get("duration_ms", s["end_ms"] - s["start_ms"])
        if duration >= 1000 and s["start_ms"] <= center_ms <= s["end_ms"]:
            return True
    return False
