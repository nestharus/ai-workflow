# Algorithm Graph Creator - Definitions

## Entity Definitions

| ID | Name | Definition | Component |
|----|------|------------|-----------|
| DFN-01 | COM (Component) | A bounded unit of functionality. Owns a surface, algorithms, and invariant aspects. | [component.md](components/component.md) |
| DFN-02 | SUR (Surface) | Exposes zero or more contracts (CON). | [surface.md](components/surface.md) |
| DFN-03 | CON (Contract) | A boundary inside a surface. Expresses capabilities and declares invariant aspects. | [contract.md](components/contract.md) |
| DFN-04 | ALG (Algorithm) | An implementation unit. Owns exactly one contract (CON). Provides responsibilities. | [algorithm.md](components/algorithm.md) |
| DFN-05 | CAP (Capability) | An outcome of a contract. | [capability.md](components/capability.md) |
| DFN-06 | INV (Invariant) | A self-constraint owned by an entity and applied to itself. | [invariant.md](components/invariant.md) |
| DFN-07 | SHP (Shape) | A collection of invariants. Shapes can contain invariants and other shapes. | [shape.md](components/shape.md) |
| DFN-08 | Invariant Aspect | Applies a shape to entities via roles. | [invariant-aspect.md](components/invariant-aspect.md) |
| DFN-09 | Role | A semantic slot within an invariant aspect. Entities are slotted into roles. | [role.md](components/role.md) |

## Execution Definitions

| ID | Name | Definition | Component |
|----|------|------------|-----------|
| DFN-10 | EXE-INV (Execution Invariant) | Describes how a caller is executing (top-down). Propagates from caller to callee. | [execution-invariant.md](components/execution-invariant.md) |
| DFN-11 | Execution Dimension | A category of execution characteristic: Amount, Parallelism, Size, Locality. | [execution-invariant.md](components/execution-invariant.md) |
| DFN-12 | Execution Transformation | When execution invariants pass through a surface, they may be transformed. | [surface.md](components/surface.md) |

## Responsibility Definitions

| ID | Name | Definition | Component |
|----|------|------------|-----------|
| DFN-13 | ResponsibilityPattern | A string from a fixed vocabulary describing atomic behavioral patterns. | [algorithm.md](components/algorithm.md) |
| DFN-14 | Responsibility Signature | A multiset of responsibility patterns accumulated from providing ALGs. | [capability.md](components/capability.md) |

### Responsibility Vocabulary

| Pattern | Behavior |
|---------|----------|
| builder | Construct data from parts |
| classifier | Boolean predicate |
| collector | Build collection from iterable |
| entity | Domain class with fields |
| extractor | Get specific data from source |
| filter | Yield elements that pass predicate |
| getter | Return private field |
| guard | Guard clause for early return |
| mapper | Map data between formats |
| mutator | Set/modify data |
| orchestrator | Sequential integration |
| projection | Derived view for transmission |
| reducer | Aggregate data |
| router | Route via labeled conditions |
| setter | Set private field |
| splitter | Fan-out stream |
| validator | Validate, throw on failure |
| visitor | Accept callback per element |
| walker | Yield individual elements |
| zip | Combine streams by index |

## Relationship Definitions

| ID | Name | Definition |
|----|------|------------|
| DFN-15 | owns | Ownership relationship (1:1). COM owns SUR. |
| DFN-16 | has | Ownership relationship (1:N). COM has ALG. ALG has CON. |
| DFN-17 | exposes | SUR exposes CON to external callers. |
| DFN-18 | expresses | CON expresses CAP. The contract offers this capability. |
| DFN-19 | supports | CAP supports CAP. Capability composition/dependency. |
| DFN-20 | provides | ALG provides responsibilities to its CON's capabilities. |
| DFN-21 | fulfills | Entity fulfills a role within an invariant aspect. |

## Context Definitions

| ID | Name | Definition |
|----|------|------------|
| DFN-26 | CTX (Context) | Transient data passed during execution. Not persisted. |
| DFN-27 | ART (Artifact) | Operational metadata. Examples: CLI arguments, configuration. |
| DFN-28 | INV-STORES | Storage invariant indicating a component persists data. Applied to COM. |

## Conflict Definitions

| ID | Name | Definition |
|----|------|------------|
| DFN-29 | Provider Conflict | When multiple ALGs provide the same capability but disagree on findings. Resolution: union all + record conflict. |
| DFN-30 | Execution Conflict | When execution invariants don't satisfy a surface's requirements. Detected by Bug Finder. |
