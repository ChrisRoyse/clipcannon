"""VoiceAgent -- top-level orchestrator wiring all Phase 1 components."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from voiceagent.config import VoiceAgentConfig, load_config
from voiceagent.errors import VoiceAgentError

logger = logging.getLogger(__name__)


class VoiceAgent:
    """Top-level orchestrator for the voice agent.

    Wires: config -> DB -> ASR -> LLM -> TTS -> ConversationManager -> Transport -> Activation.

    Usage:
        agent = VoiceAgent()          # loads config only
        agent._init_components()      # loads GPU models
        agent.start()                 # starts server
        agent.shutdown()              # releases everything
    """

    def __init__(self, config: VoiceAgentConfig | None = None) -> None:
        self.config = config or load_config()
        self._db_conn = None
        self._asr = None
        self._brain = None
        self._tts_adapter = None
        self._tts = None
        self._conversation = None
        self._wake_word = None
        self._hotkey = None
        self._transport = None
        self._app = None
        self._current_conversation_id: str | None = None
        self._initialized = False
        logger.info("VoiceAgent created (config loaded, models NOT loaded)")

    def _init_components(self) -> None:
        """Initialize all components and load GPU models."""
        if self._initialized:
            logger.warning("Components already initialized")
            return

        logger.info("Initializing components...")

        # Database
        from voiceagent.db.schema import init_db
        from voiceagent.db.connection import get_connection
        data_dir = Path(self.config.data_dir).expanduser()
        db_path = data_dir / "agent.db"
        init_db(db_path)
        self._db_conn = get_connection(db_path)
        logger.info("Database initialized at %s", db_path)

        # ASR (VAD + Whisper)
        from voiceagent.asr.streaming import StreamingASR
        self._asr = StreamingASR(self.config.asr)
        logger.info("ASR initialized")

        # LLM Brain
        from voiceagent.brain.llm import LLMBrain
        self._brain = LLMBrain(self.config.llm)
        logger.info("LLM Brain initialized")

        # System prompt
        from voiceagent.brain.prompts import build_system_prompt
        self._system_prompt = build_system_prompt(self.config.tts.voice_name)

        # Context manager
        from voiceagent.brain.context import ContextManager
        self._context = ContextManager(tokenizer_path=self.config.llm.model_path)

        # TTS (ClipCannon adapter + sentence chunker + streaming TTS)
        from voiceagent.adapters.clipcannon import ClipCannonAdapter
        from voiceagent.tts.chunker import SentenceChunker
        from voiceagent.tts.streaming import StreamingTTS
        self._tts_adapter = ClipCannonAdapter(voice_name=self.config.tts.voice_name)
        self._tts = StreamingTTS(self._tts_adapter, SentenceChunker())
        logger.info("TTS initialized with voice '%s'", self.config.tts.voice_name)

        # Transport
        from voiceagent.transport.websocket import WebSocketTransport
        self._transport = WebSocketTransport(
            host=self.config.transport.host,
            port=self.config.transport.port,
        )

        # Conversation manager
        from voiceagent.conversation.manager import ConversationManager
        self._conversation = ConversationManager(
            asr=self._asr,
            brain=self._brain,
            tts=self._tts,
            transport=self._transport,
            context_manager=self._context,
            system_prompt=self._system_prompt,
        )
        logger.info("Conversation manager initialized")

        # Activation (wake word + hotkey) -- optional, don't fail if unavailable
        try:
            from voiceagent.activation.wake_word import WakeWordDetector
            self._wake_word = WakeWordDetector(threshold=0.6)
            logger.info("Wake word detector initialized")
        except Exception as e:
            logger.warning("Wake word detector unavailable: %s", e)

        try:
            from voiceagent.activation.hotkey import HotkeyActivator
            self._hotkey = HotkeyActivator(callback=self._on_hotkey)
            logger.info("Hotkey activator initialized")
        except Exception as e:
            logger.warning("Hotkey activator unavailable: %s", e)

        # Server app
        from voiceagent.server import create_app
        self._app = create_app()
        self._app.state.on_audio = self._on_audio
        self._app.state.on_control = self._on_control
        self._app.state.db_conn = self._db_conn

        self._initialized = True
        logger.info("All components initialized successfully")

    async def _on_audio(self, audio) -> None:
        """Handle incoming audio from WebSocket."""
        if self._conversation:
            await self._conversation.handle_audio_chunk(audio)

    async def _on_control(self, data: dict) -> None:
        """Handle control messages from WebSocket."""
        msg_type = data.get("type", "")
        if msg_type == "dismiss":
            if self._conversation:
                await self._conversation.dismiss()
        logger.debug("Control message: %s", data)

    def _on_hotkey(self) -> None:
        """Hotkey callback -- placeholder for activation."""
        logger.info("Hotkey pressed")

    def start_conversation(self) -> str:
        """Start a new conversation, return conversation_id."""
        conv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        if self._db_conn:
            self._db_conn.execute(
                "INSERT INTO conversations (id, started_at, voice_profile) VALUES (?, ?, ?)",
                (conv_id, now, self.config.tts.voice_name),
            )
            self._db_conn.commit()
        self._current_conversation_id = conv_id
        logger.info("Started conversation %s", conv_id)
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
        now = datetime.now(timezone.utc).isoformat()
        if self._db_conn:
            self._db_conn.execute(
                "INSERT INTO turns (id, conversation_id, role, text, started_at, asr_ms, llm_ttft_ms, tts_ttfb_ms, total_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (turn_id, conversation_id, role, text, now, asr_ms, llm_ttft_ms, tts_ttfb_ms, total_ms),
            )
            self._db_conn.execute(
                "UPDATE conversations SET turn_count = turn_count + 1 WHERE id = ?",
                (conversation_id,),
            )
            self._db_conn.commit()
        logger.info("Logged turn %s (%s) for conversation %s", turn_id, role, conversation_id)
        return turn_id

    def start(self) -> None:
        """Initialize components and start the server."""
        self._init_components()
        import uvicorn
        logger.info("Starting server on %s:%d", self.config.transport.host, self.config.transport.port)
        uvicorn.run(self._app, host=self.config.transport.host, port=self.config.transport.port)

    async def talk_interactive(self) -> None:
        """Interactive local mic conversation (placeholder for Phase 1)."""
        self._init_components()
        logger.info("Interactive talk mode -- use WebSocket client to connect")
        await self._transport.start(self._on_audio, self._on_control)

    def shutdown(self) -> None:
        """Release ALL GPU resources and close DB."""
        logger.info("Shutting down VoiceAgent...")

        if self._brain:
            try:
                self._brain.release()
            except Exception as e:
                logger.warning("Error releasing LLM: %s", e)
            self._brain = None

        if self._tts_adapter:
            try:
                self._tts_adapter.release()
            except Exception as e:
                logger.warning("Error releasing TTS: %s", e)
            self._tts_adapter = None

        if self._hotkey:
            try:
                self._hotkey.stop()
            except Exception:
                pass
            self._hotkey = None

        if self._db_conn:
            try:
                self._db_conn.close()
            except Exception:
                pass
            self._db_conn = None

        self._asr = None
        self._tts = None
        self._conversation = None
        self._wake_word = None
        self._transport = None
        self._app = None
        self._initialized = False

        try:
            import torch
            torch.cuda.empty_cache()
        except ImportError:
            pass

        logger.info("VoiceAgent shutdown complete")
