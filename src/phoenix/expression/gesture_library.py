"""Semantic-indexed gesture library for contextual gesture selection.

Provides a library of gesture clips indexed by 768-dim Nomic semantic
embeddings. Selection is performed via cosine similarity search over
all gestures, optionally filtered by category.

No CPU fallbacks. Errors raise BehaviorError with full context.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from phoenix.errors import BehaviorError

# Default gesture definitions for build_default_library().
# Each tuple: (gesture_id, category, description, duration_ms,
#               body_parts, intensity)
_DEFAULT_GESTURES: list[
    tuple[str, str, str, int, list[str], float]
] = [
    ("nod_agreement", "agreement", "Slow vertical head nod",
     800, ["head"], 0.6),
    ("double_nod", "agreement", "Two quick affirmative nods",
     600, ["head"], 0.7),
    ("thumbs_up", "agreement", "Thumbs-up hand gesture",
     500, ["hands"], 0.8),
    ("head_shake", "disagreement", "Horizontal head shake",
     900, ["head"], 0.6),
    ("wave_off", "disagreement", "Dismissive hand wave",
     700, ["hands"], 0.5),
    ("brow_furrow", "disagreement", "Furrowed brows with slight head tilt",
     400, ["head"], 0.4),
    ("head_tilt", "uncertainty", "Slight head tilt to one side",
     600, ["head"], 0.4),
    ("shrug", "uncertainty", "Shoulder shrug with raised palms",
     800, ["shoulders", "hands"], 0.5),
    ("lip_purse", "uncertainty", "Pursed lips with micro head shake",
     400, ["head"], 0.3),
    ("hand_chop", "emphasis", "Downward hand chop for emphasis",
     500, ["hands"], 0.8),
    ("finger_point", "emphasis", "Forward finger point",
     400, ["hands"], 0.9),
    ("palm_press", "emphasis", "Flat palm press downward",
     600, ["hands"], 0.7),
    ("wave_hello", "greeting", "Open-palm wave greeting",
     700, ["hands"], 0.6),
    ("slight_bow", "greeting", "Slight forward bow of head",
     500, ["head"], 0.4),
    ("chin_stroke", "thinking", "Hand on chin thinking gesture",
     1000, ["hands", "head"], 0.5),
    ("look_up", "thinking", "Eyes and head tilt upward in thought",
     800, ["head"], 0.4),
    ("eyes_wide", "surprise", "Wide eyes with slight head back",
     400, ["head"], 0.7),
    ("head_back_laugh", "humor", "Head tilted back in laughter",
     900, ["head", "shoulders"], 0.8),
    ("open_palms", "explanation", "Open palms outward while explaining",
     700, ["hands"], 0.5),
    ("point_aside", "reference", "Point to the side referencing something",
     500, ["hands"], 0.6),
]

# All valid categories.
VALID_CATEGORIES: frozenset[str] = frozenset(
    g[1] for g in _DEFAULT_GESTURES
)


@dataclass(frozen=True)
class GestureClip:
    """Metadata for a gesture animation clip.

    Attributes:
        gesture_id: Unique identifier, e.g. "nod_agreement".
        category: Gesture category (agreement, emphasis, etc.).
        description: Human-readable description.
        embedding: 768-dim Nomic semantic embedding.
        duration_ms: Clip duration in milliseconds.
        body_parts: List of body parts involved.
        intensity: Gesture intensity [0, 1].
    """

    gesture_id: str
    category: str
    description: str
    embedding: np.ndarray
    duration_ms: int
    body_parts: list[str]
    intensity: float

    def __eq__(self, other: object) -> bool:
        """Equality based on gesture_id."""
        if not isinstance(other, GestureClip):
            return NotImplemented
        return self.gesture_id == other.gesture_id

    def __hash__(self) -> int:
        """Hash based on gesture_id."""
        return hash(self.gesture_id)


def _cosine_search(
    query: np.ndarray,
    candidates: Sequence[np.ndarray],
) -> list[float]:
    """Vectorized cosine similarity search.

    Args:
        query: 1-D query vector.
        candidates: Sequence of 1-D candidate vectors.

    Returns:
        List of cosine similarities, one per candidate.

    Raises:
        BehaviorError: If query has zero norm.
    """
    query_norm = float(np.linalg.norm(query))
    if query_norm == 0.0:
        raise BehaviorError(
            "Cannot search with zero-norm query embedding",
            {"query_shape": query.shape},
        )

    # Stack candidates into a matrix for vectorized computation.
    matrix = np.stack(candidates, axis=0)  # (N, D)
    norms = np.linalg.norm(matrix, axis=1)  # (N,)

    # Avoid division by zero for any zero-norm candidates.
    safe_norms = np.where(norms > 0.0, norms, 1.0)

    dots = matrix @ query  # (N,)
    similarities = dots / (safe_norms * query_norm)

    return similarities.tolist()


class GestureLibrary:
    """Semantic-indexed gesture library.

    Stores gesture clips with their semantic embeddings and supports
    nearest-neighbor selection via cosine similarity. Optionally
    persists to SQLite for cross-session use.

    Args:
        db_path: Optional path to SQLite database for persistence.
            If None, operates in memory-only mode.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._gestures: list[GestureClip] = []
        self._db_path = db_path

        if db_path is not None:
            self._load_from_db(db_path)

    @property
    def size(self) -> int:
        """Return the number of gestures in the library."""
        return len(self._gestures)

    def add_gesture(
        self,
        gesture_id: str,
        category: str,
        description: str,
        embedding: np.ndarray,
        duration_ms: int,
        body_parts: list[str],
        intensity: float,
    ) -> GestureClip:
        """Add a gesture to the library.

        Args:
            gesture_id: Unique identifier for the gesture.
            category: Gesture category.
            description: Human-readable description.
            embedding: 768-dim Nomic semantic embedding.
            duration_ms: Clip duration in milliseconds.
            body_parts: List of body parts involved.
            intensity: Gesture intensity [0, 1].

        Returns:
            The newly created GestureClip.

        Raises:
            BehaviorError: If embedding is not 1-D, or if gesture_id
                already exists.
        """
        if embedding.ndim != 1 or embedding.size == 0:
            raise BehaviorError(
                "Gesture embedding must be a non-empty 1-D array",
                {"gesture_id": gesture_id, "ndim": embedding.ndim},
            )
        for existing in self._gestures:
            if existing.gesture_id == gesture_id:
                raise BehaviorError(
                    f"Gesture already exists: {gesture_id}",
                    {"gesture_id": gesture_id},
                )

        clip = GestureClip(
            gesture_id=gesture_id,
            category=category,
            description=description,
            embedding=embedding.copy(),
            duration_ms=duration_ms,
            body_parts=list(body_parts),
            intensity=intensity,
        )
        self._gestures.append(clip)

        if self._db_path is not None:
            self._save_gesture_to_db(clip)

        return clip

    def select(
        self,
        text_embedding: np.ndarray,
        category: str | None = None,
    ) -> GestureClip:
        """Select the best-matching gesture for a text embedding.

        Performs cosine similarity search over all gestures (or only
        those matching the given category).

        Args:
            text_embedding: 768-dim semantic embedding of the text.
            category: Optional category filter.

        Returns:
            The GestureClip with the highest cosine similarity.

        Raises:
            BehaviorError: If the library is empty, or if no gestures
                match the given category, or if text_embedding is
                invalid.
        """
        if text_embedding.ndim != 1 or text_embedding.size == 0:
            raise BehaviorError(
                "text_embedding must be a non-empty 1-D array",
                {"ndim": text_embedding.ndim, "size": text_embedding.size},
            )

        candidates = self._gestures
        if category is not None:
            candidates = [
                g for g in self._gestures if g.category == category
            ]

        if not candidates:
            if category is not None:
                raise BehaviorError(
                    f"No gestures found for category: {category}",
                    {"category": category, "library_size": self.size},
                )
            raise BehaviorError(
                "Gesture library is empty",
                {"library_size": 0},
            )

        embeddings = [g.embedding for g in candidates]
        similarities = _cosine_search(text_embedding, embeddings)

        best_idx = int(np.argmax(similarities))
        return candidates[best_idx]

    def get_by_category(self, category: str) -> list[GestureClip]:
        """Return all gestures in a given category.

        Args:
            category: The category to filter by.

        Returns:
            List of matching GestureClip objects.
        """
        return [g for g in self._gestures if g.category == category]

    def build_default_library(self) -> None:
        """Populate with 20 default gesture definitions.

        Creates placeholder embeddings using deterministic seeds so that
        each gesture has a unique 768-dim embedding. Existing gestures
        are preserved (duplicates are skipped).
        """
        existing_ids = {g.gesture_id for g in self._gestures}

        for idx, (gid, cat, desc, dur, parts, intensity) in enumerate(
            _DEFAULT_GESTURES
        ):
            if gid in existing_ids:
                continue

            # Deterministic placeholder embedding from seed.
            rng = np.random.default_rng(seed=42 + idx)
            embedding = rng.standard_normal(768).astype(np.float32)
            # Normalize to unit length.
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            self.add_gesture(
                gesture_id=gid,
                category=cat,
                description=desc,
                embedding=embedding,
                duration_ms=dur,
                body_parts=list(parts),
                intensity=intensity,
            )

    def _load_from_db(self, db_path: str) -> None:
        """Load gestures from SQLite database.

        Args:
            db_path: Path to SQLite database.

        Raises:
            BehaviorError: If the database cannot be read.
        """
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()

                # Check if table exists.
                cursor.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='gestures'"
                )
                if cursor.fetchone() is None:
                    # Table doesn't exist yet, create it.
                    self._create_table(conn)
                    return

                cursor.execute(
                    "SELECT gesture_id, category, description, embedding, "
                    "duration_ms, body_parts, intensity FROM gestures"
                )
                for row in cursor.fetchall():
                    gid, cat, desc, emb_bytes, dur, parts_str, intensity = row
                    embedding = np.frombuffer(emb_bytes, dtype=np.float32)
                    body_parts = parts_str.split(",") if parts_str else []

                    clip = GestureClip(
                        gesture_id=gid,
                        category=cat,
                        description=desc,
                        embedding=embedding.copy(),
                        duration_ms=dur,
                        body_parts=body_parts,
                        intensity=intensity,
                    )
                    self._gestures.append(clip)
        except sqlite3.Error as exc:
            raise BehaviorError(
                f"Failed to load gesture database: {exc}",
                {"db_path": db_path},
            ) from exc

    def _save_gesture_to_db(self, clip: GestureClip) -> None:
        """Persist a single gesture to SQLite.

        Args:
            clip: The gesture clip to save.

        Raises:
            BehaviorError: If the database write fails.
        """
        if self._db_path is None:
            return

        try:
            with sqlite3.connect(self._db_path) as conn:
                self._create_table(conn)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO gestures "
                    "(gesture_id, category, description, embedding, "
                    "duration_ms, body_parts, intensity) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        clip.gesture_id,
                        clip.category,
                        clip.description,
                        clip.embedding.tobytes(),
                        clip.duration_ms,
                        ",".join(clip.body_parts),
                        clip.intensity,
                    ),
                )
                conn.commit()
        except sqlite3.Error as exc:
            raise BehaviorError(
                f"Failed to save gesture to database: {exc}",
                {"gesture_id": clip.gesture_id, "db_path": self._db_path},
            ) from exc

    @staticmethod
    def _create_table(conn: sqlite3.Connection) -> None:
        """Create the gestures table if it does not exist.

        Args:
            conn: Active SQLite connection.
        """
        conn.execute(
            "CREATE TABLE IF NOT EXISTS gestures ("
            "  gesture_id TEXT PRIMARY KEY,"
            "  category TEXT NOT NULL,"
            "  description TEXT NOT NULL,"
            "  embedding BLOB NOT NULL,"
            "  duration_ms INTEGER NOT NULL,"
            "  body_parts TEXT NOT NULL,"
            "  intensity REAL NOT NULL"
            ")"
        )
        conn.commit()
