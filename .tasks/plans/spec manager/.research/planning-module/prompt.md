# Research: Planning Module Architecture

## What I Need From You

Design the **Planning Module** — a new layer that sits ON TOP of the existing research system and drives auto-mode decision-making across the spec manager lifecycle. The planner is what auto mode uses. It utilizes research as one of its tools, but adds integration analysis, design generation, and layer-aware planning.

This is a significant architectural addition. The current system has research (resolves ambiguities by looking things up) but no planning (analyzing the implementation, generating designs, making strategic decisions). Planning needs to be layer-aware because each layer (L1/L2/L3) has different concerns, discovery mechanisms, and skeleton structures.

---

## Specific Questions

### Q1: What is the Planning Module's architecture?

Planning sits on top of research. It:
- Uses research as a tool to ask its own questions during planning
- Performs integration analysis against the existing implementation
- Generates designs (function plans, wiring plans, refactoring plans)
- Is the primary driver for auto mode (replaces the current auto-responder)

What are its core abstractions? What is its public API? How does it replace/wrap the current `AutoResponder` and `AutoSignalResolver`?

### Q2: How is the planner layer-aware?

Each layer (L1, L2, L3) has:
- Its own **routing mechanism for discovery** (L1 discovers code concerns, L2 discovers architecture, L3 discovers quality issues)
- Its own **layer-specific "research"** (L1 researches code-as-spec, L2 researches architecture patterns, L3 researches code quality best practices)
- Its own **skeleton planner** that produces plans appropriate for that layer

There is also:
- **Web research** as a separate research dimension (Firecrawl, Brennar Bot)
- A **general planner** that works across any layer and can delegate to layer-specific skeleton planners

What does this layered planner hierarchy look like? How do the general planner and skeleton planners interact?

### Q3: What models does the planner use, and for what?

The planner uses three models: **Opus**, **GPT 5.2 XHigh**, and **GLM 4.7**.

Each model has different strengths. The current research system already uses:
- Opus: signal extraction (deep reasoning)
- GLM: web research (tool use, search)
- GPT: synthesis (balanced judgment)

But the current approach is sequential and doesn't properly route different types of tasks to appropriate models. How should the planner route work across models? What types of planning tasks go to which model?

### Q4: How does the planner integrate with the PromotionLoop?

The 10-step PromotionLoop (COLLECT → GAP → PLAN → IMPLEMENT → UNDER_SPEC → ANALYZE → PROMOTE → INTEGRATE → VERIFY → ALIGN) currently has:
- GapExplorationStep: detects what's missing
- PlanStep: generates intentions
- ImplementStep: executes plans
- UnderSpecCheck: blocks on ambiguity

The planner should be involved in at least GAP, PLAN, and UNDER_SPEC. How does it integrate with these steps? Does it replace them, wrap them, or sit alongside?

### Q5: How does JIT tooling apply?

The article_writer project (`scripts/article_writer/`) has JIT tooling patterns that are useful for:
1. **Reviewing phases** — adapting and creating reviews based on inputs (the ReviewPack concept)
2. **Planning** — state machine phases with pause/resume and input requests
3. **General lifecycle** — dynamically adding new phases

Key patterns from article_writer:
- `Phase` enum with ordered phases (INIT → PLAN → RESEARCH → DRAFT → ANALYZE → REVIEW → REVISE → FINALIZE)
- `StateMachine` with pause/resume and `WAITING_INPUT` status
- `AgentRunner` for LLM invocation with context logging
- `extract_skeleton` for structural analysis
- `NextAction` pattern (CALL_AGENT, RUN_TOOL, USER_INPUT, COMPLETE)

How should these JIT patterns be adapted for the spec manager's planner? What can be reused vs. what needs to be purpose-built?

### Q6: How does the planner relate to Brennar Bot?

