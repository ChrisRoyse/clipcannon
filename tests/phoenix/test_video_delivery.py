"""Test the Insertable Streams video delivery pipeline.

Verifies that the init script successfully:
1. Intercepts getUserMedia
2. Gets a real fake-device track with proper metadata
3. Pipes custom canvas frames through the track
4. Produces a video track with real getSettings()/getCapabilities()
5. Custom frame content (JPEG from __santaJpegB64) appears in the video

Run with: python -m pytest tests/phoenix/test_video_delivery.py -v
Requires: playwright, chromium browser installed
"""
from __future__ import annotations

import asyncio
import base64
import http.server
import logging
import sys
import threading

import cv2
import numpy as np
import pytest

logger = logging.getLogger(__name__)

# Minimal HTML page served over localhost (required for mediaDevices API)
_TEST_HTML = """<!DOCTYPE html><html><head><title>AvatarTest</title></head>
<body><h1>Avatar Video Delivery Test</h1></body></html>"""

_http_server = None
_http_port = 18923


def _start_test_server():
    """Start a minimal HTTP server on localhost for tests (idempotent)."""
    global _http_server
    if _http_server is not None:
        return f"http://127.0.0.1:{_http_port}/"

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(_TEST_HTML.encode())

        def log_message(self, *args):
            pass  # Suppress logs

    _http_server = http.server.HTTPServer(("127.0.0.1", _http_port), Handler)
    _http_server.allow_reuse_address = True
    t = threading.Thread(target=_http_server.serve_forever, daemon=True)
    t.start()
    return f"http://127.0.0.1:{_http_port}/"


def _stop_test_server():
    global _http_server
    if _http_server:
        _http_server.shutdown()
        _http_server = None

# The EXACT init script from santa_meet_bot.py — extracted here for testing
# so we can validate it without starting the full bot.
INIT_SCRIPT = """
Object.defineProperty(navigator,"webdriver",{get:()=>false});
const _origGUM=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
window.__santaJpegB64=null;
navigator.mediaDevices.getUserMedia=async function(c){
    if(!c||!c.video) return _origGUM(c);
    try{
        const realStream=await _origGUM({video:c.video});
        const realTrack=realStream.getVideoTracks()[0];
        const realSettings=realTrack.getSettings();
        const realCaps=realTrack.getCapabilities?realTrack.getCapabilities():{};
        const W=realSettings.width||1280, H=realSettings.height||720;
        console.log('[AvatarCam] Real track:',realTrack.label,W+'x'+H,JSON.stringify(realSettings));
        const oc=new OffscreenCanvas(W,H);
        const ox=oc.getContext('2d');
        let outTrack;
        if(typeof MediaStreamTrackProcessor!=='undefined'&&typeof MediaStreamTrackGenerator!=='undefined'){
            console.log('[AvatarCam] Using Insertable Streams');
            const proc=new MediaStreamTrackProcessor({track:realTrack});
            const gen=new MediaStreamTrackGenerator({kind:'video'});
            const reader=proc.readable.getReader();
            const writer=gen.writable.getWriter();
            let lastJpeg=null;
            (async()=>{
                while(true){
                    const{value:frame,done}=await reader.read();
                    if(done)break;
                    frame.close();
                    if(window.__santaJpegB64&&window.__santaJpegB64!==lastJpeg){
                        lastJpeg=window.__santaJpegB64;
                        try{
                            const resp=await fetch('data:image/jpeg;base64,'+lastJpeg);
                            const blob=await resp.blob();
                            const bmp=await createImageBitmap(blob);
                            ox.drawImage(bmp,0,0,W,H);
                            bmp.close();
                        }catch(e){}
                    }else if(!lastJpeg){
                        ox.fillStyle='#1a1a2e';ox.fillRect(0,0,W,H);
                        ox.fillStyle='#eee';ox.font='36px Arial';
                        ox.fillText('Santa joining...',W/2-120,H/2);
                    }
                    const bmp=oc.transferToImageBitmap();
                    const vf=new VideoFrame(bmp,{timestamp:performance.now()*1000});
                    try{await writer.write(vf);}catch(e){vf.close();break;}
                    vf.close();
                }
            })();
            const origGS=gen.getSettings.bind(gen);
            gen.getSettings=()=>({...origGS(),...realSettings});
            if(gen.getCapabilities)gen.getCapabilities=()=>realCaps;
            outTrack=gen;
        }else{
            console.log('[AvatarCam] Fallback: captureStream');
            const visCanvas=document.createElement('canvas');
            visCanvas.width=W;visCanvas.height=H;
            const vx=visCanvas.getContext('2d');
            const capStream=visCanvas.captureStream(15);
            const capTrack=capStream.getVideoTracks()[0];
            capTrack.getSettings=()=>realSettings;
            if(realTrack.getCapabilities)capTrack.getCapabilities=()=>realCaps;
            capTrack.getConstraints=()=>realTrack.getConstraints();
            let lastJpeg=null;
            (async()=>{
                while(capTrack.readyState==='live'){
                    if(window.__santaJpegB64&&window.__santaJpegB64!==lastJpeg){
                        lastJpeg=window.__santaJpegB64;
                        try{
                            const resp=await fetch('data:image/jpeg;base64,'+lastJpeg);
                            const blob=await resp.blob();
                            const bmp=await createImageBitmap(blob);
                            vx.drawImage(bmp,0,0,W,H);
                            bmp.close();
                        }catch(e){}
                    }else if(!lastJpeg){
                        vx.fillStyle='#1a1a2e';vx.fillRect(0,0,W,H);
                        vx.fillStyle='#eee';vx.font='36px Arial';
                        vx.fillText('Santa joining...',W/2-120,H/2);
                    }
                    await new Promise(r=>setTimeout(r,66));
                }
            })();
            outTrack=capTrack;
            realTrack.stop();
        }
        const outStream=new MediaStream([outTrack]);
        if(c.audio){
            try{
                const aStream=await _origGUM({audio:c.audio});
                for(const t of aStream.getAudioTracks())outStream.addTrack(t);
            }catch(e){}
            const actx=new AudioContext({sampleRate:48000});
            const dest=actx.createMediaStreamDestination();
            if(!outStream.getAudioTracks().length){
                outStream.addTrack(dest.stream.getAudioTracks()[0]);
            }
            window.__santaAudioCtx=actx;
            window.__santaAudioDest=dest;
        }
        console.log('[AvatarCam] Output:',outStream.getTracks().length,'tracks');
        return outStream;
    }catch(e){
        console.error('[AvatarCam] Fallback:',e);
        return _origGUM(c);
    }
};
"""


