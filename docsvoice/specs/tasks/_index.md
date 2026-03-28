# Task Index: Voice Agent Phase 1 -- Core Voice Pipeline

## Overview
- **Total Tasks:** 20
- **Foundation:** 4 tasks (TASK-VA-001 through TASK-VA-004)
- **Logic:** 11 tasks (TASK-VA-005 through TASK-VA-015)
- **Surface:** 5 tasks (TASK-VA-016 through TASK-VA-020)
- **Current Progress:** 0/20 (0%)

## Dependency Graph

```mermaid
graph TD
    subgraph Foundation
        T001[TASK-VA-001: Project Scaffolding]
        T002[TASK-VA-002: Configuration]
        T003[TASK-VA-003: Database Schema]
        T004[TASK-VA-004: ASR Types]
    end

    subgraph Logic
        T005[TASK-VA-005: Silero VAD Wrapper]
        T006[TASK-VA-006: Streaming ASR]
        T007[TASK-VA-007: LLM Brain]
        T008[TASK-VA-008: System Prompt Builder]
        T009[TASK-VA-009: Context Window Manager]
        T010[TASK-VA-010: ClipCannon Adapter]
        T011[TASK-VA-011: Sentence Chunker]
        T012[TASK-VA-012: Streaming TTS]
        T013[TASK-VA-013: Conversation State Machine]
        T014[TASK-VA-014: Wake Word Detector]
        T015[TASK-VA-015: Hotkey Activator]
    end

    subgraph Surface
        T016[TASK-VA-016: WebSocket Transport]
        T017[TASK-VA-017: FastAPI Server]
        T018[TASK-VA-018: VoiceAgent Orchestrator]
        T019[TASK-VA-019: CLI Entry Point]
        T020[TASK-VA-020: Integration Test]
    end

    %% Foundation dependencies
    T001 --> T002
    T001 --> T003
    T001 --> T004

    %% Logic depends on Foundation
    T004 --> T005
    T002 --> T005
    T004 --> T006
    T005 --> T006
    T002 --> T007
    T001 --> T008
    T002 --> T009
    T007 --> T009
    T002 --> T010
    T001 --> T011
    T010 --> T012
    T011 --> T012
    T001 --> T013
    T002 --> T014
    T001 --> T015

    %% Surface depends on Logic
    T001 --> T016
    T016 --> T017
    T002 --> T017
    T006 --> T018
    T007 --> T018
    T008 --> T018
    T009 --> T018
    T010 --> T018
    T011 --> T018
    T012 --> T018
    T013 --> T018
    T014 --> T018
    T015 --> T018
    T016 --> T018
    T003 --> T018
    T017 --> T018
    T018 --> T019
    T017 --> T019
    T019 --> T020
    T001 --> T020
    T002 --> T020
    T003 --> T020
    T004 --> T020
    T005 --> T020
    T006 --> T020
    T007 --> T020
    T008 --> T020
    T009 --> T020
    T010 --> T020
    T011 --> T020
    T012 --> T020
    T013 --> T020
    T014 --> T020
    T015 --> T020
    T016 --> T020
    T017 --> T020
    T018 --> T020
```

## Execution Order

| # | Task ID | Title | Layer | Depends On | Status |
|---|---------|-------|-------|------------|--------|
| 1 | TASK-VA-001 | Project Scaffolding | foundation | -- | Ready |
| 2 | TASK-VA-002 | Configuration | foundation | 001 | Blocked |
| 3 | TASK-VA-003 | Database Schema | foundation | 001 | Blocked |
| 4 | TASK-VA-004 | ASR Types | foundation | 001 | Blocked |
| 5 | TASK-VA-005 | Silero VAD Wrapper | logic | 002, 004 | Blocked |
| 6 | TASK-VA-006 | Streaming ASR | logic | 004, 005 | Blocked |
| 7 | TASK-VA-007 | LLM Brain | logic | 002 | Blocked |
| 8 | TASK-VA-008 | System Prompt Builder | logic | 001 | Blocked |
| 9 | TASK-VA-009 | Context Window Manager | logic | 002, 007 | Blocked |
| 10 | TASK-VA-010 | ClipCannon Adapter | logic | 002 | Blocked |
| 11 | TASK-VA-011 | Sentence Chunker | logic | 001 | Blocked |
| 12 | TASK-VA-012 | Streaming TTS | logic | 010, 011 | Blocked |
| 13 | TASK-VA-013 | Conversation State Machine | logic | 001 | Blocked |
| 14 | TASK-VA-014 | Wake Word Detector | logic | 002 | Blocked |
| 15 | TASK-VA-015 | Hotkey Activator | logic | 001 | Blocked |
| 16 | TASK-VA-016 | WebSocket Transport | surface | 001 | Blocked |
| 17 | TASK-VA-017 | FastAPI Server | surface | 002, 016 | Blocked |
| 18 | TASK-VA-018 | VoiceAgent Orchestrator | surface | 003, 006-017 | Blocked |
| 19 | TASK-VA-019 | CLI Entry Point | surface | 017, 018 | Blocked |
| 20 | TASK-VA-020 | Integration Test | surface | 001-019 (ALL) | Blocked |

## Status Legend
- Ready -- Can be started now
- In Progress -- Currently being worked on
- Complete -- Finished and verified
- Blocked -- Waiting on dependencies
- Failed -- Needs revision

## Critical Path
```
TASK-VA-001 --> TASK-VA-004 --> TASK-VA-005 --> TASK-VA-006 --> TASK-VA-018 --> TASK-VA-019 --> TASK-VA-020
```

TASK-VA-020 is the final gate. It depends on ALL 19 prior tasks and proves the entire Phase 1 pipeline works end-to-end with real GPU models, real audio, and real database writes.

## Parallel Opportunities
- **Batch 1:** TASK-VA-001 (sole starting task, no dependencies)
- **Batch 2:** TASK-VA-002, TASK-VA-003, TASK-VA-004 (all depend only on 001)
- **Batch 3:** TASK-VA-005, TASK-VA-007, TASK-VA-008, TASK-VA-010, TASK-VA-011, TASK-VA-013, TASK-VA-014, TASK-VA-015 (independent within logic layer, various foundation deps)
- **Batch 4:** TASK-VA-006 (depends on 005), TASK-VA-009 (depends on 007), TASK-VA-012 (depends on 010, 011)
- **Batch 5:** TASK-VA-016 (independent surface entry point)
- **Batch 6:** TASK-VA-017 (depends on 016)
- **Batch 7:** TASK-VA-018 (depends on most logic tasks + 016 + 017)
- **Batch 8:** TASK-VA-019 (depends on 017, 018)
- **Batch 9:** TASK-VA-020 (depends on ALL prior tasks -- final integration gate)
