"""Constants and thresholds for the transcription stage."""

from __future__ import annotations

OPERATION = "transcription"
STAGE = "whisperx"


# ============================================================
# ANTI-HALLUCINATION CONFIGURATION
# ============================================================

# VAD thresholds for WhisperX (pyannote-based)
# Higher vad_onset = more selective about what counts as speech
_VAD_ONSET = 0.5
_VAD_OFFSET = 0.363

# Thresholds for faster-whisper fallback (ignored by WhisperX batched mode)
_NO_SPEECH_THRESHOLD = 0.4
_LOG_PROB_THRESHOLD = -0.7
_COMPRESSION_RATIO_THRESHOLD = 2.0
# Silence duration (seconds) that triggers hallucination suppression
_HALLUCINATION_SILENCE_THRESHOLD = 2.0

# Post-transcription filtering thresholds
_MIN_WORD_CONFIDENCE = 0.3
_MIN_SEGMENT_CONFIDENCE = 0.4
# Compression ratio above this indicates repetitive/hallucinated text
_MAX_COMPRESSION_RATIO = 2.0
# Known hallucination phrases -- ~35% of all Whisper hallucinations
# are just the top 2, and >50% come from the top 10.
# Substring-matched against normalized segment text.
_HALLUCINATION_PHRASES: list[str] = [
    "thank you for watching",
    "thanks for watching",
    "thank you for listening",
    "thanks for listening",
    "please subscribe",
    "like and subscribe",
    "subscribe to my channel",
    "subtitles by the amara.org community",
    "subtitles by",
    "transcript emily beynon",
    "please like and subscribe",
    "thanks for tuning in",
    "see you in the next video",
    "don't forget to subscribe",
    "hit the bell",
    "leave a comment below",
    "visit our website",
    "see you next time",
    "bye bye",
    "bye-bye",
    "music playing",
]

# Single-word or very short phrases that are hallucinated only when
# they appear as the ENTIRE segment text (not as part of real speech).
_HALLUCINATION_EXACT: list[str] = [
    "music",
    "applause",
    "laughter",
    "silence",
    "the end",
    "you",
    "check out my",
]


# ============================================================
# AUDIO CONTENT DIAGNOSTICS
# ============================================================
# Peak level below this is treated as digital silence: nothing for any
# VAD or ASR model to latch onto. Chosen well below the -40 dBFS floor
# of typical room-noise recordings but above pure numerical noise.
_SILENCE_PEAK_DBFS = -50.0
# Minimum percentage of the source that must exceed the audible threshold
# (per 50ms frame) before we will even try WhisperX. Anything below this
# is a silent/near-silent source; fail fast rather than burn GPU time.
_MIN_AUDIBLE_PCT = 1.0
# Per-frame audible threshold used to compute the audible percentage.
_AUDIBLE_FRAME_DBFS = -50.0
