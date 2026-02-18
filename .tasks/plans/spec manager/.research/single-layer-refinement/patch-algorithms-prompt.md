# Patch ALGORITHM(single-layer) Blocks: 4-Phase → 3-Phase Correction

## Your Task

33 files in `scripts/spec_manager/spec_manager/` contain `# ALGORITHM(single-layer):` comment blocks. These were written based on an incorrect 4-phase cycle model. You must patch each ALGORITHM block to reflect the corrected 3-phase forward-only model.

**Do NOT modify any code below the ALGORITHM blocks.** Only modify the `# ALGORITHM(single-layer):` comment blocks (and the `# TODO(single-layer):` blocks above them where they reference the wrong model). Preserve all other content exactly.

**Do NOT delete ALGORITHM blocks.** Patch them in place.

---

## The Correction (read completely before starting)

### WRONG model (currently in ALGORITHM blocks)

- **4 phases**: Build → Algorithm Refinement → Architecture Refinement → Quality Refinement
- **PhaseId**: `Literal['build', 'algorithm', 'architecture', 'quality']`
- **Build is the only code-editing phase**; refinement phases only emit work items
- **Phases repeat as a cycle** up to `max_phase_cycles=3`
- **Re-triage**: Findings from any phase are re-triaged to the correct phase in the next cycle iteration
- **Phase 0**: Just spec decomposition

### CORRECT model (what ALGORITHM blocks must say)

- **3 phases**: Libraries → Architecture → Quality (forward-only, no cycling back)
- **PhaseId**: `Literal['libraries', 'architecture', 'quality']`
- **Each phase edits code** via its own PromotionLoop with IMPLEMENT step
- **Each phase is its own cycle** with bounded iterations per slice, NOT a repeating 4-phase sequence
- **No backtracking**: Architecture can refine algorithms in-place (one codebase), Quality cannot change behavior. If a phase encounters something it cannot handle, it **blocks** (not demotes/re-triages to earlier phase)
- **Phase 0**: Produces draft shapes + algorithm inventories + store inventories (not just decomposition)
- **Skeleton lifecycle per phase**: propose skeleton (draft) → work (PromotionLoop) → refine skeleton (non-draft). Track via commit tags.

### Specific mappings

| Wrong (current) | Correct (target) |
|---|---|
| `PhaseId = Literal['build', 'algorithm', 'architecture', 'quality']` | `PhaseId = Literal['libraries', 'architecture', 'quality']` |
| `phase='build'` | `phase='libraries'` |
| `phase='algorithm'` | REMOVE (absorbed into Libraries phase) |
| "Build phase planner" / "BuildPhasePlanner" | "Libraries phase planner" / "LibrariesPhasePlanner" |
| "Build is the only code-editing phase" | "Each phase edits code via PromotionLoop IMPLEMENT step" |
| "refinement phases emit work items only" | REMOVE this concept — all phases do work |
| "cycle order: Build→Algo→Arch→Quality repeated" | "forward-only: Libraries→Architecture→Quality, each its own cycle" |
| `_run_build_phase()` | `_run_phase()` (unified, since all phases work the same way) |
| `_run_refinement_phase()` | REMOVE (no separate "refinement" phase concept) |
| "re-triage to correct phase in next cycle" | "phase-local remediation or block" |
| "max_phase_cycles=3" repeating all phases | "max_iterations_per_slice" within each phase, plus phase-wide caps |
| "Algorithm Refinement" as a phase | REMOVE — algorithms handled within Libraries phase |
| "Build consumes work items from prior refinement" | Libraries uses L1 behaviors; subsequent phases use L2/L3 behaviors |
| Demotion "escalation to target phase" | Phase-local remediation if within authority, block if not |

### Phase behaviors (what each phase does)

**Libraries phase** (L1 behaviors):
- Gap: algorithmic gaps
- Plan/Implement: create/edit code and tests
- Promote/Verify: deterministic verifiers + routing signals
- Skeleton freeze: library roster, ownership, store boundaries
- Can edit: everything within library boundaries

