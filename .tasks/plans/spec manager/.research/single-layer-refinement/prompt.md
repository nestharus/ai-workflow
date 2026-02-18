# Research: Single-Layer Iterative Refinement — Retiring the PIN System and Multi-Layer Promotion

## What I Need From You

Design a **single-layer iterative refinement architecture** that replaces
the current three-layer promotion pipeline (L1/L2/L3) with a single layer
that refines itself through multiple phases. The goal is to dramatically
simplify the project, reduce the risk of dropping details during
cross-layer promotion, and eliminate the PIN system entirely — while
preserving the system's correctness guarantees.

This is the seventh research prompt. Research Prompts 1-6 designed the
planning module, QA eval architecture, scoring/multi-model comparison,
agent coordination, constraint reasoning, and intent ingest. All are
implemented or have responses. This prompt explores whether the
multi-layer architecture can be collapsed without sacrificing fidelity.

**Important**: We are describing the problem as we understand it. Our
framing may not be the right frame. The design constraints and tradeoffs
in context.zip define the principles — read them first, then determine
what the actual problem is before designing solutions.

---

## The Core Problem

The current system promotes code through three layers:

```
L1 (Code-as-Spec) → L2 (Architecture) → L3 (Code Quality) → Main
```

Each layer has different step behaviors, different review packs, different
gate systems, and different skeleton types. The PIN system bridges L1 and
L2 by mapping "atoms" (algorithmic functions) to "architectural locations"
(services, events, middleware) via typed projection edges.

**This creates significant complexity:**

1. **Three sets of everything**: Each layer has its own gap exploration,
   planning, implementation, analysis, promotion gates, and verification
   steps — all with different behaviors. The PromotionLoop dispatches
   different logic per layer.

2. **PIN system overhead**: PinFunction, ImportEdge, ProjectionType,
   PinRegistryIndex, PinRegistrySnapshot, PinRegistryDrift,
   MicroAddress — all exist solely to bridge the algorithmic/architectural
   divide. Pins are registered, projected, tracked for drift, and
   traced through for demotion.

3. **Cross-layer promotion risk**: Every time work crosses a layer
   boundary, there's a risk of information loss. Atoms must be correctly
   extracted, correctly projected, correctly assembled. Each handoff is
   a potential fidelity failure point.

4. **Demotion complexity**: When a problem is found at L3, it may need
   to demote through L2 back to L1, get fixed, then re-promote through
   ALL gates at ALL layers. This round-trip is expensive and brittle.

5. **Layer-specific review packs**: L2 has 5 architecture reviewers.
   L3 has 6 quality reviewers. These are separate agent definitions
   with separate prompts, separate finding formats, and separate
   demotion routing.

**The hypothesis**: If we have a call graph extractor that can identify
algorithm edges (function-to-function relationships), and we can
distinguish structural algorithms (communication paths) from logical
algorithms (business logic), then we can operate on a single layer that
iteratively refines itself through phases — without needing to separate
"algorithmic code" from "architectural code" as distinct layers.

---

## What We Already Have

### Call Graph Extractor

`compliance/promotion/call_graph.py` — LLM-based call graph extraction.

- **Language-agnostic**: Uses `infer_adjacency_signals()` which calls an
  LLM to identify CALL relationships between function spans.
- **Evidence-based**: Every edge carries caller, callee, confidence,
  evidence (source file, rationale span, raw evidence).
- **Per-file**: Processes files individually, extracts function spans,
  infers call edges between them.

**Current capability**: Given a set of files, it produces a graph of
`(caller, callee)` edges with provenance. It understands which functions
call which other functions.

**Not yet capable of**: Cross-file call graph (edges that cross file
boundaries), identifying algorithm boundaries within a call graph,
distinguishing "communication path" edges from "business logic" edges,
mapping call graph structure to architectural patterns.

### Adjacency Signal Inference

`core/code_analysis.py` — General-purpose LLM signal inference.

- `infer_code_signals()` — cached, content-addressed LLM inference
- `infer_adjacency_signals()` — thin wrapper requesting CALL signals
- The infrastructure supports arbitrary signal types (not just CALL) —
  the `requested` parameter is a set of signal type strings.

**Key insight**: The adjacency signal infrastructure can be extended to
infer signals beyond CALL. We could request ALGORITHM_BOUNDARY,
COMMUNICATION_PATH, DATA_FLOW, STATE_MUTATION, or any other signal type
the LLM can recognize.

