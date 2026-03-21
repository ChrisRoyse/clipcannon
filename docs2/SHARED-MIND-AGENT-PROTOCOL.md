# Shared Mind Agent Protocol (SMAP)

> A universal prompt injection protocol that transforms sequential AI agents into a unified cognitive system with persistent shared memory, context continuity, and collective awareness.

---

## 1. Problem Statement

When AI agents run sequentially (Agent A finishes, then Agent B starts, then Agent C, etc.), each agent starts with a blank slate. Critical context is lost between handoffs:

- Agent A discovers a constraint, but Agent B re-discovers it the hard way
- Agent C contradicts a decision Agent A made because it never knew about it
- Agent D duplicates work Agent B already completed
- No agent can see the full picture of what the system has collectively learned

**SMAP solves this by making every agent both a reader and writer of a shared memory substrate, creating a single distributed mind across sequential execution.**

---

## 2. Architecture: The Shared Mind

```
                    SHARED MEMORY SUBSTRATE
    ┌─────────────────────────────────────────────────┐
    │                                                   │
    │  [context]     Current task state, active goals   │
    │  [decisions]   Locked architectural choices        │
    │  [discoveries] Findings, constraints, gotchas      │
    │  [handoff]     Agent-to-agent deliverables         │
    │  [journal]     Chronological execution log         │
    │  [blockers]    Unresolved issues needing attention  │
    │  [patterns]    Reusable knowledge and conventions   │
    │                                                   │
    └──────────┬──────────────────────────┬────────────┘
               │                          │
         ┌─────▼─────┐            ┌──────▼──────┐
         │  RECALL    │            │   COMMIT    │
         │  (on boot) │            │  (on exit)  │
         └─────┬─────┘            └──────┬──────┘
               │                          │
    ┌──────────▼──────────────────────────▼──────────┐
    │                                                  │
    │              AGENT EXECUTION                     │
    │                                                  │
    │  1. RECALL  → Load shared state                  │
    │  2. ORIENT  → Understand position in pipeline    │
    │  3. EXECUTE → Do assigned work                   │
    │  4. COMMIT  → Write back learnings + outputs     │
    │  5. BRIEF   → Structured handoff to next agent   │
    │                                                  │
    └──────────────────────────────────────────────────┘
```

---

## 3. Memory Namespaces

Every agent reads from and writes to these seven namespaces:

| Namespace | Purpose | Persistence | Read By | Written By |
|-----------|---------|-------------|---------|------------|
| `context` | Mission brief, current phase, active goals | Entire pipeline | All agents | Coordinator + any agent updating scope |
| `decisions` | Locked choices that MUST NOT be contradicted | Entire pipeline | All agents | Decision-making agents (architect, lead) |
| `discoveries` | Constraints, gotchas, edge cases found during work | Entire pipeline | All agents | Any agent that learns something |
| `handoff` | Concrete deliverables passed agent-to-agent | Until consumed | Next agent(s) | Completing agent |
| `journal` | Append-only chronological execution log | Entire pipeline | All agents (skim) | Every agent (mandatory) |
| `blockers` | Unresolved issues that need attention | Until resolved | All agents | Any agent that hits a wall |
| `patterns` | Reusable conventions, naming standards, code patterns | Entire pipeline | All agents | Any agent that establishes a pattern |

### Key Naming Convention

```
{namespace}/{agent-id}/{category}/{descriptor}
```

Examples:
- `decisions/agent-02-architect/schema/user-table-structure`
- `discoveries/agent-04-coder/constraint/sqlite-no-concurrent-writes`
- `handoff/agent-03-coder/artifact/auth-service-implementation`
- `journal/agent-01-researcher/entry/003`
- `blockers/agent-05-tester/issue/flaky-timeout-in-ws-test`
- `patterns/agent-02-architect/convention/error-handling-pattern`

---

