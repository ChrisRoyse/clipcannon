# AI Agent Constitution Template

> **Purpose**: Token-optimized, research-backed constitution template for AI coding agents.
> Keeps fresh-context agents aligned across sessions and multi-agent swarms.
>
> **Usage**: Copy this template, fill in `{PLACEHOLDERS}`, delete unused optional sections.
> Delete this header block and all `<!-- TEMPLATE NOTES -->` after customization.
>
> **Design Principles** (from research on 401+ repos, Anthropic/Manus/Arize findings):
> - Root file: <100 lines of universal rules (rest via progressive disclosure)
> - Every rule must fail the pruning test: "Would removing this cause mistakes?"
> - Specific > vague (100% compliance with specific rules vs inconsistent with vague)
> - Include WHY with constraints (enables edge-case reasoning)
> - Structured formats (tables, bullets) over prose (fewer tokens, better parsing)
> - Enforce style via linters/hooks, not constitution text
> - Pointers to docs, not inline copies

---

<!-- ═══════════════════════════════════════════════════════════════ -->
<!-- TEMPLATE STARTS BELOW — COPY FROM HERE                        -->
<!-- ═══════════════════════════════════════════════════════════════ -->

# Constitution: {PROJECT_NAME}

<!-- TEMPLATE NOTE: Keep this root section under 100 lines. It loads every session. -->

```xml
<constitution version="{SEMVER}">
```

## Identity

| Field | Value |
|-------|-------|
| Project | {PROJECT_NAME} |
| Version | {SEMVER} |
| Updated | {YYYY-MM-DD} |
| Domain | {DOMAIN_DESCRIPTION} |
| Stack | {LANGUAGE} {VERSION} / {FRAMEWORK} {VERSION} / {DATABASE} |
| Repository | {REPO_URL_OR_NAME} |

<!-- TEMPLATE NOTE: One-line description. Tells agent what it's working on. -->
**What**: {ONE_SENTENCE_PROJECT_DESCRIPTION}

## Critical Rules

<!-- TEMPLATE NOTE: ONLY rules where violation causes system failure. 5-10 max.
     Each rule: imperative verb, specific, testable. Include WHY in parentheses. -->

1. {CRITICAL_RULE_1} _(why: {RATIONALE})_
2. {CRITICAL_RULE_2} _(why: {RATIONALE})_
3. {CRITICAL_RULE_3} _(why: {RATIONALE})_
4. NEVER commit secrets, credentials, or .env files _(why: security)_
5. ALWAYS read a file before editing it _(why: prevents blind overwrites)_

## Build & Verify

<!-- TEMPLATE NOTE: Exact commands the agent cannot guess. Remove if standard. -->

```bash
{BUILD_COMMAND}        # Build
{TEST_COMMAND}         # Test (MUST run after code changes)
{LINT_COMMAND}         # Lint
{TYPECHECK_COMMAND}    # Type check
```

**After code changes**: {POST_CHANGE_PROTOCOL}

## Architecture

<!-- TEMPLATE NOTE: Only non-obvious structure. Skip standard framework layouts. -->

```
{ROOT}/
├── {SRC_DIR}/          # {PURPOSE}
│   ├── {SUBDIR_1}/     # {PURPOSE}
│   └── {SUBDIR_2}/     # {PURPOSE}
├── {TEST_DIR}/         # Tests
├── {DOCS_DIR}/         # Documentation
└── {CONFIG_DIR}/       # Configuration
```

**Key files**: {FILE_1} ({PURPOSE}), {FILE_2} ({PURPOSE})

## Conventions

<!-- TEMPLATE NOTE: Only conventions that DIFFER from language/framework defaults.
     If a linter enforces it, remove it from here. -->

| Scope | Convention |
|-------|-----------|
| Files | {FILE_NAMING_PATTERN} |
| Variables | {VARIABLE_NAMING_PATTERN} |
| Functions | {FUNCTION_NAMING_PATTERN} |
| Types | {TYPE_NAMING_PATTERN} |

**Patterns**:
- {PATTERN_1}: {BRIEF_DESCRIPTION}
- {PATTERN_2}: {BRIEF_DESCRIPTION}

## Anti-Patterns

