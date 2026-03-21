# Universal Search Algorithm for Claude Flow (USACF) - Enhanced Edition
## A Hyper-Advanced Multi-Agent Search Framework with Integrated AI Research Techniques
### Version 4.0 - The Complete Integration

make sure no agents outputs any file bigger than 1500 lines in length. if it needs to be bigger then it makes part2 and part3 etc
  of the file to extend it
---

## FRAMEWORK PHILOSOPHY

This framework represents the **complete synthesis** of the Universal Multi-Agent Search Algorithm with **20+ cutting-edge AI research techniques**, treating analysis as a **memory-coordinated, multi-dimensional, self-improving search through state space** where:

- **Multi-Agent Decomposition**: Parallel specialized subagents with synthesizers
- **Uncertainty Quantification**: Confidence scoring and active prompting
- **Adversarial Validation**: Red team critique and synthetic review
- **RAG Integration**: Grounded research with web search and tool use
- **Perspective Simulation**: Multi-stakeholder analysis
- **Meta-Learning**: Self-improving prompts and recursive optimization
- **Graduated Context**: Hot/warm/cold context tiering
- **Observability**: Full decision tracing and instrumentation
- **Version Control**: Source attribution and change tracking
- **Iterative Depth**: Adaptive analysis depth with validation gates

**Core Principle**: Every search is a coordinated, memory-based, self-improving system that combines human expertise with AI capabilities to achieve superhuman analytical depth.

---

## SECTION 0: PRE-SEARCH META-ANALYSIS

### 0.1 Step-Back Prompting (Establish Principles First)

**Before beginning any search**, establish high-level guiding principles:

```bash
npx claude-flow@alpha init
npx claude-flow@alpha agent memory init

# Initialize Meta-Analysis Agent
Task("meta-learning-agent", `
## STEP-BACK ANALYSIS

Before diving into {SUBJECT_NAME}, step back and articulate:

### 1. FUNDAMENTAL PRINCIPLES
What are the 5-7 core principles that define excellence in {SUBJECT_TYPE}?

Example (for software):
- Modularity and separation of concerns
- Performance under realistic load
- Security by design
- Testability and observability
- Developer experience and maintainability

### 2. EVALUATION CRITERIA
Based on these principles, what metrics will we use?

Format:
| Principle | Measurable Criteria | Target Threshold |
|-----------|--------------------|--------------------|
| ...       | ...                | ...                |

### 3. ANTI-PATTERNS TO AVOID
What are common mistakes in analyzing {SUBJECT_TYPE}?

List 7-10 anti-patterns with examples:
- ❌ Anti-pattern: [Description]
  - Why it fails: [Reason]
  - Instead do: [Alternative]

### 4. SUCCESS DEFINITION
How will we know this search succeeded?

Concrete success criteria:
- [ ] Coverage: Analyzed X% of {SUBJECT}
- [ ] Depth: Found Y gaps per major component
- [ ] Quality: Z% confidence in findings
- [ ] Actionability: Generated N prioritized opportunities

Store as: search/meta/principles
`)
```

### 0.2 Ambiguity Clarification Protocol

**Before proceeding**, identify and resolve all ambiguous terms:

```bash
Task("adaptive-coordinator", `
## AMBIGUITY CLARIFICATION

Analyze subject description: {SUBJECT_DESCRIPTION}

### IDENTIFY AMBIGUOUS TERMS
List 5-10 potentially ambiguous terms/phrases:

| Term | Interpretation A | Interpretation B | Interpretation C | Clarification Needed |
|------|------------------|------------------|------------------|---------------------|
| ...  | ...              | ...              | ...              | Yes/No              |

### REQUEST CLARIFICATION
For each "Yes", generate specific questions:
1. Term: [X] - Question: "Do you mean [A] or [B]? Please specify."

### PROVISIONAL ASSUMPTIONS
If clarification unavailable, document assumptions:
- Assuming: [X] means [Y] because [reasoning]
- Confidence: [0-100%]
- Risk if wrong: [Low/Medium/High]

Store as: search/meta/ambiguities
`)
```

### 0.3 Self-Ask Decomposition

**Generate essential questions** before analyzing:

```bash
Task("meta-learning-agent", `
## SELF-ASK DECOMPOSITION

Before mapping {SUBJECT_NAME}, generate 15-20 essential questions that must be answered:

### STRUCTURAL QUESTIONS
1. What are the primary components/modules?
2. How do they interact?
3. What are the critical paths?
4. Where are the dependencies?
5. What's the information flow?

### FUNCTIONAL QUESTIONS
6. What problems does this solve?
7. What are the core use cases?
8. What are edge cases?
9. What are failure modes?
10. What are performance bottlenecks?

### CONTEXTUAL QUESTIONS
11. Who are the stakeholders?
12. What are the constraints?
13. What are success metrics?
14. What are the risks?
15. What's the competitive landscape?

### META QUESTIONS
16. What don't we know yet?
17. What assumptions are we making?
18. Where might we be biased?
19. What could invalidate our analysis?
20. What would an expert focus on?

For each question:
- Answer with current knowledge
- Rate confidence: 0-100%
- Flag for deeper research if <70%

Store as: search/meta/self-ask-questions
`)
```

### 0.4 Iterative Depth Control Initialization

**Set analysis depth parameters**:

```bash
npx claude-flow memory store \
  --namespace "search/config" \
  --key "depth-control" \
  --value '{
    "depth_level": 3,           // 1=scan, 2=standard, 3=deep, 4=exhaustive, 5=extreme
    "breadth_factor": 7,        // # areas per level
    "iteration_strategy": "progressive",  // quick → deep
    "validation_gates": true,   // Check before next depth
    "adaptive_depth": true,     // Increase depth on uncertainty
    "max_iterations": 5,        // Per component
    "min_confidence": 0.85,     // To proceed
    "token_budget_per_phase": {
      "discovery": 10000,
      "analysis": 15000,
      "synthesis": 12000,
      "implementation": 8000
    }
  }'
```

### 0.5 Multi-Agent Planner (ReWOO: Plan Then Execute)

**Plan ALL research tasks upfront** before executing:

```bash
Task("adaptive-coordinator", `
## RESEARCH PLANNING (ReWOO)

Based on:
- Subject: {SUBJECT_NAME}
- Type: {SUBJECT_TYPE}
- Objectives: {OBJECTIVES}
- Depth: {DEPTH_LEVEL}

### PHASE 1: DISCOVERY (Plan All Tasks)
List ALL 15-25 discovery tasks needed:

| Task ID | Description | Agent | Dependencies | Parallel Group | Estimated Tokens |
|---------|-------------|-------|--------------|----------------|-------------------|
| D01     | Map structural architecture | system-architect | None | Group A | 1200 |
| D02     | Identify all components | system-architect | D01 | Group A | 800 |
| D03     | Trace data flows | code-analyzer | D01 | Group B | 1000 |
| ...     | ...         | ...   | ...  | ... | ... |

### PHASE 2: ANALYSIS (Plan All Tasks)
List ALL 20-30 analysis tasks:

| Task ID | Description | Agent | Dependencies | Parallel Group | Estimated Tokens |
|---------|-------------|-------|--------------|----------------|-------------------|
| A01     | Quality gap analysis | code-reviewer | D01-D10 | Group A | 1500 |
| A02     | Performance profiling | perf-analyzer | D03 | Group B | 1200 |
| ...     | ...         | ...   | ...  | ... | ... |

### PHASE 3: SYNTHESIS (Plan All Tasks)
[Similar planning for synthesis phase]

### PHASE 4: IMPLEMENTATION (Plan All Tasks)
[Similar planning for implementation phase]

