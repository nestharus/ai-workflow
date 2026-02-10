## Gap 1: Wire `ImplementStep` to Real Implementation

### Target behavior

`ImplementStep.run()` becomes the per-slice adapter over the working legacy Phase 9 logic, but it must emit **everything** the loop expects:

* applied edits (as a patch + structured edit list)
* **pin proposals**
* **edge proposals**
* **under-spec events** (hard blockers)
* **tests added** (small tests)

This aligns with the PromotionLoop’s intended step outputs and EvidenceBundle contract.  

---

### Concrete design

#### 1) New internal helper: `ImplementationRunner`

**Module placement**

* `orchestration/implementation/runner.py` (new)
* imported by `orchestration/promotion_loop.py` `ImplementStep`

**Key types**

* `ImplementationRef` already exists in `orchestration/evidence.py` (or equivalent); extend only if fields missing.

```python
# orchestration/implementation/types.py (new or inside runner.py)
from dataclasses import dataclass, field
from typing import Literal, Any

@dataclass
class UnderSpecEvent:
    kind: Literal[
        "MISSING_CONSTRAINT",
        "CONFLICTING_CONSTRAINTS",
        "EXTERNAL_DEP_UNKNOWN",
        "NEEDS_PRODUCT_DECISION",
        "NEEDS_API_DECISION",
    ]
    question: str
    options: list[str] = field(default_factory=list)
    needed_for: str | None = None  # e.g., fqn or plan intention id
    evidence_paths: list[str] = field(default_factory=list)

@dataclass
class PinProposal:
    pin_id: str
    fqn: str
    file: str
    role: Literal["ATOM", "STORE", "SHAPE", "TEST", "ARCH"]
    span: dict[str, Any] | None = None  # {start_line, end_line, anchor_before, anchor_after}
    atom_id_hint: str | None = None
    evidence_paths: list[str] = field(default_factory=list)

@dataclass
class EdgeProposal:
    src: str
    dst: str
    signal_type: Literal["CALL", "STORE_TOUCH", "EVENT_EMIT", "EVENT_HANDLE", "IMPORT", "REFERENCE"]
    weight: float = 0.7
    evidence_paths: list[str] = field(default_factory=list)

@dataclass
class TestArtifact:
    path: str
    purpose: str
    scope: Literal["UNIT", "SLICE", "INTEGRATION"]
    runner_hint: str | None = None  # e.g. "pytest -q"
```

**Runner API**

```python
# orchestration/implementation/runner.py
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ImplementationRunResult:
    patch_path: str
    applied_edits: list[dict]              # minimal structured summary
    pin_proposals_path: str
    edge_proposals_path: str
    under_spec_events_path: str
    tests_added_path: str                 # json list of TestArtifact
    notes_path: str

class ImplementationRunner:
    def __init__(self, llm_client, analysis_cache, config):
        ...

    def run_for_slice(
        self,
        *,
        slice_root: Path,
        iteration_dir: Path,
        plan_path: Path,
        gaps_path: Path,
        constraints_paths: list[Path],
        max_functions: int,
    ) -> ImplementationRunResult:
        """
        - Analyzes slice_root for unresolved functions
        - Chooses targets from plan (preferred), falling back to gap report
        - Calls pdd-function-implementor per function
        - Applies edits + writes tests
        - Emits proposals + under-spec events as JSON files
        - Writes unified diff patch for the whole step
        """
```

#### 2) ImplementStep control flow (per slice)

**Module placement**

* `orchestration/promotion_loop.py` (modify `ImplementStep.run()`)

**Algorithm**

1. Load `bundle.plan` + `bundle.gaps`.
2. Load constraints paths (from `UnderSpecManager`/`ConstraintsStore`; see Gap 2).
3. Call `ImplementationRunner.run_for_slice(...)`.
4. Update `bundle.implementation` refs (paths).
5. Append a `GraphDeltaRef` in the bundle for the proposals (pin/edge).

This matches the loop’s intended “IMPLEMENT emits patch + proposals + under-spec + tests” contract. 

---

### Agent prompt changes: `pdd-function-implementor`

#### Required output schema (per function)

This replaces the legacy `{body, imports_needed, gaps, notes}` schema.

**Exact JSON schema (enforced)**

