# Graph Schema

This document defines the **parseable corpus** — the structural elements that classical
code can extract from documents to build a graph for analysis. LLMs interpret semantics;
classical code parses structure.

## Dual-Use Model

```
┌─────────────────────────────────────────────────────────────────┐
│                        Document                                 │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  Required Structural Corpus (parseable)                 │   │
│   │                                                         │   │
│   │  • Node declarations (COM, SUR, CON, CAP, ALG)          │   │
│   │  • Relationship fields (Owner, Surface, Derived-from)  │   │
│   │  • Invariant/obligation references (INV, OBL)          │   │
│   │  • Cross-references with typed relations               │   │
│   │                                                         │   │
│   │  → Classical code extracts structure                    │   │
│   │  → LLM interprets semantics                             │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  Everything else (prose, details, examples)             │   │
│   │                                                         │   │
│   │  → LLM can read                                         │   │
│   │  → Classical code ignores                               │   │
│   │  → Not part of graph analysis                           │   │
│   └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Node Types

The graph has these node types, each with required properties:

### COM-XX (Component)

```yaml
id: COM-XX
type: component
properties:
  composed_of: [COM-XX, ...]  # optional, for architectural components
  pattern: string             # pattern name/id
  implements: [GOAL-XX, ...]  # PRD goals
  capabilities: [CAP-XX, ...]
  surface: SUR-XX             # 1:1 relationship
  algorithms: [ALG-XX, ...]
  invariants: [INV-XX, ...]   # state storage invariants (e.g., INV-STORES-FILE-REGISTRY)
```

### SUR-XX (Surface)

```yaml
id: SUR-XX
type: surface
properties:
  owner: COM-XX               # 1:1 relationship
  contracts: [CON-XX, ...]    # contracts on this surface
```

### CON-XX (Contract)

```yaml
id: CON-XX
type: contract
properties:
  surface: SUR-XX             # owning surface
  interaction: string         # request-response, pub-sub, batch, stream, filesystem
  guarantees: [INV-XX, ...]   # invariants this contract promises
  demands: [OBL-XX, ...]      # obligations callers must satisfy
```

### CAP-XX (Capability)

```yaml
id: CAP-XX
type: capability
properties:
  owner: COM-XX               # owning component
  derived_from: [GOAL-XX, ...] # PRD goals this fulfills
  description: string         # what this capability does
```

### ALG-XX (Algorithm)

```yaml
id: ALG-XX
type: algorithm
properties:
  owner: COM-XX               # owning component
  guarantees: [INV-XX, ...]   # invariants this algorithm promises
```


### INV-XX (Invariant)

```yaml
id: INV-XX
type: invariant
properties:
  description: string         # what must always be true
  scope: string               # system-wide or localized
  kind: string                # optional: for state storage invariants (queue, table, topic, cache, internal-api, filesystem, job, timer)
  access_obligations: [OBL-XX, ...] # optional: obligations for state accessors
```

### OBL-XX (Obligation)

```yaml
id: OBL-XX
type: obligation
properties:
  description: string         # what is demanded
  contract: CON-XX            # which contract demands this (optional)
```

### GOAL-XX (Goal)

```yaml
id: GOAL-XX
type: goal
properties:
  description: string         # high-level objective
```

---

## Edge Types

Edges are derived from the properties above:

| Edge Type | From | To | Derived From |
|-----------|------|-----|--------------|
| `owns_surface` | COM-XX | SUR-XX | `COM.surface` / `SUR.owner` |
| `has_contract` | SUR-XX | CON-XX | `SUR.contracts` / `CON.surface` |
| `has_capability` | COM-XX | CAP-XX | `COM.capabilities` / `CAP.owner` |
| `has_algorithm` | COM-XX | ALG-XX | `COM.algorithms` / `ALG.owner` |
| `has_invariant` | COM-XX | INV-XX | `COM.invariants` |
| `composed_of` | COM-XX | COM-XX | `COM.composed_of` |
| `guarantees` | CON-XX | INV-XX | `CON.guarantees` |
| `guarantees` | ALG-XX | INV-XX | `ALG.guarantees` |
| `demands` | CON-XX | OBL-XX | `CON.demands` |
| `derived_from` | CAP-XX | GOAL-XX | `CAP.derived_from` |
| `implements` | COM-XX | GOAL-XX | `COM.implements` |

---

## Structural Relationships

```
GOAL-XX (PRD)
    │
    ├── implements ──► COM-XX (component)
    │                    │
    ├── derived_from ◄── CAP-XX (capability)
    │
    │
COM-XX (component)
    │
    ├── owns_surface ──► SUR-XX (surface, 1:1)
    │                      │
    │                      └── has_contract ──► CON-XX (contract)
    │                                             │
    │                                             ├── guarantees ──► INV-XX
    │                                             └── demands ──► OBL-XX
    │
    ├── has_capability ──► CAP-XX
    │
    ├── has_algorithm ──► ALG-XX
    │                       │
    │                       └── guarantees ──► INV-XX
    │
    ├── has_invariant ──► INV-XX (state storage invariants)
    │
    └── composed_of ──► COM-XX (for architectural components)
