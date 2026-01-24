# Tech Plan: Project & Ticket Management

## Overview

This spec defines the **Project Manager** and **Ticket Manager** commands, the task decomposition system, and the ticket lifecycle under the updated architecture:

- durable WSS documents as the workspace source of truth
- sharded JSONL logs for execution evidence
- jj Patch-Stream change stacks for code changes
- sandboxes for tooling

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

- Provide a snappy local UX for:
  - listing and selecting projects and tickets
  - loading and browsing planning docs
  - coordinating execution across tickets and tasks
- Preserve context across step-by-step execution via durable state and logs.
- Make ticket work independent and parallelizable without persistent worktrees.
- Make completion deterministic:
  - validate in sandboxes
  - export stacks into the target branch policy

## Philosophy

- Planning docs and execution evidence are durable, inspectable files.
- Tickets map to change stacks; tasks and steps map to patch creation.
- Use progress-based circuit breakers instead of max-iteration caps.

## Data Model Surface (WSS + jj)

### WSS documents (authoritative)

- `workspace/projects/<project_id>/project.json`
- `workspace/tickets/<ticket_id>/ticket.json`
- `workspace/tickets/<ticket_id>/tasks/<task_id>/task.json`
- `workspace/runs/<run_id>/` (execution evidence pointers) (execution evidence pointers)

### jj (authoritative for code changes)

- `ticket_id` is mapped to a jj change stack (via metadata in `ticket.json`)
- patches created during step execution are stored as jj changes

## Project Manager (`/project-manager`)

### Responsibilities

- Create and select projects.
- Import planning docs (specs, tickets) by paste or file path.
- Maintain a keyword-searchable index of projects and tickets.
- Infer and store ticket dependencies and suggested ordering.
- Emit the “open ticket manager” command for the selected ticket.
- Act as the QA interface for out-of-band notifications:
  - show unresolved notifications
  - write control actions (ack, retry, resume) in response to user input

### Project creation

When creating a new project:

1. Create `workspace/projects/<project_id>/project.json`
2. Create a project docs directory `workspace/projects/<project_id>/docs/`
3. Add project entry to `workspace/index.json` (optional derived index)

Project Manager does not need to create a persistent worktree. The project’s “code baseline” is represented by jj parent revisions and ticket stacks.

### Project listing and search

- Search is over WSS metadata (project and ticket titles/names).
- Fuzzy, case-insensitive match is sufficient.
- Logs are not part of project/ticket search.

## Ticket Manager (`/ticket-manager --project <project_id> --ticket <ticket_id>`)

### Responsibilities

- Create or open a ticket.
- Manage tasks for the ticket.
- Execute tasks as step sequences that produce patches on the ticket’s jj stack.
- Coordinate sandbox validation.
- Raise notifications on failures and block ticket completion until resolved.

### Ticket creation (Patch-Stream)

On first open, Ticket Manager:

1. Creates `workspace/tickets/<ticket_id>/ticket.json`
2. Creates a jj change stack linked to `ticket_id`:
   - parent revision is the project baseline (or selected branch head)
3. Stores stack metadata in `ticket.json`

Ticket doc fields (minimum):

- `project_id`, `ticket_id`, `title`
- `stack_id` or jj metadata required to locate the stack
- `status` (`open`, `in_progress`, `blocked`, `done`)
- `ordering` (dependency info)
- `created_at`, `updated_at`

## Task lifecycle

### Task creation

- User pastes a complete task description.
- Ticket Manager creates:

```text
workspace/tickets/<ticket_id>/tasks/<task_id>/
  task.json
  input.md
  steps/
  deviations/
  evaluation/
```

### Task decomposition system

The multi-pass decomposition system remains, but its state and artifacts move to WSS + log shards.

- Pattern discovery agent identifies boundary patterns and emits a surfacing rule.
- Candidate surfacing script proposes split points.
- Approval agent approves or denies split candidates.
- Verification agent checks for multi-step files.

**No fixed max iterations**:

- repeat detection: identical input hash + identical candidate set + identical decision twice → mark unsplittable and emit a problem record
- novelty requirement: each additional pass must add new evidence or terminate
- oscillation detection: alternating decisions without producing valid split artifacts → stop and escalate

All decomposition events are logged to the run’s log shards; decomposition artifacts are stored under `steps/`.

## Task execution workflow

Task execution is sequential over steps, producing patches on the ticket’s stack.

For each step:

1. Context manager hydrates relevant files and computes the incremental diff (previous patch to current patch).
2. Step execution agent generates a patch:
   - Mode A: blind patch editor (hydrate, edit, apply patch)
   - Mode B: sandbox editor (hydrate sandbox, run tools, capture diff)
3. Patch is applied to the jj stack and recorded as a new change.
4. Deviations from the plan are recorded under `deviations/` and logged as events.
5. Step emits `step_stop` with status.

After all steps:

- run implementation review in a sandbox against the task plan and deviations
- write evaluation artifacts under `evaluation/`
- raise notification on failure (with refs to run/step IDs and artifact paths)

## Ticket completion

Ticket completion policy is explicit and sandbox-backed.

1. Run full sandbox validation for the ticket stack (lint/tests/build as configured).
2. If validation fails:
   - write evaluation report under WSS
   - raise notification and block completion
3. If validation passes:
   - export the ticket stack into the target branch according to policy:
     - `squash` or `linear`
   - record export artifact references in `ticket.json`
   - mark ticket status `done`

## Artifact export

Artifacts are exported from WSS:

- planning docs (specs, tickets, tasks)
- deviations and evaluation reports
- conflict resolution records
- investigation bundles (if any)

Export destination is under the runtime root (example):

```text
~/.workflow/repos/<repo_uid>/exports/<project_id>/<timestamp>/
```

## References

- Core infrastructure: Tech_Plan__Core_Infrastructure_&_Data_Model.md
- Core flows: Core_Flows__Project_Management_&_Autonomous_Monitoring.md
- Enhanced rebase: Tech_Plan__Enhanced_Rebase_&_Evaluation.md
