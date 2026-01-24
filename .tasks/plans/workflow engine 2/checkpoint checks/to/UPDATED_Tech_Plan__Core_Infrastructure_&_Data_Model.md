# Tech Plan: Core Infrastructure & Data Model

## Overview

This spec defines the durable storage, protocols, and core runtime primitives for the system after the **robust file-backed pivot** and the **Patch-Stream (jj-backed) code-change model**.

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

- Make workflow state and evidence durable across crashes and power loss.
- Support many concurrent step processes writing logs and state without contention.
- Make workflows debuggable and self-healable using durable evidence (logs + workspace state).
- Keep runtime footprint minimal:
  - no always-on database service requirement
  - no mandatory ports
  - no reliance on the repo working tree as a durability boundary
- Make the code-change backbone explicit: ticket work is represented as **jj change stacks** and **patches**, not persistent git worktrees.

## Philosophy

- **Durable evidence over convenience abstractions**: sharded JSONL logs + file-backed workspace state are the audit trail.
- **ID-centric navigation**: the primary interaction mode is “go to run/step/error ID”, not text-searching logs.
- **Protocol discipline prevents rot**: schema_version, atomic writes, and ordering guarantees are mandatory.
- **Pause is a correctness requirement**: every process must promptly honor PAUSE and acknowledge it.
- **Sandboxes are disposable**: tooling runs in ephemeral hydrated sandboxes; the durable truth is patches + workspace docs + log shards.

## Terminology

- **PGS (Patch Graph Store)**: a jj-backed change graph. Ticket work is represented as a **change stack**; each patch is an atomic change.
- **Virtual hydration**: on-demand reconstruction of file content at a given revision (anchor + patch stack) without checking it out.
- **Sandbox**: a disposable environment where tools run against a hydrated view of the repo (anchor + patch stack).
- **WSS (Workspace State Store)**: filesystem-backed hierarchical document store for mutable workspace state (repo/project/ticket/task/step/run).
- **Logs Store**: durable, sharded JSONL event logs written per step process.
- **Notifications Store**: durable filesystem queue for out-of-band user-visible notifications.
- **Control Actions Queue**: durable filesystem queue for user and UI requests (pause/resume, trace overrides, ack/resolve, retry).
- **Run**: a workflow run with a stable `run_id` that groups step executions.
- **Step execution**: one atomic action performed by a step process, identified by `step_execution_id`. A step process may execute tools internally, but orchestration remains flat.

## Runtime Root Layout

All runtime artifacts live under a single root (example):

```text
~/.workflow/
  repos/<repo_uid>/
    repo.json
    workspace/                 # WSS
      index.json
      projects/
      tickets/
      tasks/
      runs/
      conclusions/
      trace_overrides/
    logs/                      # Logs Store (sharded JSONL)
      runs/<run_id>/
        writers/<writer_id>.jsonl
        index.json             # optional derived cursor/index
    notifications/             # Notifications Store (filesystem queue)
      inbox/
      archive/
    control_actions/           # Control Actions Queue (filesystem queue)
      inbox/
      ack/
      applied/
      failed/
    sandboxes/                 # Ephemeral sandboxes (disposable)
    caches/                    # Optional caches (disposable)
```

This root is the durability boundary for the runtime. The repository working tree is not.

## Repo Identity and `repo_uid`

`repo_uid` is a stable identifier for “this repo on this machine”.

### Derivation

- Default: `repo_uid = sha256(canonical_repo_root_path + "\n" + git_remote_url_or_empty)[:16]`
- Stored in `repo.json` and treated as authoritative after first creation.

### `repo.json` schema (WSS)

```json
{
  "schema_version": 1,
  "repo_uid": "e7b4c3d2a1f09c88",
  "display_name": "ai-workflow",
  "repo_root": "/home/me/src/ai-workflow",
  "git_remote_url": "git@github.com:org/ai-workflow.git",
  "created_at": "2026-01-23T00:00:00Z",
  "updated_at": "2026-01-23T00:00:00Z"
}
```

## Patch Graph Store (PGS): jj adapter surface