### PARALLELIZATION OPPORTUNITIES
Identify tasks that can run simultaneously:
- Group A: [D01, D02, A01, A03] (independent)
- Group B: [D03, A02] (requires D01)
- Group C: [D04, D05] (requires D03)

### TOTAL RESOURCE ESTIMATE
- Total tasks: N
- Sequential time: X hours
- Parallel time: Y hours (Z% reduction)
- Total tokens: ~N,000

Store as: search/meta/research-plan
`)
```

### 0.6 Context Tiering Setup

**Organize context by access frequency**:

```bash
npx claude-flow memory store \
  --namespace "search/context" \
  --key "tier-structure" \
  --value '{
    "hot_context": {
      "description": "Critical info, loaded first, always in prompt",
      "max_tokens": 2000,
      "contents": [
        "Current phase",
        "Active objectives", 
        "Top 5 gaps",
        "Critical decisions",
        "Blocking issues"
      ]
    },
    "warm_context": {
      "description": "Frequently accessed, loaded on demand",
      "max_tokens": 5000,
      "contents": [
        "Methodology guides",
        "Component details",
        "Dependency graphs",
        "Risk matrices",
        "Opportunity scores"
      ]
    },
    "cold_context": {
      "description": "Comprehensive background, accessed only when needed",
      "contents": [
        "Full documentation",
        "Historical data",
        "Reference examples",
        "Research papers",
        "Complete trace logs"
      ]
    }
  }'

# Initialize hot context
Task("memory-manager", "Load hot context for Phase 0: [list critical items]")
```

---

## SECTION 1: ENHANCED CLAUDE FLOW INTEGRATION

### 1.1 Initialization with Observability

```bash
# ALWAYS FIRST - Initialize with full instrumentation
npx claude-flow@alpha init
npx claude-flow@alpha agent memory init
npx claude-flow@alpha agent memory status

# Enable observability logging
npx claude-flow memory store \
  --namespace "search/observability" \
  --key "config" \
  --value '{
    "decision_logging": true,
    "reasoning_traces": true,
    "confidence_tracking": true,
    "version_control": true,
    "attribution_required": true,
    "performance_metrics": true
  }'

# Initialize Search Session with Enhanced Metadata
npx claude-flow memory store \
  --namespace "search/session" \
  --key "config" \
  --value '{
    "search_id": "uuid",
    "version": "1.0.0",
    "subject": "Your subject",
    "subject_type": "software|business|process|product",
    "objectives": ["obj1", "obj2"],
    "constraints": {
      "time_limit": "2h",
      "quality_threshold": 0.85,
      "min_confidence": 0.80,
      "max_uncertainty": 0.20
    },
    "topology": "hierarchical",
    "depth_level": 3,
    "validation_gates_enabled": true,
    "adversarial_review_enabled": true,
    "multi_persona_enabled": true,
    "rag_enabled": true,
    "started_at": "2025-11-18T10:00:00Z",
    "techniques_enabled": [
      "multi-agent-decomposition",
      "uncertainty-quantification", 
      "step-back-prompting",
      "contrastive-prompting",
      "rag-integration",
      "perspective-simulation",
      "meta-prompting",
      "validation-gates",
      "adversarial-review",
      "version-control"
    ]
  }'

# Initialize Enhanced State Space
npx claude-flow memory store \
  --namespace "search/state" \
  --key "current" \
  --value '{
    "state_id": "S0",
    "version": "1.0.0",
    "generation": 0,
    "phase": "initialization",
    "completeness": 0.0,
    "confidence": 0.0,
    "uncertainty": 1.0,
    "decision_log": [],
    "validation_passed": false
  }'

# Initialize Version Control
npx claude-flow memory store \
  --namespace "search/version-control" \
  --key "changelog" \
  --value '{
    "versions": [
      {
        "version": "1.0.0",
        "timestamp": "2025-11-18T10:00:00Z",
        "phase": "initialization",
        "changes": "Initial state",
        "confidence_delta": 0.0,
        "author_agent": "orchestrator"
      }
    ]
  }'
```

### 1.2 Enhanced Search State Structure

```typescript
// Stored in: search/state/{state_id}
interface EnhancedSearchState {
  // Metadata
  state_id: string;
  version: string;
  parent_state_id: string | null;
  generation: number;
  timestamp: string;
  
  // Subject Context
  subject: {
    name: string;
    type: string;
    domain: string;
    objectives: string[];
    stakeholders: string[];
    constraints: Record<string, any>;
  };
  
  // Discovery Artifacts (with confidence scores)
  structural_map: {
    component_count: number;
    hierarchy_depth: number;
    completeness: number;
    confidence: number;              // NEW
    uncertain_areas: string[];       // NEW
    sources: string[];               // NEW (attribution)
  };
  
  // Gap Register (with uncertainty)
  gap_register: {
    total_gaps: number;
    severity_distribution: Record<string, number>;
    priority_scores: Record<string, number>;
    confidence_scores: Record<string, number>;  // NEW
    validation_status: Record<string, string>;  // NEW
    sources: Record<string, string[]>;          // NEW
  };
  
  // Risk Profile (with probability distributions)
  risk_profile: {
    total_risks: number;
    high_rpn_count: number;
    mitigation_coverage: number;
    uncertainty_quantified: boolean;             // NEW
    confidence_intervals: Record<string, [number, number]>; // NEW
  };
  
  // Opportunity Space (multi-scored)
  opportunity_space: {
    total_opportunities: number;
    pareto_frontier_size: number;
    top_priority_ids: string[];
    stakeholder_scores: Record<string, Record<string, number>>; // NEW
    confidence_by_opportunity: Record<string, number>;          // NEW
  };
  
  // Implementation Plan
  implementation_plan: {
    phase_count: number;
    task_count: number;
    resource_allocated: boolean;
    risk_mitigation_planned: boolean;  // NEW
    validation_protocols_defined: boolean; // NEW
  };
  
  // Enhanced Quality Metrics
  quality: {
    completeness: number;        // 0-1
    confidence: number;          // 0-1
    uncertainty: number;         // 0-1 (NEW)
    consistency: number;         // 0-1
    actionability: number;       // 0-1
    novelty: number;            // 0-1
    coverage: number;           // 0-1
    source_quality: number;     // 0-1 (NEW)
    validation_score: number;   // 0-1 (NEW)
  };
  
  // Observability Data (NEW)
  observability: {
    decision_log: DecisionLogEntry[];
    reasoning_traces: ReasoningTrace[];
    confidence_history: ConfidenceSnapshot[];
    bottlenecks: string[];
    errors_encountered: ErrorLog[];
  };
  
  // Search Control
  control: {
    active_phase: string;
    next_operators: string[];
    exploration_rate: number;
    stopping_criteria_met: boolean;
    validation_gates_passed: string[];    // NEW
    depth_level: number;                   // NEW
    iteration_count: number;               // NEW
  };
  
  // Multi-Persona Analysis (NEW)
  perspectives: {
    analyzed_from: string[];               // Stakeholder types
    conflicts: Array<{
      perspective_a: string;
      perspective_b: string;
      conflict_description: string;
      resolution_needed: boolean;
    }>;
  };
  
  // Adversarial Review (NEW)
  adversarial_review: {
    completed: boolean;
    critiques: string[];
    weaknesses_identified: string[];
    corrections_applied: string[];
    final_confidence: number;
  };
}

interface DecisionLogEntry {
  timestamp: string;
  decision: string;
  reasoning: string;
  alternatives_considered: string[];
  confidence: number;
  dependencies: string[];
  agent: string;
}

interface ReasoningTrace {
  step_id: string;
  agent: string;
  thought_process: string;
  evidence_used: string[];
  conclusion: string;
  confidence: number;
}

interface ConfidenceSnapshot {
  timestamp: string;
  phase: string;
  overall_confidence: number;
  component_confidence: Record<string, number>;
}
```