```json
{
  "function_target": {
    "file": "path/relative/to/slice_root.ext",
    "fqn": "package.module:SymbolName",
    "signature": "string as seen in file",
    "span_hint": { "start_line": 120, "end_line": 180 }
  },
  "edits": [
    {
      "path": "path/relative/to/slice_root.ext",
      "unified_diff": "diff --git ...\n--- ...\n+++ ...\n@@ ...\n"
    }
  ],
  "pin_proposals": [
    {
      "pin_id": "PIN-....",
      "role": "ATOM",
      "fqn": "package.module:SymbolName",
      "file": "path/relative/to/slice_root.ext",
      "span": {
        "start_line": 120,
        "end_line": 180,
        "anchor_before": "up to 120 chars",
        "anchor_after": "up to 120 chars"
      },
      "atom_id_hint": "ATOM-....",
      "evidence_paths": []
    }
  ],
  "edge_proposals": [
    {
      "src": "PIN-.... or fqn",
      "dst": "PIN-.... or store/event id",
      "signal_type": "CALL",
      "weight": 0.7,
      "evidence_paths": []
    }
  ],
  "tests": [
    {
      "path": "tests/test_symbolname.ext",
      "purpose": "Validates behavior described in spec comments for SymbolName",
      "scope": "UNIT",
      "runner_hint": null,
      "unified_diff": "diff --git ...\n--- ...\n+++ ...\n@@ ...\n"
    }
  ],
  "under_spec_events": [
    {
      "kind": "MISSING_CONSTRAINT",
      "question": "Which error policy applies when input is invalid?",
      "options": ["raise", "return sentinel", "log+skip"],
      "needed_for": "package.module:SymbolName",
      "evidence_paths": []
    }
  ],
  "notes_md": "Short markdown notes; no code fences required."
}
```

**Enforcement rules**

* If `under_spec_events` is non-empty:

  * edits/tests **may** be present for unrelated safe work, but MUST NOT implement the ambiguous decision.
  * ImplementationRunner stops scheduling further dependent functions.
* `edits[].unified_diff` is preferred over “body-only” because it’s language-agnostic.

This matches the “IMPLEMENT must emit patch + proposals + under-spec + tests” design already articulated for the loop.  

---

### Integration into PROMOTE (pins/edges)

**What happens**

* `ImplementStep` writes:

  * `pin_proposals.json`
  * `edge_proposals.json`

**PROMOTE step uses them**

* In `PromoteStep.run()`:

  * call `pin_functions.orchestrator.scan(mode="both", edge_proposals=..., pin_proposals=...)`
  * persist updated pin registry snapshot and adjacency graph snapshot into the bundle.

This is the intended “LLM proposes; orchestrator merges; gates consume graph.”   

If `pin_functions.orchestrator.scan()` currently only accepts `edge_proposals`, extend it to accept `pin_proposals` as well (no AST scanning; just merge + verify anchors).

---

### Granularity: file-by-file vs function-by-function

**Recommendation**

* **Function-by-function** is the correct core unit (because the legacy `_run_implementation()` already works this way, and under-spec blocking is naturally per function).
* However, the runner should group by file to reduce churn:

  * analyze once → implement all targeted functions in that file → write one patch per file (or multiple diffs, still OK).

So: *function unit of work; file unit of patch application.*

---

### Answers to Gap 1 questions

1. **How adapt legacy `_run_implementation()` per slice?**
   Wrap it as `ImplementationRunner.run_for_slice(slice_root=ctx.slice_root, ...)` and limit scope to:

   * files in `bundle.manifest` and/or
   * targets in `bundle.plan.edit_targets`
     Use `analyze_project()` on the slice root, not the whole repo.

2. **Implementor output schema?**
   Use the JSON schema above: `edits`, `pin_proposals`, `edge_proposals`, `tests`, `under_spec_events`.

3. **How feed pin/edge proposals into PROMOTE?**
   ImplementStep just writes proposal JSON and stores paths in `bundle.implementation`. PromoteStep passes them to `pin_functions.orchestrator.scan(mode="both", ...)`.

4. **Granularity?**
   Function-by-function scheduling, grouped by file for patching. This keeps diffs small and makes under-spec blocking precise.

---

### Test strategy (Gap 1)

Add tests that do not require real LLM calls:

1. `test_implement_step_emits_patch_and_proposals(tmp_workspace)`

   * fake LLM returns valid JSON with one edit + one pin proposal + one edge proposal.
   * assert:

     * `impl.patch.diff` exists
     * proposal json files exist
     * bundle.implementation fields reference them.

2. `test_implement_step_stops_on_under_spec_event()`

   * fake LLM returns under_spec_events for first function
   * assert no edits applied for that function, and UnderSpecCheck receives the event.

3. `test_promote_step_consumes_implementation_proposals()`

   * set bundle.implementation proposal paths
   * assert orchestrator called with `mode="both"` and proposals loaded.

---

## Gap 2: Planning Integrates with Constraints

### Target behavior

