"""Prosody matching for TTS reference style selection.

Maintains a rolling window of recent ProsodyFeatures observations and
computes room-level averages to determine the target TTS style that
best matches the conversational context.

No CPU fallbacks. Errors raise BehaviorError with full context.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from phoenix.errors import BehaviorError
from phoenix.expression.emotion_fusion import ProsodyFeatures


@dataclass(frozen=True)
class ProsodyMatch:
    """Result of prosody matching analysis.

    Attributes:
        target_style: Target TTS style label. One of "energetic",
            "calm", "emphatic", "varied", "question", "fast", "slow",
            "rising".
        room_energy: Average energy of recent speakers [0, 1].
        room_f0_mean: Average fundamental frequency in Hz.
        room_speaking_rate: Average speaking rate in WPM.
        confidence: Matching confidence [0, 1].
    """

    target_style: str
    room_energy: float
    room_f0_mean: float
    room_speaking_rate: float
    confidence: float


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a scalar to [lo, hi]."""
    return max(lo, min(hi, value))


def _detect_response_intent(response_text: str) -> str | None:
    """Detect intent from response text punctuation.

    Args:
        response_text: The avatar's response text.

    Returns:
        Intent string or None. Priorities:
        - "?" at end -> "question"
        - "!" at end -> "emphatic"
        - Otherwise -> None
    """
    stripped = response_text.strip()
    if not stripped:
        return None
    if stripped.endswith("?"):
        return "question"
    if stripped.endswith("!"):
        return "emphatic"
    return None


class ProsodyMatcher:
    """Matches TTS reference style to room prosody context.

    Maintains a rolling window of ProsodyFeatures observations and
    computes room-level statistics to determine the appropriate TTS
    style for the avatar's response.

    Args:
        history_window: Maximum number of prosody observations to keep.
            Must be >= 1.

    Raises:
        BehaviorError: If history_window < 1.
    """

    def __init__(self, history_window: int = 10) -> None:
        if history_window < 1:
            raise BehaviorError(
                "history_window must be >= 1",
                {"history_window": history_window},
            )
        self._window = history_window
        self._history: deque[ProsodyFeatures] = deque(maxlen=history_window)

    def update(self, prosody: ProsodyFeatures) -> None:
        """Add a new prosody observation to the rolling window.

        Args:
            prosody: Prosody features from the most recent speaker.
        """
        self._history.append(prosody)

    def match(self, response_text: str) -> ProsodyMatch:
        """Determine target TTS style based on room prosody and response.

        Logic:
        1. Compute room averages from prosody history.
        2. Detect response intent from punctuation.
        3. Match room energy to style: high -> energetic, low -> calm.
        4. Override: question mark -> "question", exclamation -> "emphatic".
        5. If history is empty, return "varied" with zero confidence.

        Args:
            response_text: The avatar's response text.

        Returns:
            ProsodyMatch with the recommended TTS style.
        """
        if not self._history:
            return ProsodyMatch(
                target_style="varied",
                room_energy=0.0,
                room_f0_mean=0.0,
                room_speaking_rate=0.0,
                confidence=0.0,
            )

        # Compute room averages.
        n = len(self._history)
        room_energy = sum(p.energy_mean for p in self._history) / n
        room_f0_mean = sum(p.f0_mean for p in self._history) / n
        room_rate = sum(p.speaking_rate_wpm for p in self._history) / n

        # Confidence increases with more observations.
        confidence = _clamp(n / self._window)

        # Detect response intent override.
        intent = _detect_response_intent(response_text)
        if intent == "question":
            return ProsodyMatch(
                target_style="question",
                room_energy=room_energy,
                room_f0_mean=room_f0_mean,
                room_speaking_rate=room_rate,
                confidence=confidence,
            )
        if intent == "emphatic":
            return ProsodyMatch(
                target_style="emphatic",
                room_energy=room_energy,
                room_f0_mean=room_f0_mean,
                room_speaking_rate=room_rate,
                confidence=confidence,
            )

        # Determine style from room prosody.
        style = self._classify_room_style(room_energy, room_f0_mean, room_rate)

        return ProsodyMatch(
            target_style=style,
            room_energy=room_energy,
            room_f0_mean=room_f0_mean,
            room_speaking_rate=room_rate,
            confidence=confidence,
        )

    def reset(self) -> None:
        """Clear the prosody history."""
        self._history.clear()

    @staticmethod
    def _classify_room_style(
        energy: float,
        f0_mean: float,
        rate: float,
    ) -> str:
        """Classify room prosody into a TTS style.

        Args:
            energy: Average room energy [0, 1].
            f0_mean: Average room F0 in Hz.
            rate: Average speaking rate in WPM.

        Returns:
            Style label string.
        """
        if energy > 0.6 and rate > 160.0:
            return "energetic"
        if energy > 0.6:
            return "emphatic"
        if energy < 0.3:
            return "calm"
        if rate > 180.0:
            return "fast"
        if rate < 100.0:
            return "slow"
        if f0_mean > 250.0:
            return "rising"
        return "varied"
