## Target architecture

Treat the planner as a first‑class decision service with first‑class artifacts:

1. **Every planner call emits a trace** with a deterministic `decision_key` (stable across runs).
2. **Eval reads traces** (not in-memory objects) and produces:

   * per-decision verdicts + diagnostics
   * per-slice aggregates
   * per-run **PlannerScorecard**
3. **Ground truth is capability-specific** and **constraint-style** (acceptable regions), not brittle exact-match strings.
4. **Replay and diff are trace-native**: reproduce a single decision, override inputs/outputs, and compare before/after changes.

---

# 1) Ground truth schema

## Core design choice

Planner decisions are non-deterministic, so ground truth cannot be “exact JSON match.” Use **constraint-based ground truth**:

* **Hard invariants** (must be true)
* **Expected atoms** (things that should appear, order-insensitive)
* **Forbidden atoms** (must not appear; catches false positives/out-of-scope)
* **Allowed variants** (multiple acceptable answer sets)
* **Process expectations** (tool usage / evidence-first) as optional constraints

This makes “correctness” comparable while allowing multiple valid plans.

## Deterministic decision identity

Add a stable identifier derived from the request and inputs:

* `decision_key = "{layer}:{capability}:{slice_id}:{iteration}:{input_hash[:8]}"`

Where:

* `iteration` comes from `PlanningContext.iteration` (or 0 if unset)
* `input_hash = sha256(canonical_json(inputs_subset))`
* `inputs_subset` is capability-specific (see below) so the key doesn’t drift when irrelevant metadata changes.

This is the join key between traces and ground truth.

## Ground truth file layout

Create a separate fixture file alongside existing Phase 0 truth:

```
fixtures/
  chaotic_treasury_expanded_planner_ground_truth.yaml
```

Optionally split per layer later:

```
fixtures/gt/
  treasury_planner_gt_l1.yaml
  treasury_planner_gt_l2.yaml
  treasury_planner_gt_l3.yaml
```

### YAML schema (v1)

```yaml
meta:
  spec_id: chaotic_treasury_expanded
  gt_version: 1
  created_at: "2026-02-11"
  phase0_gt_ref: chaotic_treasury_expanded_ground_truth.yaml
  notes: "Constraint-based truth for planner decisions."

cases:
  - decision_key: "l1:PLAN:LIB-01:0:9f12ab3c"
    capability: PLAN
    layer: l1
    slice_id: LIB-01
    iteration: 0
    input_fingerprint:
      gaps_hash: "sha256:..."          # optional drift detection
      slice_snapshot_hash: "sha256:..." # optional
    expected:
      outcome:
        intentions:
          must_include:
            - id: "fn:create_ledger_entry"
              match:
                function_name_any_of: ["create_ledger_entry", "add_ledger_entry"]
                file_any_of: ["ledger.py", "lib/ledger.py"]
            - id: "fn:validate_transaction"
              match:
                function_name_any_of: ["validate_transaction"]
          must_not_include:
            - id: "oos:payments_service"
              match:
                function_name_regex: ".*payments.*"
      invariants:
        - type: "schema"
          rule: "l1_plan_intentions_v1"
        - type: "scope"
          rule: "files_within_slice_root"
        - type: "dedupe"
          key_fields: ["function_name", "file"]
          max_duplicates: 0
    process_expectations:
      - type: "evidence_first"
        min_rate: 1.0
        applicable_when: "any_under_spec_or_signal"
    rubric:
      hard_gates:
        - metric: "must_include_recall"
          threshold: 1.0
        - metric: "must_not_include_precision"
          threshold: 1.0
      soft_signals:
        - metric: "actionability"
          threshold_warn: 0.7
          threshold_fail: 0.4
```

### Capability-specific “inputs_subset” for hashing

Use only what defines the decision:

* **RESOLVE_SIGNAL**: `signal_id` (or `signal.text` hash) + `layer`
* **GAP**: `bundle.gaps.open_gaps` (or evidence bundle id + hash of evidence excerpts)
* **PLAN**: normalized `gaps` list (targets + descriptions + dependencies), plus a discovery signature if you want drift detection
* **UNDER_SPEC**: normalized list of `events` (event_id + question + key context)
* **INTEGRATION_ANALYSIS**: slice + discovered topology file list hash (L2) or diffs hash (L3)