### Component Boundaries

The system already discovers component boundaries:

- **Phase 0**: Discovers libraries from prose (functional boundaries)
- **L1 slices**: One per library (concern-based boundaries)
- **L2 slices**: One per component (architectural boundaries from
  component manifest)

### Agent Prompt Extraction

Agent prompts (`.agents/agents/*.md`) are structured text that define
what each LLM agent does. They describe:

- Input format
- Output format
- Decision rules
- Quality criteria

Agent prompt extraction is deterministic — the prompts follow a known
format. If the extraction fails, the prompt itself is malformed (and the
agent won't run reliably either).

---

## The Key Insight

Algorithms have two aspects:

1. **Logical algorithms**: The business logic. "Settlement instructions
   must contain valid currency codes." "Risk exposure is calculated as
   sum of unsettled amounts." These are the WHAT.

2. **Structural algorithms**: The communication paths. "When a settlement
   completes, notify the risk engine via an event." "The compliance
   check runs as middleware before settlement processing." These define
   HOW components interact.

In the current system, L1 implements logical algorithms (atoms) and L2
assembles them into structural patterns (services, events, middleware)
via pins. The PIN system exists precisely to bridge this divide.

**But a call graph already encodes both aspects.** A call from
`validate_settlement()` to `check_currency_code()` is a logical edge.
A call from `settlement_event_handler()` to `notify_risk_engine()` is
a structural edge. The call graph doesn't distinguish them, but an LLM
can — because the distinction is semantic, not syntactic.

If we can:
1. Extract the full call graph (within and across files)
2. Have the LLM annotate each edge as "logical" or "structural"
3. Use structural edges to understand communication patterns
4. Use logical edges to understand algorithm boundaries
5. Apply constraints to structural edges (architecture quality)
6. Apply constraints to logical edges (algorithm correctness)

...then we don't need separate layers. We have one codebase, one call
graph, and different refinement phases that focus on different aspects
of the same graph.

---

## What a Single-Layer System Would Look Like

### Phases (NOT layers)

Instead of promoting through L1 → L2 → L3, the system iterates
through phases on a SINGLE codebase:

**Phase A: Build** — Implement from spec. Fill function bodies. Write
small tests. Block on ambiguity. This is current L1 behavior.

**Phase B: Algorithm Refinement** — Extract call graph. Identify logical
algorithm edges. Apply algorithm-level quality checks (correctness,
completeness, no remaining spec comments, no stubs). This is the
algorithm-focused subset of current L1 + L2 promotion gates.

**Phase C: Architecture Refinement** — From the SAME call graph, identify
structural edges (communication paths). Apply architecture-level quality
checks (boundary integrity, topology, event flow, middleware ordering).
This is the architecture-focused subset of current L2 gates.

**Phase D: Code Quality Refinement** — Apply quality reviewers to the
SAME codebase. Clarity, consistency, maintainability, correctness. This
is current L3 behavior.

Each phase refines the same codebase. There is no promotion between
layers. There is no PIN system. There is no atom/architecture divide.
There is just code, and different lenses (phases) through which that
code is evaluated and refined.

### What Replaces PINs

PINs exist to track which algorithmic functions are used where in the
architecture. In a single-layer system:

- The **call graph** tracks relationships between functions.
- **Structural edge annotations** identify which relationships are
  communication paths (the "architecture").
- **Algorithm boundary annotations** identify which subgraphs are
  coherent algorithms.
- When an algorithm changes, the call graph shows which structural
  edges are affected — this IS the change propagation that PINs
  currently provide.

### What Replaces Demotion

Demotion currently sends issues back to lower layers for fixing. In a
single-layer system, there is no "lower layer" — there's just the code.

- Architecture issue found → annotate the structural edge as needing
  rework → refinement phase fixes it directly.
- Logic issue found → annotate the logical edge/function → refinement
  phase fixes it directly.
- No round-trip through multiple layers. The fix happens in place.

### What This Adds as TODOs

When a refinement phase identifies an issue, it doesn't fix the code
directly (that would violate "promotion, not direct editing"). Instead:

- It adds TODO annotations to the code in the right places.
- The next iteration of the build phase picks up the TODOs.
- This maintains the routing principle — the refinement phase ROUTES
  the issue to the right location, the build phase implements the fix.

---

## The Research Questions

### Q1: Can a call graph replace PINs for change propagation?

PINs track: atom function → architectural location (with projection type).
A call graph tracks: caller → callee (with edge type).

- Is the call graph sufficient for all PIN use cases?
- PINs have projection types (PASS_THROUGH, EVENT_BRIDGE, MIDDLEWARE_WRAP,
  etc.). Can structural edge annotations carry the same information?
- PINs support drift detection via content hashes. Can call graph diff
  between iterations serve the same purpose?
- PINs support MicroAddress (precise line-range or call-site addressing).
  Can call graph edge evidence provide equivalent precision?

### Q2: How do you extract a cross-file call graph?

The current call graph extractor works per-file. But architecture is
inherently cross-file — `settlement_service.py` calls
`risk_engine.py:check_exposure()`.

- Should the LLM see multiple files simultaneously?
- Should cross-file edges be inferred from import analysis + per-file
  call graphs? (import analysis is deterministic and already exists
  via `scan_imports_from_files()`)
- How do you handle the context window limit for large projects?
- What's the confidence model for cross-file edges?

### Q3: How do you distinguish logical from structural edges?

An LLM can annotate edges, but what are the classification criteria?

- **Logical**: Implements a business rule. The edge exists because the
  algorithm requires it. Removing it changes business behavior.
- **Structural**: Implements a communication pattern. The edge exists
  because of architecture. It could be restructured without changing
  business behavior (e.g., event bus vs direct call).

- Is this distinction always clear? What about edges that are both?
- What signal types would the LLM look for? Can we extend
  `infer_adjacency_signals()` with new requested types like
  `LOGICAL_EDGE` and `STRUCTURAL_EDGE`?
- How reliable is this classification? What's the error rate?
- Can the user's spec provide hints about which patterns are
  structural vs logical?

### Q4: What happens to compliance gates?

The current system has:
- 5 L1 gates (NO_REMAINING_COMMENTS, NO_STUB_FUNCTIONS, ALL_TESTS_PASS,
  CALL_GRAPH_CONNECTED, STORE_MONOGAMY)
- 8 L2 gates (ARCH_BOUNDARY, TOPOLOGY, PIN_COVERAGE, ARCH_DRIFT,
  GOVERNANCE, etc.)
- L3 quality gates (gap analysis + diff-impact)

In a single-layer system:
- Which gates survive as-is?
- Which gates need reformulation?
- Which gates become redundant?
- How do you order the gates when there's only one layer?
- Can gates be organized by "aspect" (algorithm, architecture, quality)
  rather than by layer?

### Q5: How does iterative refinement converge?

With three layers, convergence is relatively clear: L1 converges when
all spec comments are implemented, L2 converges when all gates pass,
L3 converges when quality reviewers are satisfied.

With a single layer doing multiple refinement phases:
- How do you prevent phases from interfering? (Architecture refinement
  changes code, which triggers algorithm refinement, which changes code,
  which triggers architecture refinement...)
- How do you detect stagnation? (The same issue being found and fixed
  in alternating phases)
- Is there a natural ordering of phases that minimizes oscillation?
- What's the termination condition?

### Q6: How do agent prompts feed into the call graph?

Agent prompts define agent behavior. They are structured text with known
format. The user mentions that agent prompt extraction is deterministic.

- How do agent prompts relate to the call graph? Do they define nodes?
  Edges? Constraints on the graph?
- When an agent prompt specifies "call service X before service Y", is
  that a structural edge that should appear in the call graph?
- How do changes to agent prompts propagate through the system?
- Is agent prompt extraction truly deterministic, or are there edge cases?

### Q7: What simplification does single-layer actually achieve?

Quantify the complexity reduction:

- How many modules/files become unnecessary? (PIN system, layer-specific
  step dispatch, demotion routing, review packs per layer, etc.)
- How many concepts are eliminated? (Atoms, pins, projection types,
  layers, slices-per-layer, etc.)
- What new concepts are introduced? (Edge annotations, aspect-based
  gates, TODO routing, etc.)
- Is the net complexity lower? Or are we just moving complexity from
  layers to edge annotations?

### Q8: What are the correctness risks?

The current system has layer-specific guarantees:
- L1 guarantees all spec comments are implemented before promoting
- L2 guarantees architectural integrity before promoting
- L3 guarantees code quality before merging

With a single layer:
- How do you prevent merging code that has algorithm issues?
- How do you prevent merging code that has architecture issues?
- Is phase ordering sufficient, or do you need something stronger?
- What if a phase D (quality) fix breaks a phase B (algorithm) guarantee?

### Q9: Does the call graph handle the "routing" problem?

Currently:
- Phase 0 routes prose to libraries (vertical slices by concern)
- L1 routes changes to functions within libraries
- L2 routing happens via pins (atoms → architectural locations)
- L3 routing happens via reviewer findings (issues → specific locations)

With a single layer:
- How does routing work? The call graph tells you what calls what, but
  does it tell you WHERE to put new code?
- When a new requirement arrives, how does the system determine which
  functions/files need to change?
- Is the call graph sufficient for routing, or do you still need
  vertical slice summaries?

### Q10: How do communication path constraints work?

The user mentions: "algorithms can denote communication paths without
including structure and then those communication paths can have
constraints applied to them based on the logical algorithm."

- What does a communication path constraint look like?
- Example: "Settlement notification must reach the risk engine within
  2 hops" — how is this expressed, checked, and enforced?
- How do constraints on structural edges differ from constraints on
  logical edges?
- Can the constraint store (from Research Prompt 5) hold graph
  constraints? Or does it need extension?

### Q11: What extraction is acceptable?

The design principles say "routing over extraction" and "no
language-specific parsing." But call graph extraction IS extraction.

- Is call graph extraction acceptable because it's LLM-based (not
  language-specific)?
