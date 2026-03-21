"""ClipCannon MCP server entry point.

Provides the main() function used by the clipcannon console script
defined in pyproject.toml. Initializes the FastMCP server with tool
registry, stdio/SSE transport support, and configuration loading.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def main() -> None:
    """Start the ClipCannon MCP server.

    Entry point for the ``clipcannon`` console script. Loads configuration,
    initializes the MCP server, and starts serving on the configured
    transport (stdio or SSE).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    logger.info("ClipCannon MCP Server starting...")

    # Placeholder: Full MCP server implementation will be added by Agent 3
    # This entry point exists to satisfy pyproject.toml [project.scripts]
    logger.info("Server scaffold ready. MCP tool registration pending.")


if __name__ == "__main__":
    main()
