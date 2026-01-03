# Component: COM-05 — SchedulingDomain

Sources: [requirements.md](../requirements.md) | [design-map.md](../design-map.md) | [plan.md](../plan.md) | [architecture.md](architecture.md) | [components architecture.md](../../../../processes/components/architecture.md)

Implements: (ALG-05)
Cross-references: (requires: INV-04, PROC-04, PROC-05, PROC-06, PROC-07, PERF-02; satisfies: GOAL-02)

## Capabilities

- CAP-05 — Build deterministic, conflict-free phases and ARG_MAX-safe chunks.
  Derived-from: (GOAL-02, GOAL-04)

## Surface: SUR-05

Contracts: (CON-04)

- CON-04 — Build schedule. Spec: [design-map.md#contract-con-04-build-schedule](../design-map.md#contract-con-04-build-schedule)

## State holders (IAR-XX)

- IAR-01 — Run args (commit mode + concurrency cap)
- IAR-02 — Runtime facts (ARG_MAX budgeting inputs)
- IAR-04 — File registry (instances + fileset cache)
- IAR-05 — Scheduling result (phases + items)

## Algorithms (ALG-XX)

### ALG-05 — Build a deterministic, conflict-free schedule

Guarantees: (INV-02, INV-04)

```mermaid
flowchart TD
  %% Cross-references: (requires: INV-04, PROC-04, PROC-05, PROC-06, PROC-07)
  A([Start]) --> B{Commit mode and any mutating linter?}
  B -- Yes --> B1["Record scheduling error (commit mode forbids mutators)"] --> Z([Return scheduling error])
  B -- No --> C["Drop empty filesets (mark non-applicable)"]

  C --> D["Classify linters: mutating | read-only parallel-safe | read-only sequential"]
  D --> E["Sort mutators deterministically\n(priority, then name)"]
  E --> F["Pack mutators into phases by disjoint resource sets\n(scope-aware)"]
  F --> G["Create phases:\n- each read-only sequential linter gets its own phase\n- final phase runs all read-only parallel-safe linters together"]

  G --> H["For each phase, build scheduled chunk items in deterministic order"]
  H --> I["Fetch per-instance filesets from file registry (IAR-04)"]
  I --> J["Chunk each fileset for command-size budget (PROC-06)"]
  J --> K["Assign contiguous chunk sequence IDs (PROC-07)\n+ mark snapshot-needed for mutator chunks (SR-04)"]
  K --> L([Return phases + skipped + warnings/errors])
```

### Helper — ArgMaxChunker

```mermaid
flowchart TD
  %% Cross-references: (requires: PROC-06)
  A([Start]) --> B["Compute per-invocation command-size budget\n(ARG_MAX - base command - environment - safety margin)"]
  B --> C{Budget valid (> 0)?}
  C -- No --> C1["Record scheduling error (budget exhausted before files)"] --> Z([Stop])
  C -- Yes --> D["Iterate fileset in deterministic order"]
  D --> E{Any single path exceeds budget?}
  E -- Yes --> E1["Record scheduling error (single path exceeds budget)"] --> Z
  E -- No --> F["Accumulate paths into chunks until next path would exceed budget"]
  F --> G["Emit chunks in order"]
  G --> H([Return chunks])
```