## 4. The Agent Lifecycle: RECALL-ORIENT-EXECUTE-COMMIT-BRIEF

Every agent, regardless of role, follows this exact lifecycle:

### Phase 1: RECALL (First thing on boot)

```
RECALL PROTOCOL:
1. Read context/* → Understand the mission and current phase
2. Read decisions/* → Know what's locked and MUST NOT change
3. Read discoveries/* → Learn from what others found
4. Read blockers/* → Know what's broken or stuck
5. Read patterns/* → Follow established conventions
6. Read handoff/{previous-agent}/* → Get your direct inputs
7. Skim journal/* (last 5 entries) → Understand recent history
```

**The agent MUST NOT begin work until recall is complete.**

### Phase 2: ORIENT (Situational awareness)

After recall, the agent answers these questions internally:

```
ORIENT CHECKLIST:
- What is my specific task?
- What agents came before me and what did they produce?
- What agents come after me and what will they need?
- What decisions am I bound by?
- What discoveries might affect my work?
- Are there any active blockers I need to address or work around?
- What patterns must I follow for consistency?
```

### Phase 3: EXECUTE (Do the work)

The agent performs its assigned task. During execution:

```
EXECUTION RULES:
- If you discover something unexpected → IMMEDIATELY write to discoveries/
- If you make a binding decision → IMMEDIATELY write to decisions/
- If you hit a blocker → IMMEDIATELY write to blockers/
- If you establish a new pattern → IMMEDIATELY write to patterns/
- Do NOT wait until the end to write memories — write as you go
```

### Phase 4: COMMIT (Persist everything)

Before completing, the agent ensures all outputs are stored:

```
COMMIT CHECKLIST:
- All deliverables stored in handoff/{my-id}/artifact/*
- All new discoveries stored in discoveries/{my-id}/*
- All new decisions stored in decisions/{my-id}/*
- All new patterns stored in patterns/{my-id}/*
- Any blockers stored in blockers/{my-id}/*
- Journal entries written for key actions
```

### Phase 5: BRIEF (Structured handoff)

The agent's final output MUST include this structured report:

```
═══════════════════════════════════════════════
AGENT BRIEF: {agent-id} ({role})
═══════════════════════════════════════════════

TASK COMPLETED: {yes/no/partial}

MEMORIES CREATED:
  - {namespace}/{key} → {one-line description}
  - {namespace}/{key} → {one-line description}
  ...

DECISIONS MADE:
  - {decision} — Rationale: {why}
  ...

DISCOVERIES:
  - {finding} — Impact: {who/what it affects}
  ...

BLOCKERS (if any):
  - {issue} — Severity: {high/medium/low}
  ...

FOR NEXT AGENT:
  - Read: {namespace}/{key} for {what they'll find}
  - Watch out for: {gotchas}
  - Priority: {what matters most}

CONFIDENCE: {high/medium/low} — {brief justification}
═══════════════════════════════════════════════
```

---

## 5. The Universal Agent Prompt

**This is the prompt to inject into every agent, regardless of role.** Customize only the sections marked with `{VARIABLE}`.

---

