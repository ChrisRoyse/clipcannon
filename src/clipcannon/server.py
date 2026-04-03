"""ClipCannon MCP server entry point.

Provides the main() function used by the clipcannon console script
defined in pyproject.toml. Initializes the MCP server with tool
registry, stdio/SSE transport support, and structured logging.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from datetime import UTC, datetime

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import ImageContent, TextContent, Tool

from clipcannon import __version__
from clipcannon.tools import ALL_TOOL_DEFINITIONS, TOOL_DISPATCHERS

logger = logging.getLogger(__name__)


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter for MCP server output.

    Formats log records as single-line JSON objects written to stderr
    so they do not interfere with the MCP stdio transport on stdout.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON string.

        Args:
            record: The log record to format.

        Returns:
            JSON-formatted log line.
        """
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry, ensure_ascii=False)


def _setup_logging() -> None:
    """Configure structured JSON logging to stderr."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Quiet noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def create_server() -> Server:
    """Create and configure the MCP server with all tools registered.

    Returns:
        Configured MCP Server instance.
    """
    server = Server(
        name="ClipCannon",
        version=__version__,
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """Return all registered tool definitions."""
        return ALL_TOOL_DEFINITIONS

    @server.call_tool()
    async def call_tool(
        name: str,
        arguments: dict[str, object] | None = None,
    ) -> list[TextContent | ImageContent]:
        """Dispatch a tool call and return the result.

        Routes the call to the appropriate tool dispatcher based on
        the tool name. Results are serialized as JSON text. If the
        result contains a '_image' key, an ImageContent with base64
        data is also returned so the AI can see the image directly.

        Args:
            name: Tool name to invoke.
            arguments: Tool arguments dictionary.

        Returns:
            List of TextContent and optionally ImageContent.
        """
        args = arguments or {}
        logger.info("Tool call: %s", name)

        dispatch_fn = TOOL_DISPATCHERS.get(name)
        if dispatch_fn is None:
            error_result = {
                "error": {
                    "code": "UNKNOWN_TOOL",
                    "message": f"Unknown tool: {name}",
                    "details": {"available_tools": [t.name for t in ALL_TOOL_DEFINITIONS]},
                },
            }
            return [
                TextContent(
                    type="text",
                    text=json.dumps(error_result, indent=2, default=str),
                )
            ]

        try:
            result = await dispatch_fn(name, args)
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            result = {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"Tool execution failed: {exc}",
                    "details": {"tool": name},
                },
            }

        contents: list[TextContent | ImageContent] = []

        # Extract inline image data if present
        image_data = None
        if isinstance(result, dict) and "_image" in result:
            image_data = result.pop("_image")

        contents.append(
            TextContent(
                type="text",
                text=json.dumps(result, indent=2, default=str),
            )
        )

        if image_data is not None:
            contents.append(
                ImageContent(
                    type="image",
                    data=str(image_data["data"]),
                    mimeType=str(image_data["mimeType"]),
                )
            )

        return contents

    logger.info(
        "ClipCannon MCP server created: %d tools registered",
        len(ALL_TOOL_DEFINITIONS),
    )
    return server


async def run_stdio() -> None:
    """Run the MCP server over stdio transport."""
    server = create_server()
    init_options = server.create_initialization_options()

    async with stdio_server() as (read_stream, write_stream):
        logger.info("ClipCannon MCP server v%s running on stdio", __version__)
        await server.run(read_stream, write_stream, init_options)


def _start_wake_listener() -> "subprocess.Popen[bytes] | None":
    """Spawn the voice agent wake listener as a background process.

    Runs ``python -m voiceagent listen`` in the background so the user
    can say "Hey Jarvis" at any time while ClipCannon is active.
    Logs go to ~/.clipcannon/wake_listener.log so they don't block
    the MCP stdio transport or fill up a pipe buffer.
    Returns the Popen handle (or None if launch fails).
    """
    from pathlib import Path

    log_dir = Path.home() / ".clipcannon"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "wake_listener.log"

    try:
        fh = open(log_file, "a")  # noqa: SIM115
        proc = subprocess.Popen(
            [sys.executable, "-m", "voiceagent", "listen", "--voice", "boris"],
            stdout=fh,
            stderr=fh,
            start_new_session=True,  # Detach from parent's terminal signals
        )
        logger.info(
            "Wake listener started (PID %d, log=%s) -- say 'Hey Jarvis' to activate",
            proc.pid, log_file,
        )
        return proc
    except (OSError, FileNotFoundError) as exc:
        logger.warning("Failed to start wake listener: %s", exc)
        return None


def main() -> None:
    """Start the ClipCannon MCP server.

    Entry point for the ``clipcannon`` console script. Configures
    structured logging and starts the server on stdio transport.
    Auto-starts the voice agent wake listener in the background.
    """
    _setup_logging()
    logger.info("ClipCannon MCP Server v%s starting...", __version__)

    # Auto-start the wake listener so "Hey Jarvis" works immediately
    listener_proc = _start_wake_listener()

    try:
        asyncio.run(run_stdio())
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception:
        logger.exception("Server crashed")
        sys.exit(1)
    finally:
        # Clean up the wake listener when the MCP server exits
        if listener_proc and listener_proc.poll() is None:
            logger.info("Stopping wake listener (PID %d)...", listener_proc.pid)
            listener_proc.terminate()
            try:
                listener_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                listener_proc.kill()


if __name__ == "__main__":
    main()
