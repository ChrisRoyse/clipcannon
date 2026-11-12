"""Shared types for the meeting reasoning controller.

Split out of ``voiceagent.meeting.reasoning_controller`` (pure move): the
action intents, the situational-awareness state, the address-word matcher
and ``AvatarCommand``.
"""

from __future__ import annotations

import enum
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


# ---------------------------------------------------------------------------
# Action intents (Tier 2 output)
# ---------------------------------------------------------------------------
class ActionIntent(enum.Enum):
    IDLE = "idle"                         # No one talking, stay neutral
    LISTEN_ATTENTIVE = "listen_attentive" # Someone talking, look engaged
    LISTEN_AMUSED = "listen_amused"       # Humor detected, smile
    LISTEN_EMPATHETIC = "listen_empathetic"  # Sadness detected, soften
    THINK = "think"                       # Question directed at me, thinking
    RESPOND = "respond"                   # I should speak now
    INTERJECT = "interject"               # Natural opening, maybe speak
    REACT_LAUGH = "react_laugh"           # Laugh reaction (no speech)
    REACT_NOD = "react_nod"              # Nod reaction (no speech)


# ---------------------------------------------------------------------------
# Situational awareness state
# ---------------------------------------------------------------------------
@dataclass
class SituationalAwareness:
    """Rolling state of what's happening in the meeting."""
    current_speaker: str | None = None
    speaker_is_addressing_me: bool = False
    detected_emotion: str = "neutral"
    social_signal: str = "neutral"
    room_energy: float = 0.5
    silence_duration_ms: int = 0
    time_since_last_spoke_ms: int = 999999
    conversation_topic: str = ""

    # Rolling transcript window (last 60s)
    recent_segments: deque = field(default_factory=lambda: deque(maxlen=30))

    # Current decision
    current_intent: ActionIntent = ActionIntent.IDLE
    inner_thought: str = ""
    speak_urgency: float = 0.0
    last_decision_time: float = 0.0
    last_spoke_time: float = 0.0


# ---------------------------------------------------------------------------
# Address words for name detection
# ---------------------------------------------------------------------------
def _address_pattern(words: Iterable[str]) -> re.Pattern[str]:
    """Whole-word, case-insensitive matcher for the names the avatar answers to."""
    names = sorted(
        {w.strip().lower() for w in words if w and w.strip()}, key=len, reverse=True
    )
    if not names:
        return re.compile(r"(?!x)x")  # matches nothing
    alternation = "|".join(re.escape(n) for n in names)
    return re.compile(r"\b(?:" + alternation + r")(?!\w)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Reasoning Controller
# ---------------------------------------------------------------------------
class AvatarCommand:
    """Command from the reasoning controller to the avatar pipeline.

    Every reasoning cycle produces one of these, which drives ALL
    avatar subsystems: face rendering, voice, lip sync, body pose.
    """

    def __init__(
        self,
        intent: ActionIntent,
        blendshapes: dict[str, float] | None = None,
        voice_params: dict[str, float] | None = None,
        gaze_target: tuple[float, float] = (0.0, 0.0),
        head_pose: tuple[float, float, float] = (0.0, 0.0, 0.0),
        speak_text: str | None = None,
        prosody_style: str = "default",
    ) -> None:
        self.intent = intent
        self.blendshapes = blendshapes or {}
        self.voice_params = voice_params or {}
        self.gaze_target = gaze_target
        self.head_pose = head_pose
        self.speak_text = speak_text
        self.prosody_style = prosody_style
        self.timestamp = time.time()
