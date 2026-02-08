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

* INIT → SECTIONIZATION → SUMMARIZATION → LIBRARY_SYNTHESIS → EVIDENCE_EXPANSION
* → SPEC_BUILDING → SPEC_STABILIZATION → ALIGNMENT_CHECK → OVERVIEW_GENERATION
* → QA_EVALUATION → SUBLIBRARY_DETECTION → ARCH_PROPOSAL → ARCH_SELECTION
* → ARCH_MAPPING → STRUCTURE_REVIEW → INTERFACES → QUALITY_GATES → TASKS
* → IMPLEMENTATION → AUDIT

**Why it's wrong** (per the implementation plans in `.tasks/plans/spec manager/plans/`)

* Plan 01 (edit-in-place-engine.md) says: "The current system (Phase 1 sectionization)
  reads source/spec documents and uses LLM agents to extract section spans. The spec
  is a *separate artifact* derived from source material. This separation means the
  spec and code can drift apart."
* Plan 03 (planning-module.md) says: "None of the existing modules implement: Parsing
  real code to find insertion points, reverse-translating code to pseudocode,
  decomposing plans into micro-unit comments, adjacent detail discovery, evidence
  store integration."

The refinement pipeline creates drift because it maintains specs as separate artifacts
from code. The design (.tasks/plans/spec manager/design/) defines a completely
different phase structure (Phases 0-10) that the refinement pipeline does not follow.

### System B: PDD Modules (THE RIGHT SYSTEM)

These were built per the plans in `.tasks/plans/spec manager/plans/`:

| Module | Location | Plan |
|--------|----------|------|
| Edit-in-Place Engine | `core/edit_in_place.py`, | Plan 01 |
| | `core/edit_in_place_bridge.py` | |
| Pin-Functions | `pin_functions/` | Plan 02 |
| Planning (algorithmic) | `planning/` (models, code_parser, inserter, reverser,
  adjacency, evidence_store, gap_bridge, algo_cli, workflow) | Plan 03 |
| Branch Organization | `branches/` (13 files: types, layout, atoms, pins,
  promotion, compliance, gap_detection, downward_flow, collapse, slices,
  analysis, manager) | Plan 04 |
| Executable Gap Detection | `compliance/detection/` | Plan 05 |
| Hollowed-Out Spec Evidence | `compliance/promotion/` | Plan 06 |
| Adjacency Detection | `analysis/adjacency/` | Plan 07 |
| Compliance Gating | (in compliance/) | Plan 08 |
| Lineage Tracking | `projection/lineage/` | Plan 09 |
| Strategy Evolution | `strategies/evolution.py` | Plan 10 |
| Analysis File Generator | `analysis/generator.py` | Plan 11 |

**Why it's right**: These implement the actual design:

* Code IS the spec (no drift)
* Comments = gaps (mechanical detection, no LLM inference)
* Pin-functions = real Python imports (not offset-based pins)
* Branches = algorithmic/architectural/analysis layers
* Compliance gating at promotion boundaries

### What Happened

* Session `0e59fabb` (Feb 6): Sub-agents built all 11 PDD modules as **standalone
  packages** alongside the refinement pipeline instead of integrating them.

* User caught it immediately: "Why does it look like it just built a separate
  independent system rather than enhancing the existing system?"

* Refactors were created (refactor-01 through refactor-05) but only fixed naming
  and surface-level deduplication. The fundamental orchestration split was not
  addressed.

* Session `ebc53202`: Signal resolver, eval fixtures, and interactive improvements
  were built into the **refinement pipeline** (wrong system), deepening the split.

* Session `1ab2d195`: Investigation correctly identified the problem but the
  consolidation plan only deleted "Legacy System A" (the already-dead workflow/,
  workspace/, staging/ packages) — the easiest, least important part.

---

## What Consolidation Actually Means

### NOT THIS (what was done)

