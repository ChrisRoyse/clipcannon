"""Always-on reasoning controller for the meeting avatar.

Three-tier continuous decision loop that observes the meeting
and decides what the avatar should be doing every moment:

  Tier 1 — Perception (every 50ms, rule-based):
    Sentiment classification, prosody extraction, avatar expression updates.
    Runs on CPU, no LLM needed.

  Tier 2 — Reasoning (every 500ms-2s, Qwen2.5-0.5B ONNX):
    "What should I be doing right now?"
    Classifies situation into action intents:
    LISTEN_ATTENTIVE, LISTEN_AMUSED, LISTEN_EMPATHETIC,
    THINK, RESPOND, INTERJECT, IDLE

  Tier 3 — Response (on-demand, Qwen3:8b via Ollama):
    Generates actual speech when Tier 2 says RESPOND/INTERJECT.

Based on: "Proactive Conversational Agents with Inner Thoughts"
(CHI 2025, arxiv 2501.00383) — maintains parallel thought stream
and evaluates whether each thought is worth externalizing.
"""
from __future__ import annotations

import asyncio
import enum
import logging
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


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
_ADDRESS_WORDS = {"santa", "jarvis", "claus", "mr. claus", "father christmas"}


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


class ReasoningController:
    """Central nervous system for the meeting avatar.

    Controls EVERYTHING: face rendering, voice synthesis, lip sync,
    eye behavior, body pose, prosody selection, when to speak, how
    to react. Every subsystem is driven by this controller.

    The controller runs a continuous observe → reason → command loop:
    1. Observe: transcript + prosody + emotion from meeting audio
    2. Reason: classify situation, decide action intent
    3. Command: produce AvatarCommand with blendshapes, voice params,
       gaze, head pose, speak/react decisions

    Args:
        character_name: The name the avatar responds to.
        respond_callback: Async callable(text) -> str that generates
            a response and speaks it. Called when intent is RESPOND.
        expression_callback: Callable(intent, awareness) that updates
            the avatar's visual expression. Called on every Tier 2 cycle.
        avatar_callback: Callable(AvatarCommand) that sends commands
            to the Gaussian renderer + voice pipeline.
    """

    def __init__(
        self,
        character_name: str = "Santa",
        respond_callback=None,
        expression_callback=None,
        avatar_callback=None,
    ) -> None:
        self._name = character_name.lower()
        self._respond = respond_callback
        self._avatar_cb = avatar_callback
        self._update_expression = expression_callback
        self._awareness = SituationalAwareness()
        self._running = False
        self._last_segment_time = 0.0
        self._responding = False

        # Tier 2 reasoning interval
        self._reasoning_interval = 0.8  # seconds

    @property
    def awareness(self) -> SituationalAwareness:
        return self._awareness

    @property
    def is_responding(self) -> bool:
        return self._responding

    # ------------------------------------------------------------------
    # Tier 1: Perception (called externally with each transcript segment)
    # ------------------------------------------------------------------
    def observe(self, text: str, speaker: str = "unknown", timestamp_ms: int = 0) -> None:
        """Feed a transcript segment into the awareness state.

        Called by the audio loop every time Whisper produces a segment.
        This is Tier 1 — pure rule-based, no LLM.
        """
        self._awareness.recent_segments.append({
            "text": text, "speaker": speaker,
            "time": time.time(), "ts_ms": timestamp_ms,
        })
        self._last_segment_time = time.time()
        self._awareness.silence_duration_ms = 0

        # Update addressing detection
        low = text.lower()
        self._awareness.speaker_is_addressing_me = any(
            w in low for w in _ADDRESS_WORDS
        )

        # Simple sentiment from keywords (Tier 1 — no model needed)
        self._awareness.detected_emotion = self._detect_emotion_keywords(low)

        # Topic extraction (last few words)
        words = text.split()
        if len(words) > 3:
            self._awareness.conversation_topic = " ".join(words[-5:])

        logger.debug("Observe: '%s' [addr=%s, emo=%s]",
                     text[:50], self._awareness.speaker_is_addressing_me,
                     self._awareness.detected_emotion)

    def tick_silence(self, elapsed_ms: int) -> None:
        """Called periodically to track silence duration."""
        self._awareness.silence_duration_ms += elapsed_ms
        self._awareness.time_since_last_spoke_ms = int(
            (time.time() - self._awareness.last_spoke_time) * 1000
        )

    # ------------------------------------------------------------------
    # Tier 2: Reasoning (called periodically)
    # ------------------------------------------------------------------
    def reason(self) -> ActionIntent:
        """Evaluate the current situation and decide what to do.

        This is the core decision loop. Currently uses fast heuristics;
        can be upgraded to Qwen2.5-0.5B ONNX for nuanced reasoning.

        Returns:
            The action intent for the avatar.
        """
        a = self._awareness
        now = time.time()

        # Don't reason while actively responding
        if self._responding:
            return ActionIntent.THINK

        # 1. Direct address — always respond
        if a.speaker_is_addressing_me:
            # Check if there's a question
            recent_text = self._get_recent_text(10)  # last 10s
            if "?" in recent_text or any(w in a.conversation_topic.lower()
                                          for w in ["what", "how", "why", "when", "tell", "can you"]):
                a.current_intent = ActionIntent.RESPOND
                a.speak_urgency = 0.95
                a.inner_thought = f"They said my name and asked a question"
                logger.info("Reason: RESPOND (addressed + question)")
                return ActionIntent.RESPOND

            # Name mentioned but no clear question — still respond
            a.current_intent = ActionIntent.RESPOND
            a.speak_urgency = 0.8
            a.inner_thought = f"They said my name"
            logger.info("Reason: RESPOND (addressed)")
            return ActionIntent.RESPOND

        # 2. Emotional reactions (no speech)
        if a.detected_emotion == "amused":
            a.current_intent = ActionIntent.LISTEN_AMUSED
            return ActionIntent.LISTEN_AMUSED

        if a.detected_emotion == "sad":
            a.current_intent = ActionIntent.LISTEN_EMPATHETIC
            return ActionIntent.LISTEN_EMPATHETIC

        # 3. Long silence — maybe interject
        if (a.silence_duration_ms > 8000
                and a.time_since_last_spoke_ms > 30000
                and len(a.recent_segments) > 3):
            a.current_intent = ActionIntent.INTERJECT
            a.speak_urgency = 0.4
            a.inner_thought = "It's been quiet, maybe I should say something"
            logger.info("Reason: INTERJECT (silence)")
            return ActionIntent.INTERJECT

        # 4. Active conversation — listen attentively
        if a.silence_duration_ms < 2000:
            a.current_intent = ActionIntent.LISTEN_ATTENTIVE
            return ActionIntent.LISTEN_ATTENTIVE

        # 5. Default — idle
        a.current_intent = ActionIntent.IDLE
        return ActionIntent.IDLE

    # ------------------------------------------------------------------
    # Avatar command generation
    # ------------------------------------------------------------------
    def produce_command(self, intent: ActionIntent) -> AvatarCommand:
        """Translate an action intent into a full avatar command.

        Maps the high-level intent to specific blendshape values,
        gaze direction, head pose, and prosody selection. This is
        what drives the Gaussian renderer every frame.
        """
        a = self._awareness

        # Intent → blendshape mapping (facial expression)
        blendshapes = self._intent_to_blendshapes(intent, a)

        # Intent → gaze (where to look)
        gaze = self._intent_to_gaze(intent, a)

        # Intent → head pose
        head = self._intent_to_head_pose(intent, a)

        # Intent → prosody style for TTS
        prosody = self._intent_to_prosody(intent, a)

        cmd = AvatarCommand(
            intent=intent,
            blendshapes=blendshapes,
            gaze_target=gaze,
            head_pose=head,
            prosody_style=prosody,
        )

        # Send to avatar pipeline
        if self._avatar_cb:
            try:
                self._avatar_cb(cmd)
            except Exception:
                pass

        return cmd

    def _intent_to_blendshapes(self, intent: ActionIntent, a: SituationalAwareness) -> dict[str, float]:
        """Map intent + awareness to ARKit blendshape values."""
        bs: dict[str, float] = {}

        if intent == ActionIntent.IDLE:
            # Neutral face, slightly relaxed
            bs["jawOpen"] = 0.0
            bs["mouthSmileLeft"] = 0.05
            bs["mouthSmileRight"] = 0.05

        elif intent == ActionIntent.LISTEN_ATTENTIVE:
            # Slightly raised brows, engaged
            bs["browInnerUp"] = 0.15
            bs["eyeWideLeft"] = 0.1
            bs["eyeWideRight"] = 0.1

        elif intent == ActionIntent.LISTEN_AMUSED:
            # Smile, raised cheeks, slight squint
            bs["mouthSmileLeft"] = 0.6
            bs["mouthSmileRight"] = 0.6
            bs["eyeSquintLeft"] = 0.3
            bs["eyeSquintRight"] = 0.3
            bs["browInnerUp"] = 0.1

        elif intent == ActionIntent.LISTEN_EMPATHETIC:
            # Concerned brows, soft mouth, slight frown
            bs["browDownLeft"] = 0.3
            bs["browDownRight"] = 0.3
            bs["browInnerUp"] = 0.4
            bs["mouthFrownLeft"] = 0.2
            bs["mouthFrownRight"] = 0.2

        elif intent == ActionIntent.THINK:
            # Eyes slightly up-left, brows furrowed, mouth closed
            bs["browDownLeft"] = 0.2
            bs["browInnerUp"] = 0.3
            bs["mouthPressLeft"] = 0.2
            bs["mouthPressRight"] = 0.2

        elif intent in (ActionIntent.RESPOND, ActionIntent.INTERJECT):
            # Mouth opens for speech (lip sync overrides this)
            bs["jawOpen"] = 0.2
            bs["mouthSmileLeft"] = 0.1
            bs["mouthSmileRight"] = 0.1
            bs["browInnerUp"] = 0.1

        elif intent == ActionIntent.REACT_LAUGH:
            # Big smile, open mouth, squinted eyes
            bs["jawOpen"] = 0.4
            bs["mouthSmileLeft"] = 0.8
            bs["mouthSmileRight"] = 0.8
            bs["eyeSquintLeft"] = 0.5
            bs["eyeSquintRight"] = 0.5

        elif intent == ActionIntent.REACT_NOD:
            # Slight smile, raised brows
            bs["mouthSmileLeft"] = 0.3
            bs["mouthSmileRight"] = 0.3
            bs["browInnerUp"] = 0.2

        return bs

    def _intent_to_gaze(self, intent: ActionIntent, a: SituationalAwareness) -> tuple[float, float]:
        """Map intent to gaze direction (degrees from center)."""
        if intent == ActionIntent.THINK:
            return (-3.0, 2.0)  # Look up-left while thinking
        if intent in (ActionIntent.RESPOND, ActionIntent.LISTEN_ATTENTIVE):
            return (0.0, 0.0)  # Look at camera (the speaker)
        if intent == ActionIntent.IDLE:
            return (0.0, -1.0)  # Slightly downward when idle
        return (0.0, 0.0)

    def _intent_to_head_pose(self, intent: ActionIntent, a: SituationalAwareness) -> tuple[float, float, float]:
        """Map intent to head pose (pitch, yaw, roll in degrees)."""
        if intent == ActionIntent.REACT_NOD:
            return (-5.0, 0.0, 0.0)  # Slight nod down
        if intent == ActionIntent.THINK:
            return (3.0, -5.0, 0.0)  # Head tilts up-left
        if intent == ActionIntent.LISTEN_EMPATHETIC:
            return (0.0, 0.0, -3.0)  # Slight head tilt (empathetic)
        return (0.0, 0.0, 0.0)

    def _intent_to_prosody(self, intent: ActionIntent, a: SituationalAwareness) -> str:
        """Map intent to prosody style for TTS reference selection."""
        if a.detected_emotion == "amused":
            return "ref_energetic"
        if a.detected_emotion == "sad":
            return "ref_warm"
        if intent == ActionIntent.RESPOND and a.speak_urgency > 0.8:
            return "ref_emphatic"
        if intent == ActionIntent.INTERJECT:
            return "ref_calm"
        return "ref_default"

    # ------------------------------------------------------------------
    # Tier 3: Response execution
    # ------------------------------------------------------------------
    async def execute_response(self, text: str) -> str | None:
        """Generate and deliver a response.

        Args:
            text: The user's message that triggered the response.

        Returns:
            The response text, or None if generation failed.
        """
        if self._respond is None:
            return None

        self._responding = True
        self._awareness.current_intent = ActionIntent.THINK
        try:
            result = await self._respond(text)
            self._awareness.last_spoke_time = time.time()
            return result
        finally:
            self._responding = False
            self._awareness.current_intent = ActionIntent.LISTEN_ATTENTIVE

    # ------------------------------------------------------------------
    # Main loop (runs as async task)
    # ------------------------------------------------------------------
    async def run(self, stop_event: asyncio.Event) -> None:
        """Continuous reasoning + command loop. Run as a background task.

        Every cycle:
        1. Reason about current situation → ActionIntent
        2. Produce AvatarCommand (blendshapes, gaze, pose, prosody)
        3. Send command to avatar pipeline (renderer, voice, lip sync)

        The avatar is ALWAYS being controlled — even during silence,
        the controller sends idle/breathing commands. There is never
        a moment where the avatar isn't being driven by intelligence.
        """
        self._running = True
        logger.info("Reasoning controller started — driving ALL avatar subsystems")

        while not stop_event.is_set() and self._running:
            try:
                # Tier 2: Decide what to do
                intent = self.reason()

                # Produce full avatar command from intent
                cmd = self.produce_command(intent)

                # Legacy expression callback
                if self._update_expression:
                    try:
                        self._update_expression(intent, self._awareness)
                    except Exception:
                        pass

                self._awareness.last_decision_time = time.time()

            except Exception as e:
                logger.error("Reasoning error: %s", e)

            await asyncio.sleep(self._reasoning_interval)

        logger.info("Reasoning controller stopped")

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_recent_text(self, seconds: float = 10) -> str:
        """Get concatenated text from the last N seconds."""
        cutoff = time.time() - seconds
        parts = []
        for seg in self._awareness.recent_segments:
            if seg["time"] >= cutoff:
                parts.append(seg["text"])
        return " ".join(parts)

    @staticmethod
    def _detect_emotion_keywords(text: str) -> str:
        """Fast keyword-based emotion detection (Tier 1)."""
        amused_words = {"haha", "lol", "funny", "joke", "hilarious", "laugh", "😂"}
        sad_words = {"sad", "sorry", "unfortunately", "miss", "lost", "passed away", "difficult"}
        excited_words = {"amazing", "awesome", "incredible", "wow", "fantastic", "great"}
        angry_words = {"angry", "frustrated", "annoyed", "terrible", "awful"}

        for w in amused_words:
            if w in text:
                return "amused"
        for w in sad_words:
            if w in text:
                return "sad"
        for w in excited_words:
            if w in text:
                return "excited"
        for w in angry_words:
            if w in text:
                return "angry"
        return "neutral"
