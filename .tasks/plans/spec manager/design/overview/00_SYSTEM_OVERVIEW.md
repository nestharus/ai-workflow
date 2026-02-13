# System Overview

## What spec_manager Is

spec_manager is a multi-agent system that transforms specifications into
implemented code through iterative promotion across quality layers. It
implements Prototype Driven Development (PDD) — building code and spec in
parallel, where each phase produces something messy and the next phase
cleans it up.

The core insight: **code IS the spec**. PDD skeleton files (class/function
signatures with spec comments and `pass` bodies) are simultaneously the
structured specification and the code. When you "implement," you fill in the
same files that ARE the spec.

---

## Package Inventory

### Core Infrastructure

| Package | Purpose |
|---------|---------|
| `core/` | Shared utilities — edit_in_place, JSON extraction, code fence stripping |
| `schemas/` | Pydantic models and JSON schemas for all data structures |

### Intake Pipeline (Phase 0)

| Package | Purpose |
|---------|---------|
| `intake/` | 5-step routing pipeline: summarize, discover, route, coverage, assemble. **Sole owner of
  library decomposition and routing boundaries (Phase 0 ownership contract).** |
| `intake/quality/` | Library quality validator (5-dimension scoring) |

### PDD Modules (Phases 1-10)

| Package | Purpose |
|---------|---------|
| `comment_planning/` | Pseudocode insertion and reverse translation scaffolds |
| `decomposition/` | Spec decomposition helpers (isolated from active pipeline) |
| `compliance/` | Gap detection, promotion gating, entity coverage |
| `branches/` | Library collapse, atom extraction, promotion |
| `pin_functions/` | Pin-function scanning and orchestration |
| `analysis/` | Adjacency analysis, graph building, analysis generation |
| `projection/` | Lineage tracking, import graph, projection generation |
| `strategies/` | Strategy evolution pipeline |

### Orchestration

| Package | Purpose |
|---------|---------|
| `orchestration/` | PDD lifecycle, promotion loop, run state management |
| `orchestration/implementation/` | ImplementationRunner + types |
| `orchestration/under_spec/` | Under-specification blocking + planning gates |
| `orchestration/demotion/` | Demotion triage, routing, ledger |
| `orchestration/downward_flow/` | DownwardFlowEngine (pin tracing for demotion) |
| `orchestration/architecture/` | Architectural assembly agent |
| `orchestration/coordination/` | Agent coordination (signals, work items, monitors, wake queue, wait graph) |
| `orchestration/review/` | Review findings to demotion tickets |

### Planner

| Package | Purpose |
|---------|---------|
| `planner/` | Planning API, router, auto-persist, TRIAGE_SIGNAL |
| `planner/layers/` | L1, L2, L3 layer-specific planners |
| `planner/tools/` | Research, integration, constraints, evidence tools |
| `planner/jit/` | Micro-state-machine for planning decisions |

### Refinement & Workspace

| Package | Purpose |
|---------|---------|
| `refinement/` | Refinement engine (analysis-only, coupling/cohesion) |
| `refinement/workspace/` | WorkspaceManager, state management |
| `refinement/interactive/` | Interactive workflow, ambiguity resolution |
| `refinement/hollowed_spec/` | Hollowed-out spec evidence gathering |

### Eval Framework

| Package | Purpose |
|---------|---------|
| `evaluation/` | Quality/reporting/comparison orchestration |
| `evaluation/quality.py` | Blended scoring for spec + code quality |
| `evaluation/scoring.py` | Run-level hard gates + soft signals scorecard (`RunReporter`) |
| `evaluation/comparison.py` | Canonical alignment and pairwise model comparison |
| `evaluation/multi_model.py` | Multi-model generation runners |
| `evaluation/cost_ledger.py` | LLM call accounting |
| `evaluation/digests.py` | Architecture and code digests |
| `evaluation/snapshot.py` | Run snapshot for forensics |
| `evaluation/model_profile.py` | Role-based model routing |
| `evaluation/report.py` | End-of-run report generation |

### Quality & Comparison

| Package | Purpose |
|---------|---------|
| `evaluation/scoring.py` | RunReporter + Scorecard (5 hard gates, 11 soft signals) |
| `evaluation/quality.py` | QualityReporter + QualityScorecard |
| `evaluation/model_profile.py` | ModelProfile (role-based model routing) |
| `evaluation/cost_ledger.py` | CostLedger + LLMCallRecord |
| `evaluation/multi_model.py` | MultiModelRunner |
| `evaluation/comparison.py` | ComparisonRunner (canonical alignment + pairwise) |
| `evaluation/digests.py` | Architecture and code digest generation |
| `evaluation/snapshot.py` | Run snapshot creation |

### VCS & Worktrees

| Package | Purpose |
|---------|---------|
| `vcs/` | Git abstraction + worktree manager |
| `orchestration/vcs.py`<br/>`orchestration/worktree_manager.py` | Compatibility re-export paths for legacy imports |

---

## Data Flow

```text
                        External Spec (prose markdown)
                                    |
                            [Phase 0: Intake]
                        summarize -> discover ->
                        route -> coverage -> assemble
                                    |
                        PDD Skeleton Files (code-as-spec)
                                    |
                    +---------------+----------------+
                    |               |                |
                [L1: Build]   [L2: Arch]      [L3: Quality]
                per-library   per-component   per-file
                worktrees     assembly        refinement
                    |               |                |
                    +-------+-------+--------+-------+
                            |                |
                    [Promotion Loop]   [Demotion Chain]
                    10-step state      all the way down
                    machine per slice  to code-as-spec
                            |
                        [Main Branch]
                    Production-ready code
```

### Phase 0 (Optional): Raw Prose -> PDD Skeletons

