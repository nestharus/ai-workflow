# Spec Manager Consolidation: Conclusions

## CRITICAL: Read this file before any spec manager work

This file records conclusions from investigation sessions (Feb 6-8 2026).

---

## Consolidation Status: Phase 0 DONE, Phases 1-10 NOT DONE

### What Was Done

1. **Legacy dead code removed**: workflow/, workspace/, staging/, discovery/,
    merging/, verification/ — all deleted.

2. **Shared infrastructure extracted**: 8 modules moved from refinement/ to
    core/ (gap.py, agent_utils.py, evidence_pointers.py, etc.)

3. **Cross-contamination eliminated**: core/, schemas/, and all PDD modules
    have zero refinement/ imports.

4. **Phase 0 intake implemented correctly** in `intake/`:
   * Routing-based restructuring per PHASE0_RESEARCH_RESPONSE.md
   * All three required operators: routing unit, routing ledger, invariant test
   * Libraries skeletons (proposed by Phase 0, analyzed by refinement engine)
   * ProseExtractor (unauthorized regex extraction) removed

5. **11 PDD modules built** per plans 01-11, all verified against plans.

### What Was Not Done

The PDD orchestrator (phases 1-10) does NOT use the PDD modules.

Every phase from 1-10 does its own simplified structural analysis (counting
functions, counting atoms, counting gaps) instead of delegating to the real
PDD module implementations. The modules exist, are tested, and work — but
the orchestrator ignores them.

This is the ACTUAL consolidation problem. The old problem (refinement
pipeline's 19-phase orchestration vs PDD modules) was partially solved by
creating `orchestration/pdd_orchestrator.py`, but the orchestrator is a
thin scaffold that doesn't call the real modules.

### Design Violation: Refinement Engine Mutations

`_run_refinement_engine()` in the PDD orchestrator calls
`executor.execute(op)` which MUTATES the branch manager. Per design:

* The refinement engine is for **analysis only** (cohesion/coupling of skeletons)
* It should NEVER execute mutations
* It should report grouping issues for human/system review
* The executor.execute() calls must be removed

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

## Verification Checklist

After Phase 3 (wire orchestrator), verify:

* [ ] Each orchestrator phase calls the real PDD module entry point
* [ ] `_run_refinement_engine()` is analysis-only (no executor.execute calls)
* [ ] Phase 0 intake output correctly feeds into Phase 1+
* [ ] Full pipeline runs end-to-end without errors
* [ ] Shared infrastructure (signal resolver, interactive mode, eval framework)
      is usable by PDD modules
* [ ] Tests validate PDD behavior
* [ ] All 2195+ tests pass