**Architecture phase** (L2 behaviors):
- Plan/Implement: wiring, components, contracts, adapters
- Can edit: component structure AND algorithm implementations in-place (one codebase)
- Cannot: create new libraries, change library ownership, reassign store ownership
- If needs library boundary change: BLOCK (not demote)
- Skeleton freeze: component roster, contract inventory, verifier suite

**Quality phase** (L3 behaviors):
- Plan/Implement: refactoring (extract helpers, rename, restructure files)
- Cannot: change behavior (tests + contract verifiers must stay green)
- If behavior change needed: BLOCK
- Skeleton freeze: internal organization decisions complete

### Skeleton lifecycle (ADD to relevant ALGORITHM blocks)

Each phase follows:
1. **Propose skeleton (draft)** — structural map at that scale
2. **Work** — PromotionLoop per slice with phase-appropriate behaviors
3. **Refine skeleton (non-draft)** — freeze structural invariants, record commit tag

Skeleton is "where code can exist at this scale" — NOT spec, NOT implementation, NOT files/functions.

### Call graph classification (ADD to routing ALGORITHM blocks)

The call graph is a hint BEFORE classification. After deterministic classification against shapes:
- Algorithm membership: surface API entrypoints as roots → reachable subgraphs within shape → labeled with shape_id + algorithm_id
- Communication paths: cross-shape edges classified by declared contracts
- Logical vs structural: within-shape non-contract = logical; contract-realizing or cross-shape = structural
- Classified call graph is authoritative as internal representation, NOT as convergence evidence

### Phase 0 outputs (CORRECT in lifecycle/orchestrator ALGORITHM blocks)

Phase 0 produces:
- **Draft shapes**: one per library, ownership paths, declared dependencies, initial contracts
- **Algorithm inventory**: names + owning library + entrypoints + required invariants
- **Store inventory**: IDs + owning library + access boundaries + required adapters

### Convergence (CORRECT in lifecycle ALGORITHM blocks)

Per-phase convergence (not per-cycle across all phases):
- **Libraries**: skeleton non-draft + verifiers pass + no open work items + within iteration bounds
- **Architecture**: skeleton non-draft + contract verifiers pass + import boundaries satisfied + no open work items + within bounds
- **Quality**: all tests + all contract verifiers green + refactor items closed + within bounds
- **Global**: run terminates after Quality convergence

### Gates (CORRECT in compliance ALGORITHM blocks)

Gates organized by aspect, run within three phases:
- **Libraries**: library verifiers (hard) + LLM gap scans (soft)
- **Architecture**: shape matching + contract verifiers + integration tests (hard) + L2 reviewers (soft)
- **Quality**: all tests + contract verifiers + style checks (hard) + quality reviewers (soft)

---

## Files to Patch (all 33)

Read each file's full `# TODO(single-layer):` and `# ALGORITHM(single-layer):` blocks. Apply the corrections above. Keep all content that is already correct. Only change what contradicts the 3-phase model.

### Core state/lifecycle (highest priority — defines shared interfaces)

1. `scripts/spec_manager/spec_manager/orchestration/run_state.py` — PhaseId definition is WRONG
2. `scripts/spec_manager/spec_manager/orchestration/pdd_lifecycle.py` — Cycle model is WRONG
3. `scripts/spec_manager/spec_manager/orchestration/promotion_loop.py` — "IMPLEMENT is Build-only" is WRONG
4. `scripts/spec_manager/spec_manager/orchestration/pdd_orchestrator.py` — Phase 0 outputs incomplete

### Routing (needs call graph classification additions)

5. `scripts/spec_manager/spec_manager/routing/shapes.py` — Phase references wrong
6. `scripts/spec_manager/spec_manager/routing/matcher.py` — Add call graph classification role
7. `scripts/spec_manager/spec_manager/routing/verifiers.py` — Phase references wrong
8. `scripts/spec_manager/spec_manager/routing/__init__.py` — Export updates

### Compliance (gate mapping)

