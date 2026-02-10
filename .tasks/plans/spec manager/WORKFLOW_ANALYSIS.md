# Workflow Analysis: Promotion Model

## Core Insight: Code IS the Spec

In PDD, the structured spec and the code are **one and the same**. The Python
skeleton files — class/function signatures with spec comments and `pass` bodies —
are simultaneously:

* The **structured spec** (spec comments describe what each function must do)
* The **code** (as implementation fills in, spec comments become implemented logic)

There is no separate "spec layer" distinct from "library code layer." When you
"implement," you are filling in the same files that ARE the spec. The spec evolves
as the code evolves.

---

## The Promotion Layers

```text
Layer 0: Raw prose (unstructured) — OPTIONAL entry point
    ↓ PROMOTION 1 (only if input is raw prose)
Layer 1: Code-as-spec (PDD skeletons — spec comments + code in same files)
    ↓ PROMOTION 2
Layer 2: Architecture (services/events/middleware assembled from pin-functions)
    ↓ PROMOTION 3
Layer 3: Clean code (production-ready, merged to main)
```

**Promotion 1 is optional.** If the input is already a structured PDD codebase
(Python files with spec comments), you start directly at Layer 1. Promotion 1 only
exists because input CAN be raw prose that needs to be transformed into PDD format.

---

## Promotion 1: Raw Prose → Code-as-Spec (Optional)

**When**: Input is freeform prose (no structure guarantees)
**Skip when**: Input is already PDD-formatted code with spec comments

**Input**: Freeform prose spec
**Output**: PDD skeletons — Python files with spec comments, organized into libraries

**Process** (current: `intake/` module, 5 steps):
1. Summarize source files (LLM — routing hints only)
2. Discover libraries from summaries (LLM)
3. Route source spans to library destinations (LLM + reimplementation test)
4. Coverage check (deterministic + LLM noise classification)
5. Assemble output by verbatim copy (deterministic)

**QA at this promotion**:

* Coverage ledger: 100% of source lines routed or classified as noise
* Library quality: overlap detection, concern isolation

* Coverage ledger: 100% of source lines routed or classified as noise
* Library quality: overlap detection, concern isolation

**Current status**: WORKING. Verified 52/52 requirements, 100% coverage.

---

## Promotion 2: Code-as-Spec → Architecture

**Input**: PDD skeletons (spec comments + `pass` stubs in algorithmic layer)
**Output**: Promoted atoms in architectural layer (services/events/middleware via pins)

This is the main work of the system. The code-as-spec files are iteratively filled
in. As implementation proceeds, under-specifications surface, decisions are made,
and atoms are promoted through compliance gates to the architectural layer.

### The Iterative Loop (per slice, with CI)

```text
FOR EACH SLICE (in parallel across library worktrees):

  1. GAP EXPLORATION
     P3 compliance → find remaining spec comments not yet implemented
     P8 planning → plan what to implement next, how to integrate

  2. IMPLEMENTATION
     Agent writes code to fill gaps (atoms/stores/shapes)
     Write small tests for the slice

  3. UNDER-SPECIFICATION CHECK
     If the agent hits something it can't resolve:
       → Planning agent checks CONSTRAINTS against potential solutions
       → If constraints cover the decision → decide, record in analysis docs
       → If constraints DON'T cover → BLOCK → human provides constraints
     See: "Planning and Under-Specification" section below

  4. ANALYZE
     P1 structure → parse what was written
     P2 decomposition → reverse-translate for intent verification

  5. PROMOTE
     P4 library → extract atoms from code
     P5 spec_build → pin + promote through compliance gates:
       1. NO_REMAINING_COMMENTS
       2. NO_STUB_FUNCTIONS
       3. ALL_TESTS_PASS
       4. CALL_GRAPH_CONNECTED
       5. STORE_MONOGAMY
     → Refinement engine: coupling/cohesion check
     → If gates FAIL → fix → retry from step 1

  6. INTEGRATE (CI on clean worktree)
     Merge grandchild → parent (dirty root)
     Extract slice → push to clean sibling
     Run ALL tests on clean
     → If tests FAIL → DownwardFlowEngine traces pins → atoms → fix
     Rebase dirty on clean

  7. VERIFY
     P6 cross-library → connections between promoted modules
     P7 projection → lineage traces back to spec
     Architectural quality gates:
       - NO_INLINED_ATOM_LOGIC (enforces demotion — see below)
       - FUNCTION_RECOMPOSITION

  8. POWER alignment check (periodic)
     Specs + implementation → detect drift/reward hacking

  9. REPEAT for next slice
```

