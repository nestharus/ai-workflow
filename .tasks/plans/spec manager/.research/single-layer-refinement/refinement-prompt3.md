# Research Refinement: Single-Layer Phase Model Correction

## Why This Refinement Exists

The routing model from response3 (shapes, matching, verifiers, work items, call graph as hint) is sound and should be preserved. However, the **phase model** diverged from the project's existing structure in a way that is a regression, not a simplification.

The original prompt accidentally proposed 4 phases (Build, Algorithm Refinement, Architecture Refinement, Quality Refinement) that don't match the existing L1/L2/L3 structure. The response faithfully implemented this 4-phase model. But the correct model keeps the existing three phase scales — Libraries, Architecture, Quality — each as its own cycle, operating on a single codebase.

The key realization: "Build" is not a separate phase — it's what happens WITHIN each phase. "Algorithm Refinement" is not a separate phase — algorithms are built within the Library phase. The proposal unnecessarily decomposed the existing structure into something different.

---

## What the Previous Response Got Right (KEEP ALL OF THIS)

1. **Shapes as routing infrastructure** (Sections 3-5) — external structural summaries replacing PINs. Shape format, storage, derivation, update rules. All correct.
2. **Matching** (Section 6) — compare declared vs observed structure. Ownership rules, dependency matching, contract matching, call graph as non-authoritative hint. All correct.
3. **Contract patterns** (Section 7) — EVENT_FLOW, DI_BINDING, MIDDLEWARE_ORDERING as verifiable structural relationships. Correct.
4. **Work item routing** (Section 8) — shape_id as primary routing handle, intra-scope targeting via call graph hints, ambiguity blocking. Correct.
5. **Deterministic verifiers as convergence authority** (Section 9.4) — tests + deterministic checks, not LLM heuristics. Correct.
6. **Gate reorganization into aspect groups** (Section 10) — Behavior/Architecture/Quality grouping. Correct concept but needs remapping to the three-phase model.
7. **Extraction boundary** (Section 13) — LLM outputs advisory only, deterministic evidence authoritative. Correct.
8. **Call graph as non-authoritative for routing** (Section 2) — used for intra-scope targeting. Partially correct — see Wrong #6 below for the missing classification role.
9. **Net simplification inventory** (Section 12) — concrete delete/keep/new lists. Correct direction but needs updating for the corrected phase model.

---

## What the Previous Response Got Wrong

### Wrong #1: Four phases instead of three

**Response3 proposes**: Build → Algorithm Refinement → Architecture Refinement → Quality Refinement (Section 9.1)

**Correct model**: Three phases matching the existing L1/L2/L3 scales:
- **Libraries** (L1 equivalent)
- **Architecture** (L2 equivalent)
- **Quality** (L3 equivalent)

"Build" is not a separate phase. Building/creating happens WITHIN each phase. "Algorithm Refinement" is not a separate phase. Algorithms are built and refined within the Library phase (and can be further refined within Architecture via the call graph).

### Wrong #2: Build as the only code-editing phase

**Response3 proposes** (Section 9.1-9.2): Non-Build phases only emit work items. Build is the only phase that edits code. "Build consumes work items and makes changes."

**Correct model**: Each phase has its own work cycle:
1. **Propose skeleton** at that scale (draft state)
2. **Do work** within the phase (create things, process work items)
3. **Refine skeleton** at end of phase (promote skeleton to non-draft)

Each phase creates and edits code appropriate to its scale. Libraries phase creates algorithms/shapes/stores. Architecture phase creates components. Quality phase reorganizes internals.

### Wrong #3: Fixed sequential order repeated in cycles

**Response3 proposes** (Section 9.3): Build→Algo→Arch→Quality repeated at most 3 times as a cycle.

**Correct model**: Forward-only progression through three phases. Each phase is its own cycle (like L1, L2, L3 currently are). No repeating the full sequence. No backtracking to earlier phases.

