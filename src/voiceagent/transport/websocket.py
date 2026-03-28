"""WebSocket transport for bidirectional audio and control messages."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import numpy as np

from voiceagent.errors import TransportError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class WebSocketTransport:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        try:
            import websockets  # noqa: F401
        except ImportError as err:
            raise ImportError(
                "websockets is required. Install with: pip install websockets"
            ) from err
        self.host = host
        self.port = port
        self._ws = None
        self._server = None

    async def start(
        self,
        on_audio: Callable[[np.ndarray], Awaitable[None]],
        on_control: Callable[[dict], Awaitable[None]],
    ) -> None:
        import websockets
        try:
            self._server = await websockets.serve(
                lambda ws: self._handle(ws, on_audio, on_control),
                self.host, self.port,
            )
            logger.info("WebSocket server listening on ws://%s:%d", self.host, self.port)
            await asyncio.Future()
        except OSError as e:
            raise TransportError(
                f"Failed to start on {self.host}:{self.port}: {e}. "
                f"Fix: check if port {self.port} is in use."
            ) from e

    async def _handle(
        self,
        ws: object,
        on_audio: Callable[[np.ndarray], Awaitable[None]],
        on_control: Callable[[dict], Awaitable[None]],
    ) -> None:
        self._ws = ws
        remote = ws.remote_address
        logger.info("Client connected: %s", remote)
        try:
            async for message in ws:
                if isinstance(message, bytes):
                    if not message:
                        continue
                    # Truncate to even length for int16 alignment
                    if len(message) % 2 != 0:
                        message = message[:-1]
                    audio = np.frombuffer(message, dtype=np.int16)
                    await on_audio(audio)
                else:
                    try:
                        data = json.loads(message)
                        await on_control(data)
                    except json.JSONDecodeError as e:
                        logger.error("Malformed JSON from %s: %s", remote, e)
        except Exception as e:
            logger.info("Client disconnected: %s (%s)", remote, type(e).__name__)
        finally:
            if self._ws is ws:
                self._ws = None

    async def send_audio(self, audio: np.ndarray) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(audio.astype(np.int16).tobytes())
        except Exception as e:
            logger.warning("Failed to send audio: %s", e)

    async def send_event(self, event: dict) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(event))
        except Exception as e:
            logger.warning("Failed to send event: %s", e)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("WebSocket server stopped")
