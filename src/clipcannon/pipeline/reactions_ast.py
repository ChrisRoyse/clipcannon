"""Reaction instrument used when FunASR is not installed: AST on AudioSet.

Audio Spectrogram Transformer fine-tuned on AudioSet (native transformers
class, no remote code), pinned to one revision and loaded from the local
cache only (the runtime is offline, #59). It replaces the energy/spectral
heuristic, which on 560 human-labelled ESC-50 clips found 1/40 laughter and
6/40 applause clips while flagging 82/480 non-reaction clips.

Each 5 s window (2.5 s hop) is scored with the max sigmoid over the AudioSet
laughter labels and over Applause/Clapping. Thresholds were chosen on ESC-50
folds 1-3 as the highest recall with zero false positives there; on held-out
folds 4-5 they gave laughter 11/16, applause 15/16, 0/208 false positives
(scripts/fsv/fsv_reactions_bench.py). The stored confidence is that
probability, not a constant.
"""

from __future__ import annotations

import gc
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

INSTRUMENT = "ast_audioset"


class ReactionInstrumentError(RuntimeError):
    """The reaction instrument cannot run; carries code + remediation."""

    def __init__(self, code: str, message: str, remediation: str) -> None:
        super().__init__(f"{code}: {message} Remediation: {remediation}")
        self.code, self.remediation = code, remediation


@dataclass(frozen=True)
class AstIdentity:
    model_id: str = "MIT/ast-finetuned-audioset-10-10-0.4593"
    revision: str = "f826b80d28226b62986cc218e5cec390b1096902"
    weights_sha256: str = "ae0c1e2ad4e1381d851fa9bf298ba13ebc9c5a914cdee2dbe427a6583869924d"
    window_s: float = 5.0
    hop_s: float = 2.5
    laughter_threshold: float = 0.08
    applause_threshold: float = 0.05

    def as_params(self) -> dict[str, str | float]:
        return {f"instrument_{k}": v for k, v in self.__dict__.items()}


IDENTITY = AstIdentity()
LABELS: dict[str, tuple[str, ...]] = {
    "laughter": ("Laughter", "Baby laughter", "Giggle", "Snicker", "Belly laugh",
                 "Chuckle, chortle"),
    "applause": ("Applause", "Clapping"),
}
SAMPLE_RATE = 16000
_BATCH = 16


_FILES = ("config.json", "preprocessor_config.json", "model.safetensors")


def _snapshot() -> str:
    """Directory holding the three pinned files; weights verified by sha256."""
    import hashlib
    from pathlib import Path

    from huggingface_hub import hf_hub_download

    remediation = (
        f"HF_HUB_OFFLINE=0 huggingface-cli download {IDENTITY.model_id} "
        f"{' '.join(_FILES)} --revision {IDENTITY.revision}, or install funasr for SenseVoice.")
    try:
        paths = [Path(hf_hub_download(IDENTITY.model_id, f, revision=IDENTITY.revision,
                                      local_files_only=True)) for f in _FILES]
    except Exception as exc:  # any cache miss is the same refusal
        raise ReactionInstrumentError(
            "REACTION_INSTRUMENT_UNAVAILABLE",
            f"{IDENTITY.model_id}@{IDENTITY.revision[:8]} is not in the local cache ({exc}).",
            remediation) from exc
    h = hashlib.sha256()
    with paths[2].open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    if h.hexdigest() != IDENTITY.weights_sha256:
        raise ReactionInstrumentError(
            "REACTION_INSTRUMENT_MISMATCH",
            f"weights sha256 {h.hexdigest()[:12]} is not the pinned "
            f"{IDENTITY.weights_sha256[:12]}.",
            remediation)
    return str(paths[0].parent)


def detect_reactions_ast(audio: np.ndarray, sample_rate: int) -> list[dict[str, object]]:
    """Laughter/applause windows from AST, with the model's probability.

    Args:
        audio: Mono float32 audio at 16 kHz.
        sample_rate: Must be 16000.

    Raises:
        ReactionInstrumentError: Model not cached, or labels missing from it.
    """
    import torch
    from transformers import ASTFeatureExtractor, ASTForAudioClassification

    if sample_rate != SAMPLE_RATE:
        raise ValueError(f"AST expects {SAMPLE_RATE} Hz audio, got {sample_rate}")
    path = _snapshot()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    fe = ASTFeatureExtractor.from_pretrained(path)
    model = ASTForAudioClassification.from_pretrained(path).to(device).eval()
    by_name = {v: int(k) for k, v in model.config.id2label.items()}
    missing = [n for names in LABELS.values() for n in names if n not in by_name]
    if missing:
        raise ReactionInstrumentError(
            "REACTION_INSTRUMENT_MISMATCH", f"labels {missing} absent from {path}.",
            "Restore the pinned revision in the Hugging Face cache.")
    idx = {k: [by_name[n] for n in names] for k, names in LABELS.items()}
    thr = {"laughter": IDENTITY.laughter_threshold, "applause": IDENTITY.applause_threshold}

    win, hop = int(IDENTITY.window_s * sample_rate), int(IDENTITY.hop_s * sample_rate)
    starts = list(range(0, max(len(audio) - win, 0) + 1, hop)) if len(audio) else []
    reactions: list[dict[str, object]] = []
    try:
        for b in range(0, len(starts), _BATCH):
            batch = starts[b : b + _BATCH]
            x = fe([audio[s : s + win] for s in batch], sampling_rate=sample_rate,
                   return_tensors="pt")["input_values"].to(device)
            with torch.no_grad():
                p = torch.sigmoid(model(x).logits).cpu().numpy()
            for row, s in zip(p, batch, strict=True):
                end = min(s + win, len(audio))
                for kind, ids in idx.items():
                    prob = float(row[ids].max())
                    if prob >= thr[kind]:
                        reactions.append({
                            "start_ms": int(s / sample_rate * 1000),
                            "end_ms": int(end / sample_rate * 1000),
                            "type": kind, "confidence": round(prob, 4),
                            "duration_ms": int((end - s) / sample_rate * 1000),
                            "intensity": None,
                        })
    finally:
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    return reactions
