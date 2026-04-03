"""OCR Provenance MCP HTTP client for meeting transcript storage.

Sends JSON-RPC tool calls to the OCR Provenance session proxy (port 3377).
Each client instance gets its own session ID for isolated database state.
Docker bridge auth trust means no API key is needed from WSL2.

Connection management:
    - httpx.AsyncClient with connection pooling (max 10 connections)
    - Proper cleanup on close() — no leaked connections
    - Timeout: 30s connect, 120s read (ingest can take time for embedding)

Memory management:
    - Responses parsed and released immediately
    - No response caching or accumulation
    - Client is stateless between calls
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from voiceagent.meeting.errors import MeetingTranscriptStoreError

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:3377/mcp"
CONNECT_TIMEOUT = 30.0
READ_TIMEOUT = 120.0


class OcrProvenanceClient:
    """HTTP JSON-RPC client for OCR Provenance MCP server.

    Each instance has a unique session ID for multi-agent isolation.
    The session proxy (port 3377) routes requests to the container's
    MCP server with per-session database selection and state.

    Args:
        base_url: URL of the OCR Provenance session proxy endpoint.
        session_id: Optional fixed session ID. Auto-generated if not provided.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        session_id: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session_id = session_id or f"clone-meeting-{uuid.uuid4().hex[:12]}"
        self._request_id = 0
        self._client: httpx.AsyncClient | None = None
        logger.info(
            "OcrProvenanceClient created: url=%s session=%s",
            self._base_url,
            self._session_id,
        )

    @property
    def session_id(self) -> str:
        """The MCP session ID for this client."""
        return self._session_id

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx async client.

        Lazy initialization — client created on first call.
        Connection pool: max 10 keepalive connections.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=CONNECT_TIMEOUT,
                    read=READ_TIMEOUT,
                    write=30.0,
                    pool=30.0,
                ),
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                ),
            )
        return self._client

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call an OCR Provenance MCP tool via JSON-RPC over HTTP.

        Args:
            tool_name: Name of the MCP tool (e.g., "ocr_db_create").
            arguments: Tool arguments as a dict.

        Returns:
            The tool result as a dict. Structure varies by tool.

        Raises:
            MeetingTranscriptStoreError: If the HTTP request fails,
                the server returns an error, or the response is malformed.
        """
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
            "id": self._request_id,
        }
        headers = {
            "Content-Type": "application/json",
            "Mcp-Session-Id": self._session_id,
        }

        client = self._get_client()

        try:
            response = await client.post(
                self._base_url,
                json=payload,
                headers=headers,
            )
        except httpx.ConnectError as e:
            raise MeetingTranscriptStoreError(
                f"Cannot connect to OCR Provenance at {self._base_url}. "
                f"Is the Docker container running? Error: {e}"
            ) from e
        except httpx.TimeoutException as e:
            raise MeetingTranscriptStoreError(
                f"Timeout calling OCR Provenance tool '{tool_name}': {e}"
            ) from e
        except httpx.HTTPError as e:
            raise MeetingTranscriptStoreError(
                f"HTTP error calling OCR Provenance tool '{tool_name}': {e}"
            ) from e

        if response.status_code != 200:
            raise MeetingTranscriptStoreError(
                f"OCR Provenance returned HTTP {response.status_code} "
                f"for tool '{tool_name}': {response.text[:500]}"
            )

        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise MeetingTranscriptStoreError(
                f"Invalid JSON response from OCR Provenance for '{tool_name}': {e}"
            ) from e

        # Check for JSON-RPC error
        if "error" in body:
            err = body["error"]
            raise MeetingTranscriptStoreError(
                f"OCR Provenance tool '{tool_name}' returned error: "
                f"code={err.get('code')}, message={err.get('message')}"
            )

        # Extract result — MCP wraps it in result.content
        result = body.get("result", {})
        if isinstance(result, dict) and "content" in result:
            content = result["content"]
            if isinstance(content, list) and len(content) > 0:
                first = content[0]
                if isinstance(first, dict) and "text" in first:
                    try:
                        return json.loads(first["text"])
                    except (json.JSONDecodeError, ValueError):
                        return {"text": first["text"]}
            return result
        return result

    async def health_check(self) -> bool:
        """Check if the OCR Provenance server is reachable.

        Returns:
            True if server responds to health check.

        Raises:
            MeetingTranscriptStoreError: If server is unreachable.
        """
        client = self._get_client()
        # Health endpoint is on the MCP server (3366), but we go through proxy
        health_url = self._base_url.replace("/mcp", "/health")
        if health_url == self._base_url:
            # Fallback: just hit the base URL
            health_url = self._base_url.rsplit("/", 1)[0] + "/health"

        try:
            resp = await client.get(health_url, timeout=10.0)
            return resp.status_code == 200
        except httpx.HTTPError as e:
            raise MeetingTranscriptStoreError(
                f"OCR Provenance health check failed at {health_url}: {e}"
            ) from e

    async def close(self) -> None:
        """Close the HTTP client and release all connections.

        Must be called on shutdown to prevent connection leaks.
        """
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.info("OcrProvenanceClient closed (session=%s)", self._session_id)