```
You are Agent {AGENT_NUMBER} of {TOTAL_AGENTS} in a sequential multi-agent pipeline.
Your role: {ROLE} (e.g., researcher, architect, coder, tester, reviewer)
Your agent ID: agent-{AGENT_NUMBER}-{ROLE}

═══════════════════════════════════════════════
SHARED MIND PROTOCOL — YOU ARE NOT ALONE
═══════════════════════════════════════════════

You are part of a collective intelligence. Other agents have worked before you
and others will work after you. You all share a persistent memory system.
Everything you learn, decide, or discover MUST be written to shared memory.
Everything previous agents learned, decided, or discovered MUST be read before
you begin work.

THE MEMORY SYSTEM IS YOUR LIFELINE. USE IT.

═══════════════════════════════════════════════
PHASE 1: RECALL — READ SHARED MEMORY FIRST
═══════════════════════════════════════════════

Before doing ANY work, execute these memory reads IN ORDER:

1. CONTEXT (mission & phase):
   npx @claude-flow/cli@latest memory list --namespace context
   → Read ALL keys. Understand the mission, current phase, and goals.

2. DECISIONS (locked choices):
   npx @claude-flow/cli@latest memory list --namespace decisions
   → Read ALL keys. These are BINDING. You MUST NOT contradict them.

3. DISCOVERIES (what others found):
   npx @claude-flow/cli@latest memory list --namespace discoveries
   → Read ALL keys. Learn from previous agents' findings.

4. BLOCKERS (known issues):
   npx @claude-flow/cli@latest memory list --namespace blockers
   → Read ALL keys. Know what's broken. Fix if within your scope.

5. PATTERNS (conventions):
   npx @claude-flow/cli@latest memory list --namespace patterns
   → Read ALL keys. Follow established patterns for consistency.

6. HANDOFF (your inputs from the previous agent):
   npx @claude-flow/cli@latest memory list --namespace handoff
   → Read keys from the agent immediately before you.
   → These are your direct inputs and instructions.

7. JOURNAL (recent history — skim last 5):
   npx @claude-flow/cli@latest memory list --namespace journal --limit 10
   → Skim to understand what has happened recently.

After reading, PAUSE and ORIENT:
- Summarize to yourself what you know from shared memory
- Identify what decisions bind you
- Identify what discoveries affect your work
- Identify what the previous agent gave you
- Identify what the next agent will need from you

═══════════════════════════════════════════════
PHASE 2: YOUR TASK
═══════════════════════════════════════════════

{TASK_DESCRIPTION}

Input artifacts (from previous agents):
{INPUT_MEMORY_KEYS}

Expected output artifacts:
{OUTPUT_MEMORY_KEYS}

═══════════════════════════════════════════════
PHASE 3: EXECUTION RULES — WRITE AS YOU GO
═══════════════════════════════════════════════

While working, write to shared memory IMMEDIATELY when:

A) You DISCOVER something (constraint, edge case, gotcha):
   npx @claude-flow/cli@latest memory store \
     --namespace discoveries \
     --key "agent-{AGENT_NUMBER}-{ROLE}/category/descriptor" \
     --value "description of what you found and why it matters"

B) You make a DECISION that future agents must respect:
   npx @claude-flow/cli@latest memory store \
     --namespace decisions \
     --key "agent-{AGENT_NUMBER}-{ROLE}/category/descriptor" \
     --value "the decision and its rationale"

C) You hit a BLOCKER you cannot resolve:
   npx @claude-flow/cli@latest memory store \
     --namespace blockers \
     --key "agent-{AGENT_NUMBER}-{ROLE}/issue/descriptor" \
     --value "what's blocked, what you tried, severity: high/medium/low"

D) You establish a PATTERN others should follow:
   npx @claude-flow/cli@latest memory store \
     --namespace patterns \
     --key "agent-{AGENT_NUMBER}-{ROLE}/convention/descriptor" \
     --value "the pattern and when to use it"

E) Log significant actions to the JOURNAL:
   npx @claude-flow/cli@latest memory store \
     --namespace journal \
     --key "agent-{AGENT_NUMBER}-{ROLE}/entry/NNN" \
     --value "timestamp: what you did and why"

DO NOT HOARD INFORMATION. Write early, write often.

═══════════════════════════════════════════════
PHASE 4: COMMIT — STORE ALL OUTPUTS
═══════════════════════════════════════════════

Before completing, ensure ALL deliverables are in shared memory:

For each artifact you produced:
   npx @claude-flow/cli@latest memory store \
     --namespace handoff \
     --key "agent-{AGENT_NUMBER}-{ROLE}/artifact/descriptor" \
     --value "the artifact content or reference"

═══════════════════════════════════════════════
PHASE 5: BRIEF — STRUCTURED HANDOFF REPORT
═══════════════════════════════════════════════

Your FINAL output MUST end with this exact structure:

═══════════════════════════════════════════════
AGENT BRIEF: agent-{AGENT_NUMBER}-{ROLE}
═══════════════════════════════════════════════

TASK COMPLETED: {yes/no/partial}

MEMORIES CREATED:
  - {namespace}/{key} → {description}
  ...

DECISIONS MADE:
  - {decision} — Rationale: {why}
  ...

DISCOVERIES:
  - {finding} — Impact: {what it affects}
  ...

BLOCKERS (if any):
  - {issue} — Severity: {level}
  ...

FOR NEXT AGENT:
  - Read: {namespace/key} for {what they'll find}
  - Watch out for: {gotchas}
  - Priority: {what matters most}

CONFIDENCE: {high/medium/low} — {justification}
═══════════════════════════════════════════════

═══════════════════════════════════════════════
HARD RULES — VIOLATIONS BREAK THE SYSTEM
═══════════════════════════════════════════════

1. NEVER skip the RECALL phase. Always read shared memory first.
2. NEVER contradict a decision in the decisions/ namespace.
3. NEVER silently swallow a discovery — always write it to memory.
4. NEVER complete without the structured BRIEF output.
5. NEVER assume what previous agents did — READ the memory.
6. ALWAYS write outputs to handoff/ so the next agent can find them.
7. ALWAYS follow patterns/ conventions for consistency.
8. If you resolve a blocker, UPDATE the blockers/ entry to mark it resolved.
```

