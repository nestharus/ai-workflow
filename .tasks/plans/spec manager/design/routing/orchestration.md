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

* `PddLifecycle(manager, mode='interactive', *, use_research=False,
  use_evidence_store=False, steering_path: Path | None = None,
  max_refinement_iterations: int = 5, worktree_manager: WorktreeManager
  | None = None, max_approval_iterations: int = 3, max_demotions_per_layer:
  int = 50, max_pipeline_passes: int = 2, model_profile: Any = None,
  user_input_fn: Callable[[str], str] | None = None).run() -> dict` — full
  pipeline
* `PddLifecycle.qa() -> dict` — QA eval framework

**Dependencies**: `pdd_orchestrator`, `promotion_loop`, `promotion_scheduler`,
`planner.api`, `refinement.workspace`, `orchestration.run_state`,
`orchestration.source_analysis_cache`, `orchestration.demotion`,
`orchestration.coordination`

**Consumers**: CLI entry point

### Intent Agent Orchestrator

**Module**: `spec_manager/orchestration/intent_agent/agent.py`
**Purpose**: User-facing interaction loop that owns question ingestion, queue
management, deterministic resume, quality-gated follow-ups, and pre-decomposition
skeleton generation, queue reassessment, and planner-update-driven reconciliation.

**Surface API**:

* `IntentAgentOrchestrator(run_dir, mode, run_agent, ... )`
* `resume() -> QuestionItem | None`
* `handle_user_message(text)`, `handle_answer(question_id, raw_text,
  selected_choice_id)`
* `handle_vague_input(text)`, `handle_redefinition(trigger)`
* `ingest_signal(signal)` and `handle_planner_updates()` (mechanical pass +
  reassess)
* `produce_skeleton() -> list[Path] | None`
* `next_action() -> dict[str, Any]`
* `save_state()`

**Dependencies**: `intent_agent.queue`, `intent_agent.signals`,
`intent_agent.skeleton`, `intent_agent.state`, `intent_agent.quality_gate`,
`intent_agent.answer_translation`, `planner.api`

**Consumers**: `pdd_lifecycle` for interactive checkpoints, Planner callback for
answer ingestion

### Response2 subcomponents

* `intent_agent/signals.py` stores and reads `coordination/user_questions.jsonl`.
* `intent_agent/queue.py` handles prioritization, dedupe, persistence, and
  reassessment.
* `intent_agent/taxonomy.py` classifies/reframes signal types for user-safe flow.
* `intent_agent/quality_gate.py` validates/repairs candidates before enqueue or
  enqueue-follow-ups.
* `intent_agent/answer_translation.py` produces projection artifacts for planner
  ingest.
* `intent_agent/state.py` persists session/event state and watermarks.
* `intent_agent/skeleton.py` renders and updates `intent` snapshots.

**Current status notes**:

* The orchestration surface is implemented, but audits report remaining TODO debt
  in queue/quality/skeleton files and partial execution paths in reassessment and
  answer-trigger replay.
* `next_action()` currently asks one question (`next_question()`) by default while
  `next_batch()` remains unused in the main flow.
* Planner updates are consumed on resume/update cycles; direct answer paths do not
  always trigger immediate reassessment.

### Response2 interaction boundary

The user-question bridge follows this concrete flow:

1. Lifecycle or under-spec components emit `UserQuestionSignal` records.
2. Signals are persisted to `coordination/user_questions.jsonl`.
3. Intent resume/poll reads unresolved signals by watermark and updates the queue.
4. `spec-manager intent questions` reads queue state and `spec-manager intent
   answer` routes answer text to `handle_answer`.
5. Planner callbacks persist constraints/decisions and emit
   `coordination/planner_updates.jsonl`.
6. Intent reads planner updates by watermark and runs reassessment.

The response2-aligned implementation currently has two notable caveats:

* Signal schema handling in practice allows `INTENT_AGENT` source kind, while
  runtime documentation only partially constrains the source enum.
* `SLICE_AGENT` appears in source enums but has no confirmed emitter path in
  current orchestration.

### PDD Orchestrator

**Module**: `pdd_orchestrator.py`
**Purpose**: Individual PDD phase execution (P0-P10).

**Surface API**:

* `PddOrchestrator(workspace).run(start_phase=None, end_phase=None, *,
  stop_on_failure=True, mode='loop'|'pipeline') -> dict`
* `PddOrchestrator.run_phase(phase) -> dict`
* `PddOrchestrator.run_loop(*, max_iterations=20, run_extraction=True) -> dict`

**Dependencies**: `refinement.workspace`, `core.agent_utils`

**Consumers**: `pdd_lifecycle`

### Promotion Loop

**Module**: `promotion_loop.py`
**Purpose**: 10-step state machine per slice (`COLLECT_BASELINE` →
`GAP_EXPLORATION` → `PLAN` → `IMPLEMENT` → `COORDINATE` (under-spec checkpoint)
→ `ANALYZE` → `PROMOTE` → `INTEGRATE` → `VERIFY` → `ALIGN`).

**Surface API**:

* `PromotionLoop(...).run_slice(slice_ref, run_context) -> SliceResult`
* `PromotionLoop.run_slices(slice_refs, run_context) -> list[SliceResult]`
* Step classes: `CollectBaselineStep`, `GapExplorationStep`, `PlanStep`,
  `ImplementStep`, `CoordinateStep`, `AnalyzeStep`, `PromoteStep`,
  `IntegrateStep`, `VerifyStep`, `AlignStep`
