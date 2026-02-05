# Threshold Policy Rationale

## Principle

Numeric thresholds are permitted, but must be:
- explicitly versioned
- configurable per run
- audited on fixtures
- non-authoritative when applied to uncontrolled text semantics

## Threshold Categories

1) Hard invariants (no threshold)
- coverage completeness
- contract validity
- ID uniqueness

2) Risk triggers (thresholded)
- remainder ratio
- drift rate
- low-confidence rate
- unresolved reference count

3) Similarity thresholds (thresholded)
- sequence alignment similarity for atom remaps
- projection matching score

## Default Posture

- Conservative for acceptance:
  - prefer remainder + gaps over forced matches
- Aggressive for detection:
  - trigger audits early when risk rises

## Recommended Defaults (Configurable)

- remainder_ratio_warn: 0.05
- drift_rate_warn: 0.01
- low_confidence_warn: 0.05
- atom_remap_similarity_min: 0.85 (below → treat as new atoms, preserve remainder)
- projection_match_min: 0.85 (below → GAP(DRIFT))

## Governance

- Any threshold change requires:
  - version bump
  - regression fixture run
  - audit comparison report against prior thresholds
