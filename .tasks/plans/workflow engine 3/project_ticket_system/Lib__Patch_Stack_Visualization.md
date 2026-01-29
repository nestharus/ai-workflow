# Library: Patch Stack Visualization (`stack_viz`)

- **Primary responsibility**: Provide CLI observability for a ticket’s jj-backed Patch-Stream stack (structure, dependencies, diffs, export status).
- **Depends on**: `cli`, `wss_surfaces`, `lifecycle`, `export`
- **Used by**: `tm`, `pm`, `workflowctl`

## 1) Command placement & UX (normative)

Patch-stack inspection commands exist in **two forms**:

1. **Non-interactive**: `workflowctl ticket …` (authoritative automation surface)
2. **Interactive ticket shell**: `/ticket-manager …` convenience aliases that call `workflowctl ticket …` using the currently opened ticket context.

Rules (normative):
- `/ticket-manager` aliases MUST NOT implement stack logic directly; they MUST call `workflowctl` as a subprocess (see Integration §2.1.3).
- `workflowctl ticket …` commands MUST accept `--ticket <ticket_id>` (consistent with `workflowctl ticket reopen|abandon`).

## 2) Data source contract (normative)

### 2.1 Authoritative sources

This command set uses the following sources of truth:

- **WSS**: `workspace/tickets/<ticket_id>/ticket.json` for durable ticket + stack references
- **PGS (jj)**: repository state for stack reality (patches, parents, diffs, commit messages)

### 2.2 Required `ticket.json` fields

Required fields for patch-stack visualization are defined in Core Infrastructure (authoritative):
- `Tech_Plan__Core_Infrastructure/04_WSS_Workspace_State_Store.md` (ticket.json schema)

At minimum, visualization requires:
- `ticket.json.stack_bookmark` (string): bookmark that tracks the ticket stack tip (default: `ticket/<ticket_id>`)
- `ticket.json.base_rev` (string): jj `commit_id` representing the ticket base revision
- `ticket.json.tip_rev` (string): jj `commit_id` representing the current stack tip revision
- `ticket.json.patches` (array): ordered list of patch identifiers for the stack (see §5.1)
- `ticket.json.export` (object, optional): export metadata (see `export` library), extended with `source_tip_rev` for per-patch export status (§5.2)

### 2.3 Staleness and refresh semantics

By default, visualization commands:
- **Trust** `ticket.json` for stack identity (`stack_bookmark`/`base_rev`/`tip_rev`/patch list), and
- **Query jj** for any derived display data (log text, patch summaries, diffs).

If required stack fields are missing or inconsistent, commands MUST attempt a jj fallback (§2.4).

Commands MUST NOT mutate `ticket.json` unless `--refresh` is explicitly provided.

### 2.4 Fallback behavior when metadata is missing (normative)

If `ticket.json.stack_bookmark` / `base_rev` / `tip_rev` / `patches` are missing or incomplete:
1. Attempt to resolve the stack via jj using the derived bookmark name `ticket/<ticket_id>`.
2. If the bookmark exists, derive:
   - `tip_rev` = bookmark target revision
   - `base_rev` = first non-ticket ancestor (implementation-defined; must be stable and recorded on refresh)
   - `patches[]` = linear stack order from base → tip (see §5.1)
3. Proceed with display using the derived values.

If the bookmark does not exist, commands MUST fail with `E_NOT_FOUND` (see §6).

## 3) `workflowctl ticket show-stack` (normative)

Purpose: show stack identity + patch ordering + jj log for the ticket stack.

Required arguments:
- `--ticket <ticket_id>`

Options:
- `--graph` (default: false): include an ASCII graph view of the stack (jj-style).
- `--limit <n>` (default: 50): maximum number of patches/log entries displayed.
- `--format text|json` (default: text)
- `--refresh` (default: false): refresh stack metadata from jj and write it back to `ticket.json` (requires `locks/ticket.<ticket_id>.lock`).

Behavior (normative):
1. Load `ticket.json`; resolve stack metadata (§2).
2. Print:
   - `ticket_id`
   - `base_rev`, `tip_rev`
   - export summary (if present): `export.policy`, `export.bookmark`, `export.validated`, `export.source_tip_rev` (if present)
3. Render a patch table (base → tip order) with export markers (see §5.2).
4. Render jj log output:
   - If `--graph`, include a graph view of the same revision range.
   - `--limit` applies to the number of displayed stack revisions (not lines of text).

Example (text, non-graph):
```text
ticket: NES-47
base_rev: 9b1c2d3e4f5a
tip_rev:  8a7b6c5d4e3f
export: policy=squash bookmark=export/NES-47 validated=true source_tip_rev=7f6e5d4c3b2a

PATCHES (base → tip)
  1  rlvvoknq...  Add stack inspection commands              ✓ exported (export/NES-47)
  2  s1x2y3z4...  Document ticket.json stack schema          ✓ exported (export/NES-47)
  3  abcd1234...  Add show-stack/diff/list-patches help      ✗ not exported

LOG (base_rev::tip_rev)
  abcd1234 Add show-stack/diff/list-patches help
  s1x2y3z4 Document ticket.json stack schema
  rlvvoknq Add stack inspection commands
```

## 4) `workflowctl ticket diff` (normative)

Purpose: show a unified diff for the entire stack, or for a specific patch.

Required arguments:
- `--ticket <ticket_id>`

Options:
- `--patch <change_id>` (optional): show diff for a single patch identified by jj `change_id`.
- `--stat` (default: false): show a diffstat summary instead of a full unified diff.
- `--context <n>` (optional): unified diff context lines (implementation maps to jj diff flags).
- `--color auto|always|never` (default: auto)
- `--format text|json` (default: text; `json` is only valid with `--stat`)

