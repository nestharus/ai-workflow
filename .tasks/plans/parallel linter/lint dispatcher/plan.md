# Lint Dispatcher Execution Plan

Sources: [requirements.md](requirements.md) | [design-map.md](design-map.md) | [plan structure](../../../processes/plan.md)

This document is an execution plan (work ordering only). Design topology (components, contracts, protocols) is defined in [design-map.md](design-map.md).

---

## PHASE-01 — Shared Contracts + Registry

Goal: (GOAL-01, GOAL-02)
Scope: (COM-01, COM-04, IAR-01, IAR-02, IAR-04, CON-01, CON-03)
Depends-on: ()
Decisions: ()

### MILE-01 — Shared Types and Data Contracts

Produces: (IAR-01, IAR-02, IAR-03, IAR-04, IAR-05, IAR-06, IAR-07)
Validated-by: (TEST-01)
Implements: (IAR-01, IAR-02, IAR-03, IAR-04, IAR-05, IAR-06, IAR-07)
Decisions: ()

#### TASK-01 — Define shared dataclasses and result contracts

Implements: (IAR-01, IAR-02, IAR-03, IAR-04, IAR-05, IAR-06, IAR-07)
Satisfies: (EXEC-01, IN-06)
Validated-by: (TEST-01)
Depends-on: ()
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/dev/linter/contracts.py` |
| modify | `scripts/dev/linter/base.py` |

##### Acceptance Criteria

- [ ] Shared contracts exist and are referenced by domains: (IAR-01, IAR-02, IAR-03, IAR-04, IAR-05, IAR-06, IAR-07)
- [ ] Domain modules depend on shared contracts (not CLI parsing internals) (GOAL-01)
- [ ] Validation artifacts exist: (TEST-01)

---

### MILE-02 — Linter Registry + Instance Identity

Produces: (COM-04, CON-03)
Validated-by: (TEST-01)
Implements: (COM-04, CON-03)
Decisions: ()

#### TASK-02 — Refactor linter registry to support per-run instances + metadata

Implements: (COM-04)
Satisfies: (IN-01, INV-01)
Validated-by: (TEST-01)
Depends-on: (TASK-01)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| modify | `scripts/dev/linter/linters/__init__.py` |
| modify | `scripts/dev/linter/base.py` |

##### Acceptance Criteria

- [ ] Linter registry preserves a total order (IN-01)
- [ ] Linter instances created per run carry a stable instance identity key used for hashing/equality (INV-01)
- [ ] Scheduling-relevant linter metadata exists and is used by the scheduler (IN-02)
- [ ] Validation artifacts exist: (TEST-01)

**Detailed spec:** [components/com-04-linter-config-domain.md](components/com-04-linter-config-domain.md)

---

## PHASE-02 — Leaf Domains

Goal: (GOAL-01, GOAL-02)
Scope: (COM-03, COM-04, CON-02, CON-03)
Depends-on: (PHASE-01)
Decisions: ()

### MILE-03 — File Discovery Domain

Produces: (COM-03, IAR-03)
Validated-by: (TEST-03)
Implements: (COM-03, CON-02)
Decisions: ()

#### TASK-03 — Extract FileDiscoveryDomain (git → normalize → dedupe → exists → sort)

Implements: (COM-03)
Satisfies: (IN-06)
Validated-by: (TEST-03)
Depends-on: (TASK-01)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/dev/linter/domains/file_discovery.py` |
| modify | `scripts/dev/linter/lint_cli.py` |

##### Acceptance Criteria

- [ ] Mode selection and error handling matches (EXEC-02)
- [ ] File discovery result satisfies (IN-06, INV-02)
- [ ] Existence-only filtering excludes deleted files without additional git queries (INV-03)
- [ ] Validation artifacts exist: (TEST-03)

**Detailed spec:** [components/com-03-file-discovery-domain.md](components/com-03-file-discovery-domain.md)

---

### MILE-04 — Linter Config Domain

Produces: (COM-04, IAR-04)
Validated-by: (TEST-01)
Implements: (COM-04, CON-03)
Decisions: ()

#### TASK-04 — Extract LinterConfigDomain (spec expansion, instances, filesets, preflight)