* Slice terminal statuses: `OK`, `RETRY`, `WAITING`, `BLOCKED`, `FAIL`,
  `MAX_ITERATIONS`, `STAGNATED`, `COMPLETE`

**Dependencies**: `planner`, `compliance.promotion`, `compliance.detection`,
`orchestration.evidence`, `orchestration.coordination`, `orchestration.demotion`,
`orchestration.downward_flow`, `orchestration.under_spec`, `refinement.workspace`

**Consumers**: `pdd_lifecycle`

### Coordination

**Module**: `coordination/` (6 modules)

**Purpose**: Cross-slice signals, work items, wake queues, wait graphs, monitors.

**Surface API**:

* `CoordinationSignal` — structured halt notification
* `WorkItemStore` — JSONL + index, 3-stage search
* `WakeQueue` — file-based wake events
* `WaitGraph` — dependency edges with cycle detection
* `MonitorSpec` + `MonitorRegistry` — declarative JSON DSL
* `ConditionChecker` + `MonitorExecutor` — hybrid poll + event condition
  checking (including `user_question_answered`)

**Dependencies**: `coordination.monitors`, `coordination.signals`,
`coordination.wake_queue`, `coordination.work_items`, `coordination.wait_graph`
and external constraint/work-item stores

**Consumers**: `promotion_loop.CoordinateStep`, `planner.api` (TRIAGE_SIGNAL),
`promotion_scheduler`

### Promotion Scheduler

**Module**: `promotion_scheduler.py`
**Purpose**: Parallel slice scheduling with ThreadPoolExecutor. Reactive scheduling
with WAITING support and monitor thread.

**Surface API**:

* `ReactivePromotionScheduler(loop, config).run(slices, run_context) ->
  ScheduleResult`

**Dependencies**: `coordination.wake_queue`, `coordination.monitors`

**Consumers**: `pdd_lifecycle`

### Evidence

**Module**: `evidence.py`
**Purpose**: Per-slice iteration artifacts. Immutable audit trail.

**Surface API**:

* `EvidenceBundle` — container with `Finding` instances and 18+ `Ref` sub-types
* `EvidenceBundle.add_finding()`, `.get_findings()`, `.get_refs()`

**Dependencies**: None (data structure)

**Consumers**: All promotion loop steps, compliance gates, reporters

### Implementation

**Module**: `implementation/` (runner + types)
**Purpose**: P9 code generation. Emits CoordinationSignals for under-spec.

**Surface API**:

* `ImplementationRunner(config).run(bundle) -> ImplementorOutput`

**Dependencies**: `core.agent_utils`, `coordination.signals`

**Consumers**: `promotion_loop.ImplementStep`

### Demotion

**Module**: `demotion/` (ticket, triage, router, ledger)
**Purpose**: Gate failure → triage → route to correct layer → produce patches.

**Surface API**:

* `DemotionTicket` — failure record
* `triage(ticket) -> TriageResult` — classify by priority
* `DemotionRouter.route(ticket) -> Layer` — route to L1/L2/L3
* `DemotionLedger` — persistent record

**Dependencies**: `compliance.promotion`

**Consumers**: `promotion_loop.PromoteStep`

### Under-Spec

**Module**: `under_spec/` (manager, planning_gate)
**Purpose**: Hard-stop blocking for under-specified work.

**Surface API**:

* `UnderSpecManager.resolve(slice_id, events, layer) -> dict`
* `PlanningGate.check_decision_coverage() -> bool`

**Dependencies**: `planner.api` (injectable)

**Consumers**: `promotion_loop.CoordinateStep`, `planner.constraints`

**Note**: `Constraint` and `ConstraintsStore` now live in
`planner/constraints/store.py`; the blocking manager stays here.

### Architecture

**Module**: `architecture/` (assembler)
**Purpose**: L2 service assembly from promoted L1 atoms. Reads pin registry +
adjacency, calls LLM.

**Surface API**:

* `ArchitectureAssembler.assemble(atoms, pins) -> ProjectionProposals`

**Dependencies**: `pin_functions`, `analysis.adjacency`, `core.agent_utils`

**Consumers**: `promotion_loop.IntegrateStep` (L2)

### Downward Flow

**Module**: `downward_flow/engine.py`
**Purpose**: Test failure root cause tracing through pin graph → demotion tickets.

**Surface API**:

* `DownwardFlowEngine.trace(failure) -> list[DemotionTicket]`

**Dependencies**: `core.pin_registry`, `demotion`

**Consumers**: `promotion_loop` (on test failure)

### Run State & Infra

**Modules**: `run_state.py`, `source_analysis_cache.py`, `review/`
**Purpose**: Run config + metadata, SHA-256 keyed analysis cache, review findings.

**Surface API**:

* `RunConfig`, `RunState`, `RunStateManager`
* `SourceAnalysisCache` — SHA-256 keyed

**Dependencies**: `core`

**Consumers**: `pdd_lifecycle`, `promotion_loop`

**Note**: Scoring, quality, digests, reports, multi-model, comparison, model profiles,
cost ledger, and snapshot moved to `evaluation/`. VCS and worktree management moved
to `vcs/` with compatibility re-exports in `orchestration/vcs.py` and
`orchestration/worktree_manager.py`.
