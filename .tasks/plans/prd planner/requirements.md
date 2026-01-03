# PRD: PRD/Requirements Decomposer → Requirements Graph + Dependency-Safe Ticket Backlog

## Product outcome

Given any PRD/requirements document (including dense, prose-heavy docs), produce a structured, ticket-ready output:

* **Entities** (the “things” the doc talks about: components, artifacts, workflows, concepts)
* **Requirement Units (RUs)** (atomic correctness conditions derived from the doc, not from MUST/SHALL keywords)
* **Requirement Dependency Graph (RDG)** with typed edges and evidence
* **Standalone vs Dependent** partition of RUs/entities
* **Ticket backlog**: small, reviewable tickets that increase correctness coverage, each with prerequisites and suggested ordering
* **Audit + confidence**: coverage estimate or coverage proof (configurable mode), ambiguity surfaced as first-class items

The system may rely on an existing **Information Extraction (IE) system** as a component for candidate statement extraction + span/anchor tracking.

---

## Core artifacts the system owns

### A1. Canonical Requirements Graph (source of truth)

Nodes:

* `Entity`
* `RU` (Requirement Unit)
* `Definition` (optional)
* `Invariant` (optional; can be modeled as RU tagged invariant)

Edges:

* `requires` (hard prerequisite, typed + justified)
* `related` (soft link; not a prerequisite)

### A2. Ticket Backlog (derived view)

Ticket = minimal correctness-coverage increment (small by default; slightly larger acceptable).

Each ticket contains:

* `ticket_id`, `title`, `scope` (entities/RUs)
* `deps[]` (ticket prerequisites)
* `acceptance` (how to verify increment)
* `context_pack` (all relevant RUs + immediate dependency neighborhood)

### A3. Audit + Confidence (first-class output)

* what text was covered by extracted meaning vs treated as context
* unresolved ambiguity + missing verifiability prereqs
* confidence per RU and per dependency edge
* run-level confidence summary

---

## Non-negotiable invariants (product invariants)

I1. **No keyword hardcoding for requirement detection**
The system does not require MUST/SHALL/SHOULD markers. Those can be a weak signal, not a gate.

I2. **Traceability**
Every RU and every dependency edge references evidence anchors back to source spans.

I3. **Dependency semantics are explicit**
A hard prerequisite edge exists only if one of these is asserted:

* **Unsatisfiable**: B cannot be true unless A is true
* **Untestable**: B cannot be verified unless A exists
* **Mandated ordering**: doc implies order constraint (even if prose)

I4. **Small-ticket bias**
Default ticketization prefers smaller tickets that can be reviewed and verified independently.

I5. **Ambiguity is preserved, not guessed**
Ambiguous requirements become explicit RU candidates with “needs clarification” state, not silently forced into one interpretation.

---

## Entities (system components to build)

E0. **Graph Store**
Stores Entities, RUs, Edges, Anchors, Runs, Diffs.

E1. **Document Ingestor**
Accepts doc input, normalizes to text, tracks structure (sections/paragraphs).

E2. **Span Indexer**
Splits document into stable spans with IDs and offsets; maintains section paths.

E3. **IE Adapter**
Calls IE system, returns candidate atomic statements + occurrence anchors.

E4. **Extraction Orchestrator**
Iterative extraction strategy (planning-grade and coverage-grade modes).

E5. **RU Synthesizer**
Turns extracted statements into RUs: atomicity normalization, dedup, acceptance hooks, ambiguity tagging.

E6. **Entity Discoverer / Clusterer**
Finds/creates entities and attaches RUs; resolves “same entity” merges.

E7. **Dependency Inference Engine (RDG Builder)**
Builds typed `requires` edges + justification + evidence; detects cycles.

E8. **Standalone Maximizer (Decoupler)**
Reduces incidental coupling; separates behavior vs validation when allowed; lifts cross-cutting constraints into invariants.

E9. **Ticketizer + Roadmap Generator**
Creates tickets as correctness-coverage increments; outputs ordering + parallelizable sets.

E10. **Audit + Confidence Engine**
Coverage estimate/proof, drift risk, edge strength, ambiguity report.

E11. **Exporters**
JSON, Markdown, Mermaid/DOT, and “ticket context pack” bundles.

E12. **CLI (MVP interface)**
Runs decomposition and outputs artifacts; supports re-runs and diffs.

