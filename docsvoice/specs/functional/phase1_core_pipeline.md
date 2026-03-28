# Functional Specification: Phase 1 -- Core Voice Pipeline

```xml
<functional_spec id="SPEC-VOICE-P1" version="1.0">
<metadata>
  <title>Phase 1: Core Voice Pipeline</title>
  <status>draft</status>
  <owner>Chris Royse</owner>
  <created_date>2026-03-28</created_date>
  <last_updated>2026-03-28</last_updated>
  <timeline>Weeks 1-3</timeline>
  <related_specs>
    <spec_ref>SPEC-VOICE-P2 (Phase 2: Companion + Screen Capture -- future)</spec_ref>
    <spec_ref>SPEC-VOICE-P3 (Phase 3: Memory + OCR Provenance -- future)</spec_ref>
  </related_specs>
  <source_documents>
    <source type="prd">docsvoice/prd_voice_agent.md (v3.0)</source>
    <source type="implementation">docsvoice/01_phase1_core_pipeline.md</source>
  </source_documents>
</metadata>

<!-- ================================================================== -->
<!--                            OVERVIEW                                -->
<!-- ================================================================== -->

<overview>
Phase 1 builds the foundational voice conversation loop for the Voice Agent: the
user speaks into a microphone, the agent transcribes speech via streaming ASR,
reasons about it with a local LLM, and speaks back in the user's cloned voice via
ClipCannon TTS. The complete pipeline is: Mic Audio -> Silero VAD -> Distil-Whisper
Large v3 (streaming ASR) -> Qwen3-14B-FP8 (LLM Brain) -> ClipCannon TTS (streaming
sentence chunks) -> Audio Output.

This phase exists to prove end-to-end voice interaction works with sub-500ms P95
latency entirely on local hardware (RTX 5090, no cloud dependencies). It establishes
the core pipeline that all subsequent phases (companion, memory, intelligence,
hardening) build upon.

The primary beneficiary is Chris Royse, who will use this as a voice-first personal
AI assistant. The secondary beneficiary is Chris as developer, who needs CLI tools,
debugging access, and configuration control to iterate on the system.

Phase 1 scope is intentionally narrow: no memory system, no screen capture, no dream
state, no tool calling, no ambient audio, no clipboard. Just the core ASR -> LLM ->
TTS -> audio pipeline with conversation state management, WebSocket transport, wake
word activation, and SQLite persistence.
</overview>

<!-- ================================================================== -->
<!--                          USER TYPES                                -->
<!-- ================================================================== -->

<user_types>
  <user_type id="UT-01" name="Chris Royse (Primary User)">
    <description>The sole end-user of the voice agent. Interacts exclusively via
    voice (microphone input, speaker output). Expects responses in their own cloned
    voice ("boris" profile). Uses wake word or hotkey to activate the agent.</description>
    <permissions>Full conversational access. Can activate/dismiss the agent, speak
    freely, and receive spoken responses. No admin actions required in Phase 1.</permissions>
    <goals>Have natural voice conversations with a local AI assistant that responds
    quickly (<500ms) in a voice clone indistinguishable from their own speech.</goals>
  </user_type>

  <user_type id="UT-02" name="Developer (Self)">
    <description>Chris Royse in a development capacity. Accesses the system via CLI
    commands, reads logs, modifies configuration, and debugs pipeline components.</description>
    <permissions>Full system access: CLI commands, config editing, database inspection,
    log reading, model path configuration.</permissions>
    <goals>Start/stop the agent via CLI, configure models and parameters, inspect
    conversation logs in SQLite, verify latency metrics, and iterate on pipeline
    components.</goals>
  </user_type>
</user_types>

<!-- ================================================================== -->
<!--                        USER STORIES                                -->
<!-- ================================================================== -->

<user_stories>

  <!-- =================== ACTIVATION =================== -->

  <story id="US-WAKE-01" priority="must-have">
    <narrative>
      <as_a>Primary User</as_a>
      <i_want_to>say a wake word to activate the voice agent from dormant state</i_want_to>
      <so_that>I can start a conversation hands-free without touching my computer</so_that>
    </narrative>
    <acceptance_criteria>
      <criterion id="AC-WAKE-01">
        <given>The agent is in DORMANT state with only wake word detector running on CPU</given>
        <when>I say "Hey Jarvis" (or configured wake phrase) with >0.6 confidence</when>
        <then>
          - Agent transitions to LOADING state
          - Qwen3-14B, Whisper, and TTS models load to GPU (~5-10 seconds)
          - Agent speaks "I'm here" in the boris voice
          - Agent transitions to LISTENING state (IDLE within active)
          - GPU memory increases by >5GB (models loaded)
        </then>
      </criterion>
      <criterion id="AC-WAKE-02">
        <given>The agent is in DORMANT state</given>
        <when>Background noise or non-wake-word speech occurs</when>
        <then>
          - Wake word detector returns confidence below 0.6
          - Agent remains in DORMANT state
          - No models are loaded
          - GPU memory stays at 0 bytes for voice agent
        </then>
      </criterion>
    </acceptance_criteria>
  </story>

  <story id="US-WAKE-02" priority="must-have">
    <narrative>
      <as_a>Primary User</as_a>
      <i_want_to>press a hotkey (Ctrl+Space) to activate the voice agent</i_want_to>
      <so_that>I have a reliable fallback when wake word detection is unreliable</so_that>
    </narrative>
    <acceptance_criteria>
      <criterion id="AC-WAKE-03">
        <given>The agent is in DORMANT state</given>
        <when>I press Ctrl+Space (or configured hotkey)</when>
        <then>
          - Same activation flow as wake word: DORMANT -> LOADING -> models load -> "I'm here" -> LISTENING
        </then>
      </criterion>
    </acceptance_criteria>
  </story>

  <story id="US-WAKE-03" priority="must-have">
    <narrative>
      <as_a>Primary User</as_a>
      <i_want_to>say "Go to sleep" to dismiss the agent and unload all models</i_want_to>
      <so_that>I free up GPU memory for other tasks when I am done talking</so_that>
    </narrative>
    <acceptance_criteria>
      <criterion id="AC-WAKE-04">
        <given>The agent is in ACTIVE state (IDLE/LISTENING)</given>
        <when>I say "Go to sleep" (or configured dismiss keyword)</when>
        <then>
          - Agent speaks "Going to sleep" in boris voice
          - Agent transitions to UNLOADING state
          - All models unloaded from GPU (model.cpu() + del + torch.cuda.empty_cache())
          - Agent transitions to DORMANT state
          - GPU memory returns to 0 bytes for voice agent
          - Wake word detector continues running on CPU
        </then>
      </criterion>
    </acceptance_criteria>
  </story>

  <!-- =================== CONVERSATION =================== -->

  <story id="US-CONV-01" priority="must-have">
    <narrative>
      <as_a>Primary User</as_a>
      <i_want_to>speak naturally and receive a spoken response from the agent in my cloned voice</i_want_to>
      <so_that>I can have a natural voice conversation with my AI assistant</so_that>
    </narrative>
    <acceptance_criteria>
      <criterion id="AC-CONV-01">
        <given>The agent is in LISTENING state with all models loaded</given>
        <when>I speak a question or statement and then pause for 600ms</when>
        <then>
          - VAD detects speech and buffers audio
          - 600ms of silence triggers endpoint detection
          - Final ASR transcript produced with beam_size=5
          - Agent transitions to THINKING state
          - LLM generates a response using conversation history
          - Agent transitions to SPEAKING state
          - TTS synthesizes response in boris voice as streaming sentence chunks
          - Audio plays back to user
          - Agent transitions back to LISTENING state
          - Full response text accumulated and added to conversation history
          - Turn recorded in SQLite with timestamps and latency
        </then>
      </criterion>
      <criterion id="AC-CONV-02">
        <given>The agent is in LISTENING state</given>
        <when>I speak continuously for several sentences</when>
        <then>
          - Partial transcripts emitted every 200ms (beam_size=1) during speech
          - No endpoint triggered until 600ms silence
          - Final transcript uses beam_size=5 for accuracy
        </then>
      </criterion>
    </acceptance_criteria>
  </story>

  <story id="US-CONV-02" priority="must-have">
    <narrative>
      <as_a>Primary User</as_a>
      <i_want_to>have multi-turn conversations where the agent remembers what I said earlier in the session</i_want_to>
      <so_that>I can have coherent back-and-forth dialogue without repeating context</so_that>
    </narrative>
    <acceptance_criteria>
      <criterion id="AC-CONV-03">
        <given>I have had 5 turns of conversation with the agent</given>
        <when>I reference something from turn 2 (e.g., "What was that thing I asked about earlier?")</when>
        <then>
          - Context manager includes previous turns in the LLM prompt
          - Agent responds with awareness of previous conversation context
          - Context window stays within 32K token budget
        </then>
      </criterion>
      <criterion id="AC-CONV-04">
        <given>Conversation has exceeded the history token budget (~29.5K tokens)</given>
        <when>I ask a new question</when>
        <then>
          - Oldest turns are truncated from context
          - Most recent turns preserved
          - System prompt always included
          - LLM does not error or produce garbled output
          - Total context stays under 32K tokens
        </then>
      </criterion>
    </acceptance_criteria>
  </story>

  <!-- =================== TRANSPORT =================== -->

  <story id="US-WS-01" priority="must-have">
    <narrative>
      <as_a>Developer</as_a>
      <i_want_to>connect to the voice agent via WebSocket and send/receive audio</i_want_to>
      <so_that>I can build clients that communicate with the agent over the network</so_that>
    </narrative>
    <acceptance_criteria>
      <criterion id="AC-WS-01">
        <given>The agent server is running via `voiceagent serve`</given>
        <when>A WebSocket client connects to ws://localhost:8765/conversation</when>
        <then>
          - Connection established with HTTP 101 Switching Protocols
          - Client can send binary data (16kHz 16-bit mono PCM audio)
          - Client can send text data (JSON control messages)
          - Server sends back binary data (24kHz 16-bit mono PCM audio)
          - Server sends back text data (JSON events: transcript, agent_text, state, metrics, end)
        </then>
      </criterion>
      <criterion id="AC-WS-02">
        <given>A WebSocket client is connected and mid-conversation</given>
        <when>The client disconnects unexpectedly</when>
        <then>
          - Server detects disconnection
          - Current conversation state is saved to SQLite
          - All resources for that connection are cleaned up
          - Server continues running and accepting new connections
          - No crash, no memory leak, no orphaned GPU tensors
        </then>
      </criterion>
    </acceptance_criteria>
  </story>

  <!-- =================== CLI =================== -->

  <story id="US-CLI-01" priority="must-have">
    <narrative>
      <as_a>Developer</as_a>
      <i_want_to>start the voice agent server with `voiceagent serve`</i_want_to>
      <so_that>I can run the agent as a WebSocket service accepting remote connections</so_that>
    </narrative>
    <acceptance_criteria>
      <criterion id="AC-CLI-01">
        <given>All dependencies are installed and models are available</given>
        <when>I run `voiceagent serve --voice boris --port 8765`</when>
        <then>
          - WebSocket server starts on port 8765
          - Wake word detector starts on CPU
          - Config loaded from ~/.voiceagent/config.json
          - SQLite database created/opened at ~/.voiceagent/agent.db
          - Server logs "Listening on ws://0.0.0.0:8765"
          - Server accepts WebSocket connections
        </then>
      </criterion>
    </acceptance_criteria>
  </story>

  <story id="US-CLI-02" priority="must-have">
    <narrative>
      <as_a>Developer</as_a>
      <i_want_to>have an interactive voice conversation via `voiceagent talk`</i_want_to>
      <so_that>I can test the full pipeline using my local microphone without a WebSocket client</so_that>
    </narrative>
    <acceptance_criteria>
      <criterion id="AC-CLI-02">
        <given>All dependencies are installed, microphone is available</given>
        <when>I run `voiceagent talk --voice boris`</when>
        <then>
          - Agent loads all models to GPU
          - Local microphone stream opens via sounddevice
          - Agent speaks "I'm here" when ready
          - I can speak and receive audio responses through speakers
          - Ctrl+C terminates cleanly (models unloaded, DB saved)
        </then>
      </criterion>
    </acceptance_criteria>
  </story>

  <!-- =================== PERSISTENCE =================== -->

  <story id="US-DB-01" priority="must-have">
    <narrative>
      <as_a>Developer</as_a>
      <i_want_to>see all conversations and turns logged in SQLite</i_want_to>
      <so_that>I can review conversation history, debug issues, and measure latency</so_that>
    </narrative>
    <acceptance_criteria>
      <criterion id="AC-DB-01">
        <given>I have completed a conversation with the agent (at least 1 user turn + 1 agent turn)</given>
        <when>I query `SELECT * FROM conversations` and `SELECT * FROM turns`</when>
        <then>
          - conversations table has 1 row with: id (UUID), voice_profile ("boris"), started_at (ISO 8601), status ("completed" or "active"), turns count
          - turns table has at least 2 rows: 1 user turn and 1 agent turn
          - Each turn has: conversation_id, turn_number, role, text, started_at, duration_ms, latency_ms
          - User turns have asr_confidence populated
          - Agent turns have latency_ms populated (time from user speech end to first audio byte)
        </then>
      </criterion>
      <criterion id="AC-DB-02">
        <given>A conversation is in progress</given>
        <when>I query `SELECT * FROM metrics`</when>
        <then>
          - Metrics table has rows for: asr_latency_ms, llm_first_token_ms, tts_first_chunk_ms, e2e_latency_ms
          - Each metric linked to conversation_id
          - recorded_at is ISO 8601 timestamp
        </then>
      </criterion>
    </acceptance_criteria>
  </story>

</user_stories>

<!-- ================================================================== -->
<!--                       REQUIREMENTS                                 -->
<!-- ================================================================== -->

<requirements>

  <!-- =================== ASR DOMAIN =================== -->

  <requirement id="REQ-ASR-01" story_ref="US-CONV-01" priority="must">
    <description>Silero VAD v5 detects speech in 16kHz 16-bit PCM audio chunks
    (200ms = 3200 samples) with less than 1ms processing latency per chunk.
    Threshold configurable (default 0.5). Runs on CPU via ONNX runtime.</description>
    <rationale>Speech detection must be faster than audio chunk arrival rate (200ms)
    to avoid buffering delays. CPU execution keeps GPU free for ASR/LLM/TTS.</rationale>
    <constraints>CPU only. ONNX runtime. Silero VAD v5. 200ms chunk size.</constraints>
    <verification_method>Measure process_chunk() wall-clock time over 1000 chunks.
    P99 must be under 1ms. Feed known speech audio and verify True returned. Feed
    silence and verify False returned.</verification_method>
  </requirement>

  <requirement id="REQ-ASR-02" story_ref="US-CONV-01" priority="must">
    <description>Streaming ASR produces partial transcripts every 200ms during
    active speech. Partial transcripts use beam_size=1 for speed. Model is
    Distil-Whisper Large v3 with INT8 compute type on GPU.</description>
    <rationale>Partial transcripts enable real-time feedback to clients via WebSocket
    (transcript events with final=false). beam_size=1 minimizes latency for
    non-final results.</rationale>
    <constraints>GPU (CUDA). INT8 quantization. faster-whisper library.</constraints>
    <verification_method>Feed continuous speech audio. Verify partial transcript
    events emitted at approximately 200ms intervals. Verify text contains recognizable
    words from the input audio.</verification_method>
  </requirement>

  <requirement id="REQ-ASR-03" story_ref="US-CONV-01" priority="must">
    <description>600ms of silence after detected speech triggers endpoint detection
    (user done talking). Silence duration configurable via
    config.asr.endpoint_silence_ms (default 600).</description>
    <rationale>600ms is the empirically optimal balance between cutting off the user
    mid-thought (too short) and adding perceptible delay (too long).</rationale>
    <constraints>Minimum 200ms (one chunk). Maximum 2000ms.</constraints>
    <verification_method>Feed speech audio followed by silence. Measure time from
    last speech chunk to endpoint event. Must be 600ms +/- 50ms (one chunk
    tolerance).</verification_method>
  </requirement>

  <requirement id="REQ-ASR-04" story_ref="US-CONV-01" priority="must">
    <description>Final transcript (after endpoint detection) uses beam_size=5 for
    maximum accuracy. The entire buffered audio is re-transcribed with beam_size=5
    to produce the final text.</description>
    <rationale>Final transcript feeds the LLM. Higher beam size produces more
    accurate text at the cost of ~100-200ms additional processing, acceptable since
    it runs once per turn.</rationale>
    <constraints>beam_size=5. Full audio buffer re-transcribed.</constraints>
    <verification_method>Compare word error rate of beam_size=1 vs beam_size=5 on
    a standard test utterance. beam_size=5 must produce equal or better accuracy.</verification_method>
  </requirement>

  <!-- =================== LLM DOMAIN =================== -->

  <requirement id="REQ-LLM-01" story_ref="US-CONV-01" priority="must">
    <description>Qwen3-14B loads via vLLM with FP8 quantization, configured for
    45% GPU memory utilization and 32768 max model length. Model path is
    /home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/
    9a283b4a5efbc09ce247e0ae5b02b744739e525a/.</description>
    <rationale>FP8 quantization fits within the 32GB VRAM budget alongside ASR and
    TTS models. 45% utilization leaves headroom for other models. vLLM provides
    continuous batching and optimized inference.</rationale>
    <constraints>GPU memory utilization capped at 45%. Model path from config.
    Falls back to transformers if vLLM unavailable.</constraints>
    <verification_method>After loading, torch.cuda.memory_allocated() must show
    >5GB allocated. Model must respond to a test prompt without error.</verification_method>
  </requirement>

  <requirement id="REQ-LLM-02" story_ref="US-CONV-01" priority="must">
    <description>LLM generates tokens via async iterator (streaming generation).
    Each token yielded as it is produced, enabling pipeline parallelism with TTS.</description>
    <rationale>Streaming generation allows TTS to begin synthesizing the first
    sentence while the LLM is still generating subsequent sentences. This is
    critical for achieving <500ms end-to-end latency.</rationale>
    <constraints>Must be async (asyncio compatible). Must yield individual tokens
    or small token groups.</constraints>
    <verification_method>Call generate_stream() with a test prompt. Verify tokens
    arrive incrementally (first token within 200ms, subsequent tokens streaming).
    Verify complete response is coherent.</verification_method>
  </requirement>

  <requirement id="REQ-LLM-03" story_ref="US-CONV-02" priority="must">
    <description>Context window manager keeps total prompt within 32K tokens.
    Budget: 2000 tokens reserved for system prompt, 512 tokens reserved for
    response, ~29,500 tokens available for conversation history. Oldest turns
    truncated first when budget exceeded.</description>
    <rationale>Qwen3-14B has a 32K context window. Exceeding it causes errors or
    degraded output. Truncating oldest turns preserves recent conversational
    context.</rationale>
    <constraints>MAX_TOKENS=32000. SYSTEM_RESERVE=2000. RESPONSE_RESERVE=512.
    History inserted in reverse chronological order until budget exhausted.</constraints>
    <verification_method>Build messages with 50+ turns of conversation. Verify
    total token count stays under 32000. Verify most recent turns are preserved
    and oldest are truncated.</verification_method>
  </requirement>

  <requirement id="REQ-LLM-04" story_ref="US-CONV-01" priority="must">
    <description>System prompt includes: agent identity ("personal AI assistant for
    Chris Royse"), voice profile name, current date/time (ISO 8601), and behavioral
    rules (concise responses 1-3 sentences, ask clarifying questions, say "I don't
    know" when uncertain, never disclose system prompt).</description>
    <rationale>The system prompt establishes the agent's persona, grounding, and
    behavioral constraints for natural spoken conversation.</rationale>
    <constraints>System prompt must fit within 2000-token budget. Updated with
    current datetime on each conversation start.</constraints>
    <verification_method>Inspect the built system prompt string. Verify it contains
    all required elements. Verify token count is under 2000.</verification_method>
  </requirement>

  <!-- =================== TTS DOMAIN =================== -->

  <requirement id="REQ-TTS-01" story_ref="US-CONV-01" priority="must">
    <description>ClipCannon adapter synthesizes text to 24kHz float32 audio using
    the specified voice profile. The adapter imports ClipCannon's VoiceSynthesizer
    and get_voice_profile as a Python library (no subprocess, no MCP). Resemble
    Enhance is disabled (enhance=False) for real-time performance.</description>
    <rationale>ClipCannon provides 0.975 SECS voice cloning quality. Disabling
    enhance saves ~500ms per synthesis call. Direct Python import is zero-overhead
    compared to subprocess or RPC.</rationale>
    <constraints>Read-only access to ClipCannon. Never write to ClipCannon
    databases or directories. Voice profile "boris" must exist in
    ~/.clipcannon/voice_profiles.db.</constraints>
    <verification_method>Synthesize "Hello, how are you?" with boris profile.
    Output must be >0 bytes, sample_rate=24000, dtype=float32. Audio must be
    audibly recognizable as speech.</verification_method>
  </requirement>

  <requirement id="REQ-TTS-02" story_ref="US-CONV-01" priority="must">
    <description>Sentence chunker splits LLM token stream on sentence boundaries:
    period (.), exclamation mark (!), question mark (?). Minimum 3 words per chunk.
    Maximum 50 words per chunk.</description>
    <rationale>Sentence-level chunking produces natural-sounding TTS output.
    Minimum word count prevents tiny fragments that sound choppy. Maximum prevents
    excessively long synthesis calls.</rationale>
    <constraints>MIN_WORDS=3, MAX_WORDS=50. Sentence-ending punctuation followed
    by space or newline.</constraints>
    <verification_method>"Hello. How are you?" produces 2 chunks: "Hello." and
    "How are you?". Single word "Hi." is buffered until more text arrives or
    flush.</verification_method>
  </requirement>

  <requirement id="REQ-TTS-03" story_ref="US-CONV-01" priority="must">
    <description>Long clauses (>60 characters) are split at comma (,), semicolon
    (;), or colon (:) separators when no sentence boundary is available. Minimum
    3 words per clause chunk.</description>
    <rationale>Prevents excessively long TTS synthesis calls when the LLM produces
    long comma-separated lists or compound sentences without periods.</rationale>
    <constraints>Only triggers when buffer exceeds 60 characters and contains a
    comma/semicolon/colon separator.</constraints>
    <verification_method>Feed a 100-character clause with commas but no periods.
    Verify it splits at the appropriate separator. Verify each chunk has at least
    3 words.</verification_method>
  </requirement>

  <requirement id="REQ-TTS-04" story_ref="US-CONV-01" priority="must">
    <description>Streaming TTS yields audio chunks as sentences complete from the
    LLM token stream. When the token stream ends, any remaining buffered text is
    flushed as a final TTS chunk.</description>
    <rationale>Streaming TTS enables audio playback to begin while the LLM is still
    generating, achieving pipeline parallelism and lower perceived latency.</rationale>
    <constraints>Must be async iterator. Must handle empty/whitespace-only flush
    gracefully (no TTS call for empty text).</constraints>
    <verification_method>Feed an LLM stream producing 3 sentences. Verify 3 audio
    chunks yielded. Verify audio plays in order without gaps.</verification_method>
  </requirement>

  <!-- =================== CONVERSATION MANAGEMENT =================== -->

  <requirement id="REQ-CONV-01" story_ref="US-CONV-01" priority="must">
    <description>Conversation manager implements a state machine with states:
    IDLE -> LISTENING -> THINKING -> SPEAKING -> LISTENING (loop). State transitions
    are deterministic: IDLE transitions to LISTENING on voice activity detection;
    LISTENING transitions to THINKING on ASR endpoint (final transcript); THINKING
    transitions to SPEAKING when first TTS audio chunk is ready; SPEAKING
    transitions to LISTENING when all audio has been sent.</description>
    <rationale>Explicit state machine prevents race conditions (e.g., processing
    audio while speaking) and provides clear state reporting to clients.</rationale>
    <constraints>No concurrent states. State transitions are atomic. State reported
    to WebSocket clients as JSON events.</constraints>
    <verification_method>Run a full conversation turn. Verify state transitions
    occur in the correct order. Verify no state is skipped. Verify WebSocket
    receives state change events.</verification_method>
  </requirement>

  <requirement id="REQ-CONV-02" story_ref="US-CONV-02" priority="must">
    <description>Conversation history maintained as a list of {role, content}
    message dicts. Each user turn and agent turn appended after completion.
    History is passed to the context manager for LLM prompt construction.</description>
    <rationale>Conversation history enables multi-turn dialogue where the agent
    can reference previous exchanges.</rationale>
    <constraints>History stored in memory during active conversation. Persisted to
    SQLite after each turn. History cleared when conversation ends.</constraints>
    <verification_method>After 5 turns, inspect history list. Must contain all 5
    user messages and 5 agent messages in order.</verification_method>
  </requirement>

  <requirement id="REQ-CONV-03" story_ref="US-CONV-01" priority="must">
    <description>Full agent response text accumulated across all streaming tokens
    before being added to conversation history. The accumulated text (not partial
    fragments) is stored as the agent's turn in history and SQLite.</description>
    <rationale>Incomplete or fragmented text in history would confuse subsequent
    LLM turns. Full text is needed for accurate history and logging.</rationale>
    <constraints>Text accumulation must not interfere with streaming TTS output.</constraints>
    <verification_method>After agent responds, verify history[-1]["content"] equals
    the complete response text. Verify SQLite turn text matches.</verification_method>
  </requirement>

  <!-- =================== WEBSOCKET TRANSPORT =================== -->

  <requirement id="REQ-WS-01" story_ref="US-WS-01" priority="must">
    <description>WebSocket server accepts two message types from clients: binary
    messages containing PCM audio (16kHz sample rate, 16-bit signed integer, mono
    channel) and text messages containing JSON control objects. Binary messages are
    routed to the audio processing pipeline. Text messages are parsed as JSON and
    routed to the control handler.</description>
    <rationale>Binary for audio avoids base64 encoding overhead (~33% size
    increase). JSON text for control messages provides structured metadata.</rationale>
    <constraints>Audio format: 16kHz, 16-bit, mono, little-endian PCM. JSON
    control types: {"type": "start", "voice": "boris"}, {"type": "end"}.</constraints>
    <verification_method>Connect a WebSocket client. Send a binary message of 6400
    bytes (200ms of 16kHz 16-bit audio). Verify server processes it without error.
    Send {"type": "start", "voice": "boris"} as text. Verify server acknowledges.</verification_method>
  </requirement>

  <requirement id="REQ-WS-02" story_ref="US-WS-01" priority="must">
    <description>WebSocket server sends two message types to clients: binary
    messages containing PCM audio (24kHz sample rate, 16-bit signed integer, mono
    channel) and text messages containing JSON event objects. Event types:
    "transcript" (partial/final ASR text), "agent_text" (LLM response text),
    "state" (state machine transitions), "metrics" (latency measurements),
    "end" (conversation ended).</description>
    <rationale>Clients need both audio output (for playback) and metadata (for UI
    display of transcripts, state indicators, and latency debugging).</rationale>
    <constraints>Audio format: 24kHz, 16-bit, mono, little-endian PCM. JSON event
    schema as defined in PRD Section 14.1.</constraints>
    <verification_method>Connect a WebSocket client. Speak a test phrase. Verify
    client receives: text message with type="transcript", text message with
    type="state" (THINKING, SPEAKING), binary audio data, text message with
    type="agent_text", text message with type="metrics".</verification_method>
  </requirement>

  <!-- =================== WAKE WORD / ACTIVATION =================== -->

  <requirement id="REQ-WAKE-01" story_ref="US-WAKE-01" priority="must">
    <description>OpenWakeWord detects the configured wake phrase (default
    "hey_jarvis" model) with confidence threshold >0.6. Runs on CPU via ONNX
    inference framework. Runs 24/7 in DORMANT state with approximately 50MB RAM
    and 3-5% single CPU core utilization.</description>
    <rationale>Wake word detection must be always-on and lightweight. CPU-only
    execution keeps GPU completely free in dormant state.</rationale>
    <constraints>CPU only. ONNX framework. ~50MB RAM. Threshold configurable
    (default 0.6, range 0.1-0.9).</constraints>
    <verification_method>Start agent in DORMANT state. Say wake phrase. Verify
    detection within 500ms of utterance end. Verify no false positives over 60
    seconds of background noise.</verification_method>
  </requirement>

  <requirement id="REQ-WAKE-02" story_ref="US-WAKE-02" priority="must">
    <description>pynput global hotkey listener (default Ctrl+Space) provides
    activation fallback. Configurable via config.activation.hotkey. Triggers the
    same model loading and activation flow as wake word detection.</description>
    <rationale>Wake word detection can be unreliable in noisy environments or with
    certain microphone configurations. Hotkey provides deterministic activation.</rationale>
    <constraints>pynput library. Global hotkey (works regardless of focused window).
    Default: Ctrl+Space. Configurable string format: "ctrl+space".</constraints>
    <verification_method>Start agent in DORMANT state. Press Ctrl+Space. Verify
    agent transitions to LOADING then ACTIVE. Verify models load successfully.</verification_method>
  </requirement>

  <!-- =================== DATABASE =================== -->

  <requirement id="REQ-DB-01" story_ref="US-DB-01" priority="must">
    <description>SQLite database at ~/.voiceagent/agent.db stores three tables for
    Phase 1: conversations (id, voice_profile, started_at, ended_at, duration_ms,
    turns, status), turns (id, conversation_id, turn_number, role, text, started_at,
    duration_ms, latency_ms, asr_confidence, interrupted, tool_calls_json), and
    metrics (id, conversation_id, metric_name, metric_value, recorded_at). Indexes
    on turns(conversation_id) and metrics(conversation_id).</description>
    <rationale>Persistent storage enables conversation review, latency analysis,
    and debugging across sessions. SQLite is zero-config and file-based, matching
    the local-only architecture.</rationale>
    <constraints>SQLite3 (Python stdlib). WAL journal mode for concurrent reads.
    Schema matches PRD Section 11 (conversations, turns, metrics tables only for
    Phase 1; tool_executions and capture_log are future phases).</constraints>
    <verification_method>After a conversation, run sqlite3 ~/.voiceagent/agent.db
    "SELECT count(*) FROM conversations; SELECT count(*) FROM turns; SELECT
    count(*) FROM metrics;". All must return >0.</verification_method>
  </requirement>

  <requirement id="REQ-DB-02" story_ref="US-DB-01" priority="must">
    <description>Each turn records: role (user/agent/system), full text, started_at
    (ISO 8601), duration_ms (speech duration for user, total generation+synthesis
    for agent), latency_ms (agent response latency: time from user speech end to
    first audio byte out), and asr_confidence (for user turns only).</description>
    <rationale>Per-turn metrics are essential for diagnosing latency bottlenecks
    and tracking ASR quality over time.</rationale>
    <constraints>latency_ms measured from ASR endpoint event to first TTS audio
    chunk sent. asr_confidence is the average segment confidence from
    faster-whisper.</constraints>
    <verification_method>After 1 user + 1 agent turn, query turns table. Verify
    user turn has role="user", non-null text, non-null asr_confidence. Verify
    agent turn has role="agent", non-null text, non-null latency_ms.</verification_method>
  </requirement>

  <!-- =================== CLI =================== -->

  <requirement id="REQ-CLI-01" story_ref="US-CLI-01" priority="must">
    <description>`voiceagent serve` starts a WebSocket server on configurable port
    (default 8765, overridable via --port flag). Accepts --voice flag for default
    voice profile (default "boris"). Loads config from ~/.voiceagent/config.json.
    Creates/opens SQLite database. Starts wake word detector. Logs server URL to
    stdout.</description>
    <rationale>The serve command is the primary way to run the agent as a
    long-running service for WebSocket clients.</rationale>
    <constraints>Click CLI framework. Port range 1024-65535. Voice profile must
    exist in ClipCannon's voice_profiles.db.</constraints>
    <verification_method>Run `voiceagent serve --port 9000 --voice boris`. Verify
    stdout shows "Listening on ws://0.0.0.0:9000". Verify WebSocket client can
    connect. Ctrl+C terminates cleanly.</verification_method>
  </requirement>

  <requirement id="REQ-CLI-02" story_ref="US-CLI-02" priority="must">
    <description>`voiceagent talk` starts an interactive local microphone
    conversation. Accepts --voice flag (default "boris"). Opens local microphone
    via sounddevice. Plays audio through default output device. Loads all models
    immediately (no wake word needed). Ctrl+C terminates cleanly.</description>
    <rationale>The talk command enables rapid testing and development without
    needing a WebSocket client.</rationale>
    <constraints>Click CLI framework. Requires sounddevice + working audio devices.
    Graceful Ctrl+C handling (models unloaded, DB saved).</constraints>
    <verification_method>Run `voiceagent talk --voice boris`. Verify models load.
    Speak a test phrase. Verify agent responds audibly. Press Ctrl+C. Verify clean
    shutdown (no traceback, models unloaded).</verification_method>
  </requirement>

  <!-- =================== PERFORMANCE =================== -->

  <requirement id="REQ-PERF-01" story_ref="US-CONV-01" priority="must">
    <description>End-to-end latency (from user speech endpoint to first audio byte
    of agent response) must be under 500ms at P95 across 20+ consecutive
    conversation turns.</description>
    <rationale>500ms is the threshold for natural conversational feel. Above 500ms,
    users perceive the agent as slow or unresponsive.</rationale>
    <constraints>Measured on RTX 5090 with all models loaded. Excludes model loading
    time. Includes: ASR final transcription + LLM first token + TTS first chunk
    synthesis + WebSocket send.</constraints>
    <verification_method>Run 20 consecutive turns. Record e2e_latency_ms for each
    turn in metrics table. Compute P95. Must be <500ms.</verification_method>
  </requirement>

  <!-- =================== GPU MANAGEMENT =================== -->

  <requirement id="REQ-GPU-01" story_ref="US-WAKE-01, US-WAKE-03" priority="must">
    <description>All AI models (Qwen3-14B, Whisper, TTS) load on-demand when
    activated by wake word or hotkey, and unload when dismissed. In DORMANT state,
    GPU memory usage from voice agent is 0 bytes.</description>
    <rationale>The RTX 5090 has 32GB VRAM shared with other GPU workloads
    (ClipCannon rendering, OCR Provenance, gaming). Permanent model residence would
    prevent other GPU work.</rationale>
    <constraints>Model loading takes 5-10 seconds. Model unloading takes 2-3
    seconds. Only wake word detector runs in DORMANT state (CPU, ~50MB RAM).</constraints>
    <verification_method>Start agent. Verify torch.cuda.memory_allocated() == 0
    (dormant). Activate via wake word. Verify >5GB allocated. Dismiss. Verify
    memory returns to ~0 after empty_cache().</verification_method>
  </requirement>

  <requirement id="REQ-GPU-02" story_ref="US-WAKE-03" priority="must">
    <description>torch.cuda.empty_cache() called after every model unload to return
    GPU memory to the CUDA allocator. Models are moved to CPU (model.cpu()) and
    deleted (del model) before empty_cache().</description>
    <rationale>Without explicit cache clearing, PyTorch's CUDA memory allocator
    retains freed memory blocks, preventing other processes from using GPU
    memory.</rationale>
    <constraints>Sequence: model.cpu() -> del model -> torch.cuda.empty_cache()
    for each model (LLM, ASR, TTS).</constraints>
    <verification_method>After dismiss, check torch.cuda.memory_allocated() and
    torch.cuda.memory_reserved(). Both should be near 0.</verification_method>
  </requirement>

  <!-- =================== CONFIGURATION =================== -->

  <requirement id="REQ-CFG-01" story_ref="US-CLI-01" priority="must">
    <description>Configuration loaded from ~/.voiceagent/config.json. Phase 1
    sections: llm (model_path, max_new_tokens, temperature, device), asr (model,
    compute_type, language, chunk_ms, endpoint_silence_ms, vad_threshold), tts
    (default_voice, enhance, sentence_min_words, sentence_max_words), conversation
    (max_turns, max_duration_s), transport (websocket_port, audio_format,
    output_sample_rate), activation (mode, wake_word_model, wake_word_threshold,
    hotkey), gpu (device).</description>
    <rationale>Externalized configuration enables tuning without code changes.
    JSON format is human-readable and standard.</rationale>
    <constraints>Config file must exist or be created with defaults on first run.
    Missing individual keys fall back to defaults. Invalid values raise
    ValueError at startup.</constraints>
    <verification_method>Start agent with a valid config.json. Verify all values
    loaded correctly. Delete one key. Verify default used. Set invalid value
    (e.g., vad_threshold=2.0). Verify ValueError raised.</verification_method>
  </requirement>

</requirements>

<!-- ================================================================== -->
<!--                       BUSINESS RULES                               -->
<!-- ================================================================== -->

<business_rules>

  <rule id="BR-VOICE-01" req_ref="REQ-TTS-01">
    <condition>Agent is generating a spoken response</condition>
    <action>All TTS synthesis uses the voice profile specified at activation
    (default "boris"). Voice profile is resolved once at activation time and
    remains constant for the entire conversation.</action>
    <exception>None in Phase 1. Voice switching is Phase 4+ scope.</exception>
  </rule>

  <rule id="BR-VOICE-02" req_ref="REQ-CONV-01">
    <condition>Agent is in SPEAKING state</condition>
    <action>Incoming audio chunks are ignored (not processed by ASR). No
    barge-in support in Phase 1.</action>
    <exception>None. Barge-in is Phase 5 scope.</exception>
  </rule>

  <rule id="BR-VOICE-03" req_ref="REQ-ASR-03">
    <condition>ASR has detected speech and silence period reaches endpoint threshold</condition>
    <action>Endpoint is triggered. Audio buffer is finalized and sent for
    final transcription. No additional audio appended after endpoint.</action>
    <exception>If silence is exactly at chunk boundary, one additional chunk
    of silence may be counted before endpoint fires (200ms tolerance).</exception>
  </rule>

  <rule id="BR-VOICE-04" req_ref="REQ-LLM-04">
    <condition>System prompt is being constructed for a new conversation</condition>
    <action>Current date/time (ISO 8601) is injected at construction time. The
    system prompt is rebuilt once per conversation start, not per turn.</action>
    <exception>None.</exception>
  </rule>

  <rule id="BR-VOICE-05" req_ref="REQ-GPU-01">
    <condition>Dismiss keyword detected in ASR transcript</condition>
    <action>Agent speaks farewell message FIRST, then unloads models. The
    farewell TTS synthesis completes before model unloading begins.</action>
    <exception>If TTS fails during farewell, proceed directly to model unload.</exception>
  </rule>

  <rule id="BR-VOICE-06" req_ref="REQ-DB-01">
    <condition>A new conversation starts (wake word or hotkey activation)</condition>
    <action>A new conversation row is created in SQLite with status="active" and
    a generated UUID. All subsequent turns reference this conversation_id.</action>
    <exception>If SQLite write fails, log the error and continue the conversation
    in memory only (degraded mode, no persistence).</exception>
  </rule>

  <rule id="BR-VOICE-07" req_ref="REQ-CONV-01">
    <condition>Agent finishes speaking all audio chunks</condition>
    <action>State transitions from SPEAKING to LISTENING (ready for next user
    turn). Audio buffer is cleared for the next utterance.</action>
    <exception>If dismiss keyword was detected in the turn that triggered this
    response, transition to UNLOADING instead of LISTENING.</exception>
  </rule>

</business_rules>

<!-- ================================================================== -->
<!--                        EDGE CASES                                  -->
<!-- ================================================================== -->

<edge_cases>

  <edge_case id="EC-ASR-01" req_ref="REQ-ASR-01">
    <scenario>Empty audio (complete silence) is sent to the ASR pipeline for an
    extended period (60+ seconds of silence chunks).</scenario>
    <expected_behavior>VAD returns False for every chunk. No audio buffered. No
    transcript emitted. No state transition from IDLE/LISTENING. No memory growth.
    Agent remains silent.</expected_behavior>
    <priority>critical</priority>
  </edge_case>

  <edge_case id="EC-ASR-02" req_ref="REQ-ASR-02">
    <scenario>Very long utterance (60+ seconds of continuous speech without any
    pause exceeding 600ms).</scenario>
    <expected_behavior>Audio buffer grows but does not cause OOM. Partial
    transcripts continue to be emitted every 200ms. When user finally pauses,
    final transcript covers the full utterance. Buffer is cleared after final
    transcript.</expected_behavior>
    <priority>high</priority>
  </edge_case>

  <edge_case id="EC-ASR-03" req_ref="REQ-ASR-03">
    <scenario>User speaks a single word ("Yes") followed by 600ms silence.</scenario>
    <expected_behavior>VAD detects the short speech. Endpoint triggers after 600ms
    silence. Final transcript produced for the single word. LLM processes it
    normally. Response generated.</expected_behavior>
    <priority>medium</priority>
  </edge_case>

  <edge_case id="EC-LLM-01" req_ref="REQ-LLM-02">
    <scenario>LLM generates a response exceeding 512 tokens (max_new_tokens
    config value).</scenario>
    <expected_behavior>Generation stops at max_new_tokens limit. All generated
    tokens up to the limit are streamed to TTS. TTS synthesizes all of them.
    Response may be truncated mid-sentence but is still delivered.</expected_behavior>
    <priority>medium</priority>
  </edge_case>

  <edge_case id="EC-LLM-02" req_ref="REQ-LLM-03">
    <scenario>Conversation reaches 50+ turns, exceeding the ~29.5K token history
    budget.</scenario>
    <expected_behavior>Context manager truncates oldest turns to fit within budget.
    Most recent turns preserved. System prompt always present. LLM generates a
    coherent response without context window overflow error.</expected_behavior>
    <priority>high</priority>
  </edge_case>

  <edge_case id="EC-TTS-01" req_ref="REQ-TTS-02">
    <scenario>LLM generates a response with no sentence-ending punctuation (e.g.,
    a single long clause: "well I think that depends on a lot of different
    factors and considerations").</scenario>
    <expected_behavior>Sentence chunker does not find `. ! ?` boundaries. If the
    buffer exceeds 60 characters, clause splitting at `, ; :` is attempted. If no
    separators found either, the full text is flushed as a single TTS chunk when
    the token stream ends.</expected_behavior>
    <priority>medium</priority>
  </edge_case>

  <edge_case id="EC-TTS-02" req_ref="REQ-TTS-04">
    <scenario>LLM generates an extremely long response (>512 tokens, all
    streamed to TTS as multiple sentence chunks).</scenario>
    <expected_behavior>TTS synthesizes each sentence chunk independently and yields
    audio chunks in order. All chunks are sent to the client. No chunk is dropped.
    Audio playback is continuous without gaps between chunks.</expected_behavior>
    <priority>high</priority>
  </edge_case>

  <edge_case id="EC-WS-01" req_ref="REQ-WS-01">
    <scenario>WebSocket client disconnects mid-conversation (during THINKING or
    SPEAKING state).</scenario>
    <expected_behavior>Server detects disconnection via websockets exception.
    Current conversation marked as status="error" in SQLite with ended_at
    timestamp. In-progress LLM generation is cancelled. In-progress TTS synthesis
    is cancelled. All resources for that connection are cleaned up. Server
    continues running. No crash, no memory leak.</expected_behavior>
    <priority>critical</priority>
  </edge_case>

  <edge_case id="EC-WS-02" req_ref="REQ-WS-01">
    <scenario>WebSocket client sends malformed JSON as a text message.</scenario>
    <expected_behavior>JSON parse error caught. Error logged with the raw message
    content. Client receives {"type": "error", "message": "Invalid JSON"}.
    Connection is NOT closed (client can retry).</expected_behavior>
    <priority>medium</priority>
  </edge_case>

  <edge_case id="EC-WAKE-01" req_ref="REQ-WAKE-01">
    <scenario>Wake word detected while agent is already in ACTIVE state (models
    already loaded).</scenario>
    <expected_behavior>Duplicate activation ignored. No additional model loading.
    Agent remains in current state. No error.</expected_behavior>
    <priority>medium</priority>
  </edge_case>

  <edge_case id="EC-WAKE-02" req_ref="REQ-WAKE-02">
    <scenario>Hotkey pressed while agent is already in ACTIVE state.</scenario>
    <expected_behavior>Duplicate activation ignored. No additional model loading.
    Alternatively, could serve as toggle (activate/deactivate). Phase 1
    implementation: ignore duplicate.</expected_behavior>
    <priority>low</priority>
  </edge_case>

  <edge_case id="EC-GPU-01" req_ref="REQ-GPU-01">
    <scenario>Model loading fails due to insufficient GPU memory (another process
    is using VRAM).</scenario>
    <expected_behavior>CUDA OOM error caught. Agent logs error with current GPU
    memory status. Agent returns to DORMANT state. User is not left in a broken
    state. If WebSocket connected, client receives {"type": "error", "message":
    "Insufficient GPU memory to load models"}.</expected_behavior>
    <priority>critical</priority>
  </edge_case>

  <edge_case id="EC-CFG-01" req_ref="REQ-CFG-01">
    <scenario>Config file ~/.voiceagent/config.json does not exist on first run.</scenario>
    <expected_behavior>Agent creates the config directory (~/.voiceagent/) and
    writes a default config.json with all default values. Logs "Created default
    config at ~/.voiceagent/config.json". Proceeds with default configuration.</expected_behavior>
    <priority>high</priority>
  </edge_case>

</edge_cases>

<!-- ================================================================== -->
<!--                       ERROR STATES                                 -->
<!-- ================================================================== -->

<error_states>

  <error id="ERR-ASR-01" req_ref="REQ-ASR-02">
    <condition>Whisper model files not found at configured path or model fails
    to load on GPU.</condition>
    <user_message>None (startup error, no user interaction yet).</user_message>
    <internal_message>"ASR model failed to load: {error}. Path: {model_path},
    device: {device}, compute_type: {compute_type}"</internal_message>
    <recovery_action>Fail fast. Raise FileNotFoundError or RuntimeError. Do not
    start the agent. Log full traceback.</recovery_action>
  </error>

  <error id="ERR-LLM-01" req_ref="REQ-LLM-01">
    <condition>Qwen3-14B model files not found at configured path.</condition>
    <user_message>None (startup/loading error).</user_message>
    <internal_message>"LLM model not found at {model_path}. Verify model is
    downloaded and path is correct in config.json."</internal_message>
    <recovery_action>Fail fast. Raise FileNotFoundError. Do not transition to
    ACTIVE state. Return to DORMANT.</recovery_action>
  </error>

  <error id="ERR-LLM-02" req_ref="REQ-LLM-02">
    <condition>LLM generation fails mid-stream (CUDA error, OOM, or model
    corruption).</condition>
    <user_message>Agent speaks "I'm sorry, I had a problem processing that.
    Could you try again?" (if TTS is still functional).</user_message>
    <internal_message>"LLM generation failed: {error}. Conversation: {conv_id},
    turn: {turn_num}. GPU memory: {allocated}MB/{reserved}MB"</internal_message>
    <recovery_action>Log full traceback. Cancel TTS stream. Transition to
    LISTENING state. Do not crash. Allow user to try again.</recovery_action>
  </error>

  <error id="ERR-TTS-01" req_ref="REQ-TTS-01">
    <condition>ClipCannon voice profile not found in voice_profiles.db.</condition>
    <user_message>None (startup/loading error).</user_message>
    <internal_message>"Voice profile '{name}' not found in voice_profiles.db.
    Available profiles: {list_profiles()}"</internal_message>
    <recovery_action>Fail fast. Raise ValueError. Do not start the agent.</recovery_action>
  </error>

  <error id="ERR-TTS-02" req_ref="REQ-TTS-04">
    <condition>TTS synthesis fails for a sentence chunk (ClipCannon model error,
    CUDA error).</condition>
    <user_message>Silence for that chunk (audio gap). Agent continues with next
    chunk if available.</user_message>
    <internal_message>"TTS synthesis failed for chunk '{text[:50]}...': {error}.
    Conversation: {conv_id}"</internal_message>
    <recovery_action>Log error. Skip the failed chunk. Continue streaming
    remaining chunks. Do not crash the conversation.</recovery_action>
  </error>

  <error id="ERR-WS-01" req_ref="REQ-WS-01">
    <condition>WebSocket connection fails to establish (port in use, permission
    denied).</condition>
    <user_message>None (server startup error).</user_message>
    <internal_message>"WebSocket server failed to start on {host}:{port}: {error}"</internal_message>
    <recovery_action>Fail fast. Raise OSError. Log suggestion to check if port
    is in use.</recovery_action>
  </error>

  <error id="ERR-WS-02" req_ref="REQ-WS-02">
    <condition>WebSocket client sends invalid binary data (not valid PCM audio,
    wrong byte length for expected sample format).</condition>
    <user_message>Client receives {"type": "error", "message": "Invalid audio
    format. Expected 16kHz 16-bit mono PCM."}.</user_message>
    <internal_message>"Invalid audio data from client: expected 16-bit PCM,
    got {len(data)} bytes (not divisible by 2). Client: {client_id}"</internal_message>
    <recovery_action>Log warning. Send error event to client. Do not close
    connection. Client can retry with correct format.</recovery_action>
  </error>

  <error id="ERR-DB-01" req_ref="REQ-DB-01">
    <condition>SQLite database write fails (disk full, permission denied,
    corruption).</condition>
    <user_message>None (transparent to user).</user_message>
    <internal_message>"DB write failed: {error}. Query: {query}. Params:
    {params}. DB path: {db_path}"</internal_message>
    <recovery_action>Log error with full context. Continue conversation in
    memory-only mode (degraded). Do not crash the conversation for a logging
    failure.</recovery_action>
  </error>

  <error id="ERR-GPU-01" req_ref="REQ-GPU-01">
    <condition>CUDA out of memory during model loading.</condition>
    <user_message>If WebSocket connected: {"type": "error", "message":
    "Insufficient GPU memory. Close other GPU applications and try again."}.
    If CLI talk mode: print error to stderr.</user_message>
    <internal_message>"CUDA OOM during model loading. Allocated: {allocated}MB,
    Reserved: {reserved}MB, Requested: {model_name}. Other processes using GPU:
    {gpu_processes}"</internal_message>
    <recovery_action>Catch torch.cuda.OutOfMemoryError. Unload any partially
    loaded models. Call torch.cuda.empty_cache(). Return to DORMANT state.</recovery_action>
  </error>

  <error id="ERR-CFG-01" req_ref="REQ-CFG-01">
    <condition>Config file contains invalid JSON or invalid values (e.g.,
    vad_threshold=2.0, port=-1).</condition>
    <user_message>None (startup error).</user_message>
    <internal_message>"Invalid config at {config_path}: {validation_error}.
    Key: {key}, Value: {value}, Expected: {constraint}"</internal_message>
    <recovery_action>Fail fast. Raise ValueError with specific field and
    constraint that was violated. Do not start agent with invalid config.</recovery_action>
  </error>

  <error id="ERR-WAKE-01" req_ref="REQ-WAKE-01">
    <condition>OpenWakeWord model file not found or fails to load.</condition>
    <user_message>None (startup error).</user_message>
    <internal_message>"Wake word model '{model_name}' failed to load: {error}.
    Falling back to hotkey-only activation."</internal_message>
    <recovery_action>Log warning. Disable wake word detection. Fall back to
    hotkey-only activation mode. Do not prevent agent from starting.</recovery_action>
  </error>

</error_states>

<!-- ================================================================== -->
<!--                    DATA REQUIREMENTS                               -->
<!-- ================================================================== -->

<data_requirements>

  <entity name="Conversation">
    <field name="id" type="TEXT (UUID)" required="true">
      <description>Unique identifier for the conversation session</description>
      <constraints>Primary key. UUID v4 format.</constraints>
    </field>
    <field name="voice_profile" type="TEXT" required="true">
      <description>ClipCannon voice profile name used for this conversation</description>
      <constraints>Must be a valid profile name in voice_profiles.db. Default "boris".</constraints>
    </field>
    <field name="started_at" type="TEXT (ISO 8601)" required="true">
      <description>Timestamp when conversation was initiated</description>
      <constraints>ISO 8601 format. Set at conversation creation.</constraints>
    </field>
    <field name="ended_at" type="TEXT (ISO 8601)" required="false">
      <description>Timestamp when conversation ended</description>
      <constraints>ISO 8601 format. Null while conversation is active.</constraints>
    </field>
    <field name="duration_ms" type="INTEGER" required="false">
      <description>Total conversation duration in milliseconds</description>
      <constraints>Computed as ended_at - started_at. Null while active.</constraints>
    </field>
    <field name="turns" type="INTEGER" required="true">
      <description>Total number of turns in the conversation</description>
      <constraints>Default 0. Incremented after each turn.</constraints>
    </field>
    <field name="status" type="TEXT" required="true">
      <description>Current conversation status</description>
      <constraints>CHECK constraint: must be one of 'active', 'completed', 'error'. Default 'active'.</constraints>
    </field>
  </entity>

  <entity name="Turn">
    <field name="id" type="INTEGER" required="true">
      <description>Auto-incrementing primary key</description>
      <constraints>PRIMARY KEY AUTOINCREMENT</constraints>
    </field>
    <field name="conversation_id" type="TEXT" required="true">
      <description>Foreign key to conversations table</description>
      <constraints>REFERENCES conversations(id). NOT NULL.</constraints>
    </field>
    <field name="turn_number" type="INTEGER" required="true">
      <description>Sequential turn number within the conversation (1-based)</description>
      <constraints>NOT NULL. Monotonically increasing per conversation.</constraints>
    </field>
    <field name="role" type="TEXT" required="true">
      <description>Who produced this turn</description>
      <constraints>CHECK constraint: must be one of 'user', 'agent', 'system'.</constraints>
    </field>
    <field name="text" type="TEXT" required="true">
      <description>Full text content of the turn (ASR transcript for user, LLM response for agent)</description>
      <constraints>NOT NULL. May be empty string for system turns.</constraints>
    </field>
    <field name="started_at" type="TEXT (ISO 8601)" required="true">
      <description>Timestamp when the turn began</description>
      <constraints>ISO 8601 format.</constraints>
    </field>
    <field name="duration_ms" type="INTEGER" required="false">
      <description>How long the turn took in milliseconds</description>
      <constraints>For user: speech duration. For agent: generation + synthesis time.</constraints>
    </field>
    <field name="latency_ms" type="INTEGER" required="false">
      <description>Agent response latency (time from user endpoint to first audio byte)</description>
      <constraints>Only populated for agent turns. Key metric for REQ-PERF-01.</constraints>
    </field>
    <field name="asr_confidence" type="REAL" required="false">
      <description>Average ASR segment confidence score</description>
      <constraints>Only populated for user turns. Range 0.0-1.0.</constraints>
    </field>
    <field name="interrupted" type="BOOLEAN" required="true">
      <description>Whether this turn was interrupted (barge-in)</description>
      <constraints>Default FALSE. Always FALSE in Phase 1 (no barge-in support).</constraints>
    </field>
    <field name="tool_calls_json" type="TEXT" required="false">
      <description>JSON array of tool calls made during this turn</description>
      <constraints>Always NULL in Phase 1 (no tool calling). Populated in future phases.</constraints>
    </field>
  </entity>

  <entity name="Metric">
    <field name="id" type="INTEGER" required="true">
      <description>Auto-incrementing primary key</description>
      <constraints>PRIMARY KEY AUTOINCREMENT</constraints>
    </field>
    <field name="conversation_id" type="TEXT" required="true">
      <description>Foreign key to conversations table</description>
      <constraints>REFERENCES conversations(id). NOT NULL.</constraints>
    </field>
    <field name="metric_name" type="TEXT" required="true">
      <description>Name of the metric being recorded</description>
      <constraints>NOT NULL. Expected values for Phase 1: "asr_latency_ms",
      "llm_first_token_ms", "tts_first_chunk_ms", "e2e_latency_ms",
      "gpu_memory_mb".</constraints>
    </field>
    <field name="metric_value" type="REAL" required="true">
      <description>Numeric value of the metric</description>
      <constraints>NOT NULL.</constraints>
    </field>
    <field name="recorded_at" type="TEXT (ISO 8601)" required="true">
      <description>When the metric was recorded</description>
      <constraints>ISO 8601 format.</constraints>
    </field>
  </entity>

</data_requirements>

<!-- ================================================================== -->
<!--                NON-FUNCTIONAL REQUIREMENTS                         -->
<!-- ================================================================== -->

<non_functional_requirements>

  <nfr id="NFR-PERF-01" category="performance">
    <description>End-to-end latency from user speech endpoint to first audio byte
    of agent response must be under 500ms at P95.</description>
    <metric>P95 latency < 500ms over 20+ consecutive turns</metric>
    <priority>must</priority>
  </nfr>

  <nfr id="NFR-PERF-02" category="performance">
    <description>VAD processing latency must be under 1ms per audio chunk.</description>
    <metric>P99 VAD latency < 1ms per 200ms chunk</metric>
    <priority>must</priority>
  </nfr>

  <nfr id="NFR-PERF-03" category="performance">
    <description>LLM first token latency must be under 200ms after receiving the
    prompt.</description>
    <metric>P95 time-to-first-token < 200ms</metric>
    <priority>should</priority>
  </nfr>

  <nfr id="NFR-HW-01" category="reliability">
    <description>All voice models (ASR, LLM, TTS) run on the local RTX 5090 GPU.
    No cloud API dependencies. Entire system operates offline.</description>
    <metric>System functions with no internet connection.</metric>
    <priority>must</priority>
  </nfr>

  <nfr id="NFR-HW-02" category="reliability">
    <description>VAD (Silero) and wake word (OpenWakeWord) run on CPU only. They
    must not allocate GPU memory.</description>
    <metric>torch.cuda.memory_allocated() unchanged after VAD/wake word init.</metric>
    <priority>must</priority>
  </nfr>

  <nfr id="NFR-FAIL-01" category="reliability">
    <description>Fail-fast on missing models or devices at startup. Do not attempt
    fallbacks or degraded modes for critical components.</description>
    <metric>Agent raises specific exception within 5 seconds if model files missing
    or GPU unavailable.</metric>
    <priority>must</priority>
  </nfr>

  <nfr id="NFR-FAIL-02" category="reliability">
    <description>Graceful shutdown on WebSocket disconnect. No orphaned GPU tensors,
    no memory leaks, no zombie processes.</description>
    <metric>After disconnect + cleanup, GPU memory returns to pre-connection levels.
    Process count unchanged.</metric>
    <priority>must</priority>
  </nfr>

  <nfr id="NFR-SEC-01" category="security">
    <description>No secrets, API keys, or credentials hardcoded in source files.
    All configuration via config.json or environment variables.</description>
    <metric>grep -r "API_KEY\|SECRET\|PASSWORD" src/voiceagent/ returns 0 matches.</metric>
    <priority>must</priority>
  </nfr>

  <nfr id="NFR-SEC-02" category="security">
    <description>WebSocket server binds to 0.0.0.0 by default but is intended for
    local use only. No authentication in Phase 1.</description>
    <metric>Server starts on configured port. No TLS or auth required in Phase 1.</metric>
    <priority>could</priority>
  </nfr>

  <nfr id="NFR-MAINT-01" category="maintainability">
    <description>Source files organized in the package structure defined in the
    Phase 1 implementation doc (src/voiceagent/ with asr/, brain/, tts/,
    conversation/, transport/, adapters/, activation/, db/ subpackages).</description>
    <metric>All modules importable. No circular imports.</metric>
    <priority>must</priority>
  </nfr>

</non_functional_requirements>

<!-- ================================================================== -->
<!--                       DEPENDENCIES                                 -->
<!-- ================================================================== -->

<dependencies>

  <dependency type="external">
    <name>NVIDIA RTX 5090 GPU with CUDA drivers</name>
    <description>32GB GDDR7 GPU with Blackwell architecture. Required for ASR
    (Whisper INT8), LLM (Qwen3-14B FP8), and TTS (ClipCannon models).</description>
    <impact>Without a CUDA-capable GPU, none of the AI models can load. Agent
    cannot function. Fail-fast at startup.</impact>
  </dependency>

  <dependency type="external">
    <name>Qwen3-14B-FP8 model weights</name>
    <description>Pre-downloaded at /home/cabdru/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/.
    Not downloaded at runtime.</description>
    <impact>If model files missing, LLM cannot load. Fail-fast with
    FileNotFoundError.</impact>
  </dependency>

  <dependency type="external">
    <name>Distil-Whisper Large v3 model</name>
    <description>ASR model loaded via faster-whisper library. Downloaded on
    first use by faster-whisper.</description>
    <impact>If model unavailable or download fails, ASR cannot function. Fail-fast.</impact>
  </dependency>

  <dependency type="internal">
    <name>ClipCannon voice system</name>
    <description>Imported as Python library from src/. Provides VoiceSynthesizer,
    get_voice_profile, voice_profiles.db. Read-only access.</description>
    <impact>If ClipCannon import fails or voice profile "boris" not found, TTS
    cannot function. Fail-fast with ValueError.</impact>
  </dependency>

  <dependency type="external">
    <name>Python packages</name>
    <description>faster-whisper>=1.0, silero-vad>=5.0, vllm, websockets>=12.0,
    fastapi>=0.110, uvicorn, sounddevice>=0.5.5, openwakeword>=0.6.0,
    pynput>=1.7, click, numpy, scipy, torch.</description>
    <impact>Missing packages cause ImportError at startup.</impact>
  </dependency>

  <dependency type="external">
    <name>Audio hardware (microphone + speakers)</name>
    <description>Required for `voiceagent talk` mode. sounddevice accesses
    system audio devices.</description>
    <impact>Missing audio devices cause sounddevice.PortAudioError. Only affects
    `talk` mode; `serve` mode works without local audio.</impact>
  </dependency>

</dependencies>

<!-- ================================================================== -->
<!--                       OUT OF SCOPE                                 -->
<!-- ================================================================== -->

<out_of_scope>
  <item>Screen capture / companion app -- handled by Phase 2 (SPEC-VOICE-P2)</item>
  <item>OCR Provenance integration and memory system -- handled by Phase 3 (SPEC-VOICE-P3)</item>
  <item>Tool calling / function execution by LLM -- handled by Phase 4 (SPEC-VOICE-P4)</item>
  <item>Barge-in (user interrupting agent mid-speech) -- handled by Phase 5 (SPEC-VOICE-P5)</item>
  <item>Ambient microphone transcription -- handled by Phase 2</item>
  <item>System audio loopback capture -- handled by Phase 2</item>
  <item>Clipboard monitoring -- handled by Phase 2</item>
  <item>Dream state (nightly consolidation) -- handled by Phase 3</item>
  <item>PII detection and redaction -- handled by Phase 3</item>
  <item>Cross-conversation persistent memory -- handled by Phase 3</item>
  <item>Voice switching at runtime -- future work</item>
  <item>Multi-user support -- not planned</item>
  <item>Cloud deployment -- explicitly excluded (local only)</item>
  <item>TLS/authentication on WebSocket -- Phase 5 hardening</item>
  <item>REST API endpoints (/health, /conversations, etc.) -- Phase 5</item>
  <item>Green Contexts GPU partitioning -- Phase 4</item>
  <item>NVFP4 quantization -- optimization, not Phase 1</item>
</out_of_scope>

<!-- ================================================================== -->
<!--                        TEST PLAN                                   -->
<!-- ================================================================== -->

<test_plan>

  <!-- =================== ASR TESTS =================== -->

  <test_case id="TC-ASR-01" type="unit" req_ref="REQ-ASR-01">
    <description>VAD correctly detects speech in audio containing spoken words</description>
    <preconditions>Silero VAD model loaded on CPU</preconditions>
    <inputs>16kHz 16-bit PCM audio file containing clear speech (5 seconds)</inputs>
    <expected_result>is_speech() returns True for chunks containing speech. Processing
    time per chunk < 1ms.</expected_result>
    <priority>critical</priority>
  </test_case>

  <test_case id="TC-ASR-02" type="unit" req_ref="REQ-ASR-01">
    <description>VAD correctly identifies silence (no false positives)</description>
    <preconditions>Silero VAD model loaded on CPU</preconditions>
    <inputs>16kHz 16-bit PCM audio file containing silence (5 seconds)</inputs>
    <expected_result>is_speech() returns False for all chunks.</expected_result>
    <priority>critical</priority>
  </test_case>

  <test_case id="TC-ASR-03" type="integration" req_ref="REQ-ASR-02">
    <description>Streaming ASR produces partial transcripts during speech</description>
    <preconditions>Whisper model loaded on GPU. VAD active.</preconditions>
    <inputs>Audio of someone saying "Hello, my name is Chris and I am testing the
    voice agent" (approximately 4 seconds of speech)</inputs>
    <expected_result>Multiple ASREvent objects returned with final=False during speech.
    Text contains recognizable words. Events emitted approximately every 200ms.</expected_result>
    <priority>high</priority>
  </test_case>

  <test_case id="TC-ASR-04" type="integration" req_ref="REQ-ASR-03, REQ-ASR-04">
    <description>Endpoint detection triggers final transcript after 600ms silence</description>
    <preconditions>Streaming ASR active with speech buffer</preconditions>
    <inputs>Audio containing 3 seconds of speech followed by 800ms of silence</inputs>
    <expected_result>ASREvent with final=True returned after ~600ms of silence.
    Text is a complete, accurate transcript of the spoken words (beam_size=5).
    Audio buffer is cleared.</expected_result>
    <priority>critical</priority>
  </test_case>

  <!-- =================== LLM TESTS =================== -->

  <test_case id="TC-LLM-01" type="integration" req_ref="REQ-LLM-01">
    <description>Qwen3-14B loads to GPU with >5GB memory allocation</description>
    <preconditions>GPU available with >15GB free VRAM</preconditions>
    <inputs>Model path from config. FP8 quantization. 45% GPU memory utilization.</inputs>
    <expected_result>Model loads without error. torch.cuda.memory_allocated() > 5GB.
    Model responds to a test prompt.</expected_result>
    <priority>critical</priority>
  </test_case>

  <test_case id="TC-LLM-02" type="integration" req_ref="REQ-LLM-02">
    <description>Streaming token generation produces coherent incremental output</description>
    <preconditions>Qwen3-14B loaded on GPU</preconditions>
    <inputs>Messages: [{"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is 2 + 2?"}]</inputs>
    <expected_result>generate_stream() yields tokens incrementally. First token
    arrives within 200ms. Complete response mentions "4". Total response is
    coherent English.</expected_result>
    <priority>critical</priority>
  </test_case>

  <test_case id="TC-LLM-03" type="unit" req_ref="REQ-LLM-03">
    <description>Context window manager stays within 32K token budget after 50 turns</description>
    <preconditions>ContextManager instantiated</preconditions>
    <inputs>System prompt (~500 tokens) + 50 conversation turns (~200 tokens each =
    ~10K total) + new user input (~50 tokens)</inputs>
    <expected_result>build_messages() returns a message list whose total token count
    is < 32000. Most recent turns are present. Oldest turns may be truncated.
    System prompt is always present.</expected_result>
    <priority>high</priority>
  </test_case>

  <test_case id="TC-LLM-04" type="unit" req_ref="REQ-LLM-04">
    <description>System prompt contains all required elements</description>
    <preconditions>None</preconditions>
    <inputs>voice_name="boris"</inputs>
    <expected_result>build_system_prompt("boris") returns a string containing:
    "Chris Royse", "boris", a valid ISO 8601 datetime, "1-3 sentences",
    "I don't know".</expected_result>
    <priority>medium</priority>
  </test_case>

  <!-- =================== TTS TESTS =================== -->

  <test_case id="TC-TTS-01" type="integration" req_ref="REQ-TTS-01">
    <description>ClipCannon adapter synthesizes text to valid 24kHz audio</description>
    <preconditions>ClipCannon voice profile "boris" exists. TTS model loaded.</preconditions>
    <inputs>text="Hello, how are you today?"</inputs>
    <expected_result>synthesize() returns numpy array with dtype=float32, length > 0,
    representing 24kHz audio. Audio is audibly recognizable as speech.</expected_result>
    <priority>critical</priority>
  </test_case>

  <test_case id="TC-TTS-02" type="unit" req_ref="REQ-TTS-02">
    <description>Sentence chunker splits text on sentence boundaries</description>
    <preconditions>SentenceChunker instantiated</preconditions>
    <inputs>buffer="Hello there. How are you? I am fine."</inputs>
    <expected_result>Three sequential extract_sentence() calls return: "Hello there.",
    "How are you?", "I am fine." respectively.</expected_result>
    <priority>high</priority>
  </test_case>

  <test_case id="TC-TTS-03" type="unit" req_ref="REQ-TTS-03">
    <description>Sentence chunker splits long clauses at comma/semicolon</description>
    <preconditions>SentenceChunker instantiated</preconditions>
    <inputs>buffer="Well I think that really depends on a lot of different factors
    and various considerations, but ultimately the answer is yes"</inputs>
    <expected_result>extract_sentence() returns the clause up to and including the
    comma (since buffer > 60 chars). Returned chunk has >= 3 words.</expected_result>
    <priority>medium</priority>
  </test_case>

  <test_case id="TC-TTS-04" type="integration" req_ref="REQ-TTS-04">
    <description>Streaming TTS yields audio chunks as sentences complete</description>
    <preconditions>ClipCannon adapter loaded. SentenceChunker configured.</preconditions>
    <inputs>Async token stream producing: "Hello. How are you? I am fine."</inputs>
    <expected_result>StreamingTTS.stream() yields 3 audio chunks (one per sentence).
    Each chunk is a valid numpy array with audio data. Chunks arrive incrementally
    (not all at once).</expected_result>
    <priority>high</priority>
  </test_case>

  <!-- =================== CONVERSATION TESTS =================== -->

  <test_case id="TC-CONV-01" type="integration" req_ref="REQ-CONV-01">
    <description>State machine transitions correctly through a full conversation turn</description>
    <preconditions>All models loaded. ConversationManager initialized.</preconditions>
    <inputs>Audio of "Hello" followed by 600ms silence</inputs>
    <expected_result>State transitions: IDLE -> LISTENING (on speech detection) ->
    THINKING (on endpoint) -> SPEAKING (on first TTS chunk) -> LISTENING (on
    completion). Each state change is observable.</expected_result>
    <priority>critical</priority>
  </test_case>

  <test_case id="TC-CONV-02" type="integration" req_ref="REQ-CONV-02, REQ-CONV-03">
    <description>Conversation history accumulates correctly over multiple turns</description>
    <preconditions>ConversationManager initialized with loaded models</preconditions>
    <inputs>3 sequential user utterances with agent responses between each</inputs>
    <expected_result>After 3 turns, history contains 6 entries (3 user + 3 agent).
    Each entry has role and content. Agent content matches full response text
    (not partial fragments).</expected_result>
    <priority>high</priority>
  </test_case>

  <!-- =================== WEBSOCKET TESTS =================== -->

  <test_case id="TC-WS-01" type="integration" req_ref="REQ-WS-01">
    <description>WebSocket server accepts connection and receives binary audio</description>
    <preconditions>WebSocket server running on configured port</preconditions>
    <inputs>WebSocket client connects and sends 6400 bytes of binary PCM data</inputs>
    <expected_result>Connection established (HTTP 101). Server processes binary data
    without error. No disconnection.</expected_result>
    <priority>critical</priority>
  </test_case>

  <test_case id="TC-WS-02" type="integration" req_ref="REQ-WS-02">
    <description>WebSocket sends JSON events and audio to client during conversation</description>
    <preconditions>WebSocket server running. Client connected. Models loaded.</preconditions>
    <inputs>Client sends audio of "Hello" followed by silence</inputs>
    <expected_result>Client receives: JSON {"type": "transcript", ...},
    JSON {"type": "state", "state": "THINKING"},
    JSON {"type": "state", "state": "SPEAKING"},
    binary audio data (24kHz PCM),
    JSON {"type": "agent_text", ...},
    JSON {"type": "metrics", ...}.</expected_result>
    <priority>high</priority>
  </test_case>

  <test_case id="TC-WS-03" type="integration" req_ref="REQ-WS-01">
    <description>WebSocket handles client disconnect gracefully</description>
    <preconditions>Client connected. Conversation in progress (THINKING state).</preconditions>
    <inputs>Client abruptly closes connection</inputs>
    <expected_result>Server detects disconnect. No crash. No unhandled exception.
    Server continues accepting new connections. Conversation saved to SQLite with
    status="error".</expected_result>
    <priority>critical</priority>
  </test_case>

  <!-- =================== WAKE WORD TESTS =================== -->

  <test_case id="TC-WAKE-01" type="integration" req_ref="REQ-WAKE-01">
    <description>Wake word detector triggers on configured wake phrase</description>
    <preconditions>OpenWakeWord model loaded on CPU. Agent in DORMANT state.</preconditions>
    <inputs>Audio of someone saying "Hey Jarvis"</inputs>
    <expected_result>detect() returns True. Confidence > 0.6. Agent transitions
    from DORMANT to LOADING.</expected_result>
    <priority>high</priority>
  </test_case>

  <test_case id="TC-WAKE-02" type="integration" req_ref="REQ-WAKE-02">
    <description>Hotkey activation triggers model loading</description>
    <preconditions>HotkeyActivator running. Agent in DORMANT state.</preconditions>
    <inputs>Ctrl+Space keypress</inputs>
    <expected_result>Callback fired. Agent transitions from DORMANT to LOADING.
    Models load to GPU. Agent speaks "I'm here".</expected_result>
    <priority>high</priority>
  </test_case>

  <!-- =================== DATABASE TESTS =================== -->

  <test_case id="TC-DB-01" type="integration" req_ref="REQ-DB-01">
    <description>Conversation and turns stored in SQLite after a complete turn</description>
    <preconditions>SQLite database created at ~/.voiceagent/agent.db</preconditions>
    <inputs>Complete one conversation turn (1 user utterance + 1 agent response)</inputs>
    <expected_result>conversations table has 1 row with status="active", non-null
    id, voice_profile="boris". turns table has 2 rows: 1 with role="user" and
    1 with role="agent". Both have non-null text and started_at.</expected_result>
    <priority>critical</priority>
  </test_case>

  <test_case id="TC-DB-02" type="integration" req_ref="REQ-DB-02">
    <description>Metrics recorded for each conversation turn</description>
    <preconditions>Conversation in progress</preconditions>
    <inputs>Complete one full conversation turn</inputs>
    <expected_result>metrics table has rows for: "e2e_latency_ms",
    "asr_latency_ms", "llm_first_token_ms", "tts_first_chunk_ms". All
    metric_value > 0. All linked to correct conversation_id.</expected_result>
    <priority>high</priority>
  </test_case>

  <!-- =================== CLI TESTS =================== -->

  <test_case id="TC-CLI-01" type="e2e" req_ref="REQ-CLI-01">
    <description>`voiceagent serve` starts WebSocket server</description>
    <preconditions>Dependencies installed. Config file present.</preconditions>
    <inputs>Run `voiceagent serve --port 9000 --voice boris`</inputs>
    <expected_result>Server starts. stdout contains "Listening on ws://0.0.0.0:9000".
    WebSocket client can connect to ws://localhost:9000/conversation and receives
    HTTP 101. Ctrl+C terminates cleanly.</expected_result>
    <priority>high</priority>
  </test_case>

  <test_case id="TC-CLI-02" type="e2e" req_ref="REQ-CLI-02">
    <description>`voiceagent talk` starts interactive conversation</description>
    <preconditions>Dependencies installed. Microphone available. Config present.</preconditions>
    <inputs>Run `voiceagent talk --voice boris`</inputs>
    <expected_result>Models load to GPU. Agent speaks "I'm here" through speakers.
    Microphone captures audio. Agent responds to spoken input. Ctrl+C terminates
    cleanly (models unloaded, DB saved).</expected_result>
    <priority>high</priority>
  </test_case>

  <!-- =================== PERFORMANCE TESTS =================== -->

  <test_case id="TC-PERF-01" type="e2e" req_ref="REQ-PERF-01">
    <description>End-to-end latency under 500ms at P95</description>
    <preconditions>All models loaded on GPU. Agent in ACTIVE state.</preconditions>
    <inputs>20 consecutive conversation turns with varied questions ("Hello",
    "What time is it?", "Tell me a joke", etc.)</inputs>
    <expected_result>Compute P95 of e2e_latency_ms from metrics table across all
    20 turns. P95 < 500ms.</expected_result>
    <priority>critical</priority>
  </test_case>

  <test_case id="TC-PERF-02" type="unit" req_ref="REQ-TTS-02">
    <description>Sentence chunker correctly splits multi-sentence text</description>
    <preconditions>SentenceChunker instantiated</preconditions>
    <inputs>"Hello. How are you?"</inputs>
    <expected_result>Produces exactly 2 chunks: "Hello." and "How are you?"</expected_result>
    <priority>high</priority>
  </test_case>

  <!-- =================== GPU MANAGEMENT TESTS =================== -->

  <test_case id="TC-GPU-01" type="integration" req_ref="REQ-GPU-01, REQ-GPU-02">
    <description>Models load on activation and unload on dismiss with full
    GPU memory reclamation</description>
    <preconditions>Agent in DORMANT state. GPU idle.</preconditions>
    <inputs>Activate via wake word/hotkey. Verify GPU memory. Dismiss. Verify
    GPU memory reclaimed.</inputs>
    <expected_result>
    Before activation: torch.cuda.memory_allocated() ~= 0.
    After activation: torch.cuda.memory_allocated() > 5GB.
    After dismiss: torch.cuda.memory_allocated() ~= 0,
    torch.cuda.memory_reserved() near 0.
    </expected_result>
    <priority>critical</priority>
  </test_case>

  <!-- =================== EDGE CASE TESTS =================== -->

  <test_case id="TC-EDGE-01" type="integration" req_ref="REQ-ASR-01">
    <description>Silence-only audio does not trigger agent response</description>
    <preconditions>Agent in LISTENING state. Models loaded.</preconditions>
    <inputs>60 seconds of silence-only audio chunks</inputs>
    <expected_result>No ASR transcript emitted. No LLM generation triggered.
    Agent remains in LISTENING state. No audio output.</expected_result>
    <priority>high</priority>
  </test_case>

  <test_case id="TC-EDGE-02" type="integration" req_ref="REQ-LLM-03">
    <description>Context window does not overflow after 50 turns</description>
    <preconditions>Conversation with 50+ accumulated turns</preconditions>
    <inputs>51st user utterance</inputs>
    <expected_result>build_messages() returns messages fitting within 32K tokens.
    LLM generates response without error. Oldest turns truncated. Recent turns
    preserved.</expected_result>
    <priority>high</priority>
  </test_case>

</test_plan>

<!-- ================================================================== -->
<!--                      OPEN QUESTIONS                                -->
<!-- ================================================================== -->

<open_questions>

  <question id="Q-001" status="open" assignee="Chris Royse">
    <text>Should the `voiceagent talk` command also start the wake word detector,
    or should it immediately load all models (bypassing dormant state)?</text>
    <context>The Phase 1 doc implies `talk` loads models immediately, but it could
    also start in dormant mode with wake word detection for consistency.</context>
    <resolution></resolution>
  </question>

  <question id="Q-002" status="open" assignee="Chris Royse">
    <text>What is the behavior when vLLM is not available? Should the agent fall
    back to transformers with manual FP8 quantization, or fail-fast?</text>
    <context>The Phase 1 doc mentions "Option A: vLLM (preferred)" and "Option B:
    transformers (fallback)" but the PRD says "FAIL FAST. NO FALLBACKS." These
    are contradictory.</context>
    <resolution></resolution>
  </question>

  <question id="Q-003" status="open" assignee="Chris Royse">
    <text>Should the hotkey (Ctrl+Space) serve as a toggle (activate on first press,
    dismiss on second press), or should dismiss only work via the "Go to sleep"
    voice command?</text>
    <context>The PRD mentions hotkey as "load/unload toggle" but the Phase 1 doc
    only shows activation. Toggle behavior would be more ergonomic.</context>
    <resolution></resolution>
  </question>

  <question id="Q-004" status="open" assignee="Chris Royse">
    <text>What is the maximum audio buffer size before OOM protection kicks in for
    very long utterances (60+ seconds)?</text>
    <context>Edge case EC-ASR-02 identifies long utterances. At 16kHz 16-bit mono,
    60 seconds = ~1.9MB. 10 minutes = ~19MB. Need to define an upper bound.</context>
    <resolution></resolution>
  </question>

  <question id="Q-005" status="open" assignee="Chris Royse">
    <text>Should partial ASR transcripts be sent to WebSocket clients, or only
    final transcripts?</text>
    <context>REQ-ASR-02 specifies partial transcripts are produced, but the
    WebSocket event schema shows {"type": "transcript", "final": true/false}.
    Sending partials enables live transcription UI but increases bandwidth.</context>
    <resolution></resolution>
  </question>

</open_questions>

<!-- ================================================================== -->
<!--                        GLOSSARY                                    -->
<!-- ================================================================== -->

<glossary>
  <term name="ASR">Automatic Speech Recognition. Converts spoken audio to text.
  Phase 1 uses Distil-Whisper Large v3.</term>
  <term name="VAD">Voice Activity Detection. Determines whether an audio chunk
  contains speech or silence. Phase 1 uses Silero VAD v5.</term>
  <term name="TTS">Text-to-Speech. Converts text to spoken audio. Phase 1 uses
  ClipCannon with the "boris" voice profile.</term>
  <term name="LLM">Large Language Model. The reasoning engine. Phase 1 uses
  Qwen3-14B-FP8.</term>
  <term name="Endpoint Detection">The process of determining when a user has
  finished speaking, based on a configurable silence duration (default 600ms).</term>
  <term name="PCM">Pulse Code Modulation. Raw uncompressed audio format. Input:
  16kHz 16-bit mono. Output: 24kHz 16-bit mono.</term>
  <term name="FP8">8-bit floating point quantization. Reduces model size and
  VRAM usage while maintaining acceptable accuracy.</term>
  <term name="SECS">Speaker Encoder Cosine Similarity. A metric for voice clone
  quality. 0.975 SECS means the cloned voice is nearly indistinguishable from the
  original.</term>
  <term name="VRAM">Video RAM. GPU memory. RTX 5090 has 32GB GDDR7.</term>
  <term name="vLLM">A high-throughput LLM serving engine with continuous batching
  and optimized CUDA kernels.</term>
  <term name="boris">The ClipCannon voice profile trained on Chris Royse's speech
  data. 0.975 SECS quality. Default voice for the agent.</term>
  <term name="DORMANT">Agent state where no AI models are loaded on GPU. Only wake
  word detector runs on CPU.</term>
  <term name="Barge-in">User interrupting the agent mid-speech. Not supported in
  Phase 1.</term>
  <term name="Green Contexts">CUDA feature for GPU compute partitioning. Not used
  in Phase 1.</term>
  <term name="Dream State">Nightly 3-5 AM batch processing window. Not implemented
  in Phase 1.</term>
  <term name="beam_size">Whisper ASR parameter controlling search breadth during
  decoding. Higher values = more accurate but slower. Partial=1, Final=5.</term>
</glossary>

</functional_spec>
```

