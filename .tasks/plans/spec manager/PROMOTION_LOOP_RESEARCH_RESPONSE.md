## 1) PromotionLoop control flow

### Core idea

* **Unit of work:** a **Slice** (initially: one library/worktree; later: library × connected-component or library × vertical-slice).
* **Execution model:** a **per-slice iterative loop** that repeatedly runs tools (existing P1–P10 modules) until the slice satisfies termination criteria.
* **Artifacts between steps:** file-based **EvidenceBundle** (single “bundle.json” that points to step outputs).

### Entry state

**Input to PromotionLoop.run_slice():**

* `SliceRef` (library identifier + worktree paths)
* `RunContext` (run_id, mode, config, global stores/paths)
* optional: `SeedGapSet` (if scheduler selected this slice because of known gaps)

**How a slice is selected (scheduler-side):**

* Primary: `GapQueue` items grouped by `slice_id` (highest gap count + stagnation priority).
* Secondary: `BranchManager` slice discovery (libraries with unpromoted atoms, or newly changed files).
* Tie-breakers: recency of edits, number of failing gates last iteration, test failures traced to the slice.

**Worktree entry:**

* Use `WorktreeManager` to obtain a **grandchild worktree** for that library slice (dirty, isolated).
* Evidence artifacts live inside that grandchild (so all tool scans remain “local” without rewriting internals).

### One iteration (exact order + conditions)

State machine (single slice):

```
START_ITER
  ↓
COLLECT_BASELINE   (diff/hash + manifest)
  ↓
GAP_EXPLORATION    (P3 + GapQueue view)
  ↓
PLAN               (P8)
  ↓
IMPLEMENT           (P9)  ← emits patch + pin/edge proposals + evidence
  ↓
UNDER_SPEC_CHECK   (block-or-decide; may invoke ResearchCoordinator/InteractiveWorkflow)
  ↓
ANALYZE            (P1 + P2 + analyze_source cache)
  ↓
PROMOTE            (P4 + P5 + gates + RefinementEngine)
  ├─ if gates fail → DEMOTE → RESTART_ITER
  ↓
INTEGRATE (CI)     (merge to parent + push to clean sibling + run tests)
  ├─ if tests fail → DOWNWARD_FLOW → DEMOTE → RESTART_ITER
  ↓
VERIFY             (P6 + P7 + architectural gates)
  ├─ if verify fails → DEMOTE → RESTART_ITER
  ↓
DONE?              (termination checks)
  ├─ if done → SLICE_COMPLETE
  └─ else → NEXT_ITER
```

#### Retry vs advance rules

An iteration **retries (same slice, next iteration)** when:

* any compliance/architectural gate fails,
* tests fail in clean worktree,
* verification detects orphans/disconnects/quality violations,
* `GapQueue` stagnation triggers a “cannot progress” condition (treated as under-spec).

An iteration **advances to next slice** when:

* slice reaches `SLICE_COMPLETE` (see termination below), or
* slice enters `BLOCKED` (human constraints needed) — scheduler moves on, leaving slice blocked until constraints arrive.

### Handling multiple slices

**MVP (recommended first):**

* Run slices **sequentially** in priority order (GapQueue-first), no parallelism.

**Target:**

* Run slices **in parallel** across per-library grandchild worktrees:

  * one grandchild per library slice,
  * concurrency bounded by `max_parallel_slices`,
  * integration/clean-test step is serialized or uses isolated clean siblings per slice.

Parallel safety comes from:

* slice-local worktrees,
* slice-local evidence directories,
* merge to shared parent/clean only at controlled integration boundaries.

### Termination conditions

**Per-slice termination (slice is complete):**

* `GapReport.remaining == 0` for that slice (P3 view) **AND**
* all atoms in slice are promoted through:

  * `ComplianceGates` (algorithmic_gates) **AND**
  * `ArchitecturalGates` (architectural_quality) **AND**
* clean worktree tests pass for:

  * slice tests + workspace tests (configurable; at least slice tests per iteration, full suite periodically)