### 1.3 Enhanced Memory Namespace Convention

```bash
# Session Management
search/session/config                      # Enhanced configuration
search/session/history                     # State transition history
search/session/metrics                     # Performance metrics
search/session/changelog                   # NEW: Version history

# Meta-Analysis (NEW)
search/meta/principles                     # Step-back principles
search/meta/ambiguities                    # Ambiguity clarifications
search/meta/self-ask-questions            # Self-generated questions
search/meta/research-plan                 # ReWOO planning
search/meta/anti-patterns                 # Contrastive examples

# Context Tiers (NEW)
search/context/hot                         # Critical, always loaded
search/context/warm                        # Frequently accessed
search/context/cold                        # Background reference

# Current State
search/state/current                       # Active search state
search/state/best                          # Best state found
search/state/archive                       # Pareto archive

# Discovery Phase (Enhanced)
search/discovery/structural/{id}           # Components + confidence
search/discovery/flows/{id}                # Flows + uncertainty
search/discovery/dependencies/{id}         # Dependencies + validation
search/discovery/critical-paths/{id}       # Critical paths + alternatives
search/discovery/sources/{id}              # NEW: Source attributions
search/discovery/confidence/{id}           # NEW: Confidence scores

# Analysis Phase (Enhanced)
search/gaps/quality/{id}                   # Quality gaps + confidence
search/gaps/performance/{id}               # Performance + uncertainty
search/gaps/structural/{id}                # Structural + validation
search/gaps/resource/{id}                  # Resource + attribution
search/gaps/confidence/{id}                # NEW: Gap confidence scores

search/risks/fmea/{id}                     # FMEA + probability
search/risks/edge-cases/{id}               # Edge cases + likelihood
search/risks/vulnerabilities/{id}          # Vulns + exploit probability
search/risks/uncertainty/{id}              # NEW: Risk uncertainty quantification

# Synthesis Phase (Enhanced)
search/opportunities/generated/{id}        # Raw opportunities + sources
search/opportunities/scored/{id}           # Multi-dimensional scores
search/opportunities/pareto/{id}           # Pareto-optimal + confidence
search/opportunities/stakeholder/{id}      # NEW: Per-stakeholder scoring
search/opportunities/dependencies/{id}     # Dependency graph + validation

# Implementation Phase (Enhanced)
search/implementation/roadmap/{id}         # Phased roadmap + contingencies
search/implementation/tasks/{id}           # Tasks + validation gates
search/implementation/resources/{id}       # Resource allocation + alternatives
search/implementation/verification/{id}    # Verification + escape hatches
search/implementation/risk-mitigation/{id} # NEW: Risk mitigation plans

# Multi-Persona Analysis (NEW)
search/perspectives/end-users/{id}         # End user perspective
search/perspectives/technical/{id}         # Technical team perspective
search/perspectives/management/{id}        # Management perspective
search/perspectives/competitors/{id}       # Competitor perspective
search/perspectives/regulators/{id}        # Regulatory perspective
search/perspectives/conflicts/{id}         # Perspective conflicts

# Adversarial Review (NEW)
search/adversarial/critiques/{id}          # Red team critiques
search/adversarial/weaknesses/{id}         # Identified weaknesses
search/adversarial/corrections/{id}        # Applied corrections
search/adversarial/final-review/{id}       # Final adversarial assessment

# Observability (NEW)
search/observability/decisions/{id}        # Decision logs
search/observability/reasoning/{id}        # Reasoning traces
search/observability/confidence/{id}       # Confidence tracking
search/observability/errors/{id}           # Error logs
search/observability/bottlenecks/{id}      # Performance bottlenecks

# Version Control (NEW)
search/version-control/changelog           # All version changes
search/version-control/diffs/{version}     # Version diffs
search/version-control/rollback/{version}  # Rollback snapshots

# Learning & Memory
search/learning/patterns/{id}              # Learned patterns + confidence
search/learning/strategies/{id}            # Strategy performance
search/learning/failures/{id}              # Dead ends + lessons
search/learning/successes/{id}             # NEW: Success patterns
```

---

## SECTION 2: ENHANCED CLAUDE FLOW AGENT ARCHITECTURE

### 2.1 Multi-Agent Decomposition with Specialized Subagents

```typescript
// Enhanced Agent Mapping with Parallel Subagent Swarms

// DISCOVERY SWARM (Parallel Execution)
const DISCOVERY_SWARM = {
  // Primary Agents
  structural_mapper: {
    agent: 'system-architect',
    subagents: [
      'component-identifier',      // Parallel
      'hierarchy-analyzer',        // Parallel
      'interface-mapper'           // Parallel
    ],
    synthesizer: 'integration-specialist'
  },
  
  flow_analyst: {
    agent: 'code-analyzer',
    subagents: [
      'data-flow-tracer',         // Parallel
      'control-flow-tracer',      // Parallel
      'event-flow-tracer'         // Parallel
    ],
    synthesizer: 'flow-integration-specialist'
  },
  
  dependency_tracker: {
    agent: 'dependency-analyzer',
    subagents: [
      'direct-dependency-finder',  // Parallel
      'transitive-dependency-finder', // Sequential (depends on direct)
      'circular-dependency-detector'  // Parallel
    ],
    synthesizer: 'dependency-integration-specialist'
  },
  
  critical_path: {
    agent: 'performance-optimizer',
    subagents: [
      'bottleneck-identifier',     // Parallel
      'latency-analyzer',          // Parallel
      'throughput-analyzer'        // Parallel
    ],
    synthesizer: 'performance-integration-specialist'
  }
};

// ANALYSIS SWARM (Parallel Execution)
const ANALYSIS_SWARM = {
  // Multi-Dimensional Gap Analysis
  gap_hunters: {
    coordinator: 'code-reviewer',
    subagents: [
      { agent: 'quality-gap-hunter', dimension: 'quality', parallel: true },
      { agent: 'performance-gap-hunter', dimension: 'performance', parallel: true },
      { agent: 'structural-gap-hunter', dimension: 'structural', parallel: true },
      { agent: 'resource-gap-hunter', dimension: 'resource', parallel: true },
      { agent: 'capability-gap-hunter', dimension: 'capability', parallel: true },
      { agent: 'security-gap-hunter', dimension: 'security', parallel: true },
      { agent: 'ux-gap-hunter', dimension: 'user-experience', parallel: true }
    ],
    synthesizer: 'gap-integration-specialist',
    uncertainty_quantifier: 'confidence-scorer',
    validator: 'gap-validator'
  },
  
  risk_analysts: {
    coordinator: 'security-auditor',
    subagents: [
      { agent: 'fmea-analyst', focus: 'failure-modes', parallel: true },
      { agent: 'edge-case-identifier', focus: 'edge-cases', parallel: true },
      { agent: 'vulnerability-scanner', focus: 'security', parallel: true },
      { agent: 'reliability-analyzer', focus: 'reliability', parallel: true }
    ],
    synthesizer: 'risk-integration-specialist',
    uncertainty_quantifier: 'risk-probability-estimator'
  },
  
  benchmark_analysts: {
    coordinator: 'competitive-analyst',
    subagents: [
      { agent: 'industry-standard-researcher', scope: 'standards', parallel: true },
      { agent: 'competitor-analyzer', scope: 'competitors', parallel: true },
      { agent: 'best-practice-researcher', scope: 'practices', parallel: true }
    ],
    synthesizer: 'benchmark-integration-specialist',
    rag_enabled: true  // Web search for current data
  }
};

// SYNTHESIS SWARM (Parallel Opportunity Generation)
const SYNTHESIS_SWARM = {
  opportunity_generators: {
    coordinator: 'innovation-generator',
    subagents: [
      { agent: 'quick-win-generator', horizon: 'short-term', parallel: true },
      { agent: 'strategic-generator', horizon: 'medium-term', parallel: true },
      { agent: 'transformational-generator', horizon: 'long-term', parallel: true },
      { agent: 'innovation-generator', type: 'disruptive', parallel: true }
    ],
    synthesizer: 'opportunity-integration-specialist',
    multi_persona_scorer: 'stakeholder-scorer'
  },
  
  optimizers: {
    coordinator: 'optimization-engineer',
    subagents: [
      { agent: 'pareto-optimizer', method: 'multi-objective', parallel: false },
      { agent: 'constraint-optimizer', method: 'feasibility', parallel: false },
      { agent: 'portfolio-optimizer', method: 'portfolio', parallel: false }
    ],
    synthesizer: 'optimization-integration-specialist'
  }
};

// META SWARM (Orchestration & Quality)
const META_SWARM = {
  orchestrator: 'adaptive-coordinator',
  reflector: 'meta-learning-agent',
  memory: 'memory-manager',
  uncertainty_quantifier: 'confidence-analyzer',
  adversarial_reviewer: 'red-team-agent',
  perspective_simulator: 'stakeholder-simulator',
  synthesizer: 'report-generator',
  validator: 'validation-gate-keeper'
};
```

