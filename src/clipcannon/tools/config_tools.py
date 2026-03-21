"""Configuration MCP tools for ClipCannon.

Provides tools for getting, setting, and listing configuration values
using dot-notation keys (e.g., "processing.whisper_model").
"""

from __future__ import annotations

import logging

from mcp.types import Tool

from clipcannon.config import ClipCannonConfig, ConfigValue
from clipcannon.exceptions import ConfigError

logger = logging.getLogger(__name__)


def _error_response(
    code: str, message: str, details: dict[str, object] | None = None
) -> dict[str, object]:
    """Build a standardized error response dict.

    Args:
        code: Machine-readable error code.
        message: Human-readable error message.
        details: Optional additional context.

    Returns:
        Error response dictionary.
    """
    return {"error": {"code": code, "message": message, "details": details or {}}}


async def clipcannon_config_get(key: str) -> dict[str, object]:
    """Get a configuration value by dot-notation key.

    Args:
        key: Dot-separated config key (e.g., "processing.whisper_model").

    Returns:
        Dict with key and value, or error response.
    """
    try:
        config = ClipCannonConfig.load()
        value = config.get(key)
        return {"key": key, "value": value}
    except ConfigError as exc:
        return _error_response("INVALID_PARAMETER", str(exc), exc.details)
    except Exception as exc:
        return _error_response("INTERNAL_ERROR", f"Config read failed: {exc}")


async def clipcannon_config_set(key: str, value: ConfigValue) -> dict[str, object]:
    """Set a configuration value and persist to disk.

    Args:
        key: Dot-separated config key (e.g., "gpu.max_vram_usage_gb").
        value: New value to set (must match expected type).

    Returns:
        Dict confirming the change, or error response.
    """
    try:
        config = ClipCannonConfig.load()
        old_value = config.get(key)
        config.set(key, value)
        config.save()

        return {
            "key": key,
            "old_value": old_value,
            "new_value": value,
            "saved": True,
        }
    except ConfigError as exc:
        return _error_response("INVALID_PARAMETER", str(exc), exc.details)
    except Exception as exc:
        return _error_response("INTERNAL_ERROR", f"Config write failed: {exc}")


async def clipcannon_config_list() -> dict[str, object]:
    """List all configuration values.

    Returns:
        Complete configuration dictionary.
    """
    try:
        config = ClipCannonConfig.load()
        return {
            "config": config.to_dict(),
            "config_path": str(config.config_path),
        }
    except ConfigError as exc:
        return _error_response("INTERNAL_ERROR", str(exc), exc.details)
    except Exception as exc:
        return _error_response("INTERNAL_ERROR", f"Config list failed: {exc}")


# ============================================================
# TOOL DEFINITIONS
# ============================================================

CONFIG_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="clipcannon_config_get",
        description=(
            "Get a ClipCannon configuration value by dot-notation key"
            " (e.g., 'processing.whisper_model', 'gpu.device')."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Dot-separated config key path",
                },
            },
            "required": ["key"],
        },
    ),
    Tool(
        name="clipcannon_config_set",
        description=(
            "Set a ClipCannon configuration value and save to disk."
            " Value is validated against the config schema."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Dot-separated config key path",
                },
                "value": {
                    "description": "New value (type must match config schema)",
                },
            },
            "required": ["key", "value"],
        },
    ),
    Tool(
        name="clipcannon_config_list",
        description="List all ClipCannon configuration values with their current settings.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
]


async def dispatch_config_tool(name: str, arguments: dict[str, object]) -> dict[str, object]:
    """Dispatch a config tool call by name.

    Args:
        name: Tool name.
        arguments: Tool arguments.

    Returns:
        Tool result dictionary.
    """
    if name == "clipcannon_config_get":
        return await clipcannon_config_get(
            key=str(arguments["key"]),
        )
    elif name == "clipcannon_config_set":
        return await clipcannon_config_set(
            key=str(arguments["key"]),
            value=arguments["value"],
        )
    elif name == "clipcannon_config_list":
        return await clipcannon_config_list()
    else:
        return _error_response("INTERNAL_ERROR", f"Unknown config tool: {name}")
