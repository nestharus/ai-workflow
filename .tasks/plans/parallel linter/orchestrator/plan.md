# Parallel Lint-Fixer Orchestrator Execution Plan

Sources: [requirements.md](requirements.md) | [design-map.md](design-map.md) | [plan structure](../../processes/plan.md)

This document is an execution plan (work ordering only). Design topology (components, contracts) is defined in [design-map.md](design-map.md).

---

## PHASE-01 — State Layer Foundations

Goal: (GOAL-02, GOAL-03, GOAL-04, GOAL-05)
Scope: (ALG-00, ALG-01, ALG-02, ALG-03, ALG-04, ALG-05, ALG-06)
Depends-on: ()
Decisions: ()

### MILE-01 — Shared types + core stores

Produces: (COM-01, COM-02, COM-03)
Validated-by: (TEST-02)
Implements: (COM-01, COM-02, COM-03)
Decisions: ()

#### TASK-01 — Implement shared data types

Implements: (ALG-00)
Satisfies: (INV-01, INV-04)
Validated-by: (TEST-02)
Depends-on: ()
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/types.py` |
| create | `scripts/lint_fixer/state/__init__.py` |
| create | `scripts/lint_fixer/policy/__init__.py` |
| create | `scripts/lint_fixer/workflow/__init__.py` |

##### Acceptance Criteria

- [ ] Shared data types exist and are imported by all new components (ALG-00, INV-01)
- [ ] Layer packages exist for state/policy/workflow modules
- [ ] CAS-related types are usable by ChangeTracker and workflows (INV-04)
- [ ] Validation artifacts exist: (TEST-02)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/architecture.md](components/architecture.md)

---

#### TASK-02 — Implement DiagnosticStore

Implements: (COM-01, ALG-01)
Satisfies: (INV-01, INV-02)
Validated-by: (TEST-02)
Depends-on: (TASK-01)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/state/diagnostic_store.py` |

##### Acceptance Criteria

- [ ] Diagnostics ingestion preserves locked targets and unlintable targets (INV-02)
- [ ] Query helpers exist for actionable errors/targets (PROC-01)
- [ ] Validation artifacts exist: (TEST-02)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-01-diagnostic-store.md](components/com-01-diagnostic-store.md)

---

#### TASK-03 — Implement TargetStatusStore

Implements: (COM-02, ALG-02)
Satisfies: (INV-01, INV-03)
Validated-by: (TEST-02)
Depends-on: (TASK-01)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/state/target_status_store.py` |

##### Acceptance Criteria

- [ ] Project unlintable state can be detected and forces abort in orchestrator (INV-03)
- [ ] Passed cache supports per-file linter tracking (GOAL-04)
- [ ] Dirty targets can be marked/cleared and surfaced for actionability/termination gating (PROC-06, PROC-13)
- [ ] Validation artifacts exist: (TEST-02)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-02-target-status-store.md](components/com-02-target-status-store.md)

---

#### TASK-04 — Implement ChangeTracker

Implements: (COM-03, ALG-03)
Satisfies: (INV-01, INV-04)
Validated-by: (TEST-02)
Depends-on: (TASK-01)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/state/change_tracker.py` |

##### Acceptance Criteria

- [ ] Snapshot + verify + diff APIs exist and are used as the CAS gate (INV-04)
- [ ] `<PROJECT>` fingerprint is handled as a non-file key (ALG-03)
- [ ] Validation artifacts exist: (TEST-02)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-03-change-tracker.md](components/com-03-change-tracker.md)

---

### MILE-02 — Coordination + staleness + stall planning

Produces: (COM-04, COM-05, COM-06)
Validated-by: (TEST-02)
Implements: (COM-04, COM-05, COM-06)
Decisions: ()

#### TASK-05 — Implement InvestigationCoordinator

