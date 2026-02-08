# Continuous Refinement Across PDD Promotion Layers

## The Problem

PDD uses promotions to add layers of concern (algorithms → architecture →
code quality → etc.). Each promotion layer needs continuous refinement of
its skeleton — detecting coupling/cohesion problems and restructuring to
fix them.

This is NOT a Phase 0 concern. It applies to ALL phases after Phase 0.
Phase 0 extracts. Continuous refinement improves structure as the system
evolves.

---

## Origin: The Coupling/Cohesion Algorithm

Two earlier design efforts defined a general-purpose graph-driven
architecture refinement algorithm:

- `.tasks/plans/algorithm decomposition/algorithm decomposition feedback.md`
  — The evaluation and action model (overlap, divergence, overload
  detection → split/merge/move operations)
- `.tasks/plans/algorithm graph creator/feedback.md` — The graph
  construction and decoration system (5-pass invariant propagation,
  capability profiles, incremental recomputation)

These were abandoned as a standalone system because they used **static
shapes** for everything. PDD uses static shapes only at the base layer
(algorithms/shapes/stores) and adds dynamic projections for higher layers.

However, the **core algorithm** — detecting coupling/cohesion issues and
proposing restructuring operations — applies universally to every PDD
promotion layer.

---

## What Was Kept

### Coupling/Cohesion Detection

Three states detected by analyzing the entity graph at any layer:

| State | Detection | Meaning |
|-------|-----------|---------|
| **Overlap** | Same capability exists in multiple grouping units | Deduplication needed — one source of truth |
| **Divergence** | Grouping unit has many unrelated capabilities with low cohesion | Split needed — too many concerns in one place |
| **Responsibility Overload** | Single capability has too many responsibilities | Decomposition needed — capability is too complex |

### Evaluation Flow

Events trigger evaluation:
1. Entity changed (algorithm modified, shape updated)
2. New entity added (capability introduced)
3. Grouping unit created (new library, new component)
4. Constraint violation resolved (fix applied)

After detection, actions:
- **Ship** → Move capability to existing unit that already has it (dedup)
- **Absorb** → Pull related capabilities from other units into this one
- **Group** → Create new unit for a cohesive cluster of capabilities
- **Decompose** → Split complex capability into sub-capabilities
- **Redistribute** → After decomposition, move sub-capabilities to
  appropriate units

### Operations

Both component-level and algorithm-level:

| Operation | Effect | When |
|-----------|--------|------|
| CREATE | New node + edges | New capability discovered |
| MODIFY | Edge changes | Capability changed |
| REMOVE | Node + edges removed | Capability eliminated |
| SPLIT | One node → two nodes + redistributed edges | Divergence |
| MERGE | Two nodes → one node + combined edges | Overlap |
| MOVE | Edge reassignment | Better cohesion elsewhere |

Operations are atomic — fully complete or fully rolled back.

### Post-Operation Propagation

After any operation:
1. Track capability distribution before and after
2. Validate graph consistency (no orphans, no broken references)
3. Re-propagate invariants through affected subgraph
4. Report changes to consumers

### Horizontal and Vertical Slicing

PDD adopted this directly from the algorithm decomposition design:

- **Horizontal slice** — Same abstraction level across the system
  (e.g., all algorithms, all shapes at Layer 1)
- **Vertical slice** — Cross-cutting through layers for a single feature
  (e.g., everything related to "ticket lifecycle" from algorithm through
  architecture through deployment)

Both slicing modes are needed for navigation and for detecting
cross-cutting concerns that span multiple grouping units.

---

## What Was NOT Kept

### Static Shapes for Everything

The old algorithm represented all entities as static shapes with fixed
fields. PDD uses static shapes only at Layer 1 (the base:
algorithms/shapes/stores). Higher layers use **dynamic projections** —
each promotion adds its own concerns without modifying the base
representation.

Cross-cutting concerns like security, observability, and error handling
are NOT special categories requiring their own type systems. They are
encoded as algorithms, shapes, and stores at the base layer. Security
rules are algorithms. Security schemas are shapes. Security state is
stores. No separate concern taxonomy is needed — everything reduces to
the three base types.

### Constraint Propagation

The old algorithm tried to propagate constraints through the graph
(5-pass decoration: push down, bubble up, push context, pull missing,
persist). PDD does NOT need this because:

- PDD discovers constraint violations by **running the system** and
  debugging failures
- You don't need to statically classify every possible constraint and
  propagate it through a graph
- You try to implement, fail, and then understand what constraint was
  violated

The 5-pass decoration is valuable as a reference for understanding how
invariants flow through a system, but PDD replaces static analysis with
empirical discovery.

### The Specific ID System