- Is edge annotation (logical vs structural) acceptable because it's
  semantic (not syntactic)?
- Where is the line between acceptable extraction (LLM-inferred
  structure) and unacceptable extraction (regex/AST parsing)?
- Agent prompt extraction is cited as deterministic — is deterministic
  extraction always acceptable, even when it's not LLM-based?

---

## What the Current System Gets Right

Before proposing changes, acknowledge what works:

1. **L1 eval is solid**: 38/38 functions implemented, 0 errors, 0 gaps.
   The code-as-spec model works well for algorithmic implementation.

2. **Call graph gate works**: CALL_GRAPH_CONNECTED is an L1 gate that
   already uses the call graph to verify algorithmic completeness.

3. **LLM-based review packs work**: Both L2 (5 reviewers) and L3
   (6 reviewers) produced useful findings in eval runs.

4. **Demotion routing works**: The triage system correctly classifies
   findings by type and routes them to the right layer.

5. **Stagnation detection works**: Sliding window minimum catches
   oscillating gap counts.

---

## Constraints on the Solution

1. **No language-specific parsing** — the call graph extractor uses LLM
   inference, which is correct. Any new extraction must also be LLM-based
   (except where extraction is deterministic, like agent prompt format).

2. **Routing over extraction** — the system should route issues to
   locations, not extract code from one location and move it to another.

