# Research: Remaining Gaps for Full Pipeline QA Readiness

## What I Need From You

I need concrete, implementable designs for the 6 remaining gaps that prevent
the spec_manager pipeline from being QA-ready end-to-end. These gaps were
identified during a systematic audit of `WORKFLOW_ANALYSIS.md` against the
actual codebase.

The system already has:
- Per-slice PromotionLoop (10-step state machine)
- EvidenceBundle per-slice-per-iteration
- DemotionTicket + DemotionManager (single-layer L1)
- Under-specification blocking infrastructure
- SourceAnalysisCache
- Evidence-based gate consumption (AnalyzedFile pipeline)
- All compliance gates (5 algorithmic + 4 architectural)
- Working Phase 0 intake (52/52 requirements verified)
- Working Phase 9 implementation in legacy path (LLM writes function bodies)
- Pin/edge creation exclusively from LLM proposals (Design Audit Item 3)

What's missing are the connective tissues that make the loop actually
function end-to-end on real code.

---

## The 6 Remaining Gaps

### Gap 1: Wire ImplementStep to Real Implementation

**Current state:**
- `promotion_loop.py` `ImplementStep.run()` is a STUB — returns empty
  `ImplementationRef(applied_edits=[], pin_proposals=[], ...)`
- `pdd_orchestrator.py` `_run_implementation()` has a REAL P9 that:
  1. Analyzes project for gaps via `analyze_project()`
  2. For each unresolved function, calls LLM agent `pdd-function-implementor`
  3. Agent returns JSON with `body`, `imports_needed`, `gaps`, `notes`
  4. Applies function body to file in-place
  5. Re-analyzes to verify gaps resolved

**Problem:**
The real P9 doesn't produce what the PromotionLoop expects:
- No `pin_proposals` — the LLM should propose pins during implementation
  (Principle 8: LLM does work during its actual task)
- No `edge_proposals` — the LLM should propose edges (import relationships)
- No `under_spec_events` — the LLM should signal when it hits ambiguity
- No `tests_added` — no small tests generated (see Gap 4)

The agent prompt (`pdd-function-implementor`) only asks for `body`,
`imports_needed`, `gaps`, and `notes`. It needs to also produce pin/edge
proposals and under-spec signals.

**Questions:**
1. How should `ImplementStep` adapt the legacy `_run_implementation()` logic
   for per-slice execution? The legacy version operates on the entire project;
   the loop version operates on one slice (one library worktree).
2. What should the `pdd-function-implementor` agent output schema look like
   to include pin proposals, edge proposals, and under-spec events alongside
   the function body?
3. How do pin/edge proposals from implementation feed into the PROMOTE step?
   Currently `pin_functions.orchestrator.scan(mode="both", edge_proposals=...)`
   accepts proposals. Does ImplementStep just collect proposals and pass them
   through the bundle?
4. Should implementation operate file-by-file or function-by-function within
   a slice? The legacy version does function-by-function within each file.
   Is this the right granularity for the loop?

### Gap 2: Planning Integrates with Constraints

**Current state:**
- `UnderSpecManager` exists with `ConstraintsStore` — can check whether
  existing constraints cover a decision
- `PlanStep` in the PromotionLoop calls `run_planning_v2_phase()` but does
  NOT consult constraints before producing plans
- Planning produces insertion plans from gap-derived intentions without
  checking if any intention involves an under-specified area

**Problem:**
The planning step should:
1. Check each intention against the constraints store
2. If constraints cover the decision → include the decision in the plan
3. If constraints DON'T cover → generate an under-spec event instead of
   a plan, which the subsequent UNDER_SPEC_CHECK step will handle

This prevents the implementation agent from hitting ambiguity it could have
been warned about during planning.

**Questions:**
1. Should PlanStep produce under_spec_events directly? Or should it mark
   intentions as "under-specified" and let ImplementStep surface them?
2. How should the planning agent prompt be modified to check constraints?
   Should constraints be passed as context to the LLM planning agent, or
   should constraint checking be a deterministic pre-filter?
3. What's the interface between PlanStep and the ConstraintsStore? Does
   PlanStep read constraints from the bundle, or directly from the store?

### Gap 3: Library Quality Validator (Post-Phase 0)

**Current state:**
- Phase 0 produces libraries (library definitions + routed content)
- No quality check runs on the libraries before Phases 1-10 begin
- The refinement engine (`refinement_engine/detector.py`) does coupling/
  cohesion analysis but operates on promoted atoms, not on library-level
  specs

