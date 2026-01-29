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
* `show-stack [--graph] [--limit <n>] [--refresh]` — show the ticket's Patch-Stream stack (see `project_ticket_system/Lib__Patch_Stack_Visualization.md`)
* `diff [--patch <change_id>] [--stat] [--context <n>]` — show diff for the stack or a single patch (see `project_ticket_system/Lib__Patch_Stack_Visualization.md`)
* `list-patches [--limit <n>] [--format table|json] [--refresh]` — list ordered patches with export status (see `project_ticket_system/Lib__Patch_Stack_Visualization.md`)
* `undo-last [--dry-run] [--note "reason"]` — undo the most recent patch application
  - Delegates to: `workflowctl ticket undo-last <current_ticket_id>`
* `reset --to <rev> [--confirm] [--note "reason"]` — reset the ticket stack to a prior revision (**destructive pointer move**)
  - Delegates to: `workflowctl ticket reset <current_ticket_id> --to <rev>`
* `step rerun <step_id> [--mode A|B] [--note "reason"]` — rerun a specific planned step
  - Delegates to: `workflowctl step rerun <current_ticket_id> <current_task_id> <step_id>`
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

### `workflowctl tickets detect-overlap --active`

**Purpose**: Early-warning detection of file conflicts between active tickets

**Behavior**:
1. Query all tickets with status `in_progress`
2. Load `changed_paths[]` from each ticket's `ticket.json` (see `wss_surfaces` §2.1)
3. Compute pairwise intersections of `changed_paths` sets
4. Emit warnings for any overlapping paths:
   ```
   WARNING: Tickets <ticket_A> and <ticket_B> both modify:
     - src/module/file.py
     - tests/test_file.py
   ```
5. Exit with status 0 (informational only; does NOT block work)

**Flags**:
- `--active`: Only check tickets in `in_progress` status (default)
- `--all`: Check all non-terminal tickets (`open`, `in_progress`, `blocked`)
- `--json`: Output in JSON format for scripting

**Output Format (JSON)**:
```json
{
  "overlaps": [
    {
      "tickets": ["ticket_A", "ticket_B"],
      "paths": ["src/module/file.py", "tests/test_file.py"]
    }
  ]
}
```

This command is informational-only; the normative overlap detection semantics are defined by `tm` §4.2.3.

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

## 7) `workflowctl` ticket Patch-Stream inspection commands (normative)

These commands provide observability into the jj-backed patch stack for a ticket.

Authoritative contract:
- `project_ticket_system/Lib__Patch_Stack_Visualization.md`

### 7.1 `workflowctl ticket show-stack`

Purpose: print ticket base/tip revs and a jj log view of the ticket stack.

Required arguments:
- `--ticket <ticket_id>`

### 7.2 `workflowctl ticket diff`

Purpose: print a diff for the entire stack or a specific patch.

Required arguments:
- `--ticket <ticket_id>`

### 7.3 `workflowctl ticket list-patches`

Purpose: print ordered patch ids + summaries + exported status.

Required arguments:
- `--ticket <ticket_id>`

## 8) `workflowctl` rollback commands (NEW; normative)

Rollback commands are **loud** operations that MUST preserve evidence and MUST
append a history entry to `workspace/tickets/<ticket_id>/ticket.json.history[]`
per `Tech_Plan__Core_Infrastructure/04_WSS_Workspace_State_Store.md` §5.4.3.

### 8.1 `workflowctl ticket undo-last`

Undo the most recent patch application on a ticket stack.

```text
workflowctl ticket undo-last <ticket_id> [--dry-run] [--note <string>]
```

### 8.2 `workflowctl ticket reset`

Reset the ticket stack pointer to a prior revision (requires explicit confirmation).

```text
workflowctl ticket reset <ticket_id> --to <rev> [--confirm] [--note <string>]
```

**Safety warning (normative)**: This command MUST create a safety bookmark before
moving the ticket pointer, and MUST refuse to run without explicit confirmation.

### 8.3 `workflowctl step rerun`

Re-run a specific planned step while preserving the original execution artifacts.

```text
workflowctl step rerun <ticket_id> <task_id> <step_id> [--mode A|B] [--note <string>]
```
