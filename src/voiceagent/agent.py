"""VoiceAgent -- top-level orchestrator with on-demand GPU lifecycle.

Lifecycle:
  DORMANT  -- Only wake word detector runs on CPU. Zero GPU usage.
  LOADING  -- Models loading to GPU (~10-20s). Agent says "I'm here" when ready.
  ACTIVE   -- Full conversation capability. Mic -> ASR -> LLM -> TTS -> Speaker.
  UNLOADING -- Agent says "Going to sleep", unloads all models.
  Back to DORMANT.

Activation: Wake word ("Hey Jarvis") or hotkey (Ctrl+Space).
Dismissal: Say "go to sleep" during conversation.
"""
from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from voiceagent.config import VoiceAgentConfig, load_config

logger = logging.getLogger(__name__)

DISMISS_PHRASES = {"go to sleep", "goodbye", "dismiss", "shut down"}


class AgentLifecycle(Enum):
    DORMANT = "dormant"
    LOADING = "loading"
    ACTIVE = "active"
    UNLOADING = "unloading"


class VoiceAgent:
    """Top-level orchestrator for the voice agent.

    In talk mode: starts DORMANT with only wake word on CPU.
    Wake word triggers model loading. "Go to sleep" unloads everything.
    In serve mode: loads everything immediately for WebSocket clients.
    """

    def __init__(self, config: VoiceAgentConfig | None = None) -> None:
        self.config = config or load_config()
        self._lifecycle = AgentLifecycle.DORMANT
        self._db_conn = None
        self._asr = None
        self._brain = None
        self._tts_adapter = None
        self._tts = None
        self._conversation = None
        self._wake_word = None
        self._hotkey = None
        self._transport = None
        self._local_transport = None
        self._app = None
        self._current_conversation_id: str | None = None
        self._initialized = False
        logger.info("VoiceAgent created (DORMANT, zero GPU)")

    # ------------------------------------------------------------------
    #  Database (always available, no GPU)
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Initialize SQLite database."""
        from voiceagent.db.connection import get_connection
        from voiceagent.db.schema import init_db

        data_dir = Path(self.config.data_dir).expanduser()
        db_path = data_dir / "agent.db"
        init_db(db_path)
        self._db_conn = get_connection(db_path)
        logger.info("Database at %s", db_path)

    # ------------------------------------------------------------------
    #  GPU model loading / unloading
    # ------------------------------------------------------------------

    def _load_models(self) -> None:
        """Load ASR + LLM + TTS models onto GPU. Called on activation."""
        if self._initialized:
            return
        self._lifecycle = AgentLifecycle.LOADING
        logger.info("Loading GPU models...")

        import torch
        vram_before = torch.cuda.memory_allocated()

        # ASR (VAD + Whisper)
        from voiceagent.asr.streaming import StreamingASR
        self._asr = StreamingASR(self.config.asr)
        logger.info("ASR loaded")

        # LLM Brain
        from voiceagent.brain.llm import LLMBrain
        self._brain = LLMBrain(self.config.llm)
        logger.info("LLM loaded (%.1f GB)", self._brain.vram_bytes / (1024**3))

        # TTS
        from voiceagent.adapters.clipcannon import ClipCannonAdapter
        from voiceagent.tts.chunker import SentenceChunker
        from voiceagent.tts.streaming import StreamingTTS
        self._tts_adapter = ClipCannonAdapter(
            voice_name=self.config.tts.voice_name,
        )
        self._tts = StreamingTTS(self._tts_adapter, SentenceChunker())
        logger.info("TTS loaded (voice=%s)", self.config.tts.voice_name)

        # Context + prompt
        from voiceagent.brain.context import ContextManager
        from voiceagent.brain.prompts import build_system_prompt
        self._system_prompt = build_system_prompt(self.config.tts.voice_name)
        self._context = ContextManager(
            tokenizer_path=self.config.llm.model_path,
        )

        vram_after = torch.cuda.memory_allocated()
        total_gb = (vram_after - vram_before) / (1024**3)
        logger.info("All models loaded: %.1f GB VRAM", total_gb)
        self._initialized = True

    def _unload_models(self) -> None:
        """Unload ALL GPU models and free VRAM."""
        self._lifecycle = AgentLifecycle.UNLOADING
        logger.info("Unloading GPU models...")

        if self._brain:
            self._brain.release()
            self._brain = None

        if self._tts_adapter:
            self._tts_adapter.release()
            self._tts_adapter = None

        self._asr = None
        self._tts = None
        self._conversation = None
        self._initialized = False

        try:
            import torch
            torch.cuda.empty_cache()
            vram = torch.cuda.memory_allocated() / (1024**3)
            logger.info("Models unloaded. VRAM: %.2f GB", vram)
        except ImportError:
            pass

        self._lifecycle = AgentLifecycle.DORMANT
        logger.info("Agent is DORMANT")

    # ------------------------------------------------------------------
    #  Conversation wiring
    # ------------------------------------------------------------------

    def _wire_conversation(self, transport: object) -> None:
        """Wire conversation manager to a transport."""
        from voiceagent.conversation.manager import ConversationManager
        self._conversation = ConversationManager(
            asr=self._asr,
            brain=self._brain,
            tts=self._tts,
            transport=transport,
            context_manager=self._context,
            system_prompt=self._system_prompt,
        )

    # ------------------------------------------------------------------
    #  Activation (wake word detected or hotkey pressed)
    # ------------------------------------------------------------------

    async def _activate(self, transport: object) -> None:
        """Load models and announce readiness."""
        if self._lifecycle != AgentLifecycle.DORMANT:
            return
        logger.info("Activating...")
        self._load_models()
        self._wire_conversation(transport)
        self._lifecycle = AgentLifecycle.ACTIVE
        self._current_conversation_id = self.start_conversation()

        # Say "I'm here" through the transport
        try:
            audio = await self._tts_adapter.synthesize("I'm here.")
            await transport.send_audio(audio)
        except Exception as e:
            logger.warning("Could not speak greeting: %s", e)

        logger.info("Agent is ACTIVE")

    async def _deactivate(self, transport: object) -> None:
        """Say goodbye, unload models, return to DORMANT."""
        if self._lifecycle != AgentLifecycle.ACTIVE:
            return
        logger.info("Deactivating...")

        # Say "Going to sleep"
        try:
            audio = await self._tts_adapter.synthesize("Going to sleep.")
            await transport.send_audio(audio)
        except Exception as e:
            logger.warning("Could not speak farewell: %s", e)

        self._unload_models()

    # ------------------------------------------------------------------
    #  Audio handling for talk mode
    # ------------------------------------------------------------------

    async def _handle_audio_talk(
        self,
        audio: object,
        transport: object,
    ) -> None:
        """Process mic audio in talk mode with lifecycle management."""
        import numpy as np
        if not isinstance(audio, np.ndarray) or audio.size == 0:
            return

        if self._lifecycle == AgentLifecycle.DORMANT:
            # Check wake word (expects ~1280 samples)
            if (
                self._wake_word is not None
                and self._wake_word.detect(audio)
            ):
                logger.info("Wake word detected!")
                await self._activate(transport)
            return

        if self._lifecycle == AgentLifecycle.ACTIVE and self._conversation:
            # Feed audio to conversation manager
            await self._conversation.handle_audio_chunk(audio)

            # Check for dismiss keyword in ASR output
            if hasattr(self._conversation, '_history') and self._conversation._history:
                last = self._conversation._history[-1]
                if last.get("role") == "user":
                    text_lower = last["content"].lower().strip()
                    if any(phrase in text_lower for phrase in DISMISS_PHRASES):
                        logger.info("Dismiss keyword detected: '%s'", last["content"])
                        await self._deactivate(transport)

    # ------------------------------------------------------------------
    #  talk_interactive -- the real deal
    # ------------------------------------------------------------------

    async def talk_interactive(self) -> None:
        """Run interactive local voice conversation.

        Lifecycle:
          1. DB + wake word init (CPU only, no GPU)
          2. Listen for wake word via mic
          3. On wake word: load models, start conversation
          4. Converse until "go to sleep" or Ctrl+C
          5. Unload models, return to dormant
          6. Repeat from step 2
        """
        self._init_db()

        # Init wake word detector (CPU only)
        try:
            from voiceagent.activation.wake_word import WakeWordDetector
            self._wake_word = WakeWordDetector(threshold=0.6)
            logger.info("Wake word detector ready (say 'Hey Jarvis' to activate)")
        except Exception as e:
            logger.warning(
                "Wake word unavailable: %s. "
                "Will activate immediately on any speech.",
                e,
            )

        # Init local audio transport
        from voiceagent.transport.local_audio import LocalAudioTransport
        self._local_transport = LocalAudioTransport(
            chunk_ms=self.config.asr.chunk_ms,
        )

        async def on_audio(audio: object) -> None:
            await self._handle_audio_talk(audio, self._local_transport)

        async def on_control(data: dict) -> None:
            pass

        print("\n=== Voice Agent ===")
        print(f"Voice: {self.config.tts.voice_name}")
        if self._wake_word:
            print("Say 'Hey Jarvis' to activate")
        else:
            print("Models will load on first speech detected")
        print("Say 'Go to sleep' to deactivate")
        print("Press Ctrl+C to quit")
        print("=" * 20 + "\n")

        try:
            await self._local_transport.start(on_audio, on_control)
        except KeyboardInterrupt:
            pass
        finally:
            if self._lifecycle == AgentLifecycle.ACTIVE:
                self._unload_models()
            if self._local_transport:
                await self._local_transport.stop()
            self._close_db()

    # ------------------------------------------------------------------
    #  serve mode (WebSocket, loads immediately)
    # ------------------------------------------------------------------

    def _init_components(self) -> None:
        """Initialize ALL components for serve mode (loads GPU immediately)."""
        if self._initialized:
            return
        self._init_db()
        self._load_models()

        from voiceagent.transport.websocket import WebSocketTransport
        self._transport = WebSocketTransport(
            host=self.config.transport.host,
            port=self.config.transport.port,
        )
        self._wire_conversation(self._transport)

        # Activation (optional)
        try:
            from voiceagent.activation.wake_word import WakeWordDetector
            self._wake_word = WakeWordDetector(threshold=0.6)
        except Exception as e:
            logger.warning("Wake word unavailable: %s", e)

        try:
            from voiceagent.activation.hotkey import HotkeyActivator
            self._hotkey = HotkeyActivator(callback=self._on_hotkey)
        except Exception as e:
            logger.warning("Hotkey unavailable: %s", e)

        # Server app
        from voiceagent.server import create_app
        self._app = create_app()
        self._app.state.on_audio = self._on_audio_ws
        self._app.state.on_control = self._on_control_ws
        self._app.state.db_conn = self._db_conn

        self._lifecycle = AgentLifecycle.ACTIVE
        logger.info("All components initialized (serve mode)")

    async def _on_audio_ws(self, audio: bytes) -> None:
        if self._conversation:
            await self._conversation.handle_audio_chunk(audio)

    async def _on_control_ws(self, data: dict) -> None:
        msg_type = data.get("type", "")
        if msg_type == "dismiss" and self._conversation:
            await self._conversation.dismiss()

    def _on_hotkey(self) -> None:
        logger.info("Hotkey pressed")

    def start(self) -> None:
        """Initialize and start WebSocket server (serve mode)."""
        self._init_components()
        import uvicorn
        logger.info(
            "Server on %s:%d",
            self.config.transport.host, self.config.transport.port,
        )
        uvicorn.run(
            self._app,
            host=self.config.transport.host,
            port=self.config.transport.port,
        )

    # ------------------------------------------------------------------
    #  Database helpers
    # ------------------------------------------------------------------

    def start_conversation(self) -> str:
        """Create a new conversation record, return conversation_id."""
        conv_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        if self._db_conn:
            self._db_conn.execute(
                "INSERT INTO conversations "
                "(id, started_at, voice_profile) VALUES (?, ?, ?)",
                (conv_id, now, self.config.tts.voice_name),
            )
            self._db_conn.commit()
        self._current_conversation_id = conv_id
        logger.info("Conversation started: %s", conv_id)
        return conv_id

    def log_turn(
        self,
        conversation_id: str,
        role: str,
        text: str,
        asr_ms: float | None = None,
        llm_ttft_ms: float | None = None,
        tts_ttfb_ms: float | None = None,
        total_ms: float | None = None,
    ) -> str:
        """Log a turn to the database. Returns turn_id."""
        turn_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        if self._db_conn:
            self._db_conn.execute(
                "INSERT INTO turns "
                "(id, conversation_id, role, text, started_at,"
                " asr_ms, llm_ttft_ms, tts_ttfb_ms, total_ms)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    turn_id, conversation_id, role, text, now,
                    asr_ms, llm_ttft_ms, tts_ttfb_ms, total_ms,
                ),
            )
            self._db_conn.execute(
                "UPDATE conversations "
                "SET turn_count = turn_count + 1 WHERE id = ?",
                (conversation_id,),
            )
            self._db_conn.commit()
        return turn_id

    def _close_db(self) -> None:
        if self._db_conn:
            with contextlib.suppress(Exception):
                self._db_conn.close()
            self._db_conn = None

    # ------------------------------------------------------------------
    #  Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Release ALL resources."""
        logger.info("Shutting down...")
        if self._initialized:
            self._unload_models()

        if self._hotkey:
            with contextlib.suppress(Exception):
                self._hotkey.stop()
            self._hotkey = None

        self._close_db()
        self._wake_word = None
        self._transport = None
        self._local_transport = None
        self._app = None
        self._lifecycle = AgentLifecycle.DORMANT
        logger.info("Shutdown complete")
