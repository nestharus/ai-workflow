# Component: COM-12 — InvestigationWorkflow

Sources: [requirements.md](../requirements.md) | [design-map.md](../design-map.md)

## Capabilities

- CAP-12 — Investigation processing workflow
  Derived-from: (GOAL-03)

## Surface: SUR-12

Contracts: (CON-02)

Calls: (CON-11, CON-12)

## Contracts (CON-XX)

### Contract: CON-02

Surface: (SUR-12)
Interaction: request-response
Guarantees: (INV-04, INV-05)
Demands: (OBL-02)

Pattern: in-process call
Between: (COM-14, COM-12)
For: (ART-04, IAR-04, IAR-03, IAR-01, IAR-02, IAR-05)
Implements: (ALG-12, INV-04, INV-05, GOAL-03)
Cross-references: (requires: INV-04, INV-05; satisfies: GOAL-03)
Needs: ()

Input MUST include (IDs only; no schema fields/types):

- CTX-11 — Completed investigation results (target + start snapshot + payload)
- CTX-02 — Excluded linters set (staleness)
- CTX-48 — CAS verification capability for the start snapshot

Output MUST include (IDs only; no schema fields/types):

- CTX-50 — State updates reflecting investigation outcomes
- CTX-51 — Triggered lint refresh when investigator changes are applied

Boundary obligations:

- OBL-02 — Apply investigation results only under CAS safety
  Cross-references: (requires: INV-04; satisfies: GOAL-02, GOAL-03)

## Algorithms (ALG-XX)

### ALG-12: Poll and process investigations (CAS-gated)

Owner: (COM-12)
Guarantees: (INV-04, INV-05)
Cross-references: (requires: INV-04, INV-05; satisfies: GOAL-03)

```mermaid
flowchart TD
  %% Cross-references: (requires: INV-04, INV-05)
  IW0["Poll and process"] --> IW1["Poll completed results from coordinator"]
  IW1 --> IW2{Any completed results?}
  IW2 -->|No| IW3["Return (no-op)"]
  IW2 -->|Yes| IW4["For each completed result"]

  IW4 --> IW5["Release lock in staleness manager (may create pending refresh linters)"]
  IW5 --> IW6{Result status indicates modifications?}

  %% MODIFIED
  IW6 -->|Yes| M0["CAS gate: verify start snapshot unchanged"]
  M0 --> M1{Safe to apply?}
  M1 -->|No| M2["Treat as external change and route through ExternalChangeWorkflow"] --> IW4

  M1 -->|Yes| M3["Apply investigator patch"]
  M3 --> M4{Patch produces an actual diff?}
  M4 -->|No| M5["Mark target unlintable (investigator modified but no diff)"] --> IW4

  M4 -->|Yes| M6["Snapshot after patch"]
  M6 --> M7["Record snapshot as seen; reset stall candidates conservatively"]
  M7 --> M8["Trigger post-change lint refresh"] --> IW4

  %% NO_OP / FAILURE
  IW6 -->|No| N0{Result is NO_OP or FAILURE?}
  N0 -->|Yes| N1["CAS gate: verify start snapshot unchanged"]
  N1 --> N2{Safe to trust?}
  N2 -->|No| N3["Treat as external change and route through ExternalChangeWorkflow"] --> IW4
  N2 -->|Yes| N4["Mark target unlintable (reason = NO_OP or FAILURE)"] --> IW4
  N0 -->|No| IW4
```
