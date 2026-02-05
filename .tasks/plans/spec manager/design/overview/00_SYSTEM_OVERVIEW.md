# System Overview

## Goal

Transform arbitrary, extremely large specification corpora into:

- an immutable, queryable Evidence Layer (what was written)
- a structured, traceable Derived Library Layer (what we believe the spec means)
- non-authoritative projections (plan, tasks, architecture) that are continuously drift-checked

Primary objective: zero evidence loss + maximal semantic fidelity via audits and iterative refinement.

## Three Core Designs Integrated

- Evidence-preservation (move lines / evidence graph / coverage verification)
- Strategy-driven spec processing (provenance stamps, compliance gating, gap detectors, discovery loop)
- LLM-first pattern recognition + brute-force auditing (multi-model roles; architecture + bottom-up implementation)

## Layered Architecture

L0 Evidence Layer (immutable)
- file_uids + file revisions
- line atoms (ATOM-*)
- evidence ranges (EVID-*)
- operation logs

L1 Derived Library Layer (working authority)
- libraries (LIB-*)
- derived elements (REQ/FLOW/INV/DEC/ALG/DS-*)
- spec_index.json (trace maps + relations)

L2 Projections (non-authoritative)
- plan.md (projection of L1)
- task plans (TASK-*)
- architecture docs
- reports

## Non-Loss Guarantee Mechanism

- Always start from L0 atoms (line-level, full coverage)
- Any extraction produces mappings to atom IDs
- Any unmapped atoms remain as remainder (never dropped)
- Coverage audits run after every phase transition

## “Perfect Spec” vs “Never Perfect”

- L0 is always “perfect” (it is the source)
- L1 is continuously refined and may remain imperfect; unknowns are explicit GapElements
- Implementation is allowed to proceed with L1 while generating new evidence and gaps

## Canonical Invariants

- INV-ACC-0101: every atom is accounted (mapped/remainder/excluded)
- INV-ACC-0201: every derived element is grounded in atoms (directly or via derivation chain)
- CON-0013: drift detection at every projection boundary
