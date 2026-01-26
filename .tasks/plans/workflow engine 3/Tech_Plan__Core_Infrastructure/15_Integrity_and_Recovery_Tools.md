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

Outputs:
- durable report artifact + notification if corruption is detected

### 15.2 `workflowctl recover`

Recovery actions:
- finalize or roll back incomplete journaled operations
- requeue orphaned processing items after TTL
- cleanup stranded tmp files
- optionally rebuild derived index

All recovery actions are logged and bundled as evidence.