Implements: (COM-04, ALG-04)
Satisfies: (INV-01, INV-05)
Validated-by: (TEST-02)
Depends-on: (TASK-01)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/state/investigation_coordinator.py` |

##### Acceptance Criteria

- [ ] Target-level locks prevent concurrent investigations (INV-05)
- [ ] Polling returns completed results with start snapshots (ALG-04)
- [ ] Validation artifacts exist: (TEST-02)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-04-investigation-coordinator.md](components/com-04-investigation-coordinator.md)

---

#### TASK-06 — Implement LinterStalenessManager

Implements: (COM-05, ALG-05)
Satisfies: (INV-01, INV-06, PROC-04, PROC-05)
Validated-by: (TEST-02)
Depends-on: (TASK-01)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/state/linter_staleness_manager.py` |

##### Acceptance Criteria

- [ ] Excluded-linter set is derivable from staleness state (INV-06)
- [ ] Hard failure state is queryable (e.g., `failed_linters()` for PROC-07 integration)
- [ ] Refresh-only preparation revalidates blockers (PROC-04)
- [ ] Failure transitions do not strand `PENDING_REFRESH` (PROC-05)
- [ ] Validation artifacts exist: (TEST-02)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-05-linter-staleness-manager.md](components/com-05-linter-staleness-manager.md)

---

#### TASK-07 — Implement StallDetector

Implements: (COM-06, ALG-06)
Satisfies: (INV-01, INV-06, PROC-02, PROC-03, PROC-07)
Validated-by: (TEST-02)
Depends-on: (TASK-01, TASK-02, TASK-06)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/state/stall_detector.py` |

##### Acceptance Criteria

- [ ] Candidate stalls can be set/reset and consumed deterministically (PROC-02)
- [ ] Investigation deferral rule is enforced (PROC-03, INV-06)
- [ ] Pending investigations track age and support give-up eviction (PROC-07)
- [ ] Validation artifacts exist: (TEST-02)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-06-stall-detector.md](components/com-06-stall-detector.md)

---

## PHASE-02 — Policy Layer

Goal: (GOAL-01, GOAL-05)
Scope: (ALG-07, ALG-08)
Depends-on: (PHASE-01)
Decisions: ()

### MILE-03 — Actionability + termination policies

Produces: (COM-07, COM-08)
Validated-by: (TEST-02)
Implements: (COM-07, COM-08, CON-03, CON-08)
Decisions: ()

#### TASK-08 — Implement ActionabilityPolicy

Implements: (COM-07, ALG-07)
Satisfies: (PROC-01, GOAL-05)
Validated-by: (TEST-02)
Depends-on: (TASK-02, TASK-03, TASK-05, TASK-06, TASK-07)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/policy/actionability_policy.py` |

##### Acceptance Criteria

- [ ] Actionable targets/files match gating rules (PROC-01)
- [ ] `<PROJECT>` gating is enforced when locks exist (PROC-01)
- [ ] `DIRTY` targets are excluded from `actionable_*` outputs (PROC-01)
- [ ] Validation artifacts exist: (TEST-02)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-07-actionability-policy.md](components/com-07-actionability-policy.md)

---

#### TASK-09 — Implement TerminationPolicy

Implements: (COM-08, ALG-08)
Satisfies: (GOAL-01, INV-03)
Validated-by: (TEST-02)
Depends-on: (TASK-03, TASK-06, TASK-07)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/policy/termination_policy.py` |

##### Acceptance Criteria

- [ ] `ABORT` is returned when project is unlintable (INV-03)
- [ ] `SUCCESS` requires no actionable errors, no stale linters, no pending targets, no in-flight investigations, and no `DIRTY` targets (ALG-08, PROC-13)
- [ ] Validation artifacts exist: (TEST-02)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-08-termination-policy.md](components/com-08-termination-policy.md)

---

## PHASE-03 — Workflows

Goal: (GOAL-01, GOAL-02, GOAL-03, GOAL-04)
Scope: (ALG-09, ALG-10, ALG-11, ALG-12, ALG-13)
Depends-on: (PHASE-02)
Decisions: ()

### MILE-04 — InitWorkflow

Produces: (COM-09)
Validated-by: (TEST-03)
Implements: (COM-09, CON-01)
Decisions: ()

#### TASK-10 — Implement InitWorkflow

Implements: (COM-09, ALG-09)
Satisfies: (GOAL-01)
Validated-by: (TEST-03)
Depends-on: (TASK-02, TASK-03, TASK-04, TASK-05, TASK-06, TASK-07)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/workflow/init_workflow.py` |

