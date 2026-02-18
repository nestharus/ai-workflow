# Audit ALGORITHM(single-layer) Blocks Against Response4

## Your Task

33 files in `scripts/spec_manager/spec_manager/` contain `# ALGORITHM(single-layer):` comment blocks. These algorithms describe the design for a single-layer phase model. Your task is to audit every ALGORITHM block for correctness against the authoritative design document.

**Output a structured audit report.** For each file, report:
- **PASS**: Algorithm is consistent with response4 and internally consistent with other ALGORITHM blocks
- **ISSUE**: Describe the specific inconsistency, what's wrong, and what the correct content should be

## Authoritative Design Document

Read `.tasks/plans/spec manager/.research/single-layer-refinement/response4.md` FIRST. This is the corrected single-layer phase model.

## Audit Checklist (apply to EVERY file)

### 1. Phase Model Correctness
- PhaseId must be `Literal['libraries', 'architecture', 'quality']` (3 phases, not 4)
- No references to 'build' or 'algorithm' as phase names (except when explicitly rejecting them as invalid)
- Forward-only progression: Libraries → Architecture → Quality
- No cycling back through all phases
- Each phase is its own bounded cycle with iterations per slice

### 2. Code Editing Authority
- ALL phases edit code via their own PromotionLoop IMPLEMENT step
- No "Build is the only code-editing phase" or "refinement phases emit work items only"
- Libraries: full code+test authority within library boundaries
- Architecture: wiring + components + contracts + can edit algorithms in-place; cannot create new libraries or change ownership
- Quality: refactoring only; cannot change behavior

### 3. Phase-Local Remediation (No Backtracking)
- No demotion to earlier phases
- No re-triage to earlier phases in next cycle
- Within-authority findings: handle locally (queue_work_item or fix_in_phase)
- Outside-authority findings: BLOCK with diagnostics
- Architecture can remediate algorithm issues in-place (this is NOT demotion)

### 4. Skeleton Lifecycle
- Each phase: propose skeleton (draft) → work (PromotionLoop) → refine skeleton (non-draft)
- Skeleton = "where code can exist at this scale" (structural map, NOT spec, NOT implementation)
- Libraries: freeze library roster, ownership, store boundaries
- Architecture: freeze component roster, contract inventory, verifier suite
- Quality: freeze internal organization decisions
- Track via commit tags per phase

### 5. Phase 0 Outputs
- Draft shapes (one per library, ownership, dependencies, contracts)
- Algorithm inventory (names + owning library + entrypoints + invariants)
- Store inventory (IDs + owning library + access boundaries + adapters)
- NOT just spec decomposition

### 6. Call Graph Classification
- Call graph is hint BEFORE classification
- After deterministic classification against shapes:
  - Algorithm membership: surface API entrypoints as roots → reachable subgraphs
  - Communication paths: cross-shape edges classified by declared contracts
  - Logical vs structural: within-shape non-contract = logical; contract-realizing or cross-shape = structural
- Classified call graph: authoritative as internal representation, NOT as convergence evidence
- Only verifiers (tests/checks) are convergence authority

### 7. Convergence Criteria
- Libraries: skeleton non-draft + verifiers pass + no open work items + within bounds
- Architecture: skeleton non-draft + contract verifiers pass + import boundaries satisfied + no open work items + within bounds
- Quality: all tests + all contract verifiers green + refactor items closed + within bounds
- Global: run terminates after Quality convergence

### 8. Gate Mapping
- Gates organized by aspect (behavior/architecture/quality)
- Libraries phase: library verifiers (hard) + LLM gap scans (soft)
- Architecture phase: shape matching + contract verifiers + integration tests (hard) + L2 reviewers (soft)
- Quality phase: all tests + contract verifiers + style checks (hard) + quality reviewers (soft)

