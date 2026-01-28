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