PlanStep must not produce “implement X” plans that require decisions not covered by constraints. Instead, it emits **under-spec events** early so the loop blocks before implementation.  

---

### Concrete design

#### 1) Extend PlanStep output: include decision requirements

**Planning agent output must include:**

* intentions (what to implement)
* for each intention: `decision_requirements[]`

```json
{
  "intentions": [
    {
      "intention_id": "INT-001",
      "gap_ids": ["GAP-..."],
      "target_file": "lib/foo.py",
      "target_symbols": ["pkg.foo:bar"],
      "approach": "short text",
      "acceptance_criteria": ["..."],
      "decision_requirements": [
        {
          "decision_id": "DEC-ERROR-POLICY",
          "question": "What error policy applies for invalid input?",
          "options": ["raise", "return sentinel", "log+skip"],
          "needed_for": "pkg.foo:bar"
        }
      ]
    }
  ]
}
```

**Module placement**

* Planning agent definition update in `.agents/agents/<planning-agent>.md`
* PlanStep wrapper in `orchestration/promotion_loop.py`

#### 2) Deterministic constraints coverage check in PlanStep

**New helper**

* `orchestration/under_spec/planning_gate.py` (new)

```python
@dataclass
class CoverageResult:
    covered: bool
    covering_constraints: list[str]      # paths or ids
    rationale: str

def check_decision_coverage(
    *,
    constraints_store: ConstraintsStore,
    slice_id: str,
    decision: dict,                      # as produced by planning agent
) -> CoverageResult:
    ...
```

**PlanStep algorithm**

1. Load constraints paths for this slice from `ConstraintsStore` (plus global constraints).
2. Run planning agent to produce `plan.json`.
3. For each intention decision requirement:

   * if covered → keep intention
   * if not covered → emit `UnderSpecEvent(kind="MISSING_CONSTRAINT", ...)` and mark intention blocked
4. Write:

   * `plan.json`
   * `plan.under_spec_events.json` (events derived in PlanStep)
5. Update `bundle.plan` and `bundle.under_spec.pending_events += plan_events`.

This satisfies “block on ambiguity” *before* implementation.  

---

### Answers to Gap 2 questions

1. **Should PlanStep produce under_spec_events directly?**
   Yes. PlanStep should emit them as first-class artifacts. ImplementStep may still emit additional under-spec events (because some ambiguity is only visible during code writing), but planning should catch predictable ones early.

2. **Modify planning prompt: pass constraints context or deterministic pre-filter?**
   Use **both**:

   * pass constraints (or a constraints summary + paths) into the planning agent so it avoids proposing illegal/ambiguous plans
   * still perform deterministic coverage validation with `ConstraintsStore` and convert uncovered decisions into under_spec events.

3. **Interface PlanStep ↔ ConstraintsStore: bundle or direct?**
   **Directly from the store** (store is source of truth). Bundle should contain `constraints_refs` for traceability and staleness checking, but not be the primary lookup.

---

### Test strategy (Gap 2)

1. `test_plan_step_emits_under_spec_events_when_constraints_missing()`

   * constraints store empty
   * planning agent outputs a decision requirement
   * assert UnderSpec events written and loop blocks at UNDER_SPEC_CHECK.

2. `test_plan_step_keeps_intentions_when_constraints_cover()`

   * constraints store contains matching policy
   * assert no under_spec events and plan remains.

3. `test_constraints_staleness_hash_recorded()`

   * ensure plan writes a constraints snapshot hash to detect later drift.

---

## Gap 3: Library Quality Validator (Post-Phase 0)

### Target behavior

After Phase 0 assembles libraries, run a validator that checks:

* overlap detection
* concern isolation
* completeness (post-assembly)
* dependency minimality

before starting PromotionLoop on those libraries.  

---

### Concrete design

#### Module placement

* `intake/quality/library_quality_validator.py` (new) **or**
* `intake/validate.py` (new submodule), called by:

  * `orchestration/pdd_orchestrator.py` after Phase 0 output install
  * and also by CLI entrypoint after `run_phase0()`

This is logically part of “Promotion 1 QA” (Phase 0 exit gate). 

#### Inputs (existing artifacts from Phase 0)

* `route_table.jsonl`
* `coverage_ledger.jsonl`
* `libraries/LIB-XX/analysis.md`
* `libraries/LIB-XX/constraints.md`
* `libraries/LIB-XX/details/*.md`

#### Output artifacts (new)

In workspace (or phase0 output dir):

* `library_quality.report.json`
* `library_quality.report.md` (human-readable)
* `library_quality.issues.jsonl` (one issue per line)
* Optional: `library_quality.remediation_plan.json`

#### Scoring rubric (concrete)

Compute sub-scores 0–100:

1. **Completeness (hard gate)**

* 100 if coverage ledger indicates 100% routed-or-noise and assembly contains all routed spans.
* else 0 (fail)

2. **Routing overlap (hard gate threshold)**
   Deterministic:

* For each source line, count number of distinct libraries it appears in (via route table).
* Overlap ratio = `lines_with_count>1 / total_lines`.
* Score = `100 * max(0, 1 - overlap_ratio / 0.02)` (0 overlap → 100, 2% overlap → 0)
* Fail if overlap_ratio > 1% (tuneable)

3. **Semantic overlap (LLM judge)**
   LLM compares each pair of library `analysis.md` (and optionally constraints) and returns:

* `overlap_score` in [0,1]
* `relationship`: {distinct, subset, redundant, crosscutting}
* Score = `100 * (1 - max_pair_overlap_score)`
* Fail if any pair overlap_score > 0.75 **and** relationship != “crosscutting intentional”

4. **Concern isolation (LLM judge per library)**
   LLM returns:

* `cohesion_score` [0,1]
* `top_concerns[]`
* `mixed_concerns[]` (if any)
* Score = `avg(100 * cohesion_score)`
* Fail if any library cohesion_score < 0.5 (tuneable)

5. **Dependency minimality (LLM-inferred graph + deterministic stats)**
   LLM produces `library_dependency_edges` (A depends on B with reason).
   Compute:

* max out-degree, average out-degree
* identify “god library” if out-degree > threshold
  Score = `100 - 10*(avg_out_degree)` capped [0,100]
  Advisory initially (warn-only), can be turned into gate later.

**Gate vs advisory**

* For QA-readiness: **hard gate** on (1) completeness, (2) routing overlap, (3) semantic overlap, (4) concern isolation.
* Dependency minimality starts as **advisory** but still reported.

#### Remediation flow if validation fails

**Default remediation (automatic, minimal)**

* Run a new agent `spec-intake-library-repair` (new agent def) that consumes:

  * library descriptions
  * overlap/isolations issues
  * route table summary
* Output: revised `libraries.json` (split/merge/rename suggestions)
* Then re-run Phase 0 steps 3–5 (route, coverage, assemble) using existing Phase 0 modules:

  * reuse existing summaries and sectionization
  * only re-route and re-assemble

**Manual remediation (interactive)**

* validator writes `library_quality.report.md` with:

  * top 5 conflicts
  * suggested split/merge actions
* user edits libraries.json, reruns routing.

This keeps Phase 0 as the tool and avoids inventing a new “library mutator” subsystem. 

---

### Answers to Gap 3 questions

1. **LLM-based or deterministic?**
   Hybrid:

* deterministic for overlap-by-route-table and completeness
* LLM for semantic overlap and concern isolation (the “same concern in different words” case)

2. **Metrics?**
   Use the rubric above (5 scored dimensions, 4 gating).

3. **Gate or advisory?**
   Gate (for overlap/isolation/completeness), advisory for dependency minimality at first.

4. **Remediation?**
   Automated “library repair” loop that reuses Phase 0 routing (steps 3–5), driven by a repair agent; interactive alternative is manual split/merge.

5. **Where does it live?**
   Inside `intake/` (because it validates Phase 0 outputs), invoked by orchestrator before PromotionLoop begins.

---

### Test strategy (Gap 3)

* Fixture-based tests using existing Phase 0 fixtures:

  1. `test_library_quality_passes_on_treasury_fixture()` (should pass)
  2. `test_overlap_detection_flags_duplicate_routes()` (construct route_table with duplicates)
  3. `test_semantic_overlap_flags_redundant_library_pair()` (mock LLM judge output)
  4. `test_remediation_re_routes_and_reassembles()` (mock repair agent)

---

## Gap 4: Small Test Generation

### Target behavior

When implementing code, the same agent produces **small tests** as part of its implementation output (Principle 8), and the loop runs those tests via existing gates and CI integration.  

---

### Concrete design

#### 1) Tests generated by the implementor (same agent)

**Decision**

* Use the same `pdd-function-implementor` call that writes the function.
* Rationale: it already has the spec context and is doing the “understanding” work.  

This avoids a “mechanical” separate test generator pass.

#### 2) Test types

MVP: **unit tests per function** + optional “slice smoke test” when multiple functions compose.

* Unit tests:

  * happy path
  * 1–2 edge cases implied by spec comments
  * error policy cases only if constraints cover; otherwise emit under-spec event

Optional later:

* property-based tests if the project already has tooling (Hypothesis, QuickCheck, etc.)

#### 3) Where tests live (language-agnostic)

