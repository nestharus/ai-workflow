# Component: COM-08 — ShutdownCoordinator

Sources: [requirements.md](../requirements.md) | [design-map.md](../design-map.md) | [plan.md](../plan.md) | [architecture.md](architecture.md) | [components architecture.md](../../../../processes/components/architecture.md)

Implements: (ALG-08)
Cross-references: (requires: PROC-11; satisfies: GOAL-03)

## Capabilities

- CAP-08 — Coordinate shutdown initiation and shared shutdown state.
  Derived-from: (GOAL-03)

## Surface: SUR-08

Contracts: (CON-07, CON-08)

- CON-07 — Shutdown initiation. Spec: [design-map.md#contract-con-07-shutdown-initiation](../design-map.md#contract-con-07-shutdown-initiation)
- CON-08 — Signal-to-shutdown routing. Spec: [design-map.md#contract-con-08-signal-to-shutdown](../design-map.md#contract-con-08-signal-to-shutdown)

## State holders (IAR-XX)

- IAR-11 — Shutdown event (set-once)
- IAR-12 — Shutdown reason

## Algorithms (ALG-XX)

### ALG-08 — Idempotent shutdown initiation

Guarantees: (INV-02)

```mermaid
flowchart TD
  %% Cross-references: (requires: PROC-11, OUT-05)
  A([Start]) --> B["Acquire shutdown guard (idempotence)"]
  B --> C{Shutdown already initiated? (IAR-11)}
  C -- Yes --> D["Return (idempotent)"]
  C -- No --> E["Record shutdown reason (IAR-12) and set shutdown event (IAR-11)"]
  E --> F["Invoke registered shutdown callbacks in deterministic order (best-effort)"]
  F --> G([Return])
```