---

# Ticket-ready scope (ordered backlog with dependencies)

Conventions:

* **Epic** = major entity/area
* **Ticket** includes: `Deps`, `Outputs`, `Acceptance`
* Ordering is best-effort for a first pass; later planning can refine.

---

## EP0 — Canonical data model + persistence (foundation)

### T0.1 Define canonical IDs + schemas

* **Scope**: E0
* **Deps**: —
* **Outputs**: JSON schema for Entity, RU, Edge, Anchor, Run, Ticket
* **Acceptance**:

    * Stable ID rules documented (span IDs stable under minor edits where possible)
    * Schema supports evidence anchors per RU/edge

### T0.2 Implement Graph Store (file-based)

* **Scope**: E0
* **Deps**: T0.1
* **Outputs**: local persisted store (e.g., directory + JSON/SQLite)
* **Acceptance**:

    * Can write/read a graph and reproduce identical IDs for unchanged inputs

### T0.3 Run metadata + versioning

* **Scope**: E0
* **Deps**: T0.2
* **Outputs**: `Run` record includes doc hash, config, timestamps, IE model/version string
* **Acceptance**:

    * Two runs on same input/config produce diffable artifacts

---

## EP1 — Ingestion + span anchoring

### T1.1 Document ingestion (text/markdown)

* **Scope**: E1
* **Deps**: T0.2
* **Outputs**: normalized text + section structure + paragraph boundaries
* **Acceptance**:

    * Ingest returns section path + paragraph index mapping

### T1.2 Span Indexer (stable span IDs + offsets)

* **Scope**: E2
* **Deps**: T1.1, T0.1
* **Outputs**: spans `{span_id, section_path, offsets, text}`
* **Acceptance**:

    * Span IDs deterministic for same doc
    * Offsets allow quoting exact evidence

### T1.3 Anchor/quote utility

* **Scope**: E2
* **Deps**: T1.2
* **Outputs**: function to produce evidence snippet from offsets
* **Acceptance**:

    * RU/edge can reference an anchor and render a human-readable quote

---

## EP2 — IE integration + planning-grade extraction loop

### T2.1 IE Adapter contract + stub implementation

* **Scope**: E3
* **Deps**: T1.2, T0.1
* **Outputs**: adapter interface returning candidate statements + occurrence anchors
* **Acceptance**:

    * Given spans, adapter returns `{statement_id, text, occurrences[]}`

### T2.2 Basic extraction orchestrator (single-pass)

* **Scope**: E4
* **Deps**: T2.1
* **Outputs**: extraction run that calls IE over spans and collects candidates
* **Acceptance**:

    * Produces a candidate statement set with anchors persisted in Graph Store

### T2.3 Candidate dedup (conservative)

* **Scope**: E4
* **Deps**: T2.2
* **Outputs**: dedup map that merges only “equivalent” candidates, preserving all anchors
* **Acceptance**:

    * No anchor loss when merging
    * Merges are explainable (similarity + confirmation step)

---

## EP3 — RU synthesis (semantic requirements, not keyword-based)

### T3.1 RU definition + RU creation from candidates

* **Scope**: E5
* **Deps**: T2.2, T0.1
* **Outputs**: RU objects with anchors + tags
* **Acceptance**:

    * RU includes: canonical text, entity refs (optional), modality unknown allowed, acceptance placeholder allowed

### T3.2 Atomicity splitter (multi-obligation → multiple RUs)

* **Scope**: E5
* **Deps**: T3.1
* **Outputs**: RU splitting pass with trace to original anchors
* **Acceptance**:

    * Splits preserve meaning and keep anchors

### T3.3 “Correctness necessity” classifier

* **Scope**: E5
* **Deps**: T3.1
* **Outputs**: RU tagging:

    * `correctness_condition` vs `context/rationale` vs `candidate_requirement`
* **Acceptance**:

    * Works without normative keywords (uses semantic cues + dependency tests)

### T3.4 Verifiability hooks (acceptance criteria scaffold)

* **Scope**: E5
* **Deps**: T3.1
* **Outputs**: RU field:

    * `acceptance`: test idea or “cannot be verified yet” with reason
* **Acceptance**:

    * RUs missing verifiability are flagged, not discarded

---

## EP4 — Entity discovery + RU attachment

### T4.1 Entity proposal from text + candidates