The agent must select the location consistent with the repo’s existing test layout.

ImplementationRunner provides:

* list of existing test directories (deterministic scan for common dirs `tests/`, `test/`, etc. — safe because it’s repo-owned structure, not spec parsing)
* existing runner config hints (presence of pytest.ini/package.json/etc.)

Agent chooses:

* `tests/test_<module>_<symbol>.py` (Python example), or equivalent.

#### 4) Test runner abstraction (needed for language-agnostic)

Even if you only use Python today, make the runner a swappable abstraction (per simpler.md). 

**Module placement**

* `core/testing/runner.py` (new)
* `core/testing/registry.py` (new)

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Literal

@dataclass
class TestFailure:
    test_id: str | None
    file: str | None
    message: str
    raw_excerpt_path: str

@dataclass
class TestRunResult:
    passed: bool
    scope: Literal["SLICE", "FULL"]
    runner_id: str
    command: list[str]
    stdout_path: str
    stderr_path: str
    failures: list[TestFailure]

class TestRunner(Protocol):
    runner_id: str
    def run(self, *, root: Path, scope: Literal["SLICE","FULL"], targets: list[str] | None) -> TestRunResult: ...

class TestRunnerRegistry:
    def pick(self, *, root: Path) -> TestRunner: ...
```

* `PytestRunner` implementation can call the current code path used by `ALL_TESTS_PASS` gate (reuse, don’t rewrite).

#### 5) Interaction with `ALL_TESTS_PASS` gate

Two viable integration points; choose one and be consistent:

**Option A (minimal change; recommended first)**

* Keep `ALL_TESTS_PASS` gate behavior as-is.
* Ensure tests exist before PROMOTE runs (they will, because ImplementStep runs before PROMOTE).
* Gate runs tests and passes/fails.

**Option B (more structured)**

* Run slice tests in INTEGRATE and write `tests.slice.json`.
* Modify `ALL_TESTS_PASS` gate to consume test result from EvidenceBundle instead of re-running.

MVP: Option A is fastest; Option B reduces redundant runs later.

#### 6) Failure handling: bad implementation vs bad test

Treat failures as work items, not “try again blindly”:

* On failing tests:

  * create a DemotionTicket (source=`TEST_FAILURE`) that includes:

    * failing test name/path
    * stdout/stderr excerpts
    * suspected pins/atoms (if traceable)
* Next iteration:

  * PlanStep includes intention “fix failing test/implementation”
  * Implementor sees failure output and patches either:

    * implementation, or
    * test (if test contradicted spec comments / constraints)

If the failure is due to missing constraints, implementor must emit under-spec event instead of guessing.

---

### Answers to Gap 4 questions

1. **Same agent or separate?**
   Same agent (implementor emits tests in the same output).

2. **What kind of tests?**
   Unit tests per function; optional slice smoke tests.

3. **Where do tests live?**
   In the slice worktree, in the repo’s normal test location; agent chooses, recorded in `tests_added`.

4. **Need test runner abstraction?**
   Yes, but implement minimally: a registry with at least a pytest runner that wraps your existing test execution path.

5. **What if test fails?**
   DemotionTicket + retry loop; implementor fixes code or test. If ambiguity, emit under-spec and block.

6. **Emit body + tests in one output?**
   Yes; schema already includes `tests[]` with diffs.

---

### Test strategy (Gap 4)

* `test_implementor_schema_includes_tests_and_runner_applies_patch()`
* `test_generated_tests_discovered_by_gate_and_run()`
* `test_failing_generated_test_creates_demotion_ticket()`

---

## Gap 5: Full Demotion Chain (L3 → L2 → L1)

### Target behavior

Failures at higher layers produce DemotionTickets targeting the lowest layer that can correctly fix the issue, with deterministic traceability via pins and projections. Demotion replaces “skip,” and re-promotion is automatic via the loop + pipeline.   

---

### Concrete design

#### 1) Add a `DemotionRouter` + `DemotionTriage` classifier

**Module placement**

* `orchestration/demotion/router.py` (new)
* `orchestration/demotion/triage.py` (new)

```python
from dataclasses import dataclass
from typing import Literal

Layer = Literal["L1", "L2", "L3"]

@dataclass
class DemotionContext:
    active_layer: Layer
    source_layer: Layer
    source: str                    # TEST_FAILURE, REVIEW, ARCH_GATE, etc.
    gate: str | None
    failing_files: list[str]
    failing_pins: list[str]
    evidence_paths: list[str]

@dataclass
class DemotionRouting:
    target_layer: Layer
    reason: str
    confidence: float

class DemotionRouter:
    def route(self, ctx: DemotionContext) -> DemotionRouting:
        ...
