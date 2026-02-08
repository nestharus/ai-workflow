# PDD Sources of Truth

## CRITICAL: Read this file before any spec manager work

There is ONE system: PDD. Phase 0 of PDD is extraction — converting
input to the PDD format. Phase 0 processes files independently, then
resolves cross-references across files.

**Read the Phase 0 design docs before implementing extraction:**
- `phase0/00_CLASSIFICATION.md` — the invariant trap
- `phase0/01_CROSS_REFERENCES.md` — inter-file reference handling
- `phase0/02_REAL_SPEC_PATTERNS.md` — what real specs look like
- `phase0/03_CONTINUOUS_REFINEMENT.md` — coupling/cohesion across
  promotion layers
- `phase0/04_COVERAGE_TRACKING.md` — sentence-level normative coverage
- `phase0/05_CLASSIFIER_DESIGN.md` — two-pass classifier with invariant
  challenge

---

## Origin Document

Where PDD was introduced. Shows the evolution from spec decomposition →
continuous spec refinement → Prototype Driven Development. Discusses code
ingest (brownfield) but not freeform spec ingest.

- `.tasks/plans/spec manager/simpler.md`

## PDD Foundation

The paradigm document. Defines edit-in-place, pin-functions, branches,
promotions, the algorithmic/architectural/analysis layer model, and the
core PDD loop.

- `.tasks/plans/spec manager/algorithmic-projection-patch.md`

## PDD Implementation Plans

These define the PDD modules. Each plan maps to a module in
`scripts/spec_manager/spec_manager/`.

| Plan | Module | What it defines |
|------|--------|----------------|
| `plans/01-edit-in-place-engine.md` | `core/edit_in_place.py` | Source analysis, comment=gap detection, stub detection |
| `plans/02-pin-functions.md` | `pin_functions/` | Pin-function extraction, import graph, projection types |
| `plans/03-planning-module.md` | `planning/` | Code parsing, comment insertion, reverse translation, micro-unit decomposition |
| `plans/04-branch-organization.md` | `branches/` | Branch types, atom registry, vertical/horizontal slices, promotion workflow |
| `plans/05-executable-gap-detection.md` | `compliance/detection/` | Comment scanner, stub scanner, runtime detector, call graph, coverage |
| `plans/06-hollowed-out-spec-evidence.md` | `compliance/promotion/` | Evidence store for ambiguity research during translation |
| `plans/07-adjacency-detection.md` | `analysis/adjacency/` | Unified adjacency graph, co-occurrence, store-touch edges |
| `plans/08-compliance-gating.md` | `compliance/promotion/` | Gate checks at promotion boundaries |
| `plans/09-lineage-tracking.md` | `projection/lineage/` | Lineage edges, drift detection, pin propagation |
| `plans/10-strategy-evolution.md` | `strategies/evolution.py` | Strategy gap capture, evolution loop |
| `plans/11-analysis-file-generator.md` | `analysis/generator.py` | Computed analysis artifact from pin graph |

### Fix Plans

- `plans/fix-01-unify-projection-types.md`
- `plans/fix-02-test-pin-validation.md`
- `plans/fix-03-spec-entity-coverage.md`

### Refactor Plans

- `plans/refactor-01-merge-planning.md`
- `plans/refactor-02-decompose-branches.md`
- `plans/refactor-03-consolidate-adjacency.md`
- `plans/refactor-04-deduplicate-pins.md`
- `plans/refactor-05-wire-branches-workflow.md`

---

## Phase 0: Extraction

Phase 0 converts arbitrary input into the PDD format. It processes
one file at a time, then resolves cross-references across files.

### The PDD Spec Format (output of Phase 0)

1. **Analysis docs** — options explored, decisions made, tradeoff
   reasoning ("We chose X because Y")
2. **Constraints / Invariants** — shared guiding principles, priorities,
   and rules that must always hold REGARDLESS of implementation
   (e.g. "Trust > Friction > Performance", "No silent termination",
   "Tier-1 clients always override risk caps")
3. **Details** — algorithms, shapes, and stores (the actual code with
   pseudocode comments that get translated in place)

No separate "overview" document. Function composition in the details IS
the overview.

All elements receive unique IDs.

### THE INVARIANT TRAP (critical for classification)

Real specs write algorithmic details using constraint language ("MUST").
~95% of "MUST" statements in real specs are algorithms or shapes, NOT
invariants.

**Invariants are WHY** — guiding principles that survive any
reimplementation:
- "Trust > Friction > Performance"
- "No silent termination"
- "Concurrent modifications must never corrupt state"

