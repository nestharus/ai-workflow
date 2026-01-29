# Core Infrastructure — Workspace State Store (WSS)

- **Doc**: Tech_Plan__Core_Infrastructure/04_WSS_Workspace_State_Store.md
- **Updated**: 2026-01-29
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
      undo/                          # undo-last evidence bundles (tm §5.1)
      reset/                         # reset evidence bundles + safety bookmarks (tm §5.2)
  conclusions/
    <conclusion_id>.json             # conclusion documents (Monitoring §7.3)
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

### 5.4 `workspace/tickets/<ticket_id>/ticket.json` schema (v2)

`ticket.json` is the durable ticket document stored in WSS. It contains:
- lifecycle state (see `project_ticket_system/Lib__Lifecycle.md` §1),
- Patch-Stream stack references (`base_rev`/`tip_rev` + patch IDs),
- export metadata (see `project_ticket_system/Lib__Export.md`).

#### 5.4.1 Minimal shape (normative)

```json
{
  "schema_version": 2,
  "ticket_id": "<ticket_id>",
  "project_id": "<project_id>",
  "created_at": "2026-01-26T00:00:00Z",
  "updated_at": "2026-01-26T00:00:00Z",
  "rev": 1,
  "owned_by": "tm",
  "status": "open|in_progress|blocked|done|abandoned",
  "blocker_kind": "validation_failure|approval_required|missing_dependency|user_input_required",
  "status_history": [],
  "history": [],
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

#### 5.4.3 Rollback `history[]` (NEW; normative)

`history[]` is an **append-only** array of rollback/retry operations performed against a ticket. It exists to:
- preserve auditability (“what was undone / reset / rerun and why”),
- link to durable evidence artifacts,
- support recovery via safety bookmarks (for reset operations).

`history[]` MUST be present in `ticket.json` with a default value of `[]`.

**Append-only rule (normative)**:
- Existing entries in `history[]` MUST NOT be modified, reordered, or deleted.
- Writers MUST append by rewriting the entire array with prior entries preserved + one new entry appended (RFC 7396 treats arrays as scalars).

Each history entry MUST conform to the following JSON schema (normative):

```json
{
  "schema_version": 1,
  "history_id": "<ulid>",
  "action_type": "undo_patch|reset_stack|step_rerun",
  "created_at": "<rfc3339>",
  "created_by": "<actor_id>",
  "before_state": { },
  "after_state": { },
  "evidence_refs": ["<wss artifact path>", "..."],
  "safety_bookmark": "<jj bookmark name>"
}
```

Validation rules (normative):
- `history_id` MUST be a ULID string per `Tech_Plan__Core_Infrastructure/03_IDs_and_Time.md` §4.1.1.
- `action_type` MUST be one of: `undo_patch`, `reset_stack`, `step_rerun`.
- `created_at` MUST be an RFC3339 UTC timestamp ending in `Z` (see IDs and Time §4.2).
- `created_by` MUST be a filename-safe identifier for the actor/session initiating the operation (e.g., `workflowctl`, `tm`, or a user/session id).
- `before_state` and `after_state` MUST be JSON objects; they MAY be empty but MUST be present.
- `evidence_refs` MUST be a non-empty array of WSS-relative paths (strings) pointing to durable evidence artifacts.
- `safety_bookmark` MUST be present ONLY when `action_type == "reset_stack"`.

**Schema versioning note**:
- `ticket.json.schema_version` is bumped to `2` to add `history[]`.
- Writers MUST reject unsupported schema versions per Multi-writer correctness §6.2.

### 5.5 `workspace/conclusions/<conclusion_id>.json` schema (v1)

`workspace/conclusions/<conclusion_id>.json` is the durable conclusion document that stores an evidence-backed “known failure → known fix” record (Monitoring §7).

Storage:
- Path: `workspace/conclusions/<conclusion_id>.json`
- Key: `conclusion_id` (ULID; see `Tech_Plan__Core_Infrastructure/03_IDs_and_Time.md` §4.1.1)

#### 5.5.1 Minimal shape (normative)

```json
{
  "schema_version": 1,
  "conclusion_id": "<ULID>",
  "state": "draft|confirmed|promoted",
  "failure_signature": "<string>",
  "tool_fingerprint": "<optional>",
  "remediation": { },
  "reproductions": [],
  "applications": [],
  "disabled_until": "<RFC3339 or null>",
  "disabled_reason": "<string or null>",
  "stats": { },
  "created_at": "<RFC3339>",
  "updated_at": "<RFC3339>",
  "rev": 1
}
```

#### 5.5.2 Field rules (normative)

- `schema_version` MUST be `1`.
- `conclusion_id` MUST be a ULID string.
- `state` MUST be one of: `draft`, `confirmed`, `promoted` (Monitoring §7).
- `failure_signature` MUST be a stable signature string suitable for grouping repeated incidents.
- `tool_fingerprint` MAY be present to constrain applicability to a specific tool/environment fingerprint.
- `remediation` MUST be a JSON object describing the fix (e.g., workflow id, script recipe, patch recipe). The exact remediation schema is defined in Monitoring §7.x.
- `reproductions[]` MUST be an array of reproduction records with durable evidence refs.
- `applications[]` MUST be an array of application records. Each record MUST include:
  - `timestamp` (RFC3339 UTC, ends in `Z`) — used for rolling-window stats
  - `outcome` (`success|fail`)
  - evidence refs sufficient for audit/promotion/demotion accounting

`disabled_until` / `disabled_reason`:
- `disabled_until` MAY be absent or `null`. When set, it MUST be an RFC3339 UTC timestamp ending in `Z`.
- `disabled_reason` MAY be absent or `null`. When present, it MUST be a non-empty string intended for audit trail.
- Readers MUST treat missing and `null` equivalently (“not disabled” / “no reason”).

`stats`:
- `stats` MUST be a JSON object (may be empty).
- When present, `stats` SHOULD contain the fields defined in §5.5.3.

#### 5.5.3 `stats` object (normative)

`stats` tracks derived effectiveness metrics for a conclusion (aggregated from `applications[]` and/or external evidence).

Allowed fields:
- `total_applications` (int)
- `successful_applications` (int)
- `failed_applications` (int)
- `last_applied_at` (RFC3339 timestamp)
- `avg_resolution_time_ms` (int, optional)
- `most_common_triggers` (array of failure signatures)

Rules:
- `successful_applications + failed_applications` SHOULD equal `total_applications` when all applications are classified.
- `last_applied_at` SHOULD reflect the most recent `applications[].timestamp`.

#### 5.5.4 Backwards validity (normative)

Older conclusion documents that omit `disabled_until`, `disabled_reason`, or `stats` remain valid.
- Missing `disabled_until` MUST be treated as “not disabled”.
- Missing `stats` MUST be treated as `{}`.

#### 5.5.5 Migration (normative)

A schema migration MUST be provided to update existing conclusion documents by:
- adding `disabled_until` and `disabled_reason` (defaults: `null`)
- adding `stats` (default: `{}`)

Backfill:
- When possible, backfill `stats.total_applications`, `stats.successful_applications`, `stats.failed_applications`, and `stats.last_applied_at` by scanning existing `applications[]` entries.
