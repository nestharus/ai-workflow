# Tech Plan: Core Infrastructure & Data Model — Index

- **Doc**: Tech_Plan__Core_Infrastructure.md
- **Updated**: 2026-01-26
- **Component**: Core / Storage / Protocol
- **Primary responsibility**: Durable truth (**WSS + Logs + Queues**) and minimal runtime primitives with **high trust** and **low friction**.

This document is an **index**. The authoritative library specs live under:

- `Tech_Plan__Core_Infrastructure/`

## Library map (code packages → spec files)

| Library (suggested package) | Responsibility | Spec |
|---|---|---|
| `workflow_engine.core.foundation` | Canonical terminology, product priorities, global invariants | `Tech_Plan__Core_Infrastructure/00_Foundation.md` |
| `workflow_engine.runtime.root` | Runtime root layout and platform tier durability expectations | `Tech_Plan__Core_Infrastructure/01_Runtime_Root_Layout.md` |
| `workflow_engine.runtime.identity` | `repo_uid` derivation, persistence, and collision handling | `Tech_Plan__Core_Infrastructure/02_Repo_UID_Identity.md` |
| `workflow_engine.core.ids` | ULIDs, ID classes, timestamps | `Tech_Plan__Core_Infrastructure/03_IDs_and_Time.md` |
| `workflow_engine.storage.wss` | Workspace State Store (WSS) data model + update mechanism | `Tech_Plan__Core_Infrastructure/04_WSS_Workspace_State_Store.md` |
| `workflow_engine.core.concurrency` | Ownership rules, optimistic concurrency, cross-process locks | `Tech_Plan__Core_Infrastructure/05_Multi_Writer_Correctness.md` |
| `workflow_engine.durability` | Atomic write protocol + write-ahead journals (WAJ) + deterministic recovery | `Tech_Plan__Core_Infrastructure/06_Durability_Protocol.md` |
| `workflow_engine.storage.logs` | Sharded JSONL logs + integrity chain + corruption rules | `Tech_Plan__Core_Infrastructure/07_Logs_Store.md` |
| `workflow_engine.storage.queues` | Maildir-like durable queues (notifications + control actions) | `Tech_Plan__Core_Infrastructure/08_Queues_Notifications_and_Control_Actions.md` |
| `workflow_engine.control.pause` | Mandatory PAUSE contract (durable + auditable) | `Tech_Plan__Core_Infrastructure/09_Mandatory_Pause_Protocol.md` |
| `workflow_engine.config` | TOML configuration system + precedence + model routing | `Tech_Plan__Core_Infrastructure/10_Configuration_System.md` |
| `workflow_engine.maintenance.gc` | Retention and garbage collection (explicit, evidence-preserving) | `Tech_Plan__Core_Infrastructure/11_Retention_and_GC.md` |
| `workflow_engine.privacy` | Secrets storage + network policy + redaction + export scrubber | `Tech_Plan__Core_Infrastructure/12_Privacy_Secrets_and_Export.md` |
| `workflow_engine.dependencies` | `doctor` + `bootstrap` + tool fingerprints + env capture | `Tech_Plan__Core_Infrastructure/13_Dependency_Management.md` |
| `workflow_engine.migrations` | Schema compatibility + explicit migrations | `Tech_Plan__Core_Infrastructure/14_Schema_Compatibility_and_Migrations.md` |
| `workflow_engine.maintenance.integrity` | `fsck` and `recover` tools (integrity + deterministic repair) | `Tech_Plan__Core_Infrastructure/15_Integrity_and_Recovery_Tools.md` |
| `workflow_engine.risk` | Residual risk register and controls | `Tech_Plan__Core_Infrastructure/16_Risk_Register.md` |

## Recommended reading order

1. `00_Foundation.md` (terms + invariants)
2. `01_Runtime_Root_Layout.md` and `02_Repo_UID_Identity.md`
3. `03_IDs_and_Time.md`
4. `04_WSS_Workspace_State_Store.md` and `05_Multi_Writer_Correctness.md`
5. `06_Durability_Protocol.md`
6. `07_Logs_Store.md` and `08_Queues_Notifications_and_Control_Actions.md`
7. `09_Mandatory_Pause_Protocol.md`
8. `10_Configuration_System.md` and `11_Retention_and_GC.md`
9. `12_Privacy_Secrets_and_Export.md`
10. `13_Dependency_Management.md`
11. `14_Schema_Compatibility_and_Migrations.md`
12. `15_Integrity_and_Recovery_Tools.md`
13. `16_Risk_Register.md`

## Section crosswalk (monolithic → split)

| Original section | New location |
|---|---|
| §0, §0.1, §1 | `00_Foundation.md` |
| §2 | `01_Runtime_Root_Layout.md` |
| §3 | `02_Repo_UID_Identity.md` |
| §4 | `03_IDs_and_Time.md` |
| §5 | `04_WSS_Workspace_State_Store.md` |
| §6 | `05_Multi_Writer_Correctness.md` |
| §7 | `06_Durability_Protocol.md` |
| §8 | `07_Logs_Store.md` |
| §9 | `08_Queues_Notifications_and_Control_Actions.md` |
| §10 | `09_Mandatory_Pause_Protocol.md` |
| §11 (except §11.5) | `10_Configuration_System.md` |
| §11.5 | `11_Retention_and_GC.md` |
| §12 | `12_Privacy_Secrets_and_Export.md` |
| §13 | `13_Dependency_Management.md` |
| §14 | `14_Schema_Compatibility_and_Migrations.md` |
| §15 | `15_Integrity_and_Recovery_Tools.md` |
| §16 | `16_Risk_Register.md` |

## Cross-library contracts (high-signal pointers)

- **Durable truth** is the union of:
  - **WSS** (`storage.wss`)
  - **Logs Store** (`storage.logs`)
  - **Queues** (`storage.queues`)
  - **PGS** / `jj` state (referenced throughout; implemented outside this doc set)

- **Every durable write** MUST use:
  - atomic write protocol (Durability §7.1), and
  - write-ahead journal for critical mutations (Durability §7.2).

- **All durable IDs** for runs/executions/ops are ULIDs (IDs §4.1).

- **Multi-writer correctness** is enforced via:
  - ownership map + `expected_rev` rules (Multi-writer §6.1–§6.2), and
  - cross-process lockfiles for serialized operations (Multi-writer §6.3).

- **Mandatory PAUSE** is a hard contract across runtime + steps (Pause §10); it depends on:
  - tool subprocess cancellability,
  - logs flushed to safe boundaries, and
  - durable acknowledgements via control actions queue.

- **Error recovery playbooks** provide user-facing operational guidance for all error codes defined in Logs Store §8.2.5. See `Tech_Plan__Error_Recovery_Playbooks.md`.