```

**Routing policy (concrete)**

* If issue is “style/refactor only” → L3
* If issue is “architectural wiring / projection misuse / inline atom logic” → L2
* If issue is “algorithmic behavior / missing spec / contract mismatch / under-spec” → L1

Additionally:

* If active_layer is lower than the intended target, route **down** (because higher layers aren’t editable). This matches the batch model described in the refined loop design. 

#### 2) Extend DemotionTicket for multi-layer traceability

If `DemotionTicket` doesn’t already include these, add:

```python
origin_layer: Layer
hop_trace: list[Layer] = field(default_factory=list)
```

Tickets can target any layer directly; `hop_trace` records classification (not required to physically “hop” one layer at a time).

#### 3) Implement `DownwardFlowEngine` concretely (pin-based)

**Module placement**

* `orchestration/downward_flow/engine.py` (new or wire existing)
* invoked from:

  * INTEGRATE on test failures
  * L3 review findings
  * architectural gate failures

**Key algorithm**
Input: failure evidence (test result, gate violations, review findings)
Output: DemotionTickets with `failing_pins` / `failing_atoms`

Steps:

1. Identify **failing location(s)**:

   * from test failure stack trace / file references (LLM-assisted if needed)
2. Map location → pins:

   * use PinRegistry query: `pins_covering(file, line_range)` if available
   * if not available, require generated code to embed pin markers (recommended invariant):

     * architecture wrappers contain marker comment like `# pdd:pin=PIN-...`
3. Trace backward:

   * `PinRegistry.trace_backward(pin_id)` to L1 atoms
4. Classify & route:

   * DemotionRouter chooses target layer (L1/L2/L3)
5. Create ticket:

   * include evidence paths to bundle artifacts
   * include recommended patch if you can (optional initially)

This matches the “DownwardFlowEngine traces via pins; demotion goes all the way down” model.  

#### 4) Extend `DemotionManager.apply(ticket)` to support target layers

Current behavior: patches L1 only.

Extend:

* `apply(ticket, layer_root: Path)` chooses worktree root by target layer:

  * `L1`: patch L1 dirty or a slice grandchild
  * `L2`: patch L2 dirty
  * `L3`: patch L3 dirty

This depends on having layer-aware worktree refs (already laid out in the refined model). 

#### 5) Re-promotion mechanics (no separate queue required)

* When a ticket applies to L1:

  * it creates/updates gaps (via GapQueue)
  * the affected slice naturally becomes schedulable again
  * once L1 clean advances, pipeline merges upward (L1→L2→L3) as batches

So: **GapQueue is the re-promotion queue**.

This matches the refined dirty/clean pipeline model. 

#### 6) Wire reviewer agents to emit DemotionTickets

**Module placement**

* `orchestration/review/findings_to_tickets.py` (new)

Inputs:

* reviewer outputs (existing `.agents/agents/chatgpt-*-reviewer.md` findings)
* pin registry + graph snapshots

Outputs:

* tickets via DownwardFlowEngine + DemotionRouter

---

### Answers to Gap 5 questions

1. **How does L3 decide quality vs logic?**
   LLM-assisted triage is acceptable here, but enforce structured output:

* reviewers output findings with `category: STYLE | QUALITY | LOGIC | ARCH | SPEC`
* categories map deterministically:

  * STYLE/QUALITY → L3
  * LOGIC → route via pins → likely L1
  * ARCH → L2
  * SPEC/UNDER_SPEC → L1 + under-spec events

2. **How does L2 decide fix vs demote to L1?**
   Use existing architectural gates as signals:

* `NO_INLINED_ATOM_LOGIC` violation → L1
* projection misuse / missing projections → L2
  If architectural change requires new algorithmic atoms (missing pins/spec) → L1.

3. **Multi-layer ticket: hop or direct?**
   Allow direct targeting (L3→L1) but record `origin_layer` and `hop_trace` for auditability.

4. **How does re-promotion work?**
   No new queue: DemotionManager updates GapQueue; scheduler picks slice; PromotionLoop re-runs; pipeline promotes upward.

5. **DownwardFlowEngine concrete?**
   Failure → locate pins covering failing span → `trace_backward()` → atoms → ticket.

6. **Demotion vs worktrees?**
   Apply patch in the **target layer’s dirty** worktree; if target is L1 and the unit is a slice, apply in slice grandchild (preferred) then merge.

---

### Test strategy (Gap 5)

1. `test_downward_flow_traces_test_failure_to_atom_and_creates_ticket()`
2. `test_router_sends_logic_issue_to_L1_and_quality_issue_to_L3()`
3. `test_demotion_manager_applies_patch_to_correct_layer_root()`
4. `test_repromotion_occurs_via_gapqueue_and_scheduler()` (integration)

