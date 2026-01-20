# Spec Manager Enhancement Plan

## Phase 1: Library Model Refactoring

### 1.1 Retire type-based organization
- Libraries should NOT be organized by type (data.md, algorithms.md)
- Libraries should be **subsystems** with natural boundaries
- Each subsystem contains its data structures AND algorithms together

### 1.2 Detect invalid library patterns (new gap type)
Add gap detection for libraries that don't represent system goals:
- "Extra algorithms for X" → not a system goal, needs refactoring
- "Data structures for X" → not a system goal, grouping by type
- Libraries should answer: "What system capability does this provide?"

### 1.3 Goals → Invariants migration
- Retire `G#` pattern, replace with `I#` for invariants
- Invariants can be:
  - **Element-level**: applies to specific sections `(@[!I1])`
  - **System-level**: applies across the whole spec
- Move invariants.md OUT of libraries/ to root level

### 1.4 Subsystem emergence
- Analyze reference patterns to detect natural subsystem boundaries
- Suggest library restructuring based on cohesion (what references what)
- A good subsystem: high internal cohesion, low external coupling

## Phase 2: Spec ↔ Artifact Pinning

### 2.1 Pin syntax
New annotation for pinning spec elements to artifact locations:
```
### Algorithm 1 - Event Ingestion ([=Algorithm 1])
(@pin src/ingestion/handler.py:EventHandler.ingest)
(@pin src/ingestion/validator.py:validate_event)
```

### 2.2 Drift detection
- Parse pins from spec
- Check if pinned artifact locations exist
- Detect content changes in artifact that may invalidate spec
- Report drift as gaps

### 2.3 Pin coverage
- Track which spec elements have pins
- Track which artifact elements are pinned
- Report unpinned elements as coverage gaps

## Phase 3: Artifact → Spec Translation

### 3.1 Call graph analysis
- Trace function calls to identify algorithm boundaries
- Detect data flow patterns
- Identify subsystem boundaries from import/dependency graphs

### 3.2 Incremental spec creation
- Start with call graph entry points
- Create spec elements for each discovered component
- Pin as we go
- Track gap coverage (what code isn't captured yet)

### 3.3 Algorithm extraction
- Artifact code is atomized (small functions)
- Spec algorithms are higher-level (sequences of steps)
- Need to compose atomic functions into algorithmic descriptions

## Phase 4: New Directory Structure

```
spec_folder/
├── invariants.md          # System and element invariants (was goals)
├── gaps.md                # Detected gaps and proof obligations
├── libraries/
│   ├── event_ingestion.md    # Subsystem: data + algorithms for ingestion
│   ├── event_routing.md      # Subsystem: data + algorithms for routing
│   └── event_delivery.md     # Subsystem: data + algorithms for delivery
└── .workspace/
```

## Implementation Order

1. **Gap detection for invalid libraries** - flag type-based organization
2. **Goals → Invariants migration** - new I# pattern, move out of libraries/
3. **Pin syntax and parsing** - @pin annotations
4. **Drift detection** - check pins against artifacts
5. **Subsystem analysis** - suggest restructuring based on cohesion
6. **Artifact → Spec translation** - call graph analysis, incremental creation

## New Annotation Syntax

| Pattern | Meaning |
|---------|---------|
| `([=ID])` | Declare ID in this section |
| `(@[+ID])` | Reference ID (related) |
| `(@[!I#])` | Apply invariant to this element |
| `(@pin path:symbol)` | Pin to artifact location |

## New Gap Types

| Type | Description |
|------|-------------|
| `invalid_library` | Library not organized around system goal |
| `unpinned_spec` | Spec element has no artifact pin |
| `unpinned_artifact` | Artifact element not captured in spec |
| `pin_drift` | Artifact changed since pin was created |
| `vague_invariant` | Invariant too vague to verify |
