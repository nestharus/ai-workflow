# Library: Lifecycle (`lifecycle`)

- **Primary responsibility**: Ticket/task state machines and concurrency/locking rules for durable status updates.
- **Depends on**: `wss_surfaces`
- **Used by**: `tm`, `decompose`, `execute`, `export`

## 1) Ticket lifecycle (state machine)

Ticket status is durable and updated with optimistic concurrency (`expected_rev`):

`open → in_progress → blocked → done` (plus `abandoned`)

Rules (normative):
- `done` requires validation workflow success (no bypass by default)
- `blocked` requires an explicit reason field + evidence refs

Locking (normative):
- TM MUST perform ticket status transitions under `locks/ticket.<ticket_id>.lock`.

Clarifications (normative):
- Tickets created via `/project-manager tickets create …` start in `open`.
- When `/ticket-manager open <ticket_id>` begins work, it transitions `open → in_progress`.
- If a ticket is created implicitly by Ticket Manager (create+start), it MUST be created directly in `in_progress` and treated as equivalent to `open` followed immediately by `in_progress`.

## 2) Task lifecycle (state machine)

Task status is durable and updated by TM (single-writer under the ticket lock):

`open → decomposing → ready → executing → completed`

Additional terminal / interruption states:
- `needs_user_plan` (decomposition gave up; user must edit/approve plan)
- `failed` (execution failed with evidence; may be retried via new task/run)
- `aborted` (explicit user abort)

Rules (normative):
- `needs_user_plan` is resolved only by an explicit user action (`task approve-plan`) or by re-running decomposition with new constraints.
- Retrying does not “loop”; retries produce new run IDs and MUST add new evidence.

Locking (normative):
- Task lifecycle updates MUST occur under `locks/ticket.<ticket_id>.lock` (single-writer).
- Decomposition additionally requires `locks/task.<ticket_id>.<task_id>.lock` as defined in `decompose`.
