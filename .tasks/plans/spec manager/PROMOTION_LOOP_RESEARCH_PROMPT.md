# Research: Designing the Iterative Per-Slice PromotionLoop

## What I Need From You

I need the architecture for an **iterative per-slice PromotionLoop** that replaces my current sequential P0-P10 pipeline. The current system runs all 11 phases in order, once, on the entire workspace. The target system runs a loop per slice (library/worktree) that invokes phases as tools until all gaps are closed and all atoms are promoted through compliance gates.

I have three prior design references that describe what this loop should look like. I need you to synthesize them into a concrete, implementable design — specifically the loop control flow, the shared data artifact (EvidenceBundle), the demotion chain, and how existing modules map to loop steps.

---

## The Current Architecture (What Exists)

### Sequential Pipeline

`pdd_orchestrator.py` runs P0 through P10 in fixed order:

```text
P0 (extraction) → P1 (structure) → P2 (decomposition) → P3 (compliance) →
P4 (library) → P5 (spec_build) → P6 (cross_library) → P7 (projection) →
P8 (planning) → P9 (implementation) → P10 (continuous_qa)
```

Each phase scans the entire workspace globally. There is no per-slice isolation. Phases don't communicate via a shared artifact — each re-scans files independently.

### What Each Phase Currently Does

| Phase | Module | What It Does |
|-------|--------|-------------|
| P0 | `intake/` | Routes freeform prose → PDD skeletons (5-step LLM pipeline). Promotion 1. |
| P1 | `planning.models.parse_file` + `core.edit_in_place` | Parses structure, identifies gaps |
| P2 | `planning.reverser` | Reverse-translates functions to pseudocode |
| P3 | `compliance.detection.orchestrator` | Finds executable gaps (comments, stubs) → GapQueue |
| P4 | `branches.manager.collapse_codebase` | Classifies code into atoms/stores/shapes, builds atom registry |
| P5 | `pin_functions.orchestrator` + `branches.promote` | Scans for pin functions, promotes atoms through compliance gates |
| P6 | `analysis.adjacency.runner` | Builds adjacency graph, detects disconnected components |
| P7 | `projection.lineage` + generators | Builds lineage (atom → architecture), generates analysis + plan |
| P8 | `planning.workflow` | Produces insertion plans from gap-derived intentions |
| P9 | `core.edit_in_place` | LLM implements function bodies from spec comments |
| P10 | `strategies.evolution` + `refinement_engine` | Strategy promotion + coupling/cohesion analysis |

### Existing Infrastructure (Already Built)

These are the pieces that work and should be preserved/consumed:

- **GapQueue** (`core/gap_queue.py`): Aggregation + stagnation detection. Holds GapEvidence items.
- **AdjacencyGraph** (`analysis/adjacency/graph.py`): Typed weighted directed graph with SignalType enum.
- **PinRegistry** (`core/pin_registry.py`): Forward/backward trace, drift detection. O(1) lookups.
- **WorkspaceManager** (`refinement/workspace/manager.py`): Run-scoped workspace with state tracking, phase status.
- **WorktreeManager** (`orchestration/worktree_manager.py`): Dirty/clean/grandchild worktree hierarchy. Per-library grandchild worktrees for parallel work.
- **BranchManager** (`branches/manager.py`): Atom registry, vertical slices, collapse engine, promotion engine.
- **ComplianceGates** (`compliance/promotion/algorithmic_gates.py`): 5 gates — NO_REMAINING_COMMENTS, NO_STUB_FUNCTIONS, ALL_TESTS_PASS, CALL_GRAPH_CONNECTED, STORE_MONOGAMY.
- **ArchitecturalGates** (`compliance/promotion/architectural_quality.py`): NO_INLINED_ATOM_LOGIC, FUNCTION_RECOMPOSITION, etc.
- **RefinementEngine** (`refinement_engine/detector.py`): Graph-based coupling/cohesion analysis. Analysis-only.
- **InteractiveWorkflow** (`refinement/interactive/`): Ambiguity detection and resolution.
- **ResearchCoordinator**: Multi-model research team (Opus + GPT + GLM + firecrawl).
- **DownwardFlowEngine**: Traces architectural test failures back through pins to atoms.
- **`analyze_source(content, filepath)`** (`core/code_analysis.py`): The ONE code analyzer. Language-agnostic via LLM. Returns `SourceAnalysis` with functions and comments.
- **`scan_imports_from_files()`/`scan_imports_from_directory()`** (`projection/lineage/builder.py`): Import scanning via `analyze_source`.

