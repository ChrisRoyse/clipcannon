"""Native PyTorch forward pass for nomic-embed-text-v1.5 (the semantic instrument).

Nomic ships its encoder as ``trust_remote_code`` written for transformers 4.x;
under transformers 5 it fails (``get_extended_attention_mask``), while SigLIP
needs 5.x (#70). This module ports the NomicBERT forward pass to plain torch so
the instrument no longer depends on the transformers version at all.

Instrument identity is pinned: model id, hub revision and the sha256 of the
weights file. Any other weights, or a config this port does not implement,
are refused with a typed error instead of producing different vectors under
the same name.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_ID = "nomic-ai/nomic-embed-text-v1.5"
REVISION = "e9b6763023c676ca8431644204f50c2b100d9aab"
WEIGHTS_SHA256 = "9e7d262b1fe5ea350782829496efa831901b77486bbde1cea54a4c822d010d5c"
RUNTIME = "clipcannon.nomic_native/1"
EMBEDDING_DIM = 768
MAX_TOKENS = 8192
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

# Config values this port implements; anything else is a different instrument.
_EXPECTED_CONFIG = {
    "n_embd": 768, "n_head": 12, "n_layer": 12, "n_inner": 3072,
    "activation_function": "swiglu", "prenorm": False, "rotary_emb_fraction": 1.0,
    "rotary_emb_interleaved": False, "rotary_emb_base": 1000,
    "rotary_scaling_factor": None, "qkv_proj_bias": False,
    "mlp_fc1_bias": False, "mlp_fc2_bias": False, "type_vocab_size": 2,
}


class SemanticInstrumentError(RuntimeError):
    """The pinned semantic instrument cannot be loaded as measured."""

    def __init__(self, code: str, message: str, remediation: str) -> None:
        super().__init__(message)
        self.code = code
        self.remediation = remediation


@dataclass(frozen=True)
class InstrumentIdentity:
    model_id: str
    revision: str
    weights_sha256: str
    runtime: str

    def as_dict(self) -> dict[str, str]:
        return {"model_id": self.model_id, "revision": self.revision,
                "weights_sha256": self.weights_sha256, "runtime": self.runtime}

    def as_params(self) -> dict[str, str]:
        """Flat scalar form for provenance ``model_parameters``."""
        return {f"instrument_{k}": v for k, v in self.as_dict().items()}

    @staticmethod
    def from_params(params: dict) -> dict[str, str] | None:
        got = {k.removeprefix("instrument_"): v for k, v in params.items()
               if k.startswith("instrument_")}
        return got or None


IDENTITY = InstrumentIdentity(MODEL_ID, REVISION, WEIGHTS_SHA256, RUNTIME)


def _snapshot() -> Path:
    try:
        from huggingface_hub import snapshot_download
        path = snapshot_download(
            MODEL_ID, revision=REVISION,
            allow_patterns=["config.json", "tokenizer.json", "model.safetensors"],
        )
    except Exception as exc:  # network/cache failure -> typed refusal
        raise SemanticInstrumentError(
            "SEMANTIC_INSTRUMENT_UNAVAILABLE",
            f"Cannot fetch {MODEL_ID}@{REVISION[:12]}: {exc}",
            "Connect to the Hugging Face hub once (or pre-populate the HF cache) "
            "so the pinned revision is available locally.",
        ) from exc
    return Path(path)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


class NomicEncoder:
    """Loads the pinned weights once; ``encode`` returns L2-normalised vectors."""

    def __init__(self, device: str | None = None) -> None:
        import torch
        from safetensors.torch import load_file
        from tokenizers import Tokenizer

        snap = _snapshot()
        cfg = json.loads((snap / "config.json").read_text())
        bad = {k: (v, cfg.get(k)) for k, v in _EXPECTED_CONFIG.items() if cfg.get(k) != v}
        if bad:
            raise SemanticInstrumentError(
                "SEMANTIC_INSTRUMENT_MISMATCH",
                f"Nomic config differs from the ported architecture: {bad}",
                "Re-pin REVISION to the measured snapshot, or port the new "
                "architecture and re-measure parity before admitting it.",
            )
        weights = snap / "model.safetensors"
        digest = _sha256(weights)
        if digest != WEIGHTS_SHA256:
            raise SemanticInstrumentError(
                "SEMANTIC_INSTRUMENT_MISMATCH",
                f"Weights sha256 {digest[:16]} != pinned {WEIGHTS_SHA256[:16]}",
                "The cached weights are not the measured instrument. Delete the "
                "HF cache entry for this model and re-download the pinned revision.",
            )
        self.device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        sd = load_file(str(weights), device=self.device)
        self.w = {k.removeprefix("bert."): v.float() for k, v in sd.items()}
        self.eps = float(cfg.get("layer_norm_epsilon", 1e-12))
        self.n_layer, self.n_head = cfg["n_layer"], cfg["n_head"]
        self.head_dim = cfg["n_embd"] // cfg["n_head"]
        inv = 1.0 / (float(cfg["rotary_emb_base"]) ** (
            torch.arange(0, self.head_dim, 2, dtype=torch.float32, device=self.device)
            / self.head_dim))
        self.inv_freq = inv
        self.tok = Tokenizer.from_file(str(snap / "tokenizer.json"))
        self.tok.enable_truncation(MAX_TOKENS)
        self.tok.no_padding()

    def _ln(self, x, name):  # noqa: ANN001, ANN202
        import torch.nn.functional as nnf
        return nnf.layer_norm(x, (x.shape[-1],), self.w[f"{name}.weight"],
                            self.w[f"{name}.bias"], self.eps)

    def _forward(self, ids, mask):  # noqa: ANN001, ANN202
        import torch
        import torch.nn.functional as nnf
        w = self.w
        b, s = ids.shape
        x = w["embeddings.word_embeddings.weight"][ids]
        x = x + w["embeddings.token_type_embeddings.weight"][0]
        x = self._ln(x, "emb_ln")
        t = torch.arange(s, dtype=torch.float32, device=self.device)
        freqs = torch.outer(t, self.inv_freq)
        cos = torch.cat([freqs.cos(), freqs.cos()], -1)[None, None]
        sin = torch.cat([freqs.sin(), freqs.sin()], -1)[None, None]
        attn_mask = mask[:, None, None, :].bool()

        def rot(v: torch.Tensor) -> torch.Tensor:  # (b, h, s, d), halves
            v1, v2 = v.chunk(2, dim=-1)
            return v * cos + torch.cat((-v2, v1), -1) * sin

        for i in range(self.n_layer):
            p = f"encoder.layers.{i}"
            qkv = nnf.linear(x, w[f"{p}.attn.Wqkv.weight"])
            qkv = qkv.view(b, s, 3, self.n_head, self.head_dim).permute(2, 0, 3, 1, 4)
            q, k, v = rot(qkv[0]), rot(qkv[1]), qkv[2]
            a = nnf.scaled_dot_product_attention(q, k, v, attn_mask=attn_mask)
            a = a.permute(0, 2, 1, 3).reshape(b, s, -1)
            x = self._ln(nnf.linear(a, w[f"{p}.attn.out_proj.weight"]) + x, f"{p}.norm1")
            h = nnf.linear(x, w[f"{p}.mlp.fc11.weight"]) * nnf.silu(
                nnf.linear(x, w[f"{p}.mlp.fc12.weight"]))
            x = self._ln(nnf.linear(h, w[f"{p}.mlp.fc2.weight"]) + x, f"{p}.norm2")
        m = mask[..., None].float()
        pooled = (x * m).sum(1) / m.sum(1).clamp(min=1e-9)
        return nnf.normalize(pooled, dim=-1)

    def encode(self, texts: list[str], batch_size: int = 32):  # noqa: ANN201
        """Embed already-prefixed texts; returns float32 ndarray (N, 768)."""
        import numpy as np
        import torch
        out: list[np.ndarray] = []
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        with torch.inference_mode():
            for start in range(0, len(order), batch_size):
                idx = order[start:start + batch_size]
                encs = self.tok.encode_batch([texts[i] for i in idx])
                s = max(len(e.ids) for e in encs)
                ids = torch.zeros((len(idx), s), dtype=torch.long)
                mask = torch.zeros((len(idx), s), dtype=torch.long)
                for r, e in enumerate(encs):
                    ids[r, :len(e.ids)] = torch.tensor(e.ids)
                    mask[r, :len(e.ids)] = 1
                vec = self._forward(ids.to(self.device), mask.to(self.device))
                out.append(vec.float().cpu().numpy())
        flat = np.concatenate(out) if out else np.zeros((0, EMBEDDING_DIM), np.float32)
        result = np.empty_like(flat)
        result[order] = flat
        return result.astype(np.float32)


_ENCODER: NomicEncoder | None = None


def get_encoder() -> NomicEncoder:
    """Process-wide encoder for query-time use (weights verified once per process)."""
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = NomicEncoder()
    return _ENCODER