* **Scope**: E6
* **Deps**: T2.2, T1.2
* **Outputs**: initial entity list with aliases and evidence
* **Acceptance**:

    * Entities extracted from noun phrases / repeated referents / structural headings

### T4.2 RU → Entity attachment (many-to-many)

* **Scope**: E6
* **Deps**: T3.1, T4.1
* **Outputs**: RU attached to entities with confidence + evidence
* **Acceptance**:

    * Unattached RUs allowed but tracked

### T4.3 Entity merge/split operations (conservative)

* **Scope**: E6
* **Deps**: T4.1
* **Outputs**: ability to merge aliases; ability to split overloaded entities
* **Acceptance**:

    * Merge preserves all evidence and does not erase alternative interpretations

---

## EP5 — Dependency graph builder (RDG) + validation

### T5.1 Dependency edge schema + justification model

* **Scope**: E7
* **Deps**: T0.1
* **Outputs**: edge types + justification classes stored in schema
* **Acceptance**:

    * Every `requires` edge stores: type, justification class, evidence anchors

### T5.2 Hard dependency inference (RU-level)

* **Scope**: E7
* **Deps**: T3.1, T3.4, T4.2, T5.1
* **Outputs**: RDG edges inferred from:

    * implied prerequisites
    * verifiability dependencies
    * conditional/ordering relations surfaced by IE
* **Acceptance**:

    * Each inferred edge includes a justification class and evidence

### T5.3 Cycle detection + cycle report

* **Scope**: E7
* **Deps**: T5.2
* **Outputs**: cycle detection, minimal cycle sets, remediation hints
* **Acceptance**:

    * Cycles do not crash roadmap; they produce a report and mark affected nodes

### T5.4 Entity-level dependency projection (lift)

* **Scope**: E7
* **Deps**: T5.2, T4.2
* **Outputs**: entity dependency graph derived from RU edges
* **Acceptance**:

    * Entity dependency edge is backed by RU evidence counts and top exemplars

---

## EP6 — Standalone maximization (decoupling)

### T6.1 Standalone vs dependent classification

* **Scope**: E8
* **Deps**: T5.2
* **Outputs**: partition:

    * standalone RUs/entities vs dependent RUs/entities
* **Acceptance**:

    * Configurable rule: allow definitions/invariants as “non-blocking” prereqs if desired

### T6.2 Incidental coupling reducer

* **Scope**: E8
* **Deps**: T6.1, T3.2
* **Outputs**: rewrite suggestions (not silent edits) to:

    * lift cross-cutting constraints to invariants
    * split behavior from validation RUs when permissible
* **Acceptance**:

    * Produces a diff proposal; does not overwrite canonical RU text without recording

---

## EP7 — Ticketization + roadmap (ticket-first output)

### T7.1 Ticket schema + “context pack” format

* **Scope**: E9, E11
* **Deps**: T0.1, T0.2
* **Outputs**: ticket object schema and exported bundle format
* **Acceptance**:

    * Context pack includes: ticket RUs, prereqs, dependents, entity summaries, evidence anchors

### T7.2 Ticketizer v1 (small-ticket bias)

* **Scope**: E9
* **Deps**: T5.2, T6.1, T7.1
* **Outputs**: ticket backlog where each ticket:

    * increases correctness coverage
    * has explicit prerequisites (ticket deps derived from RU deps)
* **Acceptance**:

    * Default groups are small (configurable max RU count / max prerequisite fan-in)

### T7.3 Roadmap phases from RDG (topological layering)

* **Scope**: E9
* **Deps**: T7.2, T5.2
* **Outputs**: phases + parallel sets + critical path approximation
* **Acceptance**:

    * Produces ordered phases even with cycles (cycles become “needs resolution” phase blockers)

### T7.4 Ticket ordering + parallelization annotation

* **Scope**: E9
* **Deps**: T7.3
* **Outputs**: per-ticket:

    * suggested order index
    * “can run in parallel with” set (same phase, no mutual deps)
* **Acceptance**:

    * Ordering is reproducible and explainable (derived from prerequisites and phase)

---

## EP8 — Audit + confidence (planning-grade and coverage-grade)

### T8.1 Confidence model (RU + edge)

* **Scope**: E10
* **Deps**: T3.1, T5.2
* **Outputs**:

    * `ru_confidence`, `edge_confidence` and reasons (signals used)