* no open demotion tickets for the slice
* refinement/coupling checks for slice pass (RefinementEngine thresholds)

**Global termination (run is complete):**

* all slices are `SLICE_COMPLETE` (or explicitly excluded) **AND**
* global P6 connectivity (cross-library) passes **AND**
* global P7 lineage completeness passes (no orphans) **AND**
* clean-root full test suite passes

### Relationship to `simpler.md` lifecycle

* **PromotionLoop is the execution engine for “Build”** (close gaps, implement, promote).
* It also covers the **inner QA loop** because integration runs tests and DownwardFlow demotes on failures.
* The other lifecycle phases become separate run modes using the same demotion mechanism:

  * **QA mode:** run evals/tests → DownwardFlow → DemotionTickets → PromotionLoop resumes on affected slices.
  * **Architecture mode:** run architectural assessments/proposals → DemotionTickets (target L2/L1) → PromotionLoop.
  * **Code Quality mode:** reviewer/refactor tools → DemotionTickets (target L3/L2) → PromotionLoop or direct refactor loop.

### Coexistence with current `pdd_orchestrator.py` during migration

* Keep `pdd_orchestrator.run()` intact.
* Add `PromotionLoopRunner` and a new entrypoint:

  * `pdd_orchestrator.run(mode="pipeline")` = existing behavior
  * `pdd_orchestrator.run(mode="loop")` = compatibility wrapper that:

    1. discovers slices,
    2. calls `PromotionLoopRunner.run_slices(...)`,
    3. optionally runs global verify (P6/P7) at end.
* Tests can keep calling `pdd_orchestrator.run()`; switch default mode later.

---

## 2) EvidenceBundle schema

### Goals

* Single run-scoped, per-slice artifact that **eliminates redundant scanning** by making step outputs reusable.
* **Graph-first:** pins + edges are canonical; bundle is the mechanism to propose/apply and to snapshot.
* Incremental adoption: bundle can initially **reference existing artifacts** produced by current modules.

### Physical layout (file I/O between steps)

Inside each slice grandchild worktree:

```
.pdd_runs/
  <run_id>/
    slices/
      <slice_id>/
        iter_000/
          bundle.json
          manifest.json
          diff.json
          gaps.json
          plan.json
          impl.patch.diff
          impl.result.json
          source_analysis.index.json
          promotion.report.json
          gates.report.json
          graph.snapshot.json
          pins.snapshot.json
          tests.slice.json
          tests.full.json   (optional periodic)
          verify.report.json
          blockers.json     (only if blocked)
          demotions.json
        iter_001/
          ...
```

`bundle.json` is the **index**; other files are step outputs. This keeps context small for LLM steps: pass paths, not huge inline content.

### EvidenceBundle (top-level)

Minimal but implementable dataclass-style schema:

```python
@dataclass
class EvidenceBundle:
    # identity
    run_id: str
    slice_id: str
    iteration: int
    created_at: str  # iso
    mode: Literal["interactive", "auto"]
    workspace_root: str
    slice_root: str  # grandchild worktree path

    # input set
    manifest: ManifestRef         # files included + hashes
    diff: DiffRef                 # since previous iteration / baseline
    provenance: ProvenanceBlock   # step tool versions, model ids, prompt hashes

    # analysis + facts
    source_index: SourceIndexRef  # per-file SourceAnalysis outputs (via analyze_source)
    facts: FactsRef               # normalized facts extracted from analyses + LLM claims

    # gaps + planning + implementation
    gaps: GapReportRef
    plan: PlanRef
    implementation: ImplementationRef
    under_spec: UnderSpecRef      # resolved decisions or blockers

    # graph artifacts (canonical)
    pins_snapshot: PinsSnapshotRef
    graph_snapshot: GraphSnapshotRef
    graph_deltas: list[GraphDeltaRef]  # pin proposals, edge proposals, merges

    # promotion + gates + quality
    promotion: PromotionReportRef
    gates: GatesReportRef
    refinement: RefinementRef     # coupling/cohesion results

    # integration + verification
    integration: IntegrationRef   # merges, rebases, clean sync
    tests: TestsRef
    verification: VerificationRef

    # demotions (feedback)
    demotions: DemotionsRef       # tickets emitted this iter + applied status
    status: Literal["IN_PROGRESS", "BLOCKED", "COMPLETE", "FAILED"]
```

