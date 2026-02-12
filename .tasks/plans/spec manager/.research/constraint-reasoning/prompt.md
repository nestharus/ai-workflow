# Research: Constraint Reasoning, Architectural Planning, and Decision Authority

## What I Need From You

Design how the **planner** reasons about constraints, makes architectural
decisions, and determines when to decide autonomously vs. when to surface
questions to humans.

This is the fifth research prompt. Research Prompts 1-4 designed the
planning module, QA eval architecture, scoring/multi-model comparison,
and agent coordination. All are implemented. This prompt addresses what
the planner currently lacks entirely: the ability to reason about
constraints, discover implied constraints, explore tradeoff spaces for
architectural decisions, and formulate the right questions when blocked.

**Important**: We are describing the problem as we understand it. Our
framing may not be the right frame. The design constraints and tradeoffs
in context.zip define the principles — read them first, then determine
what the actual problem is before designing solutions.

---

## The Core Problem

The planner makes design decisions at every layer (L1/L2/L3), but it
has no constraint reasoning. It can't:

- Discover that "high-frequency trading" implies latency constraints
- Recognize that choosing a library introduces legal, economic, and
  organizational constraints beyond its software API
- Explore the tradeoff space when multiple architectural approaches exist
- Formulate specific questions when blocked (it blocks, but doesn't know
  what to ask)
- Determine whether it has authority to decide or must surface to humans

The constraint infrastructure exists but is disconnected:
- Phase 0 captures surface-level constraints (verbatim text)
- `ConstraintsTool` is wired into planners but never called
- `ConstraintsStore` is never populated from Phase 0 output
- `PlanningGate` checks against an empty store
- No constraint reasoning, discovery, or flow between layers

---

## What the Planner Must Do

The planner has many jobs. These are not necessarily separate modules —
the right decomposition is part of what this research must determine.
But the planner must be able to:

### Route and translate

