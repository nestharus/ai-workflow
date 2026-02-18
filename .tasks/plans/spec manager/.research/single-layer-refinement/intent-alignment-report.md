# Intent Alignment Audit: `ALGORITHM(single-layer)` vs `proposal.md`

## Group 1: Routing (Sections 3-6, 8)
- `scripts/spec_manager/spec_manager/routing/__init__.py`: **ALIGNED** — The block correctly positions this module as the routing API surface for shapes/matcher/verifiers used across forward-only phases and work-item generation.
- `scripts/spec_manager/spec_manager/routing/shapes.py`: **ALIGNED** — The block matches proposal intent on shape format, controlled storage/derivation, ownership resolution, and per-phase skeleton lifecycle handling of draft vs active shapes.
- `scripts/spec_manager/spec_manager/routing/matcher.py`: **ALIGNED** — The block reflects deterministic matching outputs/rules, routing of drift/contract failures to work items, and call graph use as hint-before-classification/internal representation rather than convergence authority.
- `scripts/spec_manager/spec_manager/routing/verifiers.py`: **ALIGNED** — The block aligns with verifier-backed contracts and phase-specific deterministic verification as the hard convergence authority.

## Group 2: Compliance/Promotion (Section 10)
- `scripts/spec_manager/spec_manager/compliance/promotion/__init__.py`: **ALIGNED** — The block correctly reframes exports around phase/aspect gates and removes layer/pin framing without introducing compatibility shims.
- `scripts/spec_manager/spec_manager/compliance/promotion/config.py`: **MISALIGNED** — It states `Gate-to-phase mapping: each gate belongs to exactly one of the three phases.`, which contradicts proposal §10.1 that explicitly requires some hard gates (for example `ALL_TESTS_PASS` and contract verifiers) to run in multiple phases via gate→phase-list mapping.
- `scripts/spec_manager/spec_manager/compliance/promotion/algorithmic_gates.py`: **ALIGNED** — The block matches §10.2 mapping by keeping deterministic test authority hard while converting call-graph connectivity and stub checks to soft/advisory signals.
- `scripts/spec_manager/spec_manager/compliance/promotion/architectural_quality.py`: **ALIGNED** — The block follows architecture-phase gate intent by replacing pin-dependent checks with shape drift/import-boundary/contract-verifier-backed checks.
- `scripts/spec_manager/spec_manager/compliance/promotion/introduction_checker.py`: **ALIGNED** — The block is consistent with surviving deterministic checks and the rule that LLM assistance can inform diagnostics but not hard pass/fail authority.
- `scripts/spec_manager/spec_manager/compliance/promotion/orchestrator.py`: **ALIGNED** — The block matches phase-based aspect gate execution, hard vs soft separation, and deterministic-only authority for non-ship/convergence decisions.
- `scripts/spec_manager/spec_manager/compliance/promotion/provenance.py`: **INCOMPLETE** — Missing explicit extraction-boundary handling from proposal §§13.1-13.3: it should state that provenance evidence used for hard gating must be deterministic, while LLM-origin evidence remains advisory metadata only.

## Group 3: Orchestration (Sections 9, 11)
- `scripts/spec_manager/spec_manager/orchestration/run_state.py`: **ALIGNED** — The block aligns with forward-only phases plus explicit iteration/stagnation state needed for bounded per-phase convergence.
- `scripts/spec_manager/spec_manager/orchestration/pdd_lifecycle.py`: **ALIGNED** — The block matches phase order, skeleton lifecycle, Phase 0 outputs, phase-local authority/blocking, and deterministic bounded convergence criteria.
- `scripts/spec_manager/spec_manager/orchestration/pdd_orchestrator.py`: **ALIGNED** — The block reflects Phase 0 bootstrap artifacts and removal of legacy pin/layer phase paths consistent with the simplification inventory.
- `scripts/spec_manager/spec_manager/orchestration/promotion_loop.py`: **ALIGNED** — The block correctly preserves the loop machine while making IMPLEMENT active in all phases and enforcing authority-based block-not-demote behavior.
- `scripts/spec_manager/spec_manager/orchestration/implementation/runner.py`: **ALIGNED** — The block matches proposal intent that “Build” is the IMPLEMENT step inside each phase and therefore executable across Libraries/Architecture/Quality.
- `scripts/spec_manager/spec_manager/orchestration/pattern_library.py`: **ALIGNED** — The block aligns with Section 7 by modeling EVENT_FLOW/DI_BINDING/MIDDLEWARE_ORDERING as verifier-backed contract templates.

