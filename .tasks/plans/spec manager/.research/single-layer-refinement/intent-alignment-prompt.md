# Intent Alignment Audit: ALGORITHM(single-layer) blocks vs proposal.md

## Task

You are auditing **33 files** that each contain an `ALGORITHM(single-layer)` comment block.
These blocks describe how each module will change when the system transitions from a
multi-layer (L1/L2/L3) model to a single-layer, phase-based model.

Your job: verify that the **substance** of each ALGORITHM block aligns with the
**authoritative proposal** in `proposal.md`. This is NOT a structural check (phase names,
etc. are already verified). This is an **intent alignment** check — does each block say
the **right thing** about what its module should do in the new model?

## Instructions

1. Read the authoritative proposal:
   `.tasks/plans/spec manager/.research/single-layer-refinement/proposal.md`

2. For each file listed below, read the `# ALGORITHM(single-layer):` comment block
   (typically at the top of the file, before the module docstring).

3. For each block, check alignment against the specific proposal sections noted.
   Ask yourself:
   - Does the ALGORITHM block correctly describe what this module does in the new model?
   - Does it match the proposal's intent for this concern area?
   - Are there any **contradictions** between the ALGORITHM block and the proposal?
   - Are there any **missing concerns** that the proposal addresses but the block omits?
   - Are there any **extra claims** in the block that the proposal doesn't support?

4. Write your report to:
   `.tasks/plans/spec manager/.research/single-layer-refinement/intent-alignment-report.md`

## Report format

For each file, output ONE of:
- **ALIGNED** — block matches proposal intent. One sentence explaining the match.
- **MISALIGNED** — block contradicts or diverges from proposal. Quote the specific
  ALGORITHM text that's wrong, cite the proposal section it should match, and explain
  the discrepancy.
- **INCOMPLETE** — block is correct but missing important concerns from the proposal
  for this module's domain. List what's missing with proposal section references.

## Files and their relevant proposal sections

### Group 1: Routing (Shapes, Matching, Verification)
These modules implement Sections 3-6 of the proposal.

- `scripts/spec_manager/spec_manager/routing/__init__.py` — General routing overview
  Check against: Sections 3 (shapes), 6 (matching), 8 (work item routing)

- `scripts/spec_manager/spec_manager/routing/shapes.py` — Shape definitions and lifecycle
  Check against: Sections 3 (shapes), 4 (format), 5 (storage/derivation/update), 9.2 (skeleton lifecycle)

- `scripts/spec_manager/spec_manager/routing/matcher.py` — Shape matching engine
  Check against: Section 6 (matching rules, outputs, observed structure sources)

- `scripts/spec_manager/spec_manager/routing/verifiers.py` — Deterministic verifiers
  Check against: Sections 4.1 (verifier section), 7 (contract patterns), 10 (gate reorganization)

### Group 2: Compliance/Promotion (Gates)
These modules implement Section 10 of the proposal.

- `scripts/spec_manager/spec_manager/compliance/promotion/__init__.py` — Gate overview
  Check against: Section 10 (aspect gates, per-phase mapping)

- `scripts/spec_manager/spec_manager/compliance/promotion/config.py` — Gate configuration
  Check against: Section 10.1 (aspect gate groups), 10.2 (what survives/converts/eliminates)

- `scripts/spec_manager/spec_manager/compliance/promotion/algorithmic_gates.py` — Algorithmic gates
  Check against: Section 10.2 (kept/converted/eliminated gates)

- `scripts/spec_manager/spec_manager/compliance/promotion/architectural_quality.py` — Arch quality gates
  Check against: Section 10.1 (Architecture phase gates), 10.2 (gate mapping)

- `scripts/spec_manager/spec_manager/compliance/promotion/introduction_checker.py` — Introduction checking
  Check against: Section 10.2 (what survives)

- `scripts/spec_manager/spec_manager/compliance/promotion/orchestrator.py` — Gate orchestration
  Check against: Section 10.1 (phase-based gate execution)

- `scripts/spec_manager/spec_manager/compliance/promotion/provenance.py` — Provenance tracking
  Check against: Section 10.2 (what survives), 13 (extraction boundary)

### Group 3: Orchestration (Lifecycle, Promotion, Demotion)
These modules implement Sections 9 and 11 of the proposal.

- `scripts/spec_manager/spec_manager/orchestration/run_state.py` — Run state management
  Check against: Section 9.1 (three phases), 9.5 (iteration bounds), 9.6 (convergence)

- `scripts/spec_manager/spec_manager/orchestration/pdd_lifecycle.py` — PDD lifecycle
  Check against: Section 9.1 (forward-only phases), 9.2 (skeleton lifecycle), 9.4 (Phase 0 outputs), 9.6 (convergence)

- `scripts/spec_manager/spec_manager/orchestration/pdd_orchestrator.py` — PDD orchestrator
  Check against: Section 9 (phase mechanism), 12 (simplification inventory)

