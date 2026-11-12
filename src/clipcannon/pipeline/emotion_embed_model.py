"""Dimensional speech-emotion model loading and inference."""

from __future__ import annotations

import numpy as np

from clipcannon.exceptions import PipelineError
from clipcannon.pipeline.emotion_embed_audio import (
    EMBEDDING_DIM,
    MODEL_ID,
    OPERATION,
    STAGE,
    TARGET_SR,
)


def _build_emotion_model_class() -> tuple:
    """Build the dimensional-SER model class (audEERING architecture).

    Defined lazily so the module imports without torch present. The class
    matches the published audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim
    architecture: a Wav2Vec2 backbone whose mean-pooled last-layer hidden
    states feed a regression head producing [arousal, dominance, valence].

    Returns:
        Tuple of (EmotionModel class, torch module, nn module).
    """
    import torch
    from torch import nn
    from transformers import Wav2Vec2Model, Wav2Vec2PreTrainedModel

    class RegressionHead(nn.Module):
        """Regression head for arousal/dominance/valence."""

        def __init__(self, config: object) -> None:
            super().__init__()
            self.dense = nn.Linear(config.hidden_size, config.hidden_size)
            self.dropout = nn.Dropout(config.final_dropout)
            self.out_proj = nn.Linear(config.hidden_size, config.num_labels)

        def forward(self, features: object) -> object:
            x = self.dropout(features)
            x = self.dense(x)
            x = torch.tanh(x)
            x = self.dropout(x)
            return self.out_proj(x)

    class EmotionModel(Wav2Vec2PreTrainedModel):
        """wav2vec2 backbone + regression head; returns (pooled_states, logits)."""

        def __init__(self, config: object) -> None:
            super().__init__(config)
            self.config = config
            self.wav2vec2 = Wav2Vec2Model(config)
            self.classifier = RegressionHead(config)
            # transformers 5.x: post_init() (not the legacy init_weights()) wires
            # up tied-weight bookkeeping (all_tied_weights_keys) + weight init.
            self.post_init()

        def forward(self, input_values: object) -> tuple:
            outputs = self.wav2vec2(input_values)
            hidden_states = outputs[0]
            pooled = torch.mean(hidden_states, dim=1)
            logits = self.classifier(pooled)
            return pooled, logits

    return EmotionModel, torch, nn


def _compute_emotion_model(
    segments: list[tuple[int, int, np.ndarray]],
    device: str,
) -> list[dict[str, object]]:
    """Compute GROUNDED emotion features from a dimensional-SER model.

    arousal/valence: regression-head predictions in [0, 1] (grounded in
        emotional state, per Wagner et al. 2023).
    energy: normalized RMS of the raw audio waveform (grounded acoustic loudness).
    embedding: the model's mean-pooled last-layer hidden states (1024-d).

    There is no fallback. If the model cannot be loaded/run, the caller raises.

    Args:
        segments: List of (start_ms, end_ms, audio_chunk) tuples.
        device: Torch device string.

    Returns:
        List of dicts with start_ms, end_ms, energy, arousal, valence, embedding.
    """
    import gc

    from transformers import Wav2Vec2Processor

    EmotionModel, torch, _ = _build_emotion_model_class()  # noqa: N806

    # Clear VRAM left by earlier pipeline stages before loading this model.
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()

    # local_files_only=True: models MUST be pre-cached. Never download at
    # runtime (non-deterministic, breaks offline/air-gapped, slow). A missing
    # model raises here with the model id so the operator knows what to fetch.
    processor = Wav2Vec2Processor.from_pretrained(MODEL_ID, local_files_only=True)
    # FP32: the wav2vec2 Conv1d feature extractor does not support FP16
    # (input/weight dtype mismatch). The 12-layer model is ~1GB — trivial on
    # the RTX 5090's 32GB.
    model = EmotionModel.from_pretrained(MODEL_ID, local_files_only=True)
    model = model.to(device)
    model.eval()

    results: list[dict[str, object]] = []
    try:
        for start_ms, end_ms, chunk in segments:
            inputs = processor(
                chunk,
                sampling_rate=TARGET_SR,
                return_tensors="pt",
                padding=True,
            )
            input_values = inputs["input_values"].to(device)

            with torch.no_grad():
                pooled, logits = model(input_values)

            # Model output order is arousal, dominance, valence (audEERING).
            adv = logits.squeeze(0).cpu().numpy().astype(np.float64)
            arousal = float(np.clip(adv[0], 0.0, 1.0))
            valence = float(np.clip(adv[2], 0.0, 1.0))

            # Energy from the raw waveform (grounded acoustic loudness), NOT
            # from hidden-state statistics.
            rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
            energy = float(np.clip(rms / (rms + 0.05), 0.0, 1.0))

            embedding = pooled.squeeze(0).cpu().numpy().astype(np.float32)
            if embedding.shape[0] != EMBEDDING_DIM:
                raise PipelineError(
                    f"Emotion embedding dim {embedding.shape[0]} != expected "
                    f"{EMBEDDING_DIM} for model {MODEL_ID}",
                    stage_name=STAGE,
                    operation=OPERATION,
                )

            results.append(
                {
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "energy": round(energy, 4),
                    "arousal": round(arousal, 4),
                    "valence": round(valence, 4),
                    "embedding": embedding,
                }
            )
    finally:
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    _assert_not_degenerate(results)
    return results


def _assert_not_degenerate(results: list[dict[str, object]]) -> None:
    """Guard the instrument differentiation contract at the per-clip level.

    Catches the dead-instrument signatures that previously shipped: an all-zero
    embedding, or a valence that is bit-identical across every window (a real
    neural SER model effectively never does this). Either means the instrument
    is contributing ~0 bits and must fail loudly rather than poison the
    constellation centroids.

    Args:
        results: Computed emotion result dicts.

    Raises:
        PipelineError: If the emotion signal is degenerate.
    """
    if not results:
        return

    embeddings = np.stack([r["embedding"] for r in results])  # type: ignore[index]
    if not np.any(embeddings):
        raise PipelineError(
            "Emotion embeddings are all zero — dead instrument (0 bits). "
            "The SER model produced no signal; refusing to persist a "
            "degenerate emotion axis.",
            stage_name=STAGE,
            operation=OPERATION,
        )

    valences = [float(r["valence"]) for r in results]  # type: ignore[arg-type]
    if len(valences) >= 3 and len(set(valences)) == 1:
        raise PipelineError(
            f"Valence is constant ({valences[0]}) across all "
            f"{len(valences)} windows — degenerate emotion instrument "
            "(contributes 0 bits about emotional state).",
            stage_name=STAGE,
            operation=OPERATION,
        )
