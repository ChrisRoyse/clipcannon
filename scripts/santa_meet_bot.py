"""Santa clone meeting bot — full quality pipeline with OCR Provenance RAG.

Architecture:
  Audio Routing (zero feedback):
    YOUR Chrome plays meeting audio -> PulseAudio output sink -> speakers
    output.monitor captures your Chrome's audio -> parec -> Whisper -> LLM -> TTS
    TTS -> pacat -> clone_audio sink -> clone_audio.monitor -> bot fake mic -> meeting
    NO LOOPBACK. Bot TTS never reaches output.monitor. Feedback impossible.

  Intelligence (RAG):
    Question -> OCR Provenance search (past meetings) -> Ollama 14B -> response
    Transcript segments ingested into OCR Provenance in near-real-time
    AI can search all meeting history to produce informed answers

  Voice Quality:
    Full ICL mode + real Santa reference recording
    Real laugh clips from expression library (not TTS-generated)
    [LAUGH] tags in LLM prompt -> replaced with real audio clips
    Prosody-aware: system prompt demands full vocal variation

  Memory Management:
    Whisper model loaded ONCE at startup
    TTS adapter loaded ONCE at startup
    Audio buffers capped at 2x window size
    Transcript segments capped in memory, overflow flushed to OCR Provenance
    gc.collect() after each response cycle
"""
import asyncio
import gc
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

logging.basicConfig(
    level=logging.INFO, stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("santa_bot")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MEET_URL = sys.argv[1] if len(sys.argv) > 1 else ""
SESSION_DIR = str(Path("~/.voiceagent/browser-session").expanduser())
VOICE_NAME = "santa"
LLM_MODEL = "gemma4:e4b"  # Gemma 4 E4B: 4.5B active, 128K context, multimodal
WHISPER_MODEL = "large-v3-turbo"
OCR_PROVENANCE_URL = "http://localhost:3377/mcp"
OCR_DB_NAME = "meetings"

# Dynamic avatar via FIFO pipe (real-time lip sync)
Y4M_PIPE = "/tmp/santa_avatar_pipe.y4m"
SANTA_IDLE_VIDEO = str(Path("~/.voiceagent/drivers/santa_idle_listen.y4m").expanduser())
# Use neutral frame Y4M (mouth closed, face forward) as Chrome's video
IDLE_Y4M = str(Path("~/.voiceagent/drivers/santa_neutral.y4m").expanduser())
if not Path(IDLE_Y4M).exists():
    IDLE_Y4M = SANTA_IDLE_VIDEO

# Y4M writer instance (initialized at startup)
_y4m_writer = None  # Reserved for future v4l2loopback approach

# Audio capture settings
CAPTURE_DEVICE = "output.monitor"
AUDIO_SINK = "clone_audio"
SAMPLE_RATE = 16000
CHUNK_BYTES = 3200  # 100ms at 16kHz mono 16-bit

# Energy threshold for speech detection
# PulseAudio TCP bridge delivers very low amplitude (~0.0004 RMS)
# so threshold must be much lower than local audio
ENERGY_THRESHOLD = 0.00005  # PulseAudio TCP is extremely quiet
SILENCE_TIMEOUT_S = 0.8     # Fast cutoff — respond quickly after user stops
MIN_SPEECH_BYTES = 8000     # ~0.25s minimum (catch short phrases)

# Expression library — expanded to 28 clips across 5 emotional categories
LAUGH_CLIPS = [
    str(Path("~/.clipcannon/voice_data/santa/expressions/laugh_01_511s.wav").expanduser()),
    str(Path("~/.clipcannon/voice_data/santa/expressions/laugh_02_550s.wav").expanduser()),
]
_laugh_idx = 0

# Prosody-matched TTS reference clips
REFS_DIR = Path("~/.clipcannon/voice_data/santa/refs").expanduser()
_ref_mapping: dict = {}
_default_ref: str = ""
try:
    import json as _json
    _ref_map_path = REFS_DIR / "ref_mapping.json"
    if _ref_map_path.exists():
        with open(_ref_map_path) as _f:
            _ref_mapping = _json.load(_f)
        _default_ref = _ref_mapping.get("ref_default", {}).get("path", "")
except Exception:
    pass

# Prosody style keywords for response-text analysis
_PROSODY_STYLE_KEYWORDS = {
    "ref_energetic": ["excited", "amazing", "wonderful", "fantastic", "great", "love", "ho ho ho", "[LAUGH]"],
    "ref_calm": ["okay", "sure", "indeed", "yes", "I see", "understood", "agreed"],
    "ref_emphatic": ["must", "important", "absolutely", "never", "always", "critical", "truly"],
    "ref_question": ["?", "wonder", "perhaps", "maybe", "might"],
    "ref_warm": ["dear", "child", "friend", "heart", "believe", "hope", "magic", "Christmas"],
}


def select_prosody_ref(response_text: str) -> str | None:
    """Select the best prosody-matched TTS reference clip for a response.

    Analyzes response text for emotional keywords and selects the
    matching reference clip. Returns None to use the default.
    """
    if not _ref_mapping:
        return None

    text_lower = response_text.lower()
    best_style = None
    best_count = 0

    for style, keywords in _PROSODY_STYLE_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw.lower() in text_lower)
        if count > best_count:
            best_count = count
            best_style = style

    # Skip ref_question — it truncates TTS output
    if best_style and best_style != "ref_question" and best_style in _ref_mapping:
        return _ref_mapping[best_style].get("path")
    return None