### Termination

* All spec comments implemented (P3 → 0 gaps)
* All atoms promoted through ALL compliance gates
* All pins exercised (architectural code uses them)
* All quality gates pass (algorithmic + architectural)
* Cross-library connected (P6)
* Lineage complete (P7 → 0 orphans)
* Refinement clean (no overlap/divergence/overload)
* Clean worktree tests pass
* POWER alignment clean

---

## Continuous Integration: The Dirty/Clean Worktree Pipeline

### Each Layer Has a Dirty/Clean Pair

Every layer maintains TWO worktrees:

* **Dirty** — where active work happens (implementation, refactoring, etc.)
* **Clean** — where verified work lands after passing tests

Additionally, the active layer has **grandchild worktrees** for parallel per-slice work.

```text
L1 (Code-as-Spec):
  grandchild-slice-A   (parallel implementation)
  grandchild-slice-B   (parallel implementation)
  dirty                (accumulates from grandchildren)
  clean                (accumulates from dirty after tests pass)

L2 (Architecture):
  dirty                (accumulates from L1 clean)
  clean                (accumulates from L2 dirty after tests pass)

L3 (Clean Code):
  dirty                (accumulates from L2 clean)
  clean                (accumulates from L3 dirty after tests pass) → main
```

### Batch Promotion Between Layers

Promotion flows continuously through layers as **batches**, not as individual
items and not as a big-bang "all at once":

```text
L1 grandchild → L1 dirty → [gates] → L1 clean → [tests]
    → L2 dirty → [tests] → L2 clean
    → L3 dirty → [tests] → L3 clean → main
```

When a slice passes gates in L1 dirty and is promoted to L1 clean (tests pass),
it is **immediately promoted to L2 dirty**. No waiting. The promoted code lands
in L2 dirty and sits there until creative L2 work begins.

### Tracking Promoted vs Unpromoted Work

Use `git diff` between dirty and clean at each layer:

* `git diff L1-dirty L1-clean` = unpromoted work at L1
* `git diff L1-clean L2-dirty` = unpromoted work between layers
* **When dirty == clean (no diff), the entire layer is clean.**

This is the termination signal for a layer: when all work has flowed through
dirty → clean, there's nothing left to do at that layer.

### Promotion Queue and Batching

Multiple slices finishing at L1 form a **queue** to get into L1 clean:

1. Slice A finishes → queued to merge into L1 clean
2. Slice B finishes → queued behind A
3. **Batch N** (A + B) is promoted: L1 dirty → L1 clean → tests
4. If tests pass: batch N immediately flows to L2 dirty
5. **Batch N+1** can now merge into L1 clean
6. Repeat

You empty the queue each time the previous batch is promoted. This creates
a steady flow of verified batches moving through the layer pipeline.

### Creative Work vs CI Integration

**CI runs at all layers in parallel** — merges and tests happen continuously
at every layer as batches flow through. But **creative work only happens at
the active layer**:

* While L1 is active: agents implement code, fill gaps, resolve under-specs
* L2 and L3 only run CI (merge + test) — no architectural proposals, no
  code quality reviews, no design work
* When L1 dirty == L1 clean: L1 is done. Creative work moves to L2.
* When L2 dirty == L2 clean: L2 is done. Creative work moves to L3.

This prevents wasting tokens on work that would be invalidated by changes
at lower layers.

