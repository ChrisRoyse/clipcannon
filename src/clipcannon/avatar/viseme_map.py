"""Phoneme-to-viseme mapping for lip-sync support.

Maps English phonemes (ARPAbet from CMU Pronouncing Dictionary) to
visual mouth shapes (visemes). Provides word-to-phoneme lookup with
proportional timing within word boundaries.

The 14-viseme system is based on MPEG-4 Facial Animation Parameters
and the Disney animation standard.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

# 14-viseme system: phoneme → viseme category
# Each viseme represents a distinct visible mouth shape
PHONEME_TO_VISEME: dict[str, str] = {
    # Silence / neutral
    "SIL": "SIL",
    # Bilabial: lips pressed together (P, B, M)
    "P": "PP", "B": "PP", "M": "PP",
    # Labiodental: lower lip under upper teeth (F, V)
    "F": "FF", "V": "FF",
    # Dental: tongue between teeth (TH, DH)
    "TH": "TH", "DH": "TH",
    # Alveolar: tongue on upper ridge (T, D, N, L)
    "T": "DD", "D": "DD", "N": "DD", "L": "DD",
    # Velar: back tongue raised (K, G, NG)
    "K": "KK", "G": "KK", "NG": "KK",
    # Postalveolar: lips rounded, teeth close (CH, JH, SH, ZH)
    "CH": "CH", "JH": "CH", "SH": "CH", "ZH": "CH",
    # Sibilant: teeth close, lips slightly open (S, Z)
    "S": "SS", "Z": "SS",
    # Rhotic: lips slightly rounded (R, ER)
    "R": "RR", "ER": "RR", "ER0": "RR", "ER1": "RR", "ER2": "RR",
    # Open vowels: wide open (AA, AE, AH)
    "AA": "AA", "AA0": "AA", "AA1": "AA", "AA2": "AA",
    "AE": "AA", "AE0": "AA", "AE1": "AA", "AE2": "AA",
    "AH": "AA", "AH0": "AA", "AH1": "AA", "AH2": "AA",
    # Mid vowels: mid-open, spread (EH, EY)
    "EH": "EH", "EH0": "EH", "EH1": "EH", "EH2": "EH",
    "EY": "EH", "EY0": "EH", "EY1": "EH", "EY2": "EH",
    # Front close vowels: narrow, spread (IH, IY)
    "IH": "IH", "IH0": "IH", "IH1": "IH", "IH2": "IH",
    "IY": "IH", "IY0": "IH", "IY1": "IH", "IY2": "IH",
    # Back mid vowels: rounded, mid-open (AO, OW)
    "AO": "OH", "AO0": "OH", "AO1": "OH", "AO2": "OH",
    "OW": "OH", "OW0": "OH", "OW1": "OH", "OW2": "OH",
    # Back close vowels: tight round (UW, UH, W)
    "UW": "OO", "UW0": "OO", "UW1": "OO", "UW2": "OO",
    "UH": "OO", "UH0": "OO", "UH1": "OO", "UH2": "OO",
    "W": "OO",
    # Glottal / approximants (mapped to nearest visual equivalent)
    "HH": "AA",  # glottal fricative → open mouth
    "Y": "IH",   # palatal approximant → spread lips
    "AW": "OH", "AW0": "OH", "AW1": "OH", "AW2": "OH",
    "AY": "AA", "AY0": "AA", "AY1": "AA", "AY2": "AA",
    "OY": "OH", "OY0": "OH", "OY1": "OH", "OY2": "OH",
}

# All viseme categories
ALL_VISEMES = sorted(set(PHONEME_TO_VISEME.values()))

# Viseme → typical mouth openness (0-1) and width (0-1)
VISEME_GEOMETRY: dict[str, tuple[float, float]] = {
    "SIL": (0.0, 0.5),   # closed, neutral width
    "PP":  (0.0, 0.4),   # closed, compressed
    "FF":  (0.15, 0.5),  # slightly open, neutral
    "TH":  (0.2, 0.5),   # slightly open
    "DD":  (0.2, 0.5),   # slightly open
    "KK":  (0.25, 0.5),  # slightly open
    "CH":  (0.2, 0.4),   # slightly open, rounded
    "SS":  (0.1, 0.5),   # barely open
    "RR":  (0.2, 0.4),   # slightly open, rounded
    "AA":  (0.9, 0.7),   # wide open
    "EH":  (0.5, 0.6),   # mid open, spread
    "IH":  (0.3, 0.7),   # narrow, spread
    "OH":  (0.6, 0.4),   # open, rounded
    "OO":  (0.3, 0.3),   # tight round
}


@lru_cache(maxsize=1)
def _load_cmu_dict() -> dict[str, list[list[str]]]:
    """Load CMU Pronouncing Dictionary via NLTK.

    Returns:
        Dict mapping lowercase words to lists of phoneme sequences.
    """
    try:
        from nltk.corpus import cmudict
        return cmudict.dict()
    except LookupError:
        logger.info("Downloading CMU Pronouncing Dictionary...")
        import nltk
        nltk.download("cmudict", quiet=True)
        from nltk.corpus import cmudict
        return cmudict.dict()
    except ImportError:
        logger.warning("NLTK not installed, phoneme lookup unavailable")
        return {}


def _g2p_fallback(word: str) -> list[str]:
    """Grapheme-to-phoneme fallback for OOV words.

    Uses simple rule-based approximation when g2p-en is not available.
    """
    try:
        from g2p_en import G2p
        g2p = G2p()
        phonemes = g2p(word)
        return [p for p in phonemes if p.strip()]
    except ImportError:
        # Very basic fallback: one phoneme per vowel cluster
        vowels = re.findall(r'[aeiouy]+', word.lower())
        return ["AH1"] * max(1, len(vowels))


def word_to_phonemes(word: str) -> list[str]:
    """Convert a word to ARPAbet phonemes.

    Uses CMU Pronouncing Dictionary with g2p fallback for OOV words.

    Args:
        word: English word (case-insensitive).

    Returns:
        List of ARPAbet phoneme strings (e.g. ["HH", "AH0", "L", "OW1"]).
    """
    clean = re.sub(r"[^a-zA-Z']", "", word).lower()
    if not clean:
        return ["SIL"]

    cmu = _load_cmu_dict()
    if clean in cmu:
        return cmu[clean][0]

    # Try without trailing 's
    if clean.endswith("'s") and clean[:-2] in cmu:
        return cmu[clean[:-2]][0] + ["Z"]

    return _g2p_fallback(clean)


def phoneme_to_viseme(phoneme: str) -> str:
    """Map a single ARPAbet phoneme to its viseme category.

    Args:
        phoneme: ARPAbet phoneme (e.g. "AA1", "P", "SH").

    Returns:
        Viseme category string (e.g. "AA", "PP", "CH").
    """
    # Strip stress markers (0, 1, 2) for lookup
    base = re.sub(r"[0-9]", "", phoneme)
    return PHONEME_TO_VISEME.get(phoneme, PHONEME_TO_VISEME.get(base, "AA"))


def build_viseme_timeline(
    words: list[dict[str, object]],
    fps: int = 25,
) -> list[dict[str, object]]:
    """Build a frame-level viseme timeline from word timestamps.

    Takes word-level timestamps (from transcript_words) and produces
    a viseme assignment for every frame at the given fps.

    Args:
        words: List of dicts with "word", "start_ms", "end_ms" keys.
        fps: Target frame rate.

    Returns:
        List of dicts per frame: {
            "frame_idx": int,
            "timestamp_ms": int,
            "viseme": str,
            "phoneme": str,
            "word": str,
            "word_position": str,  # "start", "middle", "end"
            "prev_viseme": str,
            "next_viseme": str,
        }
    """
    if not words:
        return []

    # Find total duration
    max_ms = max(int(w["end_ms"]) for w in words)
    total_frames = (max_ms * fps) // 1000 + 1
    frame_ms = 1000 / fps

    # Build phoneme-level timeline first
    phoneme_events: list[dict[str, object]] = []

    for w in words:
        word_text = str(w["word"]).strip()
        start_ms = int(w["start_ms"])
        end_ms = int(w["end_ms"])
        if not word_text or end_ms <= start_ms:
            continue

        phonemes = word_to_phonemes(word_text)
        if not phonemes:
            continue

        # Distribute phonemes proportionally across word duration
        dur_per_phoneme = (end_ms - start_ms) / len(phonemes)

        for i, ph in enumerate(phonemes):
            ph_start = start_ms + int(i * dur_per_phoneme)
            ph_end = start_ms + int((i + 1) * dur_per_phoneme)
            vis = phoneme_to_viseme(ph)

            if i == 0 and len(phonemes) > 1:
                pos = "start"
            elif i == len(phonemes) - 1 and len(phonemes) > 1:
                pos = "end"
            else:
                pos = "middle"

            phoneme_events.append({
                "start_ms": ph_start,
                "end_ms": ph_end,
                "phoneme": ph,
                "viseme": vis,
                "word": word_text,
                "word_position": pos,
            })

    if not phoneme_events:
        return []

    # Sample at frame rate
    frames: list[dict[str, object]] = []
    ev_idx = 0

    for f in range(total_frames):
        t_ms = int(f * frame_ms)

        # Find current phoneme event
        while ev_idx < len(phoneme_events) - 1 and int(phoneme_events[ev_idx]["end_ms"]) <= t_ms:
            ev_idx += 1

        ev = phoneme_events[ev_idx]
        if int(ev["start_ms"]) <= t_ms <= int(ev["end_ms"]):
            viseme = str(ev["viseme"])
            phoneme = str(ev["phoneme"])
            word = str(ev["word"])
            word_pos = str(ev["word_position"])
        else:
            viseme = "SIL"
            phoneme = "SIL"
            word = ""
            word_pos = ""

        prev_vis = frames[-1]["viseme"] if frames else "SIL"
        # Next viseme lookahead
        next_vis = "SIL"
        next_t = t_ms + int(frame_ms)
        for j in range(ev_idx, min(ev_idx + 3, len(phoneme_events))):
            nev = phoneme_events[j]
            if int(nev["start_ms"]) <= next_t <= int(nev["end_ms"]):
                next_vis = str(nev["viseme"])
                break

        frames.append({
            "frame_idx": f,
            "timestamp_ms": t_ms,
            "viseme": viseme,
            "phoneme": phoneme,
            "word": word,
            "word_position": word_pos,
            "prev_viseme": str(prev_vis),
            "next_viseme": next_vis,
        })

    return frames
