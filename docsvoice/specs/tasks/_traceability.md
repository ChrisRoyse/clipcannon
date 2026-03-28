# Task Traceability Matrix: Voice Agent Phase 1 -- Core Voice Pipeline

## Purpose
Every Phase 1 tech spec item MUST have a corresponding task. Empty "Task ID" = INCOMPLETE.

## Package Structure / Scaffolding
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| src/voiceagent/__init__.py | Package root, __version__ | TASK-VA-001 | [ ] |
| src/voiceagent/errors.py | All custom exceptions | TASK-VA-001 | [ ] |
| src/voiceagent/asr/__init__.py | ASR subpackage | TASK-VA-001 | [ ] |
| src/voiceagent/brain/__init__.py | Brain subpackage | TASK-VA-001 | [ ] |
| src/voiceagent/conversation/__init__.py | Conversation subpackage | TASK-VA-001 | [ ] |
| src/voiceagent/tts/__init__.py | TTS subpackage | TASK-VA-001 | [ ] |
| src/voiceagent/transport/__init__.py | Transport subpackage | TASK-VA-001 | [ ] |
| src/voiceagent/adapters/__init__.py | Adapters subpackage | TASK-VA-001 | [ ] |
| src/voiceagent/activation/__init__.py | Activation subpackage | TASK-VA-001 | [ ] |
| src/voiceagent/db/__init__.py | Database subpackage | TASK-VA-001 | [ ] |

## Configuration
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| VoiceAgentConfig dataclass | Nested config with llm, asr, tts, conversation, transport, gpu sections | TASK-VA-002 | [ ] |
| config.json schema | Default config file at ~/.voiceagent/config.json | TASK-VA-002 | [ ] |
| Config loading from file | load_config() function | TASK-VA-002 | [ ] |

## Database
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| conversations table | id, started_at, ended_at, voice_profile, turn_count | TASK-VA-003 | [ ] |
| turns table | id, conversation_id, role, text, timing metrics | TASK-VA-003 | [ ] |
| metrics table | id, timestamp, metric_name, value, metadata | TASK-VA-003 | [ ] |
| Connection factory | get_connection() with path config | TASK-VA-003 | [ ] |
| Schema initialization | init_db() creates all tables | TASK-VA-003 | [ ] |

## ASR Types / Data Classes
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| ASREvent dataclass | text, final, timestamp fields | TASK-VA-004 | [ ] |
| AudioBuffer class | append(), get_audio(), clear(), has_audio() | TASK-VA-004 | [ ] |
| ASRConfig dataclass | vad_threshold, endpoint_silence_ms, model_name | TASK-VA-004 | [ ] |

## VAD
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| SileroVAD class | __init__(threshold), is_speech(), reset() | TASK-VA-005 | [ ] |
| Silero model loading | torch.hub or ONNX runtime load | TASK-VA-005 | [ ] |
| Unit test: VAD | Speech vs silence detection | TASK-VA-005 | [ ] |

## Streaming ASR
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| StreamingASR class | __init__(config), process_chunk() | TASK-VA-006 | [ ] |
| Partial transcript emission | Every 200ms during speech | TASK-VA-006 | [ ] |
| Final transcript emission | After 600ms silence endpoint | TASK-VA-006 | [ ] |
| Endpoint detection | Silence-based configurable endpoint | TASK-VA-006 | [ ] |
| Unit test: ASR | process_chunk returns ASREvent | TASK-VA-006 | [ ] |

## LLM Brain
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| LLMBrain class | __init__(config), generate_stream() | TASK-VA-007 | [ ] |
| vLLM loader | FP8 quantization, gpu_memory_utilization | TASK-VA-007 | [ ] |
| Streaming token generation | AsyncIterator[str] output | TASK-VA-007 | [ ] |
| Unit test: LLM | generate_stream yields tokens | TASK-VA-007 | [ ] |

## System Prompt
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| build_system_prompt() | Identity, datetime, rules | TASK-VA-008 | [ ] |
| Unit test: prompt builder | Output contains required sections | TASK-VA-008 | [ ] |

