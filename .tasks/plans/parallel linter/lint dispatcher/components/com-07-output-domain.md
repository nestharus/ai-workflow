# Component: COM-07 — OutputDomain

Sources: [requirements.md](../requirements.md) | [design-map.md](../design-map.md) | [plan.md](../plan.md) | [architecture.md](architecture.md) | [components architecture.md](../../../../processes/components/architecture.md)

Implements: (ALG-07)
Cross-references: (requires: OUT-01, OUT-02, OUT-03, OUT-04, OUT-05; satisfies: GOAL-04)

## Capabilities

- CAP-07 — Render deterministic output and compute the process exit code.
  Derived-from: (GOAL-04)

## Surface: SUR-07

Contracts: (CON-06)

- CON-06 — Present results + exit code. Spec: [design-map.md#contract-con-06-present-results](../design-map.md#contract-con-06-present-results)

## State holders (IAR-XX / ART-XX)

- IAR-01 — Run args (output mode selection)
- IAR-06 — Execution result
- IAR-07 — Output meta (warnings/errors)
- IAR-09 — Aggregated results
- ART-02 — Process exit code
- ART-03 — Text output stream
- ART-04 — YAML output artifact

## Algorithms (ALG-XX)

### ALG-07 — Output strategy + exit-code ownership

Guarantees: (INV-02)

```mermaid
flowchart TD
  %% Cross-references: (requires: OUT-01, OUT-02, OUT-03, OUT-04, OUT-05)
  A([Start]) --> B{Output mode is YAML?}
  B -- Yes --> C["emit ART-04:\nIAR-07 + IAR-09"]
  B -- No --> D["emit ART-03 summary:\nchunk/phase output already emitted during execution"]
  C --> E([done])
  D --> E

  F([Compute exit code]) --> G{Shutdown occurred?}
  G -- Yes --> H["Return exit code 130"]
  G -- No --> I{Any errors or failed/crashed/timed-out chunks?}
  I -- Yes --> J["Return exit code 1"]
  I -- No --> K["Return exit code 0"]
```
