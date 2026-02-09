# Spec Manager Consolidation: Conclusions

## CRITICAL: Read this file before any spec manager work

This file records conclusions from investigation sessions (Feb 6-8 2026).

---

## Consolidation Status: Phases 0-10 ALL WIRED (Phase 3 Complete)

### What Was Done (Phases 1-2)

1. **Legacy dead code removed**: workflow/, workspace/, staging/, discovery/,
    merging/, verification/ — all deleted.

2. **Shared infrastructure extracted**: 8 modules moved from refinement/ to
    core/ (gap.py, agent_utils.py, evidence_pointers.py, etc.)

3. **Cross-contamination eliminated**: core/, schemas/, and all PDD modules
    have zero refinement/ imports.

4. **Phase 0 intake implemented correctly** in `intake/`:
   * Routing-based restructuring per PHASE0_RESEARCH_RESPONSE.md
   * All three required operators: routing unit, routing ledger, invariant test
   * Libraries = skeletons (proposed by Phase 0, analyzed by refinement engine)
   * ProseExtractor (unauthorized regex extraction) removed

5. **11 PDD modules built** per plans 01-11, all verified against plans.

### What Was Done (Phase 3 — Orchestrator Wiring)

1. **All orchestrator phases now delegate to real PDD module entry points**.
   No phase does simplified counting/analysis anymore. Each phase calls the
   actual module API and returns meaningful output.

2. **Refinement engine design violation fixed**: Removed `executor.execute()`
   calls from `_run_refinement_engine()`. The refinement engine is now
   analysis-only — detects coupling/cohesion issues and proposes operations
   but does NOT execute mutations.

3. **Silent defaults removed**: P9 no longer swallows exceptions with
   `try/except` returning error dicts. All errors propagate properly.

4. **2197 tests pass** (up from 2195 due to new test additions).

---

## Design Lineage

### Three designs, in chronological order

| Design | Source Files | Core Idea |
|--------|-------------|-----------|
| #1 | `ALGORITHM.md`, `PLAN.md`, `EVOLUTION_PLAN.md` | Evidence preservation, strategy-driven |
| #2 | `simpler.md` | No extraction, LLM summarization, iterative library refinement, PDD lifecycle |
| #3 | PDD modules (current codebase) | Code IS the spec, comments = gaps, pin-functions, branches |

### Design #2: simpler.md (AUTHORITATIVE for PDD lifecycle)

4-phase model: Build -> QA -> Architecture -> Code Quality

Phase 1 (Build): 12 steps including research, sparse planning, parallel
implementation in worktrees, ambiguity blocking, POWER alignment, human
review/approval. Supports --auto and --interactive modes.

### design/ directory is NOT authoritative

`.tasks/plans/spec manager/design/` went rogue — contradicts simpler.md.
Phase 0 "Deterministic Intake" is wrong for freeform prose. DO NOT use
design/ as authoritative for intake/extraction.

---

## Phase 0: Routing-Based Restructuring (IMPLEMENTED)

### Implementation: `spec_manager/intake/`

| Step | Module | Method | LLM Agent |
|------|--------|--------|-----------|
| 1. Summarize | `summarize.py` | `summarize_sources()` | `spec-intake-summarize` |
| 2. Discover | `discover.py` | `discover_libraries()` | `spec-intake-discover-libraries` |
| 3. Route | `route.py` | `route_sources()` | `spec-intake-route` |
| 4. Coverage | `coverage.py` | `check_coverage()` | `spec-intake-coverage-filter` |
| 5. Assemble | `assemble.py` | `assemble_output()` | (deterministic) |

### Key properties (all verified in code)

* **Libraries = skeletons**: Phase 0 proposes libraries via LLM discovery.
  The refinement engine then analyzes cohesion/coupling of these skeletons.
