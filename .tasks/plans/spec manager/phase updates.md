## Phase 1 — Add a design-alignment harness (no behavior changes)

**Design references**

* `.tasks\plans\spec manager\design\overview\00_SYSTEM_OVERVIEW.md`
* `.tasks\plans\spec manager\design\constraints\00_GLOBAL_CONSTRAINTS.md`
* `.tasks\plans\spec manager\design\analysis\06_NO_REGEX_COMPLIANCE_REVIEW.md`
* `.tasks\plans\spec manager\design\clean\05_COMPLIANCE_AND_VALIDATION.md`

**Goal**
Create an enforceable “definition of aligned” inside the repo (schemas, invariants, lints, and fixtures), without changing runtime behavior yet.

**Work items**

1. **Create a “design compliance” test suite**

   * Add tests that assert the *current* artifacts (as-is) still pass existing tests, while the new compliance suite is allowed to fail (marked `xfail`) until later phases.
   * Add invariant tests for:

     * Contract validation surfaces errors but does not overwrite authority artifacts (CON-0011).
     * Coverage accounting exists as a first-class metric (INV-ACC-0101 / CON-0002), even if not yet in the new ID format.
2. **Import/centralize the design schemas**

   * Vendor the JSON schemas in `.tasks\plans\spec manager\design\templates\*.schema.json` into a runtime-accessible location (or load them directly from that path).
   * Add a schema registry that can validate any artifact type and record a `ContractValidationResult` (DS-COMP-0001).
3. **Add “no-hardcoding policy” scanning as a *report-only* lint**

   * Static scan for obvious violations (hardcoded keyword lists, regexes that target uncontrolled text, “banned library names” tables).
   * Output findings as a non-blocking report in this phase (do not change runtime yet).

**Deliverables**

* `design_compliance/` module (schema registry + invariant checks + report writer)
* A CI job that runs:

  * existing tests (must pass)
  * design compliance tests (can be `xfail` or “warn-only” until Phase 5)

**Exit criteria**

* Current system passes unchanged.
* A machine-readable compliance report is produced for each run/CI execution.

---

## Phase 2 — Rebase L0 on the design ID registry (file_uids + revisions + atom fingerprints)

**Design references**

* `.tasks\plans\spec manager\design\clean\00_ID_REGISTRY.md`
* `.tasks\plans\spec manager\design\clean\01_EVIDENCE_LAYER.md`
* `.tasks\plans\spec manager\design\constraints\00_GLOBAL_CONSTRAINTS.md` (CON-0001, CON-0008)

**Goal**
Introduce the design’s stable identifiers and revision model while keeping the existing pipeline runnable via compatibility adapters.

**Work items**

1. **Introduce a persistent File UID registry**

   * Implement `AllocateFileUid` and store a registry keyed by canonical path (ALG-CORE-0001).
   * Stop deriving F#### purely from “sorted paths each run”. Keep F#### formatting, but make it persistent and stable.
