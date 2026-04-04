"""Gesture selection driven by response text and emotion state.

Selects gestures from the GestureLibrary based on semantic similarity
to the response text, with optional emotion-based category biasing.

No CPU fallbacks. Errors raise BehaviorError with full context.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np

from phoenix.errors import BehaviorError
from phoenix.expression.gesture_library import GestureClip, GestureLibrary

if TYPE_CHECKING:
    from phoenix.expression.emotion_fusion import EmotionState


def _hash_embedding(text: str, dim: int = 768) -> np.ndarray:
    """Create a deterministic pseudo-embedding from text via hashing.

    Uses Python's built-in hash seeded into a numpy RNG to produce a
    reproducible unit-norm vector. Different texts produce different
    embeddings with high probability.

    Args:
        text: Input text string.
        dim: Embedding dimensionality.

    Returns:
        Unit-norm float32 array of shape (dim,).
    """
    # Use a stable hash: sum of character ordinals * position.
    seed = 0
    for i, ch in enumerate(text):
        seed = (seed * 31 + ord(ch)) & 0xFFFF_FFFF
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(dim).astype(np.float32)
    norm = float(np.linalg.norm(vec))
    if norm > 0.0:
        vec = vec / norm
    return vec


def _select_category(emotion: EmotionState) -> str | None:
    """Choose a gesture category based on emotion state.

    Mapping rules:
    - Sarcastic -> "uncertainty" (knowing disbelief).
    - High arousal + positive valence -> "emphasis" or "agreement".
    - Low arousal -> "thinking" or "uncertainty".
    - Otherwise -> None (no category bias).

    Args:
        emotion: Current fused emotion state.

    Returns:
        Category string or None if no strong bias.
    """
    if emotion.is_sarcastic:
        return "uncertainty"

    if emotion.arousal > 0.6 and emotion.valence > 0.55:
        # High activation, positive: emphatic agreement.
        return "emphasis" if emotion.energy > 0.5 else "agreement"

    if emotion.arousal < 0.3:
        return "thinking" if emotion.valence > 0.45 else "uncertainty"

    return None


class GestureSelector:
    """Selects gestures from a library based on response text content.

    Uses a semantic embedding function to convert response text into a
    768-dim vector, then searches the GestureLibrary for the best match.
    Optionally biases category selection using the current EmotionState.

    Args:
        library: Populated GestureLibrary to search.
        embed_fn: Callable that maps text to a 768-dim numpy array.
            If None, uses a simple hash-based embedding (for testing).

    Raises:
        BehaviorError: If the library is empty at construction time.
    """

    def __init__(
        self,
        library: GestureLibrary,
        embed_fn: Callable[[str], np.ndarray] | None = None,
    ) -> None:
        if library.size == 0:
            raise BehaviorError(
                "GestureSelector requires a non-empty library",
                {"library_size": 0},
            )
        self._library = library
        self._embed_fn = embed_fn or _hash_embedding

    def select_for_response(
        self,
        response_text: str,
        emotion_state: EmotionState | None = None,
    ) -> GestureClip:
        """Select a gesture matching the response text content.

        If emotion_state is provided, biases category selection:
        - High arousal + positive valence -> "emphasis" or "agreement".
        - Low arousal -> "thinking" or "uncertainty".
        - Sarcastic -> "uncertainty".

        If the biased category has no matching gestures, falls back to
        searching across all categories.

        Args:
            response_text: The avatar's response text.
            emotion_state: Optional current emotion state for biasing.

        Returns:
            The best-matching GestureClip.

        Raises:
            BehaviorError: If response_text is empty, or if the
                embedding function returns an invalid array.
        """
        if not response_text.strip():
            raise BehaviorError(
                "response_text must not be empty",
                {"response_text": response_text},
            )

        embedding = self._embed_fn(response_text)
        if embedding.ndim != 1 or embedding.size == 0:
            raise BehaviorError(
                "embed_fn returned invalid array",
                {"ndim": embedding.ndim, "size": embedding.size},
            )

        category: str | None = None
        if emotion_state is not None:
            category = _select_category(emotion_state)

        # Try category-biased selection first.
        if category is not None:
            try:
                return self._library.select(embedding, category=category)
            except BehaviorError:
                # Category has no gestures; fall through to unfiltered.
                pass

        return self._library.select(embedding)
