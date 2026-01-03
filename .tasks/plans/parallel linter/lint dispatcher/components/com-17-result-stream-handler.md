# Component: COM-17 — ResultStreamHandler

Sources: [requirements.md](../requirements.md) | [design-map.md](../design-map.md) | [plan.md](../plan.md) | [architecture.md](architecture.md) | [components architecture.md](../../../../processes/components/architecture.md)

Implements: (ALG-17)
Cross-references: (requires: PROC-11, OUT-03, OUT-04; satisfies: GOAL-03, GOAL-04)

## Capabilities

- CAP-17 — Stream results while honoring shutdown and deterministic output ordering.
  Derived-from: (GOAL-03, GOAL-04)

## Surface: SUR-17

Contracts: (CON-17)

- CON-17 — Result collection loop. Spec: [design-map.md#contract-con-17-result-collection-loop](../design-map.md#contract-con-17-result-collection-loop)

## Uses contracts

- CON-15 — Forward chunk results to aggregation. Spec: [design-map.md#contract-con-15-aggregate-chunks](../design-map.md#contract-con-15-aggregate-chunks)
- CON-16 — Forward ordered output. Spec: [design-map.md#contract-con-16-ordered-output](../design-map.md#contract-con-16-ordered-output)

## State holders (IAR-XX)

- IAR-11 — Shutdown event
- IAR-13 — Inflight task registry
- IAR-10 — Chunk results
- IAR-09 — Aggregated results

## Algorithms (ALG-XX)

### ALG-17 — as-completed loop with shutdown checks and ordered output

Guarantees: (INV-02)

```mermaid
flowchart TD
  %% Cross-references: (requires: PROC-11, OUT-03, OUT-04)
  A([Start]) --> B["Iterate completed in-flight tasks (completion order)"]
  B --> C{Shutdown event set (IAR-11)?}
  C -- Yes --> D["Stop processing new results"] --> M
  C -- No --> E["Convert task outcome into a chunk result\n(success/failure/crash/timeout/skipped) (CR-03)"]
  E --> F["Forward chunk result to aggregation (COM-16)"]
  F --> G{Text streaming enabled? (OUT-03/OUT-04)}
  G -- No --> H["Skip streaming output for this chunk"] --> J
  G -- Yes --> I["Forward chunk output + chunk sequence ID (CR-01) to ordered buffer (COM-15)"]
  I --> J{Fail-fast enabled and chunk indicates failure/crash/timeout?}
  J -- Yes --> K["Initiate shutdown (COM-08)"] --> B
  J -- No --> B

  M --> N["Flush any buffered text output (COM-15)"]
  N --> O([Return aggregated results (IAR-09)])
```