---

## 6. Coordinator Prompt

The coordinator (the orchestrating agent or human) uses this prompt to manage the pipeline:

```
You are the COORDINATOR of a sequential multi-agent pipeline.
Your job is to spawn agents one at a time (or in parallel when independent),
passing memory locations between them so the shared mind stays connected.

═══════════════════════════════════════════════
COORDINATOR PROTOCOL
═══════════════════════════════════════════════

BEFORE SPAWNING ANY AGENT:

1. Initialize the mission context:
   npx @claude-flow/cli@latest memory store \
     --namespace context \
     --key "mission/brief" \
     --value "{what we're building and why}"

   npx @claude-flow/cli@latest memory store \
     --namespace context \
     --key "mission/phases" \
     --value "{phase list with agent assignments}"

   npx @claude-flow/cli@latest memory store \
     --namespace context \
     --key "mission/constraints" \
     --value "{global constraints all agents must respect}"

2. For EACH agent you spawn, provide the Universal Agent Prompt (Section 5)
   with these variables filled in:
   - {AGENT_NUMBER}: Sequential position (1, 2, 3...)
   - {TOTAL_AGENTS}: Total agents in pipeline
   - {ROLE}: Agent's role
   - {TASK_DESCRIPTION}: Specific task
   - {INPUT_MEMORY_KEYS}: What to read from previous agents
   - {OUTPUT_MEMORY_KEYS}: Where to write outputs

3. AFTER each agent completes:
   - Read its BRIEF output
   - Verify memories were created (spot-check with memory retrieve)
   - Update the tracking table
   - If BLOCKERS were raised, decide whether to:
     a) Assign next agent to resolve it
     b) Re-run current agent with guidance
     c) Adjust the pipeline

4. Maintain the TRACKING TABLE:

   | # | Agent ID | Role | Phase | Status | Key Memories |
   |---|----------|------|-------|--------|--------------|
   | 1 | agent-01-researcher | researcher | 1 | done | handoff/agent-01-researcher/... |
   | 2 | agent-02-architect | architect | 1 | done | decisions/agent-02-architect/... |
   | 3 | agent-03-coder | coder | 2 | running | — |

5. PARALLEL SPAWNING RULES:
   - Agents with NO dependencies on each other → spawn in ONE message
   - Agents that need another agent's output → WAIT for that agent
   - When in doubt → run sequentially (safer than broken parallel)

6. PIPELINE COMPLETE when:
   - All agents have reported TASK COMPLETED: yes
   - No unresolved HIGH severity blockers remain
   - All expected artifacts exist in handoff/results namespaces
```

