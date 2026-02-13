# Pipeline Architecture

## PromotionLoop: 10-Step State Machine

Each slice (library at L1, component at L2, file at L3) is processed through
a 10-step state machine in `orchestration/promotion_loop.py`:

```text
COLLECT_BASELINE -> GAP_EXPLORATION -> PLAN -> IMPLEMENT -> COORDINATE
    -> ANALYZE -> PROMOTE -> INTEGRATE -> VERIFY -> ALIGN
    ^                                                                                              |
    +----------------------------------------------------------------------------------------------+
                                     (loop until all gaps closed)
```

### Step Details

| Step | What Happens | Output |
|------|-------------|--------|
| COLLECT_BASELINE | Gather current slice state (files, functions, comments) | SliceSnapshot |
| GAP_EXPLORATION | Find remaining work (unfilled spec comments, stubs, quality issues) | GapReport |
| PLAN | Decide what to implement next (function intentions, wiring, refactoring) | PlanningResult |
| IMPLEMENT | Execute the plan (write code, tests, artifacts) | ImplementorOutput |
| COORDINATE | Handle under-specifications (coordinate or block),
  monitor registration, WAITING escalation | Signals or monitor-triggered WAITING |
| ANALYZE | Parse what was written (source analysis, graph building) | AnalysisResult |
| PROMOTE | Check compliance gates (5 at L1, 8 at L2, quality at L3) | GateResult |
| INTEGRATE | Merge to clean worktree, run tests, rebase dirty on clean | IntegrationResult |
| VERIFY | Cross-library connections (P6), lineage (P7), governance | VerifyResult |
| ALIGN | POWER alignment check (spec-implementation drift detection) | AlignmentResult |

### Layer-Aware Step Dispatch

The PromotionLoop dispatches different implementations per layer:

| Step | L1 (Code-as-Spec) | L2 (Architecture) | L3 (Clean Code) |
|------|-------------------|-------------------|-----------------|
| GAP_EXPLORATION | P3 compliance scan | LLM architectural gaps | 5 quality reviewers |
| Plan | Function intentions (spec comments ARE the plan) | Wiring intentions | Refactor intentions |
| Implement | ImplementationRunner | Arch assembler | Clean-code refactorer |
| COORDINATE | CoordinateStep (signals -> triage -> WAITING) | UnderSpecManager (hard-stop block) | UnderSpecManager |
| Analyze | SourceAnalysisCache (SHA-256 keyed) | LLM arch graph | File metrics |
| Promote | 5 L1 gates (NO_REMAINING_COMMENTS, etc.) | 8 L2 gates (LLM-evaluated) | Quality gaps + diff-impact |
| Verify | Governance + lineage (P7) | Governance + topology (P6) | Governance + closure |
| Align | POWER alignment per slice | POWER alignment | POWER alignment |

---

## Layer Pipeline (pdd_lifecycle.py)

The `PddLifecycle` orchestrates the 3-layer pipeline:

```text
Phase 0 (optional)
    |
    v
L1: Code-as-Spec
    - Library refinement (entry)
    - Per-library PromotionLoop
    - Library refinement (exit)
    - Human approval checkpoint
    |
    v
L2: Architecture
    - Architectural refinement (entry)
    - Per-component PromotionLoop
    - Architectural refinement (exit)
    |
    v
L3: Clean Code
    - Code quality refinement (entry)
    - Per-file PromotionLoop
    - Code quality refinement (exit)
    - Merge to main
```

### Phase 0 Boundary Enforcement

`pdd_lifecycle._evaluate_phase0_entry()` owns Phase 0 re-entry before L1 starts.
The boundary contract is strict:

* intake queue indicates routing work is pending,
* libraries are not yet present,
* the spec snapshot signature changed since the last recorded checkpoint,
* `system/intent.md` changed since the last recorded checkpoint.

Trigger evaluation is persisted in `.pdd_runs/<run_id>/intake/phase0_state.json`
so re-entry is deterministic and auditable.

If no trigger is present, `_run_intake()` returns `SKIPPED` and orchestration
proceeds to L1 with existing `libraries/` as authoritative decomposition input.

If triggered, `_run_intake()` runs Phase 0 and records:

* `status` (`COMPLETED` | `FAILED` | `SKIPPED`),
* active triggers and boundary state fingerprints (`snapshot_signature`,
  `intent_signature`, `libraries_present`, `queue_count`).

### Layer Transitions

At each layer transition, the exiting layer's clean output is distributed to
the entering layer's dirty worktree. Transition refinement runs between layers
and can trigger demotion (rework at a lower layer) before creative work begins.

| Transition | Refinement | Can Demote To |
|------------|-----------|---------------|
| L1 -> L2 | Architectural refinement | L1 (algorithmic issues) |
| L2 -> L3 | Code quality refinement | L2 (arch issues), L1 (logic issues) |

---

## ReactivePromotionScheduler