**Algorithms are HOW** — implementation steps, even when phrased with
"MUST":
- "MUST acquire lock before writing" (a specific locking approach)
- "MUST emit step_start event" (a specific evidence approach)
- "MUST validate via dry-run apply" (a specific validation approach)

**Shapes are WHAT** — data structures, even when phrased with "MUST":
- "field MUST be a ULID" (field type definition)
- "MUST include blocker_kind when blocked" (schema rule)
- "schema_version MUST be 2" (version constraint on a data format)

See `phase0/00_CLASSIFICATION.md` for detailed examples and classifier
guidance.

### Classification targets

| Input content | PDD output | Example |
|--------------|-----------|---------|
| Prose describing what something does | Pseudocode (algorithm, shape, or store) | "The system validates payment against fraud rules" → `# validate payment against fraud rules` |
| Prose calling out priorities/tradeoffs that survive any reimplementation | Constraint doc | "Trust always comes before performance" → constraint |
| Prose discussing decisions/rationale/options | Analysis doc | "We chose event-driven over polling because..." → analysis |
| Implementation rules ("MUST do X, then Y") | Pseudocode (algorithm) | "MUST acquire lock, then write, then release" → algorithm steps |
| Data structure rules ("field X MUST be Y") | Pseudocode (shape) | "ticket.json MUST include status field" → shape definition |
| Already pseudocode | Move as-is | No rewrite needed |
| Already code (brownfield) | Collapse to Layer 1 | Extract algorithms, separate architecture |

### Processing model

1. **Pass 1 (per-file)**: Intake → sectionize → decompose → classify
   → record cross-references as metadata
2. **Pass 2 (cross-file)**: Resolve references → establish authority
   chains → deduplicate overlaps
3. **Pass 3 (organize)**: Discover or respect existing library
   structure → output PDD format files
4. **Pass 4 (verify)**: Coverage check — every normative sentence has
   a home

LLMs are not constrained to one file — they can follow references to
understand context. This simplifies cross-reference handling: the LLM
reads referenced files as needed during classification. See
`phase0/01_CROSS_REFERENCES.md` for reference types and approach.

### Phase 0 tracks

- **Coverage** — every normative sentence must have a home in output
- **Extraction failures** — pieces that couldn't be classified
- **Unresolved references** — cross-references to files not in input

### Phase 0 does NOT do

