# Expected State: Phase 1 Completion

When Phase 1 (Consolidation & Implementation) is done, this is what the
spec_manager package should look like.

---

## Package Structure

```
spec_manager/
├── __init__.py              # Top-level exports (core types + entry points)
├── __main__.py              # Entry point
├── cli.py                   # CLI with both refinement and PDD commands
├── core/                    # Shared infrastructure (no refinement dependency)
│   ├── agent_utils.py       # LLM agent runner (DONE)
│   ├── annotations.py       # Annotation parsing
│   ├── compat.py            # Python compat helpers
│   ├── context_index.py     # ContextIndex for Phase 2
│   ├── coverage.py          # Coverage tracking
│   ├── data_structures.py   # FileSections, FileTerms
│   ├── edit_in_place.py     # Plan 01: edit-in-place engine
│   ├── edit_in_place_bridge.py
│   ├── evidence_pointers.py # Evidence pointer parsing (DONE)
│   ├── gap.py               # Gap types (DONE)
│   ├── gap_compat.py        # Gap compatibility
│   ├── gap_queue.py         # GapQueue (DONE)
│   ├── gaps.py              # GapSynthesizer v1 + Severity
│   ├── id_registry.py
│   ├── ids.py
│   ├── intermediate.py
│   ├── library_registry.py
│   ├── libs_registry.py
│   ├── local_id_resolver.py
│   ├── pin_registry.py
│   ├── project_root.py
│   ├── provenance.py
│   └── sections.py
│
├── refinement/              # 19-phase LLM pipeline (THE ACTIVE SYSTEM)
│   ├── __init__.py          # Re-exports for backwards compat within refinement
│   ├── cli.py               # Refinement-specific CLI
│   ├── core/                # Thin re-export layer → core/
│   ├── evals/               # Eval framework (fixtures, runners, metrics)
│   ├── evaluation/          # Evaluation utilities
│   ├── formats.py           # LLM output parsing (strip_code_fences, etc.)
│   ├── hollowed_spec/       # Plan 06 integration point
│   ├── interactive/         # Interactive ambiguity resolution
│   ├── progress.py          # Progress tracking
│   ├── qa/                  # QA evaluation
│   ├── repair.py            # Format repair
│   ├── trace.py             # Tracing
│   ├── validation_utils.py  # Validation helpers
│   ├── workflows/           # Phase implementations
│   └── workspace/           # WorkspaceManager + Phase enum
│
├── branches/                # Plan 04: Branch organization
├── pin_functions/           # Plan 02: Pin-function management
├── planning/                # Plan 03: Algorithmic planning
├── compliance/              # Plans 05, 06, 08: Detection + promotion + gating
│   ├── detection/           # Executable gap detection
│   ├── promotion/           # Hollowed-out spec evidence + promotion gates
│   ├── coverage/            # Coverage tracking
│   └── ...                  # Scoring, validation, metrics
├── projection/              # Plan 09: Lineage + drift + projection
├── analysis/                # Plans 07, 11: Adjacency + analysis generation
├── strategies/              # Plan 10: Strategy evolution
├── schemas/                 # Pydantic schemas for all artifacts
├── decomposition/           # Decomposition utilities
├── labyrinth/               # Eval labyrinth framework
└── utils/                   # Misc utilities
```

---

## Import Rules (Cross-Contamination)

These rules MUST hold when Phase 1 is done:

### core/ imports NOTHING from refinement/
- `core/*.py` must not have `from spec_manager.refinement` imports
- This is the foundation layer; everything depends on it

### schemas/ imports NOTHING from refinement/
- `schemas/*.py` must not have `from spec_manager.refinement` imports
- Schemas are data contracts; they cannot depend on pipeline logic
- CURRENT VIOLATION: `schemas/review_actions.py` imports `build_file_id_lookup` from `refinement/validation_utils.py`

### PDD modules import from core/ not refinement/
- `planning/*.py` — CLEAN (0 refinement imports)
- `branches/*.py` — CLEAN (0 refinement imports)
- `pin_functions/*.py` — CLEAN (0 refinement imports)
- `projection/*.py` — CLEAN (0 refinement imports)
- `analysis/*.py` — need to verify
- `strategies/*.py` — need to verify (`format_repair.py` may import refinement/formats.py)
- `compliance/detection/*.py` — CLEAN for gap types; need to verify all
- `compliance/promotion/*.py` — need to verify
- `compliance/scorer.py` — may still have refinement deps

### refinement/ CAN import from core/
- This is expected and correct; refinement builds on core

### refinement/ CAN import from PDD modules
- Refinement workflows may use PDD modules (e.g., branch_lifecycle, evidence_store)

---

## Remaining Cross-Contamination to Fix

### 1. schemas/review_actions.py → refinement/validation_utils.py
`build_file_id_lookup` needs to move to core/ or schemas/

### 2. strategies/ → refinement/
`strategies/implementations/format_repair.py` may import from refinement/formats.py

### 3. compliance/scorer.py → legacy deps
Previous session identified legacy imports from workspace/ and workflow/.
The legacy packages are deleted now. Need to verify scorer.py still works.

### 4. core/tests/ → refinement/
`core/tests/test_edit_in_place_bridge.py` imported Phase from refinement workspace

---

## Test State

All tests must pass: `uv run python -m pytest scripts/spec_manager/tests/ -p no:randomly -x -q`

Tests should:
- Not import from deleted packages
- Not have hardcoded values that mask bugs
- Test actual behavior, not implementation details

---

## CLI State

The CLI should have:
- Refinement commands (refine, phase-02, etc.) — working
- PDD commands (branches, pin, plan-v2, scan-source, adjacency, etc.) — working
- Evidence store commands — working
- Eval commands — working
- NO dead commands that reference deleted packages

---

## What "Done" Looks Like

Phase 1 is done when:
1. Zero cross-contamination violations (no non-refinement code imports from refinement/)
2. All tests pass
3. All CLI commands work
4. No dead code, orphaned imports, or unused files
5. The package structure matches this document
6. CONSOLIDATION_LOG.md documents every change made