* **Acceptance**:

    * Confidence is not a single number; includes reasons like “few anchors”, “ambiguous entity”, “weak prereq evidence”

### T8.2 Planning-grade audit report

* **Scope**: E10
* **Deps**: T2.2, T3.3, T5.2, T7.2
* **Outputs**:

    * summary of extracted RUs, entity coverage, top ambiguities, cycle report
* **Acceptance**:

    * Clearly lists “unknowns” and “assumptions”

### T8.3 Coverage-grade mode: iterative span fragmentation + gap surfacing

* **Scope**: E4, E10
* **Deps**: T2.2, T1.2
* **Outputs**:

    * iterative loop that marks covered spans, reprocesses uncovered, emits “gap spans”
* **Acceptance**:

    * No silent omission: every span ends as covered-by (RU/NOTE) or gap

### T8.4 Coverage-grade mode: reconstruction check

* **Scope**: E10
* **Deps**: T8.3, T3.1
* **Outputs**:

    * reconstruction attempt per span; leftover meaning becomes gap spans
* **Acceptance**:

    * Produces actionable “gap items” tied to exact offsets

---

## EP9 — Export + CLI (MVP usability)

### T9.1 JSON exporter (graph + tickets)

* **Scope**: E11
* **Deps**: T0.2, T7.2
* **Outputs**: `graph.json`, `tickets.json`, `audit.json`
* **Acceptance**:

    * Schema-valid outputs; stable ordering for diffs

### T9.2 Markdown exporter (human readable, ticket-first)

* **Scope**: E11
* **Deps**: T7.2, T7.3
* **Outputs**: `ROADMAP.md`, `TICKETS.md` with dependencies and evidence snippets
* **Acceptance**:

    * Each ticket lists deps, RUs, and minimal evidence

### T9.3 Mermaid/DOT exporter (RDG + entity graph)

* **Scope**: E11
* **Deps**: T5.2, T5.4
* **Outputs**: `rdg.mmd`, `entity_graph.mmd` (or DOT)
* **Acceptance**:

    * Graph renders without manual fixes for typical docs

### T9.4 CLI v1

* **Scope**: E12
* **Deps**: T9.1, T9.2
* **Outputs**:

    * `decompose <doc> --mode planning|coverage --out <dir>`
* **Acceptance**:

    * One command produces graph + tickets + roadmap + audit

---

## EP10 — Graph-first authoring loop (optional, but aligns with your “start extracted” end state)

### T10.1 Graph diff/import: apply updates from arbitrary docs as proposals

* **Scope**: E0, E4, E10
* **Deps**: T9.4, T0.3
* **Outputs**:

    * run produces a proposed diff against existing graph (add/modify/remove RU/edge/entity)
* **Acceptance**:

    * Does not overwrite; emits diff + confidence + required review list

### T10.2 PRD generator view (render prose from graph)

* **Scope**: E11
* **Deps**: T0.2, T7.2
* **Outputs**:

    * generated PRD view that links each paragraph back to graph nodes
* **Acceptance**:

    * Round-trip friendly: edits to graph regenerate PRD, not vice versa

---

# First-pass ordering summary (phase plan)

Phase 0: T0.1 → T0.2 → T0.3
Phase 1: T1.1 → T1.2 → T1.3
Phase 2: T2.1 → T2.2 → T2.3
Phase 3: T3.1 → T3.2 → T3.3 → T3.4
Phase 4: T4.1 → T4.2 → T4.3
Phase 5: T5.1 → T5.2 → T5.3 → T5.4
Phase 6: T6.1 → T6.2
Phase 7: T7.1 → T7.2 → T7.3 → T7.4
Phase 8: T8.1 → T8.2 (then optional: T8.3 → T8.4)
Phase 9: T9.1 → T9.2 → T9.3 → T9.4
Phase 10 (optional loop): T10.1 → T10.2

---

# Confidence

**0.78 (medium-high)**

Reasoning behind the score:

* High confidence in the entity breakdown and core pipeline ordering (graph store → spans → IE → RUs → RDG → tickets).
* Medium confidence in where to place coverage-grade reconstruction (it can be earlier or later; dependencies are correct either way).
* Medium confidence in ticket granularity heuristics without seeing your exact planning workflow constraints (but the “small-ticket bias” design is consistent with your stated preference).
