"""OCR Provenance MCP HTTP client for meeting transcript storage.

Sends JSON-RPC tool calls to the OCR Provenance session proxy (port 3377).
Performs the MCP initialize handshake on first call, uses the server-assigned
session ID for all subsequent calls.

The session proxy returns SSE (Server-Sent Events) format responses:
    event: message
    data: {"jsonrpc": "2.0", "result": {...}, "id": 1}

This client parses the SSE `data:` line to extract the JSON-RPC payload.
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


def _parse_sse_response(text: str) -> dict[str, Any]:
    """Parse SSE (Server-Sent Events) response body to extract JSON-RPC data.

    The OCR Provenance session proxy returns responses as:
        event: message
        data: {"jsonrpc": "2.0", "result": {...}, "id": 1}

    Args:
        text: Raw response body text.

    Returns:
        Parsed JSON dict from the data line.

    Raises:
        MeetingTranscriptStoreError: If no valid JSON data found.
    """
    # Try direct JSON first (in case response is plain JSON)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Parse SSE format — find the data: line
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            json_str = line[5:].strip()
            if json_str:
                try:
                    return json.loads(json_str)
                except (json.JSONDecodeError, ValueError):
                    continue

    raise MeetingTranscriptStoreError(
        f"No valid JSON found in SSE response: {text[:300]}"
    )


class OcrProvenanceClient:
    """HTTP JSON-RPC client for OCR Provenance MCP server.

    Automatically performs the MCP initialize/initialized handshake
    on the first tool call and uses the server-assigned session ID.

    Args:
        base_url: URL of the OCR Provenance session proxy endpoint.
    """

    def __init__(self, base_url: str = DEFAULT_URL) -> None:
        self._base_url = base_url.rstrip("/")
        self._session_id: str = f"clone-meeting-{uuid.uuid4().hex[:12]}"
        self._request_id = 0
        self._client: httpx.AsyncClient | None = None
        self._initialized = False
        logger.info("OcrProvenanceClient created: url=%s", self._base_url)

    @property
    def session_id(self) -> str:
        """The MCP session ID (server-assigned after init)."""
        return self._session_id

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx async client."""
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

    def _headers(self) -> dict[str, str]:
        """Standard headers for all MCP requests."""
        return {
            "Content-Type": "application/json",
            "Mcp-Session-Id": self._session_id,
        }

    async def _ensure_initialized(self) -> None:
        """Perform MCP initialize handshake if not yet done.

        Sends initialize request, captures the server-assigned session ID,
        then sends notifications/initialized. Must complete before any
        tool calls.

        Raises:
            MeetingTranscriptStoreError: If handshake fails.
        """
        if self._initialized:
            return

        client = self._get_client()
        headers = self._headers()

        # Step 1: initialize
        init_payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {
                    "name": "clipcannon-meeting-clone",
                    "version": "1.0",
                },
            },
            "id": 1,
        }

        try:
            resp = await client.post(
                self._base_url, json=init_payload, headers=headers,
            )
        except httpx.HTTPError as e:
            raise MeetingTranscriptStoreError(
                f"MCP initialize handshake failed: {e}"
            ) from e

        if resp.status_code != 200:
            raise MeetingTranscriptStoreError(
                f"MCP initialize returned HTTP {resp.status_code}: "
                f"{resp.text[:300]}"
            )

        # Use server-assigned session ID for all subsequent calls
        server_session = resp.headers.get("mcp-session-id", "")
        if server_session:
            self._session_id = server_session
            logger.info("Server assigned session: %s", server_session)

        # Step 2: notifications/initialized
        notif_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        try:
            await client.post(
                self._base_url,
                json=notif_payload,
                headers=self._headers(),
            )
        except httpx.HTTPError:
            pass  # Notification responses are optional per MCP spec

        self._initialized = True
        self._request_id = 1
        logger.info("MCP session initialized: %s", self._session_id)

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call an OCR Provenance MCP tool via JSON-RPC over HTTP.

        Automatically performs the MCP initialize handshake on first call.
        Parses SSE response format.

        Args:
            tool_name: Name of the MCP tool (e.g., "ocr_db_create").
            arguments: Tool arguments as a dict.

        Returns:
            The tool result as a dict. Structure varies by tool.

        Raises:
            MeetingTranscriptStoreError: If the HTTP request fails,
                the server returns an error, or the response is malformed.
        """
        await self._ensure_initialized()

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

        client = self._get_client()

        try:
            response = await client.post(
                self._base_url, json=payload, headers=self._headers(),
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

        if response.status_code not in (200, 202):
            raise MeetingTranscriptStoreError(
                f"OCR Provenance returned HTTP {response.status_code} "
                f"for tool '{tool_name}': {response.text[:500]}"
            )

        # Parse SSE response format
        body = _parse_sse_response(response.text)

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
        health_url = self._base_url.replace("/mcp", "/health")
        if health_url == self._base_url:
            health_url = self._base_url.rsplit("/", 1)[0] + "/health"
        try:
            resp = await client.get(health_url, timeout=10.0)
            return resp.status_code == 200
        except httpx.HTTPError as e:
            raise MeetingTranscriptStoreError(
                f"OCR Provenance health check failed at {health_url}: {e}"
            ) from e

    async def close(self) -> None:
        """Close the HTTP client and release all connections."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            self._initialized = False
            logger.info(
                "OcrProvenanceClient closed (session=%s)", self._session_id,
            )