##### Acceptance Criteria

- [ ] Initial lint ingestion initializes all state stores (ALG-09)
- [ ] Early-exit path triggers when diagnostics are empty (GOAL-01)
- [ ] Validation artifacts exist: (TEST-03)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-09-init-workflow.md](components/com-09-init-workflow.md)

---

### MILE-05 — LintWorkflow

Produces: (COM-11)
Validated-by: (TEST-03)
Implements: (COM-11, CON-05, CON-12, CON-13)
Decisions: ()

#### TASK-11 — Implement LintWorkflow

Implements: (COM-11, ALG-11)
Satisfies: (GOAL-04, INV-02, PROC-04, PROC-05)
Validated-by: (TEST-03)
Depends-on: (TASK-02, TASK-03, TASK-05, TASK-06)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/workflow/lint_workflow.py` |

##### Acceptance Criteria

- [ ] Updates preserve `locked ∪ unlintable` diagnostics (INV-02)
- [ ] Post-change lint marks/clears `DIRTY` for change-set targets during diagnostics refresh (PROC-06, PROC-13)
- [ ] Refresh-only tick uses staleness preparation gate (PROC-04)
- [ ] Failure transitions integrate with staleness manager (PROC-05)
- [ ] Validation artifacts exist: (TEST-03)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-11-lint-workflow.md](components/com-11-lint-workflow.md)

---

### MILE-06 — AgentWorkflow

Produces: (COM-10)
Validated-by: (TEST-03)
Implements: (COM-10, CON-04)
Decisions: ()

#### TASK-12 — Implement AgentWorkflow

Implements: (COM-10, ALG-10)
Satisfies: (GOAL-02, PROC-02)
Validated-by: (TEST-03)
Depends-on: (TASK-02, TASK-04)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/workflow/agent_workflow.py` |

##### Acceptance Criteria

- [ ] Agent writes are guarded by CAS pre-write verification (INV-04)
- [ ] Candidate stalls are computed from actionable inputs + change set (PROC-02)
- [ ] Validation artifacts exist: (TEST-03)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-10-agent-workflow.md](components/com-10-agent-workflow.md)

---

### MILE-07 — ExternalChangeWorkflow

Produces: (COM-13)
Validated-by: (TEST-03)
Implements: (COM-13, CON-09, CON-13)
Decisions: ()

#### TASK-13 — Implement ExternalChangeWorkflow

Implements: (COM-13, ALG-13)
Satisfies: (PROC-06, GOAL-02)
Validated-by: (TEST-03)
Depends-on: (TASK-03, TASK-04, TASK-07, TASK-11)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/workflow/external_change_workflow.py` |

##### Acceptance Criteria

- [ ] External changes clear stalled/pending/unlintable state for changed targets (PROC-06)
- [ ] External changes mark changed targets as `DIRTY` until diagnostics are refreshed (PROC-06, PROC-13)
- [ ] External change path triggers conservative post-change lint (PROC-06)
- [ ] Validation artifacts exist: (TEST-03)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-13-external-change-workflow.md](components/com-13-external-change-workflow.md)

---

### MILE-08 — InvestigationWorkflow

Produces: (COM-12)
Validated-by: (TEST-03)
Implements: (COM-12, CON-02, CON-11, CON-12)
Decisions: ()

#### TASK-14 — Implement InvestigationWorkflow

Implements: (COM-12, ALG-12)
Satisfies: (GOAL-03, INV-04, INV-05)
Validated-by: (TEST-03)
Depends-on: (TASK-02, TASK-03, TASK-04, TASK-05, TASK-06, TASK-11, TASK-13)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/workflow/investigation_workflow.py` |

##### Acceptance Criteria

