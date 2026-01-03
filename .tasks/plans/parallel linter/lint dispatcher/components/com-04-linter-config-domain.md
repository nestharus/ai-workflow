# Component: COM-04 — LinterConfigDomain

Sources: [requirements.md](../requirements.md) | [design-map.md](../design-map.md) | [plan.md](../plan.md) | [architecture.md](architecture.md) | [components architecture.md](../../../../processes/components/architecture.md)

Implements: (ALG-04)
Cross-references: (requires: INV-01, IN-01, IN-02, IN-03, PROC-01, EXEC-03; satisfies: GOAL-02)

## Capabilities

- CAP-04 — Expand linter specs into operational instances and filesets.
  Derived-from: (GOAL-02)

## Surface: SUR-04

Contracts: (CON-03)

- CON-03 — Configure linter instances and filesets. Spec: [design-map.md#contract-con-03-configure-linters](../design-map.md#contract-con-03-configure-linters)

## State holders (IAR-XX)

- IAR-03 — File discovery result (candidate file list)
- IAR-04 — File registry (instances + fileset cache)

## Algorithms (ALG-XX)

### ALG-04 — Spec expansion, instance identity, filesets, and preflight

Guarantees: (INV-01, INV-02, INV-03)

#### Spec expansion

```mermaid
flowchart TD
  %% Cross-references: (requires: IN-03, INV-02)
  A([Start]) --> B["Initialize expansion accumulator"]
  B --> C["For each selector spec (in CLI order)"]
  C --> D["Parse selector (operator + linter name)"]
  D --> E{Selector valid?}
  E -- No --> E1["Record error (invalid selector / unknown linter)"] --> C
  E -- Yes --> F["Expand via ordered registry (deterministic)"]
  F --> G{Expansion empty?}
  G -- Yes --> G1["Record warning (empty expansion)"] --> C
  G -- No --> H["Append expanded names (stable dedupe)"] --> C
  C --> K([Return expansion result])
```

#### Per-run instance creation

```mermaid
flowchart TD
  %% Cross-references: (requires: IN-01, INV-01)
  A([Start]) --> B["Iterate selected linter names in deterministic order (IN-01)"]
  B --> C["Create per-run linter instance"]
  C --> D["Assign stable per-run instance identity key (INV-01)"]
  D --> B
  B --> E([Return instances])
```

#### Fileset computation and existence-only pruning

```mermaid
flowchart TD
  %% Cross-references: (requires: PROC-01, INV-01)
  A([Start]) --> B["For each linter instance"]
  B --> C["Compute fileset membership from candidate file list (PROC-01)"]
  C --> D["Treat file-not-found races as non-match (PROC-01)"]
  D --> E["Store per-instance fileset in file registry cache (IAR-04)"]
  E --> B
  B --> F([Return updated file registry])
```

```mermaid
flowchart TD
  %% Cross-references: (requires: INV-03)
  A([Start]) --> B["For each cached fileset in file registry (IAR-04)"]
  B --> C["Prune deleted paths using existence checks only (INV-03)"]
  C --> B
  B --> D([Return pruned cache])
```

#### Preflight checks

```mermaid
flowchart TD
  %% Cross-references: (requires: EXEC-03)
  A([Start]) --> B["Select applicable instances (non-empty filesets)"]
  B --> C["Run preflight checks concurrently (bounded workers)"]
  C --> D["Collect per-instance results (ok + message)"]
  D --> E["Drop failed applicable instances; record warnings (EXEC-03)"]
  E --> F([Return updated operational set + preflight diagnostics])
```
