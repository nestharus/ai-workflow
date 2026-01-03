# Component: COM-03 — FileDiscoveryDomain

Sources: [requirements.md](../requirements.md) | [design-map.md](../design-map.md) | [plan.md](../plan.md) | [architecture.md](architecture.md) | [components architecture.md](../../../../processes/components/architecture.md)

Implements: (ALG-03)
Cross-references: (uses: RES-03; requires: EXEC-02, IN-06, INV-02; satisfies: GOAL-01)

## Capabilities

- CAP-03 — Produce a deterministic candidate fileset for the run.
  Derived-from: (GOAL-01, GOAL-04)

## Surface: SUR-03

Contracts: (CON-02)

- CON-02 — Discover files. Spec: [design-map.md#contract-con-02-discover-files](../design-map.md#contract-con-02-discover-files)

## State holders (IAR-XX)

- IAR-01 — Run args (mode selection inputs)
- IAR-03 — File discovery result

## Algorithms (ALG-XX)

### ALG-03 — File discovery pipeline

Guarantees: (INV-02, INV-03)

```mermaid
flowchart TD
  %% Cross-references: (requires: EXEC-02, IN-06, INV-02, INV-03)
  A([Start]) --> B{File discovery mode?}
  B -- changed-only --> C["Run git diff (name-only)"]
  B -- commit --> D["Run git diff-tree (name-only)"]
  B -- explicit --> E["Use explicit file list (from run args)"]
  B -- whole-repo --> F["Run git ls-files"]

  C --> P
  D --> P
  E --> P
  F --> P

  P["Normalize paths to repo-relative"] --> Q["Dedupe (preserve order)"]
  Q --> R["Apply ignore patterns (optional)"]
  R --> S["Filter by filesystem existence checks (INV-03)"]
  S --> T["Sort deterministically"]
  T --> U{files empty?}
  U -- Yes --> U1["Return IAR-03 with empty + warning or error (mode-dependent)"]
  U -- No --> V["Return IAR-03 (files + warnings/errors)"]
```

### Helper — Existence-only filter for drift handling

```mermaid
flowchart TD
  %% Cross-references: (requires: INV-03)
  A([Start]) --> B["Filter to paths that exist on disk (existence checks only)"] --> C([Return filtered list])
```
