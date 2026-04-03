"""Custom exception hierarchy for the Clone Meeting Agent.

All meeting exceptions inherit from MeetingError, which itself
extends VoiceAgentError to keep a single error tree.
"""

from voiceagent.errors import VoiceAgentError


class MeetingError(VoiceAgentError):
    """Base exception for all meeting-related errors."""


class MeetingAudioError(MeetingError):
    """Raised when meeting audio capture fails (PulseAudio, monitor source)."""


class MeetingTranscriptionError(MeetingError):
    """Raised when meeting ASR / transcription fails."""


class MeetingAddressError(MeetingError):
    """Raised when clone address detection fails."""


class MeetingResponseError(MeetingError):
    """Raised when LLM response generation fails."""


class MeetingVoiceError(MeetingError):
    """Raised when TTS, SECS gating, or prosody selection fails."""


class MeetingDeviceError(MeetingError):
    """Raised when virtual device setup fails (v4l2loopback, PulseAudio)."""


class MeetingLipSyncError(MeetingError):
    """Raised when MuseTalk real-time lip sync fails."""


class MeetingBehaviorError(MeetingError):
    """Raised when mute/unmute automation or idle behavior fails."""


class MeetingTranscriptStoreError(MeetingError):
    """Raised when meeting database storage or retrieval fails."""