* Delete dead code in workflow/, workspace/, staging/, discovery/, merging/,
  verification/
* (This was Legacy System A — already unused. Deleting it fixed nothing.)

### THIS (what needs to happen)

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

## Design Lineage (Feb 8 2026)

### CRITICAL: The design/ directory is NOT authoritative

`.tasks/plans/spec manager/design/` was supposed to encode Design #2 (simpler.md)
but the LLM that wrote those docs **went rogue**. Specifically:

* `design/overview/01_WORKFLOW_END_TO_END.md` labels Phase 0 as "Intake
  (Deterministic)" — this is wrong for freeform prose input.
* `design/clean/13_STRUCTURE_AND_DECOMPOSITION.md` Phase 1 Structure Discovery
  algorithm contradicts the core constraint: you cannot extract atoms from
  freeform prose using regex or scripts.
* The design docs threw out the actual extraction process described in simpler.md
  and invented their own.

**DO NOT use the design/ directory as authoritative for intake/extraction.**

### Three designs, in chronological order

| Design | Source Files | Core Idea |
|--------|-------------|-----------|
| #1 | `ALGORITHM.md`, `PLAN.md`, `EVOLUTION_PLAN.md` | Evidence preservation: index
| | | lines to entities, never rewrite source, strategy-driven risk
| | | minimization, unitizer strategies, LLM inference as first-class |
| #2 | `simpler.md` | No extraction: summarize with LLM, identify libraries,
| | | detect overlap, isolate concerns, refine specs iteratively. PDD:
| | | build prototype in phases, each messy, next cleans up |
| #3 | PDD modules (current codebase) | Code IS the spec, comments = gaps,
| | | pin-functions, branches, compliance gating |

### Design #1: ALGORITHM.md + PLAN.md + EVOLUTION_PLAN.md

* `.tasks/plans/spec manager/ALGORITHM.md` — Evidence preservation algorithm
  (11 phases, line indexing, cluster hunt, semantic classification, coverage
  verification). Core rule: "NEVER rewrite or summarize source material."