## Context Window Manager
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| ContextManager class | MAX_TOKENS, SYSTEM_RESERVE, RESPONSE_RESERVE | TASK-VA-009 | [ ] |
| build_messages() | System prompt + history truncation + user input | TASK-VA-009 | [ ] |
| Token counting | _count_tokens() method | TASK-VA-009 | [ ] |
| Unit test: context manager | History truncation at budget | TASK-VA-009 | [ ] |

## ClipCannon Adapter
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| ClipCannonAdapter class | __init__(voice_name), synthesize() | TASK-VA-010 | [ ] |
| Voice profile loading | get_voice_profile from ClipCannon | TASK-VA-010 | [ ] |
| Audio synthesis | Returns 24kHz float32 np.ndarray | TASK-VA-010 | [ ] |
| Unit test: adapter | synthesize returns audio array | TASK-VA-010 | [ ] |

## Sentence Chunker
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| SentenceChunker class | MIN_WORDS, MAX_WORDS | TASK-VA-011 | [ ] |
| extract_sentence() | Sentence boundary detection | TASK-VA-011 | [ ] |
| Clause fallback | Long clause at comma/semicolon >60 chars | TASK-VA-011 | [ ] |
| Unit test: chunker | Splits "Hello. How are you?" into 2 chunks | TASK-VA-011 | [ ] |

## Streaming TTS
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| StreamingTTS class | __init__(adapter, chunker) | TASK-VA-012 | [ ] |
| stream() method | Token iterator -> sentence chunks -> audio chunks | TASK-VA-012 | [ ] |
| Buffer flush | Remaining text synthesized at end | TASK-VA-012 | [ ] |
| Unit test: streaming TTS | Yields audio chunks from token stream | TASK-VA-012 | [ ] |

## Conversation State Machine
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| ConversationState enum | IDLE, LISTENING, THINKING, SPEAKING | TASK-VA-013 | [ ] |
| ConversationManager class | handle_audio_chunk(), _generate_response() | TASK-VA-013 | [ ] |
| State transitions | IDLE->LISTENING->THINKING->SPEAKING->LISTENING | TASK-VA-013 | [ ] |
| History tracking | Append user/assistant turns | TASK-VA-013 | [ ] |
| Unit test: state machine | State transitions on events | TASK-VA-013 | [ ] |

## Wake Word Detector
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| WakeWordDetector class | __init__(model_name, threshold) | TASK-VA-014 | [ ] |
| detect() method | Returns bool for wake word presence | TASK-VA-014 | [ ] |
| Unit test: wake word | Detection on synthetic audio | TASK-VA-014 | [ ] |

## Hotkey Activator
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| HotkeyActivator class | __init__(key_combo, callback) | TASK-VA-015 | [ ] |
| start() method | Begins listening for global hotkey | TASK-VA-015 | [ ] |
| Unit test: hotkey | Callback fires on key combo | TASK-VA-015 | [ ] |

## WebSocket Transport
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| WebSocketTransport class | __init__(host, port) | TASK-VA-016 | [ ] |
| start() method | Bidirectional audio + JSON control | TASK-VA-016 | [ ] |
| send_audio() | PCM audio to client (24kHz 16-bit mono) | TASK-VA-016 | [ ] |
| send_event() | JSON event to client | TASK-VA-016 | [ ] |
| Unit test: websocket | Connect, send/receive messages | TASK-VA-016 | [ ] |

## FastAPI Server
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| FastAPI app | Health endpoint + conversations endpoint + WebSocket route | TASK-VA-017 | [ ] |
| GET /health | Returns {"status": "ok", "version": "0.1.0", "uptime_s": float} | TASK-VA-017 | [ ] |
| GET /conversations/{id} | Returns conversation data from SQLite | TASK-VA-017 | [ ] |
| /ws WebSocket route | Delegates to on_audio/on_control callbacks | TASK-VA-017 | [ ] |
| Unit test: server | Health check 200, WebSocket 101, conversation 200/404 | TASK-VA-017 | [ ] |