Semantics (normative):
- **Entire stack diff** means the net diff from `base_rev` → `tip_rev` (equivalent to “combined diff of all patches”).
- `--patch <change_id>` means the diff introduced by that patch alone (not cumulative).
  - The patch MUST be validated as a member of `ticket.json.patches[]` (or derived equivalent).

Output (normative):
- Default output is unified diff text (or tool-native output when using color).
- With `--stat`, output MUST include changed paths and per-path additions/deletions.

## 5) `workflowctl ticket list-patches` (normative)

Purpose: list ordered patches, their summaries, and their export status.

Required arguments:
- `--ticket <ticket_id>`

Options:
- `--limit <n>` (default: 200): maximum number of patches listed.
- `--format table|json` (default: table)
- `--refresh` (default: false): refresh stack metadata from jj and write it back to `ticket.json` (requires `locks/ticket.<ticket_id>.lock`).

Behavior (normative):
1. Resolve stack metadata (§2).
2. Determine stack order (§5.1).
3. Query jj for patch summaries (first line of description) for each patch.
4. Compute export status (§5.2).
5. Emit a table (or JSON) with columns/fields:
   - `patch` (jj `change_id`)
   - `summary`
   - `exported` (boolean)
   - `export_bookmark` (string|null)

Example output (table):
```text
PATCH                  SUMMARY                                   EXPORTED  BOOKMARK
rlvvoknq...            Add stack inspection commands             yes       export/NES-47
s1x2y3z4...             Document ticket.json stack schema         yes       export/NES-47
abcd1234...            Add show-stack/diff/list-patches help     no        -
```

### 5.1 Patch ordering (normative)

“Ordered” means **stack order: base → tip**.

Definition (normative):
- The patch list MUST represent the linearized first-parent chain from `base_rev` (exclusive) to `tip_rev` (inclusive).
- The ordering MUST be stable across invocations given an unchanged jj graph.

### 5.2 Export status (normative)

Export status is computed as follows:

1. If `ticket.json.export` is missing: all patches are `exported=false`.
2. If `ticket.json.export.source_tip_rev` is present:
   - a patch is exported iff it is part of the stack up to `source_tip_rev` (inclusive) in base → tip order.
   - `export_bookmark` is `ticket.json.export.bookmark`.
3. If `ticket.json.export.source_tip_rev` is missing but `ticket.json.export.bookmark` exists:
   - treat export status as **unknown** and render as `exported=false` with an explanatory note in `show-stack` output.

`source_tip_rev` is required for per-patch exported markers and MUST be recorded by the export implementation when an export succeeds.

## 6) Error handling (normative)

All commands MUST follow CLI error rules (see `cli` §2): a loud error includes an error code and a path to evidence.

Required error cases:

1. Ticket does not exist:
   - `code`: `E_NOT_FOUND`
   - `message`: `Ticket not found: <ticket_id>`
   - `evidence`: expected `workspace/tickets/<ticket_id>/ticket.json`

2. Ticket exists but has no stack (no stack metadata and no `ticket/<ticket_id>` bookmark):
   - `code`: `E_NOT_FOUND`
   - `message`: `Ticket has no Patch-Stream stack yet: <ticket_id>`
   - `evidence`: `workspace/tickets/<ticket_id>/ticket.json`

3. jj is missing / not available:
   - `code`: `E_DEPENDENCY_MISSING` (preferred) or `E_TOOL_FAILED`
   - `message`: `jj is required for patch-stack inspection`
   - `evidence`: `workspace/runs/<run_id>/artifacts/tools/jj/*` (or equivalent tool evidence bundle)

4. `--patch <change_id>` not in the ticket stack:
   - `code`: `E_NOT_FOUND`
   - `message`: `Patch not found in ticket stack: <change_id>`
   - `evidence`: `workspace/tickets/<ticket_id>/ticket.json` + tool log output

## 7) Adapter integration (normative)

All jj interactions MUST be isolated behind the adapter:
- `scripts/core/vcs/jj_adapter.py`

Minimum adapter capabilities required by this spec:
- Resolve bookmark → `commit_id`
- Compute stack range and linearized patch order (base → tip)
- `log_stack(base_rev, tip_rev, graph: bool, limit: int) -> str`
- `diff_stack(base_rev, tip_rev, *, stat: bool, context: int|None, color: str) -> str`
- `diff_patch(change_id, *, stat: bool, context: int|None, color: str) -> str`
- `summaries(change_ids: list[str]) -> dict[change_id, summary_line]`

If new adapter methods are required, they are in scope for the same feature slice as these CLI commands (no deferral).

## 8) Performance considerations (normative)

- `show-stack` default `--limit` MUST cap output to a safe value (default 50).
- `list-patches` default `--limit` MUST cap output to a safe value (default 200).
- Implementations SHOULD avoid N subprocess calls by batching summary/log queries when possible.

## 9) Lifecycle interaction (normative)

These commands MUST work for tickets in any lifecycle state:
- `open`, `in_progress`, `blocked`, `done`, `abandoned`

Notes:
- For `done` tickets, `show-stack` SHOULD include `ticket.json.export` summary prominently.
- For `abandoned` tickets, commands still report the stack if it exists (no implicit deletion).

## 10) Help text / documentation (normative)

`workflowctl help` output MUST include a brief description and examples for:
- `workflowctl ticket show-stack`
- `workflowctl ticket diff`
- `workflowctl ticket list-patches`

Example help excerpt:
```text
workflowctl ticket show-stack --ticket NES-47 [--graph] [--limit 50] [--refresh]
workflowctl ticket diff       --ticket NES-47 [--patch <change_id>] [--stat]
workflowctl ticket list-patches --ticket NES-47 [--limit 200] [--format table|json] [--refresh]
```
