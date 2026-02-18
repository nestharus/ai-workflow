# TODO(single-layer) Algorithm Refinement — Tier 2

## Your Task

You are expanding directional TODO comments into detailed implementation algorithms.
Each `TODO(single-layer)` in the codebase contains a directional description of what
needs to change and why (with section references to the design proposal). Your job is
to read each TODO, read the referenced proposal sections, read the existing code, and
write a detailed pseudocode algorithm that a code-writing agent can implement without
ambiguity.

**CRITICAL**: Some TODO blocks span 30+ lines. Read the ENTIRE TODO block before
writing your algorithm. Do NOT truncate at 20 lines.

## How to Work

For each file listed below:
1. Read the full `TODO(single-layer)` block at the top of the file
2. Read the proposal sections it references (in `response3.md`)
3. Read the existing code in that file to understand current structure
4. **Write your algorithm as a NEW comment block** directly below the existing TODO,
   prefixed with `# ALGORITHM(single-layer):`. Do NOT modify the existing TODO.
5. Your algorithm must specify:
   - **Data structures**: Fields, types, relationships (use Python type hints)
   - **Control flow**: if/else, loops, state machines — in pseudocode
   - **Error handling**: What can go wrong, how to handle it
   - **Integration points**: What calls this, what does this call
   - **Interface contracts**: Function signatures with types
   - **Test requirements**: What should be tested (key scenarios)

**Do NOT write implementation code.** Write pseudocode-level algorithms detailed
enough that a code-writing agent can implement without ambiguity or falling back
on bias.

## Files to Read First

- **Design proposal**: `scripts/spec_manager/.tasks_plans_spec_manager_.research/single-layer-refinement/response3.md`
  - Actually located at: `.tasks/plans/spec manager/.research/single-layer-refinement/response3.md`
- **Evaluation report** (accepted modifications): `.tasks/plans/spec manager/.research/single-layer-refinement/evaluation-report.md`
  - Section "Proposed Modifications" contains 5 constraints your algorithms must satisfy

## Evaluation Report Constraints (MUST be incorporated)

These were identified during evaluation and must be reflected in your algorithms:

1. **Bootstrap rule**: Phase 0 produces initial shapes from spec decomposition.
   First Build pass operates from spec inputs (like current L1). Shapes without
   verifiers are PROPOSALS, not active shapes.
2. **Phase ordering**: Work items from any phase are re-triaged and queued for
   the correct phase in the next cycle iteration. Fixed order: Build → Algorithm
   → Architecture → Quality.
3. **Verifier lifecycle**: Active shapes require at least one verifier. When a shape
   is created or updated, a work item to create/update verifiers is automatically
   generated as a Build task.
4. **Pattern library scope**: Project-scoped, derived from spec/algorithms, validated
   by verifier test existence.
5. **First Build pass**: Same as current L1 behavior (discovery + implementation from
   spec inputs), subsequent Build passes consume work items from prior refinement phases.

## Files Requiring Algorithms

### NEW files (need full algorithm design)

These are placeholder files. Design the complete module from scratch.

1. **`scripts/spec_manager/spec_manager/routing/shapes.py`** — Shape parser/loader (Sections 4, 5)
2. **`scripts/spec_manager/spec_manager/routing/matcher.py`** — Shape matcher (Section 6)
3. **`scripts/spec_manager/spec_manager/routing/verifiers.py`** — Verifier runner (Sections 4.1, 6.3, 9.4)
4. **`scripts/spec_manager/spec_manager/routing/__init__.py`** — Package exports

### RESTRUCTURE files (need algorithm for what changes)

These files survive but with significant reorganization. Design the delta.

5. **`scripts/spec_manager/spec_manager/orchestration/pdd_lifecycle.py`** — Core lifecycle: L1→L2→L3 becomes single-layer four-phase cycle (Sections 9, 12)
6. **`scripts/spec_manager/spec_manager/orchestration/promotion_loop.py`** — 10-step state machine adapts to phase-bounded iteration (Sections 9.1, 9.2)
7. **`scripts/spec_manager/spec_manager/orchestration/pdd_orchestrator.py`** — Phase 0 intake KEEPS, Phases 1-3 merge into single-layer (Sections 9, 12)
8. **`scripts/spec_manager/spec_manager/orchestration/run_state.py`** — Loses active_layer, gains phase/cycle tracking (Section 9.3)
9. **`scripts/spec_manager/spec_manager/compliance/promotion/orchestrator.py`** — Gate orchestrator: layer gates → aspect groups (Section 10)
10. **`scripts/spec_manager/spec_manager/compliance/promotion/config.py`** — GateId enum reorganization (Section 10.2)
11. **`scripts/spec_manager/spec_manager/compliance/promotion/algorithmic_gates.py`** — Become "Behavior gates" (Section 10.1 group A)
12. **`scripts/spec_manager/spec_manager/compliance/promotion/architectural_quality.py`** — Become "Architecture gates" (Section 10.1 group B)
13. **`scripts/spec_manager/spec_manager/compliance/promotion/__init__.py`** — Public API renames
14. **`scripts/spec_manager/spec_manager/compliance/promotion/provenance.py`** — Provenance adapts to shape-based traceability
15. **`scripts/spec_manager/spec_manager/compliance/promotion/introduction_checker.py`** — Shape contract presence instead of comment markers
16. **`scripts/spec_manager/spec_manager/orchestration/demotion/triage.py`** — Triage targets phases instead of layers (Section 11)
17. **`scripts/spec_manager/spec_manager/orchestration/demotion/router.py`** — Converts failures to work items (Section 11)
18. **`scripts/spec_manager/spec_manager/orchestration/demotion/__init__.py`** — Demotion → work item escalation
19. **`scripts/spec_manager/spec_manager/orchestration/review/findings_to_tickets.py`** — Loses layer routing, gains phase routing
20. **`scripts/spec_manager/spec_manager/orchestration/coordination/work_items.py`** — Work items gain shape_id routing (Section 8)
21. **`scripts/spec_manager/spec_manager/projection/lineage/builder.py`** — Consumes shape ownership instead of PinFunctionRegistry
22. **`scripts/spec_manager/spec_manager/planner/router.py`** — LayerRouter → PhaseRouter (Section 9.1)
23. **`scripts/spec_manager/spec_manager/planner/layers/l1.py`** — Merge into Build phase planner
24. **`scripts/spec_manager/spec_manager/planner/layers/l2.py`** — Merge into Architecture Refinement phase
25. **`scripts/spec_manager/spec_manager/planner/layers/l3.py`** — Merge into Quality Refinement phase
26. **`scripts/spec_manager/spec_manager/planner/strategies/architecture_strategy.py`** — Loses L2 gate, uses shape verifiers