## Group 4: Orchestration - Demotion (Section 11)
- `scripts/spec_manager/spec_manager/orchestration/demotion/__init__.py`: **ALIGNED** — The block correctly removes demotion-as-backtracking and retains only phase-context classification for queue-in-phase vs block decisions.
- `scripts/spec_manager/spec_manager/orchestration/demotion/router.py`: **ALIGNED** — The block matches deterministic owner-shape routing followed by phase-authority triage and block-not-reroute behavior.
- `scripts/spec_manager/spec_manager/orchestration/demotion/triage.py`: **ALIGNED** — The block mirrors the proposal’s phase-context-dependent authority matrix, including Architecture in-place behavior remediation and Quality behavior-change blocking.

## Group 5: Orchestration - Review & Coordination (Sections 8, 9, 13)
- `scripts/spec_manager/spec_manager/orchestration/review/findings_to_tickets.py`: **ALIGNED** — The block is consistent with shape-based work-item routing, phase-authority triage, and LLM findings treated as advisory unless converted to deterministic verifier tasks.
- `scripts/spec_manager/spec_manager/orchestration/coordination/work_items.py`: **ALIGNED** — The block matches the external durable work-item model centered on `shape_id`, `required_change_type`, and active-phase authority routing.
- `scripts/spec_manager/spec_manager/orchestration/coordination/monitors.py`: **INCOMPLETE** — Missing key monitor concerns from §§9.5-9.6: explicit monitoring hooks/conditions for iteration caps, work-item cap pressure, stagnation-window exhaustion, and per-phase convergence completion criteria.
- `scripts/spec_manager/spec_manager/orchestration/coordination/monitor_executor.py`: **INCOMPLETE** — Missing execution-time enforcement for §§9.5-9.6 bounds/convergence signals (iteration/work-item limits and stagnation progression) beyond shape verifier/drift condition checks.

## Group 6: Planner (Sections 9.1-9.3)
- `scripts/spec_manager/spec_manager/planner/api.py`: **ALIGNED** — The block aligns with phase-aware planner dispatch over the three forward-only phases.
- `scripts/spec_manager/spec_manager/planner/router.py`: **ALIGNED** — The block correctly defines phase-based planner registration/selection while decoupling capability/model routing from phase dispatch.
- `scripts/spec_manager/spec_manager/planner/layers/l1.py`: **ALIGNED** — The block matches Libraries-phase behavior using Phase 0/skeleton-derived inputs and iterative work-item-driven planning.
- `scripts/spec_manager/spec_manager/planner/layers/l2.py`: **MISALIGNED** — The block’s `ArchitectureFinding: ... required_change_type: Literal['wiring_only','spec_change']` (and “Emits only allowed change types”) conflicts with proposal §9.3, which explicitly allows Architecture-phase `behavior_change` within existing library boundaries for in-place algorithm remediation.
- `scripts/spec_manager/spec_manager/planner/layers/l3.py`: **ALIGNED** — The block matches Quality authority as refactor-only with explicit blocking of behavior-changing work.
- `scripts/spec_manager/spec_manager/planner/strategies/architecture_strategy.py`: **ALIGNED** — The block aligns with Architecture authority to edit algorithms in place within fixed library boundaries and block boundary-changing decisions.

## Group 7: Projection & Evaluation (Sections 6, 13, 14)
- `scripts/spec_manager/spec_manager/projection/lineage/builder.py`: **ALIGNED** — The block follows deterministic import-scan-based observed-structure extraction and shape-level lineage construction without pin-registry authority.
- `scripts/spec_manager/spec_manager/refinement/evals/metrics.py`: **INCOMPLETE** — Missing explicit success-criterion coverage from §14.2 for spec-fidelity parity metrics (for example QA/judge pass-rate parity and dropped-requirement deltas), which are required alongside thrash and complexity reduction metrics.
- `scripts/spec_manager/spec_manager/refinement/evals/runner.py`: **ALIGNED** — The block matches §14 A/B design, fairness constraints, success/failure criteria, and proof-of-feasibility routing validation.