### Key referenced sub-objects

**ManifestRef**

* `files: [{path, sha256, size, language_hint}]`
* `slice_patterns` (how slice was selected)
* `generated_files` (tests, analysis docs)

**DiffRef**

* `base_commit`, `head_commit` (if using git inside worktrees)
* `changed_files`
* `patch_path` (optional)
* `content_hash` (used for caching)

**SourceIndexRef**

* `entries: [{path, analysis_path, content_hash}]`
* analysis_path contains serialized `SourceAnalysis` from `analyze_source()`

**FactsRef**

* normalized facts used by planning/gates:

  * `functions: {fqn: {signature, doc, file, lines}}`
  * `stores: {store_id: {owner_atoms, schema}}`
  * `atoms: {atom_id: {file, boundaries, responsibilities}}`
  * `constraints_refs: [paths]`
  * `llm_claims: [{claim, evidence_refs, confidence, produced_by_step}]`

**GapReportRef**

* `open_gaps: [GapEvidenceRef]` (compatible with `GapQueue`)
* `by_file`, `by_atom`, `by_pin`
* `stagnation: {is_stagnating, signature, count}`

**PlanRef**

* `intentions: [{gap_id, target_file, approach, acceptance_criteria}]`
* `edit_targets: [{path, spans, operations}]`
* `test_plan: [...]`
* `risk/ambiguity: [...]` (can pre-trigger under-spec)

**ImplementationRef**

* `patch_path`
* `result.json` includes:

  * `applied_edits: [...]`
  * `pin_proposals: [...]`
  * `edge_proposals: [...]`
  * `evidence: [...]` (provenance/justifications)
  * `under_spec_events: [...]` (hard blockers)
  * `tests_added: [...]`

**PinsSnapshotRef / GraphSnapshotRef**

* point to serialized `PinRegistry` + `AdjacencyGraph`
* include `snapshot_hash` and `schema_version`

**GatesReportRef**

* per gate:

  * `gate_name`
  * `pass/fail`
  * `violations: [{pin_id, atom_id, evidence_refs, message}]`
  * `recommended_demotions: [DemotionTicketRef]` (or link)

**TestsRef**

* slice-level test run (fast)
* periodic full run (slow)
* failures structured for DownwardFlow

**VerificationRef**

* P6 connectivity summary
* P7 lineage/orphans summary
* architectural gate results

**DemotionsRef**

* list of tickets emitted this iteration
* list of tickets applied (with patch refs)
* list pending (blocked)

### Production of EvidenceBundle (incremental, no big-bang)

**MVP bundle creation:**

* Each tool step runs as-is (scanning the slice worktree).
* After each step, write that step’s output to the iteration directory.
* `bundle.json` is assembled as an index that points to:

  * the outputs you already have (GapQueue serialization, promotion reports, etc.)
  * plus new outputs (plan.json, impl.result.json)

**Next step (reduce redundant parsing):**

* Introduce a `SourceAnalysisCache` keyed by `(file_hash, analyzer_version)`.
* P1/P3/P4 can progressively switch from “scan files → analyze_source” to “read SourceIndexRef”.

**Graph consolidation without rewrite:**

* Keep `PinRegistry` and `AdjacencyGraph` as canonical objects.
* Add a thin `GraphApplier` that:

  * reads `pin_proposals`/`edge_proposals`,
  * merges into in-memory registry/graph,
  * writes snapshots.
* Existing modules can still compute edges/pins; you just treat their output as another `GraphDeltaRef`.

---

## 3) Loop step design (inputs/outputs/modules/pure signatures)

### Common step interface