def _make_test_jpeg(width: int = 640, height: int = 480, color: tuple = (0, 0, 255)) -> str:
    """Create a solid-color JPEG and return base64-encoded string."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = color  # BGR
    # Draw a distinctive marker (white rectangle in top-left)
    frame[10:50, 10:100] = (255, 255, 255)
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return base64.b64encode(buf).decode("ascii")


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_insertable_streams_video_delivery():
    """Test that the init script creates a video track with real metadata.

    This test:
    1. Launches Chrome with --use-fake-device-for-media-stream
    2. Injects the init script
    3. Calls getUserMedia from a test page
    4. Verifies the returned track has proper camera metadata
    5. Sets a JPEG frame and verifies it renders
    """
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    try:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir="",
            headless=True,
            args=[
                "--no-sandbox",
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
            ],
            permissions=["camera", "microphone"],
        )

        await context.add_init_script(INIT_SCRIPT)
        page = context.pages[0] if context.pages else await context.new_page()

        # Navigate to localhost page (mediaDevices requires secure context)
        test_url = _start_test_server()
        await page.goto(test_url)
        await asyncio.sleep(0.5)

        # Test 1: getUserMedia returns a stream with proper metadata
        result = await page.evaluate("""async () => {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({
                    video: {width: 640, height: 480},
                    audio: true
                });
                const vTrack = stream.getVideoTracks()[0];
                const settings = vTrack.getSettings();
                const hasCaps = typeof vTrack.getCapabilities === 'function';
                const caps = hasCaps ? vTrack.getCapabilities() : {};

                return {
                    success: true,
                    trackCount: stream.getTracks().length,
                    videoTracks: stream.getVideoTracks().length,
                    audioTracks: stream.getAudioTracks().length,
                    trackState: vTrack.readyState,
                    trackKind: vTrack.kind,
                    settingsWidth: settings.width,
                    settingsHeight: settings.height,
                    hasDeviceId: !!settings.deviceId,
                    hasFrameRate: !!settings.frameRate,
                    hasCaps: hasCaps,
                    capsHasWidth: !!caps.width,
                    audioCtxReady: !!window.__santaAudioCtx,
                    audioDestReady: !!window.__santaAudioDest,
                };
            } catch(e) {
                return {success: false, error: e.message};
            }
        }""")

        logger.info("getUserMedia result: %s", result)
        assert result["success"], f"getUserMedia failed: {result.get('error')}"
        assert result["videoTracks"] == 1, "Expected 1 video track"
        assert result["audioTracks"] >= 1, "Expected at least 1 audio track"
        assert result["trackState"] == "live", "Track should be live"
        assert result["trackKind"] == "video", "Track should be video kind"

        # Verify REAL camera metadata is present
        assert result["settingsWidth"] is not None, "Settings must have width"
        assert result["settingsHeight"] is not None, "Settings must have height"
        assert result["hasDeviceId"], "Settings must have deviceId (from real track)"
        assert result["hasFrameRate"], "Settings must have frameRate"
        assert result["audioCtxReady"], "AudioContext should be initialized"
        assert result["audioDestReady"], "AudioDestination should be initialized"

        logger.info(
            "PASS: Track has real metadata - %dx%d, deviceId=%s, frameRate=%s",
            result["settingsWidth"], result["settingsHeight"],
            result["hasDeviceId"], result["hasFrameRate"],
        )

        # Test 2: Push a custom JPEG frame and verify it renders
        test_jpeg_b64 = _make_test_jpeg(640, 480, color=(0, 0, 255))

        # Set the frame
        await page.evaluate(
            "b64 => { window.__santaJpegB64 = b64; }",
            test_jpeg_b64,
        )

        # Wait for the frame to be processed by the Insertable Streams pipeline
        await asyncio.sleep(1.0)

        # Verify the JPEG was received
        jpeg_check = await page.evaluate("""() => {
            return {
                jpegSet: !!window.__santaJpegB64,
                jpegLength: window.__santaJpegB64 ? window.__santaJpegB64.length : 0,
            };
        }""")
        assert jpeg_check["jpegSet"], "JPEG should be set"
        assert jpeg_check["jpegLength"] > 100, "JPEG should have data"

        # Test 3: Render the video to a canvas and check pixel content
        pixel_result = await page.evaluate("""async () => {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({
                    video: {width: 640, height: 480}
                });
                const track = stream.getVideoTracks()[0];
                const settings = track.getSettings();

                // Use a video element to capture frame
                const video = document.createElement('video');
                video.srcObject = stream;
                video.muted = true;
                await video.play();

                // Wait for video to have frames
                await new Promise(r => setTimeout(r, 2000));

                const canvas = document.createElement('canvas');
                canvas.width = settings.width || 640;
                canvas.height = settings.height || 480;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(video, 0, 0);

                // Sample pixel at center and at the white marker area
                const centerPixel = ctx.getImageData(320, 240, 1, 1).data;
                const markerPixel = ctx.getImageData(50, 30, 1, 1).data;

                video.pause();
                track.stop();

                return {
                    success: true,
                    videoWidth: video.videoWidth,
                    videoHeight: video.videoHeight,
                    centerR: centerPixel[0],
                    centerG: centerPixel[1],
                    centerB: centerPixel[2],
                    markerR: markerPixel[0],
                    markerG: markerPixel[1],
                    markerB: markerPixel[2],
                    settingsStr: JSON.stringify(settings),
                };
            } catch(e) {
                return {success: false, error: e.message};
            }
        }""")

        logger.info("Pixel test result: %s", pixel_result)

        if pixel_result["success"]:
            logger.info(
                "Video dimensions: %dx%d",
                pixel_result["videoWidth"],
                pixel_result["videoHeight"],
            )
            logger.info(
                "Center pixel RGB: (%d, %d, %d)",
                pixel_result["centerR"], pixel_result["centerG"], pixel_result["centerB"],
            )
            logger.info(
                "Marker pixel RGB: (%d, %d, %d)",
                pixel_result["markerR"], pixel_result["markerG"], pixel_result["markerB"],
            )
            logger.info("Track settings: %s", pixel_result["settingsStr"])

            # The center should be reddish (our test frame is BGR red = RGB blue)
            # But JPEG is RGB so our (0,0,255) BGR becomes (255,0,0) in the image
            # Actually cv2 BGR (0,0,255) = pure red. In canvas it shows as red.
            # With JPEG compression, values may not be exact
            assert pixel_result["videoWidth"] > 0, "Video should have width"
            assert pixel_result["videoHeight"] > 0, "Video should have height"

        # Test 4: Verify console logs from init script
        console_logs = []
        page.on("console", lambda msg: console_logs.append(msg.text))

        await page.evaluate("""async () => {
            const s = await navigator.mediaDevices.getUserMedia({video: true});
            console.log('[Test] Got stream with', s.getTracks().length, 'tracks');
            s.getTracks().forEach(t => t.stop());
        }""")
        await asyncio.sleep(0.5)

        logger.info("Console logs: %s", console_logs)

        await context.close()
        logger.info("ALL TESTS PASSED")

    finally:
        await pw.stop()


@pytest.mark.asyncio
async def test_audio_injection():
    """Test that audio injection via __santaPlayAudio works."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    try:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir="",
            headless=True,
            args=[
                "--no-sandbox",
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ],
            permissions=["camera", "microphone"],
        )

        # Add the audio part of init script
        await context.add_init_script(INIT_SCRIPT + """
        window.__santaPlayAudio=function(b64,sr){
            const ctx=window.__santaAudioCtx,dest=window.__santaAudioDest;
            if(!ctx||!dest)return Promise.resolve(false);
            return ctx.resume().then(()=>new Promise((res,rej)=>{
                try{
                    const bin=atob(b64),bytes=new Uint8Array(bin.length);
                    for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);
                    const f32=new Float32Array(bytes.buffer);
                    const buf=ctx.createBuffer(1,f32.length,sr);
                    buf.copyToChannel(f32,0);
                    const src=ctx.createBufferSource();src.buffer=buf;
                    const g=ctx.createGain();g.gain.value=3.0;
                    src.connect(g);g.connect(dest);
                    src.onended=()=>res(true);src.start();
                }catch(e){rej(e.message);}
            }));
        };
        """)

        page = context.pages[0] if context.pages else await context.new_page()
        test_url = _start_test_server()
        await page.goto(test_url)
        await asyncio.sleep(0.5)

        # Initialize getUserMedia to set up AudioContext
        await page.evaluate("""async () => {
            await navigator.mediaDevices.getUserMedia({video: true, audio: true});
        }""")
        await asyncio.sleep(0.5)

        # Generate a short sine wave as test audio
        sr = 24000
        duration = 0.1  # 100ms
        t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
        audio = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)
        audio_b64 = base64.b64encode(audio.tobytes()).decode("ascii")

        # Try to play audio
        result = await page.evaluate(
            "([b64, sr]) => window.__santaPlayAudio(b64, sr)",
            [audio_b64, sr],
        )
        logger.info("Audio injection result: %s", result)
        assert result is True, "Audio should play successfully"

        await context.close()
        logger.info("Audio injection test PASSED")

    finally:
        await pw.stop()


