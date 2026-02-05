# Hybrid Architecture Rationale

## Primary Decision: Two-Layer (Evidence + Derived) Instead of “Evidence Only” or “Rewrite Only”

Chosen: L0 evidence atoms + L1 derived libraries grounded in atoms.

Rationale:
- Evidence-only maximizes non-loss but is hard to implement against at scale
- Rewrite-only yields usability but cannot guarantee detail preservation
- Two-layer model yields both:
  - L0 guarantees non-loss
  - L1 yields executable specs while remaining traceable

## Primary Decision: LLM Contracts for Semantics, Deterministic Code for Accounting

Chosen:
- deterministic code performs only:
  - atomization, hashing, alignment, coverage, contract validation, ID allocation
- semantics (sections, entities, decomposition, classification) comes from LLM outputs that must:
  - reference atom IDs
  - pass schema validation
  - be audited

Rationale:
- satisfies no-hardcoding constraint
- preserves accuracy by forcing every semantic claim to be grounded in evidence references

## Primary Decision: Remainder Is a First-Class Product, Not a Failure

Chosen:
- “remainder units” are valid outputs at every phase
- remainder is always visible and convertible into gaps/tasks

Rationale:
- prevents forced hallucinated structure
- allows continuous progress without losing content

## Primary Decision: Strategy Engine + Evolution Loop

Chosen:
- modular strategies with gating on risk signals
- experimental strategies require fixtures + audits before promotion

Rationale:
- arbitrary specs will continue to surface new structures
- controlled evolution prevents brittle, hardcoded logic creep

## Primary Decision: Projection/Sync with Pins

Chosen:
- projections are regenerated; pins map projection offsets → authoritative IDs

Rationale:
- prevents plan.md drift from becoming silent new “truth”
- enables stable linking and trace queries for users and agents

## Primary Decision: Implementation Co-Evolution

Chosen:
- implementation tasks can proceed with explicit gaps
- unknowns discovered in code create new evidence + spec patches

Rationale:
- matches the reality that specs are never perfect
- turns implementation friction into structured refinement work

## Tradeoffs Accepted

- More artifacts and metadata (atoms, mappings, indexes)
- More up-front processing cost
- Stronger constraints on agent outputs (schema and evidence requirements)
