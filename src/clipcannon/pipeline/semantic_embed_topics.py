"""Sentiment, keyword extraction and topic clustering for semantic_embed."""

from __future__ import annotations

import json
import logging
from collections import Counter

import numpy as np

logger = logging.getLogger(__name__)

# Clustering parameters
DISTANCE_THRESHOLD = 0.7
MIN_CLUSTER_SIZE = 1

# Stop words for keyword extraction
_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "need",
        "dare",
        "ought",
        "used",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "because",
        "but",
        "and",
        "or",
        "if",
        "while",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "him",
        "his",
        "she",
        "her",
        "they",
        "them",
        "their",
        "what",
        "which",
        "who",
        "whom",
        "about",
        "up",
        "like",
        "also",
        "well",
        "really",
        "right",
        "going",
        "know",
        "think",
        "get",
        "got",
        "go",
        "yeah",
        "okay",
        "um",
        "uh",
        "oh",
    }
)


def _compute_sentiment(texts: list[str]) -> list[dict[str, object]]:
    """Compute sentiment for each transcript segment text.

    Uses transformers sentiment-analysis pipeline with DistilBERT.

    Args:
        texts: List of segment texts.

    Returns:
        List of {label: 'POSITIVE'/'NEGATIVE', score: float} dicts.
    """
    # No substitute on failure: a NEUTRAL/0.5 placeholder would be stored as if
    # it were a measurement (#68). Errors propagate and fail the stage.
    from transformers import pipeline as hf_pipeline

    classifier = hf_pipeline(
        "sentiment-analysis",
        model="distilbert/distilbert-base-uncased-finetuned-sst-2-english",
        device="cpu",  # CPU is fast enough for text classification
        batch_size=32,
    )
    results = classifier(texts, truncation=True, max_length=512)
    return [{"label": r["label"], "score": round(r["score"], 3)} for r in results]


def _extract_keywords(
    texts: list[str],
    top_k: int = 5,
) -> list[str]:
    """Extract top keywords from a list of texts using word frequency.

    Args:
        texts: List of segment texts.
        top_k: Number of top keywords to return.

    Returns:
        List of top keywords.
    """
    word_counts: Counter[str] = Counter()
    for text in texts:
        words = text.lower().split()
        for word in words:
            cleaned = word.strip(".,!?;:\"'()-")
            if len(cleaned) > 2 and cleaned not in _STOP_WORDS:
                word_counts[cleaned] += 1

    return [word for word, _ in word_counts.most_common(top_k)]


def _cluster_segments(
    embeddings: np.ndarray,
    segments: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Cluster segments into topics using agglomerative clustering.

    Args:
        embeddings: L2-normalized embeddings array (N, 768).
        segments: List of segment dicts.

    Returns:
        List of topic dicts with label, start_ms, end_ms, etc.
    """
    from sklearn.cluster import AgglomerativeClustering

    if len(segments) <= 1:
        # Single segment = single topic
        seg = segments[0]
        text = str(seg.get("text", ""))
        keywords = _extract_keywords([text], top_k=3)
        return [
            {
                "start_ms": int(seg.get("start_ms", 0)),
                "end_ms": int(seg.get("end_ms", 0)),
                "label": ", ".join(keywords) if keywords else "topic_0",
                "keywords": json.dumps(keywords),
                "coherence_score": 1.0,
                "semantic_density": 1.0,
            }
        ]

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=DISTANCE_THRESHOLD,
        metric="cosine",
        linkage="average",
    )
    labels = clustering.fit_predict(embeddings)

    # Group segments by cluster
    cluster_map: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        cluster_map.setdefault(int(label), []).append(idx)

    topics: list[dict[str, object]] = []
    for cluster_id, indices in sorted(cluster_map.items()):
        cluster_segments = [segments[i] for i in indices]
        cluster_embeddings = embeddings[indices]
        cluster_texts = [str(s.get("text", "")) for s in cluster_segments]

        # Time range
        start_ms = min(int(s.get("start_ms", 0)) for s in cluster_segments)
        end_ms = max(int(s.get("end_ms", 0)) for s in cluster_segments)

        # Keywords
        keywords = _extract_keywords(cluster_texts, top_k=5)
        label = ", ".join(keywords[:3]) if keywords else f"topic_{cluster_id}"

        # Coherence: average pairwise cosine similarity within cluster
        if len(cluster_embeddings) > 1:
            sim_matrix = cluster_embeddings @ cluster_embeddings.T
            n = len(cluster_embeddings)
            mask = np.ones((n, n), dtype=bool)
            np.fill_diagonal(mask, False)
            coherence = float(np.mean(sim_matrix[mask]))
        else:
            coherence = 1.0

        # Semantic density: mean distance from centroid
        centroid = np.mean(cluster_embeddings, axis=0)
        distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)
        density = float(1.0 / (1.0 + np.mean(distances)))

        topics.append(
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "label": label,
                "keywords": json.dumps(keywords),
                "coherence_score": round(coherence, 4),
                "semantic_density": round(density, 4),
            }
        )

    return topics