3. **Code IS the spec** — there is still only one codebase. No separate
   "spec layer" vs "code layer."

4. **Promotion, not direct editing** — refinement phases route findings
   to locations. The build phase implements fixes. No phase directly
   edits code based on its own findings.

5. **Graph operations, not code operations** — the system operates on
   the call graph (relationships between functions), not on source code
   syntax.

6. **Block on ambiguity** — when the system can't classify an edge or
   determine where a fix belongs, it blocks and asks.

7. **Fidelity is the primary objective** — any simplification that risks
   dropping requirements, misinterpreting them, or breaking traceability
   is rejected. The three-layer system may be complex, but if it's more
   faithful, complexity is the right tradeoff.

8. **Deterministic extraction is acceptable** — where the input format
   is controlled (agent prompts, known file structures), deterministic
   extraction is acceptable because failure means the input is malformed.

9. **The single-layer approach must be AT LEAST as correct as the
   current three-layer approach.** This is not about simplification for
   its own sake — it's about simplification that preserves or improves
   correctness while reducing complexity.

10. **Existing infrastructure reuse** — the call graph extractor,
    adjacency signal inference, component discovery, constraint store,
    coordination system, and PromotionLoop state machine all exist. The
    design should compose with them, not replace them wholesale.

---

## Deliverables

1. **Feasibility assessment.** Can the three-layer system actually be
   collapsed to one layer without losing correctness guarantees? What
   are the specific risks? Is the call graph sufficient to replace PINs?
   Be honest — if this can't work, say so and explain why.

2. **Single-layer architecture.** If feasible: the phase structure,
   how phases iterate, what each phase does, how they interact with the
   PromotionLoop state machine. If partially feasible: which layers can
   be merged and which must remain separate.