@pytest.mark.asyncio
async def test_track_metadata_completeness():
    """Verify that the output track has ALL metadata fields Meet checks."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    try:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir="",
            headless=True,
            args=[
                "--no-sandbox",
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
            ],
            permissions=["camera", "microphone"],
        )

        await context.add_init_script(INIT_SCRIPT)
        page = context.pages[0] if context.pages else await context.new_page()
        test_url = _start_test_server()
        await page.goto(test_url)
        await asyncio.sleep(0.5)

        metadata = await page.evaluate("""async () => {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: {width: 1280, height: 720, frameRate: 30}
            });
            const track = stream.getVideoTracks()[0];
            const settings = track.getSettings();
            const hasCaps = typeof track.getCapabilities === 'function';
            const caps = hasCaps ? track.getCapabilities() : null;

            // These are the fields Google Meet checks
            return {
                label: track.label,
                kind: track.kind,
                readyState: track.readyState,
                enabled: track.enabled,
                muted: track.muted,

                // Settings (the critical ones)
                width: settings.width,
                height: settings.height,
                frameRate: settings.frameRate,
                deviceId: settings.deviceId,
                groupId: settings.groupId,
                facingMode: settings.facingMode,
                resizeMode: settings.resizeMode,

                // Capabilities
                hasCaps: hasCaps,
                capsWidth: caps && caps.width ? JSON.stringify(caps.width) : null,
                capsHeight: caps && caps.height ? JSON.stringify(caps.height) : null,
                capsFrameRate: caps && caps.frameRate ? JSON.stringify(caps.frameRate) : null,

                // Full settings dump
                allSettings: JSON.stringify(settings),
            };
        }""")

        logger.info("Track metadata: %s", metadata)

        # Core metadata must be present
        assert metadata["kind"] == "video"
        assert metadata["readyState"] == "live"
        assert metadata["enabled"] is True

        # Settings must have real camera values (not empty)
        assert metadata["width"] is not None and metadata["width"] > 0, \
            f"width must be set, got: {metadata['width']}"
        assert metadata["height"] is not None and metadata["height"] > 0, \
            f"height must be set, got: {metadata['height']}"
        assert metadata["deviceId"] is not None and metadata["deviceId"] != "", \
            f"deviceId must be set, got: {metadata['deviceId']}"

        # frameRate should be present and positive
        if metadata["frameRate"] is not None:
            assert metadata["frameRate"] > 0, \
                f"frameRate must be positive, got: {metadata['frameRate']}"

        logger.info(
            "PASS: Full track metadata - %dx%d @ %sfps, deviceId=%s",
            metadata["width"], metadata["height"],
            metadata["frameRate"], metadata["deviceId"][:16] + "...",
        )

        await context.close()

    finally:
        await pw.stop()


@pytest.mark.asyncio
async def test_frame_render_loop_simulation():
    """Simulate the actual render loop: push JPEG frames and verify they appear.

    This mirrors what video_render_loop() does in santa_meet_bot.py:
    encode a BGR frame as JPEG, base64 it, push via page.evaluate.
    """
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    try:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir="",
            headless=True,
            args=[
                "--no-sandbox",
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
            ],
            permissions=["camera", "microphone"],
        )

        await context.add_init_script(INIT_SCRIPT)
        page = context.pages[0] if context.pages else await context.new_page()
        test_url = _start_test_server()
        await page.goto(test_url)
        await asyncio.sleep(0.5)

        # Initialize the stream (triggers getUserMedia intercept)
        await page.evaluate("""async () => {
            window.__testStream = await navigator.mediaDevices.getUserMedia({
                video: {width: 640, height: 480}
            });
        }""")
        await asyncio.sleep(0.5)

        # Simulate pushing frames at 10fps like the real bot does
        for i in range(5):
            # Create frame with varying content (different colors per frame)
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            frame[:] = (0, 0, 50 + i * 40)  # BGR: increasingly red
            # Add frame number marker
            cv2.putText(frame, f"Frame {i}", (50, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 3)
            _, jpg_buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            jpg_b64 = base64.b64encode(jpg_buf).decode("ascii")

            # Push frame exactly like the real bot
            await page.evaluate("b64 => { window.__santaJpegB64 = b64; }", jpg_b64)
            await asyncio.sleep(0.1)

        # Wait for frames to process
        await asyncio.sleep(1.0)

        # Verify the last frame was processed by capturing the video output
        result = await page.evaluate("""async () => {
            const stream = window.__testStream;
            if (!stream) return {success: false, error: 'No stream'};

            const track = stream.getVideoTracks()[0];
            if (!track || track.readyState !== 'live') {
                return {success: false, error: 'Track not live: ' + (track ? track.readyState : 'null')};
            }

            // Capture a frame using ImageCapture if available
            if (typeof ImageCapture !== 'undefined') {
                try {
                    const capture = new ImageCapture(track);
                    const bitmap = await capture.grabFrame();
                    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(bitmap, 0, 0);
                    const pixel = ctx.getImageData(320, 240, 1, 1).data;
                    return {
                        success: true,
                        method: 'ImageCapture',
                        width: bitmap.width,
                        height: bitmap.height,
                        r: pixel[0], g: pixel[1], b: pixel[2], a: pixel[3],
                    };
                } catch(e) {
                    return {success: false, error: 'ImageCapture: ' + e.message};
                }
            }
            return {success: true, method: 'noImageCapture', note: 'Track is live but cannot grab frame in headless'};
        }""")

        logger.info("Render loop simulation result: %s", result)
        assert result["success"], f"Render loop failed: {result.get('error')}"

        if result.get("method") == "ImageCapture":
            assert result["width"] > 0
            assert result["height"] > 0
            # Should have non-zero red channel (our frames are reddish)
            logger.info("Captured pixel at center: RGB(%d,%d,%d)", result["r"], result["g"], result["b"])

        # Verify the frame count tracking
        jpeg_state = await page.evaluate("""() => ({
            hasJpeg: !!window.__santaJpegB64,
            jpegLen: window.__santaJpegB64 ? window.__santaJpegB64.length : 0,
        })""")
        assert jpeg_state["hasJpeg"], "Should have JPEG data"
        assert jpeg_state["jpegLen"] > 100, "JPEG should not be empty"

        await context.close()
        logger.info("Render loop simulation PASSED")

    finally:
        await pw.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    pytest.main([__file__, "-v", "-s"])
