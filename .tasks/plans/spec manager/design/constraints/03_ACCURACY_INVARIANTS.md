# Accuracy Invariants

## Evidence Integrity

- INV-ACC-0001  Atom immutability: atom.content never changes after ingest of its revision
- INV-ACC-0002  Atom ordering: atom.sequence_index preserved per file revision
- INV-ACC-0003  Evidence range integrity: evidence_range.atom_ids is a contiguous slice of a file revision’s atom list

## Coverage

- INV-ACC-0101  Atom accounting completeness:
  - accounted_atoms = mapped_atoms ∪ remainder_atoms ∪ excluded_atoms
  - accounted_atoms == all_atoms
- INV-ACC-0102  Exclusions are explicit:
  - excluded_atoms requires reason_code ∈ DS-COMP-0006.ExclusionReasonCode
- INV-ACC-0103  No “implicit discard” paths exist in workflows

## Derived Element Grounding

- INV-ACC-0201  Each DerivedElement has:
  - evidence_refs.count ≥ 1 OR derivation_parent_id != null
- INV-ACC-0202  If derivation_parent_id != null, the derivation chain must terminate in atoms
- INV-ACC-0203  Derived text cannot be presented as verbatim evidence

## Transformations

- INV-ACC-0301  Every transformation emits lineage edges (from_atoms → to_atoms OR from_elements → to_elements)
- INV-ACC-0302  Membership mapping supports many-to-many with confidence and method
- INV-ACC-0303  Sequence-aware diff is used for ordered content comparisons (no set-based membership)

## Progress / Completion

- INV-ACC-0401  Each phase has a fallback state that preserves all atoms as remainder
- INV-ACC-0402  All unresolved items are represented as GapElements; “unknown” is a valid state
