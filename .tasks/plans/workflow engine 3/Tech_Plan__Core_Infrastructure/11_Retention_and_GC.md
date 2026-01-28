# Core Infrastructure — Retention and Garbage Collection

- **Doc**: Tech_Plan__Core_Infrastructure/11_Retention_and_GC.md
- **Updated**: 2026-01-26
- **Library**: `workflow_engine.maintenance.gc`
- **Depends on**: [`00_Foundation.md`](00_Foundation.md), [`10_Configuration_System.md`](10_Configuration_System.md)
- **Primary responsibility**: Evidence-preserving retention rules and explicit garbage collection (no background deletion).

## 11.5 Retention and garbage collection

Retention is enforced by an explicit GC operation. There is no silent background deletion.

### 11.5.1 Invocation

GC can be invoked:

- manually: `workflowctl gc`
- opportunistically on CLI startup (optional): if `workflowctl` detects `last_gc_at` older than `gc_interval_hours` (configurable)

Any GC run MUST write a summary to:

- `workspace/gc/gc_<run_ts>.json`

### 11.5.2 What GC manages

GC may delete or compact:

- completed run directories under `workspace/runs/`
- archived notifications/control actions older than retention window
- sandboxes under `sandboxes/` (subject to sandbox TTL semantics §11.4.1)
- log shards under `workspace/logs/` (optional compression)

GC MUST NOT delete:

- active runs (`run.json.status in {"running","paused","investigating"}`)
- artifacts referenced by active runs

### 11.5.3 Run retention rule

Config:

- `[retention] keep_days`
- `[retention] keep_runs`

Normative rule:

- For each repo, compute:
  - `cutoff_time = now - keep_days`
  - `protected_runs = newest keep_runs runs by start time`
- A completed run is eligible for deletion if:
  - it is not in `protected_runs`
  - AND its `finished_at < cutoff_time`

This means “keep at least N recent runs, and also keep all runs from the last D days”.

### 11.5.4 Log compaction

If enabled, GC MAY compress old log shards:

- Input: `logs/shards/<run_id>/*.log`
- Output: `logs/shards/<run_id>/*.log.gz`

Compression is optional and must be transparent:

- `workflowctl logs show` MUST read either plain or compressed logs.

### 11.5.5 Evidence preservation

Before deleting a run, GC MUST ensure that ticket-level durable evidence remains:

- ticket records in `workspace/tickets/`
- exported patches / summaries required for audit

GC is allowed to delete *run-local* artifacts that are reproducible from ticket state (e.g., hydration blobs), but must not delete ticket state.

### 11.5.6 GC Lock Acquisition (normative)

- GC operations MUST acquire `locks/gc.lock` before performing any deletion or compaction.
- `locks/gc.lock` is the highest-priority lock in the global lock order (see `Tech_Plan__Core_Infrastructure/05_Multi_Writer_Correctness.md` §6.4).
- GC MUST NOT acquire any other locks (`branch`, `ticket`, `task`) while holding `locks/gc.lock` to prevent blocking other operations.

If GC needs to inspect ticket or task state, it MUST:
1. release `locks/gc.lock`
2. acquire the necessary lower-priority locks
3. perform inspection
4. release lower-priority locks
5. re-acquire `locks/gc.lock` if needed