### 2.2 Enhanced Coordination with Parallel Tool Calling

```bash
# Initialize coordination with parallel execution support
npx claude-flow coordination swarm-init --topology adaptive-hierarchical

# Enable parallel tool calling
npx claude-flow memory store \
  --namespace "search/config" \
  --key "parallelization" \
  --value '{
    "enabled": true,
    "max_parallel_agents": 8,
    "parallel_groups": {
      "discovery": ["structural", "flows", "dependencies"],
      "gap-analysis": ["quality", "performance", "structural", "resource", "capability"],
      "risk-analysis": ["fmea", "edge-cases", "vulnerabilities"]
    }
  }'

# Complexity-based topology selection
# 1-3 operators: centralized       (Simple, <1 hour)
# 4-8 operators: hierarchical      (Typical, 1-4 hours)
# 9-15 operators: mesh             (Complex, 4-8 hours)
# 16+ operators: adaptive-mesh     (Very complex, >8 hours)
```

### 2.3 Universal Agent Prompt Template (Enhanced)

Every agent receives this hyper-enhanced, forward-looking prompt:

```markdown
# {Operator Name} Excellence Framework v4.0

## IDENTITY & CONTEXT
You are a specialized {domain} search operator in the Universal Search Algorithm.
**Level**: {current_level} | **XP**: {current_xp} | **Mastery**: {mastery_score}

**Agent #{N} of {M} in {Phase} Phase**
- **Previous Agents**: {agents} (results in: {namespaces})
- **Your Mission**: {operator_mission}
- **Next Agents**: {future_agents} (they need: {requirements})
- **Ultimate Goal**: {search_objective}

## ENHANCED WORKFLOW CONTEXT

### Step-Back Principles
```bash
# Retrieve guiding principles
npx claude-flow memory retrieve --key "search/meta/principles"
```
**Your analysis MUST align with**: {principles}
**Avoid these anti-patterns**: {anti_patterns}

### Self-Ask Integration
Before starting, answer these pre-generated questions relevant to your mission:
```bash
npx claude-flow memory retrieve --key "search/meta/self-ask-questions"
```
{filtered questions for this agent}

### Memory Retrieval (What You Inherit)
```bash
# Retrieve work from previous agents (in parallel)
npx claude-flow memory retrieve --key "search/{phase}/{key1}" &
npx claude-flow memory retrieve --key "search/{phase}/{key2}" &
npx claude-flow memory retrieve --key "search/{phase}/{key3}" &
wait
```

**HOT CONTEXT** (Critical - Always Consider):
{hot_context_items}

**WARM CONTEXT** (Reference as Needed):
Available at: search/context/warm/*

**COLD CONTEXT** (Deep Background):
Available at: search/context/cold/* (access only if uncertain)

## YOUR ENHANCED MISSION

### Primary Objective
{detailed_mission_description}

### Success Criteria (100/100 Achievement)
- [ ] **Completeness**: {specific_deliverable_count} items minimum
- [ ] **Quality**: {quality_threshold}% confidence per item
- [ ] **Depth**: Level {depth_level} analysis (1=surface, 5=exhaustive)
- [ ] **Attribution**: Every claim sourced
- [ ] **Uncertainty**: Quantified for all findings
- [ ] **Validation**: Self-validated before submission

### Contrastive Examples

**✅ EXCELLENT OUTPUT** (Study This):
```
{annotated_example_of_excellent_work}
// Note: This example excels because:
// 1. Specific quantification (not vague)
// 2. Clear source attribution
// 3. Confidence scores provided
// 4. Multiple perspectives considered
// 5. Actionable recommendations
```

**❌ POOR OUTPUT** (Never Do This):
```
{example_of_poor_work}
// Why this fails:
// 1. Vague generalizations
// 2. No source attribution
// 3. Overconfident without evidence
// 4. Single perspective only
// 5. Not actionable
```

## ACTIVE PROMPTING WITH UNCERTAINTY QUANTIFICATION

For EVERY finding, claim, or recommendation:

### Confidence Scoring
```
Finding: [Your finding]
Confidence: [0-100%]
Reasoning: [Why this confidence level]
Evidence: [What supports this]
Uncertainty Sources: [What could be wrong]
```

### Automatic Research Triggers
**IF confidence < 70%**: Generate follow-up research questions and execute them

Example:
```
Finding: "Component X has performance issues"
Confidence: 65%
Research Needed:
1. Search for: "Component X performance benchmarks"
2. Search for: "Common performance issues in [technology]"
3. Ask: "What is acceptable performance for [use case]?"

[Execute searches using web_search tool]
[Re-evaluate finding with new evidence]
[Update confidence score]
```

## RAG INTEGRATION (Grounded Research)

**YOU MUST** ground analysis in real evidence:

### Web Search Integration
For factual claims, recent developments, benchmarks, or best practices:
```bash
# Use web_search tool to find supporting evidence
web_search("industry standard for {topic}")
web_search("best practices {domain} {specific_area}")
web_search("recent developments {technology}")
```

### Source Attribution Protocol
EVERY factual claim must be attributed:
```
Claim: [Specific assertion]
Source: [URL or document name]
Retrieved: [Timestamp]
Relevance: [Why this source is authoritative]
Confidence boost: [How this changes confidence from X% to Y%]
```

### Document Analysis
If documents are provided:
```bash
# Analyze provided documentation
view /mnt/user-data/uploads/{filename}
# Extract relevant information
# Cross-reference with web research
```

## PARALLEL SUBAGENT DECOMPOSITION

Your task may require multiple specialized subagents:

### Decomposition Protocol
1. **Analyze** your mission
2. **Identify** 3-7 independent subtasks
3. **Spawn** specialized subagents for each
4. **Execute** all subagents IN PARALLEL
5. **Synthesize** results into coherent output

### Subagent Template
```bash
# For each independent subtask:
Task("specialized-agent-{n}", `
Sub-mission: {specific_subtask}
Context: {relevant_context}
Output format: {specific_format}
Store as: search/{namespace}/{key}
`)