PGS is backed by `jj` (Jujutsu). This spec defines the minimal adapter surface the rest of the system relies on.

### Core concepts

- **Ticket = change stack**:
  - stack has a stable `ticket_id`
  - stack has a base parent revision
  - stack contains one or many patch changes
- **Patch = atomic change object**:
  - can be represented as a jj change
  - can be imported from unified diff or structured hunks
- **Rebase = pointer move**:
  - move the base of a stack to a new parent
  - replay patches
  - conflicts become resolver jobs/objects

### Required adapter operations (conceptual)

- `create_stack(ticket_id, parent_rev) -> stack_id`
- `describe_stack(stack_id) -> {parent_rev, patches[]}`
- `apply_patch(stack_id, patch) -> patch_id`
- `hydrate_file(stack_id, path) -> bytes`
- `hydrate_tree(stack_id, paths[]) -> sandbox_input`
- `rebase_stack(stack_id, new_parent_rev) -> rebase_result`
- `export_stack(stack_id, mode) -> artifact` where `mode in {squash, linear}`

The adapter is responsible for mapping these conceptual operations to jj commands and producing stable IDs.

## Workspace State Store (WSS)

WSS is the durable document store for workflow state and artifacts that are not safely “re-derived” from logs alone.

### WSS layout

```text
workspace/
  index.json                         # optional: derived index for fast lookup
  projects/<project_id>/
    project.json
    docs/                            # imported planning docs (markdown)
  tickets/<ticket_id>/
    ticket.json
    docs/                            # ticket-level docs
    tasks/<task_id>/
      task.json
      input.md
      steps/<step_id>.md
      deviations/
      evaluation/
  runs/<run_id>/
    run.json
    steps/<step_execution_id>.json   # step metadata + status + pointers to logs
    artifacts/
  conclusions/
    tools/<tool_fingerprint>/
    perf/<step_signature>/
  trace_overrides/
    overrides.json
```

### Document requirements

Every durable WSS document MUST include:

- `schema_version` (integer)
- a stable ID (`project_id`, `ticket_id`, `run_id`, `step_execution_id`, etc.)
- `created_at` and `updated_at` timestamps
- writer/ownership fields where relevant (for multi-writer correctness)

### Run and step documents

`runs/<run_id>/run.json`:

```json
{
  "schema_version": 1,
  "run_id": "01J3ZQK9X2K6QZV6J2Q2Z0A7TR",
  "workflow_type": "task_exec",
  "repo_uid": "e7b4c3d2a1f09c88",
  "project_id": "LIN-1",
  "ticket_id": "LIN-1-NES-123",
  "status": "running",
  "started_at": "2026-01-23T00:00:00Z",
  "ended_at": null,
  "metadata": {}
}
```

`runs/<run_id>/steps/<step_execution_id>.json`:

```json
{
  "schema_version": 1,
  "step_execution_id": "01J3ZQK9X5J9H6R8V2S4J2E9P3",
  "run_id": "01J3ZQK9X2K6QZV6J2Q2Z0A7TR",
  "workflow_type": "task_step",
  "function_context": "scripts.ticket_manager.task_executor.execute_step",
  "ticket_id": "LIN-1-NES-123",
  "status": "running",
  "parent_step_execution_id": null,
  "attempt": 1,
  "writer_id": "writer-6f14c7",
  "log_shard_path": "logs/runs/01J3ZQK9X2K6QZV6J2Q2Z0A7TR/writers/writer-6f14c7.jsonl",
  "started_at": "2026-01-23T00:00:00Z",
  "ended_at": null,
  "metrics": {
    "heartbeat_ts": "2026-01-23T00:00:10Z"
  },
  "metadata": {}
}
```

### WSS update semantics: JSON Merge Patch

All updates to JSON documents use **JSON Merge Patch (RFC 7396)**.

- Writers submit a patch object.
- A patch is applied to the current document to produce the new document.
- Arrays are treated as scalars (replace entirely).

#### Edge-case rules (locked)

