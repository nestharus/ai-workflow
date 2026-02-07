# Spec Manager Consolidation: Conclusions

## CRITICAL: Read this file before any consolidation work

This file records conclusions from multiple investigation sessions (Feb 6-7 2026).
Every consolidation attempt so far has failed because the conclusions were lost
between sessions. DO NOT start consolidation work without reading this entire file.

---

## The Problem (Verified Across 3+ Sessions)

The spec manager has two complete, parallel architectures:

### System A: Refinement Pipeline (THE WRONG SYSTEM)

Location: `scripts/spec_manager/spec_manager/refinement/`

This is a 19-phase LLM-driven pipeline that extracts specs from prose documents:
- INIT → SECTIONIZATION → SUMMARIZATION → LIBRARY_SYNTHESIS → EVIDENCE_EXPANSION
- → SPEC_BUILDING → SPEC_STABILIZATION → ALIGNMENT_CHECK → OVERVIEW_GENERATION
- → QA_EVALUATION → SUBLIBRARY_DETECTION → ARCH_PROPOSAL → ARCH_SELECTION
- → ARCH_MAPPING → STRUCTURE_REVIEW → INTERFACES → QUALITY_GATES → TASKS
- → IMPLEMENTATION → AUDIT

**Why it's wrong** (per the implementation plans in `.tasks/plans/spec manager/plans/`):
- Plan 01 (edit-in-place-engine.md) says: "The current system (Phase 1 sectionization)
  reads source/spec documents and uses LLM agents to extract section spans. The spec
  is a *separate artifact* derived from source material. This separation means the
  spec and code can drift apart."
- Plan 03 (planning-module.md) says: "None of the existing modules implement: Parsing
  real code to find insertion points, reverse-translating code to pseudocode, decomposing
  plans into micro-unit comments, adjacent detail discovery, evidence store integration."

The refinement pipeline creates drift because it maintains specs as separate artifacts
from code. The design (.tasks/plans/spec manager/design/) defines a completely different
phase structure (Phases 0-10) that the refinement pipeline does not follow.

### System B: PDD Modules (THE RIGHT SYSTEM)

These were built per the plans in `.tasks/plans/spec manager/plans/`:

| Module | Location | Plan |
|--------|----------|------|
| Edit-in-Place Engine | `core/edit_in_place.py`, `core/edit_in_place_bridge.py` | Plan 01 |
| Pin-Functions | `pin_functions/` | Plan 02 |
| Planning (algorithmic) | `planning/` (models, code_parser, inserter, reverser, adjacency, evidence_store, gap_bridge, algo_cli, workflow) | Plan 03 |
| Branch Organization | `branches/` (13 files: types, layout, atoms, pins, promotion, compliance, gap_detection, downward_flow, collapse, slices, analysis, manager) | Plan 04 |
| Executable Gap Detection | `compliance/detection/` | Plan 05 |
| Hollowed-Out Spec Evidence | `compliance/promotion/` | Plan 06 |
| Adjacency Detection | `analysis/adjacency/` | Plan 07 |
| Compliance Gating | (in compliance/) | Plan 08 |
| Lineage Tracking | `projection/lineage/` | Plan 09 |
| Strategy Evolution | `strategies/evolution.py` | Plan 10 |
| Analysis File Generator | `analysis/generator.py` | Plan 11 |

**Why it's right**: These implement the actual design:
- Code IS the spec (no drift)
- Comments = gaps (mechanical detection, no LLM inference)
- Pin-functions = real Python imports (not offset-based pins)
- Branches = algorithmic/architectural/analysis layers
- Compliance gating at promotion boundaries

### What Happened

1. Session `0e59fabb` (Feb 6): Sub-agents built all 11 PDD modules as **standalone
   packages** alongside the refinement pipeline instead of integrating them.

2. User caught it immediately: "Why does it look like it just built a separate
   independent system rather than enhancing the existing system?"

3. Refactors were created (refactor-01 through refactor-05) but only fixed naming
   and surface-level deduplication. The fundamental orchestration split was not addressed.

4. Session `ebc53202`: Signal resolver, eval fixtures, and interactive improvements
   were built into the **refinement pipeline** (wrong system), deepening the split.

5. Session `1ab2d195`: Investigation correctly identified the problem but the
   consolidation plan only deleted "Legacy System A" (the already-dead workflow/,
   workspace/, staging/ packages) — the easiest, least important part.

---

## What Consolidation Actually Means

### NOT THIS (what was done):
- Delete dead code in workflow/, workspace/, staging/, discovery/, merging/, verification/
- (This was Legacy System A — already unused. Deleting it fixed nothing.)

### THIS (what needs to happen):

1. **The refinement pipeline's 19-phase orchestration must be replaced** by the PDD
   module architecture. The PDD modules implement the actual design.

2. **Shared infrastructure** (signal resolver, interactive mode, eval framework,
   workspace manager, agent runner) should be extracted from `refinement/` and made
   available to the PDD system.

3. **The Phase enum** should reflect the design document's phases (0-10), not the
   refinement pipeline's 19 phases.

4. **The CLI** should expose PDD operations as primary commands, not refinement
   phases.

5. **Tests** that test refinement pipeline behavior need to be updated to test PDD
   behavior instead.

---

## Key Files

### Design (what the system should be):
- `.tasks/plans/spec manager/design/overview/00_SYSTEM_OVERVIEW.md` — L0/L1/L2 layers
- `.tasks/plans/spec manager/design/overview/01_WORKFLOW_END_TO_END.md` — Phases 0-10

### Plans (how to build it):
- `.tasks/plans/spec manager/plans/01-edit-in-place-engine.md`
- `.tasks/plans/spec manager/plans/02-pin-functions.md`
- `.tasks/plans/spec manager/plans/03-planning-module.md`
- `.tasks/plans/spec manager/plans/04-branch-organization.md`
- `.tasks/plans/spec manager/plans/05-executable-gap-detection.md`
- `.tasks/plans/spec manager/plans/06-hollowed-out-spec-evidence.md`
- `.tasks/plans/spec manager/plans/07-adjacency-detection.md`
- `.tasks/plans/spec manager/plans/08-compliance-gating.md`
- `.tasks/plans/spec manager/plans/09-lineage-tracking.md`
- `.tasks/plans/spec manager/plans/10-strategy-evolution.md`
- `.tasks/plans/spec manager/plans/11-analysis-file-generator.md`

### Current system analysis (what exists now):
- `.tasks/plans/spec manager/system-analysis3.md` — documents the refinement pipeline

### This file:
- `.tasks/plans/spec manager/CONSOLIDATION_CONCLUSIONS.md` — YOU ARE HERE

---

## Verification Checklist

After consolidation, verify:
- [ ] No imports from `spec_manager.refinement.workflows` for sectionization, summarization,
      library_synthesis, evidence_expansion, spec_building, etc.
- [ ] The PDD modules (branches, pin_functions, planning, edit_in_place) are the primary
      entry points
- [ ] The Phase enum matches the design (Phases 0-10), not the 19-phase refinement enum
- [ ] CLI commands match PDD operations
- [ ] Shared infrastructure (signal resolver, interactive mode, eval framework) is usable
      by PDD modules, not coupled to refinement
- [ ] Tests validate PDD behavior
