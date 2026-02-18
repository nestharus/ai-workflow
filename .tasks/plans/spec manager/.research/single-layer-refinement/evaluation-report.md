# Proposal Evaluation: Single-Layer Iterative Refinement with Shape-Based Routing

## Summary Verdict

**ACCEPT WITH MODIFICATIONS** — The proposal is well-aligned with project intent and
design principles. It correctly retires PINs and layers, introduces minimal new
machinery (shapes + verifiers + matcher), and maintains deterministic convergence
authority. There are 2 significant alignment concerns, 3 actionability gaps, and
several minor tensions that should be addressed before or during Tier 2 refinement.

---

## Intent Alignment

### Problem Drift: NONE
The proposal directly addresses the original problem: simplify L1/L2/L3, retire PINs,
route work without extraction. No drift detected. The three-turn research cycle
(prompt → refinement → refinement2) successfully converged on the original intent.

### Mechanism Alignment: STRONG
- Shapes route, they don't extract (DP#3 compliant)
- Call graph is hint-only (matches original prompt intent)
- Deterministic verifiers as convergence authority (DP#1/10 compliant)
- Work items are external, not code markers (fixes response2's comment problem)

### Authority Alignment: STRONG
- Deterministic evidence has authority (tests, import scans, file diffs)
- LLM outputs are advisory only (Section 13.1-13.3)
- Human provides constraints, not solutions (Section 12 block-on-ambiguity)

---

## Constraint Compliance (Design Principles)

### DP#1: LLM for pattern recognition — ALIGNED
Shapes are parsed from controlled markdown format (deterministic). LLM is used only
for call graph hints and reviewer findings (advisory). No new hardcoded parsing.

### DP#2: Abstraction over implementation — ALIGNED
Shape format is abstract (markdown docs, not code types). Verifiers are abstract
(tests, not implementation checks). Contract patterns describe WHAT, not HOW.

### DP#3: Routing over extraction — ALIGNED (strongest alignment)
This is the proposal's core strength. Shapes route work to scopes. The call graph
maps within scopes. No extraction machinery is added. Existing extraction is preserved
as hint-only.

### DP#4: Code IS the spec — TENSION (minor)
The proposal introduces shapes as external documents separate from code. This creates
a mild tension with "code IS the spec" (PDD skeletons are simultaneously spec and code).
However, shapes are routing infrastructure, not a separate spec layer. They describe
WHERE code lives and HOW it connects — they don't duplicate WHAT the code does. The
tension is acceptable because shapes replace pins (which were also external to code)
with something lighter.

**Recommendation**: Accept this tension. Note that shapes are routing infrastructure,
not a spec layer. This distinction should be documented.

### DP#5: Promotion, not direct editing — INTENTIONAL CHANGE
The proposal deliberately changes the authority model: Build directly edits code based
on work items. There is no cross-layer promotion. This is the core design change, not
a violation — the entire proposal is about removing multi-layer promotion.

Phases still provide refinement structure (Build → Algorithm → Arch → Quality) with
re-triage for out-of-authority findings. This preserves the SPIRIT of "changes flow
through a structured process" even though the MECHANISM changes from promotion to
phase-bounded iteration.

**Recommendation**: Accept. Document that "promotion" in the single-layer model means
"phase iteration with authority boundaries" rather than "cross-representation movement."

### DP#6: System always knows what to edit — ALIGNED
Shapes + work items + ownership mapping tell the system exactly what to edit.
Shape_id is the primary routing handle. This is arguably better than the current
system because routing is simpler (scope-level, not function-level).

### DP#7: Pins as the bridge — INTENTIONALLY RETIRED
The proposal explicitly retires pins. This is the stated goal. Section 15 provides
the safety condition: "if you cannot write verifiers for key structural contracts,
pins were giving you a safety net you are not replacing."

**Recommendation**: Accept. The non-ship safety gate (Section 15) is the right
safeguard. Emphasize it during implementation.

### DP#8: Graph operations, not code operations — ALIGNED
Shapes describe structural relationships (dependencies, consumers, contracts).
Matching compares declared vs observed structure. No source code parsing is introduced.

### DP#9: Dynamic structures over rigid types — ALIGNED
Shape format is markdown (dynamic, flexible). No rigid type system is introduced.
Work items use dicts with typed fields but not rigid schemas.

### DP#10: LLM does work during its actual task — MOSTLY ALIGNED (see concern)
Shape matching and verifier execution are deterministic — not redundant LLM steps.
However, Architecture Refinement phase emits shape-drift findings — this could
become a "separate analysis step" if not careful. As long as Architecture Refinement
runs concurrently with verification (not as a pre-pass), this is fine.

**Concern**: The proposal doesn't specify whether phases run sequentially or can
overlap. If Build must complete before Algorithm Refinement starts, and Algorithm
must complete before Architecture, we have 4 sequential passes per cycle. This is
fine for correctness but may feel like "separate mechanical steps."

**Recommendation**: Accept as-is. The sequential phase model is simpler and avoids
interference. Document that phases are sequential BY DESIGN (authority boundaries
prevent overlap).

### DP#11: Minimal planning, constant iteration — ALIGNED
Phase cycles with explicit bounds (max 3 cycles) are the embodiment of this principle.
Each phase produces something messy; the next phase cleans it up. Bounded iteration
prevents unbounded planning.

### DP#12: Block on ambiguity — ALIGNED
Section 8.2: "if ambiguous, emit a coordination signal and block (no guessing)."
Section 9.3: stagnation detection blocks with diagnostics.
Section 13.3: LLM findings must be converted to verifiable tasks or remain advisory.

---

## Significant Alignment Concerns

### Concern 1: Shape Bootstrapping is Underspecified

**What the proposal says**: Shapes are derived from "spec decomposition outputs,
human-authored design docs, explicit decisions" (Section 5.2). LLMs may draft
shapes as proposals.

**What's missing**: For a NEW project with no existing shapes:
- Who creates the initial shapes? The user? Phase 0? A bootstrap step?
- What happens in the first Build pass with no shapes to route against?
- Are shapes required for the first run, or can the system operate without them?

**Why this matters**: Without a clear bootstrap path, implementation will stall
at "but there are no shapes yet." Agents won't know what to do.

**Recommendation**: Add a bootstrap rule: "Phase 0 produces initial shapes as part
of spec decomposition. If no shapes exist, Build operates on the full codebase
(degenerate case: one shape per library from Phase 0 output). Shapes are refined
during Architecture Refinement."

### Concern 2: Phase Order is Hardcoded

**What the proposal says**: Build → Algorithm → Architecture → Quality, always in
this order (Section 9.1).

**What might be limiting**: If Architecture issues are discovered early (e.g.,
import boundary violations from the start), they must wait until the Architecture
phase to be addressed. Meanwhile, Build may make changes that worsen the architecture.

**Why this matters**: The current system handles this via demotion (immediate re-routing).
The proposal replaces demotion with "work item escalation" but doesn't specify whether
work items can be fast-tracked to earlier phases in the NEXT cycle.

**Recommendation**: Clarify that work items from any phase are triaged by type and
queued for the appropriate phase in the NEXT cycle. This is already implied by
Section 9.2's re-triage rule but should be made explicit: "out-of-authority findings
are re-triaged and queued for the correct phase in the next cycle iteration."

---

## Actionability Assessment

### Strengths (Clear Enough to Implement)
- Shape format: Concrete example in Section 4.1 with header fields and verifier syntax
- Matching rules: 4 numbered rules in Section 6.3, deterministic vs hint boundary clear
- Work item routing: 2-step process in Section 8.2, unambiguous
- Phase bounds: Explicit defaults in Section 9.3 (3 cycles, 200 items, 50 per-phase, 2-window stagnation)
- Gate mapping: Complete keep/convert/eliminate table in Section 10.2
- Migration inventory: Concrete delete/restructure/keep/new lists in Section 12

### Gap 1: Contract Pattern Library is a Sketch

Section 7.2 shows 3 pattern templates (EVENT_FLOW, DI_BINDING, MIDDLEWARE_ORDERING)
as examples, but doesn't specify:
- How patterns are discovered (from spec? from code analysis? from human?)
- How patterns are validated (what makes a pattern correct?)
- How the library is versioned or extended
- Whether patterns are project-specific or universal

**Risk**: An agent implementing the pattern library won't know what "complete" means.

**Recommendation**: Accept the sketch as direction. During Tier 2, refine to specify:
patterns are derived from spec/algorithms (like shapes), not from code. The pattern
library is project-scoped. Validation = verifier tests exist and pass.

### Gap 2: Verifier Creation Strategy is Implicit

Verifiers are the convergence authority, but the proposal doesn't specify:
- Who writes verifiers? (Build phase? Human? Architecture Refinement?)
- What happens when a shape has no verifiers? (Is it still active?)
- How do verifiers get updated when shapes change? (Section 5.3 says "always
  accompanied by updating verifiers" but doesn't specify the mechanism)

**Risk**: Without clear verifier creation rules, the system may have shapes
with no verifiers (unverifiable) or stale verifiers (false confidence).

**Recommendation**: Clarify: "A shape without verifiers is a PROPOSAL, not an active
shape. Active shapes must have at least one verifier. Verifier creation is a Build
task — when a shape is created or updated, a work item to create/update verifiers
is automatically generated."

### Gap 3: First Build Pass Behavior

The proposal says "Build consumes work items and makes changes" (Section 9.1).
But in the first cycle, there are no work items yet — they come from refinement
phases which run AFTER Build.

**Current behavior**: L1 does discovery + implementation from spec skeletons.
**Proposal**: Doesn't specify what Build does on first pass.

**Recommendation**: Clarify: "First Build pass operates from spec inputs (like
current L1). Subsequent Build passes consume work items from prior refinement
phases. This is the same pattern as current L1→L2→L3 but within one cycle."

---

## Tradeoff Assessment

### What We're Gaining
- **Massive simplification**: Delete pin + layer + drift + demotion + projection machinery
- **Single codebase**: No cross-representation fidelity loss
- **Bounded iteration**: Explicit caps prevent infinite loops
- **Deterministic convergence**: Tests + verifiers, not LLM heuristics
- **Simpler routing**: Scope-level (not function-level) with clear ownership

### What We're Giving Up
- **Function-level routing precision**: Pins tracked per-function; shapes track per-scope.
  Intra-scope targeting is hint-based, not authoritative. This is acceptable if scopes
  are well-defined and verifiers are comprehensive.
- **Cross-layer fidelity checks**: Promotion gates ensured L1 atoms appeared in L2
  architecture. The replacement (shape verifiers) must cover this or issues will escape.
  Section 15's non-ship safety gate addresses this.
- **Pin-based drift detection**: Pin registry snapshots caught function-level drift.
  Shape drift is coarser. Fine-grained drift within a module may be missed.

### Risk Assessment
- **Worst case**: Key structural contracts can't be verifier-backed, and issues that
  pins caught now escape. Section 15 addresses this: "should not ship" if verifiers
  can't cover critical contracts.
- **Reversibility**: Medium. The migration deletes pin/layer modules. If we need to
  revert, those modules exist in git history. But re-integrating would be painful.
- **Incremental path**: Yes — Section 14.4 proposes a proof-of-feasibility milestone
  before full migration. This is the right approach.

---

## Accepted Elements

1. Single-layer with four phases (Build → Algorithm → Architecture → Quality)
2. Shapes as external routing summaries (not code markers, not pins)
3. Deterministic verifiers as convergence authority
4. Call graph as hint-only (non-authoritative)
5. Work items as external TODOs (not code comments)
6. Bounded iteration with explicit caps
7. Gate reorganization into aspect groups (Behavior/Architecture/Quality)
8. Demotion → work item escalation
9. Net simplification inventory (concrete delete/keep/new lists)
10. Non-ship safety gate (Section 15)
11. A/B evaluation plan (Section 14)

## Rejected Elements

None. The proposal doesn't contain elements that fundamentally conflict with
project intent or design principles.

## Proposed Modifications (for Tier 2 Refinement)

1. **Add bootstrap rule**: Phase 0 produces initial shapes from spec decomposition.
   First Build operates from spec inputs. Shapes without verifiers are proposals.
2. **Clarify phase ordering**: Work items from any phase are re-triaged and queued
   for the correct phase in the next cycle iteration.
3. **Specify verifier lifecycle**: Active shapes require verifiers. Verifier
   creation/update is an automatic Build work item when shapes change.
4. **Document pattern library scope**: Project-scoped, derived from spec/algorithms,
   validated by verifier test existence.
5. **Address first-Build-pass explicitly**: Same as current L1 behavior (discovery +
   implementation from spec inputs), subsequent passes consume work items.

## Open Questions for Human

1. **Shape bootstrapping**: Should Phase 0 produce initial shapes, or should shapes
   be created during the first Architecture Refinement pass?
2. **Phase ordering flexibility**: Is fixed order (Build → Algo → Arch → Quality)
   acceptable, or should phases be dynamically ordered based on work item priority?
3. **Verifier coverage threshold**: What's the minimum verifier coverage for a shape
   to be considered "active"? (1 verifier? Coverage of all contracts?)
