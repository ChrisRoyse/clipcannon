# Voice Agent — Implementation Index

## Documents

| File | Description |
|------|-------------|
| [prd_voice_agent.md](prd_voice_agent.md) | Product Requirements Document (v3.0) |
| [ai_voice_agent_benchmarks.md](ai_voice_agent_benchmarks.md) | Industry benchmark research |
| [01_phase1_core_pipeline.md](01_phase1_core_pipeline.md) | Phase 1: Core voice pipeline (ASR + LLM + TTS + WebSocket) |
| [02_phase2_companion.md](02_phase2_companion.md) | Phase 2: Windows companion + capture system |
| [03_phase3_memory.md](03_phase3_memory.md) | Phase 3: OCR Provenance integration + memory retrieval |
| [04_phase4_intelligence.md](04_phase4_intelligence.md) | Phase 4: Dream state + persistent memory + conversation intelligence |
| [05_phase5_hardening.md](05_phase5_hardening.md) | Phase 5: Production hardening + benchmarks |

## Build Order

Phases must be implemented in order. Each phase's exit criteria must be met before starting the next.

```
Phase 1 (Weeks 1-3): Can talk to the agent, it responds in cloned voice
    │
Phase 2 (Weeks 4-5): Companion captures screen/audio/clipboard on Windows
    │
Phase 3 (Weeks 6-7): Agent can search captures and answer "what was I doing?"
    │
Phase 4 (Weeks 8-9): Dream state consolidation, cross-session memory, barge-in
    │
Phase 5 (Week 10):   Production polish, benchmarks, Docker compose
```

## Key Paths

| Item | Path |
|------|------|
| Voice agent source | `src/voiceagent/` |
| Companion source | `src/companion/` |
| Voice agent Docker | `docker/voiceagent/Dockerfile` |
| Companion PyInstaller spec | `src/companion/voiceagent-capture.spec` |
| Shared volume (Windows) | `C:\voiceagent_data\` |
| Agent data (Docker) | `/data/agent/` (~/.voiceagent/ equivalent) |
| Qwen3-14B model | `~/.cache/huggingface/hub/models--Qwen--Qwen3-14B-FP8/snapshots/9a283b4a5efbc09ce247e0ae5b02b744739e525a/` |
| ClipCannon voice profiles | `~/.clipcannon/voice_profiles.db` |
| OCR Provenance | Docker container `ocr-provenance-mcp` at port 3366 |

## Hardware

| Component | Spec |
|-----------|------|
| CPU | AMD Ryzen 9 9950X3D (16C/32T, 5.7GHz, 192MB L3) |
| GPU | NVIDIA RTX 5090 (Blackwell GB202, 170 SMs, 32GB GDDR7, CC 12.0) |
| RAM | 128GB DDR5-3592 |
| OS | Windows 11 Pro |
| CUDA | 13.1/13.2 |
