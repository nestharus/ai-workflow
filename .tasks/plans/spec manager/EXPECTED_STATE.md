# Expected State: Phase 3 — Wire PDD Orchestrator

When Phase 3 is done, the PDD orchestrator correctly delegates to the
real PDD module implementations instead of doing thin structural analysis.

---

## Package Structure

```text
spec_manager/
├── __init__.py              # Minimal (docstring + sys.path setup)
├── __main__.py              # Entry point
├── cli.py                   # CLI wiring layer (imports from all subsystems)
│
├── core/                    # Shared infrastructure (NO refinement dependency)
│   ├── agent_utils.py       # LLM agent runner
│   ├── annotations.py       # Annotation parsing
│   ├── edit_in_place.py     # Plan 01: edit-in-place engine
│   ├── edit_in_place_bridge.py
│   ├── evidence_index.py    # EvidenceIndex for hollowed specs
│   ├── evidence_pointers.py # Evidence pointer parsing
│   ├── gap.py               # Gap types (GapType, GapEvidence, Gap)
│   ├── json_extraction.py   # JSON payload extraction
│   ├── pin_registry.py      # PinRegistryIndex
│   └── ...                  # Other shared utilities
│
├── intake/                  # Phase 0: Routing-based restructuring (DONE)
│   ├── __init__.py          # run_phase0() entry point
│   ├── types.py             # SourceSpan, RouteEntry, LibraryDef, CoverageLedgerEntry
│   ├── summarize.py         # Step 1: LLM summarization (routing hints)
│   ├── discover.py          # Step 2: Library discovery = skeleton proposal
│   ├── route.py             # Step 3: Source span → destination routing (LLM)
│   ├── coverage.py          # Step 4: Coverage ledger (deterministic + LLM)
│   └── assemble.py          # Step 5: Verbatim copy assembly (deterministic)
│
├── orchestration/           # PDD orchestrator (phases 0-10)
│   └── pdd_orchestrator.py  # Sequences PDD modules through design phases
│
├── refinement_engine/       # Cohesion/coupling analysis of skeletons
│   ├── detector.py          # GroupingUnit, detect_all (analysis ONLY)
│   ├── operations.py        # propose_operations, validate_operation
│   └── executor.py          # RefinementExecutor (MUST NOT mutate)
│
├── refinement/              # Legacy 19-phase pipeline (kept for eval/infrastructure)
│   ├── workflows/           # Phase implementations
│   ├── workspace/           # WorkspaceManager + Phase enum
│   ├── interactive/         # Interactive ambiguity resolution
│   ├── hollowed_spec/       # Hollowed-out spec system
│   ├── evals/               # Eval framework
│   └── formats.py           # LLM output parsing (_strip_code_fences)
│
├── branches/                # Plan 04: Branch organization (3-layer model)
├── pin_functions/           # Plan 02: Pin-function management
├── planning/                # Plan 03: Algorithmic planning
├── compliance/              # Plans 05, 06, 08
│   ├── detection/           # Executable gap detection (5 scanners)
│   ├── promotion/           # Promotion gates (10 gate types)
│   └── coverage/            # Entity coverage
├── projection/              # Plan 09: Lineage + drift
├── analysis/                # Plans 07, 11: Adjacency + generation
│   ├── adjacency/           # Adjacency graph (4 extractors)
│   └── generator.py         # Analysis file generator
├── strategies/              # Plan 10: Strategy evolution
├── schemas/                 # Pydantic schemas
├── decomposition/           # Decomposition utilities
└── labyrinth/               # Eval labyrinth framework
```

---

## Import Rules (ACHIEVED - maintain)

### core/ imports NOTHING from refinement/

### PDD modules import from core/ not refinement/

All PDD modules are clean:

* `planning/` — 0 refinement imports
* `branches/` — 0 refinement imports
* `pin_functions/` — 0 refinement imports
* `projection/` — 0 refinement imports
* `analysis/` — 0 refinement imports
* `compliance/` — 0 refinement imports
* `intake/` — uses only `refinement.formats._strip_code_fences` (utility)

---

## Phase 0: Intake (DONE)

Phase 0 routing-based restructuring is fully implemented in `intake/`:

* `run_phase0(source_dir, output_dir)` entry point
* 5-step pipeline: Summarize → Discover → Route → Coverage → Assemble
* 4 LLM agent definitions in `.agents/agents/spec-intake-*.md`
* Libraries = skeletons (proposed by Phase 0, analyzed by refinement engine)
* All three required operators implemented:
  1. Legal routing unit (SourceSpan: file + start + end)
  2. Routing ledger (coverage_ledger.jsonl)
  3. Routing-time invariant test (reimplementation test in classification guidance)
* Output artifacts: summaries/, libraries.json, route_table.jsonl, coverage_ledger.jsonl, libraries/

---

## Orchestrator Phases 1-10: ACHIEVED

All phases delegate to real PDD module entry points. Each phase runner:

1. Calls the PDD module's entry point
2. Passes workspace-derived inputs
3. Returns the module's actual outputs
4. Does NOT reimplement what the module already does

### What each phase calls

| Phase | Module(s) Called |
|-------|-----------------|
| P0 | `intake/run_phase0()` — 5-step routing pipeline |
| P1 | `planning.code_parser.parse_file()` + `core.edit_in_place.analyze_project()` + `find_gaps()` |
| P2 | `planning.reverser.reverse_translate()` per function |
| P3 | `compliance.detection.orchestrator.scan_executable_gaps()` + `GapQueue` integration |
| P4 | `branches.manager.collapse_codebase()` + atom registration + persist |
| P5 | `pin_functions.orchestrator.scan()` + `branches.promote()` |
| P6 | `analysis.adjacency.runner.run_adjacency_analysis()` |
| P7 | `ImportGraph` + `LineageBuilder.build_lineage()` + `generate_analysis_file()` + `ProjectionGenerator` |
| P8 | `planning.workflow.run_planning_v2_phase()` with gap-derived intentions |
| P9 | `core.edit_in_place.analyze_project()` + `find_gaps()` + `format_gap_report()` |
| P10 | `StrategyEvolutionPipeline` (promotion, evolution report) + `refinement_engine` (analysis-only) |

### Refinement engine integration (ACHIEVED)

* `_run_refinement_engine()` IS analysis-only — no `executor.execute()` calls
* Post-phase hook reports cohesion/coupling issues, does not execute operations
* Runs automatically after Phase 4+ and explicitly in Phase 10

---

## Test State

All tests pass: `uv run python -m pytest scripts/spec_manager/tests/ -p no:randomly -x -q`
Current: 2197 passed, 18 deselected, 8 xfailed, 6 warnings

---

## What "Done" Looks Like (Phase 4)

Phase 4 is done when:
1. [x] PDD lifecycle from simpler.md is orchestrated (Build→QA→Architecture→Code Quality)
2. [x] Worktree management for parallel library implementation
3. [x] --auto and --interactive mode orchestration
4. [x] POWER alignment check
5. [x] Human review document generation + approval loop
6. [x] Full pipeline runs end-to-end against treasury spec (Phase 0: 100% coverage, 90% recall)
7. [x] All tests pass (2300 passed)