- Libraries → complete → Architecture → complete → Quality → complete
- Architecture can refine algorithms within itself (call graph enables this) without going back to Libraries
- Quality only changes internal organization (no behavior changes) so it never needs to touch Architecture
- The call graph is what makes this work — it allows later phases to handle lower-level concerns within themselves

### Wrong #4: Demotion as work item re-triage to next cycle

**Response3 proposes** (Section 11): Demotion becomes "work item escalation" where failures are re-triaged and queued for the correct phase.

**Correct model**: There is no demotion to earlier phases. Each phase handles its own concerns. If Architecture needs algorithm changes, it makes them within Architecture (the call graph shows what's connected). Quality never changes behavior, only internal organization.

There IS a draft/non-draft lifecycle for skeletons:
- Enter phase → skeleton is in draft state
- Work within phase
- Exit phase → skeleton promoted to non-draft
- Track state transitions via commits (commit where skeleton became non-draft)

### Wrong #5: Phase 0 only produces spec decomposition

**Response3 inherits** Phase 0 from the existing system as spec decomposition only.

**Correct model**: Phase 0 produces shapes + algorithms + stores. This provides the foundation for library creation in the Libraries phase.

### Wrong #6: Call graph reduced to "hint-only" without classification role

**Response3 proposes** (Section 2): The call graph is a "map/hint, never the authority." It's used only for intra-scope targeting within shapes.

**Underexplored role**: The call graph has a deeper role than just hints. The process is:

1. **Shapes/summaries** describe expected structural patterns (what SHOULD exist)
2. **Call graph** shows actual function-to-function relationships (what DOES exist)
3. **Pattern matching** classifies call graph subgraphs against shapes — "this subgraph is algorithm X", "these edges are communication path Y"
4. **After classification**, the call graph IS the algorithm — it's the ground truth of what's connected

The call graph is a hint BEFORE classification (raw edges don't mean much on their own). But after pattern matching against shapes, the classified call graph becomes the authoritative representation of the algorithm.

This is what enables single-layer operation: the call graph, once classified, tells you what algorithms exist, where their boundaries are, and how they communicate. This is the mechanism that replaces PINs — not just shapes alone, but shapes + classified call graph together.

Response3 correctly identified that the call graph is non-authoritative for ROUTING decisions (shapes handle that). But it missed that the call graph, after classification via pattern matching against shapes, becomes the authoritative representation of algorithmic structure.

---

## Redirected Questions

### RQ1: How do the three phases map to existing L1/L2/L3 infrastructure?

The existing system has substantial infrastructure for each layer (promotion loop, gates, planners, reviewers). In the single-codebase model:

- What from L1 infrastructure maps to the Libraries phase?
- What from L2 infrastructure maps to the Architecture phase?
- What from L3 infrastructure maps to the Quality phase?
- What infrastructure is shared across all three phases?
- What is the MINIMAL change to make these operate on one codebase instead of three representations?

### RQ2: How does the skeleton propose/refine cycle work within each phase?

Each phase follows: propose skeleton → work → refine skeleton.

- What does "propose skeleton" mean concretely at each scale? (Libraries: what libraries exist. Architecture: what components, how they relate/communicate/connect. Quality: what functional units, how they connect/relate.)
- What does "refine skeleton" mean at each scale?
- The skeleton is "where code can exist" — it is the structural map at that scale, not spec, not implementation.
- How does draft/non-draft state work? Enter phase = draft. Exit phase = non-draft. Track via commits.

### RQ3: How does Architecture refine algorithms without going back to Libraries?

This is enabled by the call graph. When Architecture creates components and discovers algorithm issues:

- The call graph shows which functions are connected and how
- Architecture can modify algorithm implementations in-place because there's only one codebase
- No need to "demote" to an earlier phase — just edit the code directly within the Architecture phase
- What are the boundaries? Can Architecture add NEW algorithms, or only modify existing ones?
- How does this interact with the Library skeleton (which is now non-draft)?

### RQ4: How does Quality avoid changing behavior?

Quality phase only changes internal organization — abstraction, naming, structure. It never changes behavior.

- How is "behavior change" detected/prevented? (Tests? Call graph stability? Shape verifier stability?)
- Can Quality extract helper functions, rename things, restructure files?
- What happens if a Quality change accidentally affects behavior? (Test failure → block?)
- Does the call graph help here? (Structural edges shouldn't change during Quality)

### RQ5: What does Phase 0 produce and how does it feed into Libraries?

Phase 0 produces shapes + algorithms + stores.

- How do initial shapes get created from spec decomposition?
- What are the "algorithms" produced by Phase 0? (Algorithmic descriptions? Pseudocode? Skeleton functions?)
- What are the "stores" produced by Phase 0? (Data model definitions? Persistence skeletons?)
- How do these feed into the Libraries phase skeleton proposal?

### RQ6: How do compliance gates map to three phases instead of four?

Response3's gate reorganization (Section 10) used Behavior/Architecture/Quality groups mapped to four phases. With three phases:

- Which gates run during Libraries phase?
- Which gates run during Architecture phase?
- Which gates run during Quality phase?
- Are gates still organized by aspect, or by phase?
- How do gates interact with skeleton draft/non-draft state?

### RQ7: How does call graph classification work with shapes?

The call graph's role is bigger than "hint-only for targeting." It's the mechanism that enables single-layer operation:

- How does pattern matching classify call graph subgraphs against shapes?
- What does "this subgraph is algorithm X" look like concretely?
- How are algorithm boundaries determined from the classified call graph?
- How are communication paths (structural edges) distinguished from business logic (logical edges) after classification?
- How do constraints flow from logical algorithms to communication paths? (The original prompt says: "algorithms can denote communication paths without including structure and then those communication paths can have constraints applied to them based on the logical algorithm")
- What is the relationship between classified call graph and shape verifiers?
- Is the classified call graph deterministic (and thus authoritative) or LLM-dependent (and thus advisory)?

### RQ8: What does convergence look like per phase?

Each phase is its own cycle. What determines convergence for each?

- Libraries phase converges when: ?
- Architecture phase converges when: ?
- Quality phase converges when: ?
- How do shape verifiers factor into per-phase convergence?
- Is there a global termination condition after all three phases?

---

## What Success Looks Like

1. A corrected phase model with three phases (Libraries, Architecture, Quality) that preserves the existing L1/L2/L3 semantics while operating on a single codebase.

2. Clear description of how each phase's cycle works (propose skeleton → work → refine skeleton) with concrete examples.

3. Routing model from response3 (shapes, matching, verifiers, work items) preserved and adapted to three phases.

4. Explanation of how Architecture handles algorithm concerns within itself via call graph.

5. Explanation of how Quality avoids behavior changes.

6. Gate reorganization mapped to three phases.

7. Per-phase convergence criteria.

8. Call graph classification model — how shapes + call graph + pattern matching work together to understand algorithms and enable single-layer operation.

9. Updated simplification inventory (what's deleted, kept, new) reflecting the corrected phase model.

---

## Files to Read

- **Response3** (preserve routing, correct phases): `.tasks/plans/spec manager/.research/single-layer-refinement/response3.md`
- **Current lifecycle**: `scripts/spec_manager/spec_manager/orchestration/pdd_lifecycle.py`
- **Current promotion loop**: `scripts/spec_manager/spec_manager/orchestration/promotion_loop.py`
- **Current L1/L2/L3 planners**: `scripts/spec_manager/spec_manager/planner/layers/l1.py`, `l2.py`, `l3.py`
- **Design principles**: `.tasks/plans/spec manager/LONG_TERM_GOALS.md`
- **Current state**: `.tasks/plans/spec manager/CURRENT_STATE_ASSESSMENT.md`
- **Original prompt**: `.tasks/plans/spec manager/.research/single-layer-refinement/prompt.md`