---

## PRD Analysis Summary

### Source Documents
- **PRD**: docsvoice/prd_voice_agent.md (v3.0, 2026-03-28, Chris Royse)
- **Implementation**: docsvoice/01_phase1_core_pipeline.md (Weeks 1-3)

### User Types Identified
| ID | Type | Description | Permission Level |
|----|------|-------------|------------------|
| UT-01 | Chris Royse (Primary) | Voice-first end user, expects cloned voice responses | Full conversational |
| UT-02 | Developer (Self) | CLI access, debugging, configuration | Full system |

### User Journeys Extracted
1. **Wake Word Activation**: Say wake word -> models load -> "I'm here" -> conversation
2. **Hotkey Activation**: Press Ctrl+Space -> same flow as wake word
3. **Dismissal**: Say "Go to sleep" -> farewell -> models unload -> dormant
4. **WebSocket Service**: `voiceagent serve` -> server starts -> client connects -> bidirectional audio
5. **Interactive Talk**: `voiceagent talk` -> local mic conversation

### Functional Domains
- [x] Streaming ASR (VAD + Whisper)
- [x] LLM Brain (Qwen3-14B loading, streaming, context)
- [x] Streaming TTS (ClipCannon adapter, chunking)
- [x] Conversation Management (state machine, history)
- [x] WebSocket Transport (bidirectional audio + JSON)
- [x] Wake Word / Activation (OpenWakeWord + hotkey)
- [x] CLI Entry Points (serve + talk)
- [x] Database (SQLite persistence)
- [x] Configuration (config.json)

### Requirement Coverage
| Priority | Count | Percentage |
|----------|-------|------------|
| Must | 21 | 100% |
| Should | 0 | 0% |
| Could | 0 | 0% |

All 21 requirements are must-have, reflecting Phase 1's nature as the minimum viable core pipeline.