---

## Gap 6: Architectural Implementation Agent

### Target behavior

After atoms are promoted (pins exist), an architectural agent builds L2 services/handlers/middleware by consuming **pin projections** and emitting:

* architecture code patch
* projection proposals (PASS_THROUGH, EVENT_BRIDGE, STORE_FACADE, COMPOSITION)
* edges (event/call/store)
* under-spec events if the assembly requires missing decisions

This is Promotion 2’s missing “construction” step. 

---

### Concrete design

#### 1) When architectural implementation runs

**Rule**

* Architectural creative work runs when **active layer is L2**, i.e. after L1 has drained (`l1.dirty == l1.clean`) per the batch model.  

**Trigger**

* A scheduler discovers L2 work units from the graph:

  * components with promoted atoms but missing projections / missing architecture entrypoints.

#### 2) Work unit definition (per-slice vs cross-slice)

MVP: per-slice (per library) architecture assembly:

* build `architecture/<slice_id>_service.*` and event handlers that wrap atoms from that slice
* cross-slice interactions expressed via events or explicit calls based on adjacency edges

Follow-on: “connected component” work units at L2 using adjacency graph components (better long-term).

#### 3) New agent: `pdd-architecture-implementor`

**Input (file-based, low context pressure)**

* `pins.snapshot.json` (PinRegistry)
* `graph.snapshot.json` (AdjacencyGraph)
* `libraries/<slice_id>/analysis.md` + constraints
* existing architecture files list + excerpts (paths only; agent can request specific files)

**Output schema (exact)**

```json
{
  "architecture_patch": [
    {
      "path": "architecture/<slice_id>_service.py",
      "unified_diff": "diff --git ...\n--- ...\n+++ ...\n@@ ...\n"
    }
  ],
  "projection_proposals": [
    {
      "projection_id": "PROJ-...",
      "type": "PASS_THROUGH",
      "from_pin": "PIN-ATOM-...",
      "to_arch_fqn": "architecture.<slice_id>_service:handle_xyz",
      "file": "architecture/<slice_id>_service.py",
      "span": { "start_line": 10, "end_line": 48, "anchor_before": "...", "anchor_after": "..." },
      "evidence_paths": []
    }
  ],
  "pin_proposals": [
    {
      "pin_id": "PIN-ARCH-...",
      "role": "ARCH",
      "fqn": "architecture.<slice_id>_service:handle_xyz",
      "file": "architecture/<slice_id>_service.py",
      "span": { "start_line": 10, "end_line": 48, "anchor_before": "...", "anchor_after": "..." }
    }
  ],
  "edge_proposals": [
    { "src": "PIN-ARCH-...", "dst": "PIN-ATOM-...", "signal_type": "CALL", "weight": 0.9 }
  ],
  "tests": [
    {
      "path": "tests/test_<slice_id>_service.py",
      "purpose": "Integration test: service delegates to atom pins correctly",
      "scope": "INTEGRATION",
      "unified_diff": "diff --git ...\n--- ...\n+++ ...\n@@ ...\n"
    }
  ],
  "under_spec_events": [
    {
      "kind": "MISSING_CONSTRAINT",
      "question": "Which transport/event bus is used for EVENT_BRIDGE handlers?",
      "options": ["existing bus", "in-process callbacks", "HTTP"],
      "needed_for": "architecture.<slice_id>_service"
    }
  ],
  "notes_md": "..."
}
```

**Required invariant for traceability**

* Every generated architectural wrapper block includes a stable marker referencing its pin/projection id, e.g.:

  * `# pdd:pin=PIN-ARCH-...`
  * `# pdd:projection=PROJ-...`

This makes DownwardFlowEngine and gate checks deterministic without AST parsing.

#### 4) Module placement and wiring

**New modules**

* `orchestration/architecture/assembler.py`

  * calls the architecture agent
  * applies patches in L2 dirty worktree
  * writes evidence artifacts into EvidenceBundle iteration directory for L2 runs

* `branches/projections/applier.py` (new or extend existing BranchManager)

  * merges `projection_proposals` into PinRegistry

**Integration points**

* When L2 is active:

  * run an L2-specific loop (can reuse PromotionLoop skeleton but with different step set):

    * GAP_EXPLORATION (missing projections/entrypoints)
    * PLAN (architecture plan)
    * IMPLEMENT (architecture agent)
    * UNDER_SPEC_CHECK
    * ANALYZE (analyze_source for architecture files)
    * PROMOTE (update projections + run architectural gates)
    * INTEGRATE (tests in L2 clean)
    * VERIFY (lineage + connectivity)

