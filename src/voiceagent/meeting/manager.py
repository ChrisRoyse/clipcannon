"""Clone Meeting Manager -- top-level orchestrator.

Wires all meeting components into a running clone pipeline:
Audio Capture -> Transcriber -> Address Detector -> Responder ->
Voice Output -> Meeting Behavior -> Webcam Writer

Supports Mode 1 (virtual device -- replace me) and Mode 2 (bot join -- placeholder).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from voiceagent.meeting.address_detector import AddressDetector
from voiceagent.meeting.audio_capture import MeetingAudioCapture
from voiceagent.meeting.config import (
    CloneConfig,
    MeetingConfig,
    load_meeting_config,
)
from voiceagent.meeting.devices import CloneDeviceManager
from voiceagent.meeting.errors import MeetingError
from voiceagent.meeting.meeting_behavior import MeetingBehavior
from voiceagent.meeting.meeting_summary import MeetingSummaryGenerator
from voiceagent.meeting.responder import MeetingResponder
from voiceagent.meeting.transcript_format import (
    CloneInteraction,
    MeetingSegment,
)
from voiceagent.meeting.transcript_store import MeetingTranscriptStore
from voiceagent.meeting.transcriber import MeetingTranscriber
from voiceagent.meeting.voice_output import MeetingVoiceOutput

logger = logging.getLogger(__name__)


@dataclass
class CloneInstance:
    """A running clone with all pipeline components."""

    clone_name: str
    meeting_id: str
    config: MeetingConfig
    clone_config: CloneConfig
    transcript_store: MeetingTranscriptStore
    audio_capture: MeetingAudioCapture
    transcriber: MeetingTranscriber
    address_detector: AddressDetector
    responder: MeetingResponder
    voice_output: MeetingVoiceOutput
    behavior: MeetingBehavior
    device_manager: CloneDeviceManager
    summary_generator: MeetingSummaryGenerator
    recent_segments: list[MeetingSegment] = field(default_factory=list)
    _running: bool = False
    _flush_task: asyncio.Task | None = None


class CloneMeetingManager:
    """Orchestrate one or more meeting clones.

    Lifecycle: start_clone() -> pipeline runs -> stop_clone().
    Pipeline: audio -> transcribe -> detect -> respond -> speak.
    Supports Mode 1 (virtual device) and Mode 2 (bot join -- placeholder).
    """

    def __init__(self, config: MeetingConfig | None = None) -> None:
        self._config = config or load_meeting_config()
        self._clones: dict[str, CloneInstance] = {}
        self._device_manager = CloneDeviceManager()

    # ------------------------------------------------------------------
    # Mode 1: Virtual device (Replace Me)
    # ------------------------------------------------------------------

    async def start_clone(
        self,
        clone_name: str,
        voice_profile: str | None = None,
        driver_video: str | None = None,
        platform: str = "unknown",
    ) -> CloneInstance:
        """Start a clone for Mode 1 (virtual device).

        Creates all pipeline components, starts audio capture,
        and begins the transcribe-detect-respond loop.
        """
        if clone_name in self._clones:
            raise MeetingError(f"Clone '{clone_name}' is already running")

        voice = voice_profile or clone_name
        clone_cfg = self._config.clones.get(
            clone_name, CloneConfig(voice_profile=voice),
        )

        # Create transcript store
        store = MeetingTranscriptStore(config=self._config.transcript)
        meeting_id = store.create_meeting(
            clone_names=[clone_name], platform=platform,
        )

        meeting_start_ms = int(time.time() * 1000)

        # Create transcriber with segment callback
        transcriber = MeetingTranscriber(
            config=self._config.transcription,
            on_segment=lambda seg: self._on_segment(clone_name, seg),
            meeting_start_ms=meeting_start_ms,
        )

        # Create audio capture wired to transcriber
        audio_capture = MeetingAudioCapture(
            config=self._config.audio_capture,
            on_audio=transcriber.feed_audio,
        )

        # Create detection + response pipeline with OCR Provenance RAG
        detector = AddressDetector(clone_name, clone_cfg)
        responder = MeetingResponder(
            config=self._config.response,
            clone_name=clone_name,
            ocr_client=store._client,  # Share the OCR Provenance connection
        )
        voice_out = MeetingVoiceOutput(
            config=self._config.voice, clone_name=voice,
        )
        behavior = MeetingBehavior(
            config=self._config.behavior, platform=platform,
        )
        summary_gen = MeetingSummaryGenerator()

        # Create virtual audio devices
        self._device_manager.create_audio_devices(clone_name)

        instance = CloneInstance(
            clone_name=clone_name,
            meeting_id=meeting_id,
            config=self._config,
            clone_config=clone_cfg,
            transcript_store=store,
            audio_capture=audio_capture,
            transcriber=transcriber,
            address_detector=detector,
            responder=responder,
            voice_output=voice_out,
            behavior=behavior,
            device_manager=self._device_manager,
            summary_generator=summary_gen,
        )
        instance._running = True
        self._clones[clone_name] = instance

        # Start audio capture (spawns background thread)
        audio_capture.start()

        # Start periodic flush task
        instance._flush_task = asyncio.create_task(
            self._flush_loop(clone_name),
        )

        # Recover any stale transcripts from previous crashes
        recovered = await store.recover_stale_transcripts()
        if recovered > 0:
            logger.info("Recovered %d stale transcripts", recovered)

        logger.info(
            "Clone '%s' started (meeting=%s, platform=%s)",
            clone_name, meeting_id, platform,
        )
        return instance

    # ------------------------------------------------------------------
    # Mode 2: Bot join (placeholder)
    # ------------------------------------------------------------------

    async def join_meeting(
        self,
        meeting_url: str,
        display_name: str,
        clone_name: str,
        voice_profile: str | None = None,
    ) -> CloneInstance:
        """Join a meeting as a bot participant (Mode 2 -- placeholder)."""
        raise MeetingError(
            "Mode 2 (bot join) is not yet implemented. "
            f"URL: {meeting_url}, display: {display_name}, "
            f"clone: {clone_name}. "
            "Use Mode 1 (virtual device) with start_clone() instead."
        )

    # ------------------------------------------------------------------
    # Pipeline callbacks
    # ------------------------------------------------------------------

    def _on_segment(self, clone_name: str, segment: MeetingSegment) -> None:
        """Callback from transcriber. Runs in audio thread -- must be thread-safe."""
        instance = self._clones.get(clone_name)
        if instance is None or not instance._running:
            return

        # Store segment in transcript
        instance.transcript_store.append_segment(
            instance.meeting_id, segment,
        )
        instance.recent_segments.append(segment)

        # Keep last 40 segments for context window — slice in-place to
        # avoid creating a new list object and leaking the old one
        if len(instance.recent_segments) > 50:
            del instance.recent_segments[:len(instance.recent_segments) - 40]

        # Check if clone is addressed
        result = instance.address_detector.check_segment(
            segment, recent_context=instance.recent_segments,
        )

        if result.is_addressed:
            # Schedule async response on the event loop (thread-safe)
            try:
                loop = asyncio.get_event_loop()
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(
                        self._handle_address(
                            clone_name,
                            result.extracted_question,
                            segment,
                            result.confidence,
                        )
                    )
                )
            except RuntimeError:
                logger.error(
                    "No event loop available for response scheduling"
                )

    async def _handle_address(
        self,
        clone_name: str,
        question: str,
        trigger_segment: MeetingSegment,
        address_confidence: float,
    ) -> None:
        """Handle address: LLM response -> TTS (SECS >0.95) -> unmute -> play -> mute."""
        instance = self._clones.get(clone_name)
        if instance is None or not instance._running:
            return

        response_start_ms = int(time.time() * 1000)

        try:
            # Generate LLM response
            response_text = await instance.responder.generate_response(
                question=question,
                meeting_context=instance.recent_segments[-20:],
            )

            # Synthesize voice with SECS >0.95
            audio, secs_score, prosody_style = (
                await instance.voice_output.synthesize_verified(
                    text=response_text,
                )
            )

            response_end_ms = int(time.time() * 1000)
            latency_ms = response_end_ms - response_start_ms

            # Record the interaction
            interaction = CloneInteraction(
                clone_name=clone_name,
                question_text=question,
                response_text=response_text,
                questioner=trigger_segment.speaker_name,
                question_at_ms=trigger_segment.start_ms,
                response_at_ms=trigger_segment.end_ms + 500,
                latency_ms=latency_ms,
                secs_score=secs_score,
                prosody_style=prosody_style,
                address_confidence=address_confidence,
            )
            instance.transcript_store.record_interaction(
                instance.meeting_id, interaction,
            )

            # Add clone response as a transcript segment
            audio_duration_ms = int(len(audio) / 44100 * 1000)
            response_segment = MeetingSegment(
                start_ms=trigger_segment.end_ms + 500,
                end_ms=trigger_segment.end_ms + 500 + audio_duration_ms,
                text=response_text,
                speaker_name=f"{clone_name.title()} (Clone)",
                is_clone=True,
                clone_name=clone_name,
                segment_type="response",
                secs_score=secs_score,
            )
            instance.transcript_store.append_segment(
                instance.meeting_id, response_segment,
            )

            # Unmute, play audio, re-mute
            async def play_audio(a):
                # Routes to PulseAudio sink in production
                logger.info(
                    "Playing %d samples of clone audio", len(a),
                )

            await instance.behavior.unmute_and_speak(audio, play_audio)

            logger.info(
                "Clone '%s' responded: SECS=%.3f, prosody=%s, "
                "latency=%dms, text='%s'",
                clone_name, secs_score, prosody_style,
                latency_ms, response_text[:80],
            )

        except MeetingError as e:
            logger.error(
                "Clone '%s' response failed: %s", clone_name, e,
            )

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------

    async def _flush_loop(self, clone_name: str) -> None:
        """Periodically flush transcript to disk and ingest into OCR Provenance.

        Two operations on each cycle:
        1. Flush to local disk for crash safety
        2. Ingest partial transcript into OCR Provenance for live search
        """
        instance = self._clones.get(clone_name)
        if instance is None:
            return

        interval = self._config.transcript.flush_interval_seconds
        ingest_counter = 0
        while instance._running:
            await asyncio.sleep(interval)
            if not instance._running:
                break
            try:
                if instance.transcript_store.should_flush(
                    instance.meeting_id,
                ):
                    instance.transcript_store.flush(instance.meeting_id)

                # Ingest into OCR Provenance every 3rd flush cycle
                # for live search capability without overwhelming the server
                ingest_counter += 1
                if ingest_counter >= 3:
                    ingest_counter = 0
                    await instance.transcript_store.ingest_partial(
                        instance.meeting_id,
                    )
            except MeetingError as e:
                logger.error(
                    "Flush failed for '%s': %s", clone_name, e,
                )

    # ------------------------------------------------------------------
    # Stop / cleanup
    # ------------------------------------------------------------------

    async def stop_clone(self, clone_name: str) -> str | None:
        """Stop a clone: capture -> flush -> summary -> ingest -> GPU release -> devices -> MCP close."""
        instance = self._clones.pop(clone_name, None)
        if instance is None:
            logger.warning("Clone '%s' is not running", clone_name)
            return None

        instance._running = False

        # Cancel flush task
        if instance._flush_task is not None:
            instance._flush_task.cancel()
            try:
                await instance._flush_task
            except asyncio.CancelledError:
                pass

        # Stop audio capture (joins background thread)
        instance.audio_capture.stop()

        # Flush remaining audio in transcription buffer
        instance.transcriber.flush()

        # Generate summary
        summary = ""
        tags: list[str] = []
        doc = instance.transcript_store._active_meetings.get(
            instance.meeting_id,
        )
        if (
            doc
            and doc.segments
            and self._config.transcript.auto_summary
        ):
            try:
                summary = (
                    await instance.summary_generator.generate_summary(
                        doc.segments,
                    )
                )
                if self._config.transcript.auto_tag:
                    tags = (
                        await instance.summary_generator.extract_topics(
                            summary,
                        )
                    )
            except MeetingError as e:
                logger.error("Summary generation failed: %s", e)

        # End meeting -- ingest into OCR Provenance, delete local file
        doc_id = None
        try:
            doc_id = await instance.transcript_store.end_meeting(
                instance.meeting_id, summary=summary, tags=tags,
            )
        except MeetingError as e:
            logger.error(
                "Meeting end failed for '%s': %s", clone_name, e,
            )

        # Release GPU resources
        instance.voice_output.release()
        instance.transcriber.release()

        # Destroy virtual audio devices
        self._device_manager.destroy_audio_devices(clone_name)

        # Close MCP client
        await instance.transcript_store.close()

        logger.info(
            "Clone '%s' stopped (doc_id=%s)", clone_name, doc_id,
        )
        return doc_id

    async def stop_all(self) -> None:
        """Stop all running clones."""
        for name in list(self._clones.keys()):
            await self.stop_clone(name)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def list_clones(self) -> list[str]:
        """List names of running clones."""
        return list(self._clones.keys())

    def get_clone(self, clone_name: str) -> CloneInstance | None:
        """Get a running clone instance by name."""
        return self._clones.get(clone_name)

    async def list_meetings(self, limit: int = 50) -> dict:
        """List past meetings from OCR Provenance."""
        store = MeetingTranscriptStore(config=self._config.transcript)
        try:
            return await store.list_meetings(limit=limit)
        finally:
            await store.close()

    async def search_meetings(self, query: str, limit: int = 20) -> dict:
        """Semantic + full-text hybrid search across meeting transcripts."""
        store = MeetingTranscriptStore(config=self._config.transcript)
        try:
            return await store.search(query=query, limit=limit)
        finally:
            await store.close()