Implements: (COM-04)
Satisfies: (INV-01, PROC-01)
Validated-by: (TEST-01)
Depends-on: (TASK-02, TASK-03)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/dev/linter/domains/linter_config.py` |
| modify | `scripts/dev/linter/lint_cli.py` |

##### Acceptance Criteria

- [ ] Spec expansion preserves stable ordering and returns errors for unknown names (IN-03)
- [ ] Per-run linter instances preserve identity end-to-end (INV-01)
- [ ] Filesets are calculated per instance and tolerate file-not-found races (PROC-01)
- [ ] Existence-only pruning is used for drift handling (INV-03)
- [ ] Preflight behavior matches self-healing rules (EXEC-03)
- [ ] Validation artifacts exist: (TEST-01)

**Detailed spec:** [components/com-04-linter-config-domain.md](components/com-04-linter-config-domain.md)

---

## PHASE-03 — Scheduling

Goal: (GOAL-02)
Scope: (COM-05, IAR-05, CON-04)
Depends-on: (PHASE-02)
Decisions: ()

### MILE-05 — SchedulingDomain + ArgMaxChunker

Produces: (COM-05, IAR-05)
Validated-by: (TEST-02)
Implements: (COM-05, CON-04)
Decisions: ()

#### TASK-05 — Implement SchedulingDomain (phases + chunk sequence IDs)

Implements: (COM-05)
Satisfies: (INV-04, PERF-02)
Validated-by: (TEST-02)
Depends-on: (TASK-04)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/dev/linter/domains/scheduling.py` |
| modify | `scripts/dev/linter/base.py` |

##### Acceptance Criteria

- [ ] Phase plan generation is deterministic and stable (INV-02)
- [ ] Mutator packing prevents concurrent conflicts (INV-04, PROC-05)
- [ ] Commit-mode rules enforced (PROC-04)
- [ ] Chunking honors ARG_MAX budgeting and fails fast on invalid budgets (PROC-06)
- [ ] Chunk sequence IDs are contiguous and monotonic (PROC-07)
- [ ] Validation artifacts exist: (TEST-02)

**Detailed spec:** [components/com-05-scheduling-domain.md](components/com-05-scheduling-domain.md)

---

## PHASE-04 — Execution (Internals + Domain)

Goal: (GOAL-02, GOAL-03, GOAL-04)
Scope: (COM-06, COM-08, COM-09, COM-10, COM-11, COM-12, COM-13, COM-14, COM-15, COM-16, COM-17)
Depends-on: (PHASE-03)
Decisions: ()

### MILE-06 — Process Management Internals

Produces: (COM-11, COM-12, COM-13)
Validated-by: (TEST-05)
Implements: (COM-11, COM-12, COM-13, CON-10, CON-11, CON-13)
Decisions: ()

#### TASK-06 — Implement ProcessPoolManager + ProcessTreeManager + SubprocessRunner

Implements: (COM-11, COM-12, COM-13)
Satisfies: (PERF-02, PROC-10)
Validated-by: (TEST-05)
Depends-on: (TASK-01)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/dev/linter/execution/process_pool.py` |
| create | `scripts/dev/linter/execution/process_tree.py` |
| create | `scripts/dev/linter/execution/subprocess_runner.py` |

##### Acceptance Criteria

- [ ] Process pools are sized deterministically and honor concurrency rules (PERF-02)
- [ ] Process termination kills the entire process tree (PROC-10)
- [ ] Timeouts return structured timeout/crash markers (PROC-10)
- [ ] Validation artifacts exist: (TEST-05)

**Detailed spec:** [components/com-11-process-pool-manager.md](components/com-11-process-pool-manager.md)

---

### MILE-07 — Shutdown + Snapshots

Produces: (COM-08, COM-09, COM-10, COM-14)
Validated-by: (TEST-05)
Implements: (COM-08, COM-09, COM-10, COM-14, CON-07, CON-08, CON-09, CON-12, CON-14)
Decisions: ()

#### TASK-07 — Implement shutdown coordination and snapshot safety

Implements: (COM-08, COM-09, COM-10, COM-14)
Satisfies: (PROC-09, PROC-11, OUT-05)
Validated-by: (TEST-05)
Depends-on: (TASK-06)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/dev/linter/execution/shutdown.py` |
| create | `scripts/dev/linter/execution/signal_handler.py` |
| create | `scripts/dev/linter/execution/cleanup.py` |
| create | `scripts/dev/linter/execution/snapshot_manager.py` |

##### Acceptance Criteria

- [ ] Shutdown initiation is idempotent and cleanup ordering is deterministic (PROC-11)
- [ ] SIGINT triggers coordinated shutdown without raising from the handler (GOAL-03)
- [ ] Snapshot semantics match crash vs shutdown behavior (PROC-09)
- [ ] Cleanup order matches terminate → shutdown → restore (PROC-11)
- [ ] Validation artifacts exist: (TEST-05)

**Detailed spec:** [components/com-14-snapshot-manager.md](components/com-14-snapshot-manager.md)

---

### MILE-08 — Ordered Output + Result Aggregation

Produces: (COM-15, COM-16, COM-17)
Validated-by: (TEST-03, TEST-05)
Implements: (COM-15, COM-16, COM-17, CON-15, CON-16, CON-17)
Decisions: ()

#### TASK-08 — Implement result collection loop with ordered buffering