The `ReactivePromotionScheduler` in `orchestration/promotion_scheduler.py`
manages concurrent slice processing:

* **ThreadPoolExecutor** with bounded `max_workers` for parallel slice
  execution
* **WAITING support**: Slices that hit cross-slice dependencies enter WAITING
  state and are re-evaluated when wake events arrive
* **Monitor thread**: Runs MonitorExecutor to check JIT monitor conditions
  and generate wake events
* **Wake events**: File-based WakeQueue survives process restart
* **Termination guards**: `max_idle_polls` and `max_wait_cycles` prevent
  infinite loops

---

## Coordination Infrastructure

Agent coordination for cross-slice dependencies
(`orchestration/coordination/`):

```text
Slice A hits under-spec         Slice B completes implementation
        |                                   |
        v                                   v
CoordinateStep                    ImplementationRunner
  emits CoordinationSignal          emits CoordinationSignal
  with SignalNeed                   with SignalProgress
        |                                   |
        v                                   v
WorkItemStore                      WorkItemStore
  creates WorkItem                   updates WorkItem
  with WAITING status                with COMPLETED status
        |                                   |
        v                                   v
WaitGraph                          WakeQueue
  records wait edge                  enqueues WakeEvent
  (cycle detection)                  (file-based, durable)
        |                                   |
        v                                   v
MonitorRegistry                    MonitorExecutor
  registers JIT monitor              checks conditions
  (declarative JSON DSL)             fires wake events
        |                                   |
        +-----------------------------------+
                        |
                        v
            ReactivePromotionScheduler
              re-evaluates WAITING slice
```

---

## Demotion Pipeline

When an issue cannot be resolved at the current layer:

```text
Issue at L3 (quality)
    |
    v
DemotionTriage (demotion/triage.py)
    - Classify: behavior_change -> L1, wiring_only -> L2, refactor_only -> fix
    - By category: LOGIC/SPEC -> L1, ARCH -> L2, STYLE -> L3
    - By gate: mapped per gate name
    - By source: TEST_FAILURE -> L1, REVIEW -> L3
    |
    v
DemotionRouter (demotion/router.py)
    - Route to target layer
    - Create DemotionTicket with target_layer
    |
    v
DemotionLedger (demotion/ledger.py)
    - Record demotion for audit trail
    |
    v
DownwardFlowEngine (downward_flow/engine.py)
    - Trace pins from L2 back to L1 atoms
    - Identify exact function to fix
    |
    v
Fix at L1 -> re-promote through ALL gates -> back to L2 -> L3
```

---

## Planner Architecture

### Response2 Feedback Loop (Intent↔Planner authority)

The response2 interaction contract is implemented through the lifecycle-intent-planner
closure loop:

1. Lifecycle and under-spec/promotion emit `UserQuestionSignal` records into
   `coordination/user_questions.jsonl`.
2. `IntentAgentOrchestrator.resume()` loads persisted state, replays new signals by
   watermark, classifies/reframes, runs quality checks, and enqueues questions.
3. CLI entrypoints (`spec-manager intent questions` / `spec-manager intent answer`)
   call orchestrator methods for deterministic question presentation and answer handling.
4. `handle_answer()` produces `AnswerTranslation` and invokes planner ingest through
   lifecycle callback wiring.
5. Planner writes authoritative constraints/decisions and emits
   `coordination/planner_updates.jsonl` events.
6. Intent replay consumes update watermarks, updates question keys, and reassesses
   queue state.

Current implementation notes:
* The planning ingest path is authoritative, while intent artifacts (`answers`,
  `answer_translations`, `question_queue`) remain interface/state projections.
* `next_action()` returns one question via `next_question()`; batched presentation
  (`next_batch()`) is not wired into the default action path.
* Planner-induced reassessment is reliably replayed on resume/update cycles and is
  not immediate in all direct answer paths.

### Intention-boundary artifacts and stream alignment

* User-question stream: `coordination/user_questions.jsonl`.
* Planner-update stream: `coordination/planner_updates.jsonl`.
* Intent queue snapshot: `intent/skeleton/analysis/intent/question_queue.json`.
* Planner-update and user-question stream consumers use independent watermarks
  inside intent state.

The `Planner` in `planner/api.py` is the single auto-mode decision authority:

* **CapabilityRouter**: Routes planning requests by capability
  (TRIAGE_SIGNAL, RESEARCH, INTEGRATION, CONSTRAINTS, EVIDENCE)
* **LayerRouter**: Routes by layer (L1Planner, L2Planner, L3Planner)
* **TRIAGE_SIGNAL**: Search work items -> classify -> route/expand ->
  schedule monitor
* **PlannerTrace**: Records DecisionRecords with compute_decision_key for
  eval framework
* **Tools**: ResearchTool (wired to ResearchCoordinator), IntegrationTool
  (wired to SourceAnalysisCache), ConstraintsTool, EvidenceTool
* **Auto-persist**: Planning results automatically persisted to workspace
