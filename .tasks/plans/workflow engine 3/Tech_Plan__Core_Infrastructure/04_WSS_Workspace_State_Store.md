# Core Infrastructure — Workspace State Store (WSS)

- **Doc**: Tech_Plan__Core_Infrastructure/04_WSS_Workspace_State_Store.md
- **Updated**: 2026-01-26
- **Library**: `workflow_engine.storage.wss`
- **Depends on**: [`00_Foundation.md`](00_Foundation.md), [`03_IDs_and_Time.md`](03_IDs_and_Time.md), [`06_Durability_Protocol.md`](06_Durability_Protocol.md)
- **Primary responsibility**: Define the durable hierarchical document store for mutable workflow state and non-derivable artifacts.

## 5) Workspace State Store (WSS)

WSS is the durable hierarchical document store for mutable workflow state and artifacts that are not safely re-derivable.

### 5.1 WSS layout (authoritative)

```text
workspace/
  config.toml
  journals/
  index.json                         # derived, optional
  workflows/                         # WSS-scoped workflows (optional, YAML)
  projects/<project_id>/
    project.json
    docs/
    artifacts/
  tickets/<ticket_id>/
    ticket.json
    docs/
    tasks/<task_id>/
      task.json
      input.md
      steps/                         # step definitions (durable plan)
      deviations/
      evaluation/
    rebase/
      conflicts/
  runs/<run_id>/
    run.json
    steps/<step_execution_id>.json        # step_execution_id is ULID execution instance (not semantic step_id)
    artifacts/
      env/                           # env capture, tool versions, fingerprints
      sandbox/                       # lint/test/build outputs (durable)
      investigation/                 # bounded evidence bundles
      scripts/                       # registered scripts (hash-addressed)
  conclusions/
    tools/<tool_fingerprint>/
    perf/<step_signature>/
  trace_overrides/
    overrides.json
```

**Note**: `step_execution_id` is a ULID. For causal ordering, use explicit links (`run_id` + `step_execution_id`), not ULID comparison (see §4.1.2 for ULID monotonicity scope).

### 5.2 Required fields for every durable JSON document

Every durable JSON document MUST include:

- `schema_version: int`
- stable ID field(s) (`ticket_id`, `run_id`, etc.)
- `created_at`, `updated_at`
- `rev: int` (monotonic document revision; starts at 1)
- ownership metadata when relevant:
  - `owned_by` (component role)
  - `writer_id` (if step-owned)

### 5.3 JSON Merge Patch (RFC 7396) as the only update mechanism

All updates to JSON docs use **JSON Merge Patch (RFC 7396)**:
- Patch root MUST be a JSON object; otherwise reject.
- Arrays are treated as scalars (replace entirely) → avoid arrays in multi-writer docs.
- `null` in a patch indicates deletion and MUST NOT be used as a business value.

RFC 7396: https://datatracker.ietf.org/doc/html/rfc7396

### 5.4 `workspace/tickets/<ticket_id>/ticket.json` schema (v1)

`ticket.json` is the durable ticket document stored in WSS. It contains:
- lifecycle state (see `project_ticket_system/Lib__Lifecycle.md` §1),
- Patch-Stream stack references (`base_rev`/`tip_rev` + patch IDs),
- export metadata (see `project_ticket_system/Lib__Export.md`).

#### 5.4.1 Minimal shape (normative)

```json
{
  "schema_version": 1,
  "ticket_id": "<ticket_id>",
  "project_id": "<project_id>",
  "created_at": "2026-01-26T00:00:00Z",
  "updated_at": "2026-01-26T00:00:00Z",
  "rev": 1,
  "owned_by": "tm",
  "status": "open|in_progress|blocked|done|abandoned",
  "blocker_kind": "validation_failure|approval_required|missing_dependency|user_input_required",
  "status_history": [],
  "stack_bookmark": "ticket/<ticket_id>",
  "base_rev": "<jj commit_id>",
  "tip_rev": "<jj commit_id>",
  "patches": [
    { "change_id": "<jj change_id>", "commit_id": "<jj commit_id>" }
  ],
  "export": {
    "policy": "squash|linear",
    "bookmark": "export/<ticket_id>|review/<ticket_id>",
    "exported_tip": "<jj commit_id>",
    "exported_at": "2026-01-26T00:00:00Z",
    "validated": true,
    "source_tip_rev": "<jj commit_id>",
    "no_change": false
  }
}
```

#### 5.4.2 Field rules (normative)

Lifecycle fields:
- `status` MUST be one of the states defined in `project_ticket_system/Lib__Lifecycle.md` §1.1.
- When `status == "blocked"`, `blocker_kind` MUST be present and MUST be one of the enum values defined in Lifecycle §1.1.
- When `status != "blocked"`, `blocker_kind` MUST be absent (do not use `null`).
- `status_history` MUST be a bounded array containing the last N transitions as defined by Lifecycle §1.7.

Patch-Stream stack fields:
- `stack_bookmark`, `base_rev`, `tip_rev`, and `patches` MAY be absent for tickets that have not yet created a Patch-Stream stack (e.g., newly created tickets in `open`).
- When present:
  - `stack_bookmark` MUST be a bookmark name. Default naming convention: `ticket/<ticket_id>`.
  - `base_rev` and `tip_rev` MUST be jj **commit IDs** (not change IDs).
  - `patches` MUST be ordered base → tip and MUST represent the stack’s linearized first-parent chain from `base_rev` (exclusive) to `tip_rev` (inclusive).
  - Each `patches[]` entry MUST include:
    - `change_id` (required): jj change identifier
    - `commit_id` (optional): last observed commit ID for that change

Export fields:
- `export` MAY be absent if the ticket has never been exported.
- When present, `export` MUST conform to `project_ticket_system/Lib__Export.md` and:
  - `source_tip_rev` MUST be recorded on successful export (commit ID of the ticket stack tip at export time). This enables per-patch exported markers.
  - For “no-op export” cases (`base_rev == tip_rev`), `exported_tip` MUST be omitted or absent and `no_change` MUST be `true` (do not use `null`).