This makes `decision_key` stable even if non-essential metadata changes.

---

## What “ground truth” should contain per capability

### RESOLVE_SIGNAL

Ground truth is **question → acceptable answer set**.

* `should_resolve: true/false`
* `answers_any_of`: list of acceptable canonical answers (short, declarative)
* Optional: `must_cite`: evidence section ids / constraints ids

**Correct means**:

* If `should_resolve=false`, planner returns `NOOP` (or `None`) and does not hallucinate.
* If `should_resolve=true`, answer matches one of the acceptable variants.

### GAP

Ground truth is **gap atoms + optional clustering constraints**, not a full clustering tree.

* `must_find`: list of gap atoms (id + target + summary)
* `must_not_find`: known false positives
* Optional: cluster labels are soft (since clustering is subjective)

**Correct means**:

* High recall on `must_find`
* Low false positives on `must_not_find`

### PLAN

Ground truth is **intentions as atoms** plus invariants.

Atoms differ by layer:

* L1 atoms: `{function_name, file, spec_comment_ref(optional)}`
* L2 atoms: `{component_id, target_files, pin_refs}`
* L3 atoms: `{file, function_span, smell_type, behavior_preservation_check}`

**Correct means**:

* Must-include intentions appear (order doesn’t matter)
* No out-of-scope intentions
* Intentions are actionable (minimum required fields non-empty)

### UNDER_SPEC

Ground truth is a **block/unblock truth table** per event.

Per event:

* `should_block: true/false`
* If `should_block=false`: required constraint keys or answer type
* If `should_block=true`: required question patterns (so the planner asks the right thing)

**Correct means**:

* No false unblocks (safety-critical)
* Questions are specific and tied to the slice context

### INTEGRATION_ANALYSIS

Ground truth is **risk atoms** and **dependency edges** at coarse granularity.

* `must_include_risks`: e.g., “pin consumed by component X but not wired”
* `must_not_include_risks`: bogus dependencies

**Correct means**:

* Flags the real integration risks and dependencies
* Avoids inventing topology not present in manifests

---

## Deriving truth from downstream outcomes (should you?)

Use downstream outcomes only as **secondary signals**:

* A plan leading to success does **not** mean the plan was correct (implementation may compensate).
* A plan leading to failure does **not** mean the plan was wrong (downstream steps may fail independently).

So:

* Primary: decision-vs-ground-truth constraints
* Secondary: convergence/iteration efficiency, demotions, CI failures correlated to decisions

---

## Granularity recommendation

Start with **per-decision evaluation** but only ground-truth the **high-value decisions** first:

1. UNDER_SPEC (safety / block policy)
2. RESOLVE_SIGNAL (ambiguity hygiene)
3. PLAN (actionability + scope)
4. L2 integration risks (coarse)
5. GAP clustering last (hard to truth early)

Then expand coverage.

---

# 2) Eval harness design

## Required modes

### A) In-situ (primary)

Runs the real pipeline with output chaining and scores planner decisions from traces.

**Entry point**: `PddLifecycle.run()`
This is the only way to satisfy:

* real call patterns
* cross-layer transitions
* demotion propagation
* output chaining

**Artifacts produced**:

* normal pipeline receipts (existing)
* planner traces (existing)
* `planner_eval.jsonl` (new)
* `planner_scorecard.json/md` (new)

### B) Slice-level in-situ (fast iteration)

Runs `PromotionLoop.run_slice()` for a target slice/layer.

Use for tight debugging while still exercising real orchestration.

### C) Isolated replay (debugging + regression)

Re-runs a single planner decision using `replay.json` (and optional overrides).

Use for:

* reproducing a wrong decision quickly
* testing planner fixes without running the full pipeline
* creating minimal regression cases

---

## Preventing cascading errors (without breaking realism)

You can’t eliminate cascade in in-situ runs; instead you **separate diagnosis from propagation**:

1. **Score every decision independently** (vs ground truth) even if downstream cascades.
2. Provide a targeted **counterfactual runner**:

   * pick a failing decision
   * override it with ground truth / oracle
   * re-run from the next step onward
   * measure whether the cascade disappears