Translate incoming work into terms the planner can reason about. Spec
text arrives in domain language ("settlement processing", "risk
exposure limits"). The planner must understand what these mean in
product/design terms before it can plan.

### Understand the real problem

Before solving, understand what is actually being asked. The stated
problem may not be the right frame. The planner should ask:

- What is the actual problem being solved? (Not the stated problem —
  the underlying problem.)
- What dimensions of variation exist?
- What is the scope? (One function? One library? System-wide?)
- Is this the right level of abstraction?

This is Proportional Commitment applied to planning: explore the problem
space before committing to a solution space.

### Research

When information is missing, investigate. The planner already has
research tools (ResearchTool wired to ResearchCoordinator). But it needs
to know WHAT to research — which requires understanding what's missing
and what type of answer would fill the gap.

### Reason about constraints

Constraints exist at multiple levels:

**Surface constraints** (captured by intake): "All transactions must be
ACID-compliant." Verbatim spec text, already routed to workspace.

**Implied constraints**: "High-frequency trading" implies latency
requirements. "Healthcare data" implies HIPAA. Domain markers that carry
constraint implications the system should recognize and explore.

**Solution-introduced constraints**: Choosing a library, cloud provider,
or architectural pattern introduces constraints across dimensions the
system cannot fully evaluate: legal (licensing), economic (fees at
scale), organizational (team expertise), temporal (maintenance burden),
operational (deployment complexity). See `design/TRADEOFFS.md` for the
full constraint space.

**Inter-layer constraints**: L1 implementation discovers constraints that
affect L2 architecture. L2 architectural decisions create constraints
that flow back to L1. Constraints propagate forward and backward.

The planner needs to discover, refine, and reason about constraints at
all these levels. When it encounters a constraint it cannot evaluate
(non-software dimensions), it must surface the right question to humans.

### Propose and assess solutions

For decisions with multiple valid approaches (especially architectural
decisions), the planner needs to:

1. Generate multiple candidates that explore different positions in the
   tradeoff space
2. Understand what each candidate prioritizes and sacrifices
3. Evaluate candidates against known constraints
4. Choose — or surface to humans when the decision exceeds its authority

### Determine decision authority

When should the planner decide autonomously vs. surface to humans?

- Known constraints fully satisfied → decide
- Non-software dimensions unknown → ask humans (provide constraints, not solutions)
- Constraints conflict → surface the conflict
- Decision introduces dependencies with unknown constraint spaces → block
- Low-impact, easily reversible → lower threshold for autonomous decision
- High-impact, architectural, cross-cutting → higher threshold

### Employ specialized agents

The planner can delegate to specialized agents for different strategies.
Not every job requires the same approach. Research is different from
proposal generation is different from constraint analysis. The planner
orchestrates — it routes work to the right strategy.

---

## Architectural Planning

Architecture is where constraint and tradeoff reasoning is most critical.
The current system treats L2 as "architecture topology + wiring
intentions" but lacks the deeper process that architectural planning
requires.

### Architecture is NOT library decomposition

Library decomposition (Phase 0) focuses on cohesion and coupling —
grouping related concerns, separating unrelated ones. This is a simpler
problem. Libraries maximize cohesion and minimize coupling.

Architecture is about HOW components are organized, communicate, and
interact — and every architectural choice carries tradeoffs. Event-driven
vs. request-response. Monolith vs. services. Shared state vs. message
passing. Each choice opens some possibilities and closes others.

### Architecture requires tradeoff space exploration

1. **Understand the tradeoff space.** What are the relevant tradeoff
   dimensions? (Consistency vs. availability. Latency vs. throughput.
   Simplicity vs. flexibility.)

2. **Generate architectural candidates.** Each represents a different
   position in the tradeoff space. Multiple candidates needed.

3. **Each candidate knows its own tradeoffs.** What does it prioritize?
   Sacrifice? What constraints does it introduce? Satisfy?

4. **Evaluate and choose.** Compare against known constraints, priority
   ordering, and the full constraint space.

### Architectural proposer design

Multiple proposers generate variety. Each proposer:

- **Does NOT see other proposed architectures.** Prevents convergence.
- **DOES know what tradeoff positions have been taken** by others.
  ("Previous proposals prioritized consistency. Explore different
  positions.")
- **DOES get general architectural classifications** to explore avenues
  it might not consider. (Layered, hexagonal, event-driven, pipe-and-filter,
  microkernel, etc.)
- **Takes the constraint/tradeoff ecosystem as input.** Known constraints
  narrow what's viable. Known tradeoffs inform positions to explore.

### Architecture is fractal

Not a single big-bang proposal. It exists at multiple scopes:

**Intra-library**: How a single library is internally organized. Patterns,
internal communication. Self-contained — depends on library responsibilities
and constraints.

**Inter-library**: How libraries interact. Communication patterns, shared
contracts, dependency directions. Requires understanding library
interactions.

Scoping this way provides:
- Better accuracy (smaller scope = fewer errors)
- Better scoring (evaluate each scope independently)
- Better tradeoff understanding (scoped to where they matter)
- Pick-and-choose (different scopes can adopt different architectures)

### Architecture needs library interaction knowledge

For inter-library architecture, the system must understand:
- What data flows between which libraries?
- What are the dependency directions?
- Which libraries share state?
- Which libraries have temporal ordering requirements?
- Where are the high-traffic interaction points?

This exists partially in Phase 0 output and partially in L1 output.
The architectural planner needs access to both.

---

## The Research Questions

### Q1: Planner decomposition

How should the planner's jobs (routing, problem understanding, research,
constraint reasoning, proposal generation, assessment, decision authority)
be decomposed?

- Are these separate modules? Strategies within one module? Agents?
- What is the right decomposition given the principle of fractal scoping?
- How do the jobs interact? (Understanding feeds constraint reasoning.
  Constraint reasoning feeds proposal generation. Assessment feeds
  decision authority.)
- How do they integrate with existing planner infrastructure (tools,
  trace, capabilities, layer router)?
- When is each job invoked? (Proportional to decision impact.)

### Q2: Architectural planning algorithm

How should the fractal architectural planning process work?

- How are candidates generated? (One proposer per candidate? What
  prompts? What context?)
- How are tradeoff positions communicated between proposers without
  sharing full proposals?
- How are candidates evaluated and compared?
- How does scoping work? (Intra-library first, then inter-library?
  Or simultaneously?)
- How does library interaction knowledge feed into inter-library
  architecture?
- How does this connect to the existing L2 layer?

### Q3: Intake depth and constraint classification

How should intake handle the spectrum from explicit to implied constraints?

- Explicit: "All transactions must be ACID-compliant."
- Stated tradeoffs: "Prefer correctness over speed."
- Domain markers: "Healthcare data processing." (Implies HIPAA.)
- Dependency declarations: "Uses Kafka for messaging."
- Implicit: "High-frequency trading." (Implies latency.)

What is the right split between intake (broad surface capture) and the
planner (deep reasoning)? Should intake classify beyond binary
CONSTRAINTS/DETAIL?

### Q4: Constraint flow through the pipeline

How do constraints flow forward and backward?

- Phase 0 → ConstraintsStore bootstrap
- L1 implementation constraints → L2
- L2 architectural constraints → back to L1
- Architectural tradeoffs → implementation constraints
- Human constraints at any point → propagation to all affected layers
- Does this use existing demotion/coordination infrastructure?

### Q5: Non-software constraint handling

How does the system handle constraints it cannot evaluate autonomously?

- Legal, economic, organizational, temporal, operational dimensions
- The system CAN know these dimensions exist and ask about them
- When should it ask? (Every dependency decision? Only major ones?)
- How are non-software constraints represented?
- What can be reasoned about autonomously vs. what must be deferred?

### Q6: Skeleton refinement and planning integration

How does constraint/tradeoff reasoning integrate with skeleton refinement?

- Library skeletons: cohesion/coupling only — no deep constraint analysis
- Architectural skeletons: require full constraint reasoning
- Different architectural choices produce different skeletons
- How does the system track which constraints/tradeoffs each skeleton
  embodies?

---

## Constraints on the Solution

1. **LLM-only reasoning** — no deterministic constraint solvers, no
   formal logic engines. Constraints are natural language. Reasoning
   is LLM inference.

2. **Proportional cost** — constraint reasoning proportional to decision
   impact. Variable naming doesn't need constraint analysis. Architecture
   choices do.

3. **Human authority on non-software constraints** — the system surfaces
   questions; humans provide answers. The system cannot autonomously
   decide a license is acceptable or a cost is justified.

4. **Existing infrastructure** — coordination infrastructure (signals,
   work items, monitors, wake queue, wait graph) already exists.
   Constraint flow should use it, not build parallel infrastructure.

5. **Block on uncertainty** — when the planner doesn't know whether a
   constraint is satisfied, it blocks. The cost of surfacing a question
   is low; the cost of a wrong assumption is high.

6. **Information permanence** — constraints are preserved through
   processing. Reasoning about constraints must not destroy original
   constraint text.

7. **Fractal scoping** — architecture is scoped (intra-library,
   inter-library), not big-bang. Within a scope, focus on atomic units.
   Between scopes, focus on relationships. Apply the same process at
   every scale.

8. **Exploration over convergence** — architectural proposers explore
   the tradeoff space. The system needs variety in proposals, not
   convergence on one answer.

---

## What Options Have Been Considered

### For constraint reasoning

**Option A: Constraint graph with LLM reasoning** — Nodes are
constraints, edges are relationships (implies, conflicts, scoped_to).
LLM discovers edges during planning.
- Pro: Rich reasoning, conflict detection, implication chains.
- Con: Expensive, unbounded growth, hard to validate.

**Option B: Decision-triggered constraint discovery** — Every
significant decision triggers a constraint check across all dimensions.
- Pro: Proportional cost, discovers dependency-introduced constraints.
- Con: Misses constraints not tied to decisions.

**Option C: Hybrid tiered capture** — Intake captures surface. Planner
enriches with implications. Decision-triggered checks for new
constraints. Demotion for backward flow.
- Pro: Combines breadth with depth, proportional, uses existing infra.
- Con: Complex to implement.

### For architectural planning

**Option D: Single big-bang architectural proposal** — One LLM call
proposes the full system architecture.
- Pro: Simple, coherent.
- Con: Misses tradeoff space, no variety, hard to evaluate.

**Option E: Multiple independent proposers with tradeoff hints** —
Each proposer generates one candidate. Knows what tradeoff positions
others took. Doesn't see other proposals. Evaluated against constraints.
- Pro: Explores tradeoff space, supports pick-and-choose.
- Con: Needs coordination, evaluation logic.

**Option F: Fractal scoped proposals** — Intra-library and inter-library
architectures proposed separately. Multiple candidates per scope.
Composed by picking best-per-scope.
- Pro: Better accuracy, better scoring, pick-and-choose composition.
- Con: Needs library interaction knowledge, composition logic.

**Option G: Options E + F combined** — Multiple proposers per scope,
tradeoff-hint-informed, fractal. Most capable but most complex.

---

## Deliverables

1. **Planner decomposition.** How the planner's jobs are organized —
   modules, agents, strategies, or whatever decomposition the research
   determines is right. Input/output contracts, invocation triggers,
   integration points.

2. **Architectural planning algorithm.** How fractal scoped architecture
   works end-to-end: library interaction discovery → scoped candidate
   generation → tradeoff-informed proposers → evaluation → composition.

3. **Constraint flow design.** Forward and backward constraint
   propagation through the pipeline, integrated with existing
   coordination and demotion infrastructure.

4. **Intake classification expansion.** Whether and how to expand
   intake's classification beyond binary CONSTRAINTS/DETAIL to capture
   tradeoffs, domain markers, and dependency declarations.

5. **Non-software constraint model.** How the system represents, stores,
   and reasons about constraint dimensions it cannot evaluate
   autonomously.

6. **Concrete wiring.** What changes in the planner, intake,
   coordination, and promotion modules to connect everything.

7. **Implementation plan.** Concrete steps, files to create/modify,
   dependencies between changes.

---

## Context Files (in context.zip)

### Design principles (READ FIRST)

- `design/constraints/00_PROPORTIONAL_COMMITMENT.md`
- `design/constraints/01_INFORMATION_PERMANENCE.md`
- `design/constraints/02_SOURCE_AUTHORITY.md`
- `design/constraints/03_ERROR_AMPLIFICATION.md`
- `design/constraints/04_COUPLING.md`
- `design/constraints/05_FRACTAL_SCOPING.md`
- `design/TRADEOFFS.md`
- `design/patterns/CORE_PATTERNS.md`

### Authoritative source documents

- `LONG_TERM_GOALS.md` — core design principles, QA methodology
- `WORKFLOW_ANALYSIS.md` — promotion model, pipeline architecture, demotion
- `simpler.md` — PDD lifecycle, iteration philosophy
- `ALGORITHM.md` — evidence preservation, semantic framework
- `CURRENT_STATE_ASSESSMENT.md` — what exists, what works, what doesn't

### Planner (current implementation)

- `planner/api.py` — Planner + PlanningContext/Request/Result
- `planner/router.py` — LayerPlanner protocol + LayerRouter + CapabilityRouter
- `planner/layers/l1.py` — L1Planner (code-as-spec + function intentions + triage_signal)
- `planner/layers/l2.py` — L2Planner (architecture topology + wiring intentions)
- `planner/layers/l3.py` — L3Planner (quality graph + refactor intentions)
- `planner/tools/constraints_tool.py` — dead wiring (never called)
- `planner/tools/research_tool.py`
- `planner/tools/integration_tool.py`
- `planner/tools/evidence_tool.py`

### Coordination infrastructure (from Research Prompt 4)

- `orchestration/coordination/signals.py` — CoordinationSignal + types
- `orchestration/coordination/work_items.py` — WorkItemStore + 3-stage search
- `orchestration/coordination/wake_queue.py` — WakeEvent + WakeQueue
- `orchestration/coordination/wait_graph.py` — WaitEdge + WaitGraph
- `orchestration/coordination/monitors.py` — MonitorSpec + MonitorRegistry
- `orchestration/coordination/monitor_executor.py` — MonitorExecutor

### Orchestration

- `orchestration/promotion_loop.py` — 10-step state machine per slice
- `orchestration/pdd_lifecycle.py` — L1→L2→L3 layer orchestrator
- `orchestration/demotion/triage.py` — demotion triage routing
- `orchestration/under_spec/manager.py` — hard-stop blocking
- `orchestration/under_spec/planning_gate.py` — constraint gate (checks empty store)
- `orchestration/implementation/runner.py` — ImplementationRunner
- `orchestration/implementation/types.py` — RunResult, UnderSpecEvent

### Intake

- `intake/route.py` — Reimplementation Test classification
- `intake/assemble.py` — verbatim constraint copying
