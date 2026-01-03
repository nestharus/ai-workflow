# Component: COM-14 — Orchestrator

Sources: [requirements.md](../requirements.md) | [design-map.md](../design-map.md) | [architecture.md](architecture.md)

## Capabilities

- CAP-14 — Orchestrator composition loop
  Derived-from: (GOAL-01, GOAL-06)

## Surface: SUR-14

Contracts: ()

Calls: (CON-01, CON-02, CON-03, CON-04, CON-05, CON-06, CON-07, CON-08, CON-09, CON-10)

## Algorithms (ALG-XX)

### ALG-14: Orchestration tick loop (composition-only)

Owner: (COM-14)
Guarantees: (INV-03)
Cross-references: (requires: INV-03, INV-04, INV-06, PROC-08, PROC-09, PROC-10, PROC-13; satisfies: GOAL-01)

```mermaid
flowchart TD
  %% Cross-references: (satisfies: GOAL-01)
  O0["Start"] --> O1["CON-01: init (initial diagnostics + state init)"]
  O1 --> O2["Loop until termination decision"]

  O2 --> O3{Fail-fast abort? (INV-03)}
  O3 -->|Yes| O4["CON-10: emit report"] --> O5["ABORT"]
  O3 -->|No| O6["CON-02: process completed investigations"]

  O6 --> O7{Any linter pending refresh-only?}
  O7 -->|Yes| O8["CON-05: refresh-only lint tick (PROC-04, PROC-05)"]
  O7 -->|No| O9["Skip refresh-only tick"]

  O8 --> O10["Granular pending dispatch (PROC-08, PROC-09)"]
  O9 --> O10

  O10 --> O11["CON-03: compute actionability plan"]
  O11 --> O12{Any actionable work?}

  O12 -->|No| O13["Idle wait/select (PROC-10)"] --> O14["CON-08: termination decision"] --> O15{CONTINUE?}
  O15 -->|Yes| O2
  O15 -->|No| O16["CON-10: emit report"] --> O17["Return SUCCESS or ABORT"]

  O12 -->|Yes| O18["CON-04: agent run (CAS gated)"]
  O18 --> O19{CAS_FAILED?}
  O19 -->|Yes| O20["CON-09: external change apply"] --> O14
  O19 -->|No| O21["CON-05: post-change lint tick"]
  O21 --> O22["CON-06: plan investigations from stalls"]
  O22 --> O23["CON-07: dispatch investigations (if any)"]
  O23 --> O14
```