### Mechanical design for overrides

Add an optional override hook to Planner:

* `Planner(..., override_provider: Callable[[PlanningRequest], PlanningResult] | None = None)`

If override_provider returns non-None, planner returns it and still writes a trace marking `overridden=true`.

This enables:

* “force ground truth for decision X”
* “force oracle answer for under-spec”
* “replay with frozen model outputs”

---

## Shadow mode (planner vs oracle)

Purpose: **triage and ground-truth acceleration**, not pass/fail.

Mechanics:

* For each planning request, run:

  * **candidate planner** (the one under test, used by pipeline)
  * **oracle planner** (Claude / Opus / “best available” config)
* Record oracle outputs in the same trace directory:

  * `shadow_decision.json`
  * optional `shadow_calls.jsonl`

Rules:

* oracle run is **side-effect free** (no constraint persistence, no writes)
* oracle output is **never consumed by the pipeline**, only logged

Shadow comparisons can generate:

* divergence rate
* cases where candidate blocks but oracle resolves (and vice versa)
* candidate hallucinations detected by oracle judge prompts

---

## Harness structure (recommended)

Create a dedicated planner eval package:

```
spec_manager/evals/planner/
  harness.py
  ground_truth.py
  scorers/
    base.py
    resolve_signal.py
    gap.py
    plan.py
    under_spec.py
    integration_analysis.py
  trace_loader.py
  reporter.py
  export_gt.py
```

And a CLI entry:

* `spec-manager eval planner --fixture chaotic_treasury_expanded --gt fixtures/..._planner_ground_truth.yaml --mode e2e`

---

# 3) Planner scorecard

## Keep it separate from the pipeline scorecard

Recommendation:

* **Separate `PlannerScorecard`** artifact for planner-specific metrics
* Optionally add **one** soft signal in the existing pipeline Scorecard:

  * `planner.overall` (summary only)

Reason: pipeline Scorecard is about end-to-end delivery; planner Scorecard is about decision quality and hygiene.

---

## Hard gates vs soft signals

### Hard gates (initial set)

These should be “mechanically certain,” not fuzzy.

1. **planner.trace_integrity**

   * Every planner call produces `request.json` + `decision.json`
   * `PASS=1.0`, else `FAIL`

2. **planner.no_error_status**

   * `PlanningResult.status == ERROR` count is zero
   * `PASS` if 0, else `FAIL`

3. **planner.under_spec_safety**

   * False-unblock rate for events that GT says must block is **0**
   * `PASS` if 0, else `FAIL`

4. **planner.schema_validity**

   * Outputs conform to capability schema (see below)
   * `PASS` if 0 violations, else `FAIL`

5. **planner.no_oos_intentions**

   * For PLAN: no intention targets outside slice scope (by file path / component id)
   * `PASS` if 0, else `FAIL`

### Soft signals (diagnostics)

These can tolerate judge noise and non-determinism.

**Decision quality**

* `planner.resolve_signal.accuracy`
* `planner.gap.recall`, `planner.gap.precision`
* `planner.plan.coverage`, `planner.plan.redundancy`
* `planner.integration.risk_recall`

**Epistemic hygiene (quantitative, mechanical)**
Define “unsafe resolution” mechanically:

* For RESOLVE_SIGNAL or UNDER_SPEC:

  * Planner returns a non-empty answer/constraint **and**
  * trace has **no evidence_tool/tool_calls** and decision has **no evidence_refs**

Metrics:

* `planner.unsafe_resolution_rate` (target 0)
* `planner.block_when_uncertain_rate` (higher is better, but bounded)

**Efficiency**

* `planner.model_calls_per_decision_p50/p95`
* `planner.tokens_per_decision_p50/p95` (requires token capture)
* `planner.tool_calls_per_decision`

**Tool usage**

* `planner.evidence_first_rate`
* `planner.web_escalation_rate` (if web research exists)
* `planner.integration_tool_used_rate` (L2/L3)

**Convergence impact (secondary)**

* `planner.iterations_per_slice_delta_vs_baseline`
* `planner.demotion_rate_delta_vs_baseline`

