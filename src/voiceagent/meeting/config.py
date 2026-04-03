"""Meeting clone configuration system.

All config classes are frozen dataclasses (immutable after creation).
MeetingConfig is the top-level container that aggregates all sub-configs.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from voiceagent.errors import ConfigError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CloneConfig:
    """Per-clone identity and behavior settings.

    Args:
        voice_profile: Name of the TTS voice profile to use.
        driver_image: Path to headshot image for lip sync driver.
        driver_video: Optional path to driver video for lip sync.
        aliases: List of names/phrases that trigger address detection.
        video_device_nr: v4l2loopback device number for this clone.
        address_threshold: Minimum confidence to consider clone addressed.
        llm_max_tokens: Max tokens for LLM response generation.
        llm_temperature: Temperature for LLM response generation.
    """

    voice_profile: str = ""
    driver_image: str = ""
    driver_video: str | None = None
    aliases: list[str] = field(default_factory=list)
    video_device_nr: int = 20
    address_threshold: float = 0.8
    llm_max_tokens: int = 150
    llm_temperature: float = 0.4


@dataclass(frozen=True)
class AudioCaptureConfig:
    """Meeting audio capture settings.

    Args:
        source: PulseAudio source name (e.g. "default.monitor").
        sample_rate: Audio sample rate in Hz.
    """

    source: str = "default.monitor"
    sample_rate: int = 16000


@dataclass(frozen=True)
class TranscriptionConfig:
    """ASR transcription settings.

    Args:
        model: Faster-whisper model name.
        compute_type: Compute precision type.
        window_seconds: Sliding window size for streaming ASR.
        context_buffer_minutes: Minutes of context to keep for diarization.
    """

    model: str = "large-v3-turbo"
    compute_type: str = "float16"
    window_seconds: int = 5
    context_buffer_minutes: int = 10


@dataclass(frozen=True)
class DiarizationConfig:
    """Speaker diarization settings.

    Args:
        model: Pyannote model identifier.
        enabled: Whether to run diarization.
    """

    model: str = "pyannote/speaker-diarization-community-1"
    enabled: bool = True


@dataclass(frozen=True)
class VoiceConfig:
    """TTS voice quality and prosody settings.

    Args:
        secs_threshold: Minimum SECS score to accept TTS output.
        secs_candidates_max: Max candidates for best-of-N SECS selection.
        prosody_selection: Prosody selection mode ("always", "never").
        enhance: Whether to run Resemble Enhance on TTS output.
        enhance_sample_rate: Target sample rate after enhancement.
    """

    secs_threshold: float = 0.95
    secs_candidates_max: int = 5
    prosody_selection: str = "always"
    enhance: bool = True
    enhance_sample_rate: int = 44100


@dataclass(frozen=True)
class LipSyncConfig:
    """Real-time lip sync settings.

    Args:
        engine: Lip sync engine name.
        output_fps: FPS when clone is speaking.
        idle_fps: FPS when clone is idle.
        resolution: Output video resolution as [width, height].
        face_resolution: Face crop resolution as [width, height].
    """

    engine: str = "musetalk-1.5"
    output_fps: int = 30
    idle_fps: int = 30
    resolution: tuple[int, int] = (1280, 720)
    face_resolution: tuple[int, int] = (256, 256)


@dataclass(frozen=True)
class ResponseConfig:
    """LLM response generation settings.

    Args:
        max_tokens: Max tokens for response.
        temperature: Sampling temperature.
        model: LLM model identifier.
        system_prompt_override: Optional override for the system prompt.
    """

    max_tokens: int = 150
    temperature: float = 0.4
    model: str = "qwen3:14b-nothink"
    system_prompt_override: str | None = None


@dataclass(frozen=True)
class TranscriptConfig:
    """Meeting transcript storage settings via OCR Provenance MCP.

    Args:
        ocr_provenance_url: URL of the OCR Provenance session proxy (port 3377).
        database_name: Name of the OCR Provenance database for meeting transcripts.
        transcript_dir: Local directory for Markdown transcript files (crash safety).
        flush_interval_seconds: Flush transcript to disk every N seconds.
        flush_interval_segments: Flush transcript to disk every N segments.
        auto_end_silence_minutes: End meeting after this many minutes of silence.
        auto_summary: Whether to generate post-meeting summary.
        auto_title: Whether to auto-generate meeting title.
        auto_tag: Whether to auto-tag meetings by topic, clone, platform.
    """

    ocr_provenance_url: str = "http://localhost:3377/mcp"
    database_name: str = "meetings"
    transcript_dir: str = "~/.voiceagent/meeting_transcripts"
    flush_interval_seconds: int = 30
    flush_interval_segments: int = 10
    auto_end_silence_minutes: int = 5
    auto_summary: bool = True
    auto_title: bool = True
    auto_tag: bool = True


@dataclass(frozen=True)
class BehaviorConfig:
    """Clone behavior and presence simulation settings.

    Args:
        default_muted: Whether clone starts muted in the meeting.
        unmute_before_speak_ms: Milliseconds to unmute before speaking.
        mute_after_speak_ms: Milliseconds to wait after speaking before re-muting.
        platform_auto_detect: Whether to auto-detect the meeting platform.
        platform_override: Force a specific platform (overrides auto-detect).
        idle_blink_interval_s: Range [min, max] seconds between idle blinks.
        comfort_noise_dbfs: Comfort noise level in dBFS when muted.
    """

    default_muted: bool = True
    unmute_before_speak_ms: int = 200
    mute_after_speak_ms: int = 300
    platform_auto_detect: bool = True
    platform_override: str | None = None
    idle_blink_interval_s: tuple[int, int] = (3, 6)
    comfort_noise_dbfs: int = -60


@dataclass(frozen=True)
class ZoomSdkConfig:
    """Zoom Meeting SDK credentials for Mode 2 bot join.

    Args:
        client_id: Zoom Meeting SDK client ID from marketplace.zoom.us.
        client_secret: Zoom Meeting SDK client secret.
    """

    client_id: str = ""
    client_secret: str = ""


@dataclass(frozen=True)
class BrowserBotConfig:
    """Puppeteer/Playwright browser bot settings for Mode 2.

    Args:
        chromium_path: Path to Chromium binary. None = auto-detect.
        headless: Run browser headless (no GUI).
        user_data_dir: Directory for Chromium profile data.
    """

    chromium_path: str | None = None
    headless: bool = True
    user_data_dir: str = "~/.voiceagent/chromium-profile"


@dataclass(frozen=True)
class BotJoinConfig:
    """Mode 2: Join meeting as a separate participant.

    Args:
        enabled: Whether Mode 2 bot join is available.
        default_display_name: Default name shown in participant list.
        zoom_sdk: Zoom Meeting SDK credentials.
        browser_bot: Browser automation settings.
    """

    enabled: bool = False
    default_display_name: str = "AI Notes"
    zoom_sdk: ZoomSdkConfig = field(default_factory=ZoomSdkConfig)
    browser_bot: BrowserBotConfig = field(default_factory=BrowserBotConfig)


@dataclass(frozen=True)
class MeetingConfig:
    """Top-level meeting clone configuration.

    Aggregates all sub-configs and the per-clone definitions.

    Args:
        clones: Mapping of clone name to its CloneConfig.
        audio_capture: Audio capture settings.
        transcription: ASR transcription settings.
        diarization: Speaker diarization settings.
        voice: TTS voice quality settings.
        lip_sync: Lip sync settings.
        response: LLM response settings.
        transcript: Transcript storage settings.
        behavior: Clone behavior settings.
        bot_join: Mode 2 bot join settings.
    """

    clones: dict[str, CloneConfig] = field(default_factory=dict)
    audio_capture: AudioCaptureConfig = field(default_factory=AudioCaptureConfig)
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    diarization: DiarizationConfig = field(default_factory=DiarizationConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    lip_sync: LipSyncConfig = field(default_factory=LipSyncConfig)
    response: ResponseConfig = field(default_factory=ResponseConfig)
    transcript: TranscriptConfig = field(default_factory=TranscriptConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    bot_join: BotJoinConfig = field(default_factory=BotJoinConfig)


_SECTION_MAP: dict[str, type] = {
    "audio_capture": AudioCaptureConfig,
    "transcription": TranscriptionConfig,
    "bot_join": BotJoinConfig,
    "diarization": DiarizationConfig,
    "voice": VoiceConfig,
    "lip_sync": LipSyncConfig,
    "response": ResponseConfig,
    "transcript": TranscriptConfig,
    "behavior": BehaviorConfig,
}

_RANGE_CHECKS: dict[str, dict[str, tuple[float, float]]] = {
    "voice": {
        "secs_threshold": (0.0, 1.0),
        "secs_candidates_max": (1, 20),
        "enhance_sample_rate": (8000, 96000),
    },
    "transcription": {
        "window_seconds": (1, 60),
        "context_buffer_minutes": (1, 120),
    },
    "transcript": {
        "flush_interval_seconds": (5, 300),
        "flush_interval_segments": (1, 100),
        "auto_end_silence_minutes": (1, 60),
    },
    "behavior": {
        "unmute_before_speak_ms": (0, 5000),
        "mute_after_speak_ms": (0, 5000),
        "comfort_noise_dbfs": (-100, 0),
    },
    "response": {
        "max_tokens": (1, 131072),
        "temperature": (0.0, 2.0),
    },
}


def _validate_range(
    section: str,
    key: str,
    value: float | int,
    low: float | int,
    high: float | int,
) -> None:
    """Validate that a config value falls within an allowed range.

    Args:
        section: Config section name (for error messages).
        key: Config key name (for error messages).
        value: The value to validate.
        low: Minimum allowed value (inclusive).
        high: Maximum allowed value (inclusive).

    Raises:
        ConfigError: If value is out of range.
    """
    if not (low <= value <= high):
        raise ConfigError(
            f"Meeting config [{section}].{key} = {value!r} is out of range "
            f"[{low}, {high}]. Fix: set {key} to a value between {low} and {high} "
            f"in ~/.voiceagent/meeting.json"
        )


_NESTED_DATACLASS_MAP: dict[str, dict[str, type]] = {
    "bot_join": {
        "zoom_sdk": ZoomSdkConfig,
        "browser_bot": BrowserBotConfig,
    },
}


def _build_section(section_name: str, cls: type, data: dict) -> object:
    """Build a config section dataclass from a dict, ignoring unknown keys.

    Handles nested frozen dataclasses for sections listed in
    _NESTED_DATACLASS_MAP (e.g., bot_join.zoom_sdk).

    Args:
        section_name: Section name (for error messages).
        cls: The frozen dataclass type to instantiate.
        data: Raw config dict.

    Returns:
        An instance of cls.

    Raises:
        ConfigError: If field types are wrong or values are out of range.
    """
    import dataclasses

    valid_fields = {f.name for f in dataclasses.fields(cls)}
    filtered = {k: v for k, v in data.items() if k in valid_fields}

    # Convert list values to tuples for tuple-typed fields
    field_types = {f.name: f.type for f in dataclasses.fields(cls)}
    for k, v in filtered.items():
        if isinstance(v, list) and "tuple" in str(field_types.get(k, "")):
            filtered[k] = tuple(v)

    # Build nested frozen dataclasses from dicts
    nested_map = _NESTED_DATACLASS_MAP.get(section_name, {})
    for nested_key, nested_cls in nested_map.items():
        if nested_key in filtered and isinstance(filtered[nested_key], dict):
            nested_fields = {f.name for f in dataclasses.fields(nested_cls)}
            nested_data = {
                k: v for k, v in filtered[nested_key].items()
                if k in nested_fields
            }
            filtered[nested_key] = nested_cls(**nested_data)

    try:
        instance = cls(**filtered)
    except TypeError as e:
        raise ConfigError(
            f"Invalid meeting config for [{section_name}]: {e}. "
            f"Fix: check field names and types in ~/.voiceagent/meeting.json"
        ) from e

    checks = _RANGE_CHECKS.get(section_name, {})
    for key, (low, high) in checks.items():
        _validate_range(section_name, key, getattr(instance, key), low, high)
    return instance


def _build_clone(name: str, data: dict) -> CloneConfig:
    """Build a CloneConfig from a dict.

    Args:
        name: Clone name (for error messages).
        data: Raw clone config dict.

    Returns:
        A CloneConfig instance.

    Raises:
        ConfigError: If field types are wrong.
    """
    import dataclasses

    valid_fields = {f.name for f in dataclasses.fields(CloneConfig)}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    try:
        return CloneConfig(**filtered)
    except TypeError as e:
        raise ConfigError(
            f"Invalid clone config for '{name}': {e}. "
            f"Fix: check clone field names in ~/.voiceagent/meeting.json"
        ) from e


def load_meeting_config(path: str | Path | None = None) -> MeetingConfig:
    """Load meeting config from JSON file, returning defaults if file does not exist.

    Args:
        path: Path to config JSON file. Defaults to ~/.voiceagent/meeting.json.

    Returns:
        MeetingConfig with values from file merged over defaults.

    Raises:
        ConfigError: If JSON is malformed or field values are invalid.
    """
    if path is None:
        path = Path.home() / ".voiceagent" / "meeting.json"
    path = Path(path).expanduser()

    if not path.exists():
        return MeetingConfig()

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"Cannot read meeting config file {path}: {e}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigError(
            f"Invalid JSON in meeting config file {path}: {e}. "
            f"Fix: validate your JSON at ~/.voiceagent/meeting.json"
        ) from e

    if not isinstance(data, dict):
        raise ConfigError(
            f"Meeting config file must contain a JSON object (dict), "
            f"got {type(data).__name__}. Fix: ensure ~/.voiceagent/meeting.json "
            f"starts with {{ and ends with }}"
        )

    kwargs: dict = {}

    # Build per-clone configs
    if "clones" in data and isinstance(data["clones"], dict):
        clones: dict[str, CloneConfig] = {}
        for clone_name, clone_data in data["clones"].items():
            if isinstance(clone_data, dict):
                clones[clone_name] = _build_clone(clone_name, clone_data)
        kwargs["clones"] = clones

    # Build section configs
    for section_name, cls in _SECTION_MAP.items():
        if section_name in data and isinstance(data[section_name], dict):
            kwargs[section_name] = _build_section(section_name, cls, data[section_name])

    return MeetingConfig(**kwargs)
