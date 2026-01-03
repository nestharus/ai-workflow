# Execution Invariant (EXE-INV)

## Definition

Describes how a caller is executing. Propagates top-down from caller to callee through surfaces.

## Properties

```mermaid
mindmap
  root((EXE-INV))
    Identity
    Dimension
    Value
    Risk
```

## Relationships

```mermaid
erDiagram
    SUR ||--o{ EXE-INV : receives
    SUR ||--o{ EXE-INV : emits
    EXE-INV ||--o| EXE-INV : "transforms to"
```

## Identity

`EXE-INV-XX` where XX describes the execution mode.

## Dimension

The category of execution characteristic being described.

- **Amount**: atomic, multiplicative (single call vs repeated calls)
- **Parallelism**: concurrent, serial
- **Shape**: bounded, unbounded (protocol - all at once vs stream)
- **Size**: bounded, unbounded (potential data volume)

## Value

The specific execution mode within a dimension.

## Risk

Execution invariants carry **memory** risk.

### Risk Interactions

```mermaid
flowchart TD
    US[Unbounded Size] -->|mitigated by| USH[Unbounded Shape]
    USH -->|creates| LR[Latency Risk]
    LR -->|mitigated by| BSH[Bounded Shape / Batch]
    BSH -->|implies| MULT[Multiplicative]
```

- **Unbounded size** is a general memory risk mitigated by unbounded shape (streaming)
- **Unbounded shape** creates latency risk, mitigated by bounded shape (batching)
- **Bounded shape** implies multiplicative execution

## Propagation

```mermaid
flowchart TD
    Caller -->|declares| EXE-INV
    EXE-INV -->|propagates through| SUR
    SUR -->|may transform| EXE-INV2[EXE-INV']
    EXE-INV2 -->|received by| Callee
```

## Example

```
EXE-INV-UNBOUNDED-SIZE
├── Identity: EXE-INV-UNBOUNDED-SIZE
├── Dimension: Size
├── Value: unbounded
└── Risk: memory
```
