# Consolidation Log

## Step 1: Move gap types to core/ (done)

Moved `refinement/core/gap.py` and `gap_queue.py` to `core/`. Shared infrastructure
(GapType, GapEvidence, Gap, GapQueue, GapSynthesizer) used by 25+ files across PDD
and refinement. Updated all imports, deleted originals. 700 + 91 tests pass.

## Step 2: Move agent_utils to core/ (done)

Moved `refinement/agent_utils.py` to `core/agent_utils.py`. Pure stdlib utility for
running LLM agents. Used by 27 files including 3 PDD planning modules. Caught a
relative import in `refinement/repair.py`. 700 + 91 tests pass.

## Step 3: Extract evidence pointers to core/ (done)

Created `core/evidence_pointers.py` with `EVIDENCE_POINTER_RE`, `EVIDENCE_POINTER_NEW_RE`,
`parse_evidence_pointer`, `extract_pointer_components`. These were in `refinement/formats.py`
but 4 `schemas/` files imported them — schemas should not depend on refinement.

Updated schemas/edge_list.py, interface_contract.py, review_actions.py, tasks.py to
import from `core.evidence_pointers`. `refinement/formats.py` now imports from
`core.evidence_pointers` and re-exports for its remaining consumers. 700 + 91 tests pass.

## Summary so far

Three shared utilities extracted from `refinement/` to `core/`:
- `core/gap.py` + `core/gap_queue.py` — gap data structures
- `core/agent_utils.py` — LLM agent runner
- `core/evidence_pointers.py` — evidence pointer parsing

**Cross-contamination fixed**: `schemas/` no longer imports from `refinement/`.
PDD `planning/` modules no longer import from `refinement/` for gap types or agent runner.
`compliance/detection/` no longer imports from `refinement/` for gap types.

## Remaining refinement dependencies in non-refinement code

```
schemas/review_actions.py → refinement/validation_utils.py (build_file_id_lookup)
strategies/implementations/format_repair.py → refinement/formats.py (multiple)
```

`review_actions.py` still imports `build_file_id_lookup` from `refinement/validation_utils.py`.
This is the last schemas→refinement dependency. Could extract it, but it's a bigger
function with more dependencies — lower priority.

## Next steps (bigger items)

The remaining consolidation work shifts from "extract shared utilities" to
"replace refinement orchestration with PDD orchestration":

1. The Phase enum and WorkspaceManager in `refinement/workspace/` are the core
   orchestration state. PDD modules need their own orchestration (branches/).
2. The 19-phase workflow in `refinement/workflows/` needs to be replaced by the
   PDD phase structure (Phases 0-10 per design).
3. The CLI needs PDD commands as primary entry points.

These are the deep changes described in CONSOLIDATION_CONCLUSIONS.md.
