# Component: COM-02 — RunLintersOrchestrator (composition root)

Sources: [requirements.md](../requirements.md) | [design-map.md](../design-map.md) | [plan.md](../plan.md) | [architecture.md](architecture.md) | [components architecture.md](../../../../processes/components/architecture.md)

Implements: (ALG-02)
Cross-references: (requires: EXEC-03, EXEC-04, OUT-05; satisfies: GOAL-01, GOAL-03)

## Capabilities

- CAP-02 — Drive the run lifecycle and coordinate domains.
  Derived-from: (GOAL-01, GOAL-03)

## Surface: SUR-02

Contracts: (CON-01)

- CON-01 — Invoked by CLI adapter. Spec: [design-map.md#contract-con-01-cli-invoke](../design-map.md#contract-con-01-cli-invoke)

## Uses contracts

- CON-02 — File discovery. Spec: [design-map.md#contract-con-02-discover-files](../design-map.md#contract-con-02-discover-files)
- CON-03 — Linter configuration. Spec: [design-map.md#contract-con-03-configure-linters](../design-map.md#contract-con-03-configure-linters)
- CON-04 — Scheduling. Spec: [design-map.md#contract-con-04-build-schedule](../design-map.md#contract-con-04-build-schedule)
- CON-05 — Execution. Spec: [design-map.md#contract-con-05-execute-schedule](../design-map.md#contract-con-05-execute-schedule)
- CON-06 — Output + exit code. Spec: [design-map.md#contract-con-06-present-results](../design-map.md#contract-con-06-present-results)
- CON-18 — SIGINT handler installation. Spec: [design-map.md#contract-con-18-install-sigint-handler](../design-map.md#contract-con-18-install-sigint-handler)

## State holders (IAR-XX)

- IAR-01 — Run args
- IAR-02 — Runtime facts
- IAR-04 — File registry
- IAR-06 — Execution result
- IAR-07 — Output meta (diagnostic accumulation)
- IAR-11 — Shutdown event

## Algorithms (ALG-XX)

### ALG-02 — Orchestrate a lint run

Guarantees: (INV-02, INV-05)

```mermaid
flowchart TD
  %% Cross-references: (requires: EXEC-01, EXEC-03, EXEC-04, OUT-05; satisfies: GOAL-01, GOAL-03)
  A([Start]) --> B0["Init COM-08 + COM-09 via CON-18 (shutdown wiring)"]
  B0 --> B["Init COM-07 (OutputDomain / output-mode strategy)"]

  B --> C["Determine mode from IAR-01 (Run args)"]
  C --> D["Call COM-03 via CON-02 -> IAR-03"]
  D --> E{IAR-03 has errors?}
  E -- Yes --> E1["Call COM-07 via CON-06 -> ART-02=1"]
  E -- No --> M["Init IAR-04 from IAR-03\n+ existence-only prune (INV-03)"]

  M --> F{files empty?}
  F -- Yes --> F1["Call COM-07 via CON-06 -> ART-02=0"]
  F -- No --> G["Call COM-07 to report file count"]

  G --> H["Call COM-04 via CON-03 -> IAR-04 (instances/filesets)"]
  H --> I{errors?}
  I -- Yes --> I1["Call COM-07 via CON-06 -> ART-02=1"]
  I -- No --> N["Preflight (EXEC-03) and drop failed instances from IAR-04"]

  N --> P{operational instances non-empty?}
  P -- No --> P1["Call COM-07 via CON-06 -> ART-02 (0 or 1 per EXEC-03)"]
  P -- Yes --> Q["Call COM-05 via CON-04 -> IAR-05 (schedule)"]

  Q --> R{scheduling errors?}
  R -- Yes --> R1["Call COM-07 via CON-06 -> ART-02=1"]
  R -- No --> S{phases empty?}
  S -- Yes --> S1["Call COM-07 via CON-06 -> ART-02=0"]
  S -- No --> T["Call COM-06 via CON-05 -> IAR-06 (execution result)"]

  T --> V["Call COM-07 via CON-06 -> ART-02/ART-03/ART-04"]
  V --> Z([Exit])
```