<!-- TEMPLATE NOTE: Things the agent MUST NOT do. Be specific — include what to do instead. -->

| Do NOT | Do Instead | Why |
|--------|-----------|-----|
| {BAD_PRACTICE_1} | {GOOD_PRACTICE_1} | {REASON} |
| {BAD_PRACTICE_2} | {GOOD_PRACTICE_2} | {REASON} |
| {BAD_PRACTICE_3} | {GOOD_PRACTICE_3} | {REASON} |

## Security

<!-- TEMPLATE NOTE: Non-negotiable security rules. Reference specific threats. -->

- **Secrets**: {SECRET_HANDLING_RULE}
- **Input**: {INPUT_VALIDATION_RULE}
- **Paths**: {PATH_SANITIZATION_RULE}
- **Auth**: {AUTH_RULE}

## Performance Budgets

<!-- TEMPLATE NOTE: Only include if non-obvious thresholds exist. -->

| Component | Metric | Target |
|-----------|--------|--------|
| {COMPONENT_1} | {METRIC} | {TARGET} |
| {COMPONENT_2} | {METRIC} | {TARGET} |

## Known Gotchas

<!-- TEMPLATE NOTE: Non-obvious behaviors that have bitten agents before.
     Each one should prevent a real mistake. -->

| Gotcha | Workaround |
|--------|------------|
| {GOTCHA_1} | {WORKAROUND_1} |
| {GOTCHA_2} | {WORKAROUND_2} |

```xml
</constitution>
```

---

<!-- ═══════════════════════════════════════════════════════════════ -->
<!-- OPTIONAL SECTIONS — Include only if needed for your project    -->
<!-- Each section adds ~20-50 lines. Include via @import or inline. -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## [OPTIONAL] Data Model

<!-- TEMPLATE NOTE: Include when agents create/modify database schemas.
     Use compact notation. Omit if schema is self-documenting. -->

```
{TABLE_1} ({KEY_COLUMN} PK, {COLUMN_2}, {COLUMN_3}) -> {RELATIONSHIP}
{TABLE_2} ({KEY_COLUMN} PK, {FK_COLUMN} FK -> {TABLE_1}) -> {RELATIONSHIP}
```

**Invariants**:
- {DATA_INVARIANT_1}
- {DATA_INVARIANT_2}

**FK ordering for cascades**: {TABLE_A} -> {TABLE_B} -> {TABLE_C}

## [OPTIONAL] API Surface

<!-- TEMPLATE NOTE: Include when agents implement/modify APIs.
     Compact notation — full OpenAPI spec lives in docs/. -->

| Tool/Endpoint | Purpose | Key Params |
|--------------|---------|------------|
| {ENDPOINT_1} | {PURPOSE} | {PARAMS} |
| {ENDPOINT_2} | {PURPOSE} | {PARAMS} |

**Handler pattern**: {DESCRIBE_STANDARD_HANDLER_FLOW}

## [OPTIONAL] External Services

<!-- TEMPLATE NOTE: Include when agents interact with external APIs/services. -->

| Service | Auth | Rate Limit | Critical Notes |
|---------|------|------------|----------------|
| {SERVICE_1} | {AUTH_METHOD} | {LIMIT} | {NOTES} |
| {SERVICE_2} | {AUTH_METHOD} | {LIMIT} | {NOTES} |

## [OPTIONAL] Multi-Agent Coordination

<!-- TEMPLATE NOTE: Include for multi-agent/swarm projects.
     These rules keep fresh-context agents aligned. -->

**Shared State**: {WHERE_SHARED_STATE_LIVES}

**Handoff Protocol**:
1. Outgoing agent writes summary to {HANDOFF_LOCATION}
2. Summary includes: completed work, decisions made, blockers, next steps
3. Incoming agent reads {HANDOFF_LOCATION} before starting

**Consensus**: {CONSENSUS_METHOD} _(e.g., raft, last-writer-wins, coordinator-approved)_

**Memory Namespace**: {NAMESPACE} _(all agents read/write to same namespace)_

**Rules**:
- NEVER duplicate work another agent completed — check shared state first
- ALWAYS record decisions with rationale in shared memory
- When blocked, document blocker and move to next task — don't spin