2. **Add file revision IDs (R####)**

   * Implement `AllocateRevisionId` per file_uid keyed by file content hash (ALG-CORE-0002).
   * Emit a revision entry whenever file content changes; do not mutate old revisions (CON-0001).
3. **Update atom emission to design shape**

   * Atom IDs become: `ATOM-{file_uid}-{rev_id}-L{line:04d}`
   * Add `atom_fingerprint` using `BuildAtomFingerprint` (ALG-CORE-0004) so later phases can remap across revisions.
4. **Compatibility layer**

   * Continue to support reading old IDs (e.g., `ATOM-F0001-L0001`) by:

     * parsing legacy formats
     * mapping legacy → new with default `rev_id=R0001` for old workspaces
   * Keep old fields temporarily in JSON outputs if necessary (deprecated, read-only).

**Deliverables**

* Persistent registry file (location documented; e.g., workspace root or `runs/_registry/`)
* Updated manifests and atoms output with file_uid + rev_id
* Updated unit tests for atom emission / file manifests (pattern changes)

**Exit criteria**

* A run produces stable `F####` across runs and emits `R####`.
* Atoms include `atom_fingerprint`.
* All existing workflows still execute using adapters.

---

## Phase 3 — Add evidence ranges (EVID-*) and an evidence graph with 100% accounting gates

**Design references**

* `.tasks\plans\spec manager\design\clean\01_EVIDENCE_LAYER.md`
* `.tasks\plans\spec manager\design\clean\02_PROVENANCE_AND_MEMBERSHIP.md`
* `.tasks\plans\spec manager\design\clean\13_STRUCTURE_AND_DECOMPOSITION.md`
* `.tasks\plans\spec manager\design\constraints\03_ACCURACY_INVARIANTS.md` (INV-ACC-0101)

**Goal**
Make “evidence ranges” (EVID-*) the canonical bridge between spans/units and atoms, and enforce full atom accounting as a hard gate.

**Work items**

1. **Emit EVID ranges for section spans**

   * For each section span, emit:

     * `EVID-{file_uid}-{rev_id}-L{start}-L{end}`
   * Ensure spans cover 100% of atoms; uncovered atoms become:

     * an “UNKNOWN span” + remainder + GAP(COVERAGE) (design Phase 1 fallback).
2. **Create an evidence graph artifact**

   * Nodes: atoms, evidence ranges, sections (and later units/elements)
   * Edges: atom→range, range→section
3. **Coverage reports become authoritative gates**

   * Implement the design’s “coverage validator” behavior:

     * Any non-100% coverage blocks promotion of authoritative artifacts, but still produces a valid fallback state (CON-0009).
4. **Update decomposition/units to attach atom_ids, not just line numbers**

   * Units reference `atom_ids` (with rev ids), ensuring preservation.

**Deliverables**

* `evidence_ranges.json` (or per-file) + `evidence_graph.json`
* Coverage report generated after Phase 1 and Phase 2 equivalents
* Tests:

  * “All atoms are in exactly one of {mapped, remainder, excluded}”
  * “Span coverage repair produces UNKNOWN spans deterministically”

**Exit criteria**

* Every run emits EVID ranges and an evidence graph.
* Coverage gates exist and can BLOCK/WARN_PASS/PASS, even if later phases still use old citations.

---

## Phase 4 — Migrate all citations/pointers to EVID-only and ban derived-artifact pointers in L1

**Design references**

* `.tasks\plans\spec manager\design\clean\05_COMPLIANCE_AND_VALIDATION.md` (CON-0021)
* `.tasks\plans\spec manager\design\constraints\02_AUTHORITY_MODEL.md`
* `.tasks\plans\spec manager\design\templates\provenance_stamp_format.md`

**Goal**
Make evidence references in all L1 artifacts use only EVID/ATOM IDs (not file paths, not run workspace paths), and enforce this via contract lint.

**Work items**

1. **Define canonical citation syntax for human-readable docs**

   * Standardize on bracketed EVID usage (example): `[EVID-F0001-R0001-L0001-L0012]`
   * Keep parsing/regex strictly limited to this system-owned format (CON-0004).
2. **Add a migration path from existing pointer formats**

   * Migrate:

     * `[F####::SECTION]`
     * `[spec_snapshot/<relpath>::SEC-…]`
   * To EVID by:

     * resolving the referenced section/span to its covering EVID range(s)
     * replacing pointers in charters/specs/task docs
3. **Update contract lint**

   * Evidence fields must contain only `EVID-*` (hard error).
   * Free-text scan warns on derived-artifact tokens like `runs/`, `views/`, `spec_snapshot/` (per CON-0021).
4. **Update all agent prompts and repairers**

   * Prompts must demonstrate EVID format examples and prohibit path-based citations.
   * Repair agents updated accordingly.

**Deliverables**

* Pointer migration tool: “section pointer → EVID range”
* Updated contract lint rules and tests
* Updated `.agents/agents/*` prompts where citations are produced

**Exit criteria**

* New runs produce L1 outputs that contain **no** `spec_snapshot/`-style pointers.
* Lints catch any regression immediately.

---

## Phase 5 — Remove hardcoded semantic heuristics (no-regex-on-uncontrolled-text compliance)

**Design references**

* `.tasks\plans\spec manager\design\constraints\01_NO_HARDCODE_POLICY.md`
* `.tasks\plans\spec manager\design\analysis\06_NO_REGEX_COMPLIANCE_REVIEW.md`
* `.tasks\plans\spec manager\design\clean\04_STRATEGY_ENGINE.md`
* `.tasks\plans\spec manager\design\clean\06_GAP_DETECTION.md`

**Goal**
Eliminate keyword/regex-based semantic inference on uncontrolled text and replace it with (a) LLM contract outputs or (b) purely structural metrics, with heuristics allowed only as explicitly non-authoritative fallbacks.

**Work items**

1. **Strategy gating must not scan raw text with hardcoded patterns**

   * Example fixes:

     * Replace vague-reference regex gating in entity resolution with:

       * always-run on scoped units, or
       * LLM-produced “unresolved reference count” signal
2. **Rewrite gap detectors that use keyword lists / banned names**

   * Convert to either:

     * structural detectors (graph-based, coverage-based), or
     * LLM detectors that output schema-validated `DetectorFinding` → `GapElement`
3. **Heuristic fallbacks become non-authoritative**

   * Any residual heuristics must:

     * emit a GapElement
     * set confidence < 0.5
     * never overwrite authority state without confirmation (per policy)
4. **Introduce fixtures for each detector/strategy**

   * Regression fixtures that assert:

     * no forbidden heuristic signatures
     * stable outputs on the fixture corpus

**Deliverables**

* Updated strategy engine signals + gating (risk from state, not raw text scanning)
* Reworked detectors/strategies with fixture coverage
* A “forbidden heuristic signatures” audit report that must be empty for Phase 5 completion

**Exit criteria**

* No hardcoded keyword lists/regexes are used to interpret uncontrolled spec text.
* Any remaining heuristics are quarantined/non-authoritative and produce explicit gaps.

---

## Phase 6 — Rebuild L1 around entity-tag graph discovery + derived elements grounded in atom_ids

**Design references**

* `.tasks\plans\spec manager\design\clean\07_LIBRARY_DISCOVERY.md`
* `.tasks\plans\spec manager\design\clean\08_LIBRARY_SPEC_BUILDING.md`
* `.tasks\plans\spec manager\design\clean\13_STRUCTURE_AND_DECOMPOSITION.md`
* `.tasks\plans\spec manager\design\constraints\00_GLOBAL_CONSTRAINTS.md` (CON-0005, CON-0019)

**Goal**
Align library discovery and spec building with the design’s data shapes: entities → co-occurrence graph → libraries → derived elements (REQ/FLOW/INV/DEC/ALG/DS) → spec_index with atom↔element maps.

**Work items**

1. **Introduce an explicit Entities artifact**

   * Either:

     * add an entity extraction agent step (ENT-*) during structure discovery, or
     * reformat existing “terms per section” output into entity/mention schemas.
2. **Library discovery via entity co-occurrence graph**

   * Build graph from entity tags, not keyword heuristics.
   * LLM proposes library candidates; system allocates stable `LIB-*` using stability keys (ALG-CORE-0006).
3. **Derived elements must cite atom/evidence IDs**

   * Update spec-building agents to output derived elements containing `evidence_atom_ids` (or evidence ranges expanded to atoms).
4. **Implement local_id → stable_id rewriting**

   * Agents emit `local_id` for new elements/relations; system resolves to stable IDs and rewrites endpoints (CON-0019).
5. **Build a design-compliant spec_index**

   * Include:

     * `atom_to_elements`
     * `element_to_atoms`
     * `relations`
   * Keep the old spec_index format temporarily as `spec_index_legacy.json` for compatibility.

**Deliverables**

* Entities artifact + tag index deltas (if used)
* Design-compliant `spec_index.json` (or `spec_index_v2.json` during transition)
* Updated interfaces/tasks workflows to consume the new index (behind a flag if needed)
* Tests:

  * every derived element has ≥1 evidence reference (CON-0005)
  * spec_index mappings are consistent and complete

**Exit criteria**

* L1 libraries and elements are grounded in atoms and indexed canonically.
* Downstream workflows can run using the new index (even if legacy is still emitted).

---

## Phase 7 — Make plan/tasks/architecture true L2 projections with pins + drift detection, then remove legacy subsystems

**Design references**

* `.tasks\plans\spec manager\design\clean\09_PROJECTION_AND_SYNC.md`
* `.tasks\plans\spec manager\design\templates\projection_pin_format.md`
* `.tasks\plans\spec manager\design\clean\03_TRANSFORM_AND_COMPOSITING.md` (atom alignment)
* `.tasks\plans\spec manager\design\clean\15_WORKFLOW_ORCHESTRATOR.md`
* `.tasks\plans\spec manager\design\clean\16_CLI_SCRIPTS.md`

**Goal**
Finish alignment by enforcing the authority model: L2 docs are regenerated projections pinned to L1 IDs, drift-checked, and never treated as source-of-truth. Consolidate duplicate orchestration and legacy gap APIs.

**Work items**

1. **Plan projection generation + pins**

   * Generate `plan.md` from libraries/elements.
   * Insert pins mapping offsets → IDs.
2. **Atom-aware drift comparator**

   * Compare projections using atom alignment/remap tables, not raw text heuristics.
   * Convert drift into GapElements (CON-0013).
3. **CLI + orchestrator convergence**

   * Align CLI surfaces to the design’s command set (validate/clean/discover/refine/project/plan-tasks/trace/run).
   * Deprecate/remove the legacy workflow path that parses uncontrolled text via deterministic regex.
4. **Remove legacy gap detection API**

   * Eliminate dict-based gap outputs; migrate all callers to unified GapElement flow.

**Deliverables**

* `plan.md` generation (projection) + pin parser/validator
* Drift report artifacts + drift→gap conversion
* Legacy orchestrator removal or isolation behind explicit “legacy” command
* Unified gap engine only
* Full end-to-end regression run on the fixture corpus

**Exit criteria**

* L2 documents are regenerated each run and drift is always detected.
* Only one orchestrator path remains for primary usage.
* Only one gap API remains (GapElement-based).
