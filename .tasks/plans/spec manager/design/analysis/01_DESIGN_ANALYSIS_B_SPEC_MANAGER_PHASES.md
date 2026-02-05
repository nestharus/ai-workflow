# Design Analysis: Strategy-Driven Spec Manager (PHASE_A..E, system-analysis.md, EVOLUTION_PLAN.md)

## Core Thesis

- Spec processing is risk minimization, not deterministic equivalence proof
- Track provenance and coverage across transformations
- Use strategy registry + gating to apply repairs/extractions conditionally
- Use iterative workflows (cleaning → discovery → review → sync → finalize)
- Treat libraries as authoritative, regenerate projections (plan.md) and detect drift

## Strengths (Robustness)

- Explicit provenance model:
  - TrackedUnit with lineage edges
  - many-to-many membership support
  - coverage tracking as a first-class invariant
- Compliance gating:
  - prevents bad intermediate artifacts from silently contaminating later phases
  - creates a clear “stop or proceed with warnings” mechanism
- Strategy framework:
  - makes extraction/repair modular
  - enables evolution: capture gaps → propose strategies → promote to stable
- Discovery is multi-stage:
  - labeling, overlap detection/resolution
  - shape aggregation and convergence heuristics
- Operational tooling:
  - scripts for validate/clean/discover/compose/trace/extract
  - workspace snapshots and manifests

## Weaknesses / Failure Modes

- Violates the no-hardcoding constraint in several places:
  - regex patterns and keyword heuristics used on uncontrolled input for detection/classification
  - fixed thresholds strongly shape outcomes and can hide tail failure modes
- Dual systems / legacy overlap:
  - parallel gap detection implementations increase inconsistency risk
  - legacy module naming and compatibility paths increase maintenance risk
- LLM integration is uneven:
  - some steps assume pre-existing annotation density and recognizable structures
  - can degrade on highly irregular specs without strong initial structuring
- Blocking gates can halt progress if not paired with total fallbacks
  - the system contains warn-paths, but “progress guarantee” must be made explicit per phase

## What the Hybrid Takes

- Strategy architecture + gating as the backbone for iterative improvement
- Intermediate state snapshots, manifests, and trace queries as operational necessities for large specs
- Provenance stamps as an optional temporary debugging aid (never authoritative)
- Library-first authority + plan regeneration + drift detection
- Gap synthesis pipeline concept (findings → cluster → GapElements)

## What the Hybrid Changes

- Moves all uncontrolled-text pattern inference to LLM contracts
  - deterministic code never “interprets” spec semantics via keyword/regex
- Adds explicit phase fallbacks to guarantee forward motion (CON-0009)
- Collapses duplicate subsystems into a single GapElement API and a single validator stack
- Strengthens ID stability across revisions using fingerprint remaps rather than line-number IDs alone
