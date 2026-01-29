# Core Infrastructure — Integrity and Recovery Tools

- **Doc**: Tech_Plan__Core_Infrastructure/15_Integrity_and_Recovery_Tools.md
- **Updated**: 2026-01-26
- **Library**: `workflow_engine.maintenance.integrity`
- **Depends on**: [`00_Foundation.md`](00_Foundation.md), [`04_WSS_Workspace_State_Store.md`](04_WSS_Workspace_State_Store.md), [`06_Durability_Protocol.md`](06_Durability_Protocol.md), [`07_Logs_Store.md`](07_Logs_Store.md), [`08_Queues_Notifications_and_Control_Actions.md`](08_Queues_Notifications_and_Control_Actions.md)
- **Primary responsibility**: Define `fsck` validations and deterministic recovery actions (journals, queues, tmp debris, derived index).

## 15) Integrity and recovery tools (trust requirement)

### 15.1 `workflowctl fsck`

Validations:
- WSS JSON parse + required fields present
- `rev` monotonicity
- log shard parse, seq monotonicity, hash chain verification
- queue directory invariants (no duplicates, no stranded tmp)
- journal invariants (prepare/commit pairs)

Options (v1):
- `workflowctl fsck` — run the standard integrity suite (fast, safe defaults).
- `workflowctl fsck --full` — run all checks including the most expensive validations.
- `workflowctl fsck --check-ownership` — validate ownership map invariants used for multi-writer correctness.
- `workflowctl fsck --check-ulids` — validate ULID invariants (format, uniqueness expectations, and any detected collisions).
- `workflowctl fsck --check-schema` — validate schema versions across durable documents and report unsupported versions.

Outputs:
- durable report artifact + notification if corruption is detected

### 15.2 `workflowctl recover`

Recovery actions:
- finalize or roll back incomplete journaled operations
- requeue orphaned processing items after TTL
- cleanup stranded tmp files
- optionally rebuild derived index

All recovery actions are logged and bundled as evidence.

Options (v1):
- `workflowctl recover` — run deterministic recovery across journals/queues/tmp debris (bounded by policy).
- `workflowctl recover --op <op_id>` — inspect and recover a specific journaled operation by `op_id` (decision tree output is mandatory).
- `workflowctl recover --clear-ownership <resource_id>` — clear a stale ownership record when `fsck --check-ownership` indicates it is safe.

### 15.3 `workflowctl backup` and `workflowctl restore`

Backup and restore provide portable snapshots of durable state.

#### 15.3.1 `workflowctl backup create --output <path.zip>`

Creates a compressed ZIP archive containing:
- `workspace/**` (entire WSS)
- `logs/**` (all JSONL shards)
- `config.toml` (repo-machine-local config)
- `repo.json` (repo_uid metadata)

Excludes:
- `sandboxes/**` (ephemeral)
- `caches/**` (disposable)
- `locks/**` (runtime-only)
- `vcs/**` (jj sidecar)
- Temporary files (`*.tmp`)

Secrets policy:
- Never exports secrets from OS keychain
- Config files may contain secret references (key names), not values
- Backup manifest documents this policy

#### 15.3.2 `workflowctl backup restore <path.zip>`

Restores backup into runtime root for current `repo_uid`:
- Extracts to `~/.workflow/repos/<current_repo_uid>/`
- Runs `workflowctl fsck` after extraction
- Warns if backup `repo_uid` ≠ current `repo_uid`
- Requires `--force-repo-uid-mismatch` to proceed with mismatch

Post-restore validation:
- `workflowctl fsck` ensures integrity
- `workflowctl doctor` validates dependencies

Portability requirements:
- Repo checkout must exist at same or equivalent path
- Dependencies must be installed (`workflowctl doctor` validates)
- Secrets must be reconfigured in OS keychain on target machine