### Key Gaps in Current Architecture

1. **No per-slice loop**: `run()` iterates phases, not slices. No way to loop gap→implement→promote→verify per slice.
2. **No shared evidence artifact**: Each phase re-scans files. No EvidenceBundle passed between steps.
3. **No demotion chain**: Gate failures log warnings and skip atoms. Nothing produces a concrete DemotionTicket that feeds back into L1.
4. **P9 doesn't loop**: Implementation runs once, not iteratively until gaps close.
5. **Phase 0 always runs**: Even when input is already structured code, P0 is the first phase in the sequence.
6. **No under-specification blocking**: Planning produces plans without blocking on ambiguity.

---

## Prior Design #1: WORKFLOW_ANALYSIS.md — The Target Model

### The Iterative Loop (per slice)

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

  4. ANALYZE
     P1 structure → parse what was written
     P2 decomposition → reverse-translate for intent verification

  5. PROMOTE
     P4 library → extract atoms from code
     P5 spec_build → pin + promote through compliance gates
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
     Architectural quality gates

  8. POWER alignment check (periodic)

  9. REPEAT for next slice
```

### Termination Criteria

- All spec comments implemented (P3 → 0 gaps)
- All atoms promoted through ALL compliance gates
- All pins exercised (architectural code uses them)
- All quality gates pass
- Cross-library connected (P6)
- Lineage complete (P7 → 0 orphans)
- Refinement clean (no overlap/divergence/overload)
- Clean worktree tests pass
- POWER alignment clean

### Key Insight: P1-P10 Are Tools, Not Stages

"P1-P10 are TOOLS invoked within the promotion cycle, not a sequential pipeline."

| Phase | Role in Loop |
|-------|-------------|
| P0 | Conditional entry point (Promotion 1 only) |
| P1 | Analyze step |
| P2 | Analyze step |
| P3 | Gap exploration |
| P4 | Promote step |
| P5 | Promote step (L1→L2 bridge) |
| P6 | Verify step (post all-slice) |
| P7 | Verify step (post all-slice) |
| P8 | Gap exploration (planning) |
| P9 | Implementation step |
| P10 | Periodic assessment |

---

## Prior Design #2: DESIGN_AUDIT_RESEARCH_RESPONSE.md — Structural Fixes

The design audit identified this as **Priority #1** (everything else depends on it):

### Migration Path (from audit)

1. **Introduce a new runner** (`promotion_loop.py`) that runs on ONE slice.
2. **Refactor existing phases into pure functions** with explicit inputs/outputs (no global scanning).
3. **Make `pdd_orchestrator.py` a compatibility wrapper** that calls the loop once (or runs "batch mode"), then slowly retire it.
4. **Add parallelism** only after slices are truly isolated (worktrees + artifact boundaries).

### EvidenceBundle (from audit, Priority #2)

"Create a single run-scoped **EvidenceBundle** (facts + pins + edges + diff + provenance) produced once per slice."

This is the prerequisite for removing redundant per-phase parsing. Gates, promotion, planning, and verification all consume the same bundle.

### DemotionTicket (from audit, Priority #5)

"Gate failure must produce a **DemotionTicket** that becomes a concrete edit target in Layer 1."

Schema: `{gate, failing_pins, recommended_spec_patch, questions}`

`DemotionManager.apply(ticket)` writes the patch into L1 skeleton (or queues an intake routing item if truly new), records lineage. Replace "skip atom" with "demote atom," then loop.

### Conditional Phase 0 (from audit, Violation A)

Phase 0 should be a conditional entrypoint used only for:
- External intake (new prose requirements)
- Demoted algorithm descriptions
- Genuinely new constraints

Otherwise bypass it entirely.

---

## Prior Design #3: simpler.md — The PDD Lifecycle

The 4-phase lifecycle model:

1. **Build**: Research → sparse plan → worktree → implement in parallel → block on ambiguity → POWER alignment → human review → approve
2. **QA**: Create evals → detect failures → root cause → patch back
3. **Architecture**: Proposals → analysis → choice → refactor
4. **Code Quality**: N reviewers → refactor → merge to main

Key principle: "Plan as little as you can get away with. Constant baby steps. Each phase produces something messy. The next phase cleans it up."

The 3-layer promotion model:
```text
Layer 0: Raw prose (unstructured) — OPTIONAL entry point
    ↓ PROMOTION 1 (only if input is raw prose)
