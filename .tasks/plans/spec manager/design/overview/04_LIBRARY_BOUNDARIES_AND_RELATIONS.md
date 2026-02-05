# Library Boundaries and Relations

## Boundary Model

Two orthogonal partitions are supported simultaneously:

1) Vertical slices (components with state/lifecycle)
2) Horizontal slices (protocols/algorithms/utilities that are stateless or cross-cutting)

Libraries may be nested (library-within-library) but nesting is a projection; the authoritative structure is the graph in spec_index.json.

## Store Monogamy (from evidence-preservation design)

- Each persistent store is owned by exactly one vertical library
- Cross-library access to a store must be mediated via explicit interfaces (EDGE contracts)
- Violations are emitted as GAP(OVERLAP) + interface tasks

## Relation Types (DS-SPEC-0004.relation_type)

- DEPENDS_ON: requires another element/library
- REFINES: a more specific statement of a parent
- CONTRADICTS: conflicts (requires resolution)
- OVERLAPS: shared responsibility (requires boundary decision)
- IMPLEMENTS: task/code patches implement an element

## Overlap Resolution Options (non-destructive)

- MOVE: reassign elements to one library
- SPLIT: create a new library for the overlap
- ABSTRACT: lift shared protocol into a horizontal library
- DUPLICATE (discouraged): allowed only if evidence is intentionally duplicated with explicit justification + linkage

## Evidence Rule

All boundary decisions must cite evidence atoms that motivated the decision, plus any new decision evidence created during refinement.