### 9. Interface Consistency
Verify these shared types are defined consistently across all files that reference them:
- **PhaseId**: same Literal type everywhere
- **Shape/ShapeId**: consistent fields
- **WorkItem**: consistent fields, especially `target_phase` removed or corrected
- **ShapeMatchReport**: consistent structure
- **VerifierResult**: consistent structure
- **EscalationContext/EscalationRouting**: no `target_phase` field (use `action: block` instead of routing to another phase)

### 10. Design Principle Compliance
Cross-check against design principles in `.tasks/plans/spec manager/LONG_TERM_GOALS.md`:
- No extraction (route instead)
- No language-specific parsing (LLM only)
- Graph operations not code operations
- Dynamic structures not rigid types
- LLM does work during its task
- Promotion not direct editing
- Block on ambiguity

## Files to Audit

Read each file's complete `# TODO(single-layer):` and `# ALGORITHM(single-layer):` comment blocks.

1. `scripts/spec_manager/spec_manager/orchestration/run_state.py`
2. `scripts/spec_manager/spec_manager/orchestration/pdd_lifecycle.py`
3. `scripts/spec_manager/spec_manager/orchestration/promotion_loop.py`
4. `scripts/spec_manager/spec_manager/orchestration/pdd_orchestrator.py`
5. `scripts/spec_manager/spec_manager/routing/shapes.py`
6. `scripts/spec_manager/spec_manager/routing/matcher.py`
7. `scripts/spec_manager/spec_manager/routing/verifiers.py`
8. `scripts/spec_manager/spec_manager/routing/__init__.py`
9. `scripts/spec_manager/spec_manager/compliance/promotion/config.py`
10. `scripts/spec_manager/spec_manager/compliance/promotion/orchestrator.py`
11. `scripts/spec_manager/spec_manager/compliance/promotion/algorithmic_gates.py`
12. `scripts/spec_manager/spec_manager/compliance/promotion/architectural_quality.py`
13. `scripts/spec_manager/spec_manager/compliance/promotion/__init__.py`
14. `scripts/spec_manager/spec_manager/compliance/promotion/provenance.py`
15. `scripts/spec_manager/spec_manager/compliance/promotion/introduction_checker.py`
16. `scripts/spec_manager/spec_manager/orchestration/demotion/triage.py`
17. `scripts/spec_manager/spec_manager/orchestration/demotion/router.py`
18. `scripts/spec_manager/spec_manager/orchestration/demotion/__init__.py`
19. `scripts/spec_manager/spec_manager/orchestration/review/findings_to_tickets.py`
20. `scripts/spec_manager/spec_manager/orchestration/coordination/work_items.py`
21. `scripts/spec_manager/spec_manager/orchestration/coordination/monitors.py`
22. `scripts/spec_manager/spec_manager/orchestration/coordination/monitor_executor.py`
23. `scripts/spec_manager/spec_manager/projection/lineage/builder.py`
24. `scripts/spec_manager/spec_manager/planner/router.py`
25. `scripts/spec_manager/spec_manager/planner/api.py`
26. `scripts/spec_manager/spec_manager/planner/layers/l1.py`
27. `scripts/spec_manager/spec_manager/planner/layers/l2.py`
28. `scripts/spec_manager/spec_manager/planner/layers/l3.py`
29. `scripts/spec_manager/spec_manager/planner/strategies/architecture_strategy.py`
30. `scripts/spec_manager/spec_manager/orchestration/pattern_library.py`
31. `scripts/spec_manager/spec_manager/orchestration/implementation/runner.py`
32. `scripts/spec_manager/spec_manager/refinement/evals/runner.py`
33. `scripts/spec_manager/spec_manager/refinement/evals/metrics.py`

## Output Format

```
# ALGORITHM Audit Report

## Summary
- Files audited: 33
- PASS: N
- ISSUE: N

## Per-File Results

### 1. orchestration/run_state.py — PASS/ISSUE
[details if ISSUE]

### 2. orchestration/pdd_lifecycle.py — PASS/ISSUE
[details if ISSUE]

...
```

Write the report to: `.tasks/plans/spec manager/.research/single-layer-refinement/audit-report.md`
