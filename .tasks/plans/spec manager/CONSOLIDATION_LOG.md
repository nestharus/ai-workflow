# Consolidation Log

## Step 1: Move gap types to core/ (done)

Moved `refinement/core/gap.py` and `gap_queue.py` to `core/`. Shared infrastructure
(GapType, GapEvidence, Gap, GapQueue, GapSynthesizer) used by 25+ files across PDD
and refinement. Updated all imports, deleted originals. 700 tests pass.

## Step 2: Move agent_utils to core/ (done)

Moved `refinement/agent_utils.py` to `core/agent_utils.py`. Pure stdlib utility for
running LLM agents. Used by 27 files including 3 PDD planning modules. Caught a
relative import in `refinement/repair.py`. 700 tests pass.

## Step 3: Extract evidence pointers to core/ (done)

Created `core/evidence_pointers.py` with `EVIDENCE_POINTER_RE`, `EVIDENCE_POINTER_NEW_RE`,
`parse_evidence_pointer`, `extract_pointer_components`. These were in `refinement/formats.py`
but 4 `schemas/` files imported them. 700 tests pass.

## Step 4: Extract file_id_lookup to core/ (done)

Created `core/file_id_lookup.py` with `build_file_id_lookup`. Was in
`refinement/validation_utils.py` but `schemas/review_actions.py` imported it. 700 tests pass.

## Step 5: Extract EvidenceIndex to core/ (done)

Created `core/evidence_index.py` with `EvidenceIndex` and `build_evidence_index`. Was in
`refinement/hollowed_spec/indexer.py` but 4 compliance files imported it (TYPE_CHECKING).
Fixed compliance/coverage/cli.py run_dir→root attribute error. 700 tests pass.

## Step 6: Extract RunFolderStructure to core/ (done)

Created `core/run_folder.py` with `RunFolderStructure`. Was in
`refinement/workspace/manager.py`. compliance/coverage/cli.py was the only non-refinement
consumer. 700 tests pass.

## Step 7: Extract JSON extraction to core/ (done)

Created `core/json_extraction.py` with `_extract_json_payload`,
`_record_json_extraction_evidence`, `_infer_extraction_method`. Was in
`refinement/formats.py` but `strategies/format_repair.py` imported them. 700 tests pass.

## Step 8: Remove Phase enum test from core/tests (done)

Removed `TestPhaseEnumExtension` from `core/tests/test_edit_in_place_bridge.py`.
It tested `Phase.EDIT_IN_PLACE` from `refinement/workspace/state.py` — core tests
should not test refinement internals.

## Step 9: Remove dead code — first pass (done)

Deleted 3 dead files (1,026 lines):

* `core/compat.py` — atom ID compatibility functions, never referenced
* `core/intermediate.py` — FileSnapshot/IntermediateManager, never used
* `core/local_id_resolver.py` — LocalIdResolver, never imported

Cleaned `refinement/core/__init__.py` (was dead re-export layer).
Removed dead exports from `core/__init__.py`. 700 tests pass.

## Step 10: Remove dead lazy exports (done)

Removed all lazy `__getattr__` exports from:

* `refinement/__init__.py` — ArtifactType, get_repair_model, repair_artifact, ProgressTracker
* top-level `__init__.py` — 16 re-exported symbols (AnnotationParser, Strategy, etc.)

All consumers import directly from submodules. 700 tests pass.

## Step 11: Remove dead core re-exports and orphaned modules (done)

* `core/__init__.py` — removed 44 unused re-exports, replaced with docstring only
* `core/gap_compat.py` — deleted orphaned v1→v2 migration adapter (zero imports)
* `core/library_registry.py` — deleted dead module (only used by dead __init__.py)

543 lines removed. 700 tests pass.

## Cross-Contamination Status

**CLEAN** (zero refinement imports):
- `core/` — foundation layer
- `schemas/` — data contracts
- `planning/` — algorithmic planning (PDD)
- `branches/` — branch organization (PDD)
- `pin_functions/` — pin management (PDD)
- `projection/` — lineage + drift (PDD)
- `analysis/` — adjacency + generation (PDD)
- `compliance/` — detection + promotion + gating
- `decomposition/` — decomposition utilities
- `labyrinth/` — eval framework

**ACCEPTABLE** (architectural boundary imports):
- `cli.py` — top-level wiring layer, dispatches to all subsystems
- `strategies/implementations/format_repair.py` — wraps refinement LLM repair system

## What Was Extracted to core/

| File | From | Consumers |
|------|------|-----------|
| `core/gap.py` | `refinement/core/gap.py` | 25+ files across all packages |
| `core/gap_queue.py` | `refinement/core/gap_queue.py` | refinement workflows, core bridge |
| `core/agent_utils.py` | `refinement/agent_utils.py` | planning, interactive, workflows |
| `core/evidence_pointers.py` | `refinement/formats.py` | schemas, refinement |
| `core/file_id_lookup.py` | `refinement/validation_utils.py` | schemas, refinement |
| `core/evidence_index.py` | `refinement/hollowed_spec/indexer.py` | compliance, refinement |
| `core/run_folder.py` | `refinement/workspace/manager.py` | compliance, refinement |
| `core/json_extraction.py` | `refinement/formats.py` | strategies, refinement |