---

## Promotion 3: Architecture → Clean Code

**Input**: Working but messy architecture
**Output**: Clean, production-ready code, merged to main

**Process**:

1. N code quality reviewers (each enforces different standards):
   * Clarity, completeness, consistency, correctness
2. Collect findings
3. Refactor based on findings
4. If refactoring touches logic → **demotion** (see below)
5. Re-review until quality standards pass
6. Merge root worktree to main

---

## Planning and Under-Specification

Under-specification is the natural state of any spec. As agents implement code,
they WILL hit things that aren't fully specified. This triggers the planning and
approval process.

### How It Works

```text
Agent hits under-specification
    ↓
Planning agent activates:
  1. Identify potential solutions
  2. Check CONSTRAINTS against each solution
  3. Constraints cover the decision?
     YES → Make decision, record in analysis docs
     NO  → Block
    ↓
If blocked (interactive mode):
  Generate research prompt with full context
  Human receives the prompt
  Human provides CONSTRAINTS (not solutions)
    → Constraints tell the system HOW to make tradeoff decisions
    → e.g., "prioritize latency over throughput"
    → e.g., "use existing event bus, don't add new infrastructure"
  Planning agent uses new constraints to decide
  Decision recorded in analysis docs
    ↓
If blocked (auto mode):
  Built-in research team sources the decision:
    → Opus: pattern recognition, orchestration
    → GPT: synthesis, detail tracking
    → GLM: summarization, evidence gathering
    → firecrawl: web research
  Decision recorded in analysis docs
```

### Key Principles

**The human provides CONSTRAINTS, not solutions.** Constraints define the
decision space. The planning agent operates within that space. If the space
doesn't cover a decision, the system blocks and asks for more constraints.

**In interactive mode, the system can't decide on its own.** The human is the
decision-maker for tradeoffs. The system surfaces the question with full context
via a research prompt. The human can take that prompt to external tools with more
powerful reasoning capabilities (the point of generating research prompts).

**In auto mode, the research team decides.** Multiple models collaborate to
produce an answer. The quality of these decisions is what we evaluate.

### Why Planning Exists

Planning isn't just "what to implement next." It serves two critical functions:

1. **Change integration**: When a decision is made or a gap is filled, planning
   figures out WHERE the change needs to go and HOW it integrates with existing
   work. The agent that signaled the requirement needs the implementation, but the
   implementation may need to be distributed across multiple locations.

2. **Brownfield support**: The same planning mechanism works for existing codebases.
   Planning can analyze existing code, understand what exists, and figure out how
   incoming changes integrate with what's already there.

---

## Demotion: All the Way Down

Demotion doesn't stop at layer N-1. When something can't be resolved at layer N,
the system evaluates at N-1, and if it still can't be resolved, it keeps going
down until it reaches the bottom: expanding the code-as-spec (adding new spec
comments, new functions, new files to the PDD skeletons).

```text
Issue discovered at Layer 3 (clean code / quality)
    ↓ evaluate: is this a quality issue or a logic issue?
    ↓ if logic issue → demote
Layer 2 (architecture)
    ↓ evaluate: is this architectural or algorithmic?
    ↓ if algorithmic → demote
Layer 1 (code-as-spec)
    ↓ evaluate: is this implemented or under-specified?
    ↓ if under-specified → expand the spec (add spec comments, new functions)
    ↓ then implement → promote back up through ALL gates
```

### Demotion Enforcement

**`NO_INLINED_ATOM_LOGIC`** gate at the architectural layer enforces demotion.
If you try to write business logic directly in a service/event handler, the gate
fails. You MUST create it as an atom in the code-as-spec layer and promote it
through pins.

**`DownwardFlowEngine`** traces architectural test failures back through pins to
atoms. The fix happens at Layer 1 (code-as-spec), re-promotes through gates,
and the architectural layer is automatically updated (shared pin-functions).

### Demotion Examples

