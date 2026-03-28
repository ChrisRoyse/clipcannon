"""Custom exception hierarchy for the Voice Agent.

All voice agent exceptions inherit from VoiceAgentError.
Subsystem-specific exceptions are organized by domain.
"""


class VoiceAgentError(Exception):
    """Base exception for all voice agent errors."""


class ConfigError(VoiceAgentError):
    """Raised when configuration is invalid or missing."""


class ASRError(VoiceAgentError):
    """Raised when ASR (speech recognition) fails."""


class VADError(ASRError):
    """Raised when VAD (voice activity detection) fails. Subclass of ASRError."""


class LLMError(VoiceAgentError):
    """Raised when LLM inference fails."""


class TTSError(VoiceAgentError):
    """Raised when TTS (text-to-speech) synthesis fails."""


class TransportError(VoiceAgentError):
    """Raised when WebSocket transport fails."""


class DatabaseError(VoiceAgentError):
    """Raised when database operations fail."""


class WakeWordError(VoiceAgentError):
    """Raised when wake word detection fails."""


class ActivationError(VoiceAgentError):
    """Raised when voice activation (wake word or push-to-talk) fails."""


class ModelLoadError(VoiceAgentError):
    """Raised when a GPU model fails to load (VRAM, path, or compatibility issues)."""


class ConversationError(VoiceAgentError):
    """Raised when conversation state machine encounters an invalid transition."""
