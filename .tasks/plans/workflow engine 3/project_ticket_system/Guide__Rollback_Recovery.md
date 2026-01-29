# Guide: Rollback & Recovery (User-facing)

This guide describes how to use rollback-style commands safely, and how to recover
if you reset to the wrong revision.

## Principles

- Rollback operations preserve evidence. Prior run/step artifacts are never overwritten.
- Every rollback operation appends an entry to `workspace/tickets/<ticket_id>/ticket.json.history[]`.
- Reset operations create a safety bookmark before moving the ticket stack pointer.

## Undo the last patch

Undo the most recent patch on the ticket stack:

```text
workflowctl ticket undo-last <ticket_id> [--dry-run] [--note "<reason>"]
```

Notes:
- Use `--dry-run` to preview what would be undone.
- Evidence is written under `workspace/runs/<run_id>/artifacts/undo/<history_id>/`.

## Reset the ticket stack to a prior revision (with safety bookmark)

Reset the ticket stack pointer to a prior revision:

```text
workflowctl ticket reset <ticket_id> --to <rev> --confirm [--note "<reason>"]
```

What happens:
- The CLI shows current tip, target rev, and how many patches become unreachable from the ticket bookmark.
- A safety bookmark is created at the pre-reset tip:
  - `wf/undo/<ticket_id>/<ulid>`
- Evidence is written under `workspace/runs/<run_id>/artifacts/reset/<history_id>/`.

### Recovery: return to the pre-reset state

Use the safety bookmark printed by the reset command:

```text
jj edit <safety_bookmark>
```

The bookmark name is also stored in:
- `workspace/tickets/<ticket_id>/ticket.json.history[][*].safety_bookmark`
- `workspace/runs/<run_id>/artifacts/reset/<history_id>/safety_bookmark.txt`

## Rerun a step (preserve original attempt)

Rerun a planned step for a given ticket/task:

```text
workflowctl step rerun <ticket_id> <task_id> <step_id> [--mode A|B] [--note "<reason>"]
```

What happens:
- A new `step_execution_id` is generated and written to:
  - `workspace/runs/<run_id>/steps/<step_execution_id>.json`
- The new execution record links back to the prior attempt via `original_step_execution_id`.
- Both the original and rerun artifacts remain queryable via WSS and logs.