# CRITICAL: Launch all subagents, then wait
# Do NOT run sequentially unless dependencies exist
```

## MULTI-PERSPECTIVE ANALYSIS

**YOU MUST** analyze from multiple stakeholder perspectives:

### Required Perspectives
For each finding, evaluate from viewpoint of:
1. **End Users**: How does this affect user experience?
2. **Technical Team**: Implementation feasibility and maintainability?
3. **Management**: Business value and ROI?
4. **Competitors**: Competitive advantage/disadvantage?
5. **Regulators**: Compliance and risk?

### Perspective Conflict Resolution
Document any conflicts:
```
Finding: [Your finding]
Perspective A (Users): [View] - Priority: High
Perspective B (Management): [View] - Priority: Low
Conflict: [Description of tension]
Recommended Resolution: [How to balance perspectives]
```

## META-PROMPTING (Self-Improvement)

**BEFORE** executing your mission, improve your own instructions:

### Self-Critique Protocol
```
Step 1: Review your mission instructions
Step 2: Identify 3-5 potential improvements:
- [ ] Improvement 1: [What could be more specific]
- [ ] Improvement 2: [What constraint is missing]
- [ ] Improvement 3: [What validation step is needed]

Step 3: Apply improvements and proceed
```

## ESCAPE HATCHES & GRACEFUL DEGRADATION

If you encounter obstacles:

### Insufficient Information
```
**MISSING INFORMATION DETECTED**
What's missing: [Specific information needed]
Impact: [How this affects analysis]
Partial analysis: [What can be determined with available info]
Confidence: [Lower score due to gaps]
Research questions: [Specific questions to fill gaps]
Recommendation: [Proceed with caveats OR pause for more info]
```

### Insurmountable Complexity
```
**COMPLEXITY THRESHOLD EXCEEDED**
Problem: [What's too complex]
Attempted approach: [What was tried]
Why it failed: [Reason for failure]
Alternative approaches:
1. [Simpler approximation] - Trade-offs: [...]
2. [Decompose further] - Requirements: [...]
3. [Escalate to human] - Decision needed: [...]
Recommended: [Best fallback option]
```

## OBSERVABILITY INSTRUMENTATION

**LOG ALL DECISIONS** in this format:

```
[{TIMESTAMP}] DECISION: {decision_made}
REASONING: {why_this_decision}
ALTERNATIVES: [{alt1}, {alt2}, {alt3}]
CHOSEN BECAUSE: {selection_reasoning}
CONFIDENCE: {0-100%}
DEPENDENCIES: [{dep1}, {dep2}]
AGENT: {your_agent_name}
```

Store in: search/observability/decisions/{decision_id}

## VALIDATION GATE

**BEFORE** storing results, validate:

### Self-Validation Checklist
- [ ] **Completeness**: All required elements present?
- [ ] **Quality**: Meets 100/100 standard?
- [ ] **Attribution**: All claims sourced?
- [ ] **Confidence**: All uncertainties quantified?
- [ ] **Perspectives**: Multiple viewpoints considered?
- [ ] **Actionability**: Clear next steps provided?
- [ ] **Future Needs**: Next agents have what they need?

### Validation Score
```
Self-assessed score: {0-100}

IF score < 100:
  - Identified gaps: [{gap1}, {gap2}, ...]
  - Remediation plan: [How to reach 100]
  - ITERATE until 100 achieved
```

## MEMORY STORAGE (Enhanced)

### Store for Future Agents
```bash
# PRIMARY OUTPUT (what next agents need most)
npx claude-flow memory store \
  --namespace "search/{phase}/{type}" \
  --key "{component_id}" \
  --value '{
    "data": {your_analysis},
    "confidence": {overall_confidence},
    "sources": [{source_list}],
    "uncertainty": {uncertainty_quantification},
    "perspectives": {stakeholder_views},
    "version": "1.0.0",
    "timestamp": "{ISO_timestamp}",
    "agent": "{your_name}"
  }'

# OBSERVABILITY DATA
npx claude-flow memory store \
  --namespace "search/observability/reasoning" \
  --key "{task_id}" \
  --value '{
    "thought_process": {your_reasoning},
    "evidence_used": [{evidence}],
    "confidence_evolution": [{initial}, {final}]
  }'

# VERSION CONTROL
npx claude-flow memory store \
  --namespace "search/version-control/changelog" \
  --key "{task_id}" \
  --value '{
    "version": "1.1.0",
    "changes": [{change_description}],
    "confidence_delta": {change_in_confidence},
    "author": "{your_name}"
  }'
```

## TOKEN BUDGET MANAGEMENT

**Your allocated token budget**: {token_budget}

### Budget Allocation
- Executive summary: {15%} of budget
- Detailed analysis: {60%} of budget
- Examples/evidence: {15%} of budget
- Recommendations: {10%} of budget

**Monitor usage**: If approaching limit, prioritize depth over breadth

## EXECUTION PROTOCOL

### Phase 1: Preparation
1. Load hot context
2. Retrieve previous work
3. Review principles & anti-patterns
4. Self-improve mission instructions

### Phase 2: Analysis
1. Decompose into parallel subagents (if applicable)
2. Execute with RAG support
3. Quantify uncertainty
4. Analyze from multiple perspectives

### Phase 3: Synthesis
1. Integrate all findings
2. Resolve perspective conflicts
3. Generate actionable recommendations
4. Document decision reasoning

### Phase 4: Validation
1. Self-validate against checklist
2. Iterate until 100/100 achieved
3. Store with full metadata
4. Log all decisions and reasoning

## XP REWARDS

### Standard Rewards (10-15 categories)
- Completeness: {0-15 XP}
- Quality: {0-15 XP}
- Depth: {0-10 XP}
- Attribution: {0-10 XP}
- Confidence quantification: {0-10 XP}
- Multi-perspective analysis: {0-10 XP}
- Source quality: {0-10 XP}
- Actionability: {0-10 XP}

### Bonus Rewards
- 🌟 Perfect 100/100: +25 XP
- 🚀 Novel insight: +15 XP
- 🔍 Deep research (5+ sources): +10 XP
- 🎯 Critical gap found: +20 XP
- 💡 Breakthrough opportunity: +20 XP
- 🛡️ Critical risk identified: +15 XP
- ⚡ Exceptional efficiency: +10 XP

**Total possible**: 200+ XP

## RADICAL HONESTY

- Truth above optics
- Confidence over certainty
- Evidence over assumption
- Multiple perspectives over single narrative
- Acknowledge unknowns explicitly
- Flag weaknesses in your own analysis
- Request help when needed

---

**NOW EXECUTE**: Begin with meta-prompting self-improvement, then proceed with mission.
```

---

## SECTION 3: PHASE 0 - ENHANCED DISCOVERY

### Phase 0.1: Multi-Agent Structural Mapping

```bash
# Launch parallel structural analysis
Task("adaptive-coordinator", `
## STRUCTURAL DISCOVERY ORCHESTRATION

**Context**: {SUBJECT_NAME} - {SUBJECT_TYPE}

### PARALLEL SUBAGENT DEPLOYMENT

You will coordinate 4 parallel structural subagents:

#### Subagent 1: Component Identifier
Agent: component-identifier
Mission: Identify ALL components/modules/services
Store as: search/discovery/structural/components

#### Subagent 2: Hierarchy Analyzer
Agent: hierarchy-analyzer  
Mission: Map organizational hierarchy/layering
Store as: search/discovery/structural/hierarchy

#### Subagent 3: Interface Mapper
Agent: interface-mapper
Mission: Document all interfaces/APIs/contracts
Store as: search/discovery/structural/interfaces

#### Subagent 4: Boundary Analyzer
Agent: boundary-analyzer
Mission: Identify system boundaries and external dependencies
Store as: search/discovery/structural/boundaries

### EXECUTION

LAUNCH ALL FOUR AGENTS IN PARALLEL using parallel tool calls.
Each agent has independent scope - no dependencies.

Then synthesize results into unified structural map.

### RAG REQUIREMENTS

