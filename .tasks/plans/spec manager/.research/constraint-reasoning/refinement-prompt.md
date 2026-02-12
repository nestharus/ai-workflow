# Refinement: Constraint Reasoning Response

This is a follow-up to your response. The same context.zip applies.
Re-read the design principles before proceeding — several violations
need correction.

---

## What's Good (keep these)

The overall structure is sound:

- **Constraint lifecycle framing** (inputs → derived understanding →
  decisions → propagation) — correct reframe from "constraint reasoning"
- **Planning Session as strategy pipeline** (A-G steps, not new modules)
  — respects existing infrastructure
- **Impact classifier** (1.4) gating proportional cost — correct
- **Intake stays shallow** (Section 4, subtype tags) — correct split
- **Non-software constraint model** (Section 5) — structured question
  packs, not solutions — correct
- **Concrete wiring fixes** (Section 6, steps 1-5) — these are real
  broken wiring that must be fixed regardless
- **Implementation ordering** (Section 7, steps 1-3 first) — correct

---

## What Violates Design Principles

### Violation 1: LibraryInteractionGraph is extraction AND big-bang

Section 2.2 proposes building a `LibraryInteractionGraph` — a
comprehensive graph of ALL library interactions (nodes, typed edges,
traffic levels, failure modes, constraint hotspots) BEFORE proposers
run.

This violates two principles simultaneously:

**Routing over extraction** (`LONG_TERM_GOALS.md`): The graph takes
information from Phase 0 charters, L1 outputs, and L2 analysis and
synthesizes a NEW derived artifact. Information is extracted from its
source and repackaged. The routing alternative: route source artifacts
directly to proposers and let them reason about interactions during
their actual task.

**Fractal scoping** (`design/constraints/05_FRACTAL_SCOPING.md`): The
graph attempts to capture all interactions comprehensively in one pass.
This is the big-bang failure mode. "A single reasoning pass over the
full space will miss interactions that scoped reasoning would catch."
The graph's scope is the entire system — the opposite of working at
the smallest self-contained scope.

### Violation 2: Architecture scoping assumes complete knowledge upfront

Section 2.3 defines ALL scopes before any proposer runs. This assumes
we know the full scope landscape before exploration. But architecture
understanding is progressive — we start coarse and refine.

Phase 0 gives us a COARSE understanding of library interactions
(routing decisions, cross-library references). That coarse understanding
gives us a COARSE architecture. Then we refine — discover more through
implementation, encounter new architectural decisions, branch when
tradeoffs emerge.

This is the same pattern the system already uses everywhere:
**summarization → routing → discovery through implementation**.

### Violation 3: Composition algorithm assumes simultaneous evaluation

Section 2.6 proposes greedy composition with backtracking across ALL
scopes simultaneously. This requires all candidates for all scopes to
exist before composition begins. That's another big-bang — evaluating
everything at once rather than composing incrementally.

---

## The Right Model for Architecture

Architecture follows the same progressive refinement pattern as
everything else in the system:

### Start coarse

Phase 0 output already contains library charters, cross-library
references, and routing decisions. This IS the coarse interaction
knowledge. No extraction needed — it already exists.

### Explore in parallel

From the coarse understanding, explore architectural approaches. Each
exploration is scoped — intra-library or per-interaction-edge. Multiple
explorations can run in parallel, each examining different tradeoff
positions.

But they don't need to see a comprehensive interaction graph. They need
the RELEVANT source artifacts routed to them: the charters of the
libraries they're scoping, the cross-references between them, the
constraints that apply.

### Discover through implementation

As L1 implementation proceeds, NEW interaction knowledge emerges —
actual imports, actual call patterns, actual data shapes. This is
discovery, not upfront analysis. When new interactions emerge that
affect architecture, they trigger architectural re-evaluation at the
relevant scope.

### Branch on new decisions

When an architectural exploration surfaces a new decision point (e.g.,
"this interaction could be sync or async, and the choice affects three
other libraries"), that's a BRANCH. Explore both options. This isn't
breadth-first search — it's branching when the problem demands it,
depth-first within each branch.

### Refine progressively

Each iteration produces a slightly less coarse understanding.
Architecture isn't designed once — it's refined through the same
promotion loop everything else uses. L2's job is to take L1's
implementation output and refine the architectural understanding,
not to produce a complete architecture from scratch.

---

## Questions to Address in Revision

### Q1: How does architectural exploration integrate with the existing promotion loop?

L2 currently runs AFTER L1 promotes. L1 output includes implementation
artifacts. L2 takes those and produces "architecture topology + wiring
intentions." How does progressive architecture refinement fit within
this existing flow?

- Does L2 run multiple iterations?
- Does architectural exploration happen WITHIN a single L2 promotion
  step, or across multiple promotion cycles?
- How do architectural branches map to the existing slice model?

### Q2: What triggers architectural branching?

When does the system recognize "this is a decision point that needs
parallel exploration"? What artifact or event triggers branching?
How is this different from the existing under-spec mechanism?

### Q3: How does coarse-to-refined architecture connect to constraint flow?

The constraint flow design (Section 3) is mostly correct. But how
does progressive architecture refinement produce constraints? A coarse
architectural understanding produces coarse constraints. As the
architecture refines, constraints refine. How does this work with the
authoritative/non-authoritative split?

### Q4: What does "architecture candidate" look like without the interaction graph?

Section 2.4's candidate output contract assumes an interaction graph
exists. Without it, what context does each proposer receive? What does
the candidate output look like when it's scoped to a single library or
a single interaction edge?

---

## Deliverables for This Revision

1. **Revised Section 2** — Architecture planning that uses progressive
   refinement instead of comprehensive upfront analysis. No interaction
   graph artifact. Coarse → refine through implementation → branch on
   new decisions.

2. **Integration with promotion loop** — How architectural exploration
   maps to existing L2 steps, iteration cycles, and slice model.

3. **Branching mechanism** — What triggers branches, how branches are
   tracked, how they relate to coordination infrastructure.

4. **Revised candidate contract** — What a proposer receives (routed
   source artifacts) and what it produces, without assuming a
   pre-built graph.

5. **Unchanged sections** — Sections 1, 3, 4, 5, 6, 7 are largely
   correct. Only revise if the architecture changes in Section 2
   affect them. Section 6.7 (architecture integration points) will
   likely need revision.