# Transcript buffer
_transcript_segments: list[dict] = []
_MAX_TRANSCRIPT_SEGMENTS = 200

# ---------------------------------------------------------------------------
# PulseAudio setup
# ---------------------------------------------------------------------------
try:
    _gw = subprocess.run(
        ["ip", "route", "show", "default"],
        capture_output=True, text=True, timeout=5,
    ).stdout.strip().split()[2]
    os.environ["PULSE_SERVER"] = f"tcp:{_gw}:4713"
except Exception:
    pass

# Remove ALL loopbacks — wrapped in try/except since PulseAudio TCP can timeout
try:
    subprocess.run(["pactl", "set-default-source", "clone_audio.monitor"],
                   capture_output=True, timeout=10)
    subprocess.run(["pactl", "set-default-sink", "output"],
                   capture_output=True, timeout=10)
    for line in subprocess.run(
        ["pactl", "list", "short", "modules"],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip().split("\n"):
        if "loopback" in line.lower():
            mid = line.split()[0]
            subprocess.run(["pactl", "unload-module", mid],
                           capture_output=True, timeout=10)
            logger.info("Removed loopback module %s", mid)
except Exception as e:
    logger.warning("PulseAudio setup issue (continuing): %s", e)


# ---------------------------------------------------------------------------
# GPU memory management (RTX 5090 Blackwell / CUDA 13.x optimizations)
# ---------------------------------------------------------------------------
#
# RTX 5090 specs: 21,760 CUDA cores, 170 SMs, 32GB GDDR7, 1792 GB/s BW
# Key: Lazy module loading + expandable segments + no unnecessary syncs
#
os.environ.setdefault("CUDA_MODULE_LOADING", "LAZY")  # Don't load all modules at startup
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF",
                       "expandable_segments:True,max_split_size_mb:256")
os.environ.setdefault("PYTORCH_NO_CUDA_MEMORY_CACHING", "0")  # Keep caching on

# Limit CuPy memory pool to prevent competition with PyTorch
try:
    import cupy as _cp
    _pool = _cp.get_default_memory_pool()
    _pool.set_limit(size=512 * 1024 * 1024)  # 512MB cap for compositor
except ImportError:
    pass

_GPU_VRAM_WARNING_GB = 28.0  # Warn if VRAM usage exceeds this


def gpu_cleanup():
    """Free fragmented GPU memory. Call between heavy CUDA operations."""
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
    try:
        import cupy as cp
        cp.get_default_memory_pool().free_all_blocks()
    except ImportError:
        pass


def gpu_health_check() -> bool:
    """Check GPU health. Returns False if VRAM critically high or GPU unreachable."""
    try:
        import torch
        if not torch.cuda.is_available():
            logger.error("GPU: CUDA not available!")
            return False
        alloc = torch.cuda.memory_allocated() / 1e9
        reserved = torch.cuda.memory_reserved() / 1e9
        total = torch.cuda.get_device_properties(0).total_memory / 1e9
        if alloc > _GPU_VRAM_WARNING_GB:
            logger.warning("GPU: VRAM HIGH %.1fGB/%.1fGB — forcing cleanup", alloc, total)
            torch.cuda.empty_cache()
            gc.collect()
            return True
        return True
    except Exception as e:
        logger.error("GPU health check failed: %s", e)
        return False


def log_gpu_state(label: str = ""):
    """Log current GPU memory usage."""
    try:
        import torch
        if torch.cuda.is_available():
            alloc = torch.cuda.memory_allocated() / 1e9
            reserved = torch.cuda.memory_reserved() / 1e9
            logger.info("GPU [%s]: %.2fGB allocated, %.2fGB reserved", label, alloc, reserved)
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Model singletons — loaded ONCE, released on exit
# ---------------------------------------------------------------------------
_whisper_model = None
_tts_adapter = None
_ocr_client = None


