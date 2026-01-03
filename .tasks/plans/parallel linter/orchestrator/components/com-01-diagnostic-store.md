# Component: COM-01 — DiagnosticStore

Sources: [requirements.md](../requirements.md) | [design-map.md](../design-map.md)

## Capabilities

- CAP-01 — Diagnostics indexing and query support
  Derived-from: (GOAL-04, GOAL-05)

## Surface: SUR-01

Contracts: ()

## State Holders (IAR-XX)

### IAR-01 — Diagnostics index

Owner: (COM-01)
Kind: index
Invariants: (INV-02)
Access obligations: (OBL-21)
Cross-references: (requires: INV-02)
Details: [design-map.md](../design-map.md)

## Algorithms (ALG-XX)

### ALG-01: Diagnostics ingestion + queries

Owner: (COM-01)
Guarantees: (INV-02)
Cross-references: (requires: INV-02; satisfies: GOAL-04)

```mermaid
flowchart TD
  %% Cross-references: (requires: INV-02)
  subgraph U["Update linter diagnostics (preserve semantics)"]
    U0["Normalize target identities in new diagnostics"] --> U1{Patch update?}

    U1 -->|No (full replace)| U2["Start from empty linter view"]
    U2 --> U3["Copy preserved targets (locked ∪ unlintable) from current view"]
    U3 --> U4["Insert new diagnostics for all non-preserved targets"]
    U4 --> U5["Persist updated linter view"]

    U1 -->|Yes (patch)| U6["Start from current linter view"]
    U6 --> U7["Insert new diagnostics for all non-preserved targets"]
    U7 --> U8["Remove cleared targets that are neither preserved nor present in new diagnostics"]
    U8 --> U5
  end

  subgraph Q["Query helpers (actionability support)"]
    Q0["Inputs: excluded linters, excluded targets"] --> Q1["Filter excluded linters"]
    Q1 --> Q2["Filter excluded targets"]
    Q2 --> Q3["Drop empty entries"]
    Q3 --> Q4["Return filtered diagnostics view and/or targets-with-errors set"]
  end

  subgraph L["Linters-with-errors for a target (raw view)"]
    L0["Input: target"] --> L1["Return linters that currently report errors for target"]
  end
```