---

## Initial thresholds (reasonable defaults)

These are starting points; tune after one full run.

Hard gates:

* trace_integrity: PASS 1.0
* no_error_status: PASS if 0
* under_spec_safety: PASS if 0 false unblocks
* schema_validity: PASS if 0 violations
* no_oos_intentions: PASS if 0

Soft:

* unsafe_resolution_rate: PASS 0, WARN <= 0.01, FAIL > 0.01
* evidence_first_rate: PASS >= 0.9, WARN >= 0.75, FAIL < 0.75
* plan.coverage (must_include recall): PASS >= 0.9, WARN >= 0.75, FAIL < 0.75
* plan.redundancy: PASS <= 0.05 dup rate, WARN <= 0.15, FAIL > 0.15
* model_calls_per_decision_p95: PASS <= 6, WARN <= 10, FAIL > 10 (layer-dependent)

---

## Capability output schemas (validation)

Add simple JSON-schema-like validators per capability (not full JSON Schema required):

* RESOLVE_SIGNAL: `{"response": dict|str}` or NOOP
* PLAN/L1: list of `{function_name, file, approach, dependencies}` etc.
* UNDER_SPEC: `{blocked: bool, constraints: dict, questions: list}`

Schema validation is a hard gate because it’s deterministic.

---

# 4) Trace/replay analysis tooling

## Trace index and aggregation

Scanning the filesystem for traces is fine initially, but add an index for speed and run grouping:

* `workspace/analysis/planner_traces/index.jsonl`

Each line:

```json
{
  "trace_id": "abc123",
  "timestamp": "...",
  "run_id": "...",
  "model_id": "...",
  "slice_id": "...",
  "layer": "l1",
  "capability": "PLAN",
  "decision_key": "l1:PLAN:LIB-01:0:9f12ab3c",
  "status": "OK"
}
```

This enables `list`, `filter`, `aggregate` without directory crawling.

## CLI commands (minimum useful set)

### Inspect

* `spec-manager planner trace list --run-id <run_id> [--slice LIB-01] [--capability PLAN]`
* `spec-manager planner trace show <trace_id> [--calls] [--artifacts]`

### Aggregate

* `spec-manager planner trace summarize-run --run-id <run_id>`

  * emits `planner_traces_summary.md` with tables:

    * calls per capability
    * failure clusters
    * top expensive decisions

### Replay

* `spec-manager planner trace replay <trace_id> [--model-config X] [--override overrides.yaml]`

  * re-runs the planner decision
  * writes a *new* trace directory
  * supports modified inputs via override file

### Diff

* `spec-manager planner trace diff <trace_id_a> <trace_id_b>`

  * compares:

    * decision outputs
    * tool/model call sequences
    * confidence, assumptions
  * emits:

    * `diff.md`
    * `diff.json` (machine-readable)

## Replay content requirements

To replay “without repo state,” `replay.json` must contain either:

A) a snapshot of the relevant files (preferred), or
B) enough extracted discovery artifacts to bypass filesystem reads.

Recommended approach: store a minimal **slice snapshot**:

* L1: all files under `slice_root` (text only)
* L2: all `*_manifest.yaml`, `wiring.yaml`, registries referenced
* L3: changed file content + diff hunks + quality receipts

Store as:

* `artifacts/snapshot.zip` (small, reproducible)
* `replay.json` references the zip and includes hashes

Replay runner:

1. materializes snapshot into a temp dir
2. sets `ctx.slice_root` / `ctx.workspace_root` to temp dir
3. calls `Planner.plan(request)`

## Visualization (low-effort, high leverage)

Generate one HTML per run:

* `reports/pdd/<run_id>/planner_timeline.html`

  * timeline view: one row per trace, sortable by slice/capability
  * heatmap cells: model_calls count, tool_calls count
  * click opens trace dir path

No complex frontend required; static HTML with embedded JSON is enough.

---

# 5) Output chaining strategy

## Rule: evaluate later layers on *actual upstream outputs*

Primary eval must run:

```
Phase 0 output → L1 (real) → propagate → L2 (real) → propagate → L3 (real)
```

So the harness should run `PddLifecycle.run()` and snapshot layer outputs.