## VoiceAgent Orchestrator
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| VoiceAgent class | Wires config -> DB -> ASR -> LLM -> TTS -> ConversationManager -> Transport -> Activation | TASK-VA-018 | [ ] |
| __init__(config=None) | Loads config only, does NOT load GPU models | TASK-VA-018 | [ ] |
| _init_components() | Initializes all subsystems, loads GPU models | TASK-VA-018 | [ ] |
| start() method | Calls _init_components() then starts server | TASK-VA-018 | [ ] |
| talk_interactive() | Local mic conversation mode using sounddevice | TASK-VA-018 | [ ] |
| shutdown() | Releases ALL GPU resources, closes DB (idempotent) | TASK-VA-018 | [ ] |
| _log_turn() | Writes turn record to SQLite turns table | TASK-VA-018 | [ ] |
| Integration test | REAL test: DB tables, conversation record, turn record, GPU memory | TASK-VA-018 | [ ] |

## CLI Entry Point
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| cli group | click.group() root command | TASK-VA-019 | [ ] |
| serve command | `voiceagent serve --voice boris --port 8765 --host 0.0.0.0` | TASK-VA-019 | [ ] |
| talk command | `voiceagent talk --voice boris` | TASK-VA-019 | [ ] |
| __main__.py | `python -m voiceagent` support | TASK-VA-019 | [ ] |
| Unit test: CLI | CliRunner tests for help text, args, defaults | TASK-VA-019 | [ ] |

## Integration Test (End-to-End)
| Item | Description | Task ID | Verified |
|------|-------------|---------|----------|
| Startup test | Server starts, WebSocket accepts connections | TASK-VA-020 | [ ] |
| ASR test | Speech audio -> transcript event via WebSocket | TASK-VA-020 | [ ] |
| LLM test | Transcript -> LLM generation -> response text | TASK-VA-020 | [ ] |
| TTS test | LLM response -> ClipCannon audio -> WebSocket | TASK-VA-020 | [ ] |
| Full loop test | Speak "Hello" -> hear response in "boris" voice | TASK-VA-020 | [ ] |
| DB verification | turns table has user + assistant rows | TASK-VA-020 | [ ] |
| Latency P95 | End-to-end P95 < 500ms | TASK-VA-020 | [ ] |
| Context window | 50 turns without overflow | TASK-VA-020 | [ ] |
| Sentence chunking | "Hello. How are you?" -> 2 TTS chunks | TASK-VA-020 | [ ] |
| Shutdown test | Clean shutdown, GPU memory < 1GB, all refs None | TASK-VA-020 | [ ] |

## Error Handling
| Error | Condition | Task ID | Verified |
|-------|-----------|---------|----------|
| ASRError | Whisper model load failure | TASK-VA-001, TASK-VA-006 | [ ] |
| LLMError | vLLM model load failure | TASK-VA-001, TASK-VA-007 | [ ] |
| TTSError | ClipCannon synthesis failure | TASK-VA-001, TASK-VA-010 | [ ] |
| ConfigError | Invalid/missing configuration | TASK-VA-001, TASK-VA-002 | [ ] |
| TransportError | WebSocket connection failure | TASK-VA-001, TASK-VA-016 | [ ] |
| VADError | Silero model load failure | TASK-VA-001, TASK-VA-005 | [ ] |
| DatabaseError | SQLite connection/query failure | TASK-VA-001, TASK-VA-003 | [ ] |

## Verification Checklist (from Phase 1 spec Section 9)
| # | Test | Task ID | Verified |
|---|------|---------|----------|
| 1 | Qwen3-14B loads to GPU | TASK-VA-007, TASK-VA-020 | [ ] |
| 2 | Whisper transcribes speech | TASK-VA-006, TASK-VA-020 | [ ] |
| 3 | ClipCannon TTS produces audio | TASK-VA-010, TASK-VA-020 | [ ] |
| 4 | VAD detects speech | TASK-VA-005, TASK-VA-020 | [ ] |
| 5 | WebSocket connects | TASK-VA-016, TASK-VA-020 | [ ] |
| 6 | Full loop: speak -> hear response | TASK-VA-020 | [ ] |
| 7 | Conversation logged to SQLite | TASK-VA-020 | [ ] |
| 8 | Latency P95 < 500ms | TASK-VA-020 | [ ] |
| 9 | Sentence chunker splits correctly | TASK-VA-011, TASK-VA-020 | [ ] |
| 10 | Context window doesn't overflow | TASK-VA-009, TASK-VA-020 | [ ] |

