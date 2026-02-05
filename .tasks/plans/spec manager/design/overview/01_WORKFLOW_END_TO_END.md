# End-to-End Workflow

## Phase 0: Intake (Deterministic)

Inputs: arbitrary text files (no assumed structure)

Outputs:
- FilesManifest (file_uids, revisions, hashes)
- Atom manifests (ATOM-*)
- Baseline CoverageReport (all atoms initially remainder)

## Phase 1: Structure Discovery (LLM, contract-validated)

Per file revision:
- Propose SectionSpan list (SEC-*)
- Validate span coverage; repair by emitting “UNKNOWN spans” for any uncovered atoms
- Extract entities + mentions (ENT-*)

Outputs:
- sections.json (contract)
- entities.json (contract)
- evidence ranges (EVID-*) for each span

## Phase 2: Surgical Decomposition (LLM + coverage tracker)

Per section:
- Decompose into fragments (project / split / mark decision / mark underspec / mark noise)
- Produce TrackedUnits backed by atom slices
- Ensure union(leaf.fragments.atom_ids) == section.atom_ids

Outputs:
- units.json
- lineage edges
- GapElements for underspec / ambiguity / contradictions found during decomposition

## Phase 3: Cleaning + Compliance Gate (strategy-driven)

- Run strategy set selected by risk signals
- Contract-validate all agent outputs
- Compute compliance metrics (coverage, remainder ratio, trace completeness)
- Gate decision:
  - PASS: proceed
  - WARN_PASS: proceed but emit mandatory tasks
  - BLOCK: freeze authority; emit gap report; fall back to “all remainder” state for next phases

## Phase 4: Library Discovery + Labeling

- Build co-occurrence graph from entity tags (NOT keyword heuristics on raw text)
- Propose library candidates
- Assign multi-labels (primary + secondary) to units with evidence
- Aggregate shapes, detect overlaps and low convergence
- Refine until convergence or max iterations; unresolved units remain “unassigned” with gaps

Outputs:
- libraries.json
- unit_labels.json
- shape_report.json

## Phase 5: Library Spec Build + Stabilize

Per library:
- Build charter (responsibilities/boundaries) with evidence
- Extract derived elements (REQ/FLOW/INV/DEC/ALG/DS)
- Build spec_index.json with atom↔element maps
- Iterative gap-closure loop (bounded iterations; stagnation detection)
- Proof-chain validation; quarantine non-authoritative elements

Outputs:
- libraries/*.md (L1 authority)
- spec_index.json

## Phase 6: Cross-Library Review

- overlap detection (shape overlap, relation density)
- propose non-destructive actions (move/split/merge) + gaps
- execute actions only if coverage + trace invariants preserved

## Phase 7: Projection + Sync

- generate plan.md (L2)
- run atom-aware projection comparator:
  - plan-only content → drift gaps + remainder
  - mismatches → drift gaps
- plan regenerated from libraries on every run (plan never authoritative)

## Phase 8: Task Planning

- derive TASK-* from:
  - open gaps
  - required interfaces
  - element dependencies
- build dependency DAG; detect cycles; bundle cycle groups

## Phase 9: Implementation Co-Evolution

For each task:
- implementation agent consumes bounded context bundle (evidence + relevant spec elements)
- unknowns encountered become:
  - ImplementationUnknown entries
  - GapElements + “NEEDS_SPEC” tasks
  - spec patch proposals (non-authoritative until validated)

Loop:
- ingest new evidence + patches → rerun phases 0..8 incrementally

## Phase 10: Continuous QA

- coverage audits (hard)
- grounding audits (hard)
- semantic consistency audits (soft, judge-based, escalation-only)
- regression suite for strategies and agent contracts
