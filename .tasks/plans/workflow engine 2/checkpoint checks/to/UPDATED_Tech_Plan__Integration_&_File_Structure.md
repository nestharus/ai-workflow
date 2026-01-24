# Tech Plan: Integration & File Structure

## Overview

This spec defines how the updated runtime integrates with existing workflows, and the expected module boundaries and file structure after migrating to:

- robust file-backed Workspace State Store (WSS)
- sharded JSONL Logs Store
- filesystem Notifications + Control Actions queues
- Patch-Stream (jj-backed) code-change model
- ephemeral sandboxes for tooling
- optional notifications-only UI

**Constraints & Invariants**

- Local-only, single-machine execution. Not distributed, not cloud.
- Runtime artifacts are local and not committed to git.
- Prefer robustness over micro-optimizing I/O.
- Step logging is always on (step enter/exit + key events).
- Dynamic tracing is optional and enabled per-step when needed.
- Root orchestration is flat: root directly owns/controls all step/agent processes (no grandchildren).
- Pause is mandatory: on PAUSE, processes must stop promptly; enforcement is inside each process.
- Patch-Stream code-change model (jj-backed change graph). Persistent worktrees are not required for the system to function.
- Lint/tests/build run in ephemeral sandboxes (queued execution).
- UI is optional and must not gate workflows; MVP UI surfaces out-of-band notifications only.
- Users do not search logs by text; logs are retrieved and navigated by IDs.
- Keyword/fuzzy search is sufficient for project and ticket lookup; no embedding-model requirement.
- We avoid fixed iteration caps as termination criteria (progress-based circuit breakers instead).
- The system must support many concurrent writers without a single-writer bottleneck.
- All runtime files live under a single predictable root for easy cleanup and backup.


## Goals

- Provide a clear module map and file layout for the new runtime primitives.
- Retrofit existing workflows (review, update-pr, merge, rebase) to emit durable logs and respect PAUSE.
- Make the Patch-Stream model usable from existing agent flows without requiring persistent worktrees.
- Keep the repo clean:
  - no runtime artifacts committed
  - no required local services
  - no scattered state outside `~/.workflow/`

## Philosophy

- Prefer a small number of boring, inspectable primitives (docs + shards + queues + patches).
- Keep orchestration flat: root manages step processes; steps manage their internal tool subprocesses.
- Preserve backwards compatibility at the command surface where practical, while moving the durable truth to WSS + logs + jj.

## Integration Strategy

### Runtime entrypoints

- **Interactive entrypoints**:
  - `/project-manager`
  - `/ticket-manager --project <project_id> --ticket <ticket_id>`
- **Non-interactive entrypoints**:
  - `workflowctl <subcommand>` (hydrate, apply-patch, sandbox run, tail notifications, send control actions)

### Step instrumentation

The system keeps the `@step` concept, but its backing store is no longer a database.

- `@step` creates or updates:
  - `workspace/runs/<run_id>/steps/<step_execution_id>.json`
  - the step's log shard (`logs/runs/<run_id>/writers/<writer_id>.jsonl`)
- `StepLogger.log_event(event_type, data)` appends JSONL events to the shard.
- All step processes must:
  - emit `step_start` and `step_stop`
  - emit periodic heartbeats (as WSS metric updates or `trace`/`info` log events)
  - honor PAUSE and write ACK files

### Flat orchestration rule

- Root owns a flat set of step/agent processes (no orchestration-level grandchildren).
- Step processes may spawn tool subprocesses internally (linters, tests), but must:
  - track them for pause/shutdown
  - ensure they are not left running after PAUSE is acknowledged

### Patch-Stream integration

Existing workflows that previously “edited files in a worktree” are adapted to one of two modes:

- **Mode A: blind patch editor**:
  - hydrate specific files/functions via `workflowctl hydrate`
  - generate a patch (unified diff or structured hunks)
  - apply patch to the ticket stack via `workflowctl apply-patch`
- **Mode B: sandbox editor**:
  - create sandbox hydrated from the ticket stack
  - run tools normally (`rg`, formatters, tests)
  - capture resulting diff and commit as a patch on the stack

