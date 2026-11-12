"""Santa bot configuration, prosody-ref selection and import-time environment setup.

Moved verbatim from scripts/santa_meet_bot.py. Importing this module performs the same
import-time side effects as the original script did, in the same order: logging config,
PulseAudio routing, CUDA allocator env vars and the CuPy memory-pool cap.
"""
import logging
import os
import subprocess
import sys
from pathlib import Path

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
AUDIO_SINK = "bot_output"  # null sink — TTS discarded, never reaches output.monitor
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

# PulseAudio routing — bot's Chrome audio goes to bot_output (null sink / discarded)
# so Whisper on output.monitor only hears meeting participants, not our TTS.
os.environ["PULSE_SINK"] = "bot_output"

# Remove ALL loopbacks — wrapped in try/except since PulseAudio TCP can timeout
try:
    subprocess.run(["pactl", "set-default-source", "output.monitor"],
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