```python
@dataclass
class StepResult:
    status: Literal["OK", "RETRY", "BLOCKED", "FAIL"]
    bundle_path: str
    emitted_tickets: list["DemotionTicket"] = field(default_factory=list)
    notes_path: str | None = None  # human-readable summary

class LoopStep(Protocol):
    def run(self, ctx: "SliceContext", bundle: EvidenceBundle) -> StepResult: ...
```

`SliceContext` includes:

* `slice_id`
* `slice_root` (grandchild worktree)
* `dirty_parent_root`
* `clean_sibling_root`
* references to managers: WorktreeManager, WorkspaceManager, BranchManager
* config

---

### Step: COLLECT_BASELINE (diff + manifest)

**Input**

* slice_root filesystem state

**Output**

* `manifest.json`, `diff.json` (or `git diff` snapshot)
* updated `bundle.manifest`, `bundle.diff`

**Module mapping**

* new: `orchestration/evidence/collector.py`
* uses WorkspaceManager for state bookkeeping

**Pure signature**

```python
def collect_baseline(slice_root: str, prev_bundle: EvidenceBundle | None) -> tuple[Manifest, Diff]:
    ...
```

---

### Step: GAP_EXPLORATION (P3 + GapQueue view)

**Input**

* `bundle.manifest`
* optionally `bundle.source_index` (later)

**Output**

* `gaps.json`
* updates slice-scoped view of `GapQueue` (global queue aggregates all slices)
* updates `bundle.gaps`

**Module mapping**

* P3: `compliance.detection.orchestrator` (run against slice_root)
* GapQueue: `core/gap_queue.py`

**Adapter requirement**

* Add a `root_path`/`file_subset` parameter to P3 orchestrator if not present; otherwise run it in slice worktree root.

**Pure signature**

```python
def explore_gaps(slice_root: str, source_index: SourceIndex | None) -> GapReport:
    ...
```

---

### Step: PLAN (P8)

**Input**

* `bundle.gaps`
* `bundle.facts` / `bundle.source_index`
* `bundle.graph_snapshot` (optional, helps choose integration points)

**Output**

* `plan.json`
* updates `bundle.plan`

**Module mapping**

* P8: `planning.workflow`
* plus a small adapter that blocks early if ambiguity is detected in plan formation.

**Pure signature**

```python
def plan_work(bundle: EvidenceBundle) -> Plan:
    ...
```

---

### Step: IMPLEMENT (P9, plus “emit pins/edges/evidence”)

**Input**

* `bundle.plan`
* `bundle.gaps`
* `bundle.constraints` (from under_spec decisions)
* file paths to edit (plan edit targets)

**Output**

* `impl.patch.diff` (applied to slice worktree)
* `impl.result.json` (structured, includes proposals)
* test files added/updated
* updates `bundle.implementation`
* produces `GraphDeltaRef` (pin/edge proposals)

**Module mapping**

* P9: `core.edit_in_place` (LLM-based)
* plus a structured output schema.

**LLM output contract (must be enforced)**

```json
{
  "applied_patch": {"unified_diff_path": "impl.patch.diff"},
  "pin_proposals": [
    {"pin_id": "...", "fqn": "...", "file": "...", "role": "pin", "atom_id_hint": "...", "evidence": [...]}
  ],
  "edge_proposals": [
    {"src": "...", "dst": "...", "signal_type": "...", "weight": 0.7, "evidence": [...]}
  ],
  "tests_added": [{"path": "...", "purpose": "..."}],
  "under_spec_events": [
    {"kind": "MISSING_CONSTRAINT", "question": "...", "options": [...], "needed_for": "..."}
  ],
  "notes_path": "impl.notes.md"
}
```

**Pure signature**

```python
def implement(plan: Plan, bundle: EvidenceBundle) -> ImplementationResult:
    ...
```

---

### Step: UNDER_SPEC_CHECK (hard stop or decide)

**Input**

* `bundle.implementation.under_spec_events`
* existing constraints files (e.g., `analysis/constraints/<slice_id>.md` or `constraints.yaml`)
* `InteractiveWorkflow` / `ResearchCoordinator` depending on mode

