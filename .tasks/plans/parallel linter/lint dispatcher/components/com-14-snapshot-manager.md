# Component: COM-14 — SnapshotManager

Sources: [requirements.md](../requirements.md) | [design-map.md](../design-map.md) | [plan.md](../plan.md) | [architecture.md](architecture.md) | [components architecture.md](../../../../processes/components/architecture.md)

Implements: (ALG-14)
Cross-references: (requires: PROC-09, PROC-11; satisfies: GOAL-03)

## Capabilities

- CAP-14 — Create and restore snapshots for mutator safety.
  Derived-from: (GOAL-03)

## Surface: SUR-14

Contracts: (CON-12, CON-14)

- CON-14 — Snapshot per chunk. Spec: [design-map.md#contract-con-14-snapshot-per-chunk](../design-map.md#contract-con-14-snapshot-per-chunk)
- CON-12 — Restore snapshots. Spec: [design-map.md#contract-con-12-restore-snapshots](../design-map.md#contract-con-12-restore-snapshots)

## State holders (IAR-XX)

- IAR-08 — Snapshot store
- IAR-13 — Inflight task registry

## Algorithms (ALG-XX)

### ALG-14 — Snapshot creation and restore semantics

Guarantees: (INV-04)

#### Snapshot creation (main process, before submit)

```mermaid
flowchart TD
  %% Cross-references: (requires: PROC-09)
  A([Start]) --> B["Allocate snapshot location for this mutator chunk (SNAP-01)"]
  B --> C["For each path in the mutator chunk fileset (stable order)"]
  C --> D{Path exists?}
  D -- No --> C
  D -- Yes --> E["Copy file content into snapshot location atomically"]
  E --> C
  C --> F["Record snapshot location in snapshot store (IAR-08)\nkeyed by chunk identity (SNAP-01)"]
  F --> G([Return snapshot reference])
```

#### Restore all in-flight snapshots (used on fail-fast/SIGINT)

```mermaid
flowchart TD
  %% Cross-references: (requires: PROC-09, PROC-11)
  A([Start]) --> B["For each in-flight task identity in IAR-13 (IF-01)"]
  B --> C["Restore snapshot for that task (SNAP-02)"] --> B
  B --> D([Done])
```
