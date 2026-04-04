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


# The JavaScript init script for Chrome
# NOTE: This is the WebSocket-based version for reference. The active
# implementation in santa_meet_bot.py uses a different approach:
# page.evaluate() to set window.__santaJpegB64 (no WebSocket needed).
#
# IMPORTANT: Both approaches now use the Insertable Streams technique:
# 1. Call original getUserMedia to get fake-device track (has real metadata)
# 2. Use MediaStreamTrackProcessor to read fake-device frames
# 3. Replace each frame with our rendered content
# 4. Output via MediaStreamTrackGenerator (inherits real track metadata)
# 5. Google Meet sees proper getSettings()/getCapabilities() → accepts video
#
# The old approach of creating a raw MediaStreamTrackGenerator FAILS because
# Meet checks track metadata and silently disables tracks without proper
# camera settings (width, height, deviceId, facingMode, etc).
CHROME_INIT_SCRIPT = """
(function() {
    const FRAME_WS = 'ws://localhost:9876';
    let frameWidth = 640, frameHeight = 480;
    let latestFrame = null;
    let wsConnected = false;

    function connectWS() {
        try {
            const ws = new WebSocket(FRAME_WS);
            ws.binaryType = 'arraybuffer';
            ws.onopen = () => { wsConnected = true; console.log('[AvatarCam] WS connected'); };
            ws.onmessage = (evt) => {
                if (typeof evt.data === 'string') {
                    const [w, h] = evt.data.split('x').map(Number);
                    frameWidth = w; frameHeight = h;
                } else {
                    latestFrame = new Uint8ClampedArray(evt.data);
                }
            };
            ws.onclose = () => { wsConnected = false; setTimeout(connectWS, 2000); };
            ws.onerror = () => { ws.close(); };
        } catch(e) { setTimeout(connectWS, 2000); }
    }
    connectWS();

    const origGUM = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);

    navigator.mediaDevices.getUserMedia = async function(constraints) {
        if (!constraints || !constraints.video) return origGUM(constraints);

        // Get real fake-device track for metadata
        const realStream = await origGUM({video: constraints.video});
        const realTrack = realStream.getVideoTracks()[0];
        const realSettings = realTrack.getSettings();
        const realCaps = realTrack.getCapabilities ? realTrack.getCapabilities() : {};

        // Insertable Streams: process real track, replace frames with ours
        const proc = new MediaStreamTrackProcessor({track: realTrack});
        const gen = new MediaStreamTrackGenerator({kind: 'video'});
        const reader = proc.readable.getReader();
        const writer = gen.writable.getWriter();
        const oc = new OffscreenCanvas(frameWidth, frameHeight);
        const ox = oc.getContext('2d');

        (async function pump() {
            while (true) {
                const {value: frame, done} = await reader.read();
                if (done) break;
                frame.close();
                if (latestFrame && latestFrame.length === frameWidth * frameHeight * 4) {
                    try {
                        const id = new ImageData(new Uint8ClampedArray(latestFrame), frameWidth, frameHeight);
                        const bmp = await createImageBitmap(id);
                        ox.drawImage(bmp, 0, 0);
                        bmp.close();
                    } catch(e) {}
                }
                const bmp = oc.transferToImageBitmap();
                const vf = new VideoFrame(bmp, {timestamp: performance.now() * 1000});
                try { await writer.write(vf); } catch(e) { vf.close(); break; }
                vf.close();
            }
        })();

        // Spoof metadata
        const origGS = gen.getSettings.bind(gen);
        gen.getSettings = () => ({...origGS(), ...realSettings});
        if (gen.getCapabilities) gen.getCapabilities = () => realCaps;

        const stream = new MediaStream([gen]);
        if (constraints.audio) {
            try {
                const aStream = await origGUM({audio: constraints.audio});
                for (const t of aStream.getAudioTracks()) stream.addTrack(t);
            } catch(e) {
                const ctx = new AudioContext({sampleRate: 48000});
                const dest = ctx.createMediaStreamDestination();
                stream.addTrack(dest.stream.getAudioTracks()[0]);
                window.__santaAudioCtx = ctx;
                window.__santaAudioDest = dest;
            }
        }
        return stream;
    };

    window.__santaPlayAudio = function(b64Data, sampleRate) {
        const ctx = window.__santaAudioCtx;
        const dest = window.__santaAudioDest;
        if (!ctx || !dest) return Promise.resolve(false);
        return ctx.resume().then(() => new Promise((resolve, reject) => {
            try {
                const binary = atob(b64Data);
                const bytes = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
                const float32 = new Float32Array(bytes.buffer);
                const buffer = ctx.createBuffer(1, float32.length, sampleRate);
                buffer.copyToChannel(float32, 0);
                const source = ctx.createBufferSource();
                source.buffer = buffer;
                const gain = ctx.createGain();
                gain.gain.value = 3.0;
                source.connect(gain);
                gain.connect(dest);
                source.onended = () => resolve(true);
                source.start();
            } catch(e) { reject(e.message); }
        }));
    };

    console.log('[AvatarCam] Insertable Streams + WebSocket bridge active');
})();
"""
