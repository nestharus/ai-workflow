# Authority Model

## Layers

- L0 Evidence Layer (authoritative, immutable)
  - atoms, evidence ranges, operation logs, membership maps
- L1 Derived Library Layer (working authority)
  - libraries/*.md (structured specs with evidence citations)
  - spec_index.json (IDs, edges, membership)
- L2 Projections (non-authoritative views)
  - plan.md, task plans, architecture docs, reports

## Rules

- AUTH-0001  L0 is the ultimate truth for “what was written”
- AUTH-0002  L1 is the authoritative operational spec for implementation (must be fully traced to L0)
- AUTH-0003  L2 is always regenerable from L1; edits to L2 are treated as drift evidence, not authority
- AUTH-0004  Conflicts resolve by: L0 evidence → L1 structured interpretation → L2 views
- AUTH-0005  Any L2-only content MUST be either:
  - migrated into L1 with evidence support, or
  - captured as GapElement (drift), or
  - explicitly excluded with rationale and atom list

## Required Drift Checks

- PROJ-DRIFT-0001  L1 → L2 membership check (atom-aware, sequence-aware)
- PROJ-DRIFT-0002  L2 → L1 “plan-only” remainder capture (never silent)
