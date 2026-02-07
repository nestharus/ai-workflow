# Expected State: Phase 1 Completion

When Phase 1 (Consolidation & Implementation) is done, this is what the
spec_manager package should look like.

---

## Package Structure

```text
spec_manager/
├── __init__.py              # Minimal (docstring + sys.path setup)
├── __main__.py              # Entry point
├── cli.py                   # CLI wiring layer (imports from all subsystems)
├── core/                    # Shared infrastructure (NO refinement dependency)
│   ├── __init__.py          # Docstring only (no re-exports)
│   ├── agent_utils.py       # LLM agent runner
│   ├── annotations.py       # Annotation parsing
│   ├── context_index.py     # ContextIndex for Phase 2
│   ├── coverage.py          # Coverage tracking
│   ├── data_structures.py   # FileSections, FileTerms
│   ├── edit_in_place.py     # Plan 01: edit-in-place engine
│   ├── edit_in_place_bridge.py
│   ├── evidence_index.py    # EvidenceIndex for hollowed specs
│   ├── evidence_pointers.py # Evidence pointer parsing
│   ├── file_id_lookup.py    # File ID lookup builder
│   ├── gap.py               # Gap types (GapType, GapEvidence, Gap)
│   ├── gap_queue.py         # GapQueue
│   ├── gaps.py              # GapSynthesizer v1 + Severity
│   ├── id_registry.py       # File UID + revision registries
│   ├── ids.py               # IdValidator
│   ├── json_extraction.py   # JSON payload extraction
│   ├── libs_registry.py     # LibsRegistry
│   ├── pin_registry.py      # PinRegistryIndex
│   ├── project_root.py      # resolve_from_root
│   ├── provenance.py        # ProvenanceTracker, TrackedUnit, lineage
│   ├── run_folder.py        # RunFolderStructure
│   └── sections.py          # SectionExtractor
│
├── refinement/              # 19-phase LLM pipeline (active system)
│   ├── __init__.py          # Re-exports from core (Gap, GapQueue, etc.)
│   ├── workflows/           # Phase implementations
│   ├── workspace/           # WorkspaceManager + Phase enum
│   ├── interactive/         # Interactive ambiguity resolution
│   ├── hollowed_spec/       # Hollowed-out spec system
│   ├── evals/               # Eval framework
│   ├── evaluation/          # Repair bakeoff + fixtures
│   ├── formats.py           # LLM output parsing
│   └── ...
│
├── branches/                # Plan 04: Branch organization
├── pin_functions/           # Plan 02: Pin-function management
├── planning/                # Plan 03: Algorithmic planning
├── compliance/              # Plans 05, 06, 08
│   ├── detection/           # Executable gap detection
│   ├── promotion/           # Promotion gates
│   └── coverage/            # Entity coverage
├── projection/              # Plan 09: Lineage + drift
├── analysis/                # Plans 07, 11: Adjacency + generation
├── strategies/              # Plan 10: Strategy evolution
├── schemas/                 # Pydantic schemas
├── decomposition/           # Decomposition utilities
├── labyrinth/               # Eval labyrinth framework
└── utils/                   # Misc utilities
```

---

## Import Rules (ACHIEVED)

### core/ imports NOTHING from refinement/ — DONE

### schemas/ imports NOTHING from refinement/ — DONE

### PDD modules import from core/ not refinement/ — DONE

All PDD modules are clean:

* `planning/` — 0 refinement imports
* `branches/` — 0 refinement imports
* `pin_functions/` — 0 refinement imports
* `projection/` — 0 refinement imports
* `analysis/` — 0 refinement imports
* `compliance/` — 0 refinement imports
* `decomposition/` — 0 refinement imports
* `labyrinth/` — 0 refinement imports

### Acceptable boundary imports

* `cli.py` — top-level wiring layer, dispatches to all subsystems
* `strategies/implementations/format_repair.py` — wraps refinement LLM repair

### refinement/ CAN import from core/ and PDD modules

---

## Dead Code Removal (COMPLETE)

All dead code identified and removed:

* Dead legacy packages (workflow/, workspace/, staging/, discovery/, merging/, verification/)
* Dead core files (compat.py, intermediate.py, local_id_resolver.py, gap_compat.py, library_registry.py)
* Dead re-export layers (core/__init__.py, refinement/__init__.py, top-level __init__.py)
* Dead refinement/core/__init__.py re-exports

---

## CLI Commands: VERIFIED

### Entry points:
- `spec` → `refinement.cli:main` (19-phase refinement pipeline)
- `spec-manager` → `cli:main` (PDD module commands)

### spec-manager commands: all working
- `phase-02`, `refine`, `ambiguities`, `evidence-store`
- `generate-analysis`, `adjacency`, `scan-source`
- `branches`, `pin`, `eval`, `plan-v2`, `coverage`

---

## Test State

All tests pass: `uv run python -m pytest scripts/spec_manager/tests/ -p no:randomly -x -q`
Current: 700 passed, 2 warnings

---

## What "Done" Looks Like

Phase 1 is done when:
1. [x] Zero cross-contamination violations (core/, schemas/, PDD modules clean)
2. [x] All tests pass (700 passed)
3. [x] All CLI commands work
4. [x] No dead code, orphaned imports, or unused files
5. [x] Package structure matches this document
6. [x] CONSOLIDATION_LOG.md documents every change made
7. [x] All PDD module implementations verified against plans

## Plan Verification Results

All 11 main plans and 5 refactors verified as COMPLETE:

| Plan | Module | Status |
|------|--------|--------|
| 01 | Edit-in-Place Engine | COMPLETE |
| 02 | Pin-Functions System | COMPLETE |
| 03 | Planning Module | COMPLETE |
| 04 | Branch Organization | COMPLETE |
| 05 | Executable Gap Detection | COMPLETE |
| 06 | Hollowed-Out Spec Evidence | COMPLETE |
| 07 | Adjacency Detection | COMPLETE |
| 08 | Compliance Gating | COMPLETE |
| 09 | Lineage Tracking | COMPLETE |
| 10 | Strategy Evolution | COMPLETE |
| 11 | Analysis File Generator | COMPLETE |
| refactor-01 | Merge Planning | COMPLETE |
| refactor-02 | Decompose Branches | COMPLETE |
| refactor-03 | Consolidate Adjacency | COMPLETE |
| refactor-04 | Deduplicate Pins | COMPLETE |
| refactor-05 | Wire Branches Workflow | COMPLETE |