The old algorithm used COM-XX, SUR-XX, ALG-XX, CON-XX, CAP-XX, INV-XX,
OBL-XX, EXE-INV-XX, EXE-OBL-XX IDs. PDD has its own ID system from the
spec refinement evidence layer. The concepts map but the IDs don't carry
over.

---

## How It Applies to PDD Layers

The same coupling/cohesion algorithm applies at every promotion layer.
Only the **grouping unit** and **entity type** change:

### Layer 1: Algorithms / Shapes / Stores (Library Refinement)

| Concept | Maps to |
|---------|---------|
| Grouping unit | Library |
| Entities | Algorithms, shapes, stores |
| Capabilities | What a library can do |
| Overlap | Same algorithm/shape in multiple libraries |
| Divergence | Library does too many unrelated things |
| Overload | Single algorithm is too complex |
| Operations | Split/merge libraries, move algorithms between libraries |

This is **continuous library refinement**. As new algorithms are added or
existing ones modified, the library structure may need to change. The spec
refinement design docs already have library discovery
(`clean/07_LIBRARY_DISCOVERY.md`) with co-occurrence graphs and overlap
resolution — this is the same concept.

**Implementation history**: The `discovery/` module (removed in commit
`debd3f6`) implemented this: candidate identification → multi-label
assignment → shape aggregation → iterative refinement → primary
assignment. The design is preserved in `clean/07_LIBRARY_DISCOVERY.md`
and `clean/08_LIBRARY_SPEC_BUILDING.md`. PDD needs to reimplement this
capability using the coupling/cohesion algorithm rather than the old
TF-IDF/NLP approach.

### Layer 2: Architecture (Component Refinement)

| Concept | Maps to |
|---------|---------|
| Grouping unit | Component |
| Entities | Services, modules, interfaces |
| Capabilities | What a component provides |
| Overlap | Same service in multiple components |
| Divergence | Component has too many unrelated services |
| Overload | Single service is too complex |
| Operations | Split/merge components, move services between components |

This is the original domain of the algorithm decomposition design doc.
Architecture promotions add component boundaries, contracts, and
deployment concerns. The coupling/cohesion algorithm detects when
components are badly bounded.

### Layer N: Any Promotion

Each new promotion layer introduces its own entities and grouping units.
The algorithm is the same:

1. Build a graph of entities at this layer
2. Detect overlap, divergence, overload
3. Propose restructuring operations
4. Execute operations atomically
5. Propagate changes

---

## Integration with PDD

### Where This Runs

Continuous refinement is NOT a separate pipeline. It runs as part of the
PDD loop:

1. Phase 0 extracts (no refinement needed)
2. Phases 1-5 build initial structure (library discovery, pin-functions,
   branch organization)
3. **After initial structure exists**: continuous refinement kicks in
4. Every time content changes (new algorithm, modified shape, promoted
   layer), the coupling/cohesion check runs on the affected grouping units
5. Proposed operations go through the same promotion/compliance gating as
   any other change

### What Triggers Refinement

- Adding a new algorithm to a library
- Modifying an existing algorithm
- Promoting a layer (algorithms → architecture)
- Splitting a library during manual planning
- Merging libraries discovered to overlap
- Any operation that changes the entity graph

### Relationship to Existing PDD Modules

| PDD Module | Relationship to Continuous Refinement |
|------------|--------------------------------------|
| `branches/` | Branch manager tracks library structure; refinement proposes split/merge |
| `pin_functions/` | Pin-functions track algorithm relationships; refinement uses these as edges |
| `analysis/adjacency/` | Adjacency detector builds the entity graph; refinement consumes it |
| `compliance/detection/` | Gap detection finds missing pieces; refinement restructures around them |
| `planning/` | Planning creates new algorithms; refinement evaluates their placement |
| `strategies/evolution.py` | Strategy evolution captures refinement patterns for reuse |

### Spec Refinement Infrastructure Used

| Infrastructure | What It Provides |
|---------------|-----------------|
| Co-occurrence graph (`clean/07`) | Entity overlap detection across files/libraries |
| Multi-label assignment (`clean/07`) | Units belonging to multiple libraries |
| Non-destructive overlap resolution (`clean/07`) | Link duplicates instead of deleting |
| Provenance tracking (`clean/02`) | Track which atom came from where during restructuring |
| Coverage verification (`clean/02`) | Ensure nothing is lost during restructuring |
| Lineage edges (`clean/02`) | Track SPLIT/MERGE/MOVE transformations |

---

## Key Design Principle

> Continuous refinement detects problems by analyzing the entity graph.
> PDD discovers problems by trying to implement and failing.
> These are complementary — refinement catches structural issues
> (coupling/cohesion), PDD catches semantic issues (ambiguity,
> underspecification).

The coupling/cohesion algorithm runs on the structure. PDD's
edit-in-place loop runs on the content. Both are needed. Neither replaces
the other.