```

---

## Parsing Rules

Classical code extracts nodes and edges by parsing:

### 1. Node Detection

Nodes are detected by header patterns:

```regex
## Component: (COM-\d+)
## Surface: (SUR-\d+)
## Contract: (CON-\d+)
## Capability: (CAP-\d+)
## Algorithm: (ALG-\d+)
### ALG-(\d+): .*
## Invariant: (INV-\d+)
### INV-(\d+): .*
```

### 2. Property Extraction

Properties are extracted from field patterns:

```regex
Owner: \((COM-\d+)\)
Surface: \((SUR-\d+)\)
Contracts: \((CON-\d+(?:, CON-\d+)*)\)
Guarantees: \((INV-\d+(?:, INV-\d+)*)\)
Demands: \((OBL-\d+(?:, OBL-\d+)*)\)
Derived-from: \((GOAL-\d+(?:, GOAL-\d+)*)\)
Implements: \((GOAL-\d+(?:, GOAL-\d+)*)\)
Composed-of.*: \((COM-\d+(?:, COM-\d+)*)\)
```

### 3. Cross-Reference Extraction

Cross-references follow the grammar:

```
Cross-references: (relation: ID[, ID]*[; relation: ID[, ID]]*)
```

Relations: `requires`, `uses`, `satisfies`, `derived-from`, `decided-by`, `impacts`

---

## Violation Detection Points

The graph enables detecting violations at these points:

| Violation Type | Detection |
|----------------|-----------|
| **CON ↔ ALG mismatch** | `CON.guarantees ≠ ALG.guarantees` for ALGs behind that surface |
| **Missing capability** | `COM.capabilities` empty or doesn't trace to `GOAL` |
| **Obligation not satisfied** | `OBL` demanded by `CON` not provided by caller's surface |
| **Invariant not guaranteed** | `INV` expected by consumer not in producer's `CON.guarantees` |
| **Capability overlap** | Same `CAP` appears in multiple `COM` |
| **Capability divergence** | `COM` has unrelated `CAP` clusters |

---

## Graph Output Format

The extracted graph can be serialized as:

```yaml
nodes:
  - id: COM-01
    type: component
    properties:
      surface: SUR-01
      capabilities: [CAP-01, CAP-02]
      algorithms: [ALG-01]
      invariants: [INV-STORES-FILE-REGISTRY]

  - id: SUR-01
    type: surface
    properties:
      owner: COM-01
      contracts: [CON-01, CON-02]

  - id: CON-01
    type: contract
    properties:
      surface: SUR-01
      guarantees: [INV-01, INV-02]
      demands: [OBL-01]

edges:
  - from: COM-01
    to: SUR-01
    type: owns_surface

  - from: SUR-01
    to: CON-01
    type: has_contract

  - from: CON-01
    to: INV-01
    type: guarantees
```

---

## Graph Mutation Primitives

The graph supports mutation operations for decomposition and recomposition. These
primitives are used by the operations defined in
`.tasks/plans/algorithm decomposition/feedback.md` Part II.

### Node Operations

| Operation | Signature | Description |
|-----------|-----------|-------------|
| `add_node` | `(type, id, properties) → Node` | Create a new node in the graph |
| `remove_node` | `(id) → void` | Delete node (fails if incoming edges exist) |
| `update_node` | `(id, properties) → Node` | Modify node properties |

### Edge Operations

| Operation | Signature | Description |
|-----------|-----------|-------------|
| `add_edge` | `(from, to, type) → Edge` | Create edge between nodes |
| `remove_edge` | `(from, to, type) → void` | Delete specific edge |
| `redirect_edge` | `(edge_id, new_target) → void` | Change edge target |

### Compound Operations

These operations combine multiple primitives atomically:

| Operation | Effect | Used By |
|-----------|--------|---------|
| `create_component` | Creates COM-XX + SUR-XX + owns_surface edge | CREATE COM |
| `modify_component` | Updates CAP/ALG/INV/CON properties and edges | MODIFY COM |
| `remove_component` | Removes COM-XX + SUR-XX + owned nodes (after redirects) | REMOVE COM |
| `split_component` | Creates N COMs, redistributes CAP/ALG/INV, updates edges | SPLIT COM |
| `merge_components` | Combines nodes into one COM, removes originals | MERGE COM |
| `create_algorithm` | Creates ALG-XX, links owner COM, infers CAP | CREATE ALG |
| `modify_algorithm` | Updates ALG guarantees and inferred CAP | MODIFY ALG |
| `remove_algorithm` | Removes ALG-XX and dependent edges | REMOVE ALG |
| `move_algorithm` | Transfers ALG-XX between COMs, updates CAP ownership when needed | MOVE ALG |
| `split_algorithm` | Creates N ALGs, redistributes logic + CAP | SPLIT ALG |
| `merge_algorithms` | Merges ALGs, unions guarantees + CAP | MERGE ALG |

After any compound operation:

- Re-run invariant/obligation propagation (see `.tasks/processes/propagation-rules.md`).
- Re-validate `ALG` ↔ `CON` alignment (see “Violation Detection Points”).
- Re-check capability overlap/divergence as an architecture quality signal.

## Summary

The graph schema defines:

1. **Node types**: COM, SUR, CON, CAP, ALG, INV, OBL, GOAL
2. **Edge types**: Derived from ownership and reference properties
3. **Parsing rules**: Regex patterns for extracting from markdown
4. **Violation detection**: Where mismatches indicate bugs
5. **Output format**: YAML serialization of the graph

Classical code parses structure. LLMs interpret meaning. Together they enable
graph-based analysis of the architecture.