If subject is a technology/product, search for:
- "architecture diagram {SUBJECT_NAME}"
- "{SUBJECT_NAME} component documentation"
- "{SUBJECT_TYPE} architecture best practices"

Include sources in all findings.

### OUTPUT FORMAT

Unified structural map with:
- Component inventory (with confidence scores)
- Hierarchy diagram (Mermaid format)
- Interface catalog (with uncertainty noted)
- Boundary definitions (with external dependencies)
- Source attributions for all claims
- Confidence score per component: 0-100%
- Identified unknowns (areas needing more research)

Store as: search/discovery/structural/unified-map
`)

# Validation gate
Task("validation-gate-keeper", `
Review: search/discovery/structural/unified-map

Validate:
- [ ] Completeness: All major components identified?
- [ ] Confidence: Avg confidence >= 85%?
- [ ] Attribution: All claims sourced?
- [ ] Clarity: Actionable for next phase?

IF validation fails: Document gaps and iterate
IF validation passes: Proceed to Phase 0.2
`)
```

### Phase 0.2: Multi-Agent Flow Analysis

```bash
Task("adaptive-coordinator", `
## FLOW ANALYSIS ORCHESTRATION

Retrieve: search/discovery/structural/unified-map

### PARALLEL FLOW SUBAGENTS

#### Subagent 1: Data Flow Tracer
Agent: data-flow-tracer
Mission: Trace all data flows between components
Include: Data transformations, storage, transmission
Store as: search/discovery/flows/data-flows

#### Subagent 2: Control Flow Tracer
Agent: control-flow-tracer
Mission: Map control flow and decision points
Include: State machines, orchestration, error handling
Store as: search/discovery/flows/control-flows

#### Subagent 3: Event Flow Tracer
Agent: event-flow-tracer
Mission: Document event-driven flows and messaging
Include: Pub/sub, webhooks, callbacks, async patterns
Store as: search/discovery/flows/event-flows

#### Subagent 4: User Journey Mapper
Agent: user-journey-mapper
Mission: Map end-to-end user journeys through system
Include: Happy paths, error paths, edge cases
Store as: search/discovery/flows/user-journeys

### UNCERTAINTY QUANTIFICATION

For each flow:
- Confidence in flow existence: 0-100%
- Confidence in flow behavior: 0-100%
- Unknowns: [List uncertain aspects]
- Research needed: [Specific questions to answer]

### WEB SEARCH INTEGRATION

Search for:
- "event-driven architecture patterns"
- "data flow best practices {DOMAIN}"
- "common pitfalls {TECHNOLOGY} flows"

### MULTI-PERSPECTIVE EVALUATION

For each critical flow, evaluate from:
- User perspective: Experience quality?
- Developer perspective: Maintainability?
- Operations perspective: Observability?
- Security perspective: Vulnerability?

Store all perspectives.

### SYNTHESIS

Integrate all 4 flow types into:
- Unified flow diagram (Mermaid)
- Critical flow paths (ranked by importance)
- Flow complexity metrics
- Identified bottlenecks (with confidence)

Store as: search/discovery/flows/unified-analysis
`)

# Validation gate with adversarial review
Task("red-team-agent", `
## ADVERSARIAL FLOW REVIEW

Retrieve: search/discovery/flows/unified-analysis

**Your mission**: Challenge the flow analysis

### CRITIQUE FOCUS
1. Missing flows: What flows were likely overlooked?
2. Overconfident claims: Which flows lack sufficient evidence?
3. Perspective gaps: Which stakeholder views are missing?
4. Unrealistic assumptions: What assumptions might be wrong?
5. Edge cases: What edge case flows weren't considered?

For each critique:
- Describe the weakness
- Estimate impact: Low/Medium/High
- Propose correction or additional research

Store as: search/adversarial/critiques/flow-analysis
`)

Task("flow-integration-specialist", `
Retrieve: 
- search/discovery/flows/unified-analysis
- search/adversarial/critiques/flow-analysis

Incorporate critique and regenerate improved flow analysis.

Mark confidence adjustments:
- Original confidence: X%
- Critiques applied: [list]
- Revised confidence: Y%

Store as: search/discovery/flows/unified-analysis (version 1.1.0)
`)
```

### Phase 0.3: Dependency Network with Validation

```bash
Task("adaptive-coordinator", `
## DEPENDENCY ANALYSIS ORCHESTRATION

Retrieve: 
- search/discovery/structural/unified-map
- search/discovery/flows/unified-analysis

### PARALLEL DEPENDENCY SUBAGENTS

#### Subagent 1: Direct Dependency Finder
Agent: direct-dependency-finder
Mission: Identify direct dependencies (A → B)
Store as: search/discovery/dependencies/direct

#### Subagent 2: Transitive Dependency Finder
Agent: transitive-dependency-finder
Mission: Calculate transitive closure (A → B → C)
Depends on: Subagent 1 completion
Store as: search/discovery/dependencies/transitive

#### Subagent 3: Circular Dependency Detector
Agent: circular-dependency-detector
Mission: Find circular dependencies and cycles
Store as: search/discovery/dependencies/circular

#### Subagent 4: External Dependency Mapper
Agent: external-dependency-mapper
Mission: Map external dependencies (libraries, services, APIs)
Include: Version info, license info, risk assessment
Store as: search/discovery/dependencies/external

### RAG INTEGRATION

For each external dependency:
web_search("{dependency_name} known issues")
web_search("{dependency_name} security vulnerabilities")
web_search("{dependency_name} alternatives")

Document findings with sources.

### EXECUTION

1. Launch Subagents 1, 3, 4 IN PARALLEL
2. Wait for completion
3. Launch Subagent 2 (depends on Subagent 1)
4. Synthesize results

### UNCERTAINTY QUANTIFICATION

For each dependency:
- Confidence in relationship: 0-100%
- Criticality: Low/Medium/High (with confidence)
- Risk if broken: 0-10 (with uncertainty range)

### OUTPUT

Unified dependency graph with:
- Complete dependency network (Mermaid graph)
- Critical dependencies (ranked)
- Circular dependencies (flagged with resolution plans)
- External dependencies (with versions and risks)
- Confidence scores per dependency

Store as: search/discovery/dependencies/unified-graph
`)

# Multi-perspective dependency review
Task("stakeholder-simulator", `
## MULTI-STAKEHOLDER DEPENDENCY REVIEW

Retrieve: search/discovery/dependencies/unified-graph

Evaluate dependencies from each perspective:

### Technical Team Perspective
- Maintainability impact?
- Technical debt implications?
- Testing complexity?

### Management Perspective
- Vendor lock-in risks?
- Cost implications?
- Strategic dependencies?

### Security Team Perspective
- Security vulnerabilities?
- Supply chain risks?
- Compliance issues?

### Operations Perspective
- Deployment complexity?
- Monitoring requirements?
- Failure modes?

For each perspective, score dependencies:
| Dependency | Technical | Management | Security | Operations | Conflicts |
|------------|-----------|------------|----------|------------|-----------|
| ...        | ...       | ...        | ...      | ...        | ...       |

Document perspective conflicts and recommended resolutions.

Store as: search/perspectives/dependencies/stakeholder-analysis
`)
```

### Phase 0.4: Critical Path Analysis with Probability

```bash
Task("performance-optimizer", `
## CRITICAL PATH ANALYSIS WITH UNCERTAINTY

Retrieve:
- search/discovery/flows/unified-analysis
- search/discovery/dependencies/unified-graph

### CRITICAL PATH IDENTIFICATION

Using dependencies and flows, identify:

1. **Performance Critical Paths**
   - Paths affecting latency
   - Confidence in impact: 0-100%
   - Expected latency: X ms (±Y ms uncertainty)

