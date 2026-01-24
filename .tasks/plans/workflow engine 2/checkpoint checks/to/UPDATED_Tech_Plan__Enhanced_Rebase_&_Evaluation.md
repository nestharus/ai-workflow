# Tech Plan: Enhanced Rebase & Evaluation

## Overview

This spec defines:

1. **Enhanced rebase** for jj Patch-Stream ticket stacks with documentation-aware conflict investigation.
2. **Evaluation** as sandbox-based gap analysis (no persistent evaluation worktree).

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

- Make rebasing a ticket stack a first-class operation with conflict evidence and durable resolution records.
- Reduce repeated conflict confusion by persisting resolution rationale and evidence references.
- Replace evaluation worktrees with disposable evaluation sandboxes that produce durable reports.

## Philosophy

- Rebase is pointer movement plus resolver jobs; conflicts are data, not repo breakage.
- Documentation and prior conclusions inform conflict resolution, not only code context.
- Evaluation outputs are durable artifacts in WSS; the sandbox itself is disposable.

## Enhanced Rebase (jj stack-based)

### Purpose

Rebase a ticket’s change stack onto a new parent revision while:

- detecting conflicts as jj conflict objects
- investigating using WSS planning docs, prior deviations, and prior conflict resolutions
- producing durable resolution records in WSS

### Inputs

- `ticket_id`
- current `stack_id` (from `ticket.json`)
- new parent revision (project baseline updated)

### High-level flow

1. Invoke `jj rebase` (stack pointer move) for the ticket stack.
2. If jj reports conflicts:
   - enumerate conflict objects / conflicted changes
   - create a resolver job per conflict
3. For each conflict:
   - gather evidence:
     - hydrated versions of conflicted files at both sides
     - relevant WSS docs (project, ticket, tasks, deviations)
     - relevant tool conclusions (if any)
     - relevant past conflict resolution records
   - invoke investigator sub-agent to propose a resolution
4. Apply resolution as a new patch on top of the stack (jj change).
5. Write a conflict resolution record under WSS, referencing evidence.
6. If conflict is not resolvable automatically:
   - write an escalated resolution record
   - emit a notification with clear user instructions and artifact references
7. Rebase completes when all conflicts are resolved or escalated.

### Conflict resolution record storage

Store under:

```text
workspace/tickets/<ticket_id>/rebase/conflicts/<resolution_id>.md
```

Resolution record must include:

- resolution_id
- ticket_id
- stack_id
- affected file paths
- resolution_type: `auto` | `manual` | `escalated`
- resolution_text (rationale)
- evidence refs:
  - `run_id`
  - `step_execution_id`
  - log shard ranges (`writer_id`, `seq_start`, `seq_end`)
  - relevant WSS artifact paths

### Conflict resolution types

- **auto**: system resolves automatically and applies a patch
- **manual**: system proposes a recommendation; user chooses between options
- **escalated**: user must create a reconciliation plan; system provides a report and blocks

## Evaluation (sandbox-based)

### Purpose

Produce a final gap report comparing:

- planning docs (project and ticket docs in WSS)
- what was actually implemented (patch stack contents + deviations)

### Evaluation sandbox

- Create an ephemeral sandbox hydrated from the ticket stack (or project aggregate stack).
- Run the configured validation suite:
  - lint
  - tests
  - build
- Collect results and write durable artifacts.

### Gap analysis

Gap analyzer consumes:

- WSS planning docs
- deviations recorded during step execution
- sandbox results and tool output

Outputs a gap report stored in WSS:

```text
workspace/tickets/<ticket_id>/tasks/<task_id>/evaluation/gaps.md
```

Or for project-level evaluation:

```text
workspace/projects/<project_id>/evaluation/<timestamp>/gaps.md
```

If gaps are found:

- emit a notification with the report path
- project manager uses the gaps to create new tickets (manually loaded into WSS)

## References

- Core infrastructure: Tech_Plan__Core_Infrastructure_&_Data_Model.md
- Core flows: Core_Flows__Project_Management_&_Autonomous_Monitoring.md
- Monitoring and conclusions: Tech_Plan__Monitoring_&_Self-Healing.md
