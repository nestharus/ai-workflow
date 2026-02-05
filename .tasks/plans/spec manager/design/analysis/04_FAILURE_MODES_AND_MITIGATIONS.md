# Failure Modes and Mitigations

## FM-0001: LLM outputs structure that does not cover all atoms

Risk:
- dropped atoms via partial mappings

Mitigation:
- contract requires explicit atom lists
- coverage validator (INV-ACC-0101) blocks authority update
- fallback: assign uncovered atoms to UNKNOWN span + remainder unit + GAP(COVERAGE)

## FM-0002: LLM invents derived requirements not supported by evidence

Mitigation:
- grounding audit (INV-ACC-0201/0202)
- judge-based semantic audit with evidence bundle
- policy: unsupported claims are QUARANTINED + GAP(CONTRADICTION/UNDERSPECIFIED)

## FM-0003: Hidden semantic loss via “summaries” that replace evidence

Mitigation:
- derived layer is never considered evidence
- every element must cite atoms
- summaries may exist but are labeled derived and linked to evidence

## FM-0004: ID churn across revisions causes broken references

Mitigation:
- atom fingerprints + sequence alignment remap tables (ALG-CORE-0005)
- deterministic ID allocator with stable_maps (DS-CORE-0009)
- drift report for missing pin targets

## FM-0005: Overlap between libraries causes incoherent boundaries

Mitigation:
- overlap detection via shape aggregation + relation density
- non-destructive move/split/abstract actions
- store monogamy rule; overlaps become interface tasks

## FM-0006: Contradictions between requirements or invariants

Mitigation:
- contradiction detector produces GAP(CONTRADICTION) with evidence atoms
- resolution requires DEC elements with explicit tradeoff evidence
- unresolved contradictions block “DONE” status but do not block other work

## FM-0007: “Stuck” remainder that never gets decomposed

Mitigation:
- remainder queue with stagnation detection
- escalation policy: stronger models + larger bundles for high-risk remainder
- strategy evolution: new decomposition strategy if repeated failures

## FM-0008: Projection drift (plan/task docs edited manually)

Mitigation:
- projection comparator converts drift into gaps
- projection regenerates from L1 every run
- manual edits treated as proposal evidence; must be migrated to L1 with evidence support

## FM-0009: Implementation discovers unknowns and patches spec informally

Mitigation:
- unknown capture is mandatory (DS-TASK-0005)
- spec patch proposals are validated and ingested as new evidence revisions
- audits run before patches become authoritative

## FM-0010: Tooling complexity creates its own failure surface

Mitigation:
- strict contracts + schemas
- minimal deterministic core (atomization, validation, alignment)
- test fixtures per strategy and per agent contract