Brennar Bot (https://brennerbot.org/) is a top-tier research agent, but it "brute forces underneath" — it doesn't properly utilize a variety of models for different types of tasks.

The researcher should investigate Brennar Bot's approach and identify:
- What it does well (research quality, depth)
- Where it's wasteful (brute force, single-model approach)
- How the planner can learn from its research quality while avoiding its inefficiency
- Whether the planner should use Brennar Bot as an external research tool or build competing capabilities

### Q7: How does the planner fit into the QA eval strategy?

Per the QA methodology, during eval:
1. The pipeline runs in interactive mode
2. When ambiguities arise, the **planner** attempts to resolve them (using research, integration analysis, etc.)
3. The QA evaluator (Claude) also knows the **right answer** from ground truth
4. The evaluator compares the planner's answer to ground truth
5. This dual comparison evaluates planner quality and finds bugs

The planner IS the thing being QA'd. How should the planner be instrumented so its decisions can be inspected, compared to ground truth, and debugged?

---

## What Currently Exists

### Research System (`refinement/interactive/`)

The current research system resolves ambiguities during spec refinement:

**Signal Resolution Pipeline:**
```
Ambiguity detected
  → SignalResolver.resolve(signal)
    → AutoSignalResolver (auto mode):
        → SteeringScript.match() (pre-defined responses)
        → EvidenceStoreResearcher (local evidence search)
        → ResearchCoordinator (multi-agent web research)
    → InteractiveSignalResolver (interactive mode):
        → AutoSignalResolver (try auto first)
        → InteractiveIO (fall back to stdin prompt)
```

**ResearchCoordinator flow:**
```
0. Evidence store search (local, if available)
1. Opus → extract search signals from ambiguity
2. GLM → web search via Firecrawl
3. GPT → synthesize findings into decision
4. If confidence < 0.5 → tradeoff analysis
```

**Key files** (included in context.zip):
- `refinement/interactive/signal_resolver.py` — SignalResolver protocol + 5 implementations
- `refinement/interactive/steering/auto_responder.py` — AutoResponder (steering → evidence → research)
- `refinement/interactive/research/coordinator.py` — ResearchCoordinator (Opus → GLM → GPT)
- `refinement/interactive/workflow.py` — InteractiveWorkflow orchestrator

### PromotionLoop Steps (`orchestration/promotion_loop.py`)

The 10-step state machine per slice. Steps that interact with ambiguity/planning:

**GapExplorationStep**: Dispatches by layer:
- L1: P3 compliance gap detection
- L2: LLM architecture gap analysis (5 reviewers)
- L3: LLM quality gap analysis (5 reviewers)

**PlanStep**: Dispatches by layer:
- L1: Function implementation intentions
- L2: Wiring intentions (component_id, target_files, approach)
- L3: Refactor intentions

**ImplementStep**: Dispatches by layer:
- L1: ImplementationRunner (P9)
- L2: Architecture assembler (create entrypoints, connect pins)
- L3: Clean-code refactorer

**UnderSpecCheck**: 3-agent research pipeline:
- opus-ambiguity-signal-extractor → glm-web-researcher → chatgpt-research-synthesizer

### Layer Pipeline (`orchestration/pdd_lifecycle.py`)

```
Phase 0 → L1 (per-library) → Human Approval → L2 (per-component) → L3 (per-file) → Main
```

Each layer runs: entry refinement → per-slice PromotionLoop → exit refinement.
Between layers: transition refinement (next layer's type) as gate.

### Article Writer JIT Tooling (`scripts/article_writer/`)

State machine-based workflow with:
- `Phase` enum: INIT → PLAN → RESEARCH → DRAFT → ANALYZE → REVIEW → REVISE → FINALIZE → INVARIANT_EXTRACT → INVARIANT_CHECK → CONDENSE → APPLY_CUT → EXPORT → COMPLETE
- `StateMachine` with `Status` (RUNNING, PAUSED, WAITING_INPUT, COMPLETED, ERROR)
- `NextAction` pattern (CALL_AGENT, RUN_TOOL, USER_INPUT, COMPLETE)
- `AgentRunner` for LLM invocation with context logging
- Feedback loops: REVIEW → REVISE → REVIEW, INVARIANT_CHECK → CONDENSE → INVARIANT_CHECK
- `extract_skeleton` for structural analysis of content

### Agent Infrastructure

Agents are defined as markdown files in `.agents/agents/` and invoked via `run_agent(agent_name, prompt, workspace)`. Each agent definition specifies:
- Model to use (e.g., `opus-4`, `chatgpt-4o`, `glm`)
- System prompt
- Tools available

---

## Design Constraints

All new design must comply with the established design principles:

1. **LLM for pattern recognition** — no hardcoding, no regex, no language-specific parsing
2. **Abstraction over implementation** — any solution not in the spec needs an abstraction
3. **Routing over extraction** — route, don't extract
4. **Code IS the spec** — PDD skeletons are simultaneously spec and code
5. **Promotion, not direct editing** — changes flow through the promotion system
6. **Graph operations, not code operations** — operate on relationships, not syntax
7. **Dynamic structures over rigid types** — language-agnostic means no assumptions about constructs
8. **LLM does work during its actual task** — no redundant mechanical steps
9. **Block on ambiguity** — don't guess, surface the question

---

## Deliverables

1. **Planning Module architecture** — modules, classes, public API, data flow
2. **Layer-specific planner design** — how L1/L2/L3 skeleton planners work, how they're discovered/routed
3. **Model routing strategy** — which model for which planning task, why
4. **PromotionLoop integration** — how the planner plugs into GAP/PLAN/IMPLEMENT/UNDER_SPEC
5. **JIT tooling reuse plan** — what to adapt from article_writer, what to build new
6. **Brennar Bot analysis** — strengths, weaknesses, what to learn/avoid
7. **QA instrumentation** — how planner decisions are logged, inspectable, comparable to ground truth
8. **Migration path** — how to get from current AutoResponder/ResearchCoordinator to the new planner without breaking existing tests

---

## Context Files (in context.zip)

- `signal_resolver.py` — SignalResolver protocol + 5 implementations
- `auto_responder.py` — AutoResponder (steering → evidence → research)
- `coordinator.py` — ResearchCoordinator (Opus → GLM → GPT pipeline)
- `workflow.py` — InteractiveWorkflow orchestrator
- `promotion_loop.py` — PromotionLoop 10-step state machine (2200+ lines)
- `pdd_lifecycle.py` — PddLifecycle L1→L2→L3 orchestrator
- `article_writer/state_machine.py` — Article writer state machine (JIT patterns)
- `article_writer/agents.py` — AgentRunner with context logging
- `WORKFLOW_ANALYSIS.md` — Target state for promotion model
- `simpler.md` — Design #2 (PDD lifecycle)
- `LONG_TERM_GOALS.md` — QA methodology and design principles
