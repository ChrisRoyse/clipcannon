"""GPU housekeeping, model singletons and the OCR Provenance client for the Santa bot.

Owns the mutable singletons _whisper_model, _tts_adapter and _ocr_client; read them
through this module (models._ocr_client), not through a copied name.
"""
import gc
import logging
from pathlib import Path

from .config import (
    _GPU_VRAM_WARNING_GB,
    OCR_DB_NAME,
    OCR_PROVENANCE_URL,
    VOICE_NAME,
    WHISPER_MODEL,
)

logger = logging.getLogger("santa_bot")


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