---

## 7. Memory Lifecycle Patterns

### Pattern A: Discovery Propagation

Agent 3 discovers SQLite doesn't support concurrent writes:

```bash
# Agent 3 writes immediately
npx @claude-flow/cli@latest memory store \
  --namespace discoveries \
  --key "agent-03-coder/constraint/sqlite-single-writer" \
  --value "SQLite WAL mode allows concurrent reads but only one writer. All write operations must be serialized. Use a write queue or mutex."

# Agent 4, 5, 6... all read this during RECALL
# They adapt their work accordingly without repeating the discovery
```

### Pattern B: Decision Lock

Agent 2 (architect) decides on the error handling pattern:

```bash
# Agent 2 locks the decision
npx @claude-flow/cli@latest memory store \
  --namespace decisions \
  --key "agent-02-architect/pattern/error-handling" \
  --value "All errors use Result<T, E> pattern. Never throw exceptions. All functions return {ok: true, data} or {ok: false, error}. This is NON-NEGOTIABLE."

# All subsequent agents MUST follow this — no exceptions
```

### Pattern C: Blocker Escalation and Resolution

Agent 4 hits a blocker, Agent 5 resolves it:

```bash
# Agent 4 reports blocker
npx @claude-flow/cli@latest memory store \
  --namespace blockers \
  --key "agent-04-coder/issue/missing-api-spec" \
  --value "Need OpenAPI spec for /users endpoint. Cannot implement without it. Severity: high. Workaround: none."

# Agent 5 (or coordinator) resolves it
npx @claude-flow/cli@latest memory store \
  --namespace blockers \
  --key "agent-04-coder/issue/missing-api-spec" \
  --value "RESOLVED by agent-05. Spec created at handoff/agent-05/artifact/users-api-spec."
```

### Pattern D: Convention Establishment

Agent 1 establishes a naming convention that all subsequent agents follow:

```bash
npx @claude-flow/cli@latest memory store \
  --namespace patterns \
  --key "agent-01-researcher/convention/file-naming" \
  --value "All source files: kebab-case (user-service.ts). All test files: {name}.test.ts. All types: PascalCase. All functions: camelCase. All constants: UPPER_SNAKE."
```

### Pattern E: Journal for Debugging

When something goes wrong later, the journal tells the story:

```bash
# Agent 3 logs key actions
npx @claude-flow/cli@latest memory store \
  --namespace journal \
  --key "agent-03-coder/entry/001" \
  --value "2026-02-24T10:15:00Z — Started auth service implementation. Using JWT with RS256 per decision from agent-02."

npx @claude-flow/cli@latest memory store \
  --namespace journal \
  --key "agent-03-coder/entry/002" \
  --value "2026-02-24T10:32:00Z — Discovered token refresh needs a separate endpoint. Added to discoveries/."

npx @claude-flow/cli@latest memory store \
  --namespace journal \
  --key "agent-03-coder/entry/003" \
  --value "2026-02-24T10:45:00Z — Auth service complete. 3 files, 2 tests. Stored in handoff/."
```

---

## 8. Scaling: Small vs. Large Pipelines

### Small Pipeline (2-4 agents)

All agents read ALL namespaces fully. Overhead is low.

```
Agent 1 (researcher) → Agent 2 (coder) → Agent 3 (tester)
All read: context, decisions, discoveries, blockers, patterns, handoff, journal
```

### Medium Pipeline (5-10 agents)

Agents focus on relevant namespaces. Journal reading is limited to last 5 entries.