**Problem:**
After Phase 0 routes prose into libraries, and before the iterative loop
begins, the system should validate library quality:
- **Overlap detection**: Do any two libraries cover the same concern? This
  means the routing was imprecise and code will end up in the wrong place.
- **Concern isolation**: Does each library have a single, coherent purpose?
  A library that mixes settlement processing with audit notifications is
  poorly scoped.
- **Completeness**: Were all source requirements routed? (This is already
  checked by Phase 0's coverage ledger, but should be verified post-assembly.)
- **Dependency minimality**: Are cross-library dependencies minimal? Heavy
  cross-cutting suggests wrong library boundaries.

**Context — what "library" means here:**
Libraries are vertical slices of the spec. Each library is a collection of
Python skeleton files with spec comments. They are NOT code libraries in
the traditional sense — they are spec-level groupings that will become
independent implementation targets.

Phase 0 output structure:
```
libraries/
  LIB-01/
    analysis.md      # Library scope description
    constraints.md   # Library-specific constraints
    details/
      section_N.md   # Routed source content
  LIB-02/
    ...
```

**Questions:**
1. Should library quality validation be LLM-based (judge the library
   descriptions for overlap/isolation) or deterministic (check routing
   metadata for duplicate spans)?
2. What metrics define "quality"? Propose a concrete scoring rubric.
3. Should this be a gate (pass/fail with threshold) or advisory (report
   issues, human decides whether to re-route)?
4. If quality fails, what's the remediation? Re-run Phase 0 with adjusted
   library definitions? Manually split/merge libraries? Feed issues back
   to the library discovery agent?
5. Where does this validator live in the codebase? New module? Extension
   of refinement engine? Part of Phase 0's pipeline?

### Gap 4: Small Test Generation

**Current state:**
- `_run_implementation()` has a TODO: "Add small test generation step here.
  simpler.md step 4: write small tests to validate small units of work."
- The `ALL_TESTS_PASS` compliance gate exists but there are no generated
  tests to run
- No test generation module or agent exists

**Problem:**
Per `simpler.md`, after implementation writes code for a slice, small tests
should be generated to validate the implemented functions. These tests:
- Validate that implemented functions behave according to spec comments
- Are run by the ALL_TESTS_PASS gate during promotion
- Provide regression safety for the iterative loop (subsequent iterations
  shouldn't break earlier implementations)

**Context:**
The system is language-agnostic. Test generation must work for any language
the LLM can handle, not just Python. The LLM that implements a function
already understands the spec comments and the function's purpose — per
Principle 8, it should produce tests as part of its work, not as a separate
mechanical step.

**Questions:**
1. Should tests be generated by the same `pdd-function-implementor` agent
   that implements functions? Or by a separate `pdd-test-generator` agent?
   (Principle 8 suggests the same agent, but test quality might benefit
   from specialization.)
2. What kind of tests? Unit tests per function? Integration tests per
   slice? Property-based tests?
3. Where do generated tests live? In the slice worktree alongside the
   implementation? In a separate test directory?
4. How do generated tests interact with the ALL_TESTS_PASS gate? The gate
   currently checks whether `pytest` (or equivalent) passes. Do we need
   a test runner abstraction for language-agnosticism?
5. What happens when a generated test fails? Is it a bug in the
   implementation (demote) or a bad test (regenerate)?
6. Should the implementation agent emit both the function body AND its
   tests in one output? What does the output schema look like?

### Gap 5: Full Demotion Chain (L3 → L2 → L1)

**Current state:**
- `DemotionTicket` exists with `target_layer: Literal["L1", "L2", "L3"]`
  but defaults to "L1"
- `DemotionManager.apply(ticket)` writes patches to L1 (spec comments,
  new functions) and enqueues items in GapQueue
- The PromotionLoop's `PromoteStep` creates DemotionTickets when gates fail
  (lines 455-470) — but only for L1
- No `DownwardFlowEngine` traces through pins to atoms
- Code quality review (Promotion 3: L2→L3) exists in `pdd_lifecycle.py`
  but findings don't produce DemotionTickets

**Problem:**
Per WORKFLOW_ANALYSIS.md, demotion should cascade all the way down:

```
Issue at L3 (code quality)
  → evaluate: quality issue or logic issue?
  → if logic → demote to L2
Issue at L2 (architecture)
  → evaluate: architectural or algorithmic?
  → if algorithmic → demote to L1
Issue at L1 (code-as-spec)
  → evaluate: implemented or under-specified?
  → if under-specified → expand spec → implement → re-promote
```

The system needs:
1. **L3→L2 demotion**: Code quality reviewers find a logic issue →
   DemotionTicket targeting L2 → architectural layer is patched
2. **L2→L1 demotion**: Architectural quality gates fail OR architectural
   change requires new atoms → DemotionTicket targeting L1 → code-as-spec
   layer is expanded
3. **Re-promotion**: After L1 fix, the atom must re-promote through ALL
   gates back up to where it came from

**What exists that can be reused:**
- `DownwardFlowEngine` in the codebase (needs verification — may be a
  reference in WORKFLOW_ANALYSIS but not yet implemented)
- Pin tracing: `PinRegistry.trace_backward()` can follow pins from
  architectural locations back to atoms
- `DemotionTicket` schema already supports `target_layer`
- The 4 code quality reviewer agents (`chatgpt-*-reviewer`) produce
  findings but don't create DemotionTickets

**Questions:**
1. How does L3 decide whether an issue is "quality" (fix in place) vs
   "logic" (demote to L2)? Is this an LLM classification?
2. How does L2 decide whether to fix architecturally or demote to L1?
   Is this based on the NO_INLINED_ATOM_LOGIC gate?
3. What does a multi-layer DemotionTicket look like? Does it hop one
   layer at a time (L3→L2, then L2→L1 if needed)? Or can it go directly
   from L3→L1?
4. How does re-promotion work? When an L1 atom is fixed, does it
   automatically re-enter the PromotionLoop? Or is there a separate
   "re-promotion queue"?
5. How does the DownwardFlowEngine work concretely? Input: failing test
   at L2. Output: the specific atom(s) at L1 that need fixing. Algorithm:
   trace pins backward from the architectural location to the algorithmic
   location. What data does it need?
6. How does demotion interact with worktrees? If L3 demotes to L1, which
   worktree does the fix happen in? The L1 grandchild? A new worktree?

### Gap 6: Architectural Implementation Agent

**Current state:**
- P9 (`pdd-function-implementor`) implements algorithmic functions —
  it fills in function bodies from spec comments
- No agent builds the architectural layer (services, event handlers,
  middleware, API endpoints) from promoted atoms
- Pin projection types exist (`PASS_THROUGH`, `EVENT_BRIDGE`, etc.) in
  `branches/types.py` but nothing uses them to assemble architecture

**Problem:**
After atoms are promoted via pins (Promotion 2), the architectural layer
needs to be BUILT. This is a different kind of work from P9:
- P9 fills in individual function bodies from spec comments
- Architectural implementation assembles promoted atoms into services,
  wires event handlers, builds middleware chains, creates API endpoints

Per the design:
- Pin projection types describe HOW atoms are assembled
- `PASS_THROUGH`: Direct delegation to atom
- `EVENT_BRIDGE`: Atom wrapped in event handler
- `STORE_FACADE`: Atom behind store abstraction
- `COMPOSITION`: Multiple atoms composed into one function

**Questions:**
1. When does architectural implementation happen? After all atoms in a
   slice are promoted? After each atom promotion? Triggered by what?
2. Should the architectural agent receive pin projections as input and
   produce service/handler code as output? What's the input/output schema?
3. Is architectural implementation per-slice or cross-slice? Services
   often span multiple libraries. How does this interact with the
   per-slice PromotionLoop?
4. How does the architectural layer relate to worktrees? Does architectural
   code live in the L2 dirty worktree? Is it separate from the L1
   grandchild worktrees?
5. What compliance gates apply to architectural code? The existing
   architectural quality gates (NO_INLINED_ATOM_LOGIC, FUNCTION_RECOMPOSITION,
   PIN_COVERAGE, INTRODUCED_ALGORITHM_SPECS) check architectural quality.
   Are these sufficient, or do we need architectural-specific gates?
6. Can the implementation agent (P9) be extended to also handle
   architectural implementation, or should this be a completely separate
   agent with different capabilities?

---

## Existing Infrastructure to Reuse

| Component | Module | What It Does |
|-----------|--------|-------------|
| PromotionLoop | `orchestration/promotion_loop.py` | 10-step per-slice state machine |
| EvidenceBundle | `orchestration/evidence.py` | Per-slice per-iteration artifact (18+ Ref types) |
| DemotionTicket | `orchestration/demotion.py` | Single-layer demotion to L1 |
| UnderSpecManager | `orchestration/under_spec/manager.py` | Blocking with ConstraintsStore |
| SourceAnalysisCache | `orchestration/source_analysis_cache.py` | SHA-256-keyed analysis cache |
| IntakeQueue | `orchestration/intake_queue.py` | Conditional Phase 0 routing |
| PromotionScheduler | `orchestration/promotion_scheduler.py` | Bounded-concurrency parallel slices |
| WorktreeManager | `orchestration/worktree_manager.py` | Dirty/clean/grandchild hierarchy |
| ComplianceGates | `compliance/promotion/` | 9 gates (5 algorithmic + 4 architectural) |
| Evidence Loader | `compliance/promotion/evidence_loader.py` | AnalyzedFile bridge to gates |
| PinOrchestrator | `pin_functions/orchestrator.py` | Scan pins + merge LLM proposals |
| GapQueue | `core/gap_queue.py` | Gap aggregation + stagnation detection |
| PinRegistry | `core/pin_registry.py` | Pin trace forward/backward, drift detection |
| BranchManager | `branches/manager.py` | Atom registry, promotion, navigation |
| _run_implementation | `orchestration/pdd_orchestrator.py:849-977` | Real P9 with LLM function body generation |
| analyze_source | `core/code_analysis.py` | Language-agnostic LLM code analysis |
| RefinementEngine | `refinement_engine/detector.py` | Graph-based coupling/cohesion |
| InteractiveWorkflow | `refinement/interactive/` | Ambiguity detection/resolution |
| ResearchCoordinator | (multiple) | Multi-model research team |
| 4 reviewer agents | `.agents/agents/chatgpt-*-reviewer.md` | Code quality review |
| pdd-function-implementor | `.agents/agents/pdd-function-implementor.md` | LLM function body generation |

---

## Constraints On Your Design

1. **Existing modules are tools.** Don't propose rewriting core modules.
   Extend, adapt, wire — but preserve working logic.

2. **Language-agnostic.** All code analysis goes through `analyze_source()`.
   No AST, no tokenize, no language-specific parsing.

3. **LLM does work during its task (Principle 8).** When the implementation
   agent writes code, it should also emit pin proposals, edge proposals,
   under-spec events, and tests. Don't add separate mechanical steps for
   things the LLM already understands during its work.

4. **Promotion, not direct editing (Principle 4).** Architectural code
   emerges from promotion. The architectural agent should work with pin
   projections, not edit services directly.

5. **Block on ambiguity (Principle 10).** Under-specification must produce
   a hard stop. No best-effort guesses.

6. **Graph operations (Principle 6).** Downstream modules consume graph
   data (pins, edges, adjacency). New modules should follow this pattern.

7. **No backwards compatibility.** Old APIs can be deleted once new ones
   work. No shims, no dual-mode support long-term.

8. **Incremental implementation.** Design should allow implementing one
   gap at a time, testing each before moving to the next. Propose an
   implementation order with clear dependencies.

9. **File I/O between steps.** Steps produce files/artifacts consumed by
   the next step. This reduces LLM context pressure.

10. **Demotion replaces "skip."** Gate failures must produce DemotionTickets,
    not skip atoms. The loop handles the retry.

---

## What I Need From You

For each of the 6 gaps:

1. **Concrete design** — data structures, function signatures, control flow
2. **Module placement** — where the code lives, what it imports
3. **Agent prompt changes** — if an LLM agent needs new output fields,
   specify the exact schema changes
4. **Integration points** — how it connects to existing PromotionLoop steps,
   EvidenceBundle fields, and compliance gates
5. **Test strategy** — how to verify this gap is correctly filled

Additionally:
6. **Implementation order** — which gaps depend on which? What's the
   minimum viable order to get to QA-ready?
7. **Migration from legacy path** — which parts of `pdd_orchestrator.py`
   can be reused vs need replacement?
8. **Impact on existing tests** — what breaks, what needs updating?

---

## Reference Documents

- `simpler.md` — Authoritative design (PDD lifecycle + intake)
- `WORKFLOW_ANALYSIS.md` — Promotion model (correct target state)
- `LONG_TERM_GOALS.md` — Phase history + eval methodology + design principles
- `PROMOTION_LOOP_RESEARCH_RESPONSE.md` — PromotionLoop design (implemented)
- `PROMOTION_LOOP_REFINEMENT_RESPONSE.md` — PromotionLoop refinements
- `DESIGN_AUDIT_RESEARCH_RESPONSE.md` — Full design audit (10 violations)
- `PHASE0_RESEARCH_RESPONSE.md` — Phase 0 routing design
- `LANGUAGE_AGNOSTIC_RESEARCH_RESPONSE.md` — Language-agnostic migration