**Output**

* If resolvable:

  * `decisions.json` + optional patch to constraints docs
  * updates `bundle.under_spec` with decisions
* If not resolvable:

  * `blockers.json` + `constraint_request.md`
  * sets `bundle.status = BLOCKED`
  * StepResult = `BLOCKED`

**Module mapping**

* `refinement/interactive/` for interactive
* `ResearchCoordinator` for auto research
* new: `under_spec/manager.py` to implement the policy “constraints must cover; no guessing”

**Pure signature**

```python
def resolve_under_spec(events: list[UnderSpecEvent], constraints: ConstraintsStore, mode: Mode) -> UnderSpecOutcome:
    ...
```

---

### Step: ANALYZE (P1 + P2, backed by analyze_source)

**Input**

* slice_root (post-implementation)
* `bundle.diff` (to limit work)
* `analyze_source` cache

**Output**

* `source_analysis.index.json`
* optional `reverse_pseudocode.json`
* updates `bundle.source_index`, `bundle.facts`

**Module mapping**

* P1: `planning.models.parse_file` (+ adapters to read SourceAnalysis)
* P2: `planning.reverser`
* `core/code_analysis.analyze_source` (the only analyzer)

**Pure signature**

```python
def analyze_slice(slice_root: str, manifest: Manifest, cache: SourceAnalysisCache) -> tuple[SourceIndex, Facts]:
    ...
```

---

### Step: PROMOTE (P4 + P5 + gates + refinement)

**Input**

* `bundle.source_index` / `bundle.facts`
* graph/pin snapshots from previous iteration
* `bundle.implementation.pin_proposals` + `edge_proposals`

**Output**

* updated `pins.snapshot.json`, `graph.snapshot.json`
* `promotion.report.json`, `gates.report.json`, `refinement.json`
* if failures: emits `DemotionTicket`s

**Module mapping**

* P4: `branches.manager.collapse_codebase` (run on slice worktree)
* P5: `pin_functions.orchestrator` + `branches.promote`
* Gates:

  * `compliance/promotion/algorithmic_gates.py`
  * `compliance/promotion/architectural_quality.py`
* Refinement:

  * `refinement_engine/detector.py`

**Adapter requirements (incremental)**

* Add optional inputs to P5:

  * `pin_proposals_path`
  * `edge_proposals_path`
  * mode: `"scan"|"proposals"|"both"` (default `"both"` initially)
* Gates should accept `graph_snapshot` and `pins_snapshot` to avoid rescanning later; initially they can keep scanning.

**Pure signature**

```python
def promote(bundle: EvidenceBundle, branch_manager: BranchManager) -> PromotionOutcome:
    ...
```

---

### Step: INTEGRATE (CI on clean worktree)

**Input**

* dirty grandchild slice worktree (implemented + promoted)
* WorktreeManager hierarchy
* bundle promotion outcome

**Output**

* merge grandchild → dirty parent
* extract slice → clean sibling
* run tests in clean sibling
* `tests.slice.json` (and optional `tests.full.json`)
* if failures: structured failure report for DownwardFlow

**Module mapping**

* WorktreeManager: `orchestration/worktree_manager.py`
* test runner (existing)
* DownwardFlowEngine (on failure)

**Pure signature**

```python
def integrate_and_test(ctx: SliceContext, bundle: EvidenceBundle) -> IntegrationOutcome:
    ...
```

---

### Step: VERIFY (P6 + P7 + architectural gates)

**Input**

* clean sibling (preferred) or dirty parent (depending on policy)
* graphs/pins updated after integration

**Output**

* `verify.report.json`
* may emit DemotionTickets on:

  * disconnected cross-library graph,
  * lineage orphans,
  * architectural quality failures

**Module mapping**

* P6: `analysis.adjacency.runner` (cross-library pass)
* P7: `projection.lineage` + generators
* Architectural gates: `architectural_quality.py`

