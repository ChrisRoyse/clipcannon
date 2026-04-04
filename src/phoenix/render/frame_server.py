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
            ws.onopen = () => { wsConnected = true; console.log('[AvatarCam] WebSocket connected'); };
            ws.onmessage = (evt) => {
                if (typeof evt.data === 'string') {
                    const [w, h] = evt.data.split('x').map(Number);
                    frameWidth = w; frameHeight = h;
                    console.log('[AvatarCam] Resolution:', w, 'x', h);
                } else {
                    latestFrame = new Uint8ClampedArray(evt.data);
                }
            };
            ws.onclose = () => {
                wsConnected = false;
                setTimeout(connectWS, 2000);
            };
            ws.onerror = () => { ws.close(); };
        } catch(e) {
            setTimeout(connectWS, 2000);
        }
    }
    connectWS();

    // Monkey-patch getUserMedia BEFORE Google Meet loads
    const origGUM = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);

    navigator.mediaDevices.getUserMedia = async function(constraints) {
        if (!constraints || !constraints.video) {
            return origGUM(constraints);
        }

        console.log('[AvatarCam] Intercepting getUserMedia for video');

        // Create MediaStreamTrackGenerator for video
        const generator = new MediaStreamTrackGenerator({ kind: 'video' });
        const writer = generator.writable.getWriter();

        // Frame pump: WebSocket data → VideoFrame → generator
        (async function pumpFrames() {
            while (true) {
                if (latestFrame && latestFrame.length === frameWidth * frameHeight * 4) {
                    try {
                        const imageData = new ImageData(
                            new Uint8ClampedArray(latestFrame), frameWidth, frameHeight
                        );
                        const bitmap = await createImageBitmap(imageData);
                        const vf = new VideoFrame(bitmap, {
                            timestamp: performance.now() * 1000
                        });
                        await writer.write(vf);
                        vf.close();
                        bitmap.close();
                    } catch(e) { /* skip frame */ }
                }
                await new Promise(r => setTimeout(r, 40));  // ~25fps
            }
        })();

        // Build stream with our video track
        const stream = new MediaStream([generator]);

        // If audio requested, get it from fake device or AudioContext
        if (constraints.audio) {
            try {
                // Try getting audio from the original getUserMedia
                const audioStream = await origGUM({ audio: constraints.audio });
                for (const t of audioStream.getAudioTracks()) {
                    stream.addTrack(t);
                }
            } catch(e) {
                console.log('[AvatarCam] No audio device, using AudioContext');
                const ctx = new AudioContext({ sampleRate: 48000 });
                const dest = ctx.createMediaStreamDestination();
                stream.addTrack(dest.stream.getAudioTracks()[0]);
                // Store for later audio injection
                window.__santaAudioCtx = ctx;
                window.__santaAudioDest = dest;
            }
        }

        console.log('[AvatarCam] Returning synthetic stream:', stream.getTracks().length, 'tracks');
        return stream;
    };

    // Ensure at least one videoinput in device enumeration
    const origEnum = navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices);
    navigator.mediaDevices.enumerateDevices = async function() {
        const devices = await origEnum();
        if (!devices.some(d => d.kind === 'videoinput')) {
            devices.push({
                deviceId: 'avatar-cam', kind: 'videoinput',
                label: 'Avatar Camera', groupId: 'virtual',
                toJSON: () => ({})
            });
        }
        return devices;
    };

    // Audio playback function (same as before)
    window.__santaPlayAudio = function(b64Data, sampleRate) {
        const ctx = window.__santaAudioCtx;
        const dest = window.__santaAudioDest;
        if (!ctx || !dest) return Promise.resolve(false);
        return ctx.resume().then(() => {
            return new Promise((resolve, reject) => {
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
            });
        });
    };

    console.log('[AvatarCam] getUserMedia hooked + WebSocket frame bridge active');
})();
"""
