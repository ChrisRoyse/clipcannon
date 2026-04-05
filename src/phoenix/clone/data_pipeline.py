"""Training data pipeline for the clone model.

Provides the MeaningAlignedDataset from pre-extracted embeddings in NPZ
format. The old frame-by-frame extraction pipeline (insightface + SQLite)
has been replaced by the meaning-aware approach that works directly from
the embeddings NPZ produced during ingest.

For the full meaning-aware pipeline, see meaning_trainer.py.
"""
from __future__ import annotations

import logging
import os

import numpy as np

logger = logging.getLogger(__name__)


def load_embeddings_npz(
    npz_path: str = "~/.clipcannon/models/santa/embeddings/all_embeddings.npz",
) -> dict[str, np.ndarray]:
    """Load all pre-computed embeddings from NPZ file.

    The NPZ contains:
      vis_emb: (N_vis, 1152) SigLIP visual embeddings
      vis_ts: (N_vis,) timestamps in ms
      sem_emb: (N_sem, 768) Nomic semantic embeddings
      sem_ts: (N_sem,) timestamps in ms
      emo_data: (N_emo, 3) arousal/valence/energy
      emo_ts: (N_emo,) timestamps in ms
      pro_data: (N_pro, 12) prosody features
      pro_ts: (N_pro,) timestamps in ms
      flame_exp: (N_flame, 100) FLAME expression params
      flame_ts: (N_flame,) timestamps in seconds

    Returns:
        Dict with all arrays.
    """
    path = os.path.expanduser(npz_path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Embeddings not found: {path}")

    data = np.load(path, allow_pickle=True)
    result = {key: data[key] for key in data.keys()}

    logger.info(
        "Loaded embeddings: %s",
        {k: v.shape for k, v in result.items()},
    )
    return result


def get_embedding_dims(npz_path: str | None = None) -> dict[str, int]:
    """Get embedding dimensions from NPZ file or defaults.

    Returns:
        Dict of modality name -> embedding dimension.
    """
    if npz_path:
        data = load_embeddings_npz(npz_path)
        dims = {}
        if "vis_emb" in data:
            dims["visual"] = data["vis_emb"].shape[1]
        if "sem_emb" in data:
            dims["semantic"] = data["sem_emb"].shape[1]
        if "pro_data" in data:
            dims["prosody"] = data["pro_data"].shape[1]
        if "emo_data" in data:
            dims["emotion_scalars"] = data["emo_data"].shape[1]
        return dims

    return {
        "visual": 1152,
        "semantic": 768,
        "prosody": 12,
        "emotion_scalars": 3,
    }