2. **Reliability Critical Paths**
   - Paths with no redundancy
   - Single points of failure
   - Failure probability: 0-100%

3. **Business Critical Paths**
   - Paths affecting core business functions
   - Revenue impact: $X (±$Y uncertainty)

4. **Security Critical Paths**
   - Paths handling sensitive data
   - Attack surface: High/Medium/Low (confidence: X%)

### WEB SEARCH FOR BENCHMARKS

For each critical path:
web_search("industry benchmark {process_type} latency")
web_search("typical failure rates {technology}")

Compare findings to benchmarks.

### PROBABILISTIC ANALYSIS

For each path:
- Best case performance: X (probability: Y%)
- Expected performance: X (probability: Y%)
- Worst case performance: X (probability: Y%)
- Confidence in estimates: 0-100%

### ALTERNATIVE PATH ANALYSIS

For each critical path:
- Are there alternative paths?
- What's the cost of switching?
- What's the feasibility?

### OUTPUT

Critical path report with:
- Ranked list of critical paths (by impact × probability)
- Mermaid diagram highlighting critical paths
- Performance estimates with uncertainty
- Alternative paths and trade-offs
- Recommendations with confidence scores

Store as: search/discovery/critical-paths/analysis
`)
```

---

## SECTION 4: PHASE 1 - ENHANCED GAP ANALYSIS

### Phase 1.1: Multi-Dimensional Gap Hunting with Uncertainty

```bash
Task("adaptive-coordinator", `
## COMPREHENSIVE GAP ANALYSIS ORCHESTRATION

Retrieve ALL discovery artifacts:
- search/discovery/structural/unified-map
- search/discovery/flows/unified-analysis  
- search/discovery/dependencies/unified-graph
- search/discovery/critical-paths/analysis

### PARALLEL GAP-HUNTING SUBAGENTS

Deploy 7 specialized gap hunters IN PARALLEL:

#### Subagent 1: Quality Gap Hunter
Agent: quality-gap-hunter
Focus: Code quality, design quality, documentation quality
Target: 30+ quality gaps
Store as: search/gaps/quality/findings

#### Subagent 2: Performance Gap Hunter
Agent: performance-gap-hunter
Focus: Latency, throughput, resource usage, scalability
Target: 20+ performance gaps
Store as: search/gaps/performance/findings

#### Subagent 3: Structural Gap Hunter
Agent: structural-gap-hunter
Focus: Architecture, modularity, coupling, cohesion
Target: 25+ structural gaps
Store as: search/gaps/structural/findings

#### Subagent 4: Resource Gap Hunter
Agent: resource-gap-hunter
Focus: Infrastructure, capacity, staffing, tooling
Target: 15+ resource gaps
Store as: search/gaps/resource/findings

#### Subagent 5: Capability Gap Hunter
Agent: capability-gap-hunter
Focus: Missing features, incomplete functionality, technical debt
Target: 30+ capability gaps
Store as: search/gaps/capability/findings

#### Subagent 6: Security Gap Hunter
Agent: security-gap-hunter
Focus: Vulnerabilities, compliance, access control, data protection
Target: 20+ security gaps
Store as: search/gaps/security/findings

#### Subagent 7: UX Gap Hunter
Agent: ux-gap-hunter
Focus: User experience, usability, accessibility, documentation
Target: 15+ UX gaps
Store as: search/gaps/ux/findings

### ENHANCED GAP FORMAT

Each gap must include:

\`\`\`
{
  "gap_id": "G001",
  "category": "quality|performance|structural|resource|capability|security|ux",
  "severity": "critical|high|medium|low",
  "severity_score": 0-10,
  "description": "Detailed gap description",
  "current_state": "What exists now",
  "desired_state": "What should exist",
  "impact": {
    "users": "Impact on users",
    "business": "Impact on business",
    "technical": "Impact on technical team",
    "operations": "Impact on operations"
  },
  "evidence": [
    {
      "type": "observed|researched|inferred",
      "description": "Supporting evidence",
      "source": "Source of evidence",
      "confidence": 0-100
    }
  ],
  "confidence": 0-100,
  "uncertainty": {
    "exists": "Confidence gap exists",
    "severity": "Confidence in severity rating",
    "impact": "Confidence in impact assessment"
  },
  "stakeholder_perspectives": {
    "end_users": { "priority": 0-10, "rationale": "..." },
    "technical_team": { "priority": 0-10, "rationale": "..." },
    "management": { "priority": 0-10, "rationale": "..." },
    "security": { "priority": 0-10, "rationale": "..." }
  },
  "research_questions": [
    "Questions to increase confidence if < 70%"
  ],
  "sources": ["Source attributions"]
}
\`\`\`

### RAG INTEGRATION FOR GAP HUNTERS

EACH gap hunter must:

1. Search for industry standards:
   web_search("{SUBJECT_TYPE} industry standards")
   web_search("{DOMAIN} best practices")

2. Search for common pitfalls:
   web_search("common problems {TECHNOLOGY}")
   web_search("{SUBJECT_TYPE} anti-patterns")

3. Search for benchmarks:
   web_search("{METRIC} industry benchmark")

4. Document sources for ALL claims

### ACTIVE PROMPTING

For each gap with confidence < 70%:
1. Generate 3-5 research questions
2. Execute web searches to answer
3. Re-evaluate gap with new evidence
4. Update confidence score

### CONTRASTIVE PROMPTING

Provide each agent with:
- ✅ Example of well-documented gap (annotated)
- ❌ Example of poorly-documented gap (annotated)
- Anti-patterns to avoid

### EXECUTION

1. Launch all 7 gap hunters IN PARALLEL
2. Each produces 15-30+ gaps in their domain
3. Wait for all completions
4. Total expected: 150+ gaps

### SUCCESS CRITERIA PER AGENT

- [ ] Minimum gap count met
- [ ] All gaps have confidence scores
- [ ] All gaps have stakeholder perspectives
- [ ] All gaps have source attributions
- [ ] Low confidence gaps have research questions
- [ ] Multi-perspective conflicts documented

Store aggregated gaps as: search/gaps/comprehensive/all-findings
`)

# Uncertainty Quantification Pass
Task("confidence-analyzer", `
## GAP CONFIDENCE ANALYSIS

Retrieve: search/gaps/comprehensive/all-findings

For EACH gap:

### Analyze Confidence Components
1. Evidence Quality: How strong is supporting evidence?
2. Source Reliability: How authoritative are sources?
3. Assumption Risk: What assumptions could be wrong?
4. Coverage: How thoroughly was area analyzed?

### Calculate Composite Confidence
\`\`\`
Overall Confidence = (
  Evidence Quality × 0.3 +
  Source Reliability × 0.3 +
  (1 - Assumption Risk) × 0.2 +
  Coverage × 0.2
) × 100
\`\`\`

### Flag Low Confidence Gaps
For gaps with confidence < 70%:
- Escalate for additional research
- Generate specific research plan
- Estimate effort to reach 85%+ confidence

### Generate Confidence Report
| Gap ID | Confidence | Evidence | Sources | Assumptions | Coverage | Action |
|--------|-----------|----------|---------|-------------|----------|--------|
| ...    | ...       | ...      | ...     | ...         | ...      | ...    |

Store as: search/gaps/confidence/analysis
`)

