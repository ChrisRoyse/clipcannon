"""Configuration management for ClipCannon.

Loads configuration from ~/.clipcannon/config.json with fallback to
bundled defaults. Supports dot-notation access for nested keys and
type-safe updates with pydantic validation.

Example:
    config = ClipCannonConfig.load()
    model = config.get("processing.whisper_model")
    config.set("gpu.max_vram_usage_gb", 24)
    config.save()
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path

from pydantic import BaseModel, Field

from clipcannon.exceptions import ConfigError

logger = logging.getLogger(__name__)

# Type alias for config values (no Any)
ConfigValue = str | int | float | bool | None | list["ConfigValue"] | dict[str, "ConfigValue"]

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "default_config.json"
USER_CONFIG_DIR = Path.home() / ".clipcannon"
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.json"


class DirectoriesConfig(BaseModel):
    """Directory path configuration."""

    projects: str = "~/.clipcannon/projects"
    models: str = "~/.clipcannon/models"
    temp: str = "~/.clipcannon/tmp"


class ProcessingConfig(BaseModel):
    """Video processing configuration."""

    frame_extraction_fps: int = 2
    whisper_model: str = "large-v3"
    whisper_compute_type: str = "int8"
    batch_size_visual: int = 64
    scene_change_threshold: float = 0.85
    highlight_count_default: int = 20
    min_clip_duration_ms: int = 5000
    max_clip_duration_ms: int = 600000


class AudioConfig(BaseModel):
    """Audio generation and mixing configuration."""

    music_model: str = "ace-step-v1.5"
    music_guidance_scale: float = 15.0
    music_infer_steps: int = 100
    music_default_volume_db: float = -12
    musicgen_model_size: str = "medium"
    auto_music_tier: str = "auto"
    duck_under_speech: bool = True
    duck_level_db: float = -18
    sfx_on_transitions: bool = True
    sfx_default_type: str = "whoosh"
    midi_soundfont: str = "GeneralUser_GS.sf2"
    normalize_output: bool = True
    sample_rate: int = 44100


class RenderingConfig(BaseModel):
    """Rendering output configuration."""

    default_profile: str = "youtube_standard"
    use_nvenc: bool = True
    nvenc_preset: str = "p4"
    caption_default_style: str = "bold_centered"
    thumbnail_format: str = "jpg"
    thumbnail_quality: int = 95
    max_parallel_renders: int = 3


class PublishingConfig(BaseModel):
    """Publishing configuration."""

    require_approval: bool = True
    max_daily_posts_per_platform: int = 5


class GPUConfig(BaseModel):
    """GPU device configuration."""

    device: str = "cuda:0"
    max_vram_usage_gb: int = 24
    concurrent_models: bool = True


class FullConfig(BaseModel):
    """Complete validated configuration model."""

    version: str = "1.0"
    directories: DirectoriesConfig = Field(default_factory=DirectoriesConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    rendering: RenderingConfig = Field(default_factory=RenderingConfig)
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)
    gpu: GPUConfig = Field(default_factory=GPUConfig)


def _load_default_config() -> dict[str, ConfigValue]:
    """Load the bundled default configuration file.

    Returns:
        Parsed default configuration dictionary.

    Raises:
        ConfigError: If the default config file is missing or unparsable.
    """
    if not DEFAULT_CONFIG_PATH.exists():
        raise ConfigError(
            f"Default config not found at {DEFAULT_CONFIG_PATH}",
            details={"path": str(DEFAULT_CONFIG_PATH)},
        )
    try:
        return json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))  # type: ignore[return-value]
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"Invalid JSON in default config: {exc}",
            details={"path": str(DEFAULT_CONFIG_PATH)},
        ) from exc


def _deep_merge(
    base: dict[str, ConfigValue], override: dict[str, ConfigValue]
) -> dict[str, ConfigValue]:
    """Deep-merge override into base, returning a new dict.

    Args:
        base: Base configuration dictionary.
        override: Override values to merge on top.

    Returns:
        Merged configuration dictionary.
    """
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)  # type: ignore[arg-type]
        else:
            result[key] = deepcopy(value)
    return result


def _get_nested(data: dict[str, ConfigValue], dotted_key: str) -> ConfigValue:
    """Retrieve a value from a nested dict using dot-notation.

    Args:
        data: Nested configuration dictionary.
        dotted_key: Dot-separated key path (e.g. "processing.whisper_model").

    Returns:
        The value at the specified key path.

    Raises:
        ConfigError: If the key path does not exist.
    """
    parts = dotted_key.split(".")
    current: ConfigValue = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            raise ConfigError(
                f"Config key not found: {dotted_key}",
                details={"key": dotted_key, "failed_at": part},
            )
        current = current[part]
    return current


def _set_nested(data: dict[str, ConfigValue], dotted_key: str, value: ConfigValue) -> None:
    """Set a value in a nested dict using dot-notation.

    Args:
        data: Nested configuration dictionary (modified in place).
        dotted_key: Dot-separated key path.
        value: Value to set.

    Raises:
        ConfigError: If the key path cannot be traversed.
    """
    parts = dotted_key.split(".")
    current: ConfigValue = data
    for part in parts[:-1]:
        if not isinstance(current, dict):
            raise ConfigError(
                f"Cannot traverse config path: {dotted_key}",
                details={"key": dotted_key, "failed_at": part},
            )
        if part not in current:
            current[part] = {}
        current = current[part]
    if not isinstance(current, dict):
        raise ConfigError(
            f"Cannot set config at path: {dotted_key}",
            details={"key": dotted_key},
        )
    current[parts[-1]] = value


class ClipCannonConfig:
    """Configuration manager with dot-notation access and pydantic validation.

    Loads config from ~/.clipcannon/config.json, falling back to bundled
    defaults for any missing keys. Validates the full config on load and
    on each update.

    Attributes:
        data: Raw configuration dictionary.
        validated: Pydantic-validated configuration model.
        config_path: Path to the user config file.
    """

    def __init__(self, data: dict[str, ConfigValue], config_path: Path = USER_CONFIG_PATH) -> None:
        """Initialize configuration from a pre-merged data dictionary.

        Args:
            data: Merged configuration dictionary.
            config_path: Path where user config will be saved.

        Raises:
            ConfigError: If the data fails pydantic validation.
        """
        self.data = data
        self.config_path = config_path
        self.validated = self._validate(data)

    @staticmethod
    def _validate(data: dict[str, ConfigValue]) -> FullConfig:
        """Validate configuration data against the pydantic model.

        Args:
            data: Configuration dictionary to validate.

        Returns:
            Validated FullConfig instance.

        Raises:
            ConfigError: If validation fails.
        """
        try:
            return FullConfig.model_validate(data)
        except Exception as exc:
            raise ConfigError(
                f"Config validation failed: {exc}",
                details={"error": str(exc)},
            ) from exc

    @classmethod
    def load(cls, config_path: Path | None = None) -> ClipCannonConfig:
        """Load configuration from disk with fallback to defaults.

        Loads the default config first, then deep-merges the user config
        on top if it exists.

        Args:
            config_path: Override path for user config file.

        Returns:
            Loaded and validated ClipCannonConfig instance.

        Raises:
            ConfigError: If configuration cannot be loaded or validated.
        """
        path = config_path or USER_CONFIG_PATH
        defaults = _load_default_config()

        if path.exists():
            try:
                user_data: dict[str, ConfigValue] = json.loads(path.read_text(encoding="utf-8"))
                merged = _deep_merge(defaults, user_data)
                logger.info("Loaded user config from %s", path)
            except json.JSONDecodeError as exc:
                logger.warning("Invalid user config at %s, using defaults: %s", path, exc)
                merged = defaults
        else:
            logger.info("No user config at %s, using defaults", path)
            merged = defaults

        return cls(merged, config_path=path)

    def get(self, dotted_key: str) -> ConfigValue:
        """Retrieve a configuration value using dot-notation.

        Args:
            dotted_key: Dot-separated key path (e.g. "processing.whisper_model").

        Returns:
            The configuration value at the specified path.

        Raises:
            ConfigError: If the key path does not exist.
        """
        return _get_nested(self.data, dotted_key)

    def set(self, dotted_key: str, value: ConfigValue) -> None:
        """Set a configuration value using dot-notation and re-validate.

        Args:
            dotted_key: Dot-separated key path.
            value: New value to set.

        Raises:
            ConfigError: If the update results in invalid configuration.
        """
        _set_nested(self.data, dotted_key, value)
        self.validated = self._validate(self.data)

    def save(self) -> None:
        """Save current configuration to disk.

        Creates the parent directory if it does not exist.

        Raises:
            ConfigError: If the file cannot be written.
        """
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(
                json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            logger.info("Saved config to %s", self.config_path)
        except OSError as exc:
            raise ConfigError(
                f"Failed to save config: {exc}",
                details={"path": str(self.config_path)},
            ) from exc

    def resolve_path(self, dotted_key: str) -> Path:
        """Resolve a directory config value to an absolute Path.

        Expands ~ to the user home directory.

        Args:
            dotted_key: Dot-separated key path pointing to a path string.

        Returns:
            Resolved absolute Path.

        Raises:
            ConfigError: If the value is not a string or key does not exist.
        """
        raw = self.get(dotted_key)
        if not isinstance(raw, str):
            raise ConfigError(
                f"Config key {dotted_key} is not a path string",
                details={"key": dotted_key, "type": type(raw).__name__},
            )
        return Path(raw).expanduser().resolve()

    def to_dict(self) -> dict[str, ConfigValue]:
        """Return a deep copy of the raw configuration data.

        Returns:
            Deep copy of the configuration dictionary.
        """
        return deepcopy(self.data)