**Pure signature**

```python
def verify(clean_root: str, bundle: EvidenceBundle) -> VerificationOutcome:
    ...
```

---

## 4) Demotion chain (gate/test/verify failure → ticket → L1 patch → GapQueue → re-loop)

### DemotionTicket schema (concrete)

```python
@dataclass
class DemotionTicket:
    ticket_id: str
    created_at: str
    run_id: str
    slice_id: str

    source: Literal["ALGORITHMIC_GATE", "ARCH_GATE", "TEST_FAILURE", "LINEAGE", "REVIEW"]
    gate: str | None                 # which gate failed, if applicable

    target_layer: Literal["L1", "L2", "L3"]
    severity: Literal["BLOCKER", "MAJOR", "MINOR"]

    failing_pins: list[str] = field(default_factory=list)
    failing_atoms: list[str] = field(default_factory=list)
    failing_files: list[str] = field(default_factory=list)

    diagnosis: str = ""              # human-readable root cause
    evidence_refs: list[str] = field(default_factory=list)  # paths into bundle artifacts

    # what to do
    recommended_spec_patch: str | None = None  # unified diff (L1 code-as-spec patch)
    recommended_code_patch: str | None = None  # unified diff (L3 refactor patch)
    questions: list[str] = field(default_factory=list)      # for under-spec

    # routing hook
    routing_required: bool = False
    routing_payload: dict | None = None  # {text, source_path, tags, desired_slice_hint}

    # bookkeeping
    apply_status: Literal["PENDING", "APPLIED", "REJECTED", "BLOCKED"] = "PENDING"
    applied_patch_paths: list[str] = field(default_factory=list)
```

### Who creates tickets

* **Algorithmic/Architectural gate runner** (inside PROMOTE) produces tickets from gate violations.
* **DownwardFlowEngine** (inside INTEGRATE on test failure) produces tickets by tracing:
  failing tests → call sites → pins → atoms → files.
* **Lineage/verify** produces tickets for orphans/disconnects.
* **Human review / code quality** can author tickets manually (or via reviewer tool).

### DemotionManager.apply(ticket): what it does

Core behavior (file-based; no silent skipping):

1. **Decide where to patch**

* If `recommended_spec_patch` present → apply to L1 code-as-spec files in slice worktree.
* Else if `recommended_code_patch` present and `target_layer == L3` → apply directly.
* Else → generate a minimal L1 patch that creates a concrete gap:

  * insert a spec comment stub tied to `pin_id` / `atom_id`
  * or annotate the failing region with a “SPEC REQUIRED” block

2. **Update registries**

* Mark affected atoms/pins as **demoted** in BranchManager / promotion metadata:

  * e.g. `branch_manager.demote_atom(atom_id, to_layer="L1")`
* Optionally mark pins “dirty” / “needs re-verification” in PinRegistry.

3. **Feed GapQueue**

* Create `GapEvidence` entries that correspond to the demotion patch.
* This guarantees the next GAP_EXPLORATION sees actionable items even if P3 scan misses semantic issues.

4. **Routing hook**

* If `ticket.routing_required`:

  * create a `RoutingItem` from `routing_payload`
  * invoke partial Phase 0 on that item (see §5)
  * resulting routed patch becomes part of the demotion application.

5. **Record lineage**

* Write `demotions.json` in iteration dir with:

  * ticket + applied patch refs
  * link back to the gate/test evidence in the bundle

### How demotion interacts with the loop

* Any ticket with `severity=BLOCKER` forces:

  * current iteration → `RETRY` starting at GAP_EXPLORATION (new gaps now exist).
* Tickets that require constraints (`questions` non-empty, no constraint coverage) can force:

  * `BLOCKED` if unresolved (under-spec policy).

### L3 → L2 → L1 chain

Use `target_layer` and policy routing:

* **Code quality issue (L3)**:

  * default: ticket targets `L3` with code patch (refactor) if purely local.
  * if it reveals architectural mismatch (e.g., inlined atom logic violates gate): demote to `L2`:

    * create ticket requiring extraction into atom/pin structure.
  * if architecture itself is underspecified (responsibility unclear): demote further to `L1`:

    * add/expand spec comments + constraints.