Mode A is preferred for fast iterations; Mode B is the fallback for heavy tooling or broad search.

## Retrofitting Existing Workflows

This section names the existing command files and what changes are required to align with the new runtime.

### Workflows

- `.claude/commands/review-implementation.md`
- `.claude/commands/update-pr.md`
- `.claude/commands/rebase.md`
- `.claude/commands/merge.md`

### Required retrofit changes

1. **Wrap each workflow entrypoint in the step runtime**
   - Ensure a `run_id` exists (create if missing)
   - Ensure a `step_execution_id` is allocated for the entry step
   - Ensure a `writer_id` and shard are assigned

2. **Add PAUSE handling to long-running phases**
   - Any phase that can run longer than a short threshold must periodically check for PAUSE requests
   - On PAUSE:
     - stop tool subprocesses
     - flush log shards
     - stop WSS mutations
     - write ACK file and wait for RESUME

3. **Replace DB calls with WSS + logs**
   - Project/ticket/task metadata: read from WSS documents
   - Execution evidence: read from log shards and run/step docs
   - “UI updates”: raise notifications (files) instead of database wakeup mechanisms

4. **Replace worktree assumptions**
   - Any “open a worktree and edit” step becomes:
     - apply patch directly, or
     - run in sandbox, then apply patch

## Updated Repository File Structure

This is the in-repo code layout (not runtime state). Runtime state lives under `~/.workflow/` as specified in the Core Infrastructure plan.

```text
scripts/
  core/
    protocol/
      schema_v1.py            # JSONL and WSS schema helpers
      merge_patch.py          # JSON Merge Patch apply/validate
      atomic_write.py         # tmp + fsync + rename + fsync(dir)
      pause.py                # pause request detection + ack helpers
    storage/
      wss.py                  # WSS read/write helpers
      logs.py                 # log shard append + reader utilities
      queues.py               # notifications/control queue helpers
    vcs/
      jj_adapter.py           # Patch Graph Store adapter (jj)
    sandbox/
      runner.py               # sandbox create/hydrate/run tooling
    conclusions/
      store.py                # conclusion lifecycle + promotion
    investigation/
      bundle.py               # evidence bundling for a run/step
      investigator_contract.py
    runtime/
      step.py                 # @step decorator + StepLogger
      root.py                 # root orchestration (flat)
      ids.py                  # run_id/step_id generation
  project_manager/
    cli.py
    project_index.py          # optional derived indexes for snappy listing
  ticket_manager/
    cli.py
    task_decomposition/
      orchestrator.py
      pattern_discovery_agent.md
      approval_agent.md
      verification_agent.md
      candidate_surfacing.py
    task_executor.py
  pr/
    review_implementation.py  # adapted to WSS/logs + patch-stack inputs
    update_pr.py              # adapted
    rebase_enhanced.py        # jj-based enhanced rebase
    merge.py                  # integration/export policy
  monitoring/
    monitor.py                # optional background monitor
    anomaly_detector.py
    workflow_repair_agent.md

ui/
  workflow-notifications/     # optional notifications-only UI (Tauri)
    src-tauri/
    src/

workflowctl/                  # CLI entrypoint (can live under scripts/ too)
  __main__.py

```

### Removed from the target layout

- Any local database setup directories and DB connection code (deprecated)
- Any required database migrations tooling
- UI modules that assume a DB connection and query model

### Allowed as optional legacy tools

- Worktree helpers and GC scripts may remain if useful for manual workflows, but they are not required for the system to function.

## Runtime State Layout (out of repo)

See: Tech_Plan__Core_Infrastructure_&_Data_Model.md (Runtime Root Layout).

## References

- Core infrastructure and protocols: Tech_Plan__Core_Infrastructure_&_Data_Model.md
- Project and ticket management: Tech_Plan__Project_&_Ticket_Management.md
- Enhanced rebase and evaluation: Tech_Plan__Enhanced_Rebase_&_Evaluation.md
- Monitoring and self-healing: Tech_Plan__Monitoring_&_Self-Healing.md
- Monitoring UI: Tech_Plan__Monitoring_UI_(Tauri).md