## [OPTIONAL] Testing Requirements

<!-- TEMPLATE NOTE: Include when testing patterns are non-standard. -->

| Category | Coverage | Focus Areas |
|----------|----------|-------------|
| Unit | {TARGET}% | {AREAS} |
| Integration | {TARGET}% | {AREAS} |
| E2E | {CRITICAL_PATHS} | {AREAS} |

**Test protocol**: {DESCRIBE_TEST_WORKFLOW}

## [OPTIONAL] Configuration

<!-- TEMPLATE NOTE: Include only config the agent needs to know about.
     Don't list every env var — just the ones that affect behavior. -->

| Setting | Default | Notes |
|---------|---------|-------|
| {SETTING_1} | {DEFAULT} | {WHEN_TO_CHANGE} |
| {SETTING_2} | {DEFAULT} | {WHEN_TO_CHANGE} |

**Required env vars**: `{VAR_1}`, `{VAR_2}`

---

<!-- ═══════════════════════════════════════════════════════════════ -->
<!-- DEEP REFERENCE SECTIONS — Store in separate files, @import     -->
<!-- These are NOT loaded every session. Referenced on demand.       -->
<!-- ═══════════════════════════════════════════════════════════════ -->

## [REFERENCE] Detailed Architecture → `{DOCS_DIR}/architecture.md`

<!-- TEMPLATE NOTE: Point to, don't inline. Agent reads when needed. -->

## [REFERENCE] Full Data Model → `{DOCS_DIR}/data-models.md`

## [REFERENCE] API Contracts → `{DOCS_DIR}/api-contracts.md`

## [REFERENCE] Decision Log → `{DOCS_DIR}/decisions.md`

## [REFERENCE] Migration History → `{DOCS_DIR}/migrations.md`

---

<!-- ═══════════════════════════════════════════════════════════════ -->
<!-- APPENDIX: TEMPLATE DESIGN RATIONALE                            -->
<!-- Delete this entire appendix after customizing.                  -->
<!-- ═══════════════════════════════════════════════════════════════ -->

# Appendix: Design Rationale & Optimization Guide

## Why This Structure

This template is designed from research across 35+ sources including:
- **401 repo empirical study** (arXiv:2512.18925) — identified 5 themes, 20 codes
- **Constitutional Spec-Driven Development** (arXiv:2602.02584) — 100% compliance with specific rules
- **Anthropic's context engineering** — "context window fills up fast, performance degrades as it fills"
- **Manus production insights** — KV-cache optimization (10x cost savings)
- **Arize prompt learning** — +5% general, +10.87% repo-specific improvement from optimized instructions
- **Constitutional Evolution** (arXiv:2602.00755) — 123% stability improvement over HHH baselines

## Token Budget Guidelines

| Component | Target Lines | Loaded When |
|-----------|-------------|-------------|
| Root constitution | 60-100 | Every session |
| Optional sections (each) | 20-50 | When relevant |
| Reference sections | 0 (pointer only) | On demand |
| **Total loaded per session** | **80-200** | Adaptive |

**Key metrics**:
- LLMs consistently follow ~150-200 instructions max (HumanLayer)
- Claude Code uses ~50 instructions internally, leaving ~100-150 for you
- GitHub Copilot degrades above 1,000 lines
- Cached tokens cost 10x less than uncached (keep prefixes stable)

## The Pruning Test

For each line, ask:
1. Would removing this cause the agent to make a mistake? → Keep
2. Does the agent already do this correctly without the instruction? → Remove
3. Can a linter/hook enforce this automatically? → Remove, add hook instead
4. Is this standard for the language/framework? → Remove
5. Does this duplicate information available in the codebase? → Remove

## Compression Techniques Applied

1. **Tables over prose** — 40-60% fewer tokens for equivalent information
2. **Imperative verbs** — "NEVER X" vs "You should not X" (3 tokens vs 5)
3. **Inline rationale** — `_(why: X)_` vs separate explanation paragraph
4. **Pointer pattern** — `→ docs/X.md` vs 200-line inline copy
5. **Compact notation** — `TABLE (col PK, col FK -> TABLE)` vs full DDL
6. **One-line descriptions** — Force conciseness at the metadata level
7. **Conditional sections** — [OPTIONAL] tags signal what to include/exclude