### KEEP/EXTEND files (need algorithm for the extensions only)

These files survive as-is but need new functionality added.

27. **`scripts/spec_manager/spec_manager/orchestration/pattern_library.py`** — Add contract pattern templates (Section 7.2)
28. **`scripts/spec_manager/spec_manager/orchestration/coordination/monitors.py`** — Add shape-drift and stagnation monitors (Section 9.3)
29. **`scripts/spec_manager/spec_manager/orchestration/coordination/monitor_executor.py`** — Add shape-aware monitor conditions
30. **`scripts/spec_manager/spec_manager/refinement/evals/runner.py`** — Add single-layer evaluation support (Section 14)
31. **`scripts/spec_manager/spec_manager/refinement/evals/metrics.py`** — Add shape-aware metrics (Section 14.3)

### KEEP/RESTRUCTURE files (need algorithm for reorganization + extensions)

32. **`scripts/spec_manager/spec_manager/orchestration/implementation/runner.py`** — Loses layer dispatch, gains phase-aware implementation
33. **`scripts/spec_manager/spec_manager/planner/api.py`** — GeneralPlanner: phase dispatch instead of layer dispatch

## Files NOT Requiring Algorithms (for reference only)

### DELETE files (22 files) — just delete, no algorithm needed
- `branches/pins.py`, `core/pin_registry.py`, `core/layer_types.py`
- `pin_functions/` (cli.py, orchestrator.py, __init__.py)
- `projection/` (pin_propagation.py, generator.py, drift.py)
- `projection/lineage/` (test_pin_*.py, table.py, edges.py, data_flow.py, persistence.py, drift_detector.py)
- `schemas/` (projection.py, pin_functions.py)
- `compliance/promotion/` (pin_coverage.py, test_pin_gate.py)
- `orchestration/downward_flow/engine.py`
- `tests/unit/` (test_pins.py, test_pin_function_schema.py, test_pin_coverage.py)

### KEEP files (18 files) — no changes needed
- `compliance/promotion/result.py`, `evidence_loader.py`, `call_graph.py`
- `core/testing/runner.py`, `registry.py`
- `orchestration/under_spec/manager.py`, `evidence.py`
- `orchestration/intent_agent/` (agent.py, skeleton.py, signals.py, taxonomy.py)
- `orchestration/coordination/` (signals.py, wake_queue.py, wait_graph.py)
- `planner/` (constraints/store.py, strategies/constraint_strategies.py, architecture/artifacts.py)

## Algorithm Quality Checklist

For each algorithm you write, verify:
- [ ] References specific proposal sections for every design decision
- [ ] Specifies data structure fields with types
- [ ] Defines function signatures with parameter types and return types
- [ ] Describes error/edge cases and their handling
- [ ] Lists what other modules call this and what this calls
- [ ] Describes what tests should verify
- [ ] Does NOT include actual Python implementation code
- [ ] Incorporates all 5 evaluation report constraints where applicable
- [ ] Specifies what happens on the FIRST cycle (bootstrap) vs subsequent cycles

## Interface Consistency Rules

These interfaces are shared across multiple files. Ensure consistency:

- **Shape**: Used by shapes.py, matcher.py, verifiers.py, work_items.py, monitors.py
- **WorkItem**: Used by work_items.py, triage.py, router.py, findings_to_tickets.py
- **ShapeMatchReport**: Used by matcher.py, orchestrator.py, monitors.py
- **VerifierResult**: Used by verifiers.py, matcher.py, orchestrator.py
- **PhaseId**: Used by run_state.py, promotion_loop.py, pdd_lifecycle.py, router.py

When defining these interfaces, define them ONCE (in the most natural home module)
and reference that definition in all other algorithms.
