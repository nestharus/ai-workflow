# Implementation Co-Evolution

## Objective

Allow implementation to proceed while continuously refining the spec without losing evidence or accumulating drift.

## Inputs to Implementation Work

- bounded context bundles:
  - relevant evidence atoms
  - relevant derived elements (REQ/FLOW/INV/DEC)
  - open gaps affecting the target library/element
  - interface contracts and dependencies

## Unknown Capture

When an implementer cannot proceed due to missing/ambiguous spec:

- create ImplementationUnknown (DS-TASK-0005)
- convert to:
  - GapElement (UNDERSPECIFIED / AMBIGUITY / UNRESOLVED_REFERENCE)
  - Task(status=NEEDS_SPEC)
- optionally generate SpecPatchProposal (DS-TASK-0006) with evidence

## Spec Patch Validation

A spec patch proposal becomes authoritative only after:

- contract validation (templates)
- grounding audit (element cites evidence)
- coverage audit (no atoms lost)
- drift check (projection remains regenerable)

## Convergence Loop (from evidence-preservation design)

Done criteria:
- no ERROR gaps
- no NEEDS_SPEC tasks
- coverage invariants hold
- projections show drift_rate == 0 (or explicitly accepted drift gaps)