* **Verbatim copy**: Output contains original source text via `_extract_verbatim()`.
* **LLM does classification, not extraction**: Routing uses reimplementation test.
* **Coverage ledger = termination**: `coverage_ledger.jsonl` tracks every line.
* **Rediscovery loop**: If content doesn't fit any library, routing triggers
  library rediscovery with feedback.

### Output format

```text
phase0_output/
├── summaries/          # Per-file summary JSON (routing hints only)
├── libraries.json      # Library definitions
├── route_table.jsonl   # Source span → destination mappings
├── coverage_ledger.jsonl
├── libraries/          # Per-library assembled output
│   ├── LIB-01/
│   │   ├── analysis.md
│   │   ├── constraints.md
│   │   └── details/
│   │       ├── algorithms.md
│   │       ├── stores.md
│   │       └── shapes.md
│   └── ...
└── system/             # Cross-library constraints
    └── constraints.md
```

---

## Key Files

### Source algorithms (AUTHORITATIVE)

* `.tasks/plans/spec manager/simpler.md` — Design #2 (PDD lifecycle + intake)
* `.tasks/plans/spec manager/ALGORITHM.md` — Design #1 (evidence preservation)
* `scripts/spec_manager/EVOLUTION_PLAN.md` — Design #1 (strategy framework)
* `scripts/spec_manager/PLAN.md` — Design #1 (enhancement plan)

### Phase 0 research (AUTHORITATIVE for intake algorithm)

* `.tasks/plans/spec manager/PHASE0_RESEARCH_PROMPT.md` — Problem statement
* `.tasks/plans/spec manager/PHASE0_RESEARCH_RESPONSE.md` — Solution: routing-table construction

### Plans (how PDD modules were built)

* `.tasks/plans/spec manager/plans/` — 11 core + 5 refactors + 3 fixes

### Tracking

* `.tasks/plans/spec manager/LONG_TERM_GOALS.md` — Current phase + roadmap
* `.tasks/plans/spec manager/EXPECTED_STATE.md` — What "done" looks like

---

## Verification Checklist (Phase 3 — ALL PASS)

* [x] Each orchestrator phase calls the real PDD module entry point
* [x] `_run_refinement_engine()` is analysis-only (no executor.execute calls)
* [x] Phase 0 intake output correctly feeds into Phase 1+
* [x] Shared infrastructure (signal resolver, interactive mode, eval framework)
      is usable by PDD modules
* [x] Tests validate PDD behavior
* [x] All 2197 tests pass
* [x] Full pipeline runs end-to-end against treasury spec
  * Phase 0: 100% coverage, 90.4% requirement recall @0.6, 100% sectionization
  * 7 libraries discovered (vs 8 ground truth) — LLM judgment variance
  * No code bugs found; fuzzy scoring undervalues semantic equivalence

---

## Phase 4: PDD Lifecycle Orchestration (In Progress)

### What Was Done

1. **PDD lifecycle orchestrator** (`orchestration/pdd_lifecycle.py`) wires
   the 人们对4-phase lifecycle from simpler.md: Build→QA→Architecture→Code Quality.

2. **VCS abstraction** (`orchestration/vcs.py`): Protocol-based abstraction
   (`VcsOperations`) with `GitVcs` implementation. Wraps subprocess git calls.
   Per simpler.md: *"It could be jj. It could be git. We don't care."*

3. **Worktree management** (`orchestration/worktree_manager.py`): Implements
   simpler.md's worktree hierarchy — dirty root, per-library grandchildren,
   clean sibling. Methods: setup, create, promote, rebase, cleanup.

4. **Human approval loop**: `build_with_approval()` implements steps 8-12
   from simpler.md. Auto-approves in auto/steering mode. Interactive mode
   prompts user with approve/feedback/quit options. Feedback written to disk.
   Max iterations guard prevents infinite loops.

5. **CLI integration**: `--worktrees` flag enables worktree management.

6. **2300 tests pass** (76 new tests for worktree management + approval loop).