Only runs when ownership or re-entry boundaries require it:

* Phase 0 runs when ownership re-entry is required:
  * Intake queue demand (`.pdd_intake_queue` has pending items),
  * No libraries exist for first-run decomposition,
  * `spec_snapshot/` signature changed since last recorded Phase 0 boundary,
  * `system/intent.md` signature changed since last Phase 0 boundary.

If no boundary trigger is set and existing libraries are present, processing
starts at L1 and treats Phase 0 outputs as existing decomposition authority.

Intent-driven boundary contract:

* `Lifecycle._evaluate_phase0_entry()` owns the re-entry decision.
* `intent/intent.md` signature drift is treated as an ownership trigger.
* Existing `libraries/` are treated as authoritative decomposition artifacts unless a
  trigger is active.

### L1: Code-as-Spec (Build Phase)

Working authority. Per-library worktrees. ImplementationRunner fills in
function bodies. CoordinateStep handles cross-slice dependencies. 5
compliance gates enforce quality before promotion.

### L2: Architecture (Assembly Phase)

Derived from L1 promotion via pin-functions. Assembles services, events,
middleware from promoted atoms. 8 LLM-evaluated gates.

### L3: Clean Code (Quality Phase)

Derived from L2 promotion. N quality reviewers enforce standards. Refactoring
must not change logic (logic changes trigger demotion to L1). Merges to main.

### Intent Agent ownership and lifecycle

The Intent Agent is the single user-facing interaction layer for unresolved
ambiguities.

* `IntentAgentOrchestrator` owns interactive queue state and deterministic resume.
* Queue state is persisted under:
  * `.pdd_runs/<run_id>/intent/session_state.json`
  * `.pdd_runs/<run_id>/intent/events.jsonl`
  * `.pdd_runs/<run_id>/intent/skeleton/analysis/intent/question_queue.json`
  * `.pdd_runs/<run_id>/intent/answers.jsonl`
  * `.pdd_runs/<run_id>/intent/answer_translations/<id>.json`
  * Resume flow:
  * Reads persisted state.
  * Replays new `UserQuestionSignal`s from
    `.pdd_runs/<run_id>/coordination/user_questions.jsonl`.
  * Replays new planner update events from
    `.pdd_runs/<run_id>/coordination/planner_updates.jsonl`.
* Interaction:
  * `next_action()` produces `ask`/`wait` action states.
  * `next_action()` currently routes through `next_question()` (single-question
    presentation) even though `QuestionQueue.next_batch()` exists.
  * Immediate ask preemption occurs for `BLOCKING` questions when the queue is
    empty or current context is `INFO`.
  * `handle_answer(...)` writes raw answers and translations, then sends a
    callback to planner ingest.
  * Ingestion returns `constraint_ids`/`decision_record_ids`; on success the
    queue can advance.
  * Direct `handle_answer()` does not trigger full planner-update reassessment in
    the same call; reassessment is guaranteed when the orchestrator resumes and
    reads planner-update watermarks.

### UserQuestionSignal ↔ planner_updates bridge

Signals and planner updates are two independent files:

* `coordination/user_questions.jsonl` — intent-facing questions produced by
  `UserQuestionSignal` events from planner, lifecycle, and promotion components.
* `coordination/planner_updates.jsonl` — append-only planner/intent events used for
  wake checks and reassessment (`constraint_saved`, `decision_recorded`).
* The Intent Agent consumes both streams using watermarks:
  * `UserQuestionSignalStore.read_since(uq_id)`
  * `PlannerUpdateStore.read_since(created_at)`
* The current runtime `UserQuestionSignal` schema allows `INTENT_AGENT` source in
  addition to documented source kinds, and `SLICE_AGENT` is defined as a target
  kind without a clear emitter path yet.

### `INGEST_USER_ANSWER` and decision-record persistence

`planner/api.py` exposes the `INGEST_USER_ANSWER` capability:

1) `IntentAgentOrchestrator` parses answer text into `AnswerTranslation`.
2) `Planner.ingest_user_answer()` validates and converts to `ConstraintFact`.
3) Constraints are written via the constraints store adapter.
4) Decision records are persisted in
   `analysis/decision_records/<slice_id>.json` under the workspace run.
5) Lifecycle append events for `constraint_saved` and `decision_recorded` are written
   to `coordination/planner_updates.jsonl`.

### Problem redefinition and phase transition lifecycle

`PddLifecycle` owns phase ownership and transition behavior:
* `_evaluate_phase0_entry()` decides re-entry from queue demand, missing libraries, missing
  prior phase0 state, snapshot change, and `system/intent.md` signature drift.
* Lifecycle emits `Problem redefinition` signals through the normal user-question bridge
  (`PDD_LIFECYCLE` source kind).
* Canonical checkpoint taxonomy includes:
  * `l1_approval` → `VALIDATION`
  * `l2_checkpoint` → `CONSTRAINT`
  * `release_signoff` → `TRADEOFF`
  * `l1_to_l2` / `transition_l1_l2` → `VALIDATION`
  * `l2_to_l3` / `transition_l2_l3` → `VALIDATION`

### Checkpoint/redefinition taxonomy and queue governance

* `Lifecycle` redefinition triggers map to:
  * `problem_redefinition`, `scope_redefinition` → `SCOPE`
  * `lifecycle_redefinition` → `VALIDATION`
  * `alignment_violation` → `TRADEOFF`
* Trigger taxonomy and canonical-key migration are applied before question generation
  and queue reassessment.

---

## Test Coverage

3255 tests across all packages (as of Feb 11, 2026). Includes:

* Unit tests per module
* Component tests for orchestration flows
* Eval framework tests with ground truth fixtures
* Coordination infrastructure tests (145+)