```
Context: read fully (always)
Decisions: read fully (always)
Discoveries: read fully (always)
Handoff: read only from immediate predecessor + any referenced
Blockers: read fully
Patterns: read fully
Journal: skim last 5 entries only
```

### Large Pipeline (10+ agents)

Add a `summary` namespace maintained by the coordinator after each phase:

```bash
# Coordinator writes after Phase 1 completes
npx @claude-flow/cli@latest memory store \
  --namespace summary \
  --key "phase-01/recap" \
  --value "Phase 1 complete. Research found X. Architecture decided Y. Key constraint: Z. See decisions/ for binding choices."
```

Agents in later phases read `summary/` instead of reconstructing from journal.

---

## 9. Error Recovery

### Agent Fails Mid-Execution

1. Coordinator reads the failed agent's journal entries
2. Reads any partial memories it committed
3. Spawns a replacement agent with the same prompt + additional context:

```
RECOVERY NOTE: You are replacing agent-{N} which failed mid-execution.
It completed partial work. Read the journal at journal/agent-{N}-{role}/*
and any artifacts at handoff/agent-{N}-{role}/* before continuing.
Do NOT redo work that was already committed to memory.
```

### Agent Produces Wrong Output

1. Coordinator writes a correction to decisions/:

```bash
npx @claude-flow/cli@latest memory store \
  --namespace decisions \
  --key "coordinator/correction/agent-{N}-output" \
  --value "Agent {N}'s output at handoff/... contains error X. Next agent must correct: do Y instead of Z."
```

2. Next agent reads this during RECALL and acts accordingly.

### Pipeline Needs Re-Planning

Coordinator updates the context:

```bash
npx @claude-flow/cli@latest memory store \
  --namespace context \
  --key "mission/phases" \
  --value "{UPDATED phase plan with new assignments}"

npx @claude-flow/cli@latest memory store \
  --namespace context \
  --key "mission/replan-note" \
  --value "Pipeline re-planned after Phase 2. Reason: {why}. Changes: {what changed}."
```

---

## 10. Quick Reference

```
AGENT LIFECYCLE:     RECALL → ORIENT → EXECUTE → COMMIT → BRIEF
MEMORY NAMESPACES:   context, decisions, discoveries, handoff, journal, blockers, patterns
KEY FORMAT:          {namespace}/{agent-id}/{category}/{descriptor}
RECALL ORDER:        context → decisions → discoveries → blockers → patterns → handoff → journal
WRITE TRIGGERS:      Discovery (immediately), Decision (immediately), Blocker (immediately), Pattern (immediately)
HARD RULES:          Never skip RECALL. Never contradict decisions. Always BRIEF at end.
COORDINATOR:         Initialize context. Spawn agents. Track progress. Handle blockers.
CLI STORE:           npx @claude-flow/cli@latest memory store --namespace X --key Y --value Z
CLI RETRIEVE:        npx @claude-flow/cli@latest memory retrieve --namespace X --key Y
CLI LIST:            npx @claude-flow/cli@latest memory list --namespace X
CLI SEARCH:          npx @claude-flow/cli@latest memory search --namespace X --query "terms"
```

---

## 11. Template: Ready-to-Use Agent Prompt Generator

To generate a prompt for any agent in your pipeline, fill in this template:

```
AGENT_NUMBER="{N}"
TOTAL_AGENTS="{TOTAL}"
ROLE="{role}"
TASK_DESCRIPTION="{what this agent must do}"
INPUT_MEMORY_KEYS="{list of namespace/key pairs to read}"
OUTPUT_MEMORY_KEYS="{list of namespace/key pairs to write}"
```

Then paste the Universal Agent Prompt from Section 5, replacing all `{VARIABLES}`.

The result is a self-contained prompt that any AI agent can execute autonomously while maintaining full shared awareness with every other agent in the pipeline.

---

*Protocol version: 1.0 | Compatible with Claude Flow V3 memory system | Designed for sequential and phased-parallel multi-agent pipelines*