The “promotion loop is tools invoked per slice” design already anticipates this multi-layer iteration model.  

#### 5) Compliance gates for architecture

Existing architectural gates are sufficient initially:

* NO_INLINED_ATOM_LOGIC
* FUNCTION_RECOMPOSITION
* PIN_COVERAGE
* INTRODUCED_ALGORITHM_SPECS

Plus tests via ALL_TESTS_PASS / CI.

If anything is missing later, add gates only as graph/evidence checks (no parsing). 

#### 6) Separate from P9 implementor

Keep separate agent:

* P9 implementor: algorithmic function bodies + unit tests
* Architecture implementor: composition/wiring + integration tests + projection proposals

Different task, different failure modes, different inputs.

---

### Answers to Gap 6 questions

1. **When does it happen?**
   When L2 becomes active (after L1 drained). Triggered by “missing projections / missing architecture entrypoints” work items derived from pin registry + graph.

2. **Input/output schema?**
   As specified above: `architecture_patch`, `projection_proposals`, `pin_proposals` (arch pins), `edge_proposals`, `tests`, `under_spec_events`.

3. **Per-slice or cross-slice?**
   MVP per-slice; follow-on uses graph connected components at L2.

4. **Worktrees?**
   Architecture code lives in L2 dirty/clean worktrees. L1 grandchild worktrees remain for L1 only.

5. **Are existing gates sufficient?**
   Yes initially. Add more only if you find systemic misses, and keep them graph/evidence-based.

6. **Extend P9 or separate?**
   Separate agent.

---

### Test strategy (Gap 6)

1. `test_architecture_agent_output_applies_and_projections_merge()`
2. `test_architecture_blocks_include_pin_markers_for_downward_flow()`
3. `test_architecture_gates_detect_inlined_logic()` (fixture with deliberate violation)
4. `test_l2_integration_runs_in_clean_and_on_failure_demotes()` (depends on Gap 5 routing)

---

## Implementation order and dependencies

### Minimal viable order to reach QA-ready end-to-end

1. **Gap 1 + Gap 4 together**

* Update implementor schema to include proposals + tests
* Wire ImplementStep to real implementation and produce artifacts

2. **Gap 2**

* Planning emits under-spec events early; blocks before ambiguous implementation

3. **Gap 3**

* Library quality validator gates Phase 0 outputs before loop starts (prevents wasted implementation)

4. **Gap 6**

* Architecture implementor builds L2 from promoted atoms/pins/projections

5. **Gap 5**

* Full demotion chain + DownwardFlowEngine + routing to correct layer
  (you can implement the router + L1 demotion first, then extend to L2/L3 once Gap 6 exists)

This order ensures you can get an L1 slice to “implemented + tested + promoted” first, then add architecture, then make failures converge via demotion.

---

## Migration from legacy `pdd_orchestrator.py`

### Reuse (keep)

From the real P9 logic (`_run_implementation()`):

* `analyze_project()` and any gap-finding helpers
* the per-function loop structure
* the “apply edit → re-analyze to confirm gap resolved” pattern

Those become internals of `ImplementationRunner`.

### Replace (delete once loop works)

* `pdd_orchestrator._run_implementation()` itself (legacy global phase runner)
* old implementor schema parsing (`body`, `imports_needed`, `gaps`, `notes`)
* any “project-wide” iteration assumptions (per-slice only)

This matches the “no backwards compatibility long-term” constraint.

---

## Impact on existing tests

Expect breakage in three areas:

1. **Agent-output parsing tests**

* Anything asserting old implementor JSON fields must be updated to the new schema.

2. **PromotionLoop step tests**

* ImplementStep stubs replaced with real runner:

  * tests that expected empty `ImplementationRef` need new fixtures/mocks.

3. **PDD orchestrator phase tests**

* If tests directly run `Phase.IMPLEMENTATION` expecting old behavior (gap report only), either:

  * switch them to loop mode, or
  * update expectations to “implementation produces patch + tests + proposals”.

Given “no shims long-term,” prefer flipping tests to the loop-based entrypoint once Gap 1/2/4 land.

---

## Reference links

* PromotionLoop refinement (worktrees/batching model) 
* PromotionLoop research response (bundle + step contracts) 
* simpler.md (Principle 8 tests + worktree model) 
* WORKFLOW_ANALYSIS (promotion model + demotion chain) 
* Design audit (graph-first + LLM outputs) 
* Language-agnostic response (evidence-first gates, no AST) 
* Long term goals (what’s implemented; where P9 currently sits) 
* Phase 0 research response (routing-only constraints; validator placement) 