3. **Call graph extension design.** How to extend the existing call
   graph to support cross-file edges, edge type annotations (logical
   vs structural), and algorithm boundary detection. Signal types for
   `infer_adjacency_signals()`.

4. **Gate reorganization.** How the existing 18+ gates map to the new
   system. Which survive, which merge, which are eliminated. How gates
   are organized by aspect rather than layer.

5. **Routing mechanism.** How the system determines where to put new
   code and where to fix issues without PINs. How the call graph
   replaces the PIN-based change propagation.

6. **Convergence strategy.** How iterative refinement across multiple
   phases converges. Ordering, interference prevention, stagnation
   detection, termination conditions.

7. **Communication path constraints.** How structural edges carry
   constraints. How constraints are expressed, checked, and enforced.
   How the constraint store handles graph-level constraints.

8. **Complexity comparison.** Concrete inventory of what's eliminated
   vs what's introduced. Module count, concept count, code path count.
   Net simplification (or not).

9. **Migration path.** If the design is feasible, how to get from
   the current three-layer system to the single-layer system
   incrementally. Which pieces can be changed independently.

10. **Agent prompt integration.** How agent prompts feed into the
    call graph and constraint system. Extraction approach, update
    propagation, failure handling.

---

## Context Files (in context.zip)

### Design principles (READ FIRST)

- `design/constraints/00_PROPORTIONAL_COMMITMENT.md`
- `design/constraints/01_INFORMATION_PERMANENCE.md`
- `design/constraints/02_SOURCE_AUTHORITY.md`
- `design/constraints/03_ERROR_AMPLIFICATION.md`
- `design/constraints/04_COUPLING.md`
- `design/constraints/05_FRACTAL_SCOPING.md`
- `design/constraints/06_STRUCTURED_ERROR_CONTRACTS.md`
- `design/constraints/07_EXPLICIT_SERIALIZATION_CONTRACTS.md`
- `design/constraints/08_STRUCTURED_DIAGNOSTICS.md`
- `design/constraints/10_CANONICAL_IDENTITY_SCHEMES.md`
- `design/constraints/11_PATH_CANONICALIZATION.md`
- `design/TRADEOFFS.md`
- `design/patterns/CORE_PATTERNS.md`

### Current implementation (layer system)

- `orchestration/pdd_lifecycle.py` — L1→L2→L3 orchestrator,
  layer-aware dispatch, transitions, refinement
- `orchestration/promotion_loop.py` — 10-step state machine,
  layer-specific step behaviors, PromotionLoop
- `orchestration/implementation/runner.py` — ImplementationRunner
- `orchestration/implementation/types.py` — RunResult, PinProposal
- `planner/api.py` — Planner, PlanningContext/Request/Result
- `planner/router.py` — LayerPlanner protocol, LayerRouter
- `planner/layers/l1.py` — L1Planner

### PIN system

- `schemas/pin_functions.py` — PinFunction, ImportEdge, ProjectionType
- `core/pin_registry.py` — PinRegistryIndex, Snapshot, Drift
- `branches/pins.py` — PinRegistry, DriftReport

### Call graph and adjacency

- `compliance/promotion/call_graph.py` — CallGraphEdge, build_call_graph()
- `core/code_analysis.py` — infer_adjacency_signals(),
  infer_code_signals(), analyze_source()

### Demotion system

- `demotion/triage.py` — DemotionTicket routing (category/gate/source)
- `demotion/router.py` — DemotionRouter
- `downward_flow/engine.py` — DownwardFlowEngine (pin tracing)

### Review packs

- `compliance/promotion/algorithmic_gates.py` — L1 gates (5 algorithmic)
- `compliance/promotion/orchestrator.py` — gate orchestration
- `compliance/promotion/config.py` — gate configuration
- `compliance/promotion/result.py` — gate result types
- L2 review pack: 5 architecture reviewer agents
- L3 review pack: 6 quality reviewer agents

### Coordination and constraints

- `orchestration/coordination/signals.py` — CoordinationSignal
- `orchestration/coordination/monitors.py` — MonitorSpec
- `orchestration/under_spec/manager.py` — UnderSpecManager, ConstraintsStore
- `planner/constraints/store.py` — Constraint, ConstraintsStore

### Intent agent

- `orchestration/intent_agent/` — IntentAgentOrchestrator, question
  queue, quality gate, taxonomy, signals, skeleton