* **Architecture issue (L2)**:

  * if pins/edges wrong or missing: patch L2 artifacts (pins/edges) and/or demote to L1 if spec must change.

* **Spec insufficiency (L1)**:

  * under-spec events; must block until constraints exist.

### Where DownwardFlowEngine fits

* It runs only on **clean-worktree failures** (tests or quality checks).
* It outputs **DemotionTickets** (not logs).
* Those tickets are applied in the dirty slice worktree and fed to GapQueue, then the slice re-loops.

This replaces “skipped_atoms” with “demote-and-loop”.

---

## 5) Conditional Phase 0 and partial intake routing

### When Phase 0 is needed

Phase 0 is invoked only when there is **new L0 content** that must be routed into L1, or when a demotion declares that a missing requirement must be added.

Concrete detection policy (incremental, no fragile heuristics required):

* Maintain an **IntakeQueue** directory (or manifest) in workspace:

  * e.g. `.pdd_intake_queue/`
* Phase 0 runs if and only if either:

  1. the queue is non-empty, or
  2. a DemotionTicket has `routing_required=True`.

This avoids guessing based on file extensions.

### Partial Phase 0 (route one requirement, not everything)

Add a narrow API around your existing intake pipeline:

```python
@dataclass
class RoutingItem:
    item_id: str
    text: str
    source_path: str | None
    desired_slice_hint: str | None
    tags: list[str]

def route_items(items: list[RoutingItem], workspace_root: str) -> list[RoutedPatch]:
    ...
```

* Output: `RoutedPatch {target_slice_id, unified_diff_path, notes_path}`
* PromotionLoop applies that patch in the appropriate slice worktree and immediately re-enters GAP_EXPLORATION.

### Does PromotionLoop invoke Phase 0 mid-loop?

Yes, but **only through DemotionTickets**:

* If a gate/test failure indicates “requirement missing entirely”, ticket sets `routing_required=True`.
* DemotionManager triggers `route_items([payload])`.
* The routed patch becomes an L1 spec insertion, then the normal loop continues.

No global reroute.

---

## 6) Migration strategy (incremental, preserves current orchestrator + tests)

### Step 0 — Add PromotionLoop without refactoring modules

**Add:** `orchestration/promotion_loop.py`

* Implement per-slice loop that:

  * runs P3 → P8 → P9 → P1/P2 → P4/P5 → tests
  * within a slice grandchild worktree so “global scans” become slice-local by construction
* Implement minimal EvidenceBundle as index file pointing to step outputs.

**No changes required** in P1–P10 internals yet, except possibly adding a `root_path` parameter if any phase is hardcoded to workspace root.

### Step 1 — Compatibility wrapper

Modify `pdd_orchestrator.py` minimally:

* keep existing `run()` default behavior
* add `run(mode="loop")` that calls PromotionLoop over discovered slices

Existing tests remain green.

### Step 2 — Introduce EvidenceBundle formally (still references old artifacts)

* Make each step write outputs to `.pdd_runs/<run_id>/...`
* Bundle becomes the single “handoff” object between steps.

### Step 3 — Demotion chain MVP

* Implement `DemotionTicket`, `DemotionManager.apply()`
* Wire in:

  * gate failure → ticket → apply → GapQueue update → retry
  * test failure → DownwardFlowEngine → tickets → apply → retry

### Step 4 — Under-spec blocking

* Enforce: any under-spec event blocks promotion.
* Integrate InteractiveWorkflow + ResearchCoordinator.

### Step 5 — Adapt P5 to accept pin/edge proposals

* Add “both” mode: keep scanning pins, but also apply proposals from impl output.
* Start shifting “pin+edge creation” into P9 outputs.

### Step 6 — Caching + reduced rescans

* Introduce `SourceAnalysisCache` and make P1/P3/P4 optionally consume SourceIndexRef instead of re-calling analyze_source via deep rescans.

