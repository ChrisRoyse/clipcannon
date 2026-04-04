"""Speaker tracking via WavLM speaker embeddings.

Maintains a registry of known speakers identified by their 512-dim
WavLM speaker embeddings. Uses cosine similarity for re-identification
and supports name assignment for known participants.

No CPU fallbacks. Errors raise BehaviorError with full context.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from phoenix.errors import BehaviorError


@dataclass(frozen=True)
class SpeakerInfo:
    """Tracked speaker metadata.

    Attributes:
        speaker_id: Unique identifier, e.g. "speaker_0".
        embedding: Latest speaker embedding (512-dim WavLM).
        name: Human-assigned name, empty string if unknown.
        is_speaking: Whether this speaker is currently active.
        last_spoke_ms: Timestamp of last activity in milliseconds.
        turn_count: Number of speaking turns observed.
    """

    speaker_id: str
    embedding: np.ndarray
    name: str
    is_speaking: bool
    last_spoke_ms: int
    turn_count: int

    def __eq__(self, other: object) -> bool:
        """Equality based on speaker_id only."""
        if not isinstance(other, SpeakerInfo):
            return NotImplemented
        return self.speaker_id == other.speaker_id

    def __hash__(self) -> int:
        """Hash based on speaker_id only."""
        return hash(self.speaker_id)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two 1-D vectors.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Cosine similarity in [-1, 1].

    Raises:
        BehaviorError: If either vector has zero norm.
    """
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        raise BehaviorError(
            "Cannot compute cosine similarity with zero-norm vector",
            {"norm_a": norm_a, "norm_b": norm_b},
        )
    return float(np.dot(a, b) / (norm_a * norm_b))


class SpeakerTracker:
    """Speaker identification and tracking engine.

    Maintains a registry of speakers identified by WavLM embeddings.
    When a new embedding arrives, it is compared to all known speakers
    via cosine similarity. If the best match exceeds the threshold, the
    speaker is re-identified; otherwise a new speaker is registered.

    Args:
        similarity_threshold: Minimum cosine similarity to match an
            existing speaker. Range (0, 1].

    Raises:
        BehaviorError: If similarity_threshold is not in (0, 1].
    """

    def __init__(self, similarity_threshold: float = 0.7) -> None:
        if not (0.0 < similarity_threshold <= 1.0):
            raise BehaviorError(
                "similarity_threshold must be in (0, 1]",
                {"similarity_threshold": similarity_threshold},
            )
        self._threshold = similarity_threshold
        self._speakers: list[SpeakerInfo] = []
        self._active_id: str | None = None
        self._next_id = 0

    def track(
        self,
        speaker_embedding: np.ndarray,
        timestamp_ms: int,
    ) -> SpeakerInfo:
        """Process a speaker embedding and return the matched speaker.

        If the embedding matches a known speaker (cosine similarity above
        threshold), that speaker is updated. Otherwise a new speaker is
        registered.

        Args:
            speaker_embedding: 512-dim WavLM speaker embedding.
            timestamp_ms: Current timestamp in milliseconds.

        Returns:
            The matched or newly created SpeakerInfo.

        Raises:
            BehaviorError: If speaker_embedding is not a non-empty 1-D
                array.
        """
        if speaker_embedding.ndim != 1 or speaker_embedding.size == 0:
            raise BehaviorError(
                "speaker_embedding must be a non-empty 1-D array",
                {
                    "ndim": speaker_embedding.ndim,
                    "size": speaker_embedding.size,
                },
            )
        if speaker_embedding.shape[0] != 512:
            raise BehaviorError(
                f"speaker_embedding must be 512-dim, got {speaker_embedding.shape[0]}",
                {
                    "expected": 512,
                    "got": speaker_embedding.shape[0],
                },
            )

        best_idx = -1
        best_sim = -1.0

        for idx, speaker in enumerate(self._speakers):
            try:
                sim = _cosine_similarity(speaker.embedding, speaker_embedding)
            except BehaviorError:
                continue
            if sim > best_sim:
                best_sim = sim
                best_idx = idx

        if best_idx >= 0 and best_sim >= self._threshold:
            return self._update_speaker(best_idx, speaker_embedding,
                                        timestamp_ms)
        return self._register_speaker(speaker_embedding, timestamp_ms)

    def get_active_speaker(self) -> SpeakerInfo | None:
        """Return the currently active speaker, or None.

        Returns:
            The speaker who spoke most recently (is_speaking=True),
            or None if no speakers are tracked.
        """
        for speaker in self._speakers:
            if speaker.speaker_id == self._active_id and speaker.is_speaking:
                return speaker
        return None

    def get_all_speakers(self) -> list[SpeakerInfo]:
        """Return all tracked speakers.

        Returns:
            List of all SpeakerInfo objects in registration order.
        """
        return list(self._speakers)

    def assign_name(self, speaker_id: str, name: str) -> None:
        """Assign a human-readable name to a tracked speaker.

        Args:
            speaker_id: The speaker's unique identifier.
            name: The name to assign.

        Raises:
            BehaviorError: If speaker_id is not found.
        """
        for idx, speaker in enumerate(self._speakers):
            if speaker.speaker_id == speaker_id:
                self._speakers[idx] = replace(speaker, name=name)
                return
        raise BehaviorError(
            f"Speaker not found: {speaker_id}",
            {"speaker_id": speaker_id, "known": [s.speaker_id for s in self._speakers]},
        )

    @property
    def speaker_count(self) -> int:
        """Return the number of tracked speakers."""
        return len(self._speakers)

    def _register_speaker(
        self,
        embedding: np.ndarray,
        timestamp_ms: int,
    ) -> SpeakerInfo:
        """Register a new speaker.

        Args:
            embedding: Speaker embedding vector.
            timestamp_ms: Registration timestamp.

        Returns:
            Newly created SpeakerInfo.
        """
        # Deactivate all other speakers.
        self._deactivate_all()

        speaker_id = f"speaker_{self._next_id}"
        self._next_id += 1

        info = SpeakerInfo(
            speaker_id=speaker_id,
            embedding=embedding.copy(),
            name="",
            is_speaking=True,
            last_spoke_ms=timestamp_ms,
            turn_count=1,
        )
        self._speakers.append(info)
        self._active_id = speaker_id
        return info

    def _update_speaker(
        self,
        idx: int,
        embedding: np.ndarray,
        timestamp_ms: int,
    ) -> SpeakerInfo:
        """Update an existing speaker with a new observation.

        Args:
            idx: Index into self._speakers.
            embedding: New speaker embedding.
            timestamp_ms: Observation timestamp.

        Returns:
            Updated SpeakerInfo.
        """
        self._deactivate_all()

        old = self._speakers[idx]
        updated = SpeakerInfo(
            speaker_id=old.speaker_id,
            embedding=embedding.copy(),
            name=old.name,
            is_speaking=True,
            last_spoke_ms=timestamp_ms,
            turn_count=old.turn_count + 1,
        )
        self._speakers[idx] = updated
        self._active_id = old.speaker_id
        return updated

    def _deactivate_all(self) -> None:
        """Set is_speaking=False for all tracked speakers."""
        self._speakers = [
            replace(s, is_speaking=False) if s.is_speaking else s
            for s in self._speakers
        ]