## Requirement-to-Task Mapping
| Requirement | Description | Primary Task(s) | E2E Verification |
|-------------|-------------|-----------------|------------------|
| REQ-ASR-01 | Real-time speech-to-text via Whisper | TASK-VA-006 | TASK-VA-020 (Test 02) |
| REQ-ASR-02 | VAD-gated speech detection | TASK-VA-005 | TASK-VA-020 (Test 02) |
| REQ-ASR-03 | Partial + final transcript events | TASK-VA-006 | TASK-VA-020 (Test 02) |
| REQ-LLM-01 | Qwen3-14B-FP8 via vLLM | TASK-VA-007 | TASK-VA-020 (Test 03) |
| REQ-LLM-02 | Streaming token generation | TASK-VA-007 | TASK-VA-020 (Test 03) |
| REQ-LLM-03 | Context window management | TASK-VA-009 | TASK-VA-020 (Test 08) |
| REQ-TTS-01 | ClipCannon voice synthesis | TASK-VA-010 | TASK-VA-020 (Test 04) |
| REQ-TTS-02 | Sentence-level chunked streaming | TASK-VA-011, TASK-VA-012 | TASK-VA-020 (Test 09) |
| REQ-CONV-01 | State machine (IDLE->LISTEN->THINK->SPEAK) | TASK-VA-013 | TASK-VA-020 (Test 05) |
| REQ-CONV-02 | Conversation history tracking | TASK-VA-013 | TASK-VA-020 (Test 06) |
| REQ-TRANS-01 | WebSocket bidirectional audio | TASK-VA-016 | TASK-VA-020 (Test 01) |
| REQ-TRANS-02 | FastAPI health + REST endpoints | TASK-VA-017 | TASK-VA-020 (Test 01) |
| REQ-ACT-01 | Wake word detection | TASK-VA-014 | -- |
| REQ-ACT-02 | Hotkey activation | TASK-VA-015 | -- |
| REQ-DB-01 | SQLite conversation + turn logging | TASK-VA-003, TASK-VA-018 | TASK-VA-020 (Test 06) |
| REQ-PERF-01 | P95 latency < 500ms | TASK-VA-018 | TASK-VA-020 (Test 07) |
| REQ-LIFE-01 | Clean startup and shutdown | TASK-VA-018 | TASK-VA-020 (Test 10) |
| REQ-CLI-01 | serve and talk CLI commands | TASK-VA-019 | TASK-VA-020 (Test 01) |
| REQ-CFG-01 | Configuration loading with defaults | TASK-VA-002 | TASK-VA-020 (via agent init) |

## Coverage Summary
- **Package Structure:** 10/10 covered (100%)
- **Configuration:** 3/3 covered (100%)
- **Database:** 5/5 covered (100%)
- **ASR Types:** 3/3 covered (100%)
- **VAD:** 3/3 covered (100%)
- **Streaming ASR:** 5/5 covered (100%)
- **LLM Brain:** 4/4 covered (100%)
- **System Prompt:** 2/2 covered (100%)
- **Context Manager:** 4/4 covered (100%)
- **ClipCannon Adapter:** 4/4 covered (100%)
- **Sentence Chunker:** 4/4 covered (100%)
- **Streaming TTS:** 4/4 covered (100%)
- **Conversation Manager:** 5/5 covered (100%)
- **Wake Word:** 3/3 covered (100%)
- **Hotkey:** 3/3 covered (100%)
- **WebSocket Transport:** 5/5 covered (100%)
- **FastAPI Server:** 5/5 covered (100%)
- **VoiceAgent Orchestrator:** 8/8 covered (100%)
- **CLI:** 5/5 covered (100%)
- **Integration Test:** 10/10 covered (100%)
- **Error Handling:** 7/7 covered (100%)
- **Verification Checklist:** 10/10 covered (100%)
- **Requirement Mapping:** 19/19 covered (100%)

**TOTAL COVERAGE: 100%**

## Validation Checklist
- [x] All data models have tasks
- [x] All service methods have tasks
- [x] All API endpoints have tasks
- [x] All error states handled
- [x] Task dependencies form valid DAG (no cycles)
- [x] Layer ordering correct (foundation -> logic -> surface)
- [x] Every verification checklist item maps to TASK-VA-020
- [x] Every requirement maps to at least one task
- [x] TASK-VA-020 provides E2E verification for all critical requirements