Layer 1: Code-as-spec (PDD skeletons — spec comments + code in same files)
    ↓ PROMOTION 2
Layer 2: Architecture (services/events/middleware assembled from pin-functions)
    ↓ PROMOTION 3
Layer 3: Clean code (production-ready, merged to main)
```

---

## What I Need You To Design

### Question 1: The PromotionLoop Control Flow

Design the exact control flow for the per-slice PromotionLoop. Specifically:

- What is the loop's entry state? (A slice from GapQueue? A library worktree? Something else?)
- What is one iteration of the loop? (Which steps, in what order, with what conditions?)
- When does an iteration retry vs advance to the next slice?
- How does the loop handle multiple slices? (Sequential? Parallel? Priority-ordered from GapQueue?)
- What is the termination condition? (All slices promoted? All gaps closed? Both?)
- How does the loop relate to the 4-phase lifecycle from `simpler.md`? (Is PromotionLoop = Build phase? Or does it span Build + QA?)

The current orchestrator has `run()` which iterates phases. The new design needs `run()` to iterate slices within a loop. How do these coexist during migration?

### Question 2: The EvidenceBundle Schema

Design the EvidenceBundle — the single artifact produced per slice per iteration that all downstream consumers read.

- What fields does it contain? (facts, pins, edges, diff, provenance, gaps, test results?)
- How is it produced? (By the implementation agent? By analyze_source? By a dedicated "evidence collector" step?)
- How is it consumed? (Gates query it? Planning reads it? Verification checks it?)
- What is its lifecycle? (Per-iteration? Per-slice? Cached and invalidated by diffs?)
- How does it relate to existing artifacts? (`GapQueue`, `PinRegistry`, `AdjacencyGraph`, `SourceAnalysis` — are these views over the bundle, or does the bundle aggregate them?)

The audit says: "facts + pins + edges + diff + provenance." But the current system has these as separate, independently-computed artifacts. How do they merge into one coherent bundle without a big-bang rewrite?

### Question 3: Loop Step Design — What Each Step Consumes and Produces

For each step of the loop (gap exploration, implementation, under-spec check, analyze, promote, integrate, verify), specify:

- **Input**: What artifact(s) does it read?
- **Output**: What artifact(s) does it produce or mutate?
- **Module mapping**: Which existing module(s) implement this step?
- **Pure function signature**: What would the step look like as a pure function?

The goal is to understand exactly how existing modules (P1-P10) map to loop steps, and what adapter work is needed to make them consume EvidenceBundle instead of re-scanning files.

### Question 4: The Demotion Chain

Design the full demotion chain: gate failure → DemotionTicket → Layer 1 patch → GapQueue → re-loop.

- What is a DemotionTicket? (Schema, who creates it, what it contains)
- How does `DemotionManager.apply(ticket)` work? (Does it modify files? Create new spec comments? Add to GapQueue?)
- How does demotion interact with the PromotionLoop? (Does a demotion restart the current slice iteration? Or enqueue a new slice?)
- How does the L3→L2→L1 chain work? (Code quality reviewer finds issue → demote to L2 → if architectural, demote further to L1 → expand spec → re-promote through ALL gates)
- How does `DownwardFlowEngine` (existing) fit in? (It traces pins to atoms — does it generate DemotionTickets?)

Currently, gate failures return `skipped_atoms` in the promotion result. Nothing acts on them. The fix needs to flip "skip" to "demote and loop."

### Question 5: Conditional Phase 0 and Intake Routing

Phase 0 currently runs as the first step in every pipeline invocation. The target:

- Phase 0 runs ONLY when the input is freeform prose (external intake).
- If input is already PDD skeletons (Python code with spec comments), skip Phase 0 entirely.
- When a demotion produces content that needs routing (genuinely new requirement, not just a fix), Phase 0's routing mechanism is invoked for JUST that content — not the entire spec.

How should this be wired?

- How does the system detect whether Phase 0 is needed? (File extension? Manifest flag? Content analysis?)
- How does partial Phase 0 work? (Route one new requirement, not re-route everything)
- Does the PromotionLoop ever invoke Phase 0 mid-loop? (e.g., demotion discovers a genuinely new requirement that needs routing)

### Question 6: Migration Strategy

The current `pdd_orchestrator.py` is 1132 lines and working. Tests depend on its API. The migration must be incremental.

- What is the first concrete change? (Add `promotion_loop.py` alongside existing orchestrator? Refactor `run()` to support both modes?)
- How do tests migrate? (New test file for PromotionLoop? Existing tests remain for compatibility wrapper?)
- What is the minimum viable PromotionLoop? (Maybe: single slice, no parallelism, no demotion, just gap→implement→promote→verify in a loop?)
- What order should capabilities be added? (Basic loop → EvidenceBundle → demotion → parallelism → conditional P0?)
- When can the old sequential pipeline be deleted?

### Question 7: Under-Specification Blocking

The target requires the loop to BLOCK when it hits an under-specification that constraints don't cover. Currently, planning just produces plans without blocking.

- How does the implementation agent signal "I can't resolve this"?
- What does the "waiting for constraints" state look like in the loop?
- In interactive mode: how is the research prompt generated and presented?
- In auto mode: how does the research team (Opus + GPT + GLM + firecrawl) get invoked?
- How do new constraints flow back into the loop? (Added to EvidenceBundle? Written to analysis docs? Both?)
- How does the loop resume after constraints are provided?

---

## Constraints On Your Design

1. **Incremental migration.** The current orchestrator works and has tests. Don't propose a big-bang rewrite. The PromotionLoop should be addable alongside the existing sequential pipeline, then gradually take over.

2. **Existing modules are tools.** P1-P10 modules exist and work. They should become callable steps within the loop, not be rewritten. Adapter work is acceptable (changing what they consume), but their core logic should be preserved.

3. **No backwards compatibility.** We don't need to support the old sequential-only API forever. Once migration is complete, the old `run()` method can be deleted. But during migration, both must coexist.

4. **Language-agnostic.** All code analysis goes through `analyze_source()`. No AST, no tokenize, no language-specific parsing. This was completed in the language-agnostic migration. Don't regress.

5. **LLM does work during its task.** When the implementation agent writes code, it should also emit pin proposals, edge proposals, and evidence — not as a separate step. This aligns with the audit's recommendation (Priority #3: move pin+edge creation into LLM task outputs).

6. **Graph is primary artifact.** Pins + edges in PinRegistry + AdjacencyGraph are the canonical artifacts. Gates query the graph, not source code. The EvidenceBundle may be the mechanism that populates the graph.

7. **Block on ambiguity, don't guess.** The under-specification flow must produce a hard stop, not a best-effort guess. No promotion continues until resolved.

8. **File I/O between steps.** Each step produces files/artifacts that the next step consumes. This reduces context pressure for LLM agents and allows different models for different steps.

9. **WorktreeManager exists.** Per-library grandchild worktrees, dirty/clean/sibling hierarchy — all built. The PromotionLoop should use this infrastructure for slice isolation and CI integration.

10. **No new extraction.** The loop should route, not extract. If new content needs to be added to the code-as-spec layer, it goes through the routing mechanism (Phase 0 pattern), not through an extraction pipeline.
