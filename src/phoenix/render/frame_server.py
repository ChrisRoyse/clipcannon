"""WebSocket frame server for real-time avatar video delivery.

Streams rendered avatar frames to Chrome via WebSocket. Chrome's
getUserMedia is intercepted to use MediaStreamTrackGenerator fed
by these frames. Google Meet sees a legitimate camera track.

Usage:
    server = FrameServer(port=9876)
    await server.start()
    # Push frames from avatar renderer:
    server.push_frame(bgr_numpy_array)
    # Chrome connects via ws://localhost:9876
"""
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Set

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# WebSocket server - use the built-in asyncio approach
try:
    import websockets
    import websockets.server
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


class FrameServer:
    """WebSocket server that broadcasts rendered frames to Chrome.

    Args:
        port: WebSocket server port.
        width: Frame width.
        height: Frame height.
    """

    def __init__(self, port: int = 9876, width: int = 640, height: int = 480) -> None:
        self._port = port
        self._width = width
        self._height = height
        self._clients: Set = set()
        self._current_frame: bytes | None = None
        self._server = None
        self._running = False

    async def start(self) -> None:
        """Start the WebSocket server."""
        if not HAS_WEBSOCKETS:
            logger.error("websockets package not installed: pip install websockets")
            return
        self._running = True
        self._server = await websockets.serve(
            self._handler, "localhost", self._port,
            max_size=10 * 1024 * 1024,  # 10MB max message
        )
        logger.info("Frame server started on ws://localhost:%d (%dx%d)",
                     self._port, self._width, self._height)

    async def stop(self) -> None:
        """Stop the server."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def push_frame(self, bgr_frame: np.ndarray) -> None:
        """Push a new BGR frame to all connected clients.

        Called by the avatar renderer at frame rate. Converts
        BGR to RGBA bytes for Chrome's VideoFrame API.
        """
        # Resize if needed
        h, w = bgr_frame.shape[:2]
        if w != self._width or h != self._height:
            bgr_frame = cv2.resize(bgr_frame, (self._width, self._height))

        # BGR → RGBA (Chrome's VideoFrame expects RGBA)
        rgba = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGBA)
        self._current_frame = rgba.tobytes()

    async def _handler(self, ws) -> None:
        """Handle a WebSocket client connection."""
        self._clients.add(ws)
        logger.info("Chrome connected to frame server")
        try:
            # Send resolution as first message
            await ws.send(f"{self._width}x{self._height}")
            # Broadcast frames until disconnected
            while self._running:
                if self._current_frame:
                    try:
                        await ws.send(self._current_frame)
                    except Exception:
                        break
                await asyncio.sleep(1.0 / 25)  # 25fps cap
        finally:
            self._clients.discard(ws)
            logger.info("Chrome disconnected from frame server")


# NOTE: The Chrome init script for getUserMedia interception is in
# santa_meet_bot.py (the active implementation). The WebSocket-based
# approach here is no longer used. The live system uses page.evaluate()
# to set window.__santaJpegB64 with Insertable Streams for frame injection.
