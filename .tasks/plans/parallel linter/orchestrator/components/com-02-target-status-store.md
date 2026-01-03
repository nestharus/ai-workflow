# Component: COM-02 — TargetStatusStore

Sources: [requirements.md](../requirements.md) | [design-map.md](../design-map.md)

## Capabilities

- CAP-02 — Target status tracking (unlintable, dirty, passed cache)
  Derived-from: (GOAL-01, GOAL-04, GOAL-06)

## Surface: SUR-02

Contracts: ()

## State Holders (IAR-XX)

### IAR-02 — Target status registry

Owner: (COM-02)
Kind: table
Invariants: (INV-03)
Access obligations: (OBL-22)
Cross-references: (requires: INV-03; satisfies: GOAL-01)
Details: [design-map.md](../design-map.md)

## Algorithms (ALG-XX)

### ALG-02: Target status mutations

Owner: (COM-02)
Guarantees: (INV-03)
Cross-references: (requires: INV-03; satisfies: GOAL-01, GOAL-04)

```mermaid
flowchart TD
  %% Cross-references: (requires: INV-03)
  subgraph UL["Unlintable mutations"]
    UL0["Mark target unlintable (with reason)"] --> UL1["Remove target from dirty set"]
    UL2["Clear unlintable mark for targets"] --> UL3["Remove unlintable entries (if present)"]
  end

  subgraph D["Dirty-target tracking"]
    D0["Mark targets dirty (diagnostics invalidated)"] --> D1["Add to dirty set"]
    D2["Clear dirty mark for targets"] --> D3["Remove from dirty set"]
  end

  subgraph P["Passed-cache tracking"]
    P0["Record linter passed for file targets"] --> P1["Add linter to per-file passed set"]
    P2["Clear passed cache for targets"] --> P3{Includes project sentinel?}
    P3 -->|Yes| P4["Clear all passed cache"]
    P3 -->|No| P5["Clear passed cache for the specified file targets only"]
  end
```
