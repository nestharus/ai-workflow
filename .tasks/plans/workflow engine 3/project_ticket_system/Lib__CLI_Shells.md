# Library: CLI Shells (`cli`)

* **Primary responsibility**: User interaction contract for the two interactive shells and
  their integration with `workflowctl` and the runtime.
* **Depends on**: (none)
* **Used by**: `pm`, `tm`

## 1) Shells

This system exposes two interactive shells:

* `/project-manager` — project-level navigation and ticket triage
* `/ticket-manager` — execute a specific ticket end-to-end

Both shells are line-oriented REPLs that call the same underlying `workflowctl` subcommands.

## 2) Common interaction rules (normative)

* Input parsing:
  * tokens separated by whitespace
  * quoted strings supported with `"` (no nested quotes)
* Every command MUST return either:
  * a success message + any created IDs, or
  * a loud error that includes an error code and a path to evidence.

## 3) `/project-manager` commands (minimum set)

* `help` — show available commands
* `projects list`
* `projects create "<title>"` → prints `project_id`
* `projects open <project_id>` — sets current project context
* `tickets list [--status open|in_progress|blocked|done|abandoned]`
* `tickets create "<title>"` → prints `ticket_id` (created in `open` status; status semantics follow `project_ticket_system/Lib__Lifecycle.md` §1)
* `tickets archive <ticket_id>` (optional)

Integration points:
* Writes to `workspace/projects/<project_id>/project.json` (see `pm`, `wss_surfaces`)
* Writes to `workspace/tickets/<ticket_id>/ticket.json` (see `pm`, `wss_surfaces`)
* May trigger index rebuild (see `indexer`)

## 4) `/ticket-manager` commands (minimum set)

Within a ticket context:

* `help`
* `open <ticket_id>` — loads ticket + stack context (any status transitions MUST follow `project_ticket_system/Lib__Lifecycle.md` §1)
* `status` — show ticket status + current rev
* `plan` — run decomposition (`task_decompose_v1`) and show step plan summary
* `step run <step_id>` — execute a single step (`step_execute_v1`)
* `run` — execute remaining steps in order
* `validate [--skip-test-selection|--force-smoke-only]` — run validation (`ticket_validate_v1`)
* `close` — run validate + evaluation + mark done (if pass; transition semantics follow `project_ticket_system/Lib__Lifecycle.md` §1)
* `pause` / `resume` — write control actions (Core Flows Flow 12)
* `approve-deviation <deviation_id> --approve|--deny [--note "..."]` — respond to a
  deviation request
* `approve-deviation <deviation_id> --extend-ms <ms> [--note "..."]` — extend
  approval timeout independently

**Late approval guidance**: After approving a deviation that required pausing, resume
execution via `workflowctl run resume <run_id> --from-step <step_id>` to restart from
the point where the deviation was recorded.

## 5) Integration with the runtime (normative)

* Long-running commands start a run under `workspace/runs/<run_id>/`.
* The shell streams logs from the run log shards.
* The shell may be detached; progress is observable via:
  * `workflowctl runs list`
  * `workflowctl runs show <run_id>`
  * `workflowctl notifications tail`
  * `workflowctl approve-deviation <deviation_id> --approve|--deny [--note "..."]`
  * `workflowctl approve-deviation <deviation_id> --extend-ms <ms> [--note "..."]`

**Late approval guidance**: After approving a deviation that required pausing, resume
execution via `workflowctl run resume <run_id> --from-step <step_id>` to restart from
the point where the deviation was recorded.

## 6) `workflowctl` ticket status commands (normative)

All ticket status transitions performed by `workflowctl` MUST conform to `project_ticket_system/Lib__Lifecycle.md` §1 (authoritative state machine + recording requirements).

### 6.1 `workflowctl ticket reopen`

Reopen a completed ticket (explicit `done → in_progress`).

Required arguments:
- `--ticket <ticket_id>`
- `--reason <string>`

Optional:
- `--evidence <path>` (repeatable)

Behavior:
- Validates ticket is in `done` state.
- Transitions `done → in_progress` and creates a new `ticket_rev` (never implicit).
- Records the transition per Lifecycle §1 (including the provided reason and evidence refs).

### 6.2 `workflowctl ticket abandon`

Explicitly cancel a ticket (current state → `abandoned`).

Required arguments:
- `--ticket <ticket_id>`
- `--reason <string>`

Behavior:
- Validates ticket is NOT already `done` or `abandoned`.
- Transitions the ticket to `abandoned`.
- Records the transition per Lifecycle §1 (including the provided reason and evidence refs as applicable).