## Snapshot points (for eval)

Add automatic snapshots in the eval harness (not necessarily in production):

* After Phase 0: already exists (`..._phase0_output/`)
* After L1 complete + propagation: snapshot workspace as `eval_snapshots/<run_id>/l1_workspace/`
* After L2: `.../l2_workspace/`
* After L3: `.../l3_workspace/`

These snapshots become:

* inputs for isolated L2/L3 planner testing
* reproducible artifacts for debugging

## Planner state between layers

Given planner is reconstructed per layer, state must persist via disk.

Recommended:

* Persist **planner-derived constraints** and **decision summaries** per slice:

```
workspace/analysis/planner_state/
  <run_id>/
    l1/
      <slice_id>.json
    l2/
      <slice_id>.json
    l3/
      <slice_id>.json
```

This is not required for correctness, but it enables:

* L2/L3 to “know what L1 decided” (if useful)
* evaluation attribution (which decision led to which downstream effect)

## Handling imperfect L1 outputs

Do both:

1. **Chained-real** (primary): L2/L3 evaluated on what L1 actually produced.
2. **Ideal-upstream** (diagnostic): L2/L3 evaluated on a frozen “ideal L1 output” fixture.

That gives you two signals:

* realism (how it behaves end-to-end)
* isolation (whether L2/L3 planner is good independent of upstream noise)

---

# 6) Multi-model compatibility

## Trace organization

Do **not** change the existing per-trace directory layout (backward compatibility). Instead, ensure each trace contains metadata:

* `request.json` includes `run_id`, `model_id`, `planner_version`
* index.jsonl records the same fields

For cross-model comparison, add an eval output directory per run:

```
reports/pdd/<run_id>/
  planner_scorecard.json
  planner_scorecard.md
  planner_decisions.jsonl
```

## Metrics useful for model comparison (not just debugging)

Keep these stable and comparable across runs:

* under_spec safety (false-unblock = 0 target)
* must-include coverage (PLAN)
* out-of-scope rate (PLAN)
* unsafe resolution rate (RESOLVE_SIGNAL/UNDER_SPEC)
* evidence-first rate
* tokens/decision and latency/decision
* iterations/slice and demotions/slice (secondary)

## Where to parameterize model switching

Parameterize at the **existing model config layer** (whatever your agent runner uses), not inside the planner eval.

Eval harness should accept:

* `--model-config <path-or-name>`
* optional `--shadow-model-config <path-or-name>`

Then:

* `PddLifecycle(..., config=...)` or `RunContext.config` carries model selection
* planner just uses the injected tools/agents as normal

---

# 7) Ground truth creation plan for treasury spec

## Recommended approach: “golden trace export + expert curation”

Pure hand-crafting is too slow; pure gold-run is too brittle. Do both:

### Step 1: Produce a “gold run” with a strong model

* Run `PddLifecycle.run()` on treasury spec with your best available model.
* Capture all planner traces.

### Step 2: Export a ground truth template from traces

CLI:

* `spec-manager eval planner export-gt --run-id <run_id> --out fixtures/..._planner_ground_truth.yaml`

This writes:

* one `case` per unique `decision_key`
* the observed output captured as a “candidate expected variant”
* marked `review_status: TODO`

### Step 3: Expert review pass

For each case:

* mark which atoms are truly must-include vs optional
* add must-not-include (scope errors you never want again)
* set should_block truth for under-spec events

### Step 4: Lock with drift protection

Store:

* `input_fingerprint` hashes so you can detect when the slice inputs changed and the GT needs refresh.

## What to ground-truth first (high ROI)

For treasury:

* **L1**

  * PLAN for each library slice: must-include function intentions for the most central functions (don’t try to enumerate all 38 initially)
  * UNDER_SPEC: which events must block vs can be resolved from spec comments/evidence
  * RESOLVE_SIGNAL: a curated set of common ambiguity signals

* **L2**

  * INTEGRATION_ANALYSIS: top dependencies and risks for 1–2 representative components
  * PLAN: wiring intentions for those components

* **L3**

  * PLAN: refactor intentions for `cq-audit_notification` slice (since you already exercised it)
  * UNDER_SPEC: refactor boundary questions that must block