# Multi-Perspective Conflict Resolution
Task("stakeholder-simulator", `
## RESOLVE STAKEHOLDER CONFLICTS

Retrieve:
- search/gaps/comprehensive/all-findings
- search/perspectives/dependencies/stakeholder-analysis

### Identify Perspective Conflicts

For each gap where stakeholder priorities differ significantly:

Example:
- Gap G042: "No automated testing"
- End Users: Priority 3/10 (don't see it)
- Technical Team: Priority 9/10 (critical for quality)
- Management: Priority 5/10 (cost concern)
- Conflict level: HIGH

### Analyze Root Causes
Why do perspectives differ?
- Different value systems?
- Information asymmetry?
- Misaligned incentives?

### Propose Resolution Strategies
1. **Educate**: Help stakeholder X understand stakeholder Y's concern
2. **Compromise**: Find middle ground
3. **Sequence**: Address different priorities in phases
4. **Innovate**: Find solution satisfying multiple perspectives

### Document Resolutions
| Gap | Conflict | Root Cause | Strategy | Confidence | Notes |
|-----|----------|------------|----------|------------|-------|
| ... | ...      | ...        | ...      | ...        | ...   |

Store as: search/gaps/conflicts/resolutions
`)

# Adversarial Gap Review
Task("red-team-agent", `
## RED TEAM GAP ANALYSIS REVIEW

Retrieve: search/gaps/comprehensive/all-findings

**Your mission**: Challenge gap analysis with skeptical lens

### Critique Categories

1. **False Positives**: Identified "gaps" that aren't actually problems
   - Why it might not be a gap
   - Alternative interpretation
   - Confidence this is false positive: 0-100%

2. **Severity Inflation**: Gaps rated too severely
   - Why severity might be lower
   - Evidence of over-rating
   - Proposed adjusted severity

3. **Missing Context**: Gaps lacking important context
   - What context is missing
   - How it changes interpretation
   - Research needed

4. **Overlooked Gaps**: Obvious gaps that were missed
   - Description of missed gap
   - Why it's important
   - Estimated severity

5. **Weak Evidence**: Gaps with insufficient support
   - Why evidence is weak
   - What stronger evidence would look like
   - Confidence reduction recommended

### Critique Format
\`\`\`
{
  "gap_id": "G042",
  "critique_type": "severity_inflation",
  "critique": "Detailed explanation",
  "evidence": "Supporting evidence for critique",
  "recommended_action": "Revise|Investigate|Accept",
  "confidence_adjustment": "-15%",
  "rationale": "Why this adjustment"
}
\`\`\`

Generate 20-30 critiques across all gap categories.

Store as: search/adversarial/critiques/gap-analysis
`)

# Apply Adversarial Corrections
Task("gap-integration-specialist", `
## INTEGRATE ADVERSARIAL FEEDBACK

Retrieve:
- search/gaps/comprehensive/all-findings
- search/adversarial/critiques/gap-analysis

For each critique:
1. Evaluate merit
2. Apply corrections where valid
3. Document changes in changelog
4. Update confidence scores

### Version Control
\`\`\`
Version 1.0.0 → 1.1.0
Changes:
- G042: Severity reduced from 8 to 6 (red team critique)
- G057: Confidence reduced from 85% to 70% (weak evidence)
- G101: Added (overlooked by initial analysis)
- G134: Removed (false positive)

Overall impact:
- Gaps before: 157
- Gaps after: 158
- Average confidence: 81% → 84%
\`\`\`

Store refined gaps as: search/gaps/comprehensive/all-findings (v1.1.0)
Store changelog as: search/version-control/changelog/gap-analysis
`)
```

### Phase 1.2: Risk & Vulnerability Analysis with Probability

```bash
Task("adaptive-coordinator", `
## COMPREHENSIVE RISK ANALYSIS ORCHESTRATION

Retrieve:
- search/gaps/comprehensive/all-findings (v1.1.0)
- search/discovery/* (all discovery artifacts)

### PARALLEL RISK SUBAGENTS

#### Subagent 1: FMEA Analyst
Agent: fmea-analyst
Mission: Failure Modes and Effects Analysis
Method:
- Identify failure modes per component
- Rate: Severity (1-10), Occurrence (1-10), Detection (1-10)
- Calculate RPN = S × O × D
- Include uncertainty bounds
Store as: search/risks/fmea/analysis

#### Subagent 2: Edge Case Identifier
Agent: edge-case-identifier
Mission: Comprehensive edge case catalog
Method:
- Boundary value analysis
- Interaction edge cases
- State transition edge cases
- Probability of occurrence
Store as: search/risks/edge-cases/catalog

#### Subagent 3: Vulnerability Scanner
Agent: vulnerability-scanner
Mission: Security vulnerability assessment
Method:
- Known CVEs in dependencies
- Design vulnerabilities
- Implementation risks
- Exploit likelihood
Store as: search/risks/vulnerabilities/assessment

#### Subagent 4: Reliability Analyzer
Agent: reliability-analyzer
Mission: System reliability modeling
Method:
- Component reliability
- System reliability (series/parallel)
- MTBF/MTTR estimation
- Availability calculation
Store as: search/risks/reliability/model

### RAG INTEGRATION

Each risk agent must search:
web_search("{TECHNOLOGY} common vulnerabilities")
web_search("{COMPONENT_TYPE} failure modes")
web_search("security best practices {DOMAIN}")
web_search("{SYSTEM_TYPE} reliability data")

### ENHANCED RISK FORMAT

\`\`\`
{
  "risk_id": "R001",
  "category": "fmea|edge-case|vulnerability|reliability",
  "component": "Affected component",
  "description": "Detailed risk description",
  "failure_mode": "How it fails",
  "effects": {
    "users": "Impact on users",
    "business": "Impact on business",
    "system": "Impact on system",
    "data": "Impact on data"
  },
  "severity": {
    "score": 1-10,
    "confidence": 0-100,
    "rationale": "Why this severity"
  },
  "occurrence": {
    "probability": 0-100,
    "confidence": 0-100,
    "basis": "Historical data|Expert estimate|Model"
  },
  "detection": {
    "score": 1-10,
    "confidence": 0-100,
    "current_controls": ["Existing detection methods"]
  },
  "rpn": {
    "value": 1-1000,
    "uncertainty_range": [min, max],
    "confidence": 0-100
  },
  "mitigation": {
    "existing": ["Current mitigations"],
    "proposed": ["Proposed additional mitigations"],
    "cost_estimate": "$X (±Y%)",
    "effectiveness_estimate": "X% reduction (±Y%)"
  },
  "sources": ["Source attributions"],
  "research_questions": ["If confidence < 70%"]
}
\`\`\`

### PROBABILISTIC RISK MODELING

For each risk:
1. Best case RPN: X (probability: Y%)
2. Expected RPN: X (probability: Y%)
3. Worst case RPN: X (probability: Y%)
4. Confidence intervals: [min, max]

### EXECUTION

1. Launch all 4 risk agents IN PARALLEL
2. Each produces comprehensive risk assessment
3. Synthesize into unified risk profile

Store as: search/risks/comprehensive/unified-profile
`)

# Monte Carlo Risk Simulation
Task("risk-probability-estimator", `
## PROBABILISTIC RISK SIMULATION

Retrieve: search/risks/comprehensive/unified-profile

### Monte Carlo Simulation Setup

For system-level risk:
1. Model component risks as probability distributions
2. Model dependencies and correlations
3. Run 10,000 simulations
4. Calculate:
   - Mean system risk
   - 95% confidence interval
   - Probability of catastrophic failure
   - Most likely failure scenarios

### Risk Aggregation

\`\`\`
System Risk = f(
  Component Risks,
  Dependencies,
  Correlations,
  Mitigation Effectiveness
)
\`\`\`

### Scenario Analysis

Best case: [Description] - Probability: X%
Expected: [Description] - Probability: Y%
Worst case: [Description] - Probability: Z%

### Output

Risk simulation report with:
- Probability distributions for key risks
- System-level risk metrics
- Sensitivity analysis (which risks matter most)
- Recommended mitigation priorities
- Confidence in all estimates

Store as: search/risks/comprehensive/probabilistic-assessment
`)
```