- Gap detection (PDD discovers gaps by trying to implement)
- Compliance gating (just extracting, not judging quality)
- Strategy engine (overkill for extraction)
- Gap closure loops (that's theorizing)
- Projection + sync (PDD doesn't use plan documents)
- Task planning (PDD discovers tasks by trying to implement)
- Co-evolution loops (PDD handles implementation via edit-in-place)

Key principle: **maximize 1:1 extractions without rewrites**. Prose
that describes behavior becomes pseudocode comments nearly verbatim.
Prose that states guiding principles becomes constraints nearly
verbatim. Only restructure when the input is genuinely ambiguous about
WHAT it is.

---

## Phase 0 Design Docs

| Design Doc | What it covers |
|-----------|---------------|
| `phase0/00_CLASSIFICATION.md` | Three-way classification, the invariant trap, real examples, classifier guidance |
| `phase0/01_CROSS_REFERENCES.md` | Reference types (delegation, authority, enrichment, cross-cutting), per-file processing model, overlap detection |
| `phase0/02_REAL_SPEC_PATTERNS.md` | Workflow Engine 3 analysis: document hierarchy, format diversity, pre-structured input, coverage risk, overlap patterns |
| `phase0/03_CONTINUOUS_REFINEMENT.md` | Coupling/cohesion algorithm applied to all PDD promotion layers, what was kept/abandoned from algorithm decomposition design |
| `phase0/04_COVERAGE_TRACKING.md` | Sentence-level normative content tracking, extraction failure reporting, lineage through SPLIT/MERGE/REWRITE, per-file and aggregate coverage reports |
| `phase0/05_CLASSIFIER_DESIGN.md` | LLM classifier prompt structure, two-pass classification (initial + invariant challenge), reimplementation test, few-shot examples, batch processing, validation heuristics |

---

## Continuous Refinement

PDD needs continuous refinement at every promotion layer. As entities
are added or modified, the grouping structure (libraries at Layer 1,
components at Layer 2, etc.) may need restructuring.

The core algorithm detects three states:
- **Overlap** — Same capability in multiple grouping units → deduplicate
- **Divergence** — Grouping unit has too many unrelated capabilities → split
- **Responsibility Overload** — Single capability is too complex → decompose

This algorithm was originally designed for architecture decomposition
(`.tasks/plans/algorithm decomposition/algorithm decomposition feedback.md`)
with a graph representation
(`.tasks/plans/algorithm graph creator/feedback.md`). PDD adopts the
coupling/cohesion detection and horizontal/vertical slicing concepts but
NOT the static shape system or constraint propagation.

The `discovery/` module (removed in `debd3f6`) was the implementation
of continuous library refinement: candidate identification → multi-label
assignment → shape aggregation → iterative refinement → primary
assignment. The design is preserved in `clean/07_LIBRARY_DISCOVERY.md`
and `clean/08_LIBRARY_SPEC_BUILDING.md`. PDD needs to reimplement this
capability.

See `phase0/03_CONTINUOUS_REFINEMENT.md` for full details.

---

## Spec Refinement Design Docs (selective use for Phase 0)

### Useful for Phase 0

| Design Doc | What Phase 0 uses from it |
|-----------|--------------------------|
| `clean/00_ID_REGISTRY.md` | ID system for atoms, files, evidence ranges |
| `clean/01_EVIDENCE_LAYER.md` | Atom ingestion, file revisions, evidence ranges |
| `clean/13_STRUCTURE_AND_DECOMPOSITION.md` | Sectionization, entity extraction, surgical decomposition |
| `clean/07_LIBRARY_DISCOVERY.md` | Co-occurrence graph, library candidates, multi-label assignment, overlap resolution. Cross-ref findings in `phase0/01_CROSS_REFERENCES.md`. |
| `clean/02_PROVENANCE_AND_MEMBERSHIP.md` | Atom-level tracking, coverage verification, lineage edges. Cross-ref findings in `phase0/01_CROSS_REFERENCES.md`. |
| `clean/03_TRANSFORM_AND_COMPOSITING.md` | Moving/recomposing content without rewrites |
| `clean/12_AGENT_CONTRACTS.md` | How agents are invoked |
| `clean/08_LIBRARY_SPEC_BUILDING.md` | Library charter building, spec index, relation edges. Used by continuous refinement. See `phase0/03_CONTINUOUS_REFINEMENT.md`. |

### NOT primary references (superseded by plans 01-11)

These OLD spec refinement design docs are not primary references. The
PDD modules were built from plans 01-11 (not from these docs). PDD
discovers gaps, validates quality, and plans tasks by trying to
implement.

| Design Doc | Why not needed |
|-----------|---------------|
| `clean/04_STRATEGY_ENGINE.md` | PDD discovers issues by trying, not by strategizing |
| `clean/05_COMPLIANCE_AND_VALIDATION.md` | PDD validates by running code, not by gating |
| `clean/06_GAP_DETECTION.md` | PDD's gap system: comments=gaps, stubs=gaps (mechanical) |
| `clean/09_PROJECTION_AND_SYNC.md` | PDD doesn't generate plan documents |
| `clean/10_TASK_PLANNING_AND_IMPLEMENTATION_LOOP.md` | PDD discovers tasks by trying |
| `clean/11_AUDIT_AND_QA.md` | Eval system (separate) |
| `clean/14_ARCHITECTURE_AND_TRADEOFFS.md` | Old refinement system architecture |
| `clean/15_WORKFLOW_ORCHESTRATOR.md` | 19-phase orchestration (replaced) |
| `clean/16_CLI_SCRIPTS.md` | Old CLI commands |
| `clean/17_STRATEGY_CATALOG.md` | Strategy catalog (not used) |
| `overview/05_IMPLEMENTATION_COEVOLUTION.md` | PDD uses edit-in-place instead |

### Useful as reference

| Design Doc | What it provides |
|-----------|-----------------|
| `overview/00_SYSTEM_OVERVIEW.md` | L0 evidence layer concept (atoms are immutable) |
| `overview/01_WORKFLOW_END_TO_END.md` | Context for understanding Phase 0 steps |
| `overview/03_FAILURE_HANDLING_PROGRESS_GUARANTEE.md` | Fallback approaches for extraction failures |
| `overview/04_LIBRARY_BOUNDARIES_AND_RELATIONS.md` | Library structure, overlap resolution |
| `constraints/` (all files) | Global constraints that apply to extraction |
| `analysis/` (all files) | Design decision rationale |
| `templates/` (all files) | JSON schemas for data shapes |
| `clean/98_ALGORITHM_INDEX.md` | Algorithm reference |
| `clean/99_ALGORITHM_COMPENDIUM.md` | Algorithm details |

---

## Origin Algorithms (continuous refinement)

These define the coupling/cohesion algorithm that PDD applies at every
promotion layer. The algorithm was abandoned as a standalone system (used
static shapes) but the core concepts were adopted.

| Document | What PDD uses from it |
|----------|----------------------|
| `.tasks/plans/algorithm decomposition/algorithm decomposition feedback.md` | Overlap/divergence/overload detection, split/merge/move operations, horizontal/vertical slicing, evaluation flow, post-operation propagation |
| `.tasks/plans/algorithm graph creator/feedback.md` | Graph construction from entities, capability profiles, incremental recomputation concept |

What PDD does NOT use: static shapes for all layers (PDD uses dynamic
projections), constraint propagation (PDD discovers by running),
the specific ID system (COM/SUR/ALG/CON/CAP/INV/OBL).

---

## Research

External techniques survey. Informs Phase 0 extraction decisions
(two-stage extraction, fact extraction, provenance).

- `.tasks/plans/spec manager/research-report-spec-refinement-techniques.md`

---

## Evaluation System (separate from PDD)

The eval framework evaluates PDD output but is not part of PDD itself.

- Location: `scripts/spec_manager/spec_manager/refinement/evals/`
- Fixtures: `refinement/evals/inputs/fixtures/` (chaotic_treasury.yaml
  is the treasury test)

---

## Test Specs

| Spec | Location | Complexity | What it tests |
|------|----------|-----------|---------------|
| `chaotic_treasury` | `refinement/evals/inputs/fixtures/chaotic_treasury.yaml` | 30 rules, 6 libraries → scaled to multi-file web | PDD loop quality + Phase 0 extraction (cross-refs, invariant trap, format diversity) |
| 8 math fixtures | `refinement/evals/inputs/fixtures/` | Single-library, trivial | Regression tests (not primary) |

Treasury spec scales to capture multi-file failure modes (cross-references,
invariant trap, implicit constraints, format diversity, scattered requirements).
Ground truth scales in parallel — every new rule/constraint has a corresponding
expected output.

Workflow Engine 3 (`.tasks/plans/workflow engine 3/`, 78 files, 13,700 lines)
is a design reference for Phase 0 extraction analysis. It cannot be scored
and is not an eval target. See `phase0/02_REAL_SPEC_PATTERNS.md`.

---

## Status/Meta Documents

These track project status. They are NOT design documents.

- `LONG_TERM_GOALS.md` — what needs to happen
- `CONSOLIDATION_CONCLUSIONS.md` — history and findings
- `CONSOLIDATION_LOG.md` — log of actual changes
- `EXPECTED_STATE.md` — target state (references design docs)
- `PRODUCTION_CODE_AUDIT.md` — refinement pipeline problems
- `PDD_SOURCES_OF_TRUTH.md` — this file

---

## Ingestion Types

PDD needs to handle multiple input types. Each routes differently:

| Input Type | What happens | Phase 0 needed? |
|-----------|-------------|-----------------|
| **Prose specs** (freeform requirements, PRDs) | Per-file intake → sectionize → decompose → classify → cross-ref resolution → library organization → output | Yes, full |
| **Pseudocode** (already structured) | Classify as algorithm/shape/store and move into details. No rewriting. | Minimal (classify only) |
| **Code (brownfield)** | Collapse to Layer 1. Extract algorithms, separate from architecture. | Yes, via code analysis not prose extraction |
| **Mixed** | Classify each piece (prose vs pseudocode vs code) and route accordingly | Yes, classifier + routing |
| **Pre-structured specs** (existing library organization) | Detect existing structure, respect it, classify within each library | Yes, but skip library discovery |

---

## The PDD Loop (after Phase 0)

Once specs are in PDD format:

1. Start with pseudocode (comments in real code files)
2. Try to implement — translate comments to code in place
3. Implementation failures reveal ambiguities/underspec → write new
   pseudocode stubs → ship to research
4. Constraint docs + analysis docs inform planning
5. Planning refines and adds non-ambiguous pseudocode
6. Implementor translates pseudocode → code, informs planning on failure
7. Result: spec of algorithms, shapes, and stores
8. Promote upward — each promotion decorates the prior phase using PDD
9. At each promotion level, LLMs focus on newly introduced elements;
   prior phase is distributed underneath
10. No comments allowed in production code = mechanical gap detection

Promotions add architecture, code quality, etc. You can have any number
of promotions and branch them. Like making a compiler — each pass
transforms the prior output.