## Multi-Agent Alignment Strategies

Fresh-context agents lose all prior session knowledge. This template addresses it via:

1. **Self-contained identity** — Agent immediately knows what project, stack, domain
2. **Critical rules first** — Most important constraints in first 20 lines
3. **Shared state protocol** — Explicit handoff format prevents conflicting work
4. **Decision recording** — Rationale with every rule enables edge-case reasoning
5. **Known gotchas** — Prevent repeated mistakes across agent sessions
6. **Progressive disclosure** — Load only relevant optional sections per task

## Anti-Pattern Checklist

Before finalizing your constitution, verify you haven't:

- [ ] Included rules the agent already follows by default
- [ ] Written vague rules like "write clean code" or "follow best practices"
- [ ] Pasted large code blocks that belong in reference docs
- [ ] Added style rules that a linter can enforce
- [ ] Included information that changes frequently (timestamps, counts)
- [ ] Duplicated framework documentation the model already knows
- [ ] Created contradictory rules that confuse the agent
- [ ] Exceeded 200 lines in the root file

## Example: Minimal Constitution (42 lines)

```markdown
# Constitution: MyApp

| Field | Value |
|-------|-------|
| Project | MyApp |
| Version | 1.0.0 |
| Stack | TypeScript 5.x / Next.js 15 / PostgreSQL 16 |

**What**: SaaS dashboard for real-time analytics with role-based access.

## Critical Rules

1. NEVER use `any` type — use `unknown` + type guards _(why: type safety)_
2. NEVER call APIs from React components — use server actions _(why: architecture)_
3. ALWAYS validate input with Zod at API boundaries _(why: security)_
4. NEVER commit .env files _(why: secrets leak)_

## Build & Verify

\```bash
pnpm build          # Build
pnpm test           # Test
pnpm lint           # Lint (Biome)
\```

## Conventions

| Scope | Convention |
|-------|-----------|
| Files | kebab-case (e.g., user-profile.tsx) |
| Components | PascalCase (e.g., UserProfile) |
| DB tables | snake_case plural (e.g., user_sessions) |

## Anti-Patterns

| Do NOT | Do Instead | Why |
|--------|-----------|-----|
| Raw SQL strings | Drizzle ORM queries | SQL injection |
| Client-side auth checks | Middleware + server validation | Bypassable |
| console.log in production | Structured logger (pino) | Noise + perf |

## Known Gotchas

| Gotcha | Workaround |
|--------|------------|
| Next.js caches aggressively | Use `revalidatePath()` after mutations |
| Drizzle migrations need `pnpm db:push` | Run after any schema change |

## References

- Architecture → `docs/architecture.md`
- Data model → `docs/schema.md`
- API contracts → `docs/api.md`
```

## Sources

- [Anthropic: Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Anthropic: Claude Code Best Practices](https://code.claude.com/docs/en/best-practices)
- [Manus: Context Engineering Lessons](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- [Arize: CLAUDE.md Optimization with Prompt Learning](https://arize.com/blog/claude-md-best-practices-learned-from-optimizing-claude-code-with-prompt-learning/)
- [HumanLayer: Writing a Good CLAUDE.md](https://www.humanlayer.dev/blog/writing-a-good-claude-md)
- [arXiv:2512.18925: Empirical Study of Cursor Rules (401 repos)](https://arxiv.org/abs/2512.18925)
- [arXiv:2602.02584: Constitutional Spec-Driven Development](https://arxiv.org/abs/2602.02584)
- [arXiv:2602.00755: Evolving Constitutions for Multi-Agent Coordination](https://arxiv.org/abs/2602.00755)
- [Vellum: Multi-Agent Context Engineering](https://www.vellum.ai/blog/multi-agent-systems-building-with-context-engineering)
- [GitHub Copilot Custom Instructions](https://docs.github.com/copilot/customizing-copilot/adding-custom-instructions-for-github-copilot)
- [GitHub Spec Kit](https://github.com/github/spec-kit)
- [Softcery: Agentic Coding Best Practices](https://softcery.com/lab/softcerys-guide-agentic-coding-best-practices)