### Step 7 — Parallelism

* Add `PromotionScheduler` with bounded concurrency.
* Serialize integration if needed, or allocate clean siblings per slice.

### Step 8 — Retire sequential pipeline

* Once loop mode becomes default and stable:

  * delete or freeze old P0–P10 sequential runner
  * keep only tool modules invoked by loop steps

### Testing migration

* Add new tests:

  * `test_promotion_loop_single_slice_closes_gaps()`
  * `test_gate_failure_produces_demotion_ticket_and_retries()`
  * `test_under_spec_blocks()`
  * `test_downward_flow_creates_tickets()`
* Keep existing orchestrator tests until loop mode is default; then flip tests to loop mode gradually.

### Minimum viable PromotionLoop (explicit)

MVP scope that still provides value:

* single slice at a time
* no parallelism
* no demotion (initially)
* loop: P3 → P8 → P9 → P1 → P4 → P5 → run slice tests → repeat until no gaps

Then add demotion immediately after.

---

## 7) Under-specification blocking (hard stop, no guessing)

### How the implementation agent signals “I can’t resolve this”

Via structured `under_spec_events` in `impl.result.json` (see IMPLEMENT schema). Examples:

* missing constraints (API choice, persistence semantics, error handling policy)
* conflicting constraints (two specs disagree)
* external dependency unknown (protocol, schema)

### What “waiting for constraints” looks like

* Loop step UNDER_SPEC_CHECK writes:

  * `blockers.json`
  * `constraint_request.md` (human-readable)
* Bundle status set to `BLOCKED`
* SliceContext recorded in WorkspaceManager:

  * `status=BLOCKED`
  * `blocked_on=[questions]`
  * `resume_hint` (paths to artifacts)

Scheduler moves on to other slices.

### Interactive mode flow

1. Generate `constraint_request.md` containing:

   * questions
   * options
   * references into bundle evidence (file paths, pins, gates)
   * required decision format (YAML/JSON)
2. `InteractiveWorkflow` presents it and collects constraints.
3. Constraints are written to:

   * `analysis/constraints/<slice_id>.md` or `constraints.yaml`
4. Loop resumes: planner re-runs with constraints, then implement.

### Auto mode flow (ResearchCoordinator)

Policy: research may **propose** constraints, but promotion only proceeds if constraints become explicit artifacts.

1. ResearchCoordinator runs with:

   * blockers + context paths
   * allowed sources configuration
2. Produces:

   * `research_report.md`
   * `proposed_constraints.yaml` (must be explicit)
3. Constraint validator checks:

   * constraints are concrete, testable, non-contradictory
4. If valid:

   * apply patch to constraints store
   * mark under_spec resolved
   * resume loop
5. If not valid:

   * remain `BLOCKED` (needs human constraints)

### How constraints flow back into the loop

* They become file artifacts referenced by `bundle.facts.constraints_refs`
* Planning and implementation steps load them deterministically.
* Decisions are also recorded in bundle provenance (who/what produced them).

---

## Summary of module mapping (P1–P10 as tools)

* **P0**: invoked only from IntakeQueue or DemotionTicket routing hook.
* **P1/P2**: ANALYZE step (after implementation).
* **P3**: GAP_EXPLORATION step (every iteration start).
* **P4/P5**: PROMOTE step (after analyze).
* **P6/P7**: VERIFY step (preferably on clean worktree; can be periodic).
* **P8**: PLAN step (after gaps).
* **P9**: IMPLEMENT step (writes code + tests + pin/edge proposals).
* **P10**: used inside PROMOTE (refinement) and periodically as “assessment”.

This design hits the required fixes:

* per-slice iterative loop (not phase pipeline),
* shared EvidenceBundle artifact,
* concrete demotion chain (skip → demote → patch → GapQueue → loop),
* conditional Phase 0,
* hard under-spec blocking,
* incremental migration via worktree scoping first, then evidence/adapters, then parallelism.