- [ ] Investigation results are applied only when staleness gate passes (INV-04)
- [ ] Unsafe investigation results route through ExternalChangeWorkflow (PROC-06)
- [ ] Post-change lint is triggered on successful investigator diffs (GOAL-03)
- [ ] Validation artifacts exist: (TEST-03)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-12-investigation-workflow.md](components/com-12-investigation-workflow.md)

---

## PHASE-04 — Application Integration

Goal: (GOAL-01, GOAL-06)
Scope: (ALG-14, ALG-15)
Depends-on: (PHASE-03)
Decisions: ()

### MILE-09 — Orchestrator refactor

Produces: (COM-14)
Validated-by: (TEST-03)
Implements: (COM-14, CON-01, CON-02, CON-03, CON-04, CON-05, CON-06, CON-07, CON-08, CON-09, CON-10)
Decisions: ()

#### TASK-15 — Refactor composition root (Orchestrator)

Implements: (COM-14, ALG-14)
Satisfies: (GOAL-01, INV-03)
Validated-by: (TEST-03)
Depends-on: (TASK-08, TASK-09, TASK-10, TASK-11, TASK-12, TASK-13, TASK-14)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| modify | `scripts/lint_fixer/orchestrator.py` |
| modify | `scripts/lint_fixer/__main__.py` |

##### Acceptance Criteria

- [ ] Orchestrator delegates all domain logic into components (INV-01)
- [ ] `ABORT` is enforced on project unlintable (INV-03)
- [ ] `SUCCESS` is blocked while locked targets or dirty targets are non-empty (PROC-13)
- [ ] Idle wait/select is used when waiting on investigations or dirty targets (PROC-10)
- [ ] Integration behavior remains testable via mocks (TEST-03)
- [ ] Validation artifacts exist: (TEST-03)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-14-orchestrator.md](components/com-14-orchestrator.md)

---

### MILE-10 — Reporter

Produces: (COM-15)
Validated-by: (TEST-03)
Implements: (COM-15, CON-10)
Decisions: ()

#### TASK-16 — Implement Reporter

Implements: (COM-15, ALG-15)
Satisfies: (GOAL-06)
Validated-by: (TEST-03)
Depends-on: (TASK-15)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/lint_fixer/reporter.py` |
| modify | `scripts/lint_fixer/orchestrator.py` |

##### Acceptance Criteria

- [ ] Final report includes unlintable targets + reasons + remaining diagnostics (GOAL-06)
- [ ] Reporter output is stable under mocked runs (TEST-03)
- [ ] Validation artifacts exist: (TEST-03)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)

**Detailed spec:** [components/com-15-reporter.md](components/com-15-reporter.md)

---

## PHASE-05 — Verification + Cleanup

Goal: (GOAL-01, GOAL-02, GOAL-03, GOAL-04, GOAL-05, GOAL-06)
Scope: (QA-01, QA-02, QA-03, QA-04, QA-05)
Depends-on: (PHASE-04)
Decisions: ()

### MILE-11 — Test suite alignment

Produces: (TEST-02, TEST-03)
Validated-by: (TEST-02, TEST-03)
Implements: (QA-01, QA-02, QA-03, QA-04, QA-05)
Decisions: ()

#### TASK-17 — Update/add unit and integration tests

Implements: (TEST-02, TEST-03)
Satisfies: (QA-01, QA-02, QA-03, QA-04, QA-05)
Validated-by: (TEST-02, TEST-03)
Depends-on: (TASK-16)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| modify | `scripts/tests/unit/lint_fixer/test_orchestrator.py` |
| modify | `scripts/tests/integration/lint_fixer/test_orchestrator.py` |
| create | `scripts/tests/unit/lint_fixer/test_state_components.py` |

##### Acceptance Criteria

- [ ] Validation artifacts exist: (TEST-02, TEST-03)
- [ ] No compatibility shims remain after refactor (INV-01 policy)
- [ ] Required PRD/Design IDs are referenced (no restated requirements)
- [ ] Decision links recorded when applicable: (decided-by: ADR-###)