9. `scripts/spec_manager/spec_manager/compliance/promotion/config.py` — Gate phase mapping
10. `scripts/spec_manager/spec_manager/compliance/promotion/orchestrator.py` — Phase dispatch
11. `scripts/spec_manager/spec_manager/compliance/promotion/algorithmic_gates.py` — "Behavior gates" phase mapping
12. `scripts/spec_manager/spec_manager/compliance/promotion/architectural_quality.py` — "Architecture gates" phase mapping
13. `scripts/spec_manager/spec_manager/compliance/promotion/__init__.py` — API renames
14. `scripts/spec_manager/spec_manager/compliance/promotion/provenance.py` — Phase references
15. `scripts/spec_manager/spec_manager/compliance/promotion/introduction_checker.py` — Phase references

### Demotion (now escalation/block)

16. `scripts/spec_manager/spec_manager/orchestration/demotion/triage.py` — "4 phases" → 3 phases, no backtrack
17. `scripts/spec_manager/spec_manager/orchestration/demotion/router.py` — Phase references
18. `scripts/spec_manager/spec_manager/orchestration/demotion/__init__.py` — Phase references

### Planner (phase dispatch)

19. `scripts/spec_manager/spec_manager/planner/router.py` — PhaseRouter registration
20. `scripts/spec_manager/spec_manager/planner/api.py` — PlanningContext phase
21. `scripts/spec_manager/spec_manager/planner/layers/l1.py` — "BuildPhasePlanner" → LibrariesPhasePlanner
22. `scripts/spec_manager/spec_manager/planner/layers/l2.py` — Architecture phase planner
23. `scripts/spec_manager/spec_manager/planner/layers/l3.py` — Quality phase planner
24. `scripts/spec_manager/spec_manager/planner/strategies/architecture_strategy.py` — Phase references

### Coordination/Review

25. `scripts/spec_manager/spec_manager/orchestration/coordination/work_items.py` — Phase references
26. `scripts/spec_manager/spec_manager/orchestration/coordination/monitors.py` — Phase references
27. `scripts/spec_manager/spec_manager/orchestration/coordination/monitor_executor.py` — Phase references
28. `scripts/spec_manager/spec_manager/orchestration/review/findings_to_tickets.py` — Phase references

### Projection/Eval/Other

29. `scripts/spec_manager/spec_manager/projection/lineage/builder.py` — Phase references
30. `scripts/spec_manager/spec_manager/orchestration/pattern_library.py` — Phase references
31. `scripts/spec_manager/spec_manager/orchestration/implementation/runner.py` — "Build-only" → all phases
32. `scripts/spec_manager/spec_manager/refinement/evals/runner.py` — Phase references
33. `scripts/spec_manager/spec_manager/refinement/evals/metrics.py` — Phase references

---

## Patch Rules

1. **Read the ENTIRE existing ALGORITHM block** before making changes.
2. **Preserve everything that is already correct** — don't rewrite from scratch.
3. **Change only what contradicts** the 3-phase model.
4. **Update TODO blocks** where they reference 4 phases or "Build" as a separate phase.
5. **Keep all section references** (response3 Section X) — the routing/shapes/matching sections from response3 are correct; only the phase model sections are wrong.
6. **Add** skeleton lifecycle, call graph classification, and Phase 0 output details where relevant.
7. **Preserve data structure fields** that are correct (ShapeId, VerifierSpec, ShapeContract, etc.).
8. **Update PhaseId references** everywhere: remove `'build'` and `'algorithm'`, add `'libraries'`.
9. **Interface consistency**: PhaseId is defined in run_state.py. All other files import it from there. Update the definition FIRST, then all references.

## Files to Read for Context

- **Corrected phase model**: `.tasks/plans/spec manager/.research/single-layer-refinement/response4.md`
- **Design proposal** (routing model — KEEP): `.tasks/plans/spec manager/.research/single-layer-refinement/response3.md`
- **Design principles**: `.tasks/plans/spec manager/LONG_TERM_GOALS.md`
