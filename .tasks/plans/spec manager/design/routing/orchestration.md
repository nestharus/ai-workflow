# Orchestration

**Classification**: Structural (core pipeline)
**Package**: `spec_manager/orchestration/`
**Files**: 30
**Role**: Central coordinator of the PDD lifecycle. All work flows through here.

---

## Systems

### PDD Lifecycle
**Module**: `pdd_lifecycle.py`
**Purpose**: L1 → L2 → L3 layer pipeline. The ONLY top-level lifecycle controller.
**Surface API**:
- `PddLifecycle(manager, config).run() -> dict` — full pipeline
- `PddLifecycle.qa() -> dict` — QA eval framework
**Dependencies**: `pdd_orchestrator`, `promotion_loop`, `planner.api`, `refinement.workspace`
**Consumers**: CLI entry point

### PDD Orchestrator
**Module**: `pdd_orchestrator.py`
**Purpose**: Individual PDD phase execution (P0-P10).
**Surface API**:
- `PddOrchestrator(workspace, config).run_phase(phase) -> PhaseResult`
**Dependencies**: `refinement.workspace`, `core.agent_utils`
**Consumers**: `pdd_lifecycle`

### Promotion Loop
**Module**: `promotion_loop.py`
**Purpose**: 10-step state machine per slice (COLLECT → GAP → PLAN → IMPLEMENT → UNDER_SPEC → ANALYZE → PROMOTE → INTEGRATE → VERIFY → ALIGN).
**Surface API**:
- `PromotionLoop(config).run(slice_id, bundle) -> LoopResult`
- Step classes: `CollectStep`, `GapExplorationStep`, `PlanStep`, `ImplementStep`, `CoordinateStep`, `AnalyzeStep`, `PromoteStep`, `IntegrateStep`, `VerifyStep`, `AlignStep`
**Dependencies**: `planner.api`, `compliance.promotion`, `compliance.detection`, `orchestration.evidence`, `orchestration.coordination`
**Consumers**: `pdd_lifecycle`

### Coordination
**Module**: `coordination/` (6 modules)
**Purpose**: Cross-slice signals, work items, wake queues, wait graphs, monitors.
**Surface API**:
- `CoordinationSignal` — structured halt notification
- `WorkItemStore` — JSONL + index, 3-stage search
- `WakeQueue` — file-based wake events
- `WaitGraph` — dependency edges with cycle detection
- `MonitorSpec` + `MonitorRegistry` — declarative JSON DSL
- `MonitorExecutor` — hybrid poll + event condition checking
**Dependencies**: None (self-contained)
**Consumers**: `promotion_loop.CoordinateStep`, `planner.api` (TRIAGE_SIGNAL), `promotion_scheduler`

### Promotion Scheduler
**Module**: `promotion_scheduler.py`
**Purpose**: Parallel slice scheduling with ThreadPoolExecutor. Reactive scheduling with WAITING support and monitor thread.
**Surface API**:
- `ReactivePromotionScheduler(config).schedule(slices) -> ScheduleResult`
**Dependencies**: `coordination.wake_queue`, `coordination.monitors`
**Consumers**: `pdd_lifecycle`

### Evidence
**Module**: `evidence.py`
**Purpose**: Per-slice iteration artifacts. Immutable audit trail.
**Surface API**:
- `EvidenceBundle` — container with `Finding` instances and 18+ `Ref` sub-types
- `EvidenceBundle.add_finding()`, `.get_findings()`, `.get_refs()`
**Dependencies**: None (data structure)
**Consumers**: All promotion loop steps, compliance gates, reporters

### Implementation
**Module**: `implementation/` (runner + types)
**Purpose**: P9 code generation. Emits CoordinationSignals for under-spec.
**Surface API**:
- `ImplementationRunner(config).run(bundle) -> ImplementorOutput`
**Dependencies**: `core.agent_utils`, `coordination.signals`
**Consumers**: `promotion_loop.ImplementStep`

### Demotion
**Module**: `demotion/` (ticket, triage, router, ledger)
**Purpose**: Gate failure → triage → route to correct layer → produce patches.
**Surface API**:
- `DemotionTicket` — failure record
- `triage(ticket) -> TriageResult` — classify by priority
- `DemotionRouter.route(ticket) -> Layer` — route to L1/L2/L3
- `DemotionLedger` — persistent record
**Dependencies**: `compliance.promotion`
**Consumers**: `promotion_loop.PromoteStep`

### Under-Spec
**Module**: `under_spec/` (manager, planning_gate)
**Purpose**: Hard-stop blocking for under-specified work.
**Surface API**:
- `UnderSpecManager.resolve(slice_id, events, layer) -> dict`
- `PlanningGate.check_decision_coverage() -> bool`
**Dependencies**: `planner.api` (injectable)
**Consumers**: `promotion_loop.CoordinateStep`, `planner.constraints`
**Note**: `Constraint` and `ConstraintsStore` now live in `planner/constraints/store.py`; the blocking manager stays here.

### Architecture
**Module**: `architecture/` (assembler)
**Purpose**: L2 service assembly from promoted L1 atoms. Reads pin registry + adjacency, calls LLM.
**Surface API**:
- `ArchitectureAssembler.assemble(atoms, pins) -> ProjectionProposals`
**Dependencies**: `core.pin_registry`, `analysis.adjacency`, `core.agent_utils`
**Consumers**: `promotion_loop.IntegrateStep` (L2)

### Downward Flow
**Module**: `downward_flow/engine.py`
**Purpose**: Test failure root cause tracing through pin graph → demotion tickets.
**Surface API**:
- `DownwardFlowEngine.trace(failure) -> list[DemotionTicket]`
**Dependencies**: `core.pin_registry`, `demotion`
**Consumers**: `promotion_loop` (on test failure)

### Run State & Infra
**Modules**: `run_state.py`, `source_analysis_cache.py`, `review/`
**Purpose**: Run config + metadata, SHA-256 keyed analysis cache, review findings.
**Surface API**:
- `RunConfig`, `RunState`, `RunStateManager`
- `SourceAnalysisCache` — SHA-256 keyed
**Dependencies**: `core`
**Consumers**: `pdd_lifecycle`, `promotion_loop`
**Note**: Scoring, quality, digests, reports, multi-model, comparison, model profiles, cost ledger, and snapshot moved to `evaluation/`. VCS and worktree management moved to `vcs/`.