| At Layer | Situation | Demoted To | Action |
|----------|-----------|------------|--------|
| Architecture (L2) | Need new algorithm not in library | Code-as-spec (L1) | Add spec + impl atom → promote |
| Architecture (L2) | Under-specified requirement | Code-as-spec (L1) | Add spec → planning → implement |
| Clean code (L3) | Logic bug found in review | Code-as-spec (L1) | Fix atom → re-promote through all gates |
| Clean code (L3) | Architectural issue | Architecture (L2) | Refactor arch → if logic needed → demote to L1 |

---

## Processes That Run at EVERY Promotion

| Process | What It Does |
|---------|-------------|
| **Gap exploration** | Find what's not yet done at this layer |
| **Continuous planning** | Decide what to do next, how to integrate changes |
| **Implementation** | Fill gaps (spec writing / code writing / arch building / refactoring) |
| **Small tests** | Validate each unit of work |
| **Compliance gates** | Quality check before promoting to next layer |
| **Skeletal refinement** | Refine structure/shape at this layer |
| **Logical refinement** | Refine logic/algorithms; demote if doesn't belong here |
| **CI integration** | Extract slice → push to clean → test → rebase |
| **POWER alignment** | Detect drift and reward hacking |
| **Approvals** | Human constraints or auto-research for under-specifications |

---

## Routing: Only at the Bottom Layer

### Phase 0's Routing Algorithm

Phase 0 solves the hardest routing problem: given unstructured prose, where does
each piece belong? It uses:
1. **Summarization** as routing hints (not final output)
2. **Library discovery** from summaries
3. **Route table** mapping source spans → library destinations
4. **Coverage ledger** as termination criterion

This pattern — summarize → discover structure → route by summaries — is how
routing works.

### Why Upper Layers Don't Need Routing

**You never edit architecture or clean code directly.** They emerge from promotion.

* **Architecture** comes into existence when atoms are promoted via pins.
  The pin projection type (PASS_THROUGH, EVENT_BRIDGE, etc.) already describes
  how the atom is assembled. You don't "route" something to architecture.

* **Architectural changes** come from processes that already know the target:
  refinement engine detected a coupling issue, compliance gate failed, quality
  reviewer identified a location, or DownwardFlowEngine traced a test failure.

* **Clean code changes** come from quality reviewers who identify specific
  locations. The review already IS the routing.

**The system always knows what to edit** because changes originate from processes
(promotion, demotion, refinement, gate failure, review) that identify the target.

### Routing at the Bottom Layer (Code-as-Spec)

The only layer where routing is needed is Layer 1 — the code-as-spec. When a new
requirement, decision, or demoted algorithm needs to be added, the system needs
to figure out WHICH LIBRARY and WHICH FUNCTION it belongs in.

This uses the same pattern as Phase 0:
* **Library summaries** (from vertical slices) provide routing hints
* Each vertical slice has summary details describing what it covers
* Route the change to the right library by matching against summaries
* Within the library, route to the right function/atom

Libraries are **verticals** — a bunch of isolated concerns. Routing by vertical
slice summaries is the same problem Phase 0 already solved. Phase 0 routes prose
to libraries. Layer 1 routes changes to functions within libraries. Same pattern.

### Architecture Is Not Verticals

Architecture is a **complex graph**, not a bunch of verticals. Libraries decompose
by concern (vertical slicing). Architecture decomposes by... how things are
assembled, how they communicate, how they're deployed.

But we don't need to route TO architecture because we don't edit it directly. It
emerges from promotion. The pin-function system IS the routing from library atoms
to architectural locations.

### What Exists vs What's Needed

| Layer | Routing Mechanism | Status |
|-------|------------------|--------|
| Phase 0 (prose → libraries) | Summarize → discover → route spans | WORKING |
| Layer 1 (changes → functions) | Vertical slices with summaries | PARTIAL — slices exist but not used for routing |
| Layer 2 (atoms → architecture) | Pin projection types | WORKING — promotion IS routing |
| Layer 3 (findings → code) | Reviewer identifies location | WORKING — review IS routing |