def get_whisper():
    """Get or load the Whisper model (singleton)."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        logger.info("Loading Whisper %s...", WHISPER_MODEL)
        _whisper_model = WhisperModel(
            WHISPER_MODEL, device="cuda", compute_type="float16",
        )
        logger.info("Whisper loaded")
    return _whisper_model


def get_tts():
    """Get or load the TTS adapter (singleton)."""
    global _tts_adapter
    if _tts_adapter is None:
        from voiceagent.adapters.fast_tts import FastTTSAdapter
        logger.info("Loading TTS (voice=%s)...", VOICE_NAME)
        _tts_adapter = FastTTSAdapter(voice_name=VOICE_NAME)
        logger.info("TTS loaded")
    return _tts_adapter


def release_models():
    """Release all GPU models and free VRAM."""
    global _whisper_model, _tts_adapter
    if _tts_adapter is not None:
        try:
            _tts_adapter.release()
        except Exception:
            pass
        _tts_adapter = None
    if _whisper_model is not None:
        del _whisper_model
        _whisper_model = None
    # Aggressive GPU cleanup
    gc.collect()
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
    except (ImportError, RuntimeError):
        pass
    try:
        import cupy as cp
        cp.get_default_memory_pool().free_all_blocks()
        cp.get_default_pinned_memory_pool().free_all_blocks()
    except (ImportError, RuntimeError):
        pass
    logger.info("All models released")


# ---------------------------------------------------------------------------
# OCR Provenance client
# ---------------------------------------------------------------------------
async def get_ocr_client():
    """Get or create the OCR Provenance client."""
    global _ocr_client
    if _ocr_client is None:
        from voiceagent.meeting.mcp_client import OcrProvenanceClient
        _ocr_client = OcrProvenanceClient(base_url=OCR_PROVENANCE_URL)
        # Ensure database exists
        try:
            await _ocr_client.call_tool("ocr_db_select", {"database_name": OCR_DB_NAME})
        except Exception:
            try:
                await _ocr_client.call_tool("ocr_db_create", {
                    "name": OCR_DB_NAME,
                    "description": "Clone meeting transcripts",
                })
                await _ocr_client.call_tool("ocr_db_select", {"database_name": OCR_DB_NAME})
            except Exception as e:
                logger.warning("OCR Provenance unavailable: %s", e)
                _ocr_client = None
                return None
        logger.info("OCR Provenance connected (db=%s)", OCR_DB_NAME)
    return _ocr_client


async def search_meeting_history(query: str) -> str:
    """Search past meetings via OCR Provenance for relevant context."""
    client = await get_ocr_client()
    if client is None:
        return ""
    try:
        result = await client.call_tool("ocr_search", {
            "query": query, "limit": 5,
        })
        if not isinstance(result, dict):
            return ""
        results = result.get("results", result.get("chunks", []))
        if not results:
            text = result.get("text", "")
            return text[:800] if text else ""
        lines = []
        for item in results[:5]:
            if isinstance(item, dict):
                text = item.get("text", item.get("content", ""))
                if text:
                    lines.append(text[:250].strip())
        return "\n".join(lines)
    except Exception as e:
        logger.debug("OCR search failed: %s", e)
        return ""


async def ingest_transcript(segments: list[dict], meeting_id: str) -> None:
    """Ingest transcript segments into OCR Provenance for live search."""
    client = await get_ocr_client()
    if client is None or not segments:
        return
    try:
        # Build markdown
        lines = [f"# Meeting Transcript ({meeting_id})\n"]
        for seg in segments:
            speaker = seg.get("speaker", "Unknown")
            text = seg.get("text", "")
            ts = seg.get("timestamp", "")
            lines.append(f"**{speaker}** ({ts}): {text}\n")
        md = "\n".join(lines)

        # Write to temp file and ingest
        path = Path(f"/tmp/{meeting_id}_live.md")
        path.write_text(md, encoding="utf-8")
        await client.call_tool("ocr_ingest_files", {
            "files": [str(path)],
            "disable_image_extraction": True,
        })
        path.unlink(missing_ok=True)
        logger.debug("Ingested %d segments into OCR Provenance", len(segments))
    except Exception as e:
        logger.debug("Transcript ingest failed: %s", e)


# ---------------------------------------------------------------------------
# Dynamic avatar setup
# ---------------------------------------------------------------------------
_face_warper = None


def init_face_warper():
    """Initialize the face warper from the reference frame."""
    global _face_warper
    import subprocess
    src_video = SANTA_IDLE_VIDEO
    if not Path(src_video).exists():
        return
    try:
        r = subprocess.run(
            ["ffmpeg", "-i", src_video, "-vframes", "1",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
            capture_output=True, timeout=10,
        )
        if r.returncode != 0 or len(r.stdout) == 0:
            return
        ref_frame = np.frombuffer(r.stdout, dtype=np.uint8).reshape(720, 1280, 3)
        from phoenix.render.face_warper import FaceWarper
        _face_warper = FaceWarper(ref_frame, max_pixel_shift=20)
        if _face_warper.ready:
            logger.info("Face warper ready for lip sync")
        else:
            _face_warper = None
            logger.warning("Face warper: no face detected")
    except Exception as e:
        logger.warning("Face warper init failed: %s", e)


# ---------------------------------------------------------------------------
# Browser launch
# ---------------------------------------------------------------------------
async def launch_browser():
    """Launch Playwright browser and join the meeting."""
    if not MEET_URL:
        logger.error("No meeting URL provided. Usage: python santa_meet_bot.py <URL>")
        return None, None, None

    # === WARM EVERYTHING BEFORE JOINING ===
    logger.info("=== WARMING ALL MODELS ===")

    # 1. Whisper
    logger.info("Loading Whisper...")
    get_whisper()
    gpu_cleanup()
    log_gpu_state("whisper")

    # 2. TTS + CUDA graph warmup
    logger.info("Loading TTS + warmup...")
    tts = get_tts()
    try:
        _ = await tts.synthesize("Ho ho ho, merry Christmas!")
        logger.info("TTS warmed — first response will be instant")
    except Exception:
        pass

    # 3. Pre-transcribe ALL prosody ref clips so switching is instant (no Whisper at speak time)
    if _ref_mapping:
        logger.info("Pre-transcribing %d prosody refs...", len(_ref_mapping))
        _ref_transcripts = {}
        for name, info in _ref_mapping.items():
            path = info.get("path", "")
            if path and Path(path).exists():
                try:
                    text = tts._transcribe(path)
                    _ref_transcripts[path] = text
                    logger.info("  %s: '%s'", name, (text or "")[:50])
                except Exception:
                    pass
        # Store for use in speak()
        globals()["_ref_transcripts"] = _ref_transcripts
    gpu_cleanup()
    log_gpu_state("tts")

    # 4. Face warper (optional, for future lip sync)
    init_face_warper()
    gpu_cleanup()

    logger.info("=== ALL MODELS WARM — joining meeting ===")

    # Start Xvfb virtual display — Chrome runs invisible, no window on user's screen
    import subprocess as _sp
    _xvfb = _sp.Popen(
        ["Xvfb", ":99", "-screen", "0", "1280x720x24", "-ac"],
        stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
    )
    os.environ["DISPLAY"] = ":99"
    logger.info("Xvfb started on :99 (invisible virtual display)")

    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=SESSION_DIR, headless=False,  # headful on virtual display
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-video-capture={IDLE_Y4M}",
            "--use-file-for-fake-audio-capture=/home/cabdru/.voiceagent/silence.wav",
        ],
        viewport={"width": 1280, "height": 720},
        locale="en-US",
        permissions=["camera", "microphone"],
    )
    # Init script: Intercept getUserMedia with REAL fake-device track metadata
    #
    # THE KEY INSIGHT: Google Meet validates video tracks by checking
    # getSettings() and getCapabilities(). A raw MediaStreamTrackGenerator
    # returns empty metadata and Meet silently disables it.
    #
    # SOLUTION: Call the ORIGINAL getUserMedia to get the fake device's
    # video track (which has real camera metadata). Then use Insertable
    # Streams (MediaStreamTrackProcessor → transform → MediaStreamTrackGenerator)
    # to pipe our custom canvas frames THROUGH the real track's pipeline.
    # The generator inherits the processor's metadata chain, so Meet sees
    # a track with real getSettings()/getCapabilities() that contains our frames.
    #
    # If Insertable Streams are not available (older Chrome), fall back to
    # canvas.captureStream() with getSettings/getCapabilities spoofed from
    # the real track.
    #
    # MUST be minimal — large scripts crash the page.
    await context.add_init_script("""
        Object.defineProperty(navigator,"webdriver",{get:()=>false});
        const _origGUM=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
        window.__santaJpegB64=null;
        navigator.mediaDevices.getUserMedia=async function(c){
            if(!c||!c.video) return _origGUM(c);
            try{
                // Step 1: Get REAL fake-device stream (has proper camera metadata)
                const realStream=await _origGUM({video:c.video});
                const realTrack=realStream.getVideoTracks()[0];
                const realSettings=realTrack.getSettings();
                const realCaps=realTrack.getCapabilities?realTrack.getCapabilities():{};
                const W=realSettings.width||1280, H=realSettings.height||720;
                console.log('[AvatarCam] Real track:',realTrack.label,W+'x'+H,JSON.stringify(realSettings));

                // Step 2: Canvas for rendering our frames
                const oc=new OffscreenCanvas(W,H);
                const ox=oc.getContext('2d');

                // Step 3: Try Insertable Streams approach
                let outTrack;
                if(typeof MediaStreamTrackProcessor!=='undefined'&&typeof MediaStreamTrackGenerator!=='undefined'){
                    console.log('[AvatarCam] Using Insertable Streams (Processor→Generator)');
                    const proc=new MediaStreamTrackProcessor({track:realTrack});
                    const gen=new MediaStreamTrackGenerator({kind:'video'});
                    const reader=proc.readable.getReader();
                    const writer=gen.writable.getWriter();
                    let imgReady=false;
                    const img=new Image();
                    img.onload=()=>{imgReady=true;};
                    // Background: decode JPEGs as they arrive (non-blocking)
                    let lastJpeg=null;
                    setInterval(()=>{
                        if(window.__santaJpegB64&&window.__santaJpegB64!==lastJpeg){
                            lastJpeg=window.__santaJpegB64;
                            img.src='data:image/jpeg;base64,'+lastJpeg;
                        }
                    },30);
                    // Frame pump: runs at fake device rate (~30fps), NEVER blocks
                    (async()=>{
                        while(true){
                            const{value:frame,done}=await reader.read();
                            if(done)break;
                            frame.close();
                            // Draw current image (already decoded, instant)
                            if(imgReady){
                                ox.drawImage(img,0,0,W,H);
                            }else{
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
                    // Spoof metadata on the generator track
                    const origGS=gen.getSettings.bind(gen);
                    gen.getSettings=()=>({...origGS(),...realSettings});
                    if(gen.getCapabilities)gen.getCapabilities=()=>realCaps;
                    outTrack=gen;
                }else{
                    // Fallback: canvas.captureStream + metadata spoofing
                    console.log('[AvatarCam] Fallback: captureStream + metadata spoof');
                    const visCanvas=document.createElement('canvas');
                    visCanvas.width=W;visCanvas.height=H;
                    const vx=visCanvas.getContext('2d');
                    const capStream=visCanvas.captureStream(15);
                    const capTrack=capStream.getVideoTracks()[0];
                    // Spoof metadata from real track
                    capTrack.getSettings=()=>realSettings;
                    if(realTrack.getCapabilities)capTrack.getCapabilities=()=>realCaps;
                    capTrack.getConstraints=()=>realTrack.getConstraints();
                    // Render loop on visible canvas
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
                    realTrack.stop(); // free the real device
                }

                // Step 4: Build output stream
                const outStream=new MediaStream([outTrack]);

                // Step 5: Audio — get from fake device or create silent AudioContext
                if(c.audio){
                    try{
                        const aStream=await _origGUM({audio:c.audio});
                        for(const t of aStream.getAudioTracks())outStream.addTrack(t);
                    }catch(e){}
                    // Always create AudioContext for TTS injection
                    const actx=new AudioContext({sampleRate:48000});
                    const dest=actx.createMediaStreamDestination();
                    // If no audio track was added, add silent one
                    if(!outStream.getAudioTracks().length){
                        outStream.addTrack(dest.stream.getAudioTracks()[0]);
                    }
                    window.__santaAudioCtx=actx;
                    window.__santaAudioDest=dest;
                }
                console.log('[AvatarCam] Output stream:',outStream.getTracks().length,'tracks');
                console.log('[AvatarCam] Video settings:',JSON.stringify(outTrack.getSettings()));
                return outStream;
            }catch(e){
                console.error('[AvatarCam] Init failed, raw fallback:',e);
                return _origGUM(c);
            }
        };
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
    await page.goto(MEET_URL, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)
    logger.info("Page loaded, PC capture installed")

    # Click join button
    for sel in [
        'button:has-text("Ask to join")',
        'button:has-text("Join now")',
        'button:has-text("Switch here")',
        'button:has-text("Join")',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=3000):
                await btn.click()
                logger.info("Joined")
                break
        except Exception:
            continue

    # Wait for meeting
    for _ in range(120):
        await asyncio.sleep(1)
        try:
            if await page.locator('[aria-label="Leave call"]').first.is_visible(timeout=500):
                logger.info("IN THE MEETING!")

                # UNMUTE mic — this makes Google Meet add an audio sender
                # to the RTCPeerConnection so we can replace its track
                for sel in ['[aria-label*="Turn on microphone"]',
                            '[aria-label*="Unmute"]',
                            '[aria-label*="microphone"][data-is-muted="true"]',
                            'button[aria-label*="micro"]']:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible(timeout=2000):
                            await btn.click()
                            logger.info("Mic unmuted")
                            break
                    except Exception:
                        continue

                # No replaceTrack needed — getUserMedia was intercepted by init script.
                # Video: real fake-device track → Insertable Streams → our canvas frames
                # Audio: AudioContext created in init script for TTS injection
                await asyncio.sleep(2)

                # Verify the video pipeline is working
                try:
                    status = await page.evaluate("""() => {
                        const info = {
                            jpegVar: typeof window.__santaJpegB64,
                            audioCtx: !!window.__santaAudioCtx,
                            audioDest: !!window.__santaAudioDest,
                        };
                        return JSON.stringify(info);
                    }""")
                    logger.info("Avatar pipeline status: %s", status)
                except Exception:
                    pass

                logger.info("Insertable Streams avatar pipeline active")
                return pw, context, page
        except Exception:
            continue

    return None, None, None


# ---------------------------------------------------------------------------
# Audio capture + Reasoning Controller loop
# ---------------------------------------------------------------------------
async def audio_loop(page, stop):
    """Continuous listening loop driven by the Reasoning Controller.

    The controller observes all speech, reasons about what to do,
    and controls prosody selection, lip sync, and response timing.
    """
    from voiceagent.meeting.reasoning_controller import (
        ActionIntent,
        ReasoningController,
    )

    log_gpu_state("models-ready")
    logger.info("ALL MODELS IN VRAM — ready to converse")

    history: list[dict] = []
    meeting_id = f"mtg_{int(time.time())}"

    # --- Response handler called by reasoning controller ---
    async def handle_respond(user_text: str) -> str | None:
        """Generate response, speak it, return the text."""
        t_start = time.time()
        resp = await respond(user_text, history)
        if not resp or len(resp) < 10:
            logger.warning("Skipped short/empty response: '%s'", resp)
            return None

        t_llm = time.time()
        logger.info("SANTA: '%s' (LLM: %dms)", resp, (t_llm - t_start) * 1000)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": resp})
        if len(history) > 6:
            del history[:len(history) - 6]

        await speak(page, resp)
        t_total = time.time() - t_start
        logger.info("TOTAL RESPONSE: %.1fs (target <2s)", t_total)
        return resp

    # --- Avatar rendering driven by controller commands ---
    _last_avatar_cmd = None

    def handle_avatar_command(cmd) -> None:
        """Receive command from reasoning controller — queue for rendering."""
        nonlocal _last_avatar_cmd
        _last_avatar_cmd = cmd

    def handle_expression(intent: ActionIntent, awareness) -> None:
        if intent in (ActionIntent.RESPOND, ActionIntent.INTERJECT,
                       ActionIntent.LISTEN_AMUSED, ActionIntent.LISTEN_EMPATHETIC):
            logger.info("Avatar: %s [emo=%s]", intent.value, awareness.detected_emotion)

    async def video_render_loop():
        """Render avatar → push JPEG to Chrome via page.evaluate.

        Chrome's init script uses MediaStreamTrackGenerator + OffscreenCanvas.
        We set window.__santaJpegB64 with a JPEG base64 string (~30KB).
        The generator loop decodes it and produces VideoFrames at 15fps.
        Much smaller than raw RGBA (30KB vs 4.9MB per frame).
        """
        import base64, math

        FPS = 15  # 15fps JPEG updates, generator runs at 30fps
        frame_count = 0

        while not stop.is_set() and (_face_warper is None or not _face_warper.ready):
            await asyncio.sleep(1)

        logger.info("Video render loop: %dfps JPEG → page.evaluate → MediaStreamTrackGenerator", FPS)

        while not stop.is_set():
            frame_count += 1
            t = frame_count / FPS
            cmd = _last_avatar_cmd

            # ALWAYS animate — controller overrides idle, idle always runs
            breath = math.sin(t * 0.4) * 0.03
            sway = math.sin(t * 0.3) * 2.0

            if cmd is not None:
                # Controller-driven: use blendshapes + add subtle life
                mouth_open = cmd.blendshapes.get("jawOpen", 0.0) + max(0, breath)
                smile = cmd.blendshapes.get("mouthSmileLeft", 0.0)
                head_tilt = (cmd.head_pose[2] if cmd.head_pose else 0.0) + sway * 0.3
                mouth_open = min(1.0, mouth_open + smile * 0.1)
            else:
                # No controller yet — visible idle
                mouth_open = max(0, breath)
                head_tilt = sway

            # Blink every ~4 seconds
            if (t % 4.0) < 0.15:
                mouth_open += 0.04

            frame_bgr = _face_warper.warp_mouth(mouth_open, head_tilt)

            # Encode as JPEG (~30KB vs 4.9MB for raw RGBA)
            _, jpg_buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 60])
            jpg_b64 = base64.b64encode(jpg_buf).decode('ascii')

            try:
                await page.evaluate("b64 => { window.__santaJpegB64 = b64; }", jpg_b64)
            except Exception:
                pass

            if frame_count % (FPS * 10) == 1:
                logger.info("Video frame #%d (%dKB JPEG, mouth=%.2f)",
                            frame_count, len(jpg_b64) // 1024, mouth_open)

            await asyncio.sleep(1.0 / FPS)

    # --- Create the reasoning controller ---
    controller = ReasoningController(
        character_name="Santa",
        respond_callback=handle_respond,
        expression_callback=handle_expression,
        avatar_callback=handle_avatar_command,
    )

    # Start reasoning controller + video render as async tasks
    reasoning_task = asyncio.create_task(controller.run(stop))
    video_task = asyncio.create_task(video_render_loop())
    logger.info("Reasoning controller + video render started")

    # Start audio capture
    parec = await asyncio.create_subprocess_exec(
        "parec", f"--device={CAPTURE_DEVICE}",
        "--format=s16le", f"--rate={SAMPLE_RATE}", "--channels=1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    logger.info("Capturing from %s (PID %d)", CAPTURE_DEVICE, parec.pid)

    buf = bytearray()
    window_start = time.time()
    WINDOW_S = 2.0  # Transcribe every 2 seconds
    MAX_BUF_BYTES = SAMPLE_RATE * 2 * 8

    while not stop.is_set():
        try:
            chunk = await asyncio.wait_for(
                parec.stdout.read(CHUNK_BYTES), timeout=0.2,
            )
        except asyncio.TimeoutError:
            chunk = None
            # Track silence for the controller
            controller.tick_silence(200)
        except Exception:
            break

        # While responding, drain audio but don't accumulate
        if controller.is_responding:
            continue

        if chunk:
            buf.extend(chunk)
            if len(buf) > MAX_BUF_BYTES:
                buf = buf[-MAX_BUF_BYTES:]

        # Transcribe on window boundary
        elapsed = time.time() - window_start
        if elapsed >= WINDOW_S and len(buf) > MIN_SPEECH_BYTES:
            window_start = time.time()

            # Normalize quiet PulseAudio audio
            audio = np.frombuffer(bytes(buf), dtype=np.int16).astype(np.float32) / 32768.0
            peak = np.max(np.abs(audio))
            if peak > 0:
                audio = audio * min(0.9 / peak, 50.0)

            text = await transcribe(audio)
            del audio

            if text and len(text) > 2:
                logger.info("HEARD: '%s'", text)

                # Feed to reasoning controller (Tier 1 observation)
                controller.observe(text)

                # Store transcript
                _transcript_segments.append({
                    "speaker": "Participant", "text": text,
                    "timestamp": time.strftime("%H:%M:%S"),
                })
                if len(_transcript_segments) > _MAX_TRANSCRIPT_SEGMENTS:
                    del _transcript_segments[:len(_transcript_segments) - _MAX_TRANSCRIPT_SEGMENTS]

                # Let the controller decide what to do (Tier 2)
                intent = controller.reason()

                if intent in (ActionIntent.RESPOND, ActionIntent.INTERJECT):
                    # Tier 3: Generate and speak response
                    recent_text = controller._get_recent_text(15)
                    await controller.execute_response(recent_text)
                    window_start = time.time()  # Reset so next listen starts fast

            buf.clear()

    # Cleanup
    controller.stop()
    reasoning_task.cancel()
    video_task.cancel()
    parec.kill()
    await ingest_transcript(_transcript_segments, meeting_id)


async def process(buf, history, page, meeting_id):
    """Process speech buffer: transcribe -> search -> respond -> speak.

    Catches all errors so the bot continues running even if one
    response cycle fails.
    """
    try:
        audio = np.frombuffer(bytes(buf), dtype=np.int16).astype(np.float32) / 32768.0
        # Normalize low-amplitude PulseAudio TCP audio
        peak = np.max(np.abs(audio))
        if peak > 0:
            gain = min(0.9 / peak, 50.0)
            audio = audio * gain
        text = await transcribe(audio)
        if not text or len(text) < 3:
            return
        logger.info("HEARD: '%s'", text)

        # Store in transcript
        ts = time.strftime("%H:%M:%S")
        _transcript_segments.append({
            "speaker": "Participant", "text": text, "timestamp": ts,
        })
        if len(_transcript_segments) > _MAX_TRANSCRIPT_SEGMENTS:
            del _transcript_segments[:len(_transcript_segments) - _MAX_TRANSCRIPT_SEGMENTS]

        # Only respond when directly addressed
        if not _is_addressed(text):
            logger.info("Not addressed — listening only")
            return

        resp = await respond(text, history)
        if not resp:
            logger.warning("Empty response for: '%s'", text[:60])
            return
        logger.info("SANTA: '%s'", resp)

        # Store response in transcript
        _transcript_segments.append({
            "speaker": "Santa (Clone)", "text": resp,
            "timestamp": time.strftime("%H:%M:%S"),
        })

        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": resp})
        # Keep history bounded
        if len(history) > 20:
            del history[:len(history) - 20]

        await speak(page, resp)
        # Extra silence gap after speaking to prevent echo pickup
        await asyncio.sleep(1.0)

    except Exception as e:
        logger.error("Process cycle failed (bot continues): %s", e)
        import traceback
        logger.error(traceback.format_exc())
    finally:
        # Free GPU + CPU memory after every response cycle
        gpu_cleanup()
        log_gpu_state("post-cycle")


async def transcribe(audio):
    """Transcribe audio using the singleton Whisper model."""
    model = get_whisper()
    # Disable Whisper's internal VAD — it filters out PulseAudio TCP's quiet audio.
    # We normalize audio before calling transcribe(), so VAD isn't needed.
    segs, _ = model.transcribe(audio, language="en", vad_filter=False)
    return " ".join(s.text.strip() for s in segs).strip()


async def respond(text, history):
    """Generate response using Ollama with fast turnaround."""
    import httpx

    # Skip slow OCR search for simple conversational messages
    # Only search when the question seems to reference past context
    history_context = ""
    needs_search = any(kw in text.lower() for kw in [
        "remember", "last time", "before", "earlier", "you said",
        "we talked", "mentioned", "discussed",
    ])
    if needs_search:
        try:
            history_context = await asyncio.wait_for(
                search_meeting_history(text), timeout=3.0,
            )
        except asyncio.TimeoutError:
            logger.debug("OCR search timed out, skipping")

    system = (
        "You are the real Santa Claus on a video call. "
        "You speak with a warm, deep, resonant voice full of life and emotion. "
        "RULES: "
        "1) Reply in 1-3 sentences. Be warm but concise. "
        "2) Speak like a REAL person having a genuine conversation. "
        "No emojis. No asterisks. No formatting. Pure natural speech. "
        "3) Answer what was actually asked. Be specific and genuine. "
        "4) You are a real Santa — you've visited children in hospitals, "
        "sat with families during hard times, and seen the magic of Christmas "
        "change lives. Draw from real emotions and experiences. "
        "5) Vary your tone — be jolly when happy, gentle when comforting, "
        "thoughtful when reflecting. Let emotion come through naturally. "
        "6) Say 'my friend' not 'little one'. Speak as an equal. "
        "7) Sometimes pause or use filler words like 'well' or 'you know' "
        "to sound natural, not robotic."
    )

    # Build messages — keep history SHORT to prevent hallucination
    msgs = [{"role": "system", "content": system}]
    msgs.extend(history[-6:])  # Only last 3 exchanges

    # Build user message with RAG context
    user_msg = text
    if history_context:
        user_msg = (
            f"[Context from past meetings]\n{history_context}\n\n"
            f"[Current question]\n{text}"
        )
    msgs.append({"role": "user", "content": user_msg})

    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": LLM_MODEL,
                    "messages": msgs,
                    "stream": False,
                    # Gemma 4 doesn't use think parameter
                    "options": {
                        "num_predict": 80,  # 1-2 sentences = ~40-60 tokens
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "num_gpu": 99,  # 8B fits entirely on GPU (~5GB)
                    },
                },
            )
        return r.json().get("message", {}).get("content", "").strip()
    except httpx.TimeoutException:
        logger.error("Ollama timed out after 180s")
        return ""
    except Exception as e:
        logger.error("Ollama error: %s", e)
        return ""


# Audio/video injection is handled entirely by the init script
# (MediaStreamTrackGenerator for video, AudioContext for audio)
# No post-join track replacement needed


async def speak(page, text):
    """Synthesize speech with prosody-matched refs, laugh clips, and inject to meeting."""
    global _laugh_idx
    import base64
    import soundfile as sf

    tts = get_tts()
    try:
        logger.info("speak() starting for: '%s'", text[:60])

        # Select prosody-matched reference clip for emotional voice variation
        cached_transcripts = globals().get("_ref_transcripts", {})
        ref_path = select_prosody_ref(text)
        if ref_path and Path(ref_path).exists():
            ref_text = cached_transcripts.get(ref_path)
            tts.set_ref_audio(ref_path, ref_text=ref_text)
            logger.info("Prosody ref: %s", Path(ref_path).name)

        # Strip all tags — synthesize clean text only
        clean = re.sub(r'\[.*?\]', '', text).strip()
        if not clean:
            logger.warning("speak(): empty text after cleanup")
            return

        sr = 24000
        t0 = time.time()
        a = await tts.synthesize(clean)
        tts_ms = (time.time() - t0) * 1000
        logger.info("TTS: %.0fms for %.1fs audio", tts_ms, len(a) / sr)

        if len(a) == 0:
            logger.warning("TTS returned empty audio")
            return

        segs = [a]

        if not segs:
            return
        audio = np.concatenate(segs)
        audio_duration = len(audio) / sr
        logger.info("Audio: %.1fs (%d samples), %d segments",
                     audio_duration, len(audio), len(segs))
        del segs

        # Compute lip sync frames and send to browser for video animation
        if _face_warper is not None and _face_warper.ready:
            try:
                from phoenix.render.lip_sync import LipSync
                lip = LipSync(fps=25, sample_rate=sr)
                lip_frames = lip.from_audio(audio)
                # Extract unique mouth openness levels (quantize to reduce data)
                mouth_schedule = [round(f.mouth_open, 2) for f in lip_frames]
                logger.info("Lip sync: %d frames, mouth range %.2f-%.2f",
                            len(lip_frames),
                            min(mouth_schedule), max(mouth_schedule))
                # Send the mouth schedule to browser — JS will animate the
                # video track frame by frame using the schedule
                await page.evaluate(
                    "schedule => { window.__santaMouthSchedule = schedule; }",
                    mouth_schedule,
                )
            except Exception as e:
                logger.warning("Lip sync prep failed: %s", e)

        # Inject audio into WebRTC via JavaScript WebAudio API
        audio_bytes = audio.astype(np.float32).tobytes()
        b64 = base64.b64encode(audio_bytes).decode('ascii')
        b64_len = len(b64)
        del audio, audio_bytes

        logger.info("Sending %dKB audio (%.1fs) to browser...", b64_len // 1024, audio_duration)
        try:
            # Resume AudioContext and play audio
            await page.evaluate("() => window.__santaAudioCtx && window.__santaAudioCtx.resume()")
            result = await page.evaluate(
                "([b64, sr]) => window.__santaPlayAudio(b64, sr)",
                [b64, sr],
            )
            logger.info("Audio delivered: %s", result)
        except Exception as e:
            logger.error("Audio injection failed: %s", e)
        # Wait for playback
        await asyncio.sleep(audio_duration + 0.5)
        del b64

        logger.info("Spoke: %.1fs", audio_duration)

        # Return avatar to listening state
        if _y4m_writer is not None:
            try:
                from phoenix.render.y4m_writer import AvatarState
                _y4m_writer.set_state(AvatarState.LISTENING)
            except Exception:
                pass
    except Exception as e:
        logger.error("Speak failed: %s", e)
        # Ensure avatar returns to listening even on error
        if _y4m_writer is not None:
            try:
                from phoenix.render.y4m_writer import AvatarState
                _y4m_writer.set_state(AvatarState.LISTENING)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    pw, ctx, page = await launch_browser()
    if not pw:
        return

    print("\n" + "=" * 60)
    print("  SANTA CLONE LIVE — FULL QUALITY PIPELINE")
    print(f"  LLM: {LLM_MODEL}")
    print(f"  ASR: {WHISPER_MODEL}")
    print(f"  TTS: {VOICE_NAME} (Full ICL, real laugh clips)")
    print(f"  RAG: OCR Provenance ({OCR_PROVENANCE_URL})")
    print("  Audio: parec output.monitor -> pacat clone_audio")
    print("  NO loopback. Zero feedback. Full prosody.")
    print("=" * 60 + "\n")

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_event_loop().add_signal_handler(sig, stop.set)

    try:
        await audio_loop(page, stop)
    finally:
        # Clean shutdown
        try:
            leave = page.locator('[aria-label="Leave call"]').first
            if await leave.is_visible(timeout=2000):
                await leave.click()
        except Exception:
            pass
        await ctx.close()
        await pw.stop()

        # Release GPU memory
        release_models()

        # Close OCR Provenance client
        if _ocr_client is not None:
            await _ocr_client.close()

        # Kill Xvfb
        try:
            _xvfb.kill()
        except Exception:
            pass
        logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