* `.tasks/plans/spec manager/PLAN.md` — Enhancement plan (subsystem libraries,
  I# invariants, @pin syntax, drift detection)
* `scripts/spec_manager/EVOLUTION_PLAN.md` — Strategy-driven processing
  (unitizer strategies, LLM inference, gap as first-class element, line
  membership guarantee, many-to-many provenance)

### Design #2: simpler.md

* `.tasks/plans/spec manager/simpler.md` — Core constraint: "You cannot
  assume that any text within a spec follows a set pattern. These patterns
  cannot be extracted by regex or any type of script. The best thing to
  recognize general patterns is an LLM."
* Algorithm: Summarize → Identify libraries → Detect overlap → Isolate
  concerns → Refine specs → Resolve ambiguities
* Output format: Analysis Docs, Constraints, Overview, Details (algorithms
  and shapes)
* PDD section: Build prototype in phases, each produces something messy,
  next phase cleans it up

### Design #3: PDD (current implementation)

Plans 01-11 in `.tasks/plans/spec manager/plans/`. These modules are built,
standalone, CLI-integrated. They operate on STRUCTURED input (annotated
specs with ([=ID]) markers, Analysis/Constraints/Overview/Details format).

---

## Phase 0: Routing-Based Restructuring (Feb 8 2026)

### PDD needs structured input

PDD modules expect input in a specific format:

* Analysis Docs — options and why things were chosen
* Constraints — shared guiding principles
* Overview — how things fit together (prose)
* Details — algorithms and shapes (sub-types: algorithms, stores, shapes)
* All elements have unique IDs (([=ID]) annotations)

Freeform prose specs are NOT in this format. Phase 0 bridges the gap.

### Two scenarios

**Scenario A: Input is already structured** → skip Phase 0, go into PDD.

**Scenario B: Input is freeform prose** → Phase 0 restructures it.

### Why Design #2's "refinement" step was underspecified

External research (Feb 8 2026) identified six failures in the simpler.md
algorithm as stated:

1. **"Refine" implicitly requires extraction.** "Rewrite and label" is
   extraction-by-another-name. You're generating new representations and
   inevitably dropping details. After iterations, the refined spec becomes
   a lossy reinterpretation, not a reorganization.

2. **No legal routing unit.** Without defining what unit gets moved,
   you fall back to paragraphs (loses context), overlapping windows
   (fails), or semantic retrieval (fails). Need: contiguous source spans.

3. **No completeness definition.** "Refine until details accounted for"
   is undefined without a ledger. Every source line must be routed to
   ≥1 output element, or explicitly marked ignored with a reason. This
   is Design #1's line membership guarantee, simplified.

4. **Invariant trap not solved by libraries alone.** Libraries answer
   "what area?" Categories answer "what kind of statement?" These are
   orthogonal. Library discovery alone cannot separate "must emit
   step_start/step_stop" (mechanism) from "must be able to reconstruct
   what happened" (invariant). Needs a routing-time classification rule.

5. **Cross-file references.** Can't load all files at once. When a
   reference to another file is encountered, record as REF-STUB pointer,
   resolve later when that file is processed.

6. **Recursion stopping rule.** "Until no more candidates" is not
   measurable without a coverage ledger and stability criterion.

### The correct definition of "refinement"

Refinement is NOT rewriting. Refinement is ROUTING:

> **Build a routing table that maps raw source spans (file, start_line,
> end_line) into structured destinations (library + category + element ID),
> then assemble output by verbatim copy.**

No paraphrase. No decomposition into atoms. No semantic retrieval.
Summaries are used ONLY for routing decisions (which library, which
category). The final output contains verbatim source text, not summaries.

### Phase 0 algorithm (corrected)

**Step 1: Summarize** (for routing, not for output)

* One LLM agent per source file
* Produce high-level summary: what's in there, what libraries it
  contributes to, what kinds of content (algorithms, shapes, invariants,
  analysis)
* Summaries go to `summaries/FILE.md`
* Summaries are ROUTING HINTS, not final output

**Step 2: Library discovery** (from summaries)

* Identify high-level concerns / libraries from summaries
* Detect overlap between libraries
* Assign overlap or create new libraries
* Output: `libraries.yaml` with library IDs and short descriptions
* Libraries EMERGE from data, not hardcoded

**Step 3: Route** (the core operation)

* For each source file, LLM reads the file and produces routing decisions
* Each decision maps a contiguous source span to a destination:
  * Library assignment (which library)
  * Category assignment (Analysis / Constraints / Overview / Details)
  * Sub-category for Details (algorithm / store / shape)
  * Element ID assignment
* The routing decision uses the **reimplementation test** for classification:
  "Does this survive a complete reimplementation?" → Constraint.
  Otherwise → Detail (algorithm, store, or shape) or Analysis or Overview.
* Cross-file references recorded as REF-STUB pointers
* Output: `route_table.jsonl`

**Step 4: Coverage check** (termination criterion)

* Every source line must be routed or explicitly ignored
* Output: `coverage_ledger.jsonl`
* If coverage < 100%: return to Step 3 for unrouted spans
* Stopping: coverage 100% AND library map stable

**Step 5: Assemble** (deterministic)

* Apply routing table: copy verbatim source spans into destination files
* Organize by library → category
* Assign ([=ID]) annotations
* Resolve REF-STUB pointers to final locations
* Output: Analysis/, Constraints/, Overview/, Details/ files per library

### The routing table (core artifact)

```json
{
  "route_id": "R-000812",
  "src": {"file": "tickets.md", "start": 410, "end": 487},
  "dest": {
    "library": "LIB-03",
    "category": "DETAIL/ALGORITHM",
    "element_id": "ALG-LIB03-014"
  },
  "notes": "Ticket lifecycle procedure; invariant-like sentence at 412-413"
}
```

### Key properties

* **Verbatim copy.** Output contains original source text, not paraphrases.
  No information loss by construction.

* **LLM does classification, not extraction.** The LLM decides WHERE text
  goes (routing), not WHAT the text says (extraction).

* **Coverage ledger = termination.** You know you're done when every source
  line is accounted for.

* **Summaries are ephemeral.** Used for routing decisions, not preserved
  in output. The output IS the source text, reorganized.

* **Chunks of paragraphs are fine.** A routing span can be an entire
  paragraph or section. No need to decompose into atoms.

* **Mixed content handled by splitting spans.** If a paragraph contains
  both an invariant and algorithm, route the invariant lines to Constraints
  and the algorithm lines to Details. Smallest legal unit = contiguous
  lines that preserve meaning.

### What ProseExtractor is (unauthorized)

`orchestration/extraction.py` — ProseExtractor — uses regex for everything:

* CamelCase regex for library identification
* 11 hardcoded normative patterns for requirement detection
* Sentence boundary regex for splitting

This violates every constraint. The entire `orchestration/` directory
does not appear in EXPECTED_STATE.md. It was invented by a previous
session and is not authorized by any design.

---

## Key Files

### Source algorithms (AUTHORITATIVE)

* `.tasks/plans/spec manager/simpler.md` — Design #2 (intake algorithm)
* `.tasks/plans/spec manager/ALGORITHM.md` — Design #1 (evidence preservation)
* `scripts/spec_manager/EVOLUTION_PLAN.md` — Design #1 (strategy framework)
* `scripts/spec_manager/PLAN.md` — Design #1 (enhancement plan)

### Design docs (NOT AUTHORITATIVE for intake)

* `.tasks/plans/spec manager/design/` — went rogue, contradicts simpler.md

### Plans (how PDD modules were built)

* `.tasks/plans/spec manager/plans/01-edit-in-place-engine.md`
* `.tasks/plans/spec manager/plans/02-pin-functions.md`
* `.tasks/plans/spec manager/plans/03-planning-module.md`
* `.tasks/plans/spec manager/plans/04-branch-organization.md`
* `.tasks/plans/spec manager/plans/05-executable-gap-detection.md`
* `.tasks/plans/spec manager/plans/06-hollowed-out-spec-evidence.md`
* `.tasks/plans/spec manager/plans/07-adjacency-detection.md`
* `.tasks/plans/spec manager/plans/08-compliance-gating.md`
* `.tasks/plans/spec manager/plans/09-lineage-tracking.md`
* `.tasks/plans/spec manager/plans/10-strategy-evolution.md`
* `.tasks/plans/spec manager/plans/11-analysis-file-generator.md`

### Current system analysis (what exists now)

* `.tasks/plans/spec manager/system-analysis3.md` — documents the refinement
  pipeline

### This file

* `.tasks/plans/spec manager/CONSOLIDATION_CONCLUSIONS.md` — YOU ARE HERE

---

## Verification Checklist

After consolidation, verify:

* [ ] No imports from `spec_manager.refinement.workflows` for sectionization,
      summarization, library_synthesis, evidence_expansion, spec_building, etc.
* [ ] The PDD modules (branches, pin_functions, planning, edit_in_place) are the
      primary entry points
* [ ] The Phase enum matches the design (Phases 0-10), not the 19-phase refinement
      enum
* [ ] CLI commands match PDD operations
* [ ] Shared infrastructure (signal resolver, interactive mode, eval framework) is
      usable by PDD modules, not coupled to refinement
* [ ] Tests validate PDD behavior
* [ ] ProseExtractor and orchestration/ directory removed or replaced
* [ ] Phase 0 uses LLM-driven summarization (simpler.md), not regex extraction
* [ ] design/ directory docs not used as authoritative for intake/extraction
