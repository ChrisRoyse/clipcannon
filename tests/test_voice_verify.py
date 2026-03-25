"""Tests for voice verification multi-gate quality pipeline.

Tests use real audio from proj_76961210/stems/vocals.wav for
ECAPA-TDNN embedding extraction and gate validation. Segments
are extracted using pydub and saved as temporary WAV files.
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np
import pytest

REAL_VOCALS = (
    Path.home()
    / ".clipcannon"
    / "projects"
    / "proj_76961210"
    / "stems"
    / "vocals.wav"
)

HAVE_VOCALS = REAL_VOCALS.exists()
SKIP_NO_VOCALS = pytest.mark.skipif(
    not HAVE_VOCALS, reason="Real project vocals.wav not available",
)


@pytest.fixture()
def segment_a(tmp_path: Path) -> Path:
    """Seconds 30-35 of vocals.wav as a temp WAV (strong vocal section)."""
    from pydub import AudioSegment

    audio = AudioSegment.from_wav(str(REAL_VOCALS))
    clip = audio[30000:35000]
    out = tmp_path / "seg_a.wav"
    clip.export(str(out), format="wav")
    return out


@pytest.fixture()
def segment_b(tmp_path: Path) -> Path:
    """Seconds 90-95 of vocals.wav as a temp WAV (strong vocal section)."""
    from pydub import AudioSegment

    audio = AudioSegment.from_wav(str(REAL_VOCALS))
    clip = audio[90000:95000]
    out = tmp_path / "seg_b.wav"
    clip.export(str(out), format="wav")
    return out


@pytest.fixture()
def segment_c(tmp_path: Path) -> Path:
    """Seconds 10-15 of vocals.wav as a temp WAV."""
    from pydub import AudioSegment

    audio = AudioSegment.from_wav(str(REAL_VOCALS))
    clip = audio[10000:15000]
    out = tmp_path / "seg_c.wav"
    clip.export(str(out), format="wav")
    return out


@pytest.fixture()
def silent_wav(tmp_path: Path) -> Path:
    """One second of pure silence at 16kHz mono 16-bit."""
    out = tmp_path / "silence.wav"
    sr = 16000
    n_samples = sr
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{n_samples}h", *([0] * n_samples)))
    return out


# ===========================================================================
# WER COMPUTATION
# ===========================================================================


class TestComputeWer:
    """Tests for standalone WER computation."""

    def test_perfect_match(self) -> None:
        """Identical strings yield WER 0.0."""
        from clipcannon.voice.verify import compute_wer

        assert compute_wer("hello world", "hello world") == 0.0

    def test_one_substitution(self) -> None:
        """One word wrong out of two yields WER 0.5."""
        from clipcannon.voice.verify import compute_wer

        assert compute_wer("hello world", "hello earth") == 0.5

    def test_all_wrong(self) -> None:
        """Completely different text yields high WER."""
        from clipcannon.voice.verify import compute_wer

        wer = compute_wer("hello world", "foo bar baz")
        assert wer >= 1.0

    def test_empty_reference(self) -> None:
        """Empty reference with non-empty hypothesis yields 1.0."""
        from clipcannon.voice.verify import compute_wer

        assert compute_wer("", "hello") == 1.0

    def test_both_empty(self) -> None:
        """Both empty yields 0.0."""
        from clipcannon.voice.verify import compute_wer

        assert compute_wer("", "") == 0.0

    def test_case_insensitive(self) -> None:
        """WER is case insensitive."""
        from clipcannon.voice.verify import compute_wer

        assert compute_wer("Hello World", "hello world") == 0.0

    def test_insertion(self) -> None:
        """Extra words count as errors."""
        from clipcannon.voice.verify import compute_wer

        wer = compute_wer("hello world", "hello beautiful world")
        assert wer == pytest.approx(0.5)

    def test_deletion(self) -> None:
        """Missing words count as errors."""
        from clipcannon.voice.verify import compute_wer

        wer = compute_wer("hello beautiful world", "hello world")
        assert wer == pytest.approx(1 / 3)


# ===========================================================================
# ECAPA-TDNN EMBEDDING EXTRACTION
# ===========================================================================


@SKIP_NO_VOCALS
class TestEmbeddingExtraction:
    """Tests for ECAPA-TDNN embedding extraction."""

    def test_extract_embedding_returns_192_dim(self, segment_a: Path) -> None:
        """Embedding from a real vocal segment has shape (192,)."""
        from clipcannon.voice.verify import build_reference_embedding

        emb = build_reference_embedding([segment_a])
        assert emb.shape == (192,)
        assert emb.dtype == np.float32

    def test_same_audio_high_similarity(
        self, segment_a: Path, segment_b: Path,
    ) -> None:
        """Two segments from the same speaker have cosine similarity > 0.7."""
        from clipcannon.voice.verify import build_reference_embedding

        emb_a = build_reference_embedding([segment_a])
        emb_b = build_reference_embedding([segment_b])

        cos_sim = float(
            np.dot(emb_a, emb_b)
            / (np.linalg.norm(emb_a) * np.linalg.norm(emb_b))
        )
        assert cos_sim > 0.7, f"Same-speaker cosine similarity too low: {cos_sim:.3f}"

    def test_build_reference_embedding_from_3_clips(
        self, segment_a: Path, segment_b: Path, segment_c: Path,
    ) -> None:
        """Average embedding from 3 clips has shape (192,) and is L2-normalized."""
        from clipcannon.voice.verify import build_reference_embedding

        emb = build_reference_embedding([segment_a, segment_b, segment_c])
        assert emb.shape == (192,)
        norm = float(np.linalg.norm(emb))
        assert norm == pytest.approx(1.0, abs=1e-5), f"Not L2-normalized: norm={norm}"


# ===========================================================================
# GATE 1 (SANITY)
# ===========================================================================


@SKIP_NO_VOCALS
class TestGateSanity:
    """Tests for Gate 1: sanity checks."""

    def test_gate_sanity_passes_good_audio(self, segment_a: Path) -> None:
        """Gate 1 passes on a real vocal segment with reasonable text."""
        from clipcannon.voice.verify import VoiceVerifier, build_reference_embedding

        ref_emb = build_reference_embedding([segment_a])
        verifier = VoiceVerifier(ref_emb, threshold=0.50)

        # ~5 seconds of speech; provide ~30 words so expected duration ~ 4.5s
        text = (
            "This is a sample sentence with several words used for testing "
            "the gate sanity check to make sure duration ratio falls within "
            "the acceptable range for real audio segments"
        )
        passed, details = verifier.gate_sanity(segment_a, text)
        assert passed, f"Gate 1 failed: {details}"
        assert "duration_ratio" in details
        assert "snr_db" in details

    def test_gate_sanity_fails_silent_audio(
        self, silent_wav: Path, segment_a: Path,
    ) -> None:
        """Gate 1 fails on a completely silent audio file (low SNR)."""
        from clipcannon.voice.verify import VoiceVerifier, build_reference_embedding

        ref_emb = build_reference_embedding([segment_a])
        verifier = VoiceVerifier(ref_emb, threshold=0.50)

        passed, details = verifier.gate_sanity(
            silent_wav, "hello world this is a test",
        )
        assert not passed, f"Gate 1 should fail on silence: {details}"


# ===========================================================================
# GATE 3 (IDENTITY)
# ===========================================================================


@SKIP_NO_VOCALS
class TestGateIdentity:
    """Tests for Gate 3: speaker identity verification."""

    def test_gate_identity_passes_same_speaker(
        self, segment_a: Path, segment_b: Path,
    ) -> None:
        """Gate 3 passes when reference and test are same speaker."""
        from clipcannon.voice.verify import VoiceVerifier, build_reference_embedding

        ref_emb = build_reference_embedding([segment_a])
        verifier = VoiceVerifier(ref_emb, threshold=0.50)

        passed, details = verifier.gate_identity(segment_b)
        assert passed, f"Gate 3 failed on same speaker: {details}"
        assert float(details["secs_score"]) > 0.50


# ===========================================================================
# FULL VERIFY PIPELINE
# ===========================================================================


@SKIP_NO_VOCALS
class TestVerifyPipeline:
    """Tests for the full verify() pipeline."""

    def test_verify_returns_result(
        self, segment_a: Path, segment_b: Path,
    ) -> None:
        """Full verify() returns a VerificationResult with all fields."""
        from clipcannon.voice.verify import (
            VoiceVerifier,
            VerificationResult,
            build_reference_embedding,
        )

        ref_emb = build_reference_embedding([segment_a])
        verifier = VoiceVerifier(ref_emb, threshold=0.50)

        result = verifier.verify(
            segment_b,
            "This is some speech that roughly matches the audio length",
        )
        assert isinstance(result, VerificationResult)
        assert result.attempt == 1
        assert result.max_attempts == 3
        assert isinstance(result.secs_score, float)
        assert isinstance(result.wer, float)
        assert isinstance(result.duration_ratio, float)
        assert isinstance(result.has_clipping, bool)
        assert isinstance(result.snr_db, float)
        # gate_failed is None if passed, or a string
        assert result.gate_failed is None or isinstance(result.gate_failed, str)
        assert isinstance(result.gate_details, dict)

    def test_verify_silent_fails_at_sanity(
        self, segment_a: Path, silent_wav: Path,
    ) -> None:
        """Verify on silent audio fails at the sanity gate."""
        from clipcannon.voice.verify import VoiceVerifier, build_reference_embedding

        ref_emb = build_reference_embedding([segment_a])
        verifier = VoiceVerifier(ref_emb, threshold=0.50)

        result = verifier.verify(silent_wav, "hello world test")
        assert not result.passed
        assert result.gate_failed == "sanity"
