# Planner

**Classification**: Business (decision authority)
**Package**: `spec_manager/planner/`
**Files**: 14 + sub-packages
**Role**: Single auto-mode decision authority across the spec manager lifecycle. Routes planning requests to layer-specific planners.

---

## Systems

### Planner API
**Modules**: `api.py`, `router.py`
**Purpose**: Routes `PlanningRequest` to layer planners (L1/L2/L3) via `LayerRouter`, dispatches by capability via `CapabilityRouter`. Every invocation traced.
**Surface API**:
- `Planner(workspace_root, mode, register_defaults, research_tool, integration_tool, evidence_tool, constraints_tool, override_provider, model_id, work_item_store, wait_graph)`
- `plan(request: PlanningRequest) -> PlanningResult`
- `resolve_signal(signal, context) -> Any`
- `plan_from_gaps(context, gaps) -> list[dict]`
- `resolve_under_spec(context, events) -> dict`
- `triage_signal(context, signal) -> PlanningResult`
- Capabilities: `GAP`, `PLAN`, `UNDER_SPEC`, `RESOLVE_SIGNAL`, `INTEGRATION_ANALYSIS`, `TRIAGE_SIGNAL`
- Status values: `OK`, `BLOCKED`, `NEEDS_INPUT`, `NOOP`, `ERROR`, `WAITING`
**Dependencies**: `planner.layers`, `planner.trace`, `planner.constraints.store_adapter`
**Consumers**: All promotion loop steps, `orchestration.pdd_lifecycle`

### Layer Planners
**Module**: `layers/` (l1.py, l2.py, l3.py)
**Purpose**: Per-layer specialized planning. Each satisfies `LayerPlanner` protocol.

**L1Planner** (code-as-spec):
- `discover(ctx)` — scan workspace for spec-comment functions
- `build_plan(ctx, gaps, discovery)` — function intentions (L1 PLAN = spec comments ARE the plan)
- `triage_signal(ctx, signal)` — search work items → classify → route/expand → schedule monitor
- Uses strategy pipeline when `constraints_store_adapter` provided

**L2Planner** (architecture topology):
- `discover(ctx)` — scan for arch files (manifests, pins, wiring, entrypoints)
- `build_plan(ctx, gaps, discovery)` — wiring intentions via strategy pipeline
- `resolve_under_spec(ctx, events, discovery)` — evidence lookup → block
- `triage_signal(ctx, signal)` — returns NOOP (defers to L1)

**L3Planner** (quality graph):
- `discover(ctx)` — quality metrics for workspace files
- `build_plan(ctx, gaps, discovery)` — refactor intentions
- Focus on code quality, not algorithmic or architectural correctness

**Dependencies**: `planner.tools`, `planner.strategies`, `planner.constraints`, `compliance.detection`
**Consumers**: `planner.router` (CapabilityRouter)

### Tools
**Module**: `tools/` (research_tool, integration_tool, constraints_tool, evidence_tool)
**Purpose**: Adapters over existing spec_manager subsystems. Provides tool interface for LLM context injection.
**Surface API**:
- `ResearchTool` → `refinement.interactive.research.ResearchCoordinator`
- `IntegrationTool` → `orchestration.source_analysis_cache`
- `ConstraintsTool` → `orchestration.under_spec.ConstraintsStore`
- `EvidenceTool` → `refinement.hollowed_spec.searcher`
**Dependencies**: `refinement`, `orchestration`, `core`
**Consumers**: Layer planners (L1, L2, L3)

### JIT State Machine
**Module**: `jit/` (state_machine.py, actions.py)
**Purpose**: Micro-state-machine for just-in-time planning. Tracks planner state across iterations, enables WAITING status.
**Surface API**:
- `PlannerStateMachine.transition(event) -> NextAction`
- States: `READY`, `WAITING`, `BLOCKED`, `RESOLVED`
**Dependencies**: `orchestration.coordination.monitors`
**Consumers**: `orchestration.promotion_scheduler`

### Constraints
**Module**: `constraints/` (types, store_adapter, bootstrap, impact, authority)
**Purpose**: Constraint lifecycle management. Models constraints as first-class objects, classifies impact, checks decision authority.
**Surface API**:
- `ConstraintFact`, `ConstraintHypothesis`, `DecisionRequirement`, `ImpactClassification`
- `ConstraintStoreAdapter.load_merged(slice_id) -> list[ConstraintFact]`
- `ConstraintStoreAdapter.save_facts(slice_id, facts)`
- `bootstrap_constraints_from_intake(workspace_root, libraries_dir)`
- `classify_impact(layer, gap_kinds, ...) -> ImpactClassification`
- `check_authority(impact, ...) -> "planner_ok" | "human_required"`
**Dependencies**: `orchestration.under_spec.ConstraintsStore`
**Consumers**: Layer planners, `planner.strategies`

### Strategies (Planning Session Pipeline)
**Module**: `strategies/` (protocol, constraint_strategies, architecture_strategy, authority_strategy)
**Purpose**: Sequential strategy pipeline for L2 planning. Each strategy enriches a `PlanningSession`.
**Surface API**:
- `PlanningSession` — mutable session state (gaps, discovery, impact, constraints, intentions, etc.)
- `PlanningSessionRunner(strategies).run(session) -> PlanningSession`
- Strategies: `ImpactClassifierStrategy`, `ConstraintCollectionStrategy`, `TradeoffMapperStrategy`, `ProblemFramerStrategy`, `ConstraintEnricherStrategy`, `NonSoftwareChecklistStrategy`, `ArchitecturePlannerStrategy`, `AuthorityDeciderStrategy`, `QuestionComposerStrategy`
**Dependencies**: `planner.constraints`, `planner.architecture`
**Consumers**: `L2Planner.build_plan()`

### Architecture (Decision Planning)
**Module**: `architecture/` (types, decision_detector, proposer, evaluator, artifacts)
**Purpose**: Decision-point-driven architecture planning. Detects decisions, proposes K candidates, evaluates against constraints, persists artifacts.
**Surface API**:
- `DecisionPoint`, `ScopePacket`, `ArchitectureCandidate`, `CandidateAssessment`, `DecisionOutcome`
- `DecisionPointDetector.detect(slice_id, gaps, discovery, constraints) -> list[DecisionPoint]`
- `ProposerOrchestrator.run_proposers(dp, scope_packet) -> list[ArchitectureCandidate]`
- `CandidateEvaluator.evaluate(candidates, constraints) -> list[CandidateAssessment]`
- `persist_decision_artifacts(workspace_root, run_id, decision_id, ...)`
**Dependencies**: `planner.constraints.types`, `core.agent_utils`
**Consumers**: `ArchitecturePlannerStrategy`

### Trace
**Module**: `trace.py`
**Purpose**: Observability. Every planner invocation persists a trace with decision records.
**Surface API**:
- `PlannerTrace.start(trace_id, snapshot, ...) -> PlannerTrace`
- `PlannerTrace.persist(workspace_root)`
- `DecisionRecord` — decision text + artifacts
- `compute_decision_key()` — deterministic key for dedup
- Index: `index.jsonl` (append-only)
**Dependencies**: None
**Consumers**: `planner.api.Planner`