- `scripts/spec_manager/spec_manager/orchestration/promotion_loop.py` — PromotionLoop state machine
  Check against: Section 9.1 (PromotionLoop per phase), 9.3 (phase authority), 9.5 (iteration bounds)

- `scripts/spec_manager/spec_manager/orchestration/implementation/runner.py` — Implementation runner
  Check against: Section 9.1 ("Build" is IMPLEMENT step inside each phase)

- `scripts/spec_manager/spec_manager/orchestration/pattern_library.py` — Pattern library
  Check against: Section 7 (contract patterns: EVENT_FLOW, DI_BINDING, MIDDLEWARE_ORDERING)

### Group 4: Orchestration - Demotion
These modules implement Section 11 of the proposal.

- `scripts/spec_manager/spec_manager/orchestration/demotion/__init__.py` — Demotion overview
  Check against: Section 11 (no backtracking, classification for routing only)

- `scripts/spec_manager/spec_manager/orchestration/demotion/router.py` — Demotion router
  Check against: Section 11 (phase-context-dependent authority, block vs proceed)

- `scripts/spec_manager/spec_manager/orchestration/demotion/triage.py` — Demotion triage
  Check against: Section 11 (authority classification per phase, block when outside authority)

### Group 5: Orchestration - Review & Coordination
These modules implement Sections 8, 9, and 13 of the proposal.

- `scripts/spec_manager/spec_manager/orchestration/review/findings_to_tickets.py` — Findings conversion
  Check against: Section 8 (work item routing), 11 (authority-based routing), 13.2/13.3 (LLM authority constraint)

- `scripts/spec_manager/spec_manager/orchestration/coordination/work_items.py` — Work items
  Check against: Section 8.1 (work item structure), 8.2 (routing mechanism)

- `scripts/spec_manager/spec_manager/orchestration/coordination/monitors.py` — Coordination monitors
  Check against: Section 9.5 (iteration bounds, stagnation), 9.6 (convergence criteria)

- `scripts/spec_manager/spec_manager/orchestration/coordination/monitor_executor.py` — Monitor executor
  Check against: Section 9.5 (bounds enforcement), 9.6 (per-phase convergence)

### Group 6: Planner (Phase-specific behaviors)
These modules implement Section 9.1-9.3 of the proposal (phase authority and behaviors).

- `scripts/spec_manager/spec_manager/planner/api.py` — Planner API
  Check against: Section 9 (phase-aware planning)

- `scripts/spec_manager/spec_manager/planner/router.py` — Planner routing
  Check against: Section 9 (phase dispatch)

- `scripts/spec_manager/spec_manager/planner/layers/l1.py` — Libraries phase planner
  Check against: Section 9.1 (Libraries = L1-equivalent), 9.2 (skeleton), 9.3 (full authority), 9.4 (Phase 0 inputs)

- `scripts/spec_manager/spec_manager/planner/layers/l2.py` — Architecture phase planner
  Check against: Section 9.3 (Architecture authority: wiring + in-place algorithm edits, block on library boundary changes)

- `scripts/spec_manager/spec_manager/planner/layers/l3.py` — Quality phase planner
  Check against: Section 9.3 (Quality authority: refactor only, block on behavior change)

- `scripts/spec_manager/spec_manager/planner/strategies/architecture_strategy.py` — Architecture strategy
  Check against: Section 9.3 (Architecture can edit algorithms in-place within library boundaries, blocks otherwise)

### Group 7: Projection & Evaluation
These modules implement Sections 6, 13, and 14 of the proposal.

- `scripts/spec_manager/spec_manager/projection/lineage/builder.py` — Import scanning/lineage
  Check against: Section 6.1 (observed structure sources), 13.1 (deterministic extraction)

- `scripts/spec_manager/spec_manager/refinement/evals/metrics.py` — Eval metrics
  Check against: Section 14 (evaluation success/failure criteria)

- `scripts/spec_manager/spec_manager/refinement/evals/runner.py` — Eval runner
  Check against: Section 14 (A/B experiment design, validation approach)

## CRITICAL rules for your audit

1. **Substance over structure.** Don't flag formatting or phrasing differences. Flag
   differences in MEANING — does the block describe the wrong behavior, wrong authority
   boundary, wrong routing logic, wrong convergence criteria?

2. **Proposal is authoritative.** If the ALGORITHM block says something the proposal
   doesn't address, that's only a problem if it CONTRADICTS the proposal. Extra
   implementation detail that's consistent with the proposal is fine.

3. **Phase model correctness.** The 3-phase model is: Libraries → Architecture → Quality.
   Forward-only. No cycling back. No demotion to earlier phases. Each phase has its own
   PromotionLoop. "Build" is not a separate phase — it's the IMPLEMENT step.

4. **Authority boundaries matter most.** The most important alignment check is whether
   each module correctly describes what its phase CAN and CANNOT do (Section 9.3).

5. **LLM authority constraint.** LLM findings are advisory only — they cannot become
   hard gate results unless converted to deterministic verifier tasks (Section 13.2/13.3).
