# Tech Plan: Monitoring & Self-Healing

## Overview

This spec defines the autonomous monitoring and self-healing infrastructure after the robust file-backed pivot:

- evidence is durable (WSS + log shards)
- control plane is file-based (control actions queue)
- Patch-Stream changes are applied as patches on jj stacks
- PAUSE is mandatory and enforced inside each step process

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

- Detect anomalies early without relying only on wall-clock time.
- Investigate first using durable evidence, then choose the lightest intervention.
- Enable safe autonomous repair by:
  - generating patches (not ad-hoc file edits)
  - testing fixes in sandboxes
  - persisting conclusions to avoid repeated investigation
- Escalate cleanly when user action is required, using notifications with stable IDs and evidence refs.

## Philosophy

- Prefer diagnosis over killing: timeouts trigger investigation, not immediate termination.
- PAUSE is a control-plane primitive, not a best-effort signal.
- Repairs must be auditable: every repair is a patch with evidence refs.

## Key decisions

### Investigate-first strategy

Anomaly detection triggers evidence collection and hypothesis formation before intervention.

### PAUSE replaces “kill + restart” as the default control

- Root/UI requests PAUSE.
- Step process is responsible for enforcing PAUSE promptly.
- If the step cannot pause within deadline, it spawns an investigator job.

Killing processes remains an option only when:
- investigator classifies the situation as `needs_shutdown`, or
- a tool subprocess is confirmed to be hung and cannot be stopped cleanly

### Tracing model

- Step logging is always on.
- Dynamic tracing is optional, enabled per-step via durable trace overrides.
- Trace output is stored as `trace` events in the step’s log shard.

## Components

### Root monitor (optional background)

- Watches active runs by reading:
  - WSS run and step docs (status, heartbeat metrics)
  - log shard tails for liveness/progress markers
- Applies control actions:
  - pause/resume coordination
  - trace override changes
- Raises notifications for user-visible issues.

### Step process control thread

Every step process includes a control loop that:

- polls for control actions targeted at its `step_execution_id` or `run_id`
- honors PAUSE within a deadline:
  - stops tool subprocesses
  - flushes and closes open outputs
  - stops WSS mutations
  - writes pause ACK file
- honors RESUME by re-entering execution
- escalates to investigator on inability to pause

### Investigator job

Triggered by:

- pause deadline exceeded
- tool subprocess exceeded duration threshold with no progress
- repeated identical failures with no novelty

Inputs are bounded pointers:

- step log shard path
- relevant WSS docs and artifacts
- current stack revision identifiers
- current tool command, args class, and environment signature
- last N events (bounded)

Outputs are machine-readable:

- `classification`: `resolved` | `needs_user` | `needs_retry` | `needs_shutdown`
- `actions`: concrete operations
- `resume_plan`: path to resume script + WSS patches
- `conclusion_updates`: tool/perf conclusions
- `evidence_refs`

### Workflow-repair agent

- consumes investigator output plus additional evidence
- proposes a fix as a patch on the ticket stack
- validates fix in a sandbox (at least a minimal reproduction)
- writes repair provenance as a WSS artifact and log events
- resumes the paused step (or asks root to resume)

## Evidence and conclusions

### Investigation bundles

When deep investigation is needed, create a self-contained bundle:

- WSS snapshot subset for the run/step
- relevant log shard slices
- pointers to stack revision IDs
- sandbox reproduction script (if created)

Bundle is written under:

```text
workspace/runs/<run_id>/artifacts/investigation/<bundle_id>/
```

### Conclusions lifecycle

Conclusions are persisted and promoted conservatively:

- tool conclusions (known hangs, known flags, known remedies)
- performance conclusions (baseline shifts, known slow calls)

Promotion states:

- `draft` (one observation)
- `confirmed` (reproduced across distinct runs)
- `promoted` (stable signature + successful remediation outcomes)

Conclusions are consulted before spawning new investigations.

## Safety boundaries

Self-healing is bounded by strict constraints:

- repairs must be patches on jj stacks (auditable)
- no destructive operations without explicit user action:
  - force pushes
  - mass deletes
  - irreversible migrations
- sandbox executions are isolated and disposable
- control actions are append-only requests with durable audit trail

## Convergence guards

- progress signature recorded per attempt (error class, stack excerpt, patch hash, reproduction outcome)
- if the same signature repeats without novelty, stop and escalate with consolidated evidence
- oscillation detection: alternating outcomes without producing a stable fix triggers escalation

## References

- Core infrastructure and protocols: Tech_Plan__Core_Infrastructure_&_Data_Model.md
- Core flows: Core_Flows__Project_Management_&_Autonomous_Monitoring.md
- Monitoring UI: Tech_Plan__Monitoring_UI_(Tauri).md