---

# 8) Concrete implementation plan (files + dependencies)

## Phase A — make traces evaluable (must happen first)

1. **Add decision_key + richer request snapshot**

   * Modify planner invocation sites (Planner.plan or trace start point) to include:

     * capability, layer, run_id, slice_id, iteration
     * normalized inputs hash
     * computed `decision_key`

2. **Ensure every planner call persists a trace**

   * Hard guarantee: even exceptions write `request.json` + `decision.json` with `status=ERROR`.

3. **Enrich ModelCallRecord/ToolCallRecord (if not already)**

   * Add token counts, durations, model params
   * Prefer storing prompt/response as separate files referenced by hash (keeps jsonl small)

4. **Write trace index.jsonl**

   * Append one line per persisted trace with metadata (see index format above)

## Phase B — implement planner eval package

5. Create `spec_manager/evals/planner/ground_truth.py`

   * dataclasses + YAML loader
   * validation of GT schema

6. Create per-capability scorers

   * `resolve_signal_scorer.py`
   * `plan_scorer.py`
   * `under_spec_scorer.py`
   * `integration_scorer.py`
   * (gap scorer optional until GAP capability is fully used)

7. Create `trace_loader.py`

   * load traces by run_id / slice / capability
   * map trace → decision_key
   * expose model/tool call stats

8. Create `reporter.py`

   * emit:

     * `planner_decisions.jsonl` (one line per decision)
     * `planner_scorecard.json`
     * `planner_scorecard.md`
     * `planner_review.md` listing FAIL/WARN/NEEDS_REVIEW with trace paths

## Phase C — wire into eval harness

9. Add `spec_manager/evals/planner/harness.py`

   * in-situ mode:

     * use existing WorkspaceIntegration + fixtures
     * run `PddLifecycle.run()`
     * then score traces + write planner reports
   * slice mode:

     * run `PromotionLoop.run_slice()`, then score
   * replay mode:

     * load `replay.json`, re-run planner, diff

10. Add CLI commands

* `spec-manager eval planner ...`
* `spec-manager planner trace ...` (list/show/replay/diff/summarize-run)

## Phase D — ground truth workflow

11. Add `export_gt.py`

* reads traces for a run_id
* emits GT template YAML
* groups by decision_key
* includes observed outputs as candidate variants

## Phase E — optional but high leverage

12. Add override_provider hook to Planner (counterfactuals)
13. Add shadow mode runner (candidate vs oracle) for GT acceleration
14. Add HTML timeline generator

---

## Summary answers to your specific questions (Q1–Q7)

* **Q1**: Use a **new planner GT schema** keyed by deterministic `decision_key`. Compare with **constraint-based** evaluation (must/should/must-not) plus optional judge triage. Downstream success is only a soft signal.
* **Q2**: Primary eval is **in-situ via `PddLifecycle.run()`**. Add slice-level runs for speed and replay for debugging. Prevent cascade by scoring decisions independently and using **counterfactual overrides** for attribution. Shadow mode is useful for divergence triage and GT generation.
* **Q3**: Make a separate **PlannerScorecard**. Hard gates should be mechanical (trace integrity, schema validity, under-spec false-unblock=0). Soft signals cover accuracy/precision, epistemic hygiene rates, tool usage, efficiency, and convergence deltas.
* **Q4**: Build trace tooling around **list/show/summarize/replay/diff**, plus a run-level index. Replay needs snapshot artifacts (or discovery snapshots) to be independent of repo state. Add a simple timeline/heatmap HTML for quick inspection.
* **Q5**: Keep traces per call but tag with `model_id` and `run_id`. Emit machine-readable planner metrics per run for later model comparison. Parameterize model selection at the existing agent/model-config layer.
* **Q6**: Create GT via **gold run → export template → expert curation**, starting with UNDER_SPEC + RESOLVE_SIGNAL + core PLAN atoms, then expand.
* **Q7**: Output chaining is guaranteed by running `PddLifecycle.run()` and snapshotting layer outputs. For isolation, generate “ideal upstream output” fixtures and run L2/L3 against those in separate diagnostic runs. Persist planner state via disk summaries and constraints, not in-memory planner instances.
