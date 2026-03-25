"""Voice verification with multi-gate quality pipeline.

Gates: (1) Sanity -- duration, clipping, SNR, silence
       (2) Intelligibility -- WER via Whisper
       (3) Identity -- ECAPA-TDNN cosine similarity
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
import torchaudio

logger = logging.getLogger(__name__)
_DEFAULT_MODEL_DIR = Path.home() / ".clipcannon" / "models" / "ecapa-tdnn"

# Module-level cache for expensive model loads
_whisper_model: object | None = None


@dataclass
class VerificationResult:
    """Result of multi-gate voice verification."""

    passed: bool
    attempt: int
    max_attempts: int
    secs_score: float
    wer: float
    duration_ratio: float
    has_clipping: bool
    snr_db: float
    gate_failed: str | None
    gate_details: dict[str, dict[str, object]] = field(default_factory=dict)


# -- WER (no jiwer) ----------------------------------------------------------

def _levenshtein_distance(a: list[str], b: list[str]) -> int:
    """Levenshtein edit distance between two word lists."""
    m, n = len(a), len(b)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[n]


def compute_wer(reference: str, hypothesis: str) -> float:
    """Word Error Rate between reference and hypothesis (case-insensitive)."""
    ref_words = reference.lower().split()
    hyp_words = hypothesis.lower().split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return _levenshtein_distance(ref_words, hyp_words) / len(ref_words)


# -- Audio helpers ------------------------------------------------------------

def _load_mono_16k(audio_path: Path) -> tuple[torch.Tensor, int]:
    """Load audio as mono 16 kHz waveform [1, samples]."""
    wav, sr = torchaudio.load(str(audio_path))
    if wav.shape[0] > 1:
        wav = wav.mean(dim=0, keepdim=True)
    if sr != 16000:
        wav = torchaudio.functional.resample(wav, sr, 16000)
        sr = 16000
    return wav, sr


def _compute_snr(wav: torch.Tensor, sr: int, threshold: float = 0.01) -> float:
    """Simple energy-based SNR estimate in dB."""
    samples = wav.squeeze().abs()
    speech = samples > threshold
    noise = ~speech
    if speech.sum() == 0:
        return 0.0
    if noise.sum() == 0:
        return 60.0
    sp = (samples[speech] ** 2).mean().item()
    np_ = (samples[noise] ** 2).mean().item()
    return 60.0 if np_ < 1e-12 else 10.0 * math.log10(sp / np_)


def _max_silence_gap_ms(wav: torch.Tensor, sr: int, threshold: float = 0.01) -> float:
    """Longest consecutive silence gap in milliseconds.

    Uses vectorized diff on silence boundaries instead of a Python
    per-sample loop, which is ~100x faster for typical audio lengths.
    """
    is_silent = wav.squeeze().abs() < threshold
    if not is_silent.any():
        return 0.0
    # Find indices where silence state changes
    changes = torch.diff(is_silent.int())
    # Starts of silent runs (0->1 transitions)
    starts = torch.where(changes == 1)[0] + 1
    # Ends of silent runs (1->0 transitions)
    ends = torch.where(changes == -1)[0] + 1
    # Handle edge cases: silence at the beginning or end
    if is_silent[0]:
        starts = torch.cat([torch.tensor([0], device=starts.device), starts])
    if is_silent[-1]:
        ends = torch.cat([ends, torch.tensor([len(is_silent)], device=ends.device)])
    if len(starts) == 0 or len(ends) == 0:
        return 0.0
    gaps = ends - starts
    max_gap = int(gaps.max().item())
    return max_gap / sr * 1000.0


def _transcribe_audio(audio_path: Path) -> str:
    """Transcribe via faster_whisper; returns empty string if unavailable.

    Caches the WhisperModel at module level to avoid reloading (~2s)
    on every verification attempt.
    """
    global _whisper_model
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.warning("faster_whisper not installed; skipping transcription")
        return ""
    if _whisper_model is None:
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    segs, _ = _whisper_model.transcribe(str(audio_path), language="en")
    return " ".join(s.text.strip() for s in segs)


# -- VoiceVerifier ------------------------------------------------------------

class VoiceVerifier:
    """Stateful verifier with loaded ECAPA-TDNN model."""

    def __init__(
        self, reference_embedding: np.ndarray,
        threshold: float = 0.80, model_dir: Path | None = None,
    ) -> None:
        """Load ECAPA-TDNN and store reference embedding."""
        from speechbrain.inference.speaker import SpeakerRecognition
        self._model_dir = model_dir or _DEFAULT_MODEL_DIR
        self._model_dir.mkdir(parents=True, exist_ok=True)
        self._model = SpeakerRecognition.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=str(self._model_dir),
        )
        self._ref_emb = reference_embedding.astype(np.float32)
        self._threshold = threshold
        logger.info("VoiceVerifier ready (threshold=%.2f)", threshold)

    def extract_embedding(self, audio_path: Path) -> np.ndarray:
        """Extract 192-dim ECAPA-TDNN embedding from audio file."""
        wav, _ = _load_mono_16k(audio_path)
        return self._model.encode_batch(wav).squeeze().cpu().numpy().astype(np.float32)

    def compute_secs(self, audio_path: Path) -> float:
        """Speaker Encoder Cosine Similarity against reference."""
        emb = self.extract_embedding(audio_path)
        norm = np.linalg.norm(self._ref_emb) * np.linalg.norm(emb)
        return 0.0 if norm < 1e-12 else float(np.dot(self._ref_emb, emb) / norm)

    def gate_sanity(
        self, audio_path: Path, expected_text: str,
    ) -> tuple[bool, dict[str, object]]:
        """Gate 1: Duration ratio, clipping, SNR, silence checks."""
        wav, sr = _load_mono_16k(audio_path)
        dur = wav.shape[1] / sr
        words = max(len(expected_text.split()), 1)
        # Natural speech: 250-400ms per word. Use 300ms as baseline.
        exp_dur = words * 0.30
        ratio = dur / exp_dur if exp_dur > 0 else 1.0
        clipping = bool((wav.abs() > 0.99).any().item())
        snr = _compute_snr(wav, sr)
        silence = _max_silence_gap_ms(wav, sr)

        info: dict[str, object] = {
            "duration_s": round(dur, 3), "expected_duration_s": round(exp_dur, 3),
            "duration_ratio": round(ratio, 3), "has_clipping": clipping,
            "snr_db": round(snr, 1), "max_silence_ms": round(silence, 1),
        }
        reason = None
        if not (0.2 <= ratio <= 5.0):
            reason = f"duration_ratio={ratio:.2f} outside [0.2, 5.0]"
        elif clipping:
            reason = "audio has clipping (samples > 0.99)"
        elif snr < 10.0:
            reason = f"SNR={snr:.1f}dB < 10dB"
        elif silence > 3000.0:
            reason = f"silence gap {silence:.0f}ms > 3000ms"
        if reason:
            info["fail_reason"] = reason
            logger.info("Gate 1 FAILED: %s", reason)
        return reason is None, info

    def gate_intelligibility(
        self, audio_path: Path, expected_text: str, wer_threshold: float = 0.10,
    ) -> tuple[bool, dict[str, object]]:
        """Gate 2: WER via Whisper transcription."""
        transcript = _transcribe_audio(audio_path)
        if not transcript:
            return True, {"skipped": True, "reason": "transcriber unavailable"}
        wer = compute_wer(expected_text, transcript)
        info: dict[str, object] = {
            "expected_text": expected_text, "transcript": transcript,
            "wer": round(wer, 4), "wer_threshold": wer_threshold,
        }
        if wer > wer_threshold:
            info["fail_reason"] = f"WER={wer:.2%} > {wer_threshold:.0%}"
            logger.info("Gate 2 FAILED: WER=%.1f%%", wer * 100)
        return wer <= wer_threshold, info

    def gate_identity(self, audio_path: Path) -> tuple[bool, dict[str, object]]:
        """Gate 3: SECS against reference embedding."""
        secs = self.compute_secs(audio_path)
        info: dict[str, object] = {"secs_score": round(secs, 4), "threshold": self._threshold}
        if secs < self._threshold:
            info["fail_reason"] = f"SECS={secs:.3f} < {self._threshold:.2f}"
            logger.info("Gate 3 FAILED: SECS=%.3f", secs)
        return secs >= self._threshold, info

    def verify(
        self, audio_path: Path, expected_text: str,
        attempt: int = 1, max_attempts: int = 3,
    ) -> VerificationResult:
        """Run all gates in order. Stops at first failure."""
        gd: dict[str, dict[str, object]] = {}

        def _result(passed: bool, gate: str | None, **kw: object) -> VerificationResult:
            return VerificationResult(
                passed=passed, attempt=attempt, max_attempts=max_attempts,
                gate_failed=gate, gate_details=gd, **kw,  # type: ignore[arg-type]
            )

        g1_ok, g1 = self.gate_sanity(audio_path, expected_text)
        gd["sanity"] = g1
        if not g1_ok:
            return _result(
                False, "sanity", secs_score=0.0, wer=1.0,
                duration_ratio=float(g1.get("duration_ratio", 0)),
                has_clipping=bool(g1.get("has_clipping", False)),
                snr_db=float(g1.get("snr_db", 0)),
            )

        g2_ok, g2 = self.gate_intelligibility(audio_path, expected_text)
        gd["intelligibility"] = g2
        g3_ok, g3 = self.gate_identity(audio_path)
        gd["identity"] = g3

        secs = float(g3.get("secs_score", 0))
        wer = float(g2.get("wer", 0))
        dr = float(g1.get("duration_ratio", 0))
        clip = bool(g1.get("has_clipping", False))
        snr = float(g1.get("snr_db", 0))
        common = dict(secs_score=secs, wer=wer, duration_ratio=dr,
                      has_clipping=clip, snr_db=snr)

        if not g2_ok:
            return _result(False, "intelligibility", **common)
        if not g3_ok:
            return _result(False, "identity", **common)
        logger.info("All gates passed (SECS=%.3f, WER=%.1f%%)", secs, wer * 100)
        return _result(True, None, **common)


# -- Reference embedding builder ----------------------------------------------

def build_reference_embedding(
    audio_paths: list[Path], model_dir: Path | None = None,
) -> np.ndarray:
    """Build average L2-normalized ECAPA-TDNN embedding from reference clips.

    Args:
        audio_paths: Paths to reference audio files.
        model_dir: Optional model cache directory.

    Returns:
        L2-normalized numpy array of shape (192,).

    Raises:
        ValueError: If audio_paths is empty.
        FileNotFoundError: If any path does not exist.
    """
    if not audio_paths:
        raise ValueError("audio_paths must not be empty")
    from speechbrain.inference.speaker import SpeakerRecognition
    save_dir = model_dir or _DEFAULT_MODEL_DIR
    save_dir.mkdir(parents=True, exist_ok=True)
    model = SpeakerRecognition.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb", savedir=str(save_dir),
    )
    embs: list[np.ndarray] = []
    for p in audio_paths:
        if not p.exists():
            raise FileNotFoundError(f"Reference audio not found: {p}")
        wav, _ = _load_mono_16k(p)
        embs.append(model.encode_batch(wav).squeeze().cpu().numpy().astype(np.float32))
    avg = np.mean(embs, axis=0)
    norm = np.linalg.norm(avg)
    if norm > 1e-12:
        avg = avg / norm
    logger.info("Built reference embedding from %d clips", len(audio_paths))
    return avg