The gap is at Layer 1: using vertical slice summaries to route incoming changes
(demoted algorithms, new requirements, decisions) to the right library and function.
The infrastructure exists (VerticalSlice with summary details) but isn't wired
into the planning/routing flow.

---

## Mapping P1-P10 to the Promotion Model

P1-P10 are TOOLS invoked within the promotion cycle, not a sequential pipeline:

| PDD Phase | Role in Promotion Cycle |
|-----------|------------------------|
| P0 extraction | Promotion 1 only (raw prose → code-as-spec) |
| P1 structure | Analyze: parse current code state |
| P2 decomposition | Analyze: reverse-translate for intent verification |
| P3 compliance | Gap exploration: find remaining spec comments / stubs |
| P4 library | Promote: extract atoms from code |
| P5 spec_build | Promote: pin + push through compliance gates (L1→L2 bridge) |
| P6 cross_library | Verify: connections between promoted modules |
| P7 projection | Verify: lineage traces back to spec |
| P8 task_planning | Plan: what to implement next, how to integrate |
| P9 implementation | Implement: should write code (currently only reports) |
| P10 continuous_qa | Assess: overall quality + strategy evolution |
| Refinement engine | Verify: coupling/cohesion check (post P4+) |

---

## What We Ran vs What Should Happen

### What We Ran

Promotion 1 completed (52/52 requirements). Then ran P1-P10 as a single pass
against empty PDD skeletons. Everything was correctly identified as gaps, but
nothing was implemented because P9 doesn't write code.

### What Should Have Happened

After Promotion 1 produced PDD skeletons:
1. Iterative per-slice loop: P3 (gaps) → P8 (plan) → P9 (implement) → small
   tests → P4 (extract) → P5 (promote through gates) → CI on clean
2. Under-specifications → planning agent → constraints → decisions
3. Compliance gates enforce quality at each slice
4. Refinement engine checks coupling/cohesion
5. Loop until all gaps closed, all atoms promoted
6. Then P6/P7 verify architectural connections and lineage
7. Quality reviewers → refactor → merge to main

---

## What Exists vs What's Missing

### Exists and Works

* Promotion 1 (Phase 0 intake) — verified 52/52
* Compliance gates (5 algorithmic + 2 architectural + advanced)
* Pin/promotion system (L1→L2 bridge)
* Refinement engine (coupling/cohesion analysis)
* Downward flow engine (demotion tracer via pins)
* Worktree management (dirty/clean/grandchild)
* Interactive workflow (ambiguity resolution)
* Research coordinator (multi-model research team)
* POWER alignment agent
* Architecture proposer agent
* Code quality reviewer agents (4x)
* Eval framework (EvalRunner + LLM judge)
* Human approval loop
* Planning module (P8)
* Gap detection (P3)
* Atom extraction (P4)

### Wrong Order / Wrong Time

* Worktree creation: after all phases → should be before implementation
* Ambiguity resolution: batch after phases → should be inline during implementation
* P0 conflated with P1-P10: Promotion 1 runs once, Promotion 2 loops
* Library quality check: never → should be after Promotion 1

### Missing

* **Implementation agent (P9)** — takes plans + gaps → writes code. The single
  biggest gap. Everything else (analysis, planning, gates, promotion, verification)
  exists. Nothing acts on the analysis.
* **Per-slice CI loop** — `run()` should loop per slice with CI integration, not
  single sequential pass
* **Small test generation** — simpler.md step 4: "write small tests to validate
  small units of work"
* **Under-specification → planning → constraints flow** — planning agent exists
  but isn't wired to block on under-specification and source constraints from
  human or research team
* **Full demotion chain** — DownwardFlowEngine handles L2→L1 via pins, but
  L3→L2→L1 chain not wired
* **Library quality validator** — spec-level overlap/isolation after Promotion 1
* **Architectural implementation agent** — builds services/events/middleware from
  promoted atoms (separate from algorithmic implementation)
