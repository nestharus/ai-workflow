# Component: COM-05 — LinterStalenessManager

Sources: [requirements.md](../requirements.md) | [design-map.md](../design-map.md)

## Capabilities

- CAP-05 — Linter staleness tracking and refresh gating
  Derived-from: (GOAL-04)

## Surface: SUR-05

Contracts: ()

## State Holders (IAR-XX)

### IAR-05 — Linter staleness registry

Owner: (COM-05)
Kind: table
Invariants: (INV-06)
Access obligations: (OBL-25)
Cross-references: (requires: INV-06; satisfies: GOAL-04)
Details: [design-map.md](../design-map.md)

## Algorithms (ALG-XX)

### ALG-05: Staleness state machine + refresh-only preparation

Owner: (COM-05)
Guarantees: (INV-06)
Cross-references: (requires: INV-06, PROC-04, PROC-05; satisfies: GOAL-04)

```mermaid
stateDiagram-v2
  [*] --> ACTIVE

  ACTIVE --> STALE: mark_stale(blocked-by≠∅)
  ACTIVE --> PENDING_REFRESH: mark_stale(blocked-by=∅)

  STALE --> STALE: mark_stale(update blocked-by)
  STALE --> PENDING_REFRESH: on_lock_released() when blocked-by becomes ∅

  PENDING_REFRESH --> STALE: refresh-only preparation finds blockers (PROC-04)
  PENDING_REFRESH --> ACTIVE: on_linter_run_success()
  PENDING_REFRESH --> FAILED: on_linter_run_failure() (PROC-05)

  FAILED --> ACTIVE: on_linter_run_success()
  FAILED --> PENDING_REFRESH: retry-allowed AND blockers=∅ (optional)
  FAILED --> STALE: retry-allowed AND blockers≠∅ (optional)
```

```mermaid
flowchart TD
  %% Cross-references: (requires: PROC-04)
  PR0["Prepare refresh-only tick"] --> PR1["Collect linters pending refresh"]
  PR1 --> PR2["For each pending linter: compute current blockers"]
  PR2 --> PR3{Blockers empty?}
  PR3 -->|Yes| PR4["Keep linter pending refresh"]
  PR3 -->|No| PR5["Revert linter to stale (blocked-by = blockers)"]
  PR4 --> PR2
  PR5 --> PR2
  PR2 --> PR6["Return whether any linter remains pending refresh"]
```