Implements: (COM-15, COM-16, COM-17)
Satisfies: (GOAL-03, GOAL-04)
Validated-by: (TEST-03, TEST-05)
Depends-on: (TASK-06, TASK-07)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/dev/linter/execution/output_buffer.py` |
| create | `scripts/dev/linter/execution/result_collector.py` |
| create | `scripts/dev/linter/execution/result_stream.py` |

##### Acceptance Criteria

- [ ] Ordered text streaming is stable by chunk sequence ID (OUT-03, PROC-07)
- [ ] Late results are ignored after shutdown initiation (PROC-11)
- [ ] Aggregation preserves linter instance identity and dedupes diagnostics (INV-01, OUT-01)
- [ ] Validation artifacts exist: (TEST-03, TEST-05)

**Detailed spec:** [components/com-17-result-stream-handler.md](components/com-17-result-stream-handler.md)

---

### MILE-09 — ExecutionDomain Integration

Produces: (COM-06, IAR-06)
Validated-by: (TEST-04, TEST-05)
Implements: (COM-06, CON-05)
Decisions: ()

#### TASK-09 — Implement ExecutionDomain (execute_phases/execute_phase) using internals

Implements: (COM-06)
Satisfies: (INV-03, INV-04, PROC-08, PROC-09, PROC-11)
Validated-by: (TEST-04, TEST-05)
Depends-on: (TASK-05, TASK-06, TASK-07, TASK-08)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/dev/linter/domains/execution.py` |
| modify | `scripts/dev/linter/base.py` |

##### Acceptance Criteria

- [ ] Phase execution is deterministic and honors conflict-free scheduling (INV-04, INV-02)
- [ ] Drift handling uses existence-only pruning + re-evaluation (INV-03, PROC-08)
- [ ] Crash/shutdown returns partial results with markers (OUT-05)
- [ ] Output buffering and shutdown semantics are enforced (OUT-03, OUT-04, PROC-11)
- [ ] Validation artifacts exist: (TEST-04, TEST-05)

**Detailed spec:** [components/com-06-execution-domain.md](components/com-06-execution-domain.md)

---

## PHASE-05 — Orchestration + Output + CLI

Goal: (GOAL-01, GOAL-03, GOAL-04)
Scope: (COM-01, COM-02, COM-07, CON-01, CON-02, CON-03, CON-04, CON-05, CON-06)
Depends-on: (PHASE-04)
Decisions: ()

### MILE-10 — OutputDomain

Produces: (COM-07)
Validated-by: (TEST-03, TEST-04)
Implements: (COM-07, CON-06)
Decisions: ()

#### TASK-10 — Implement OutputDomain + output-mode strategy

Implements: (COM-07)
Satisfies: (OUT-05)
Validated-by: (TEST-03, TEST-04)
Depends-on: (TASK-09)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/dev/linter/domains/output.py` |
| modify | `scripts/dev/linter/lint_cli.py` |

##### Acceptance Criteria

- [ ] Output-mode strategy centralizes YAML/text mode conditionals (OUT-02)
- [ ] OutputDomain is the only owner of exit-code computation and rendering (OUT-01)
- [ ] Exit codes follow 0/1/130 semantics (OUT-05)
- [ ] YAML is non-streaming; text streaming is deterministic (OUT-03, OUT-04)
- [ ] Validation artifacts exist: (TEST-03, TEST-04)

**Detailed spec:** [components/com-07-output-domain.md](components/com-07-output-domain.md)

---

### MILE-11 — RunLintersOrchestrator + CLI Wiring

Produces: (COM-01, COM-02)
Validated-by: (TEST-04, TEST-05)
Implements: (COM-01, COM-02, CON-01, CON-02, CON-03, CON-04, CON-05, CON-06)
Decisions: ()

#### TASK-11 — Implement RunLintersOrchestrator and replace current lint_cli flow

Implements: (COM-02)
Satisfies: (EXEC-01, EXEC-04)
Validated-by: (TEST-04, TEST-05)
Depends-on: (TASK-03, TASK-04, TASK-05, TASK-09, TASK-10)
Decisions: ()

##### Files

| Action | Path |
|--------|------|
| create | `scripts/dev/linter/orchestrator.py` |
| modify | `scripts/dev/linter/lint_cli.py` |

##### Acceptance Criteria

- [ ] Lint CLI entrypoint is a thin adapter around COM-01 + COM-02 (GOAL-01, EXEC-01)
- [ ] All old scheduling/execution paths are removed (INV-05)
- [ ] Orchestrator behavior matches preflight self-healing rules (EXEC-03)
- [ ] End-to-end run maintains deterministic behavior and correct exit codes (INV-02, OUT-05)
- [ ] SIGINT handling exits 130 without traceback and is installed at orchestration start (GOAL-03, OUT-05)
- [ ] Validation artifacts exist: (TEST-04, TEST-05)

**Detailed spec:** [components/com-02-run-linters-orchestrator.md](components/com-02-run-linters-orchestrator.md)