- Patch root MUST be a JSON object; otherwise reject.
- Deleting missing keys (patch has `null` for an absent key) is a no-op.
- Type mismatches overwrite (patch wins).
- `null` is reserved for deletion and MUST NOT be used as a business value in persisted docs.

### Atomic write protocol (mandatory)

Every durable WSS write is atomic:

1. write to `<file>.tmp.<random>`
2. flush and fsync the temp file
3. rename temp to target
4. fsync the containing directory

Readers ignore `*.tmp.*`.

## Logs Store (sharded JSONL)

Logs are the durable event stream. Each step process writes to its own shard to avoid contention.

### Shard layout

- One shard per `writer_id` per `run_id`:

```text
logs/runs/<run_id>/writers/<writer_id>.jsonl
```

- A shard is append-only.

### JSONL schema v1 (mandatory)

Each line is a JSON object:

Required fields:

- `schema_version`: int (start at 1)
- `event_type`: string enum
- `ts`: RFC3339 string (locked format)
- `run_id`: string
- `step_execution_id`: string or null
- `writer_id`: string
- `seq`: int (monotonic per shard file)
- `data`: object

Recommended fields:

- `repo_uid`
- `project_id`, `ticket_id`, `task_id`, `step_id` (definition IDs)
- `parent_step_execution_id` (logical nesting only; orchestration remains flat)
- `trace_id` / `span_id`
- `severity` (`info`, `warn`, `error`)

### Minimum event types

- `step_start`
- `step_stop`
- `stdout_chunk`
- `stderr_chunk`
- `tool_start`
- `tool_stop`
- `trace` (function-call trace frames; only when enabled per-step)
- `error`
- `notification_raised`
- `pause_requested`
- `pause_ack`
- `resume_requested`
- `resume_ack`

### Ordering guarantees

- Within a shard file, `seq` is strictly increasing and never reused.
- Consumers treat `(writer_id, seq)` as the canonical ordering key.
- Cross-shard ordering is best-effort and based on timestamps; do not assume perfect total order.

### Chunking policy

- Tool stdout/stderr is stored as chunk events with a bounded payload size.
- Each chunk includes:
  - `chunk_index`
  - `encoding` (`utf-8`)
  - `bytes` (base64) or `text` (if guaranteed safe)
- Chunking avoids huge single-line records and enables incremental streaming.

### Retention and cleanup

Defaults:

- keep last N runs per repo (configurable)
- keep last N days of logs (configurable)

Cleanup MUST refuse to delete artifacts for active (running or paused) runs.

## Notifications Store and Control Actions Queue

These are filesystem queues (durable; multi-writer safe) under the repo root.

### Notifications Store

- Writers create one JSON file per notification in `notifications/inbox/`.
- Consumers move processed items to `notifications/archive/`.

Filename pattern:

```text
notifications/inbox/<ts>.<notification_id>.json
```

Notification schema:

```json
{
  "schema_version": 1,
  "notification_id": "01J3ZQK9Y1Z8E7J9S7R1F2B3C4",
  "ts": "2026-01-23T00:00:00Z",
  "severity": "warn",
  "title": "Sandbox tests failed",
  "body": "See evaluation report for run 01J3ZQK9X2K6QZV6J2Q2Z0A7TR.",
  "refs": {
    "run_id": "01J3ZQK9X2K6QZV6J2Q2Z0A7TR",
    "step_execution_id": "01J3ZQK9X5J9H6R8V2S4J2E9P3",
    "artifact_paths": ["workspace/runs/01J3ZQK9X2K6QZV6J2Q2Z0A7TR/artifacts/evaluation/gaps.md"]
  }
}
```

### Control Actions Queue

- Requests are JSON files written into `control_actions/inbox/`.
- Targets can be a run, step execution, workflow type, or ticket.
- Acks are written by step processes into `control_actions/ack/`.
- Root or the responsible process moves applied actions into `control_actions/applied/` (or `failed/`).

Request schema:

```json
{
  "schema_version": 1,
  "request_id": "01J3ZQK9Y7H6K0X8P3Q1M4N5R6",
  "ts": "2026-01-23T00:00:00Z",
  "created_by": "ui",
  "action_type": "pause",
  "target": {
    "run_id": "01J3ZQK9X2K6QZV6J2Q2Z0A7TR",
    "step_execution_id": "01J3ZQK9X5J9H6R8V2S4J2E9P3"
  },
  "payload": {
    "reason": "User requested pause"
  }
}
```

## Pause and ACK protocol

Definition of **paused**:

1. the step process is not executing any tool subprocess
2. the step process is not mutating WSS state
3. the step process is waiting in a control loop for RESUME or STOP
4. it has flushed required log and state boundaries for safe continuation

Protocol:

- Root/UI writes `action_type=pause` into the Control Actions Queue.
- Step process detects the request (poll or notify), transitions to paused state within a deadline, then writes an ACK file:

```text
control_actions/ack/pause.<request_id>.<step_execution_id>.json
```

If a step cannot pause within deadline, it triggers the investigator path (it does not rely on root killing by default).

## Dynamic tracing and trace overrides

Trace enablement is controlled by durable override docs:

- `workspace/trace_overrides/overrides.json`

Step processes poll at safe points and emit `trace` events when enabled.

## Tool conclusions store

Conclusions are durable and have a promotion lifecycle to avoid repeated investigation.

Storage:

```text
workspace/conclusions/
  tools/<tool_fingerprint>/<conclusion_id>.json
  perf/<step_signature>/<conclusion_id>.json
```

Required fields:

- `schema_version`
- `conclusion_id`
- `kind` (`tool` or `perf`)
- `state` (`draft`, `confirmed`, `promoted`)
- `fingerprint` (tool path + version + args class + env signature)
- `evidence_refs` (run_id, writer_id, seq ranges)
- `created_at`

Promotion rules are conservative:

- draft to confirmed requires reproduction in distinct runs
- confirmed to promoted requires stable signature and successful remediation outcomes

## Investigator contract (machine-readable)

When a step process is stuck (pause deadline exceeded, tool exceeded duration without progress, repeated identical failures), it spawns an investigator job with bounded inputs and produces machine-readable outputs:

Outputs:

- `classification`: `resolved` | `needs_user` | `needs_retry` | `needs_shutdown`
- `actions`: concrete operations (kill tool PID, delete temp files, write resume script)
- `resume_plan`: path to resume script + required WSS patches
- `conclusion_updates`: new or updated conclusions
- `evidence_refs`: run_id and log shard ranges

## Sandboxes

Sandboxes are disposable directories under `sandboxes/` that contain a hydrated view of the repo for tools.

Key invariant:

- Sandboxes must not require copying the entire repo.

## CLI surface: `workflowctl`

Minimum CLI commands referenced by other specs:

- `workflowctl hydrate <ticket_id> <path>`
- `workflowctl apply-patch <ticket_id> --diff <patch_file>`
- `workflowctl sandbox run <ticket_id> -- lint|test|build`
- `workflowctl notifications tail --jsonl`
- `workflowctl control send <action_file>`
- `workflowctl gc` (safe cleanup)

## Ownership and contention rules

- Each step process owns:
  - its log shard (`writer_id`)
  - its step execution doc updates (metrics, status)
- Root (or the interactive manager process) owns:
  - run.json lifecycle transitions
  - derived indexes (optional)
  - long-lived project and ticket metadata docs
- Notifications are multi-writer: any process may create notifications; consumers must be idempotent.
- Control actions are multi-writer inbox; each target step is responsible for acknowledging requests directed at it.

## Open parameters (documented defaults)

- Durability cadence:
  - default flush at step boundaries and on errors
  - default fsync on errors; optional fsync at step boundaries
- Log chunk sizing:
  - default fixed byte limit per chunk event
- Retention:
  - default keep last N runs per repo and last N days
- Pause deadlines:
  - default short deadline; escalation spawns investigator job

---

## Related Specs

- Epic brief: Epic_Brief__Multi-Layered_Project_Management_System.md
- Core flows: Core_Flows__Project_Management_&_Autonomous_Monitoring.md
- Integration plan: Tech_Plan__Integration_&_File_Structure.md
