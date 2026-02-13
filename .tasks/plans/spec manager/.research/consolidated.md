## Phase 0 Research Response (Feb 8 2026)

External research response to PHASE0_RESEARCH_PROMPT.md. This is the
analysis that led to the "routing-based restructuring" conclusion in
CONSOLIDATION_CONCLUSIONS.md.

---

## So what's the direct answer?

You *can* do summarizations, libraries, then refinement.
But the refinement algorithm (as currently described) fails because:

* It implicitly requires forbidden extraction (rewriting into structured shapes/algorithms),
* It has no legal routing unit under your no-chunk/no-overlap/no-retrieval constraints,
* It has no coverage ledger (so it can't converge or prove completeness),
* It doesn't embed the reimplementation test into routing decisions,
* It can't resolve cross-file references without pointer stubs,
* It has no operational stopping criterion.

If you redefine "spec refinement" as **routing-table construction + coverage closure + verbatim assembly**, then the pipeline becomes workable under your constraints.

## Why summaries + libraries are still useful (but only as routing hints)

They're useful for:

* proposing initial library buckets,
* prioritizing where to route a span (which library),
* suggesting which bucket is plausible (overview vs details vs analysis),
* spotting likely cross-file reference targets ("this file seems to define the ticket schema").

They are **not** allowed to replace the source text in the final structured spec.


## High-level finding

The current system’s *core control-flow and data-flow* are “compiler pipeline” shaped:

* **Code → mechanical extraction (AST/tokenize) → derived artifacts (reports/graphs) → LLM decisions**
* **One global pass P0→P10**, not an iterative per-slice promotion loop.

That shape contradicts the philosophy in **three structural ways** that are deeper than “uses Python AST”:

1. **Intermediate representations become the de facto spec** (because the system’s “understanding” lives in extracted artifacts), conflicting with **Code IS the Spec**.
2. **The system repeatedly “discovers” what to do** (scanning/parsing/routing) instead of having *process-triggered targets*, conflicting with **System always knows what to edit** and **Routing only at bottom layer**.
3. **The graph is downstream of code parsing** instead of being the primary object produced by LLM work and then verified, conflicting with **Graph operations** + **LLM does work during its task** + **No redundant mechanical steps**.

Everything else (missing demotion loop, duplicated analyzers, mechanical pinning, etc.) falls out of those three.

---

## The key point

**Nothing is inherently wrong with "summaries -> libraries -> refinement."**
What's wrong is that the described refinement step is **underspecified for your constraints**.

It's missing three required operators:

1. **A legal routing unit** (contiguous source spans, not paragraphs/windows/embeddings)
2. **A routing ledger** (coverage = termination)
3. **A routing-time invariant test** (mechanism -> invariant mapping without paraphrasing)

### What "spec refinement" must mean under your constraints

If extraction is prohibited and summaries are only for routing, then refinement is:

> **Build a routing table that maps raw source spans (file, start_line, end_line) into structured destinations (library + category + element ID), then assemble output by verbatim copy.**

No paraphrase. No decomposition into atoms. No semantic retrieval.

### Minimal artifacts (file I/O friendly)

* `summaries/FILE.md`
  High-level only; used for routing. No details.
* `libraries.yaml`
  Emergent library buckets + short descriptions (from summaries).
* `route_table.jsonl`
  The *only* "refinement" output that matters.
  Each entry is a move/copy instruction:

  ```json
  {
    "route_id": "R-000812",
    "src": {"file": "tickets.md", "start": 410, "end": 487},
    "dest": {"library": "LIB-03", "bucket": "DETAIL/ALGORITHM", "element_id": "ALG-LIB03-014"},
    "notes": "Ticket lifecycle procedure; contains one invariant-like sentence at lines 412-413"
  }
  ```
* `coverage_ledger.jsonl`

  ```json
  {"file":"tickets.md","start":1,"end":1200,"status":"fully_routed","exceptions":[]}
  ```
* Output assembly is deterministic: apply the routing table and copy line ranges.

This is "restructuring," not extraction.

---

## What's wrong with the spec refinement algorithm (as stated)

### 1) It treats "refinement" like rewriting, but refinement is only allowed to be routing

Your constraint ("no extraction; summaries only for routing") implies:

* **The structured output must be built from *verbatim source spans*** (line ranges / blocks), not from paraphrases.
* "Refine" cannot mean "rewrite the content into shapes/algorithms."
  It can only mean "move/duplicate the exact text into the right buckets and wrap it with IDs."

Most refinement descriptions accidentally slip into "rewrite and label," which is extraction-by-another-name (even if you call it restructuring): you're generating new atomic representations and inevitably dropping details.

**Failure mode:** refinement drift. After a couple iterations, the refined spec becomes a lossy reinterpretation rather than a reorganization of the original.

### 2) It has no routing unit definition that preserves context *without chunking*

Even if you forbid extraction, the system still needs a **unit of movement**. If you don't define it, you'll implicitly fall back to:

* paragraph units (you already said this loses context), or
* overlapping windows (you said this fails), or
* semantic retrieval (embeddings / TF-IDF; you said this fails).

So the algorithm is missing a legal routing unit.

**What you actually need** is a *routing unit that is a contiguous span in the original files*, chosen to preserve context *and* stable enough to cover everything.

If the refinement algorithm doesn't define a routing unit, it can't be implemented without violating one of your constraints.

### 3) It has no formal notion of completeness ("accounted for") in a routing-only world

"Refine until all details are accounted for" is undefined unless you have a ledger like:

* **Every source line is either routed to >=1 output element, or explicitly marked "ignored" with a reason.**

Without that, you can't know whether you're done, and the system will (a) stop early while missing content, or (b) loop forever.

This is exactly why Design #1's membership guarantee exists. You don't need its full complexity, but you **do** need the concept.

### 4) It doesn't solve the invariant trap, because summaries/libraries don't solve it

Your hardest problem is still: **invariants vs mechanisms**.

* Libraries answer "*what area is this about?*"
* Categories answer "*what kind of statement is this?*"

Those are orthogonal. Library discovery alone cannot reliably separate:

* "must emit `step_start` / `step_stop`" (mechanism detail)
  from
* "must be able to reconstruct what happened" (invariant)

If refinement only routes based on summaries, it will systematically misroute constraint-language mechanisms into Constraints.

#### The missing piece: routing-time classification that avoids the invariant trap (without extraction)

You can do this without extracting atoms by enforcing a *routing rule*:

##### Routing rule (mechanism vs invariant) in a routing-only system

When deciding whether a span goes to Constraints vs Details:

* If the span's meaning survives a complete reimplementation **and it's stated as a general guarantee/principle**, route the span (or the smallest contiguous lines that contain the guarantee verbatim) to **Constraints**.
* If it's a mechanism (locks, event names, field names, ordering steps), route to **Details** and optionally add a **derived-invariant stub** (a pointer, not a paraphrase).

In other words:

* Constraints bucket contains **verbatim invariant lines** (when present).
* Details bucket contains **everything else** (including most MUST language).
* "Implied invariants" are handled as **stubs** unless/until you explicitly allow inference.

This stays inside your "no extraction" constraint.

To fix it, the refinement step needs a **routing decision rule** that uses your reimplementation test *at routing time*.

### 5) Cross-file references break "summarize first" unless refinement can point into raw files

Because you can't load all files at once, and you can't use embeddings/TF-IDF to find referenced places later, the only stable solution is:

* When a cross-file reference is encountered, refinement must be able to record it as a **pointer to unresolved evidence** ("REF-STUB") and later resolve it to a **file + line range** once that file is processed.

If refinement can't create and resolve these pointer stubs, it will either:

* hallucinate the referenced content, or
* drop it, or
* incorrectly "summarize it away."

### 6) The recursion stopping rule is not operational

"Recurse until no more candidates" for sub-libraries is not measurable without:

* a coverage ledger, and
* a stability criterion ("library map stops changing while coverage stays 100%").

Otherwise recursion is either premature (misses structure) or endless.

---

## Target-state shift (what makes most AST modules disappear)

Treat **promotion** as a transaction that produces **two outputs at once**:

1. **Edited code** (Layer 1/2/3 files)
2. **Evidence artifacts** (language-agnostic metadata):

   * `GapInventory` (comment gaps, stub gaps, ambiguity gaps) as **spans**
   * `PinRegistry` updates (PinFunctions + PinProjections)
   * `AdjacencyGraph` updates (CALL / STORE_TOUCH / EVENT / REFERENCE edges)
   * file hashes to prove evidence matches current text

Then:

* Anything that “parses code to rediscover what the LLM just understood” becomes redundant.
* Compliance gates become **graph + evidence checks**, not syntax checks.
* Static “extractors” only exist as **optional on-demand LLM signal producers** (mainly for brownfield or missing evidence), not as routine mechanical steps.

---

## 2) EvidenceBundle schema

### Goals

* Single run-scoped, per-slice artifact that **eliminates redundant scanning** by making step outputs reusable.
* **Graph-first:** pins + edges are canonical; bundle is the mechanism to propose/apply and to snapshot.
* Incremental adoption: bundle can initially **reference existing artifacts** produced by current modules.

### Directory layout (recommended)

#### Evidence + ledgers (append-only, machine-first)

`/.pdd_runs/<run_id>/`

* `run_config.json` (inputs, thresholds, test commands, model IDs)
* `run_state.json` (active layer, SHAs, budgets consumed)
* `slices/<slice_id>/iter_###/bundle.json` (+ all step artifacts referenced by bundle)
* `demotions/`

  * `tickets/<ticket_id>.json`
  * `ledger.jsonl` (state transitions: emitted → applied → resolved)
* `ci/`

  * `l1/batches/<batch_id>.json` (candidate SHA, test results, promotion receipts)
  * `l2/batches/...`
  * `l3/batches/...`
* `approvals/`

  * `l1/iteration_#/decision.json` (+ referenced overview/alignment)
  * `l2/decision.json` (if enabled)
  * `l3/release_decision.json`

Inside each slice grandchild worktree, an iteration folder typically contains:

```text
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
          verify.notes.json
          blockers.json     (only if blocked)
          demotions.json
        iter_001/
          ...
```

`bundle.json` is the **index**; other files are step outputs. This keeps context small for LLM steps: pass paths, not huge inline content.

#### Human deliverables (stable paths, easy to read)

`/reports/pdd/<run_id>/`

* `component_manifest.json` (canonical run-scoped path consumed by `FinalReportGenerator`)
* `architecture_proposals.json` (canonical run-scoped path consumed by `FinalReportGenerator`)
* `final_report.md` (single consolidated run doc)
* `scorecard.json` (machine-readable)
* `scorecard.md` (human-readable)
* `architecture/`

  * `architecture_graph.json` (or snapshots per iteration)
  * `architecture_decisions.md` (if you record decisions separately)
* `quality/`

  * `review_findings.json` (aggregated)
  * `closure_receipts.json` (what passed, when)
* `alignment/`

  * `alignment_summary.json`
  * `alignment_findings.json`
* `traceability/` (post-MVP)

  * `traceability.csv/json`

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

## Target architecture

Treat the planner as a first‑class decision service with first‑class artifacts:

1. **Every planner call emits a trace** with a deterministic `decision_key` (stable across runs).
2. **Eval reads traces** (not in-memory objects) and produces:

   * per-decision verdicts + diagnostics
   * per-slice aggregates
   * per-run **PlannerScorecard**
3. **Ground truth is capability-specific** and **constraint-style** (acceptable regions), not brittle exact-match strings.
4. **Replay and diff are trace-native**: reproduce a single decision, override inputs/outputs, and compare before/after changes.

### Granularity recommendation

Start with **per-decision evaluation** but only ground-truth the **high-value decisions** first:

1. UNDER_SPEC (safety / block policy)
2. RESOLVE_SIGNAL (ambiguity hygiene)
3. PLAN (actionability + scope)
4. L2 integration risks (coarse)
5. GAP clustering last (hard to truth early)

#### What to ground-truth first (high ROI)

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

Then expand coverage.

## 2) Eval harness design

### Harness structure (recommended)

Create a dedicated planner eval package:

```
spec_manager/evals/planner/
  harness.py
  ground_truth.py
  scorers/
    base.py
    resolve_signal_scorer.py
    plan_scorer.py
    under_spec_scorer.py
    integration_scorer.py
    gap_scorer.py  # optional until GAP capability is fully used
  trace_loader.py
  reporter.py
  export_gt.py
```

And a CLI entry:

* `spec-manager eval planner --fixture chaotic_treasury_expanded --gt fixtures/..._planner_ground_truth.yaml --mode e2e`

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
* `reports/pdd/<run_id>/planner_scorecard.json` (new)
* `reports/pdd/<run_id>/planner_scorecard.md` (new)
* `reports/pdd/<run_id>/planner_decisions.jsonl` (new)

### B) Slice-level in-situ (fast iteration)

Runs `PromotionLoop.run_slice()` for a target slice/layer.

Use for tight debugging while still exercising real orchestration.

### C) Isolated replay (debugging + regression)

Re-runs a single planner decision using `replay.json` (and optional overrides).

Use for:

* reproducing a wrong decision quickly
* testing planner fixes without running the full pipeline
* creating minimal regression cases

#### Replay content requirements

To replay "without repo state," `replay.json` must contain either:

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

### D) Shadow mode (planner vs oracle)

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

# 5) Output chaining strategy

## Rule: evaluate later layers on *actual upstream outputs*

Primary eval must run:

```
Phase 0 output → L1 (real) → propagate → L2 (real) → propagate → L3 (real)
```

So the harness should run `PddLifecycle.run()` and snapshot layer outputs.

### Snapshot points (for eval)

Add automatic snapshots in the eval harness (not necessarily in production):

* After Phase 0: already exists (`..._phase0_output/`)
* After L1 complete + propagation: snapshot workspace as `eval_snapshots/<run_id>/l1_workspace/`
* After L2: `eval_snapshots/<run_id>/l2_workspace/`
* After L3: `eval_snapshots/<run_id>/l3_workspace/`

These snapshots become:

* inputs for isolated L2/L3 planner testing
* reproducible artifacts for debugging

### Planner state between layers

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

### Handling imperfect L1 outputs

Do both:

1. **Chained-real** (primary): L2/L3 evaluated on what L1 actually produced.
2. **Ideal-upstream** (diagnostic): L2/L3 evaluated on a frozen “ideal L1 output” fixture.

That gives you two signals:

* realism (how it behaves end-to-end)
* isolation (whether L2/L3 planner is good independent of upstream noise)

### Preventing cascading errors (without breaking realism)

You can’t eliminate cascade in in-situ runs; instead you **separate diagnosis from propagation**:

1. **Score every decision independently** (vs ground truth) even if downstream cascades.
2. Provide a targeted **counterfactual runner**:

   * pick a failing decision
   * override it with ground truth / oracle
   * re-run from the next step onward
   * measure whether the cascade disappears

#### Mechanical design for overrides

Add an optional override hook to Planner:

* `Planner(..., override_provider: Callable[[PlanningRequest], PlanningResult] | None = None)`

If override_provider returns non-None, planner returns it and still writes a trace marking `overridden=true`.

This enables:

* "force ground truth for decision X"
* "force oracle answer for under-spec"
* "replay with frozen model outputs"

# 6) Multi-model compatibility

## 3) Multi-model runner design

### 3.1 CLI shape

Add a dedicated command (keeps existing pipeline unchanged for normal use):

**Option A (recommended):**
`spec-manager eval multi-model --spec <path> --models opus,gpt5.3,glm --judge-model gpt-4.1 --quality --planner-eval --runs-per-model 1`

**Option B (alias):**
`spec-manager pdd run --multi-model opus,gpt5.3,glm ...`

The multi-model runner should:

1. Generate a `comparison_id`
2. For each model (and replicate):

   * Run the full pipeline in an isolated run_id
   * Preserve artifacts (snapshot)
   * Compute planner scorecard (optional)
   * Compute quality scorecard (optional)
3. Generate a comparison report.

---

### 3.2 Model configuration structure

Introduce a model profile that supports both “single model everywhere” and mixed-model routing:

```python
@dataclass
class ModelProfile:
    name: str                 # "opus", "gpt5.3", "glm"
    producer_model_id: str    # underlying provider id
    role_models: dict[str,str] = field(default_factory=dict)
    # role_models keys: "planner", "refinement", "review", "judge"
```

Rules:

* If `role_models` empty → use `producer_model_id` for all producer roles.
* Judges always use a separate `judge_model_id` (enforced).

This avoids hardcoding per-agent model names inside pipeline code.

---

### 3.3 Parameterizing “every LLM call” without rewriting everything

You need one consistent mechanism:

**Add a `model_profile` into RunContext/SliceContext.config**

* `RunContext.config["model_profile"] = ...`

**Upgrade `run_agent(...)`**

* Add optional `model_id` override:

  * `run_agent(agent_name, prompt, workspace, model_id=ctx.config["model_profile"].role_models.get(role, default))`
* Or add a new wrapper `run_role(role, prompt, ...)` that resolves agent template + model.

**Planner**

* Already has `model_id`; set it from `model_profile.role_models["planner"]`.

This is the minimal path to enabling multi-model without exploding agent-name variants.

---

### 3.4 Sequential vs concurrent

Default: **sequential** (deterministic, simplest, less isolation work).

Optional: `--concurrent N` uses process-level isolation. If concurrent:

* Each run must have an isolated workspace root OR isolated git worktree.
* Never share `reports/` global paths (fix required; see §6).

---

### 3.5 Run IDs and storage

Do not overload `.pdd_runs/{run_id}` with models inside unless you are ready to refactor many paths.

Use stable, unique run IDs:

* `run_id = f"{comparison_id}.{model}.{replicate_index:02d}"`

Artifacts remain where the pipeline expects:

* `.pdd_runs/{run_id}/...`
* `reports/pdd/{run_id}/...`

The comparison manifest ties them together.

---

## Where to parameterize model switching

Parameterize at the **existing model config layer** (whatever your agent runner uses), not inside the planner eval.

Eval harness should accept:

* `--model-config <path-or-name>`
* optional `--shadow-model-config <path-or-name>`

Then:

* `PddLifecycle(..., config=...)` or `RunContext.config` carries model selection
* planner just uses the injected tools/agents as normal

---

## 4) Cross-model comparison framework

### 4.1 Comparison inputs

For each run:

* `reports/pdd/{run_id}/scores.json` (RunReporter)
* `reports/pdd/{run_id}/planner_scorecard.json` (PlannerReporter; optional)
* `reports/pdd/{run_id}/quality_scorecard.json` (new; optional)
* `reports/pdd/{run_id}/architecture_digest.json` (new)
* `reports/pdd/{run_id}/code_digest.json` (new)
* `.pdd_runs/{run_id}/snapshot/manifest.json` (run identity + digest hash manifest)
* `.pdd_runs/{run_id}/snapshot/files/` (immutable snapshot of produced/touched files)

---

### 4.2 Apples-to-apples alignment

Models may produce different component sets. Avoid naive "component count diff".

Use a two-step **canonical responsibility alignment** (LLM-assisted, cached):

1. **Canonical responsibilities generation**

   * Input: spec summary + requirement list
   * Output: list of canonical responsibilities (5-20 items), each with a name + description
     Example: `["Audit log ingestion", "Notification routing", "Data persistence", ...]`

2. **Per-model mapping**

   * Input: canonical responsibilities + that model's architecture digest component list
   * Output: mapping responsibilities -> components (many-to-many allowed), with confidence

This yields comparison metrics:

* `responsibility_coverage_rate`
* `duplication_rate` (multiple components doing the same thing)
* `missing_responsibilities`

This approach is robust to "7 components vs 9 components".

---

### 4.3 Comparative judging (pairwise) for "which is better"

For N=3 models, pairwise is cheap enough.

**Pairwise Architecture Judge**
Prompt takes:

* Spec summary + canonical responsibilities
* Architecture digest A (blinded)
* Architecture digest B (blinded)

Output:

```json
{
  "winner":"A|B|TIE",
  "scores":{"A": {...}, "B": {...}},
  "key_differences":["..."],
  "risks":[...]
}
```

**Pairwise Code Judge**

* Uses code digests + sampled file excerpts from snapshots.

**Aggregation**

* For each dimension, compute:

  * win-count
  * average absolute scores (if you also do per-run absolute scoring)
* Optionally compute an Elo/Bradley-Terry rating later; not required for v1.

---

### 4.4 Minimum actionable comparison metrics

Start with this set (enough to drive routing decisions in Prompt 4):

**Correctness & safety**

* `gates.final_pass` (must)
* `ci.final_pass` (must)
* `spec_fidelity.coverage_estimate` (judge)

**Quality**

* `arch.quality_score`
* `code.quality_score`
* `arch.no_critical_risks` (soft until you hard-gate it)

**Efficiency**

* `pipeline.iteration_efficiency`
* `pipeline.total_demotions`
* Planner p50/p95 model calls (already in planner scorecard)

**Cost**

* Total planner tokens (from planner traces)
* Total pipeline LLM tokens (requires adding a global call ledger; see §8)

---

### 4.5 Reporting format

Generate all three:

1. `reports/pdd/comparisons/{comparison_id}/comparison_manifest.json`
   (comparison identity + spec hash + participating runs)

2. `reports/pdd/comparisons/{comparison_id}/comparison.json`
   (all raw metrics, mappings, pairwise judgments)

3. `reports/pdd/comparisons/{comparison_id}/comparison_report.md`
   Sections:

   * Summary table: models x (gates, quality, fidelity, efficiency, cost)
   * Architecture: topology stats + canonical responsibility coverage table
   * Code: sampled file scores + systemic risks
   * Pairwise judgments: short rationales
   * Recommendation block (optional, config-gated)

---

### 4.6 Non-determinism

Support `--runs-per-model K`:

* Report mean/std for key metrics.
* For pairwise comparisons, either compare "best run" per model or do pairwise on medians.

Do not require this for v1; implement K=1 first.

---

## 5) LLM Judge upgrades

### 5.1 Specialized judges, one shared runtime

Use **specialized judges** (different rubrics/output schemas) with one shared engine:

* `DetailMatchJudge` (existing Phase 0 semantic match)
* `ArchitectureQualityJudge`
* `CodeQualityJudge`
* `SpecFidelityJudge`
* `PairwiseArchitectureJudge`
* `PairwiseCodeJudge`

All share:

* `JudgeClient` (runs agent, retries, strict JSON extraction)
* Caching layer
* Prompt versioning

---

### 5.2 “Judge != producer” enforcement

At runtime:

* If `producer_model_id == judge_model_id`, fail fast unless `--allow-self-judge` explicitly set.

Also blind the candidate identity in pairwise prompts (A/B only).

---

### 5.3 Prompt template requirements (for all judges)

* Output contract first
* Input data second
* Output format last (strict JSON)
* Explicit anti-prescriptiveness: “valid alternatives are acceptable”
* Evidence requirement: “cite component/file identifiers from the digest”

---

### 5.4 Caching

Cache key:

* `judge_type`
* `judge_model_id`
* `prompt_version`
* `input_hash` (canonical JSON hash of digest + spec summary hash)

Cache location (run-scoped + global):

* Primary: `analysis/judge_cache/{judge_type}/{hash}.json`
* Optional per-run copy for provenance: `.pdd_runs/{run_id}/judges/{judge_type}/{hash}.json`

This ensures:

* No re-judging if artifacts unchanged.
* Cheap recomparison across models.

---

### 5.5 Meta-evaluation of the judge

Add a small, growing dataset:

* Human-rated architecture/code examples with expected dimension scores.
* Compute rank correlation and calibration drift over time.

This is not needed to ship v1, but you should lay the scaffolding:

* `refinement/evals/judges/meta_eval.py`
* `fixtures/judges/arch_cases/...`

---

## 6) Artifact preservation schema (immutability + comparison readiness)

### 6.1 Fix the current global-report collision

Right now `FinalReportGenerator` reads:

* `workspace_root/reports/component_manifest.json`
* `workspace_root/reports/architecture_proposals.json`

Those are overwritten by subsequent runs, which breaks multi-model comparisons.

**Change required: all run artifacts must be run-scoped.**

Write:

* `reports/pdd/{run_id}/component_manifest.json`
* `reports/pdd/{run_id}/architecture_proposals.json`

And update `FinalReportGenerator._architecture_topology()` to read from the run-scoped paths.

---

### 6.2 Minimal artifact pack per run

At run completion, create:

`.pdd_runs/{run_id}/snapshot/manifest.json`

```json
{
  "run_id":"...",
  "comparison_id":"...",          // optional
  "spec_hash":"...",
  "pipeline_git_sha":"...",
  "producer_model_id":"...",
  "judge_model_id":"...",
  "created_at":"...",
  "paths":{
    "run_dir":".pdd_runs/{run_id}/",
    "reports_dir":"reports/pdd/{run_id}/",
    "snapshot_files_dir":".pdd_runs/{run_id}/snapshot/files/"
  },
  "hashes":{
    "architecture_digest":"sha256...",
    "code_digest":"sha256...",
    "scorecards":"sha256..."
  }
}
```

`.pdd_runs/{run_id}/snapshot/files/` contains:

* All files created/modified by the run (preferred)
* or a full output subtree if “touched files” is not reliable yet
* `reports/pdd/{run_id}/` contents
* `analysis/planner_traces/` entries for that run, or a filtered copy (optional)

Immutability guard:

* Write a `snapshot_complete` marker
* Optionally chmod read-only (best-effort)

---

### 6.3 Comparison manifest

`reports/pdd/comparisons/{comparison_id}/comparison_manifest.json`

```json
{
  "comparison_id":"...",
  "spec":{"path":"...", "hash":"..."},
  "pipeline_git_sha":"...",
  "runs":[
    {"model":"opus","run_id":"...","snapshot_manifest":"..."},
    {"model":"gpt5.3","run_id":"...","snapshot_manifest":"..."}
  ]
}
```

---

## 7) Integration with existing scoring and reporting

### 7.1 Add a new QualityScorecard (recommended)

Do **not** mutate the existing RunReporter scorecard shape in v1.

Add:

* `QualityReporter`
* `QualityScorecard` + `QualityMetric`

Write to:

* `reports/pdd/{run_id}/quality_scorecard.json`
* `reports/pdd/{run_id}/quality_scorecard.md`
* plus `architecture_digest.json`, `code_digest.json`

### 7.2 Update FinalReportGenerator to include quality (optional)

If `quality_scorecard.json` exists, add sections:

* Architecture Quality (mechanical stats + judge dimensions + top risks)
* Code Quality (sampled file table + top risks)
* Spec Fidelity (coverage estimate + missing items)

### 7.3 Quality-weighted overall scoring (don’t change pass/fail semantics)

Keep:

* `Scorecard.overall_pass` = hard gates only

Add a **separate composite score** in quality scorecard or comparison report:

```text
overall_composite =
  0.45 * quality_overall +
  0.20 * spec_fidelity +
  0.20 * pipeline_efficiency +
  0.15 * planner_quality
```

This prevents “passes gates but terrible architecture” from looking identical in comparisons, without blocking pipeline.

### 7.4 PlannerEvalHarness integration

Multi-model runner can invoke:

* `PlannerEvalHarness.score_existing_traces(run_id)` per model run
  and store results in that run’s report directory (already does).

## 8) Implementation plan (concrete steps)

### Step 0 — Make reports run-scoped (required for multi-model)

Modify:

* `orchestration/final_report.py` to read run-scoped manifest/proposals.
  Modify writers (wherever manifests/proposals are currently written) to write under:
* `reports/pdd/{run_id}/...` (and optionally keep legacy global write behind a flag for compatibility).

### Step 1 — Add digests + snapshotting

Create:

* `orchestration/digests.py`

  * `build_architecture_digest(workspace_root, run_id) -> dict`
  * `build_code_digest(workspace_root, run_id) -> dict`
* `orchestration/snapshot.py`

  * `snapshot_run(workspace_root, run_id, include_files=True)`

Wire into end of `PddLifecycle.run()` behind config flags:

* `enable_snapshots`
* `enable_quality_scoring`

### Step 2 — Judge framework v2

Create package:

* `refinement/evals/judges/`

  * `client.py` (run_agent wrapper, retries, json extraction)
  * `cache.py`
  * `arch_quality.py`
  * `code_quality.py`
  * `spec_fidelity.py`
  * `pairwise.py`
* Add schemas:

  * `schemas/eval_arch_judge.py`
  * `schemas/eval_code_judge.py`
  * `schemas/eval_spec_fidelity_judge.py`
  * `schemas/eval_pairwise_judge.py`

### Step 3 — QualityReporter + scorecard

Create:

* `orchestration/quality_scoring.py`

  * `QualityMetric`, `QualityScorecard`
  * `ArchitectureQualityScorer` (mechanical + judge)
  * `CodeQualityScorer` (mechanical + sampled judge)
  * `SpecFidelityScorer`
  * `QualityReporter.write(...)`

### Step 4 — Model profile plumbing (minimal)

* Add `model_profile` to `PddLifecycle.__init__` and pass to:

  * `Planner(model_id=...)`
  * All `run_agent(...)` calls via `model_id=` override (requires updating `run_agent`)

If updating every callsite is too large initially:

* Add a single “current model id” global in workspace config that `run_agent` reads (still deterministic per run), but prefer explicit passing.

### Step 5 — Multi-model runner + comparison

Create:

* `orchestration/multi_model_runner.py`

  * Runs K models × R replicates
  * Calls lifecycle + optional planner eval + optional quality
  * Writes comparison manifest
* `orchestration/comparison.py`

  * Loads per-run digests/scorecards
  * Runs canonical responsibility alignment
  * Runs pairwise judges
  * Writes `comparison.json` + `comparison_report.md`

### Step 6 — Cost ledger (needed for serious model routing)

Add a global LLM call ledger (separate from planner traces):

* `analysis/llm_calls.jsonl` per run
  Record from `run_agent`:
* agent_name/role, model_id, tokens_in/out, duration_ms, timestamp, run_id, slice_id, layer

---

## 9) Design answers to the key questions (explicit)

### Q1 Architecture scoring: LLM vs mechanical?

Use **hybrid**:

* Mechanical graph metrics for coupling/graph health/completeness proxies
* LLM judge for cohesion/clarity/consistency/extensibility tradeoffs
  Mechanical runs first and also guides what the judge should focus on.

### Q1 Judge context: full spec or artifacts?

Judge gets:

* spec summary + requirements list (not full prose)
* architecture digest (component list + edges + coverage + L2 findings summary)
  This is sufficient and scalable.

### Q1 Multiple valid architectures?

Enforce “non-prescriptive” rubric:

* Don’t penalize style; penalize missing requirements, unclear boundaries, hidden coupling, fragile contracts.

### Q1 Where to integrate?

Create a **separate QualityScorecard** now; later promote a couple of metrics into RunReporter once stable.

### Q2 Code scoring: LLM vs mechanical?

Hybrid:

* Mechanical from L3 findings + text-level stats + churn
* LLM judge sampled files for real maintainability/readability/error handling signals

### Q2 Python-specific tools?

Not in core scorer (violates language-agnostic constraint). Allow optional plugin later, but keep the main system independent.

### Q2 Per-file vs aggregate?

Do both:

* per-file sampled scoring + systemic risks
* aggregate weighted score

### Q2 Hard gate?

Not initially. Add optional `code.no_critical_risks` gate once calibrated.

### Q3 Multi-model runner: CLI?

Yes. A dedicated `eval multi-model` is the cleanest and keeps normal pipeline flow unchanged.

### Q3 Storage layout?

Unique `run_id` per model replicate, standard run directories, plus a comparison manifest tying them together.

### Q3 Mixed-model runs?

Support via `ModelProfile.role_models` but keep default “single model everywhere” for v1.

### Q4 Cross-model comparison: LLM judge?

Yes, but only after deterministic alignment + digest generation, and cache aggressively.

### Q4 Output alignment?

Use canonical responsibility mapping (LLM once per comparison + per run mapping). Avoid brittle file/component name matching.

### Q4 Visualization/reporting?

Markdown + JSON. Dashboard can be built later from `comparison.json`.

### Q5 Judge architecture: generalized vs specialized?

Specialized judges with one shared runtime (client, cache, extraction).

### Q5 Judge model choice?

Configurable, but **must differ** from producer. Optionally ensemble for high-stakes comparisons.

### Q6 Artifact preservation?

Run-scoped snapshot manifest + digests + file snapshot. Fix global report collisions.

### Q7 Integration hierarchy?

* per-run: RunReporter + PlannerReporter + QualityReporter
* per-comparison: ComparisonRunner report
* later: feed into routing policy (Prompt 4) via `comparison.json` aggregates

# 4) Trace/replay analysis tooling

## Phase A — make traces evaluable (must happen first)

1. **Add decision_key + richer request snapshot**

   * Modify planner invocation sites (`Planner.plan` or trace start point) to include:

     * `capability`, `layer`, `run_id`, `slice_id`, `iteration`
     * normalized inputs hash
     * computed `decision_key`

2. **Ensure every planner call persists a trace**

   * Hard guarantee: even exceptions write `request.json` + `decision.json` with `status=ERROR`.

3. **Enrich `ModelCallRecord`/`ToolCallRecord` (if not already)**

   * Add token counts, durations, model params.
   * Prefer storing prompt/response as separate files referenced by hash (keeps jsonl small).

4. **Write `index.jsonl`**

   * Append one line per persisted trace with metadata (see index format below).

## Phase B — implement planner eval package

5. Create `spec_manager/evals/planner/ground_truth.py`

   * dataclasses + YAML loader
   * validation of GT schema

6. Create per-capability scorers

   * `resolve_signal_scorer.py`
   * `plan_scorer.py`
   * `under_spec_scorer.py`
   * `integration_scorer.py`
   * `gap_scorer.py` optional until GAP capability is fully used

7. Create `trace_loader.py`

   * load traces by run_id / slice / capability
   * map trace -> decision_key
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

## Summary answers to your specific questions (Q1–Q7)

* **Q1**: Use a **new planner GT schema** keyed by deterministic `decision_key`. Compare with **constraint-based** evaluation (must/should/must-not) plus optional judge triage. Downstream success is only a soft signal.
* **Q2**: Primary eval is **in-situ via `PddLifecycle.run()`**. Add slice-level runs for speed and replay for debugging. Prevent cascade by scoring decisions independently and using **counterfactual overrides** for attribution. Shadow mode is useful for divergence triage and GT generation.
* **Q3**: Make a separate **PlannerScorecard**. Hard gates should be mechanical (trace integrity, schema validity, under-spec false-unblock=0). Soft signals cover accuracy/precision, epistemic hygiene rates, tool usage, efficiency, and convergence deltas.
* **Q4**: Build trace tooling around **list/show/summarize/replay/diff**, plus a run-level index. Replay needs snapshot artifacts (or discovery snapshots) to be independent of repo state. Add a simple timeline/heatmap HTML for quick inspection.
* **Q5**: Keep traces per call but tag with `model_id` and `run_id`. Emit machine-readable planner metrics per run for later model comparison. Parameterize model selection at the existing agent/model-config layer.
* **Q6**: Create GT via **gold run → export template → expert curation**, starting with UNDER_SPEC + RESOLVE_SIGNAL + core PLAN atoms, then expand.
* **Q7**: Output chaining is guaranteed by running `PddLifecycle.run()` and snapshotting layer outputs. For isolation, generate “ideal upstream output” fixtures and run L2/L3 against those in separate diagnostic runs. Persist planner state via disk summaries and constraints, not in-memory planner instances.

## Deterministic decision identity

Add a stable identifier derived from the request and inputs:

* `decision_key = "{layer}:{capability}:{slice_id}:{iteration}:{input_hash[:8]}"`

Where:

* `iteration` comes from `PlanningContext.iteration` (or 0 if unset)
* `input_hash = sha256(canonical_json(inputs_subset))`
* `inputs_subset` is capability-specific (see below) so the key doesn’t drift when irrelevant metadata changes.

This is the join key between traces and ground truth.

## Trace index and aggregation

Do **not** change the existing per-trace directory layout (backward compatibility). Instead, ensure each trace contains metadata:

* `request.json` includes `capability`, `layer`, `run_id`, `slice_id`, `iteration`, normalized `input_hash`, computed `decision_key`, `model_id`, `planner_version`
* `index.jsonl` records the same fields

Scanning the filesystem for traces is fine initially, but add an index for speed and run grouping:

* `workspace/analysis/planner_traces/index.jsonl`

Each line:

```json
{
  "trace_id": "abc123",
  "timestamp": "...",
  "run_id": "...",
  "model_id": "...",
  "planner_version": "...",
  "slice_id": "...",
  "layer": "l1",
  "capability": "PLAN",
  "decision_key": "l1:PLAN:LIB-01:0:9f12ab3c",
  "status": "OK"
}
```

This enables `list`, `filter`, `aggregate` without directory crawling.

For cross-model comparison, add an eval output directory per run:

```text
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

### Visualization (low-effort, high leverage)

Generate one HTML per run:

* `reports/pdd/<run_id>/planner_timeline.html`

  * timeline view: one row per trace, sortable by slice/capability
  * heatmap cells: model_calls count, tool_calls count
  * click opens trace dir path

No complex frontend required; static HTML with embedded JSON is enough.

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

## 7) Ground truth creation plan for treasury spec

### Recommended approach: "golden trace export + expert curation"

Pure hand-crafting is too slow; pure gold-run is too brittle. Do both:

#### Step 1: Produce a "gold run" with a strong model

* Run `PddLifecycle.run()` on treasury spec with your best available model.
* Capture all planner traces.

#### Step 2: Export a ground truth template from traces

CLI:

* `spec-manager eval planner export-gt --run-id <run_id> --out fixtures/..._planner_ground_truth.yaml`

This writes:

* one `case` per unique `decision_key`
* the observed output captured as a "candidate expected variant"
* marked `review_status: TODO`

#### Step 3: Expert review pass

For each case:

* mark which atoms are truly must-include vs optional
* add must-not-include (scope errors you never want again)
* set should_block truth for under-spec events

#### Step 4: Lock with drift protection

Store:

* `input_fingerprint` hashes so you can detect when the slice inputs changed and the GT needs refresh.

### Ground truth file layout

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

### What “ground truth” should contain per capability

#### RESOLVE_SIGNAL

Ground truth is **question -> acceptable answer set**.

* `should_resolve: true/false`
* `answers_any_of`: list of acceptable canonical answers (short, declarative)
* Optional: `must_cite`: evidence section ids / constraints ids

**Correct means**:

* If `should_resolve=false`, planner returns `NOOP` (or `None`) and does not hallucinate.
* If `should_resolve=true`, answer matches one of the acceptable variants.

#### GAP

Ground truth is **gap atoms + optional clustering constraints**, not a full clustering tree.

* `must_find`: list of gap atoms (id + target + summary)
* `must_not_find`: known false positives
* Optional: cluster labels are soft (since clustering is subjective)

**Correct means**:

* High recall on `must_find`
* Low false positives on `must_not_find`

#### PLAN

Ground truth is **intentions as atoms** plus invariants.

Atoms differ by layer:

* L1 atoms: `{function_name, file, spec_comment_ref(optional)}`
* L2 atoms: `{component_id, target_files, pin_refs}`
* L3 atoms: `{file, function_span, smell_type, behavior_preservation_check}`

**Correct means**:

* Must-include intentions appear (order doesn't matter)
* No out-of-scope intentions
* Intentions are actionable (minimum required fields non-empty)

#### UNDER_SPEC

Ground truth is a **block/unblock truth table** per event.

Per event:

* `should_block: true/false`
* If `should_block=false`: required constraint keys or answer type
* If `should_block=true`: required question patterns (so the planner asks the right thing)

**Correct means**:

* No false unblocks (safety-critical)
* Questions are specific and tied to the slice context

#### INTEGRATION_ANALYSIS

Ground truth is **risk atoms** and **dependency edges** at coarse granularity.

* `must_include_risks`: e.g., "pin consumed by component X but not wired"
* `must_not_include_risks`: bogus dependencies

**Correct means**:

* Flags the real integration risks and dependencies
* Avoids inventing topology not present in manifests

## Deriving truth from downstream outcomes (should you?)

Use downstream outcomes only as **secondary signals**:

* A plan leading to success does **not** mean the plan was correct (implementation may compensate).
* A plan leading to failure does **not** mean the plan was wrong (downstream steps may fail independently).

So:

* Primary: decision-vs-ground-truth constraints
* Secondary: convergence/iteration efficiency, demotions, CI failures correlated to decisions

---

# 8) Concrete implementation plan (files + dependencies)

## Q1: What is a “gap” at L2?

**Recommended:** (d) a combination, but formalized as **Architecture Continuity Gaps**: *unconsumed promoted pins, missing/incorrect component wiring, missing integration points, and component-boundary violations*.

**Rationale:** L2 isn’t missing “function bodies”; it’s missing (or mis-shaping) the **graph assembly** that turns promoted atoms into coherent components (services/events/middleware). Gaps should be detectable as **graph incompleteness** (pins/edges/components) and **layer violations** (logic inlined in architecture).

**Implications:**

* L2 needs a **component manifest** (architecture skeleton) as its “spec”, otherwise “missing” is undefined.
* Gap exploration at L2 must look at **pins/edges/component graph**, not spec comments.

---

## Q4: Human Approval

**Recommended answer**

* **Keep L1 approval as mandatory** (it’s where under-spec decisions and intent alignment happen).
* Add an **optional L2 checkpoint** in interactive mode: approve **component manifest + topology + key tradeoffs** before starting L3 (because L3 “polishes” whatever architecture you froze).
* **Final signoff after L3** should exist as a lightweight “release approval” step (can auto-approve in auto/steering mode).

**Rationale (1–3 sentences)**
L1 approval prevents building the wrong thing; L2 checkpoint prevents polishing the wrong structure; L3 signoff gates release readiness and governance completeness.

**Design implications**

* Drives **Q7** (final consolidated report must support L2/L3 signoff).
* Drives **Q15** (governance checks must run on approval artifacts).
* Drives **Q5** (approval loops need a budget and must not induce infinite cycling).

---

## Q7: Human Review Document

**Recommended answer**

* Produce a **single consolidated run-level document** (separate from per-library overview.md) that references all artifacts.
* Contents (recommended minimum):

  * Executive summary (what was built, what changed, status)
  * Architecture topology summary (components, pins consumed, key flows)
  * Scorecard (per-layer + cross-layer)
  * Demotion summary (what got pushed down, why, final disposition)
  * Known risks / unresolved issues (if any)
  * Links/paths to evidence bundles and reports
* Include POWER alignment as:

  * **Embedded summary** (counts + high severity items)
  * References to the detailed alignment artifacts
* Treat the L1 approval doc as an **input checkpoint artifact**, not the final report.

**Rationale (1–3 sentences)**
Reviewers want one artifact that answers “is this shippable and why.” Per-library docs remain useful, but they’re not a run deliverable.

**Design implications**

* Drives **Q4** (L2/L3 signoffs become “approve sections” in this report).
* Drives **Q15** (governance checks must run on the final report content).
* Drives **Q6** (report must index the artifact set consistently).

---

## 3) Planner scorecard

## Keep it separate from the pipeline scorecard

Recommendation:

* **Separate `PlannerScorecard`** artifact for planner-specific metrics
* Optionally add **one** soft signal in the existing pipeline Scorecard:

  * `planner.overall` (summary only)

Reason: pipeline Scorecard is about end-to-end delivery; planner Scorecard is about decision quality and hygiene.

## Scoring Framework

## Scorecard model (recommended)

Each metric emits:

* `raw` (measured value)
* `score` (0–100 normalized)
* `status` (PASS/WARN/FAIL)
* `hard_gate` (bool)
* `evidence_refs` (paths into `.pdd_runs/<run_id>/...`)

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

### Capability output schemas (validation)

Add simple JSON-schema-like validators per capability (not full JSON Schema required):

* RESOLVE_SIGNAL: `{"response": dict|str}` or NOOP
* PLAN/L1: list of `{function_name, file, approach, dependencies}` etc.
* UNDER_SPEC: `{blocked: bool, constraints: dict, questions: list}`

Schema validation is a hard gate because it’s deterministic.

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

## 1) Architecture quality scoring design

### 1.1 Outputs to score

Define a **run-scoped Architecture Digest** as the single input to all architecture evaluation (mechanical + LLM), built deterministically from preserved artifacts:

`reports/pdd/{run_id}/architecture_digest.json`:

```json
{
  "run_id": "...",
  "spec": {"spec_id":"...", "spec_hash":"..."},
  "pipeline": {"git_sha":"...", "pipeline_version":"..."},
  "model": {"producer_model_id":"..."},
  "topology": {
    "components":[
      {
        "id":"comp.foo",
        "type":"service|lib|adapter|worker|ui|unknown",
        "summary":"1-3 sentences",
        "responsibilities":["..."],         // if available; else empty
        "owned_data":["..."],               // if available
        "public_contracts":[{"name":"...", "inputs":"...", "outputs":"..."}],
        "depends_on":["comp.bar","..."],
        "depended_by":["comp.baz","..."]
      }
    ],
    "edges":[{"from":"comp.foo","to":"comp.bar","kind":"call|event|data|import|unknown"}]
  },
  "coverage": {
    "requirements_total": 0,
    "requirements_mapped": 0,
    "unmapped_requirements": []
  },
  "l2_review": {
    "final_findings": {
      "BLOCKER": 0, "MAJOR": 0, "MINOR": 0
    }
  },
  "notes": {
    "architecture_proposals_path":"...",
    "component_manifest_path":"..."
  }
}
```

**Key rule:** this digest must be buildable **without language-specific parsing**. It should rely on:

* The L2 **component manifest** / topology artifacts (JSON).
* The L2 reviewer outputs already produced during the run (findings JSON).
* Phase 0 requirement list / spec summary already available in pipeline artifacts.

If some fields don’t exist today (e.g., requirement→component mapping), the digest should still be emitted with zeros/empties so downstream comparison remains stable.

---

### 1.2 Mechanical architecture metrics (cheap, deterministic)

Compute these from the digest topology graph (language-agnostic):

**Graph health**

* `arch.components_count`
* `arch.edges_count`
* `arch.edge_density = edges / max(1, n*(n-1))`
* `arch.cycles_present` (boolean) and `arch.cycles_count` (optional; use simple DFS cycle detection)
* `arch.scc_count` (optional; can be approximated or skipped initially)
* `arch.max_fan_out`, `arch.max_fan_in`
* `arch.avg_fan_out`, `arch.avg_fan_in`
* `arch.degree_concentration` (optional; e.g., Gini on degrees)

**Coupling proxies**

* `arch.coupling_risk = normalize(max_fan_out, edge_density, degree_concentration)`
* `arch.bottlenecks = top_k components by fan_in`

**Cohesion proxies (non-semantic)**

* `arch.orphan_components = components with fan_in==0 and fan_out==0` (flag, not always bad)
* `arch.utility_hub_ratio = components with very high fan_in and low responsibility clarity`
  (the “responsibility clarity” part is LLM-derived; mechanically you can still flag high fan_in hubs)

**Completeness proxies**

* `arch.requirement_mapping_rate = requirements_mapped / requirements_total` (if available)
* `arch.l2_findings_severity_weighted` from L2 final findings (already produced)

**Mechanical scoring normalization**
Keep it simple and monotonic:

* Convert each metric to a [0,1] “goodness” score with explicit caps.
* Example: `max_fan_out_score = clamp01(1 - (max_fan_out - 3)/10)` (3 is “fine”, 13 is “bad”).
* Cycles: `cycles_score = 1.0 if no cycles else 0.3` (until you have better nuance).

This gives you a **Mechanical Architecture Score**:

```text
arch.mechanical_score =
  0.30 * coupling_score +
  0.20 * graph_health_score +
  0.25 * completeness_proxy_score +
  0.25 * (1 - l2_finding_severity_score)
```

---

### 1.3 LLM architecture judge (expensive, semantic)

Use an LLM judge to score subjective dimensions while explicitly allowing multiple valid architectures.

**Dimensions (each 1–5 with anchors)**

* Cohesion
* Coupling & interface quality
* Completeness vs spec intent
* Consistency (pattern reuse where appropriate)
* Clarity (contracts and responsibilities are explicit)
* Extensibility (foreseeable changes don’t require cross-cutting edits)

**Judge input (minimum viable)**

* **Spec summary + top-level requirements list** (not the whole prose).
* The **architecture digest** (components + edges + coverage + L2 findings summary + mechanical stats summary).
* Optionally include **top 3 most central components** with any stored contract snippets if available.

Avoid sending full code trees.

**Judge output contract**
`schemas/eval_arch_judge.py` (new) with strict JSON:

```json
{
  "scores": {
    "cohesion": 4,
    "coupling": 3,
    "completeness": 5,
    "consistency": 4,
    "clarity": 3,
    "extensibility": 4
  },
  "overall": 4,
  "strengths": ["..."],
  "risks": [
    {"severity":"CRITICAL|MAJOR|MINOR", "component_id":"...", "evidence":"..."}
  ],
  "tradeoffs_noted": ["..."],
  "non_prescriptive_note": "..."
}
```

**Critical anti-bias requirements in the prompt**

* “Do not penalize alternative architectural styles if requirements are met and contracts are coherent.”
* “Only deduct points when you can point to concrete evidence in the digest.”
* “Focus on failure modes: missing requirements, unclear ownership, hidden coupling, circular dependencies, leaky abstractions.”

**Architecture quality score**
Normalize judge 1–5 → 0–1:
`arch.judge_score = (overall - 1) / 4`

**Final architecture quality**
Blend mechanical first, judge second:

```text
arch.quality_score = 0.35*arch.mechanical_score + 0.65*arch.judge_score
```

---

### 1.4 Thresholds and statuses

Architecture quality should be **soft-signal-only initially**:

* PASS: `arch.quality_score >= 0.80` and **no CRITICAL risks**
* WARN: `0.65 <= score < 0.80` or any MAJOR risks
* FAIL: `< 0.65` or any CRITICAL risks

Do **not** block pipeline initially. Add an optional hard gate later:

* `arch.no_critical_risks` (hard gate off by default)

---

### 1.5 Where it shows up

Create a dedicated **Quality Scorecard** (see §7). Then optionally “promote” a couple of summary metrics into the main RunReporter later without breaking current stability.

---

## 2) Code quality scoring design

### 2.1 Outputs to score

Define a **run-scoped Code Digest**:

`reports/pdd/{run_id}/code_digest.json`:

```json
{
  "run_id":"...",
  "spec":{"spec_id":"...", "spec_hash":"..."},
  "pipeline":{"git_sha":"..."},
  "model":{"producer_model_id":"..."},
  "codebase": {
    "files":[
      {"path":"src/x.py","loc":161,"sha256":"...","role_hint":"..."}
    ],
    "totals":{"files":0,"loc":0}
  },
  "l3_review": {
    "final_findings":{"BLOCKER":0,"MAJOR":0,"MINOR":0},
    "top_files":[{"path":"...","MAJOR":3,"MINOR":7}]
  },
  "ci": {
    "final_pass": true,
    "first_pass": false
  }
}
```

**Critical:** you need immutable access to “the produced code” per run. If the repo working tree is later changed by another run, the code digest must still be judgeable.

Minimum viable approach:

* At run end, save a **snapshot of touched/produced files** (or a full snapshot) under `.pdd_runs/{run_id}/snapshots/final_files/` and hash them.
* The code digest references those snapshot paths.

---

### 2.2 Mechanical code metrics (language-agnostic text-level)

No AST, no pylint/mypy/radon in the core scorer.

Compute:

* `code.loc_total`, `code.files_total`
* `code.file_size_outliers`: count of files with LOC > p95*X (simple)
* `code.churn` (already exists as `l3.refactor_churn`; reuse)
* `code.review_blockers`, `code.review_majors`, `code.review_minors` from L3 final reviewer findings (already produced)
* `code.issue_density = (5*BLOCKER + 2*MAJOR + 1*MINOR) / max(1, loc_total/1000)`

Optional but still language-agnostic:

* `code.duplication_ratio` via line-shingle hashing across snapshot files (pure text)
* `code.long_line_ratio` (pure text; line length > N)

Mechanical code score:

```text
code.mechanical_score =
  0.35 * (1 - normalized_issue_density) +
  0.25 * churn_score +
  0.20 * outlier_score +
  0.20 * (1 - duplication_score)
```

---

### 2.3 LLM code judge (sampled, per-file + aggregate)

Do **not** send the whole repo. Sample files deterministically:

**Sampling strategy**

1. Always include top K files by LOC (K=3).
2. Include top K files by MAJOR+BLOCKER findings (K=3).
3. If still under budget, include 2 random (seeded by run_id) to catch surprises.

**Judge rubric per file (1–5)**

* Readability (naming, local reasoning, structure)
* Maintainability (seams, separation, minimal duplication)
* Error handling & edge cases
* Consistency with project patterns (based on nearby files or conventions summary)
* API/contract clarity

**Judge rubric overall (1–5)**

* Cohesion across modules
* Appropriateness of abstractions
* Test strategy adequacy (based on presence/structure of tests + CI summary; not test execution)

**Output contract**

```json
{
  "files":[
    {"path":"...","scores":{"readability":4,"maintainability":3,"error_handling":4,"consistency":4,"contract_clarity":3},"overall":4,"notes":["..."],"risks":[...]}
  ],
  "overall": 4,
  "systemic_risks":[{"severity":"MAJOR","evidence":"..."}]
}
```

**Final code quality score**
`code.judge_score = (overall - 1)/4`
`code.quality_score = 0.40*mechanical + 0.60*judge`

---

### 2.4 Spec fidelity judge (separate from “quality”)

Correctness is partially covered by gates/CI, but you still need “did we actually implement the spec”.

Add a **Spec Fidelity Judge** that answers:

* Which requirements appear implemented (with pointers to files)?
* Which requirements are missing/partial?
* Are there invented behaviors not in spec?

This judge uses:

* Spec summary + requirement list
* Code digest (file list) + **small excerpts** (or docstrings/comments) from sampled files

Output:

* `spec_fidelity.coverage_estimate` (0–1)
* `missing_requirements` list
* `hallucinated_features` list

This becomes a score feeding model comparison and routing later.

---

### 2.5 Thresholds

As with architecture:

* PASS: `code.quality_score >= 0.80` and no CRITICAL risks
* WARN: `0.65–0.80` or MAJOR systemic risks
* FAIL: `<0.65` or CRITICAL

Soft signal only initially.

---

## Q8: Scoring Dimensions

**Recommended answer**

* Your proposed mechanical dimensions are the right backbone. Add a small set of operational and governance dimensions so scoring reflects real pipeline health:

  * **CI stability**: dirty→clean pass rate per layer (first attempt and eventual).
  * **Stagnation rate**: % slices hitting stagnation detection or max iterations.
  * **Governance compliance**: count of governance FAIL/WARN; missing receipts.
  * **Blocking under-spec rate**: number of BLOCKED events per slice (L1 heavy).
* **LLM-as-judge numeric ratings** (e.g., “architecture 1–10”) can exist only as **soft signals** and must never gate promotion. If you include them, record them as “perception metrics” with low weight.

**Rationale (1–3 sentences)**
You need scores that diagnose throughput killers (CI instability, stagnation) and safety failures (governance). Numeric LLM judgments are unstable and are best treated as advisory.

**Design implications**

* Drives **Q9** (hard vs soft thresholds).
* Drives **Q11** (score aggregation must include CI + governance receipts).
* Drives **Q5** (stagnation is both a metric and a termination control).

---

## Q9: Score Computation and Thresholds

**Recommended answer**

* Prefer **mechanical computation** from stored artifacts whenever feasible:

  * L1 comment/stub counts via compliance scanner (deterministic).
  * CI results from test runner outputs (deterministic).
  * Iteration counts, ticket counts from orchestration state (deterministic).
* For L2/L3, some raw inputs are produced by LLM gates/reviewers; that’s fine, but scoring should be computed mechanically over their outputs (no second “judge pass” to count things).
* Avoid LLM scoring for counts; treat Phase 0’s fuzzy matching lesson as a general rule: use LLMs to *find candidates*, not to be the source of truth for arithmetic.

### Metrics, computation, thresholds

### Hard gates (block merge/release)

| Metric                  | Layer    |                                             Computation | Pass threshold | Notes                                        |
| ----------------------- | -------- | ------------------------------------------------------: | -------------: | -------------------------------------------- |
| `gates.final_pass`      | L1/L2/L3 |      all promotion gates PASS on final slice completion |           100% | Already enforced by loop; recorded for audit |
| `ci.final_pass`         | L1/L2/L3 | dirty→clean promotion CI receipts PASS at required tier |           100% | Defines “verified”                           |
| `governance.no_fail`    | All      |                    governance findings with status FAIL |              0 | WARN allowed but scored                      |
| `alignment.no_high`     | All      |             HIGH severity drift/reward-hacking findings |              0 | Blocks release                               |
| `l3.no_behavior_change` | L3       |               diff-impact classifier != behavior_change |           PASS | Blocks release                               |

### Soft signals (diagnostics / quality indicators)

| Metric                          | Layer |                                            Raw computation | PASS / WARN / FAIL (default)         | Why it matters                |
| ------------------------------- | ----- | ---------------------------------------------------------: | ------------------------------------ | ----------------------------- |
| `l1.gap_closure`                | L1    |                  1 - (final_open_gaps / initial_open_gaps) | PASS=1.0, WARN≥0.99, FAIL<0.99       | Detects dropped spec work     |
| `l1.gate_first_attempt_rate`    | L1    | slices passing all gates on first promote attempt / slices | PASS≥0.6, WARN≥0.4                   | Planning quality              |
| `l2.pin_consumption_rate`       | L2    |                     consumed_pins / promoted_pins_in_scope | PASS=1.0, WARN≥0.95                  | Architecture completeness     |
| `l2.component_coverage`         | L2    |               implemented_components / manifest_components | PASS=1.0, WARN≥0.98                  | Manifest realization          |
| `l2.gate_first_attempt_rate`    | L2    |                                first-attempt pass / slices | PASS≥0.5, WARN≥0.3                   | Architecture iteration health |
| `l3.reviewer_first_pass_rate`   | L3    |        files passing all reviewers on first review / files | PASS≥0.4, WARN≥0.2                   | Clean-code efficiency         |
| `l3.refactor_churn`             | L3    |                 changed_LOC / total_LOC (in touched files) | PASS≤0.15, WARN≤0.30                 | Risk proxy                    |
| `pipeline.total_demotions`      | All   |                                      total tickets emitted | PASS≤(slices*0.5), WARN≤(slices*1.0) | Stability signal              |
| `pipeline.iteration_efficiency` | All   |                            total_iterations / total_slices | PASS≤3, WARN≤6                       | Throughput signal             |
| `pipeline.ci_first_pass_rate`   | All   |       successful dirty→clean on first attempt / promotions | PASS≥0.8, WARN≥0.6                   | CI health                     |
| `pipeline.stagnation_rate`      | All   |                            stagnated_slices / total_slices | PASS=0, WARN≤0.05                    | Detects “stuck” behavior      |

**Threshold policy**

* Hard gates: always block.
* Soft signals: warnings by default; optionally block in strict CI mode.

**Where to compute**

* Compute in a `RunReporter` at end of `pdd_lifecycle.run()` (and optionally after each layer) by aggregating EvidenceBundles + CI receipts + demotion ledger.

**Rationale (1–3 sentences)**
Hard gating should be based on deterministic or already-required pass/fail receipts. Scores should help interpret efficiency and risk, not introduce a second, noisy acceptance system.

**Design implications**

* Drives **Q11** (run emits raw receipts; separate report computes scores).
* Drives **Q12** (tests define CI pass receipts).
* Drives **Q10** (ground truth is optional for eval, not required for production).

---

## Q10: Ground Truth for L2/L3

### 1) Ground truth schema

**Recommended answer**

* **Production:** do not require a fixed “ground truth architecture” beyond what you already have:

  * component manifest + drift gate + pin consumption + boundary gates.
* **Evaluation mode:** optionally support:

  * “expected manifest constraints” (e.g., required components, forbidden edges),
  * or a “reference implementation” comparison (diff-based or behavior-based).
* Keep these as **eval-only**. Production should rely on gate convergence + CI.

### Core design choice

Planner decisions are non-deterministic, so ground truth cannot be “exact JSON match.” Use **constraint-based ground truth**:

* **Hard invariants** (must be true)
* **Expected atoms** (things that should appear, order-insensitive)
* **Forbidden atoms** (must not appear; catches false positives/out-of-scope)
* **Allowed variants** (multiple acceptable answer sets)
* **Process expectations** (tool usage / evidence-first) as optional constraints

This makes “correctness” comparable while allowing multiple valid plans.

**Rationale (1–3 sentences)**
Architecture and cleanliness are context-dependent; enforcing invariants is more robust than asserting a single intended structure. Eval can use stronger oracles without burdening production.

**Design implications**

* Drives **Q8/Q9** (some scores are best-effort indicators, not hard truth).
* Drives **Q6** (store manifest/topology snapshots to enable eval comparisons).

---

## Q11: Production Scores vs Eval Scores

**Recommended answer**

* **Production:** gates + CI receipts decide pass/fail/demotion (already true).
* **Scoring/reporting:** implement a **RunReporter** that reads:

  * EvidenceBundles, demotion ledger, CI receipts, and approval artifacts
  * and writes `scores.json` + `final_report.md`.
* `pdd_lifecycle.run()` should write:

  1. raw receipts and state (for machine use), and
  2. the computed scorecard (for humans/CI dashboards).
     EvalRunner can remain separate and additionally compute benchmark metrics.

**Rationale (1–3 sentences)**
Keep decision logic simple and auditable. Reporting is a pure aggregation step and should not affect control flow.

**Design implications**

* Drives **Q6/Q7** (final deliverables).
* Drives **Q9** (mechanical aggregation is feasible if receipts are persisted).

---

## Q7: What is a “gap” at L3?

**Recommended:** (d) a combination, formalized as **Quality Closure Gaps**:

* (b) unreviewed units, and
* (a)+(c) open reviewer findings not yet cleared.

**Rationale:** L3 convergence is “all required reviews pass and nothing remains flagged”. A “gap” is any outstanding finding or any unit that still lacks a PASS receipt.

**Implications:**

* Gap exploration at L3 is “run reviewers → collect findings → produce gap list”.
* Termination can remain `open_gaps == 0` if your gap report includes findings.

---

## Q8: What does “implement” mean at L3?

**Recommended:** Refactor-only patching driven by findings, with an explicit **Diff-Impact Classifier** gate; if the diff is logic-affecting, emit **DemotionTicket → L1**.

**Rationale:** L3 is about code quality, not behavior change. The process must mechanically prevent “cleanup” from becoming silent feature changes.

**Implications:**

* L3 needs:

  1. a refactor agent (“clean-code refactorer”),
  2. a behavior-preservation verifier (diff-impact classifier + tests), and
  3. a demotion rule: “logic touched” → L1.

---

## Q9: What compliance gates apply at L3?

**Recommended:** Keep your 4 reviewers, but treat them as **dimensions** that are satisfied by a language-agnostic pattern pack (and optional strategy packs). Add explicit **NO_LOGIC_CHANGE** + **DRIFT_PASS** gates.

**Rationale:** “Clarity/completeness/consistency/correctness” is a good orthogonal decomposition if you define them in language-agnostic terms and keep detection cues separate.

**Implications:**

* L3 gates must be enforceable without parsing: rely on reviewer judgments + diff classification + tests.

**L3 gate set (final):**

1. **ALL_QUALITY_REVIEWERS_PASS** *(BLOCKER)*
   No remaining findings above configured thresholds.
2. **NO_LOGIC_CHANGE** *(BLOCKER → demote to L1 if violated)*
   Diff-impact classifier says behavior is preserved; otherwise demote to L1.
3. **NO_ARCH_BOUNDARY_VIOLATIONS** *(MAJOR → demote to L2)*
   If refactor breaks component boundaries or wiring expectations, demote to L2.
4. **DRIFT_PASS** *(MAJOR)*
   No unplanned functionality added during refactor (plan/design conformance).
5. **TESTS_PASS** *(BLOCKER, enforced via INTEGRATE/CI and recorded as a gate outcome)*
   Regression suite passes (or layer-appropriate verification command).

If you implement only one structural change beyond VerifyStep, make **GapExplorationStep layer-aware** so termination (`open_gaps == 0`) remains valid at L2/L3 by defining “gaps” as the open review/graph findings at those layers.

---

## Q10: What does VerifyStep do at L3?

**Recommended:** VerifyStep at L3 is **post-integration closure**:

* re-run reviewers (or validate their receipts),
* run diff-impact classification (if not already),
* confirm tests passed in clean worktree,
* enforce governance (receipts, decision injection).

**Rationale:** L3 Verify is the final “nothing slipped through” check after merge.

**Implications:**

* VerifyStep should fail closed on missing receipts or suspicious injection patterns (even if tests pass).

## Q11: What are L3 slices?

**Recommended:** Start with (a) one slice per file (your current approach), but define the *true unit of work* as **finding clusters** (function-level anchors) inside that slice.

**Rationale:** File slices are operationally simple; function-level slices are better for parallelism but require more scheduling/anchoring infrastructure. You can get 80% of the benefit by keeping file slices and clustering findings by function/span internally.

**Implications:**

* Reviewers must emit findings with **anchors** (symbol + span) so the refactor agent edits only targeted regions.

## Q12: How do L3 findings become DemotionTickets and flow down?

**Recommended:** Use a **two-stage classification**:

1. classify finding as *cosmetic vs structural vs behavioral*, then
2. decide the lowest layer that can legally resolve it.

**Rationale:** This avoids language-dependent heuristics and makes “demote all the way down” systematic.

**Implications:**

* `demotion/triage.py` should not depend on language; it should depend on:

  * *what kind of change is required* (behavior vs wiring vs refactor),
  * *scope* (local vs cross-component),
  * *layer legality* (L3 cannot change behavior; L2 cannot add business logic).

### Flow-down behavior

* Tickets are written to a persistent queue (e.g., `analysis/demotion/open.json`) and applied by `DemotionManager`.
* Lower layer GapExploration must incorporate “open tickets in scope” as gaps:

  * L2 tickets become L2 gaps in the relevant component slice(s)
  * L1 tickets become L1 gaps routed to the correct library/function via existing routing summaries

This is how L2/L3 “know what to edit” without routing: **the ticket is the route**.

### Conversion: Finding -> DemotionTicket

A deterministic triage function should route using `required_change_type` + `scope`.

**Triage rules (minimal and sufficient):**

1. If `required_change_type == behavior_change` -> `target_layer = L1`
2. Else if `category == architecture` OR scope is cross-component/topology -> `target_layer = L2`
3. Else -> fix-in-place at L3 and no demotion ticket

**Special forced demotions:**

* `INLINE_LOGIC_AT_ARCH` (or L2 `NO_INLINED_ATOM_LOGIC`) -> `target_layer = L1`
* L3 diff-impact classifier result `"logic-affecting"` -> `target_layer = L1`

Tickets should include precise anchors so L1 routing is deterministic:

* failing files
* `component_id` (if known)
* pin ids (if known)
* symbol/span anchors

### 1) Canonical Finding schema (used everywhere)

Every reviewer (L2/L3 and verification) emits findings in a single format:

* `dimension`: what is being evaluated (e.g., `ARCH_BOUNDARY`, `PIN_COVERAGE`, `CLARITY`, `CORRECTNESS`, `DRIFT`, `GOVERNANCE`)
* `category`: `style | maintainability | architecture | logic | drift | governance`
* `severity`: `BLOCKER | MAJOR | MINOR`
* `location`: `{file, symbol?, start_line?, end_line?}`
* `evidence`: short snippet or description
* `required_change_type`: `refactor_only | wiring_only | behavior_change | spec_change`
* `suggested_fix`: minimal
* `confidence`: 0–1
* `tags`: optional pattern IDs (`INLINE_LOGIC_AT_ARCH`, `CORRECTNESS`, `LOGIC_BUG`, `SPEC_UNDER_SPEC`, etc.)

This is language-agnostic because it never requires “imports”, “AST nodes”, etc.

**Canonical category routing defaults and tag conventions:**

| Finding category            | Meaning (language-agnostic)                              | Default action | Ticket target             |
| --------------------------- | -------------------------------------------------------- | -------------: | ------------------------- |
| `style`                     | naming/format/doc clarity without structural change      |      fix in L3 | none                      |
| `maintainability`           | complexity/duplication/structure inside a unit           |      fix in L3 | none                      |
| `architecture`              | boundary violations, wrong dependencies, wiring/topology |         demote | L2                        |
| `architecture` + `INLINE_LOGIC_AT_ARCH` tag | business logic located in architecture layer             |         demote | L1                        |
| `logic` + (`CORRECTNESS` or `LOGIC_BUG` tags) | behavior wrong, edge case missing, invariant broken      |         demote | L1                        |
| `drift`                     | extra/missing/mismatched vs plan/spec                    |         demote | L1 or L2 (based on scope) |
| `governance`                | missing receipts / decision injection                    |          block | same-layer remediation    |

## Q2: What does “implement” mean at L2?

**Recommended:** (a) + (b), with a hard constraint: **implementation at L2 = assemble + glue**, never new business logic.

**Rationale:** L2 “implementation” is the creation/modification of **composition surfaces**: handlers, service entrypoints, middleware chains, event routing, adapters, and orchestration code that **calls pins**. If missing behavior requires new logic, that is **not an L2 implement task**; it becomes a demotion to L1.

**Implications:**

* You need an L2 implementor agent (“architectural assembler”) that is explicitly scoped to: *wiring, dispatch, lifecycle, IO boundaries, config injection*.
* Any “logic-shaped” diff discovered during L2 implementation should automatically emit a **DemotionTicket → L1** (new atom).

---

## Q2: Which modules should become LLM-driven, and how?

### “Must be LLM” (real pattern recognition)

These are inherently semantic and should not be reconstructed mechanically:

1. **`planning/reverser.py`**

   * Input: `(file_path, line_start, line_end)` spans (usually PinFunctions or introduced architecture blocks).
   * Output: intent summary / pseudocode comments for review and constraint-surfacing.
   * No parsing beyond span selection.

2. **`branches/collapse.py` (brownfield ingestion)**

   * Input: repository snapshot (files + spans from `code_analysis`).
   * Output: routing plan:

     * which spans become PinFunctions
     * which files/blocks become slices/architecture nodes
     * initial Adjacency edges (CALL/STORE/EVENT) at coarse granularity
     * “ambiguity questions” that require human constraints

3. **Adjacency signal production (if evidence is missing/stale)**

   * Not as “extractors that run all the time”.
   * As an **on-demand LLM query**: “produce CALL/STORE/EVENT edges for these spans”.

### How to implement without turning everything into bespoke agents

Do **not** create 25 new agents. Create **one** language-agnostic interface that supports **facets**.

A practical shape:

* `analyze_source()` stays as-is (functions + comments).
* Add a second API: **signal/evidence inference** returning dynamic dicts:

```python
def infer_code_signals(
    *,
    file_path: str,
    source_text: str,
    spans: list[dict],           # optional: function/block spans
    requested: set[str],         # e.g. {"gaps", "call_edges", "store_edges", "event_edges", "arch_blocks"}
) -> dict[str, Any]:
    ...
```

* In production: implemented by LLM (cached by `(file_hash, requested)`).
* In tests: implemented by your existing AST-based test double (or fixtures), so the 2300 tests stay stable.

This gives you **Option B** capability without multiplying agents, and without rigid types.

## Q13: Reviewer design (language-agnostic core + evolutionary strategies)

**Recommended:** (c) **LLM judgment + pattern librarian**, backed by a **natural-language core rule catalog**.

**Rationale:** Pure “no rules” LLM judging drifts; rigid rule catalogs become language-bound. The stable middle is: language-agnostic principles as canonical patterns, plus optional strategy packs for language/framework cues.

**Implications:**

* Your pattern librarian becomes the mechanism for progressive automation.

### 4) Evolution mechanism (how strategies get created)

* Any repeated human-approved fix or repeated recurring finding produces a **StrategyCandidate** containing:

  * “signal patterns” observed in the codebase
  * approved remediation
  * exceptions/false positives
* Pattern librarian curates StrategyCandidates into strategy packs scoped by:

  * language (if relevant)
  * framework (if relevant)
  * repository/module (if relevant)
* Core reviewers always run with the core principles; strategy packs are optional overlays that can be enabled/disabled without changing the core review contract.

### Pattern library model

A “pattern” is a rule stated as:

* **Principle (core, language-agnostic):** what must be true.
* **Signals (optional strategies):** language/framework cues that help detect it.
* **Fix guidance:** minimal remediation suggestions.

Example:

* Principle: “Do not silently ignore errors.”
* Strategy signals:

  * Python: `except: pass`
  * JS: `catch(e) {}` without rethrow/log
  * etc.

The **core review pack** is only principles. Strategy packs are additive.

## 3) Review packs per layer

### L2 ReviewPack (recommended)

1. **Architecture Boundary Reviewer** (principles: responsibilities, separation, dependency direction)
2. **Topology/Connectivity Reviewer** (principles: no orphans, handlers exist, flows complete)
3. **Pin/Edge Conformance Reviewer** (principles: pins consumed, edges realized)
4. **Architecture Drift Reviewer** (manifest vs reality)
5. **Governance/Oversight Reviewer** (receipts, injection patterns)

### L3 ReviewPack (recommended)

1. **Clarity Reviewer** (readability, naming intent, cognitive load)
2. **Consistency Reviewer** (API consistency, convention uniformity)
3. **Maintainability Reviewer** (structure, complexity, duplication, decomposition)
4. **Correctness/Safety Reviewer** (edge cases, error paths, invariants)
5. **Drift Reviewer** (no new features; plan/design conformance)
6. **Diff-Impact Classifier** *(gate, not just review)*

Your existing 4 reviewers map cleanly to (1)(2)(3)(4). Add (5)(6) as explicit gates.

---

## Q14: Review loop integration with PromotionLoop

**Recommended:** (d) combine:

* (b) findings become new gaps (PromotionLoop naturally re-iterates), and
* PROMOTE/VERIFY enforce “all-pass” gates.

**Rationale:** You already have an outer convergence loop. Re-implementing an inner loop duplicates orchestration and complicates evidence accounting.

**Implications:**

* L2/L3 GapExploration must produce “open gaps” from reviews.
* PROMOTE and/or VERIFY must re-run the relevant reviews as the **gate**.

---

## Q15: Drift review vs rule-based review

**Recommended:** Run both at every layer; define an explicit “spec artifact” per layer.

**Rationale:** Rule-based review prevents “bad shape”. Drift review prevents “wrong thing”.

**Implications (layer specs):**

* **L1 drift spec:** spec comments + constraints + under-spec decisions → implementation.
* **L2 drift spec:** **Component Manifest** + pin registry + declared interactions → realized wiring/handlers/topology.
* **L3 drift spec:** approved L2 topology/contracts + “no new behavior” constraint → refactored code.

---

## Q6: How does L2 architectural refinement become language-agnostic reviews?

**Recommended:** Use **LLM-as-judge + natural-language rule catalog** as the core, and treat any language/framework heuristics as **evolutionary strategies**.

**Rationale:** Architecture review can be expressed in terms of *boundaries, responsibilities, dependencies, flows, and contracts* without referencing “imports”, “decorators”, or framework wiring. Syntax cues are optional strategies to improve detection, not required for correctness.

**Implications:**

* Define architecture rules as **principles + expected evidence** (see “Reviewer design” below).
* Add a “strategy pack” layer that can contain Python/Django/FastAPI/etc heuristics, but the core review remains usable without them.

---

## Q5: What are L2 slices?

**Recommended:** (b) one slice per **architectural component** (service/event/middleware), with a bootstrap fallback to the current per-library wrapper.

**Rationale:** L2 work is not “per library”; it is “per component topology unit”. Component slicing maximizes parallelism and makes gaps/action targets unambiguous.

**Implications:**

* Architectural refinement must output a **Component Manifest** that becomes the canonical slice map:

  * `component_id`
  * owned entrypoints
  * pins consumed
  * upstream/downstream interactions
  * files that implement the component (or generation targets)

---

## Q5: How `code_analysis.py` should evolve

### Don’t grow it into a mega-schema of language constructs

You already hit the failure mode: rigid dataclasses force language-specific fields.

### Keep `SourceAnalysis` minimal + add dynamic "facets"

Best target shape:

* Keep typed:

  * spans of "routines/blocks" (`RawFunctionInfo`, but conceptually "declared units")
  * comment spans (`RawCommentInfo`)
  * stub detection (already present)

* Add a **dynamic** container for everything else:

  * `analysis.facets: dict[str, Any]` (optional)
  * or a separate `infer_code_signals()` function returning a dict

Key: facets should be **request-driven** (on-demand), cached, and test-doubled.

Examples of facet outputs (all span-based, no language constructs required):

* `arch_blocks`: list of `{id, line_start, line_end, kind}`
* `edges`: list of `{signal_type, src_id, dst_id, confidence, rationale_span?}`
* `stores`: list of `{store_id, touched_by:[block_id...]}`

### Single call vs multiple calls

Prefer a single "requested facets" call so one read produces multiple outputs when needed, but still avoid "always compute everything."

## Q4: "Language-agnostic" for graph extractors

### Target meaning

“Language-agnostic” does **not** mean “rebuild AST walking for every language.”

It means:

* Graph edges are **evidence produced by an understanding step** (LLM during promotion / ingestion),
* stored and consumed as **graph operations** afterward.

### What to do with the three extractors

* In the mature system: **do not keep three always-on extractors**.
* Replace with **one** concept:

  * `infer_adjacency_signals(requested={CALL, STORE_TOUCH, EVENT, REFERENCE}, spans=...)`
* Keep the old modules only as thin wrappers while migrating:

  * `call_graph.py` becomes: “return CALL edges from evidence; if missing, request signals.”

This avoids:

* duplicated LLM reads (three passes)
* rigid per-signal code paths
* reintroducing “parsing pipeline” thinking

---

## Q3: What compliance gates apply at L2?

**Recommended:** Keep the two you already named as *hard blockers*, add a small set of **graph-level completeness** gates.

**Rationale:** L2 gates should enforce: (1) **layer purity** (no atom logic inline), and (2) **assembly completeness** (pins/edges/components are coherently composed). Do not use language syntax rules; enforce at the level of responsibilities and connections.

**Implications:**

* Gates should be expressible over a **component graph + pin registry + minimal code evidence** (snippets), not AST parsing.

### L2 gates (architecture) - final set:

1. **NO_INLINED_ATOM_LOGIC** *(BLOCKER)*
   Architectural code must be orchestration; business logic must be in L1 atoms.
2. **FUNCTION_RECOMPOSITION** *(BLOCKER)*
   Architectural entrypoints recombine atoms via pins; no monolithic “do everything here”.
3. **PIN_CONSUMPTION_COVERAGE** *(MAJOR)*
   Every promoted pin in-scope is either referenced by some component or explicitly justified as unused.
4. **EDGE_REALIZATION** *(MAJOR)*
   Declared cross-atom edges (or intended interactions) are realized as actual component-level wiring (handlers/routes).
5. **NO_ORPHAN_COMPONENTS** *(MAJOR)*
   Every component has at least one reachable entrypoint and/or is referenced by the runtime topology.
6. **EVENT_HANDLER_COVERAGE** *(MAJOR, conditional)*
   Every declared event has ≥1 consumer or is explicitly marked as “external-only”.
7. **CONFIG_EXTERNALIZATION** *(MINOR/MAJOR)*
   Environment-specific values are injected, not hardcoded (severity policy-driven).
8. **ARCH_DRIFT_PASS** *(MAJOR)*
   L2 artifact matches the current architecture manifest (see Q15).

### Additional evidence gates carried forward from the prior design

These checks are still useful and compatible with the above policy:

* **NO_REMAINING_COMMENTS**

  * Pass if: `GapInventory` contains **zero** gaps of kind `SPEC_COMMENT_UNIMPLEMENTED`.
  * No scanning/tokenization in the gate.
* **NO_STUB_FUNCTIONS**

  * Pass if: `GapInventory` contains **zero** gaps of kind `STUB_FUNCTION`.
  * Source for stubs:
    * `SourceAnalysis.functions[].is_stub` (already language-agnostic)
    * plus any “semantic stubs” the LLM flags (e.g., “TODO: implement”) as a gap span.
* **ALL_TESTS_PASS**

  * Language-agnostic via an abstraction:
    * `TestRunner.run(targets) -> TestRunResult`
  * Gate checks `result.passed`.
* **CALL_GRAPH_CONNECTED**

  * Gate runs a graph algorithm on `AdjacencyGraph` filtered to `signal_type == CALL`.
  * The “nodes” are PinFunctions (or “algorithmic blocks”).
  * Connectivity criterion should avoid requiring full static precision:
    * every PinFunction must be reachable from at least one slice entrypoint or at least one test entrypoint.
  * Low-confidence / ambiguous edges return **AMBIGUOUS** and surface the question.
* **STORE_MONOGAMY**

  * Use `STORE_TOUCH` edges: function/block → store node.
  * Check: each store node is owned by exactly one slice (ownership derived from PinProjections/slice nodes).
  * Pure graph check.
* **PIN_COVERAGE**

  * Define architecture blocks as nodes with spans (produced during promotion).
  * Coverage = every architecture block span is covered by at least one PinProjection span (or the node has at least one projection edge).
  * No parsing required.
* **INTRODUCED_ALGORITHM_SPECS**

  * For architecture blocks flagged as `INTRODUCTION` (no origin pin):
    * Require at least one **spec-comment span** inside that block recorded in `GapInventory` as “spec present”.
  * If “spec present” classification is uncertain, gate returns **AMBIGUOUS**.
* **ARCH_DRIFT_PASS**
  * If evidence hash does not match current file hash: gate fails as **STALE_EVIDENCE** (not “recompute by parsing”).

## Q4: What does VerifyStep do at L2?

**Recommended:** (a)+(b)+(c)+(d)+(e) — verification is **graph integrity + conformance + governance**.

**Rationale:** Post-integration verification at L2 should answer: *Is the architecture graph coherent? Are all promoted items consumed? Does the realized wiring match the intended component manifest? Did anyone inject unreceipted decisions?*

**Implications:**

* VerifyStep must run **layer-aware** checks (L2 checks differ from L1/L3).
* VerifyStep should be the place where **Pipeline Oversight Enforcer** blocks the pipeline on governance FAIL, independent of “code correctness”.

## Assessment of your 10 suspected violations

Severity scale used below:

* **Cosmetic**: naming/organization; doesn’t constrain future architecture
* **Structural**: interfaces/control-flow make the target materially harder
* **Philosophical**: the system’s invariants are opposite to the principles; must invert data/control flow

### Violation 1: Sequential pipeline vs iterative per-slice loop

**Is it a violation?** Yes.

**Severity:** **Structural → Philosophical**, depending on how entrenched the phase interfaces are.
Even if TODOs acknowledge the gap, the current architecture *bakes in* “one pass over the repo” assumptions.

**Why it violates the philosophy:**

* **Principle 9 (constant iteration):** a single pipeline encourages “analyze everything then act” rather than baby steps.
* **Principle 5 (always knows target):** the pipeline implies each phase must rediscover targets globally.
* **Target model conflict:** P1–P10 are supposed to be *tools* invoked as needed per slice; current design makes them *stages*.

**Correct design (latest):**

### CI Flow: Worktrees, Tests, Promotions, Conflicts

#### Complete End-to-End Pipeline Execution Flow

Below is the recommended end-to-end orchestration (compatible with your current sequential lifecycle, but adds the missing CI/readiness/governance loops).

## 0) Run setup

1. Allocate `run_id`.
2. Create run directories:

   * `.pdd_runs/<run_id>/...` (evidence + ledgers)
   * `reports/pdd/<run_id>/...` (human + scorecard outputs)
3. Create `pdd/<run_id>/base` ref (required if Phase 0 intake runs; optional otherwise).

## 1) Phase 0 intake (optional)

**Decision:** input is raw prose?

* If yes: Phase 0 Intake → PDD skeletons (libraries) + coverage ledger.
* Commit result to `pdd/<run_id>/base`.

**Loop limit:** Phase 0 rework max 2 passes (only if coverage < 100% or fatal routing overlap).

## 2) Worktree setup

* `setup_layers(base_ref = pdd/<run_id>/base or main HEAD)`
* Worktrees: `l1/{dirty,clean}`, `l2/{dirty,clean}`, `l3/{dirty,clean}`, plus slice worktrees for the active layer.

## 3) L1 (Code-as-Spec)

1. **Entry library refinement** (L1 entry).
2. Discover L1 slices (libraries).
3. Run L1 PromotionLoops in parallel (max_parallel configurable).

   * After each slice integrates: **tick CI pipeline** (dirty→candidate→clean→propagate).
4. **Exit library refinement** (L1 exit).
5. Generate:

   * per-library overview.md
   * alignment summary
6. **Human approval loop** (max 3 iterations):

   * approve → continue
   * feedback → re-enter L1 (repeat steps 1–5)
   * quit → stop

**Loop limits**

* Per-slice: max 20 iterations + stagnation detection
* Approval: max 3 iterations (already)

### Summary of module mapping (P1-P10 as tools)

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

#### 1) PromotionLoop control flow

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

### Worktree entry

* Use `WorktreeManager` to obtain a **grandchild worktree** for that library slice (dirty, isolated).
* Evidence artifacts live inside that grandchild (so all tool scans remain “local” without rewriting internals).

### 7) WorktreeManager extension (API design)

Keep existing methods as L1 defaults and extend with layer-aware methods.

### New core types

```python
Layer = Literal["l1", "l2", "l3"]
Lane  = Literal["dirty", "clean"]
```

### Extended WorktreeManager API

#### Setup / accessors

```python
def setup_layers(self, run_id: str, base_ref: str, layers: list[Layer] = ["l1","l2","l3"], create_all: bool = True) -> None
def layer_branch(self, layer: Layer, lane: Lane) -> str
def candidate_ref(self, layer: Layer) -> str
def layer_worktree_path(self, layer: Layer, lane: Lane) -> str
def get_layer_heads(self, layer: Layer) -> dict  # {dirty_sha, clean_sha, candidate_sha}
def is_layer_clean(self, layer: Layer) -> bool
```

#### Grandchildren (active-layer work)

```python
def create_slice_worktree(self, layer: Layer, slice_id: str, base: Lane = "dirty") -> str  # returns path
def merge_slice_to_dirty(self, layer: Layer, slice_id: str, strategy: str = "merge") -> "MergeResult"
def cleanup_slice_worktree(self, layer: Layer, slice_id: str) -> None
```

#### Batch / CI primitives

```python
def snapshot_candidate(self, layer: Layer) -> str  # sets candidate ref to dirty HEAD; returns sha
def clear_candidate(self, layer: Layer) -> None

def promote_dirty_to_clean(self, layer: Layer, gates: bool = False, tests: bool = True) -> "BatchResult"
```

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

#### 3) Loop step design (inputs/outputs/modules/pure signatures)

### Common step interface

```python
@dataclass
class StepResult:
    status: Literal["OK", "RETRY", "WAITING", "BLOCKED", "FAIL"]
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

#### Gap 1: Wire `ImplementStep` to Real Implementation

`ImplementStep.run()` becomes the per-slice adapter over the working legacy Phase 9 logic, but it must emit **everything** the loop expects:

* applied edits (as a patch + structured edit list)
* **pin proposals**
* **edge proposals**
* **under-spec events** (hard blockers)
* **tests added** (small tests)

This aligns with the PromotionLoop’s intended step outputs and EvidenceBundle contract.

#### 1) `ImplementationRunner` helper

##### orchestration/implementation/runner.py

```python
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

#### Migration from legacy `pdd_orchestrator.py`

* Reuse (keep)

  * From the real P9 logic (`_run_implementation()`):
    * `analyze_project()` and any gap-finding helpers
    * the per-function loop structure
    * the “apply edit → re-analyze to confirm gap resolved” pattern
  * Those become internals of `ImplementationRunner`.

* Replace (delete once loop works)

  * `pdd_orchestrator._run_implementation()` itself (legacy global phase runner)
  * old implementor schema parsing (`body`, `imports_needed`, `gaps`, `notes`)
  * any “project-wide” iteration assumptions (per-slice only)

  This aligns with the no-backwards-compatibility policy by removing legacy
  control flow once the loop path is active.

#### 2) ImplementStep control flow (per slice)

##### Module placement

* `orchestration/promotion_loop.py` (modify `ImplementStep.run()`)

##### Algorithm

1. Load `bundle.plan` + `bundle.gaps`.
2. Load constraints paths (from `UnderSpecManager`/`ConstraintsStore`; see Gap 2).
3. Call `ImplementationRunner.run_for_slice(...)`.
4. Update `bundle.implementation` refs (paths).
5. Append a `GraphDeltaRef` in the bundle for the proposals (pin/edge).

This matches the loop’s intended “IMPLEMENT emits patch + proposals + under-spec + tests” contract.

#### Agent prompt changes: `pdd-function-implementor`

##### Required output schema (per function)

This replaces the legacy `{body, imports_needed, gaps, notes}` schema.

##### Exact JSON schema (enforced)

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

##### Enforcement rules

* If `under_spec_events` is non-empty:
  * edits/tests **may** be present for unrelated safe work, but MUST NOT implement the ambiguous decision.
  * ImplementationRunner stops scheduling further dependent functions.
* `edits[].unified_diff` is preferred over “body-only” because it’s language-agnostic.

This matches the “IMPLEMENT must emit patch + proposals + under-spec + tests” design already articulated for the loop.

#### Integration into PROMOTE (pins/edges)

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

#### Granularity: file-by-file vs function-by-function

**Recommendation**

* **Function-by-function** is the correct core unit (because the legacy `_run_implementation()` already works this way, and under-spec blocking is naturally per function).
* However, the runner should group by file to reduce churn:
  * analyze once → implement all targeted functions in that file → write one patch per file (or multiple diffs, still OK).

So: *function unit of work; file unit of patch application.*

#### Answers to Gap 1 questions

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
   Function-by-function scheduling, grouped by file for patching. This keeps under-spec blocking precise.

#### Test strategy (Gap 1)

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

### Step: UNDER_SPEC_CHECK (hard stop or decide)

**Input**

* `bundle.implementation.under_spec_events`
* existing constraints files (e.g., `analysis/constraints/<slice_id>.md` or `constraints.yaml`)
* `InteractiveWorkflow` / `ResearchCoordinator` depending on mode
* optional context from prior blockers (`blockers.json`), including `resume_hint` paths

### How the implementation agent signals “I can’t resolve this”

The implementation step writes structured `under_spec_events` in `impl.result.json` (see IMPLEMENT schema), including:

* missing constraints (API choice, persistence semantics, error handling policy)
* conflicting constraints (two specs disagree)
* unknown external dependency assumptions (protocol, schema)

### What “waiting for constraints” looks like

When under-spec is triggered, Loop step `UNDER_SPEC_CHECK` writes:

* `blockers.json`
* `constraint_request.md` (human-readable, including evidence references)
* `bundle.status = BLOCKED`
* `SliceContext` in `WorkspaceManager`:
  * `status=BLOCKED`
  * `blocked_on=[questions]`
  * `resume_hint` (paths to constraints / evidence artifacts)

The scheduler should move on to other slices while blocked.

### Interactive mode flow

1. Generate `constraint_request.md` with:

   * questions
   * option set
   * references to bundle evidence (file paths, pin ids, gate ids)
   * required decision format (YAML/JSON)
2. `InteractiveWorkflow` presents the request and collects constraints.
3. Write constraints to:

   * `analysis/constraints/<slice_id>.md` (preferred), or
   * `constraints.yaml`
4. Re-run planner with resolved constraints and resume loop.

### Auto mode flow (ResearchCoordinator)

Research may propose constraints, but promotion only proceeds if constraints become explicit artifacts.

1. Run ResearchCoordinator with:

   * blockers + context paths
   * allowed sources configuration
2. Produce:

   * `research_report.md`
   * `proposed_constraints.yaml` (explicit constraints only)
3. Run constraint validator:

   * checks concrete, testable, non-contradictory
4. If valid:

   * apply patch to constraints store
   * mark under-spec resolved
   * resume loop
5. If invalid:

   * stay `BLOCKED` (human constraints required)

### How constraints flow back into the loop

* Add new constraints references under `bundle.facts.constraints_refs`
* deterministic loading in planning and implementation from constraints files
* record decisions in bundle provenance (creator and source artifacts)

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

* `verify.notes.json`
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

#### VerifyStep implementation (works across L1/L2/L3)

Below is a concrete implementation pattern for `VerifyStep.run()`.

##### Notes on this implementation

It:

* makes VerifyStep **layer-aware** without introducing language parsing,
* cleanly separates:

  * governance verification (fail closed),
  * layer-specific correctness/conformance checks,
  * deterministic triage into demotion tickets,
* produces findings that feed demotion and retry decisions,
* preserves the “promotion not direct editing” rule by using demotion when a change is illegal in the current layer.

It is intentionally language-agnostic: it relies on LLM reviewers + manifest/graph artifacts, not parsing.

```python
class VerifyStep:
    """Run P6 + P7 + layer-specific verification (post-integration)."""

    name = "VERIFY"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        from pathlib import Path
        import json
        import time

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")
        slice_root = Path(ctx.slice_root) if ctx.slice_root else None

        findings: list[dict] = []
        notes: dict = {
            "layer": ctx.layer,
            "slice_id": ctx.slice_id,
            "timestamp": time.time(),
            "findings": [],
        }

        # -----------------------------
        # Helpers (language-agnostic)
        # -----------------------------
        def emit_finding(**kw):
            f = {
                "dimension": kw.get("dimension", "VERIFY"),
                "category": kw.get("category", "drift"),
                "severity": kw.get("severity", "MINOR"),
                "required_change_type": kw.get("required_change_type", "refactor_only"),
                "location": kw.get("location", {}),
                "evidence": kw.get("evidence", ""),
                "suggested_fix": kw.get("suggested_fix", ""),
                "confidence": kw.get("confidence", 0.7),
                "tags": kw.get("tags", []),
            }
            findings.append(f)

        def triage_to_ticket(f: dict) -> "DemotionTicket | None":
            # Deterministic, layer-legal triage.
            # L3 cannot change behavior; L2 cannot add business logic.
            required = f.get("required_change_type", "refactor_only")
            cat = f.get("category", "style")
            sev = f.get("severity", "MINOR")

            # Governance: block in place (ticket targets current layer for remediation)
            if cat == "governance":
                target = ctx.layer.upper()
            elif required == "behavior_change":
                target = "L1"
            elif cat == "architecture":
                target = "L2"
            elif required == "wiring_only":
                target = "L2"
            else:
                return None  # fix-in-layer, no demotion

            from spec_manager.orchestration.demotion import DemotionTicket

            loc = f.get("location") or {}
            failing_files = []
            if file := loc.get("file"):
                failing_files = [file]

            return DemotionTicket(
                run_id=ctx.run_id,
                slice_id=ctx.slice_id,
                source="VERIFY",
                origin_layer=ctx.layer.upper(),
                target_layer=target,
                severity=sev if sev in ("BLOCKER", "MAJOR", "MINOR") else "MINOR",
                diagnosis=f.get("evidence", "")[:500] or f.get("dimension", "Verification finding"),
                failing_files=failing_files,
            )

        def run_agent_json(agent_name: str, prompt: str) -> dict:
            # Safe helper: if agent infra missing, return empty.
            try:
                from spec_manager.core.agent_utils import run_agent
                from spec_manager.refinement.formats import _extract_json_payload, _strip_code_fences

                out = run_agent(agent_name=agent_name, prompt=prompt, workspace=workspace)
                cleaned = _strip_code_fences(out)
                return json.loads(_extract_json_payload(cleaned))
            except Exception:
                return {}

        # -----------------------------
        # 0) Governance / Oversight
        # -----------------------------
        # Fail closed if oversight detects missing receipts / decision injection.
        # This is language-agnostic (it inspects receipts + artifact text, not syntax).
        oversight_prompt = (
            "## TASK\n"
            "Act as Pipeline Oversight Enforcer for this slice.\n"
            "Check: missing receipts, undocumented deviations, decision injection patterns.\n"
            "Return JSON: {status: PASS|WARN|FAIL, findings:[{severity, evidence, location, required_change_type}]}\n\n"
            f"Slice: {ctx.slice_id}\nLayer: {ctx.layer}\n"
        )
        oversight = run_agent_json("pipeline-oversight-enforcer", oversight_prompt)
        if oversight:
            status = oversight.get("status", "PASS")
            for of in oversight.get("findings", []) or []:
                emit_finding(
                    dimension="GOVERNANCE",
                    category="governance",
                    severity=of.get("severity", "MAJOR"),
                    required_change_type=of.get("required_change_type", "refactor_only"),
                    location=of.get("location", {}),
                    evidence=of.get("evidence", "Oversight finding"),
                    confidence=0.8,
                )
            if status == "FAIL":
                # Convert governance findings to tickets targeting current layer
                tickets = [t for t in (triage_to_ticket(f) for f in findings) if t]
                notes["findings"] = findings
                iteration_dir = bundle.iter_dir(workspace)
                notes_path = iteration_dir / "verify.notes.json"
                notes_path.write_text(json.dumps(notes, indent=2), encoding="utf-8")
                return StepResult(
                    status="RETRY",
                    emitted_tickets=tickets,
                    notes_path=str(notes_path),
                    error="VERIFY: governance FAIL",
                )

        # -----------------------------
        # 1) Layer-specific verification
        # -----------------------------
        if ctx.layer == "l1":
            # P6: cross-library connectivity, P7: lineage
            prompt = (
                "## TASK\n"
                "Verify L1 post-integration correctness:\n"
                "1) Cross-library connectivity (P6): promoted interfaces connect; no orphan dependencies.\n"
                "2) Lineage (P7): architecture-facing surfaces trace back to spec/atoms; flag orphans.\n"
                "Return JSON: {findings:[...]} with required_change_type in {refactor_only, wiring_only, behavior_change}.\n\n"
                "Provide file locations when possible.\n"
            )
            data = run_agent_json("pdd-l1-verifier", prompt)
            for f in (data.get("findings", []) or []):
                emit_finding(**f)

        elif ctx.layer == "l2":
            # L2: pin consumption + topology connectivity + manifest drift
            prompt = (
                "## TASK\n"
                "Verify L2 architecture post-integration:\n"
                "- Pin consumption coverage (no unaccounted promoted pins)\n"
                "- Topology connectivity (no orphan components)\n"
                "- No inlined business logic in architecture\n"
                "- Conformance to component manifest / intended topology\n"
                "Return JSON: {findings:[...]}.\n"
            )
            data = run_agent_json("pdd-l2-verifier", prompt)
            for f in (data.get("findings", []) or []):
                emit_finding(**f)

        elif ctx.layer == "l3":
            # L3: reviewer closure + no-logic-change + drift
            prompt = (
                "## TASK\n"
                "Verify L3 clean-code post-integration:\n"
                "- All quality findings resolved (closure)\n"
                "- Changes are behavior-preserving (no logic change)\n"
                "- No architectural boundary violations introduced\n"
                "- No unplanned functionality (drift)\n"
                "Return JSON: {findings:[...]}.\n"
            )
            data = run_agent_json("pdd-l3-verifier", prompt)
            for f in (data.get("findings", []) or []):
                emit_finding(**f)

        # -----------------------------
        # 2) Convert to demotion tickets if needed
        # -----------------------------
        tickets = [t for t in (triage_to_ticket(f) for f in findings) if t]

        # Persist verify notes
        notes["findings"] = findings
        iteration_dir = bundle.iter_dir(workspace)
        notes_path = iteration_dir / "verify.notes.json"
        notes_path.write_text(json.dumps(notes, indent=2), encoding="utf-8")

        # Decide pass/fail
        has_blocker = any(f.get("severity") == "BLOCKER" for f in findings)
        has_major = any(f.get("severity") == "MAJOR" for f in findings)

        if has_blocker or (tickets and has_major):
            return StepResult(
                status="RETRY",
                emitted_tickets=tickets,
                notes_path=str(notes_path),
                error=f"VERIFY: {len(findings)} findings ({len(tickets)} demotions)",
            )

        return StepResult(status="OK", notes_path=str(notes_path))
```

---

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

### Termination Criteria

**Per-slice termination (PromotionLoop; slice is complete):**

* `open_gaps == 0` (equivalently, `GapReport.remaining == 0` for that slice in the P3 view) **AND**
* the last iteration ends with `PROMOTE + INTEGRATE + VERIFY + ALIGN` all returning `OK` **AND**
* all atoms in slice are promoted through:

  * `ComplianceGates` (algorithmic_gates) **AND**
  * `ArchitecturalGates` (architectural_quality) **AND**
* clean worktree tests pass for:

  * slice tests + workspace tests (configurable; at least slice tests per iteration, full suite periodically)
* no unresolved demotion tickets remain targeting the slice
* refinement/coupling checks for slice pass (RefinementEngine thresholds)

**Per-layer termination (layer is complete):**

* all discovered slices are `SLICE_COMPLETE` (or explicitly `SKIPPED` with receipt)
* layer is **clean**: `dirty == clean` (no pending commits)
* no pending demotions target this layer
* exit refinement produced no new blockers/demotions

**Global termination (run is complete / overall termination):**

* all slices are `SLICE_COMPLETE` (or explicitly excluded) **AND**
* global P6 connectivity (cross-library) passes **AND**
* global P7 lineage completeness passes (no orphans) **AND**
* L3 clean is produced and CI receipts are `PASS` **AND**
* clean-root full test suite passes **AND**
* QA run is executed and pass rate is recorded (hard/soft enforcement is config-driven) **AND**
* final governance gate is `PASS` **AND**
* final report + scorecard are written **AND**
* merge/tag action is completed

#### Q5: Termination and Loop Limits

**Recommended answer**

### Infinite-loop prevention (summary)

* Per-slice max iterations (layer-specific)
* Per-ticket retry budget
* Per-transition demotion round cap
* Global pipeline pass cap
* Stagnation detection and escalation

* **Per-slice max iterations:** make it layer-specific and configurable.

  * L1: **20** (reasonable)
  * L2: **30** (more search space + LLM gate tuning)
  * L3: **15** (review/refactor loop is expensive; stagnation should cut earlier)
* **Exit refinement demotions:** treat them as **new tickets** that reopen the necessary lower-layer work; do not “finish the layer anyway.”
* **Prevent infinite cycling via 4 budgets:**

  1. **Per-ticket retry budget** (e.g., same failing_files+gate repeats > 3 → escalate).
  2. **Per-transition demotion rounds** (e.g., L1→L2 gate demotes > 3 → stop).
  3. **Per-layer global demotion budget** (e.g., > X tickets in L2 without net progress → stop).
  4. **Overall pipeline pass cap** (e.g., > 2 full L1→L2→L3 restarts → stop).
* Add **stagnation detection**: if open gaps don’t decrease for K iterations (e.g., 3) or keep reappearing with high similarity, mark slice `STAGNATED` and escalate.

**Rationale (1–3 sentences)**
Without budgets, demotion + LLM variability can create perpetual loops. Stagnation detection makes “no progress” explicit and forces escalation rather than burning tokens.

**Design implications**

* Drives **Q8/Q9** (iteration efficiency becomes a score dimension and a stop condition).
* Drives **Q13** (Investigator budget should be bounded and counted against retries).
* Drives **Q1/Q3** (active-layer switching needs clear termination semantics).

---

### Final Output Specification

#### Q6: What Artifacts Should the Pipeline Produce?

**Recommended answer**

### MVP essentials (must exist)

1. **Working code**

   * L3 clean merged to `main` (or a release branch if you want manual merge).
2. **Evidence trail (append-only)**

   * All `EvidenceBundle` files + step outputs for every slice/iteration.
3. **Demotion ledger**

   * All tickets, hop traces, resolution status, and links to evidence.
4. **Architecture artifacts**

   * `component_manifest.json` + architecture graph/topology snapshot(s).
5. **Quality artifacts**

   * Aggregated reviewer findings + closure receipts per file/slice.
6. **Run summary + scorecard**

   * A single machine-readable `run_summary.json` plus a human-readable `final_report.md`.
7. **Approval artifacts** (interactive mode)

   * L1 overview(s), alignment summary, and recorded approval decisions/feedback.

### Can wait (post-MVP)

* Full **traceability matrix** requirement → function → tests (valuable but non-trivial).
* Deep **POWER alignment** lineage analysis beyond “findings + receipts”.
* Rich visualization dashboards (graphs, HTML reports).

**Rationale (1–3 sentences)**
MVP must support debugging, auditability, and repeatability. Traceability and rich reporting are additive once the end-to-end pipeline is stable.

**Design implications**

* Drives **Q7** (final consolidated report references these artifacts).
* Drives **Q11** (where scoring is computed and stored).
* Drives **Q15** (governance must validate artifact completeness).

---

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

### Legacy quick sketch (pre-existing summary)

```text
while gaps remain:
  slice = GapQueue.next()
  ctx   = WorkspaceManager.checkout(slice)

  # tools invoked opportunistically, not obligatorily
  gaps  = gap_exploration(ctx)        # may call P3-like logic
  patch = implementation(ctx, gaps)    # agent edits
  questions = under_spec_check(ctx)    # block if needed
  facts = analyze(ctx)                # shared evidence artifacts
  pins/edges = promote(ctx, facts)    # LLM outputs + verification
  integrate(ctx)                      # CI per worktree
  verify(ctx)                         # cross-library, lineage checks
  power_alignment(ctx)                # drift detection
```

### PromotionLoop step mapping

Below is what each step does at **L2** and **L3** (analogous to your L1 mapping). The key is that the *step names stay the same*, but the meaning of “gap” and “implement” changes by layer.

### L2 PromotionLoop semantics

#### 1) COLLECT (CollectBaselineStep)

* **Does:** snapshot current component files + pin registry summary (not full extraction), record hashes.
* **Evidence:** manifest + “component inventory” (files, component_ids, pins referenced).
* **Why:** stable baseline for drift + governance.

#### 2) GAP (GapExplorationStep @ L2)

* **Does (Architecture Continuity Gaps):**

  1. load Component Manifest (from architectural refinement)
  2. load promoted pins/edges in scope
  3. detect:

     * unconsumed pins
     * missing components/files for manifest targets
     * missing event handlers / missing middleware registrations
     * “logic-like” code inside architectural files (pre-gate warning)
     * manifest drift (extra components/wiring not in manifest)
* **Output:** `bundle.gaps.open_gaps = [{kind, component_id, file, anchor, description, expected}]`

#### 3) PLAN (PlanStep @ L2)

* **Does:** converts architecture gaps into a **wiring plan**: ordered intentions describing which component to adjust and how.
* **Also:** runs under-spec planning gate if architecture decisions aren’t covered by constraints (e.g., “should this interaction be sync or async?”).
* **Output:** `bundle.plan.intentions = [{component_id, target_files, approach, acceptance_criteria}]`

#### 4) IMPLEMENT (ImplementStep @ L2)

* **Does:** “Architectural Assembler” applies minimal patches:

  * create/adjust component entrypoints
  * connect pins in correct order
  * add missing handlers/routes
  * refactor wiring to satisfy boundaries
* **Must not:** invent business logic; if required, emits under-spec or demotion.
* **Outputs:** patch + updated wiring + optional integration test hooks.

#### 5) UNDER_SPEC (UnderSpecCheckStep)

* Same meaning as L1: resolve decision gaps or block.

#### 6) ANALYZE (AnalyzeStep @ L2)

* **Does:** build/update an **Architecture Graph Cache**:

  * nodes: components, entrypoints, pins
  * edges: calls, events, middleware ordering, dependencies
* **Outputs:** summary stats + graph snapshot used by PROMOTE/VERIFY.

#### 7) PROMOTE (PromoteStep @ L2)

* **Does:** runs L2 compliance gates (above), plus L2 rule-based review pack if configured.
* **On fail:**

  * if fix is wiring-only → retry L2 (no demotion)
  * if failure is “needs new atom logic” → emit DemotionTicket → L1
* **Output:** gate report recorded in evidence.

#### 8) INTEGRATE (IntegrateStep)

* Merge slice → L2 dirty; run layer CI; on failure, emit demotion (often via downward flow pin tracing).

#### 9) VERIFY (VerifyStep @ L2)

* **Does (post-merge):**

  * connectivity / orphan checks on architecture graph
  * pin consumption completeness check
  * drift check: manifest vs realized topology
  * governance: receipts + injection detection
* **On fail:** emit tickets (L2 or L1) and RETRY.

#### 10) ALIGN (AlignStep)

* Same purpose as L1, but evaluated against architecture-level intent too (still drift/reward hacking).

### L3 PromotionLoop semantics

#### 1) COLLECT

* Snapshot target files, diffs, existing quality receipts.

#### 2) GAP (GapExplorationStep @ L3)

* **Does (Quality Closure Gaps):**

  * run the configured L3 reviewers on target files (or validate existing PASS receipts)
  * produce findings with anchors
* **Output:** `bundle.gaps.open_gaps = findings[]` (each finding is a “gap”).

#### 3) PLAN

* Convert findings into a refactor plan:

  * group by function/span
  * sequence: smallest safe refactors first
  * define “no behavior change” acceptance criteria

#### 4) IMPLEMENT

* “Clean-code refactorer” applies targeted refactors for the planned finding set.

#### 5) UNDER_SPEC

* Rare at L3; used if refactor requires a decision not covered by constraints (“rename public API?”).

#### 6) ANALYZE

* Compute diff summary + structural metrics (size/duplication hotspots) + refactor impact candidates.

#### 7) PROMOTE

* Re-run reviewers; enforce **ALL_QUALITY_REVIEWERS_PASS**.
* Run **Diff-Impact Classifier**:

  * if logic-affecting → DemotionTicket → L1
  * if boundary-affecting → DemotionTicket → L2

#### 8) INTEGRATE

* Merge slice → L3 dirty; run CI on L3 clean (or per policy).

#### 9) VERIFY

* Post-merge closure:

  * confirm tests passed
  * re-check reviewers or verify PASS receipts correspond to merged content
  * governance checks

#### 10) ALIGN

* POWER check (still useful to detect “cleanup drift” and proxy-metric optimization).

### Migration strategy (incremental, preserves current orchestrator + tests)

## 6) Migration strategy (incremental, preserves current orchestrator + tests)

### Step 0 — Add PromotionLoop without refactoring modules

### 1) Git branch strategy for 6 worktrees

#### Branch naming convention

Use a **run-scoped namespace** so multiple runs don’t collide and so refs are self-describing:

* `pdd/<run_id>/l1/clean`
* `pdd/<run_id>/l1/dirty`
* `pdd/<run_id>/l2/clean`
* `pdd/<run_id>/l2/dirty`
* `pdd/<run_id>/l3/clean`
* `pdd/<run_id>/l3/dirty`

#### Git refs (recommended)

* `pdd/<run_id>/base` (post-intake baseline)
* `pdd/<run_id>/l1/clean`, `pdd/<run_id>/l2/clean`, `pdd/<run_id>/l3/clean`
* Approval tags:

  * `pdd/<run_id>/l1-approved`
  * `pdd/<run_id>/l2-approved` (optional)
  * `pdd/<run_id>/final`

Add **CI snapshot refs** (one per layer):

* `pdd/<run_id>/l1/candidate`
* `pdd/<run_id>/l2/candidate`
* `pdd/<run_id>/l3/candidate`

Add **slice/grandchild branches only for the active layer**:

* `pdd/<run_id>/<layer>/slice/<slice_id>/<nonce>`

  * example: `pdd/2026-02-09T18-04Z/l1/slice/projection/7f3a2c`

Optional tags for batch identification (see Q2):

* `pdd/<run_id>/batch/<layer>/<seq>`
* `pdd/<run_id>/batch/<layer>/<seq>/accepted`

This stays within “git-based tracking” (branches/refs/tags only).

### Promotion queue design (multiple slices competing for L1 clean)

The queue is explicit in git refs, plus one explicit “in-flight batch” ref:

* Pending work at layer `L` is `L.clean..L.dirty`
* In-flight batch is `L.candidate` (a ref to the snapshot SHA currently under CI)

While `L.candidate` exists and CI is running, new slice merges can continue to move `L.dirty` forward; they remain queued behind the candidate snapshot.

This gives you an actual queue without a database.

### Recommended CI locking / backpressure

* One candidate per layer at a time (`L.candidate` is an exclusive per-layer lock).
* If candidate FAILS: freeze promotion for that layer until fixed (do not create a new candidate).
* Optional: allow merging more slices into dirty while candidate in flight, but do not include them in the current candidate (keep candidate ref stable).

### Conflict handling (recommended default)

* Slice→dirty merge conflict:

  * try rebase slice onto dirty and re-merge once
  * if still conflict → emit ticket + block slice
* Clean→next dirty propagation conflict:

  * attempt rebase downstream dirty onto upstream clean
  * if conflicts persist → emit ticket to regenerate/re-run affected downstream slices
  * LLM merge agent only when conflict is wiring_only/refactor_only

---

### How are batches formed?

MVP default policy (recommended):

* **Batch size = 1 for dirty→clean.**
* After each completed slice merge into `L.dirty`, if CI is free and backpressure allows, snapshot `L.candidate = L.dirty` and run the layer's gate + test tier.
* Do not start a new candidate while one is failing; keep additional merges queued in `L.clean..L.dirty`.

This gives deterministic blame/recovery while end-to-end reliability is still stabilizing.

Optional policy knobs (later, once failure attribution is stable):

* max batch size (commit count or diff size)
* min batch size (wait for N slices)
* time window batching (every N minutes)

---

### What prevents unbounded growth if CI is slow?

Track “downstream acceptance” as refs:

* `pdd/<run_id>/l2/upstream_accepted` → points to the L1-clean SHA that is already accepted into L2-clean
* `pdd/<run_id>/l3/upstream_accepted` → points to the L2-clean SHA already accepted into L3-clean

Then define backlog metrics:

* `pending_L1_to_L2 = commits_between(l2/upstream_accepted, l1/clean)`
* `pending_L2_to_L3 = commits_between(l3/upstream_accepted, l2/clean)`

Apply backpressure rules:

* If `pending_L1_to_L2 > max_pending_batches` (default 1):

  * **pause starting new L1 candidate batches**
  * optionally reduce slice parallelism (don’t create more grandchildren)

This keeps L1’s “queue to clean” bounded when upper layers are slower.

---

### Scheduler interaction: PromotionLoop vs queue/CI

Split responsibilities:

* **PromotionLoop scheduler (creative)**:

  * chooses slices to work on (GapQueue priority)
  * runs the per-slice convergence loop in grandchild worktrees
  * merges completed slice → active layer dirty

* **BatchPromoter / CI tick (non-creative)**:

  * snapshots dirty→candidate
  * runs gates/tests
  * advances clean
  * propagates clean→next layer dirty
  * runs next-layer tests
  * emits DemotionTickets on failures

In a single-process MVP, you can just call `tick_ci()` after each slice merge and periodically while slices run.

---

### Revised INTEGRATE step (within-layer + between-layer pipeline)

This step becomes “merge slice into active layer dirty, then tick the batch pipeline.”

#### Core pipeline mechanics

```text
(active layer only does creative work)

Slice worktree (grandchild)
  → merge → Layer dirty
     → snapshot candidate (dirty HEAD)
        → run layer CI (tests + required gates)
           PASS → fast-forward Layer clean to candidate
                 → propagate Layer clean → next Layer dirty
                 → (repeat upward)
           FAIL → recovery (Investigator) else DownwardFlow demotion
```

#### Revised INTEGRATE algorithm (active layer = L1 case)

1. **Merge grandchild → L1 dirty**

* `git merge` slice branch into `pdd/<run_id>/l1/dirty`
* If conflict:

  1. rebase slice onto `pdd/<run_id>/l1/dirty` and retry merge once
  2. if conflict persists, emit DemotionTicket targeting L1 (conflict resolution required)
  3. block slice (needs rework) and do not proceed to CI tick for this slice

2. **Tick CI pipeline (all layers)**
   Run in order, but each layer can test in parallel worktrees if you want:

#### - merges from_layer.clean into next_layer.dirty (l1->l2, l2->l3)

```python
def tick_pipeline(self, active_layer: Layer, backpressure: dict) -> "PipelineTickResult"
```

#### - runs gates/tests against candidate snapshot; if pass, advances clean to candidate

```python
def propagate_clean_to_next_layer(self, from_layer: Layer) -> "PropagateResult"
```

#### - attempts:

#### (A) L1 dirty → L1 clean (gates + tests, if allowed)

* Preconditions:

  * `l1/candidate` not set (no in-flight batch)
  * `l1/dirty != l1/clean` (there is queued work)
  * backpressure allows it (pending_L1_to_L2 <= max)
* Actions:

  * set `l1/candidate = snapshot_sha(l1/dirty)`
  * run layer-appropriate gate + test tier:

    * compliance gates for the active layer (graph-based)
    * compile/import smoke
    * tests affected by the candidate diff
    * small integration tier (prefer full suite at L3; run periodic full suite at lower layers)
  * If pass:

    * advance `l1/clean` to `l1/candidate` (fast-forward ref update)
    * create batch tag(s)
    * clear or set `l1/candidate = l1/clean`
  * If fail:

    * run recovery (Investigator) first, with bounded attempts and layer-legal patches only
    * if recovery succeeds, rerun required gates/tests on the candidate before any demotion
    * if recovery fails, with batch size=1 attribute failure to the latest merged slice commit; with larger batches, bisect merge commits and use DownwardFlowEngine tracebacks
    * generate DemotionTickets targeting L1 when recovery fails or cannot legally apply a fix
    * keep `l1/clean` unchanged
    * clear candidate (or keep it + mark failing; simplest is clear and rely on tags)

#### (B) Propagate L1 clean → L2 dirty (immediate)

* Preconditions:

  * `l1/clean` advanced since last propagation (`l2/upstream_accepted` ref differs)
  * and optionally L2 not currently testing a candidate
* Actions:

  * merge `l1/clean` into `l2/dirty`
  * set `l2/candidate = snapshot_sha(l2/dirty)`
  * run L2 tests
  * If pass:

    * advance `l2/clean` to `l2/candidate`
    * update `l2/upstream_accepted = current l1/clean`
  * If fail:

    * generate DemotionTicket targeting:

      * L1 if L1 is active
      * L2 if L2 is active (later phase)
    * do not advance `l2/clean`
    * stop propagating further upward for this tick

#### (C) Propagate L2 clean → L3 dirty, then L3 dirty → L3 clean (tests)

Same mechanics as (B), just one layer up, and if pass:

* advance `l3/clean`
* update `l3/upstream_accepted = current l2/clean`

#### (D) L3 clean → main

* simplest: fast-forward merge into `main` (or create PR if you prefer)
* only happens after L3 clean advances

3. **Post-CI housekeeping**

* update status artifacts
* optionally rebase or refresh active-layer slice worktrees onto updated `l1/dirty`/`l1/clean` as needed

### Failure demotion paths (summary)

* Merge conflict slice→L1 dirty (after one rebase + re-merge attempt): demote to L1 (slice blocked for rework)
* L1 gates/tests fail: demote to L1
* L2 tests fail while L1 active: demote to L1 (L2 inactive, cannot change)
* L3 tests fail while L1 active: demote to L1
* While L2 active, L3 tests fail: demote to L2 or L1 depending on diagnosis

---

#### Q2: Batch Promotion Mechanics

**Recommended answer**

* **MVP default: batch size = 1 for dirty→clean.** Merge one completed slice into layer dirty, snapshot candidate, run CI, and if it passes promote to clean.
* **Tests at dirty→clean:** run layer-appropriate "gate + test tier" (see Q12). At minimum: (a) compile/import smoke, (b) all tests affected by the change set, and (c) a small integration tier. Prefer full suite at L3.
* **If dirty→clean fails:** with batch size=1, culprit is the merged slice. With larger batches enabled later, use `git bisect` on merge commits and/or DownwardFlowEngine tracing to failing pins/atoms to route demotions.
* **Call `tick_pipeline()` after each slice integration** (not "after all slices"), with backpressure so no new candidate starts while one is failing.

**Rationale (1-3 sentences)**
Early end-to-end reliability depends more on deterministic blame than on throughput. Batch size=1 gives clean failure attribution and simpler demotion routing before enabling higher-parallelism batching.

**Design implications**

* Drives **Q13** (Investigator invocation) because recovery can be scoped to a single slice commit.
* Drives **Q8/Q9** (CI stability and first-pass metrics become meaningful).
* Drives **Q5** (candidate-in-flight backpressure prevents infinite accumulation of unverified merges).

### Merge vs cherry-pick vs rebase

Use **merge** as the default for batch promotion. Specifically:

* Slice completion: merge slice branch → active layer dirty
* Dirty→clean acceptance: clean is advanced to a commit that already exists on dirty (fast-forward update)
* Cross-layer promotion: merge upstream clean → downstream dirty

Why merge is simplest here:

* Default flow avoids history rewriting across worktrees.
* “What went into this batch?” is a commit graph question.
* Conflicts surface as standard merge conflicts.

Exception for propagation conflicts (see Q14): if downstream dirty has diverged and upstream clean advances, rebase downstream dirty onto upstream clean to preserve downstream commits before deciding whether to re-run downstream slices.

Cherry-pick is only appropriate if you later enforce “directory ownership per layer” and want to cherry-pick subsets. Not needed for the refined model.

---

### What constitutes a “batch”?

Define a batch as **one frozen candidate commit per layer**.

At layer L:

* `L.clean` is last accepted commit.
* `L.dirty` accumulates incoming merges.
* When CI is ready, snapshot the current `L.dirty` HEAD into `L.candidate`.
* That `L.candidate` commit (a specific SHA) is “the batch” being tested/accepted.

So a batch is:

* `Batch(layer=L, candidate_sha=X, base_clean_sha=Y)`

This matches your statement: “queue empties each time previous batch clears” — the queue is the diff range `Y..(current dirty head)`, and the “emptied portion” is the tested candidate.

---

### How to track which batches were promoted

Use tags and/or refs only:

Minimum viable tracking:

* `pdd/<run_id>/<layer>/candidate` ref points to the in-flight batch SHA.
* When accepted, move `<layer>/clean` to that SHA, and clear/move candidate.

Recommended tracking for auditability:

* Create an annotated tag at batch start:

  * `pdd/<run_id>/batch/<layer>/<seq>` → candidate SHA
  * tag message includes:

    * base clean SHA
    * candidate SHA
    * list of slice merge commits included (can be computed and stored as text)
* On acceptance:

  * `pdd/<run_id>/batch/<layer>/<seq>/accepted` → same SHA (or just one tag with status in message)

Cross-layer mapping is implicit:

* “Which L1 batch was merged into L2?” can be derived from the merge commit parents, but if you want explicit:

  * store `pdd/<run_id>/l2/upstream_accepted` as a ref pointing to the L1-clean SHA that L2-clean currently includes (more below)

---

### L1 clean → L2 dirty: what operation happens?

Operation: **merge**.

```
git checkout pdd/<run_id>/l2/dirty
git merge --no-ff pdd/<run_id>/l1/clean
```

If no conflicts and L2 has no additional changes, this may fast-forward or produce a trivial merge commit.

Then L2 CI tests run on the new `l2/dirty` head (snapshotted via `l2/candidate`).

---

### Conflicts when promoting to L2 dirty

Policy (simple, correct, consistent with “no creative work at inactive layers”):

* If merge produces conflicts at layer L2 while L1 is active:

  1. rebase `l2/dirty` onto `l1/clean` (preserve downstream commits if possible)
  2. if conflicts remain, do not manual-merge logic; emit DemotionTickets to re-run affected downstream slices against the new upstream baseline
  3. allow LLM-assisted merge only for `wiring_only` / `refactor_only` regions when diff-impact classification shows no behavior ambiguity
  4. if still unresolved, block further cross-layer promotion and escalate for interactive approval

This enforces “inactive layers don’t get creative conflict resolution.”

Later, when L2 is active, use the same rebase + re-run strategy, but tickets may target L2 or L1 based on diagnosis.

---

#### Q12: Test Strategy

**Recommended answer**

### Test tiers (recommended)

* **Tier 0: Smoke**

  * `uv run python -m compileall` (or equivalent)
  * “import graph smoke” (import key modules)
* **Tier 1: Unit**

  * fast unit tests, per-library or per-slice selection
* **Tier 2: Integration**

  * component wiring tests (L2), cross-library integration (L1/L2)
* **Tier 3: Full regression**

  * entire suite, plus any slow e2e checks

### What runs where

* **L1 dirty→clean:** Tier 0 + Tier 1 + minimal Tier 2 (cross-library sanity).
* **L2 dirty→clean:** Tier 0 + Tier 1 + Tier 2 (wiring/topology).
* **L3 dirty→clean:** Tier 0 + Tier 1 + Tier 2 + Tier 3 (full regression) + diff-impact classifier.
* **Cross-layer principle:** upper layers run **all lower-layer tests relevant to the code they contain**, but you can skip redundant reruns when commits are identical.

### If the target codebase has no tests

* L1 should generate minimal tests around atoms/stores as part of implementation (enough to satisfy ALL_TESTS_PASS meaningfully).
* Always run Tier 0 smoke as the baseline safety check.

**Rationale (1-3 sentences)**
L1 validates behavior; L2 validates wiring; L3 validates preservation. Tiering lets you enforce safety while controlling cost.

**Design implications**

* Drives **Q2** (what dirty→clean runs).
* Drives **Q13** (Investigator needs a reproducible test command).
* Drives **Q9** (CI stability metrics).

---

#### Q13: Recovery from Test Failures

**Recommended answer**

##### Recovery Flow: Investigator vs DemotionTickets

###### When Investigator runs

Trigger Investigator on:

* dirty→clean test failure
* propagation failure that breaks CI
* intermittent failures that reproduce deterministically in the candidate worktree

###### Investigator constraints

* fixed attempt budget (e.g., max attempts = 2)
* must respect layer legality
* must produce: root cause, reproduction steps, patch, evidence refs

* **IntegrateStep failure flow (recommended):**

  1. Capture failure evidence (logs, failing files, stack traces).
  2. Invoke **Investigator** immediately when a trigger condition is met.
  3. If Investigator succeeds: apply patch in the correct layer worktree and retry CI.
  4. If Investigator fails: invoke **DownwardFlowEngine** to trace pins/atoms and emit DemotionTickets.
* Do not invoke Investigator “instead of tickets”; invoke it **before tickets** and attach its report to the ticket when it gives up.

**Rationale (1–3 sentences)**
Many failures are small integration issues that can be fixed locally without demotion churn. When a fix requires illegal changes, demotion is still the correct mechanism.

**Design implications**

* Drives **Q2** (batch size 1 makes Investigator scope small).
* Drives **Q6** (store Investigator reports as artifacts).
* Drives **Q5** (Investigator attempts count toward retry budgets).

---

#### Q3: Demotion Rework During Transitions

**Recommended answer**

* **Do not re-run “everything” blindly.** When a transition refinement emits tickets, re-run only the **owning slice** but pass **focus targets** derived from the ticket (`failing_files`, `failing_pins`, `failing_atoms`, `location.symbol`) so Plan/Implement converge on the right patch.

  * MVP: “owning slice + focus targets” (no new slice type needed).
  * Later: true narrow “ticket slice” objects.
* **After L1 rework, always flow through normal promotion again:** L1 rework → merge into L1 dirty → dirty→clean CI → **propagate clean→L2 dirty**. Do not “direct merge into L2 dirty” bypassing L1 clean.
* **Transition demotion loop limit:** cap each transition at **N rounds** (recommend **3**) before surfacing a “transition stuck” report and requiring human constraints or changing the manifest/spec.

**Rationale (1-3 sentences)**
Bypassing the “clean” lane breaks the invariant that higher layers only consume verified inputs. Focused rework avoids wasting iterations while keeping the safety guarantees of the normal promotion pipeline.

**Design implications**

* Drives **Q14** (propagation conflicts are resolved by rebase + re-run, not ad-hoc merges).
* Drives **Q5** (demotion-round caps + per-ticket retry budgets).
* Drives **Q6** (demotion history must record transition round/attempt context).

---

#### Q14: Worktree Merge Conflicts

**Recommended answer**

* **Yes, conflicts can arise** (especially when L1 demotions happen while L2 has diverged).
* Preferred resolution strategy:

  1. **Slice→dirty merge conflict**:

     * rebase slice onto current dirty and re-merge once
     * if still conflict, emit ticket and block the slice
  2. **Clean→next dirty propagation conflict**:

     * rebase downstream dirty onto upstream clean (preserve downstream commits if possible)
     * if conflicts remain, do not manual-merge logic; emit tickets to re-run affected downstream slices (L2 wiring re-assembly, L3 refactor re-application) against the new upstream baseline
     * use an LLM merge agent only when conflict is confined to **wiring_only** or **refactor_only** regions and diff-impact classification indicates no behavior ambiguity
  3. If still unresolved: block and escalate (interactive approval required).

**Rationale (1–3 sentences)**
Most downstream work is derivative and can be regenerated; forcing merges risks silent logic drift. Rebase + re-run preserves invariants and keeps layer legality intact.

**Design implications**

* Drives **Q1/Q3** (demotion pauses higher-layer creative to reduce conflicts).
* Drives **Q12** (tests validate conflict resolution).
* Drives **Q15** (governance must flag “unreceipted conflict resolutions”).

---

#### Q15: Governance Model Beyond VerifyStep (Governance Integration)

**Recommended answer**

Governance should run at four points, not only in a final verify pass:

1. **Per-slice, per-iteration** (already in VerifyStep)

   * Enforce per-slice oversight and fail closed on governance FAIL findings.
2. **Per-layer dirty→clean promotion governance gate**

   * Confirm candidate has full CI receipts, no missing evidence files, and updated decision logs before advancing clean.
3. **Transition governance gate** (L1→L2, L2→L3)

   * Ensure no open governance FAIL findings and required manifest/alignment/decision artifacts are present.
4. **Final whole-run governance gate (pre-merge / pre-release)**

   * Run whole-run oversight + report validation and check final report completeness, artifact completeness, no missing receipts, and no decision-injection patterns.

Also run governance on the **final report** to ensure it includes mandatory sections and links to evidence.

##### Governance failure semantics

* **FAIL**: hard stop + ticket targeting current layer (category=GOVERNANCE)
* **WARN**: allowed but recorded and scored; may block in strict mode

**Rationale (1–3 sentences)**
Per-slice oversight can miss run-level omissions (missing reports, missing approvals, incomplete ledgers). Governance must also validate the integrity of the pipeline’s final outputs.

**Design implications**

* Drives **Q6/Q7** (reports must be structured and checkable).
* Drives **Q5** (governance FAIL is a hard stop).
* Drives **Q9/Q11** (scores include governance status).

---

### What if L2 dirty already has content from a previous batch?

Normal case. L2 dirty is an integration branch and will have an evolving history:

* If previous batch was accepted, L2 clean has moved forward; L2 dirty may be ahead or equal.
* If previous batch failed, L2 clean is behind; L2 dirty contains a failing candidate commit.

New promotions from L1 clean should obey backpressure (see Q3), but mechanically it’s still just:

 * merge upstream clean into L2 dirty
 * snapshot candidate
 * test

### 4) Layer transition (when active layer advances)

#### merge l3 clean->main

#### Layer transition helpers

#### - derived from which layer has dirty!=clean or open “must-fix” signals

```python
def can_advance_layer(self, layer: Layer) -> bool
```

```python
def compute_active_layer(self) -> Layer
```

### Detecting “dirty == clean”

For a layer L, treat it as fully clean when:

* `rev-parse L.dirty == rev-parse L.clean`
* and either:

  * `L.candidate` does not exist, or
  * `rev-parse L.candidate == rev-parse L.clean` (no in-flight batch)

This is faster and less ambiguous than diffing.

---

### What happens to grandchild worktrees?

When a layer stops being active:

* Remove grandchild worktrees for that layer (worktree cleanup)
* Preserve evidence artifacts (EvidenceBundle dirs) for audit/debug
* Keep any “blocked” slice branches/worktrees only if you need human intervention; otherwise delete after ticketing

This keeps the physical worktree set manageable.

---

### Does L2 creative work start immediately?

#### Q1: Layer Activation and CI

**Recommended answer**

* **Propagation is necessary but not sufficient.** Keep `propagate_clean_to_next_layer()` as the mechanism that moves verified code upward, **and add an explicit “Downstream Readiness CI” check immediately after propagation** (before any creative L2/L3 work starts).
* **Demotion should switch the active creative layer downward.** When L2 emits any demotion -> L1, **pause L2 creative work** (at least for MVP) until L1 rework lands in **L1 clean** and is **re-propagated** to L2 dirty.
* **Passive CI at upper layers is still valuable** (it catches merge/conflict/test regressions early), but creative work should remain single-layer-at-a-time.

**Rationale (1-3 sentences)**
Propagation proves "code moved"; it does not prove "code runs in the downstream lane/worktree". A readiness CI step prevents starting architecture work on an un-runnable baseline and avoids wasting L2 tokens on work that will be invalidated by imminent L1 rework.

**Design implications**

* Drives **Q12** (what readiness tests are) and **Q2** (when tests run: after every propagation/batch).
* Drives **Q14** (conflict strategy) because demotions + propagation are the primary conflict source.
* Drives **Q5** (loop prevention): demotion-triggered active-layer switching must be budgeted.

### Backward-compatible wrappers (keep existing call sites working)

* `setup()` → `setup_layers(..., layers=["l1"], create_all=False)`
* `create_library_worktree(lib_id)` → `create_slice_worktree(layer="l1", slice_id=lib_id)`
* `promote_library(lib_id)` → `merge_slice_to_dirty("l1", lib_id)` then `tick_pipeline(active_layer="l1", ...)`
* `rebase_root_on_clean()` becomes either a no-op under the “fast-forward clean to dirty commit” invariant, or a helper for refreshing worktrees.

## 4) L1→L2 transition gate

Before switching active layer from L1 → L2:

1. Ensure L1 fully clean (as above).
2. Run architectural refinement (transition).
3. If demotion tickets are emitted:

   * enqueue tickets (target L1)
   * run L1 rework (focused slices)
   * require CI pass and re-propagation
   * repeat transition gate (max 3 rounds)
4. **Propagation**: ensure `L1 clean → L2 dirty` is up-to-date.
5. **Downstream readiness CI (L2 dirty)**: smoke + baseline tests.
6. Ensure pipeline has no failing in-flight candidates above L1. A fully drained baseline is:

   * `l2.dirty == l2.clean` and `l3.dirty == l3.clean`
7. Run a **global verify checkpoint** on L1 clean (or on L2 clean if L2 mirrors L1 at this stage):

   * P6 cross-library connectivity
   * P7 lineage/orphans
   * full test suite on L1 clean (if not already)

Only then mark L2 as active.

This matches the refined model: no architecture work while L1 still moving.

## 5) L2 (Architecture)

1. L2 entry architectural refinement (establish/refresh component manifest).
2. Discover L2 slices (components).
3. Run L2 PromotionLoops in parallel.

   * After each slice integrates: tick CI pipeline.
4. L2 exit architectural refinement.
5. Optional human checkpoint (interactive): approve architecture topology before L3.

**Loop limits**

* Per-slice: max 30 iterations + stagnation detection

## 6) L2→L3 transition gate

Same structure as L1→L2:

1. Run transition refinement (code quality).
2. If demotion tickets are emitted:

   * enqueue tickets (target L2 or L1, focused)
   * run focused rework at L2 or L1
   * require CI pass and re-propagation
   * repeat transition gate (max 3 rounds)
3. **Propagation**: ensure `L2 clean → L3 dirty` is up-to-date.
4. **Downstream readiness CI (L3 dirty)**: smoke + baseline tests.

## 7) L3 (Clean Code)

1. L3 entry code quality refinement baseline.
2. Discover L3 slices (files).
3. Run L3 PromotionLoops in parallel.

   * After each slice integrates: tick CI pipeline.
4. L3 exit code quality refinement.

**Loop limits**

* Per-slice: max 15 iterations + stagnation detection

## 8) Final QA + final governance + merge

1. Run QA eval framework.
2. Run final governance gate (whole-run).
3. Generate final report + scorecard.
4. Merge L3 clean to main (or produce release branch + tag).

---

### Does L2 also get grandchild worktrees?

You have two workable choices; start with the simpler one:

**Option A (simplest): no L2 grandchildren initially**

* L2 creative work happens directly in `l2/dirty` worktree (single-threaded architectural work).
* Still uses EvidenceBundle per iteration, but slice_id might be “architecture”.

**Option B (parallelizable): L2 grandchildren exist**

* Units of work are architecture components (services, event domains, disconnected graph components from AdjacencyGraph).
* Create grandchildren from `l2/dirty` exactly like L1 library slices.

This keeps the mechanics identical; only the slice discovery differs.

---

### Can the system go back to L1 after advancing to L2?

Yes, and it should be automatic:

* If any CI/test/verification at L2 or L3 emits a DemotionTicket targeting L1:

  * apply ticket → creates new changes on `l1/dirty`
  * now `l1/dirty != l1/clean`
  * active layer is reset to L1 (creative returns to spec)

Pipeline above L1 is frozen (or runs only diagnostic CI) until L1 re-cleans and promotions re-flow upward.

This is the “re-open lower layer” mechanism.

---

---

### What happens if L2 tests fail on a promoted batch?

Key properties to preserve:

* Layer isolation: do not mutate L1 clean.
* Determinism: a failing batch SHA is preserved for diagnosis.

Mechanism:

1. **Do not update `l2/clean`**
2. Record failure artifacts + create DemotionTickets
3. Determine demotion target:

   * if active layer is L1, demote to L1
   * if active layer is L2, demote to L2 unless diagnosis indicates spec-layer gap
4. Block further promotion across this boundary until fixed (see backpressure)

You do not roll back anything. Fixes flow forward as new commits in the demotion target layer.

### Gap 5: Full Demotion Chain (L3 → L2 → L1)

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
  * once L1 clean advances, pipeline merges upward (L1→L2→L3)

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

### 5) Demotion across layers in the batch model

#### Rule: demote to the lowest layer that is allowed to change right now

DemotionTickets already have `target_layer`. In practice, combine router classification and active-layer constraints:

* DemotionRouter classifies each failure (style/refactor/ARCH/logic)
* if the active layer is below target, route down one or more layers

Concrete policy:

**While L1 is active**

* Any L2 test failure → ticket targets **L1** (L2 cannot change)
* Any L3 test failure → ticket targets **L1**

**While L2 is active**

* L3 failure:

  * target L2 if architectural/code-assembly issue
  * target L1 if missing requirement / under-spec
* L2 failure:

  * target L2 unless it’s clearly a spec-layer gap (then L1)

**While L3 is active**

* L3 failures target L3
* route to L2 or L1 if diagnosis indicates architecture pin logic or missing spec/algorithmic mismatch

DownwardFlowEngine remains the tracer:

* failure → pins → atoms → slice → ticket

---

#### If L2 tests fail but L1 had already advanced (dirty==clean)

Yes: demotion re-opens L1.

Mechanically:

* apply ticket patch into `l1/dirty` (or create new L1 slice branches)
* L1 dirty no longer equals L1 clean
* active layer becomes L1 again
* L2/L3 candidates remain unaccepted and are treated as “blocked by upstream fix”

No rollback of L1 clean is required; fixes flow forward.

---

#### If L3 tests fail, how does demotion cascade?

Same policy: target the lowest editable layer that can fix.

Typical outcomes:

* If failure traces to architectural wiring or pin misuse → ticket targets L2
* If it traces to missing spec requirement or algorithmic contract mismatch → ticket targets L1

Do not automatically “cascade multiple tickets.” Let one ticket be explicit; if resolving it reveals deeper issues, subsequent tickets will be emitted.

---

#### What happens to batches already promoted above when a lower layer reopens?

Keep them. Do not roll back clean refs.

* `L3 clean` is never advanced on a failing batch (so main is protected).
* `L2 clean` is never advanced on a failing batch.
* Failing batches remain on `dirty` (and tagged via candidate/batch tags) for diagnosis.

After fixes land in the target layer and re-promote upward, new merge commits supersede the failing state and CI re-runs.

This matches “layer isolation” and avoids rollback complexity.

### Answers to Gap 5 questions

1. **How does L3 decide quality vs logic?**
   LLM-assisted triage is acceptable here, but enforce structured output:

* reviewers output findings using the canonical schema:
  * `category: style | maintainability | architecture | logic | drift | governance`
  * `dimension` identifies the review axis (`CLARITY`, `CORRECTNESS`, `ARCH_BOUNDARY`, `DRIFT`, `GOVERNANCE`, etc.)
  * `required_change_type` is explicit (`refactor_only | wiring_only | behavior_change | spec_change`)
  * `tags` carry subtypes such as `INLINE_LOGIC_AT_ARCH`, `CORRECTNESS`, `LOGIC_BUG`, `SPEC_UNDER_SPEC`
* categories map deterministically:

  * `style`/`maintainability` + `refactor_only` → L3
  * `architecture` + `wiring_only` → L2
  * `logic` + `behavior_change` → route via pins → likely L1
  * `logic`/`drift` + `spec_change` or `SPEC_UNDER_SPEC` tag → L1 + under-spec events

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

### Test strategy (Gap 5)

1. `test_downward_flow_traces_test_failure_to_atom_and_creates_ticket()`
2. `test_router_sends_logic_issue_to_L1_and_quality_issue_to_L3()`
3. `test_demotion_manager_applies_patch_to_correct_layer_root()`
4. `test_repromotion_occurs_via_gapqueue_and_scheduler()` (integration)


### Gap 6: Architectural Implementation Agent

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

### Are all 6 worktrees created upfront?

Recommended default: **create all 6 upfront** (cheap, simplifies continuous CI):

* L1 dirty + L1 clean worktrees
* L2 dirty + L2 clean worktrees
* L3 dirty + L3 clean worktrees
* grandchild slice worktrees created **lazily** when a slice is scheduled at the active layer

If you want an incremental rollout: create L1 dirty/clean initially, then create L2/L3 pairs the first time L1 clean advances (lazy “first use”). The API can support both.

---

### How do grandchild worktrees relate to layer worktrees?

Keep the existing semantics to minimize refactors:

* **Grandchildren branch off the active layer’s `dirty`**.

  * While L1 is active: slice branches off `pdd/<run_id>/l1/dirty`
  * While L2 is active (if you choose to parallelize architecture): slice branches off `pdd/<run_id>/l2/dirty`
  * While L3 is active (code quality): slice branches off `pdd/<run_id>/l3/dirty`

Reason: this matches your current WorktreeManager behavior and avoids re-plumbing “base branch selection” during migration.

If you want a stability option later, add config `grandchild_base = "dirty" | "clean"`.

---

### Base commit relationship between layers

Do **not** make L2-dirty “branch from” L1-clean in the git sense. Instead:

* All `*/clean` branches start at the run base ref (usually `main` HEAD at run start).
* Promotion between layers is implemented as **merging upstream clean into downstream dirty**:

  * when `l1/clean` advances, merge it into `l2/dirty`
  * when `l2/clean` advances, merge it into `l3/dirty`

This yields the pipeline invariant:

* Each layer’s `clean` is “last-known-good at that layer”
* Each layer’s `dirty` is “clean + pending merges (from below or from layer’s own creative work)”
* `git diff <layer>/clean..<layer>/dirty` is always the “unpromoted queue” for that layer

This keeps layer isolation: L2 failing does not mutate L1 refs.

---

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

### Violation 2: Pin creation is mechanical, not during LLM work

### Q6: Role of pins in the conversion

So modules that currently “build pins by scanning imports” should flip direction:

* **PinProjections are produced at the moment architecture is written.**
* LLM already knows: “I’m wrapping atom X with middleware Y” → that is the projection type.

Therefore:

* `import_scanner.py` becomes unnecessary (query `PinRegistryIndex` instead).
* `projection_classifier.py` becomes unnecessary (classification is part of the promotion decision).
* The remaining need is **verification**, not discovery:

  * “Does the code still match the recorded projection?” (`wrapper_hash` / `span` hash checks)

### Recommended split

* **Producers (LLM during promotion):**

  * create/update `PinFunction`
  * create/update `PinProjection`
  * create/update adjacency edges
* **Consumers (deterministic code):**

  * gates
  * lineage builder
  * registry index queries
* **Verifiers (deterministic + optional LLM tie-break):**

  * wrapper_hash validation
  * similarity-based inlining detection
  * stale-evidence detection via hashes

**Is it a violation?** Yes, in the current form.

**Severity:** **Philosophical**.

**Core misalignment:**

* Pins are the *currency of the system* (Principle 6).
  If they’re created by AST scanning, the graph becomes an afterthought derived from language-specific parsing—directly opposing **Principle 8/12**.
* Mechanical pin discovery also reintroduces the assumption that “atoms are extractable” (Principle 1 and 2 conflicts).

**Correct design:**
Pins should be **an explicit output of the same LLM call that makes promotion/implementation decisions**.

A good pattern is:

* Implementation agent returns:

  * a patch (diff)
  * **PinProposals** (what spans correspond to atoms/functions/events/stores)
  * **EdgeProposals** (calls/events/store usage)
  * **Evidence** (why these pins/edges are correct)
  * **Questions** (if under-spec)

Then a **verifier** checks:

* spans exist and anchors are stable
* pins cover changed spans (diff coverage)
* graph constraints (gates) hold

**Is mechanical scanning acceptable as verification?**
Yes **only as an optional backend** that:

* does not define truth (LLM output does)
* is not required for correctness
* can be swapped per language (plugin), not core

**Migration path:**

1. Extend promotion/implementation agent output schema to include pins/edges.
2. Add a `PinVerifier` that checks anchors/diff coverage (text-based, not AST).
3. Make `PinProjection` type selection part of the same promotion write path; keep no separate projection classifier.
4. Keep `pin_functions/orchestrator.py` temporarily as a **fallback pin suggester** for Python, but move it behind `PinDiscoveryBackend`.
5. Gradually flip default from AST backend → LLM backend.

---

### Violation 3: Compliance gates parse code instead of consuming graph data

**Is it a violation?** Yes.

**Severity:** **Philosophical**.

**Why:**
Gates are supposed to validate artifacts of the promotion loop (pins/graph/evidence).
If every gate re-parses Python AST, the system’s real substrate becomes “Python syntax trees,” not “graph of pinned evidence.”

**Correct design: “Gates = graph queries + runtime checks”**
Examples using your own suggested mappings:

* **NO_REMAINING_COMMENTS** → query `facts.remaining_gap_pins == ∅`
* **NO_STUB_FUNCTIONS** → query `facts.stub_nodes == ∅`
* **CALL_GRAPH_CONNECTED** → query `AdjacencyGraph.connected(atom_nodes)`
* **STORE_MONOGAMY** → query `StoreGraph.owners(store).size == 1`
* **ALL_TESTS_PASS** → runtime test execution result (language/toolchain specific; that’s fine)

For architectural gates:

* Some are crisp graph properties (PIN_COVERAGE via diff coverage)
* Some are fuzzy (NO_INLINED_ATOM_LOGIC) and should be **LLM-evaluated** using pinned evidence + diff

**Migration path:**

1. Create a single run-scoped **EvidenceBundle** (facts + pins + edges + diff metadata).
2. Refactor gates to accept `EvidenceBundle` and become **pure queries**.
3. Keep AST gates only as **optional cross-checks** (and only as Python plugins).

---

### Violation 4: Graph extractors parse code instead of consuming LLM data

**Is it a violation?** Yes.

**Severity:** **Philosophical**.

**Correct design:**
Edges should be produced either:

* **as a byproduct of implementation/promotion** (best alignment with Principle 8), or
* via **one explicit LLM “relationship analysis” call** that outputs all edge types in one schema (calls/events/stores/import-like dependencies)

What’s incorrect is “three independent mechanical extractors” that each rebuilds understanding.

**Migration path:**

1. Define one `RelationshipFacts` schema:

   * `calls: [(caller_pin, callee_pin, confidence, evidence_pin)]`
   * `events: [(emitter_pin, event_id, consumer_pin?)]`
   * `stores: [(pin, store_id, access_type)]`
2. Make the adjacency runner build the graph from these facts.
3. Deprecate AST extractors; keep as plugin verifier if desired.

---

### Violation 5: `collapse.py` does extraction

**Is it a violation?** Mostly yes.

**Severity:** **Structural → Philosophical**, depending on scope.

**Key nuance (brownfield ingestion):**
Brownfield ingestion *does* require learning structure from existing code.
But the philosophy’s version of that is **routing and pinning**, not extracting a rigid representation.

**Correct design for brownfield:**

* Treat the existing codebase as “raw text to be pinned.”
* Build **Layer 1 skeletons** by:

  * creating atoms as pinned spans
  * attaching summaries as routing hints
  * avoiding copying algorithmic logic into new spec docs

So collapse should be “ingestion router,” not AST classifier.

**Migration path:**

1. Replace AST classification with an LLM ingestion pass that outputs:

   * atom candidates
   * pin spans
   * relationship hints
2. Reuse Phase 0’s summarize→discover→route mechanics, but with code-as-input.

### Q7: Brownfield ingestion (`collapse.py`) under “routing over extraction”

Brownfield ingestion is the one place where “understand existing code” is unavoidable. The way to keep it aligned is:

#### Treat collapse as routing spans into the PDD graph

* Input: existing code
* Output: **span routing decisions**, not “facts extracted into a separate spec layer”

  * “These spans become PinFunctions”
  * “These spans are slice entrypoints”
  * “These blocks touch store S”
  * “These blocks publish/subscribe events”
  * “These files/blocks should be promoted into architecture vs algorithmic”

You may generate *summaries*, but only as routing hints (e.g., to name atoms/slices), not as a parallel spec.

#### Language-agnostic implementation

* Use `code_analysis` to get candidate block spans (functions or “logical blocks”).
* Use an LLM collapse agent to:

  * choose which spans become atoms
  * generate initial PinFunctions/Projections
  * generate initial AdjacencyGraph edges with confidence
  * produce an ambiguity list (questions for constraints)

No AST required; only spans + graph outputs.

---

### Violation 6: Separate analysis modules duplicate understanding

**Is it a violation?** Yes.

**Severity:** **Structural → Philosophical**.

**Important distinction:**
Per-phase *separation of concerns* is fine.
Per-phase *re-parsing and re-extracting* is not.

**Correct design:**
A single canonical **FileFacts / EvidenceFacts** service that produces:

* structure hints (not language constructs)
* gap pins (TODO/spec comments/stubs)
* relationship edges (calls/events/stores/import-like)
* test identity hints
* anything else gates need

Then P1/P2/P3/P6/P7 become:

* either no-ops
* or thin views over the same evidence bundle

**Migration path:**

1. Make `core/code_analysis.py` the canonical “facts provider.”
2. Add a run-scoped cache keyed by file content hash / diff.
3. Rewrite other modules to consume those facts (or delete them).

---

### Violation 7: PinFunction schema references code, not graph

**Is it a violation?** **No** (as stated).

Pins are *supposed* to point to text locations. That’s the whole mechanism.

**What would be a real violation here:**
If downstream modules operate on *source code semantics* directly (e.g., AST nodes) instead of operating on the **pin graph + evidence**.

**Recommended improvement (not required by principles but helps in practice):**
Augment pins with **stable anchors**:

* `anchor_before`, `anchor_after` snippets
* `content_fingerprint` of the span
  This supports refactors without treating line numbers as truth.

---

### Violation 8: No demotion chain (gate/test/verify failure → ticket → L1 patch → GapQueue → re-loop)

**Is it a violation?** Yes.

**Severity:** **Philosophical**.

Skipping is the opposite of promotion/demotion convergence. It turns gates into “filter what passes” instead of “generate the next concrete work item.”

**Correct design:**
Gate failure must produce a **DemotionTicket** that becomes a concrete edit target in Layer 1, then drives a re-loop through GapQueue.

### 4) Demotion chain (gate/test/verify failure → ticket → L1 patch → GapQueue → re-loop)

### DemotionTicket schema (concrete)

```python
@dataclass
class DemotionTicket:
    ticket_id: str
    created_at: str
    run_id: str
    slice_id: str
    origin_layer: Literal["L1", "L2", "L3"]
    hop_trace: list[Literal["L1", "L2", "L3"]] = field(default_factory=list)

    source: Literal["ALGORITHMIC_GATE", "ARCH_GATE", "TEST_FAILURE", "LINEAGE", "REVIEW"]
    gate: str | None                 # which gate failed, if applicable

    target_layer: Literal["L1", "L2", "L3"]
    severity: Literal["BLOCKER", "MAJOR", "MINOR"]

    failing_pins: list[str] = field(default_factory=list)
    failing_atoms: list[str] = field(default_factory=list)
    failing_files: list[str] = field(default_factory=list)
    component_id: str | None = None
    symbol_span_anchors: list[dict] = field(default_factory=list)  # {file, symbol?, start_line?, end_line?}

    diagnosis: str = ""               # human-readable root cause
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

### When DemotionTickets are created

Create tickets when:

* Investigator cannot fix within legality/budget
* gate failure indicates illegal change required in current layer
* VerifyStep governance FAIL (block immediately)
* diff-impact classifier says behavior_change (L3→L1) or wiring_only (L3→L2)

Tickets must include:

* hop trace
* failing files/pins/atoms where available
* evidence refs (logs, verify notes, reviewer output)

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

This replaces “skipped_atoms” with “demote-and-loop.”

---

## System overview

### Actors

* **Slice Agents (one per library slice)**
  Implement directly from spec comments in their slice worktree. When blocked, they **stop** and emit a **signal**.
* **Reactive Planner (triage authority)**
  Only runs when it receives a signal. It **matches the need to spec text work items**, decides: *already being worked / unrouted / underspecified*, then **registers a JIT monitor** and returns.
* **Monitor Executor (runtime)**
  Runs monitors (poll + event-triggered). When a monitor condition is met, it emits a **wake event**.
* **Scheduler / PromotionLoop runtime**
  Runs slices. If a slice returns `WAITING`, it is removed from the worker pool. When a wake event arrives, the slice is re-queued.

### Key invariants (aligned to your constraints)

* **No L1 pre-plan**: L1 `PLAN` is a no-op. L1 implementation is driven by spec comments in skeleton files.
* **Work items are spec text**: the primary coordination key is **verbatim spec comment text** (plus location metadata for disambiguation).
* **Agents don’t coordinate**: agents never reference other agents, monitors, or routing logic; they only implement or emit signals.
* **Git is the communication channel**: monitors check state on the **shared branch** (layer dirty), not in-memory assumptions.

---

## Q1: Signal format and emission protocol

### Design goal

Signals must be:

* **Structured enough** for deterministic triage + monitor generation
* **Flexible enough** for edge cases (free-form payload)
* **Grounded**: every signal includes *the exact spec text that triggered it* and the *exact local code anchor*.

### Recommended format: versioned JSON envelope with flexible payload

Use a single required schema + `payload` for extensibility.

#### `CoordinationSignal` (JSON)

```json
{
  "signal_version": 1,
  "signal_id": "sig_9a3c2f7a1b2e",
  "run_id": "run_2026_02_12_001",
  "layer": "l1",
  "slice_id": "LIB-01",
  "iteration": 3,

  "status": "HALT",
  "classification": "MISSING_INTERFACE",

  "need": {
    "summary": "Need RiskEngine.check_exposure interface to implement settlement exposure check",
    "artifact_type": "git_symbol",
    "artifact_key": "RiskEngine.check_exposure",
    "expected_shape": {
      "kind": "callable",
      "signature_hint": "def check_exposure(self, tx: Transaction) -> ExposureResult"
    },
    "confidence": 0.7
  },

  "spec_refs": [
    {
      "spec_text": "Reject settlement when risk engine exposure exceeds limits.",
      "source_file": "libraries/settlement/processor.py",
      "source_symbol": "SettlementProcessor.process",
      "source_line_hint": 142
    }
  ],

  "local_context": {
    "blocked_function": {
      "file": "libraries/settlement/processor.py",
      "symbol": "SettlementProcessor.process",
      "signature_line": "def process(self, instruction: SettlementInstruction) -> Receipt:"
    },
    "attempted_approach": "Call RiskEngine.check_exposure(...) before committing settlement."
  },

  "progress": {
    "functions_implemented": 7,
    "functions_skipped": 1,
    "worktree_branch": "pdd/run_2026_02_12_001/l1/slice/LIB-01/ab12cd",
    "latest_commit": "c0ffee42",
    "artifacts": {
      "patch_path": ".pdd_runs/.../iter_003/patch.diff",
      "notes_path": ".pdd_runs/.../iter_003/notes.md"
    }
  },

  "search_hints": {
    "keywords": ["RiskEngine", "exposure", "check_exposure"],
    "possible_owner_slices": ["LIB-02"]
  },

  "payload": {}
}
```

### Why this structure works

* **Planner-critical fields are stable**: `classification`, `need`, `spec_refs`, `progress`.
* **Search is spec-text-first**: `spec_refs[].spec_text` is verbatim and can be matched across work items.
* **Not overly rigid**: `payload` can carry any additional detail without schema churn.

### Emission protocol

1. **Agent implements sequentially** (per function) until it hits a blocker.
2. On blocker:

   * It **does not** implement the blocked function (no guessing).
   * It emits **exactly one signal per blocker root-cause** (often 1).
3. ImplementationRunner writes:

   * `iter_NNN/signals.json` (array)
   * `iter_NNN/signal_<signal_id>.md` (optional human-readable)
4. PromotionLoop:

   * Commits partial progress to the slice branch (if any).
   * Calls reactive planner triage.
   * Returns `SliceResult(status="WAITING")`.

## Q2: Spec text search for dependency matching

### What the planner must do

Given a signal like “Need TransactionValidator interface,” the planner must find the relevant **work item(s)** whose **spec text** implies that interface exists / must be implemented.

### Recommended search: 3-stage retrieval (deterministic → fuzzy → semantic)

#### Stage A: Exact/fingerprint match (fast path)

* Normalize spec text: lowercase, trim, collapse whitespace
* Compute `spec_fingerprint = sha256(normalized_text)[:12]`
* If signal includes the exact spec text, match by fingerprint.

This covers the common case: signal references a spec comment that already exists as a work item.

#### Stage B: Fuzzy lexical match (cheap)

Index each work item with:

* `spec_text`
* `location.file`, `location.symbol` (if available)
* extracted tokens:

  * snake_case & CamelCase tokens
  * error words (“reject”, “validate”, “schema”, “currency”)

Use a score like:

* token overlap (Jaccard)
* trigram similarity (for typos)
* substring boost for symbol-like strings (`RiskEngine`, `validate_schema`)

#### Stage C: LLM semantic rerank (only on top-K)

When wording differs (“validation interface” vs “reject invalid currency codes”), lexical can fail.

Use LLM reranking on top-K lexical candidates:

* Input: signal.need.summary + spec_refs + top 20 candidate work items (spec text + location)
* Output: best match set + confidence + “why” + “missing coverage?”

This keeps the system language-agnostic and avoids an explicit dependency graph.

### Indexing work items

Create a persistent store (workspace-level, not per-slice) with:

* `work_item_id` (hash)
* `spec_text` (verbatim)
* `owner_slice_id` (library slice)
* `status` (`NEW|ASSIGNED|IN_PROGRESS|MERGED|DONE|BLOCKED`)
* `location` metadata

Persist as JSONL for append-only audit + easy recovery:

* `.pdd_runs/<run_id>/coordination/work_items.jsonl`
* plus a compact index: `.pdd_runs/<run_id>/coordination/work_items_index.json`

### Handling “worded differently”

Use a **two-channel query** built from the signal:

* **Spec-text channel**: exact `spec_refs[].spec_text`
* **Artifact channel**: `need.artifact_key` and symbol-like tokens

Even if the work item says “Schema validation rejects instructions with invalid currency codes,” it likely includes tokens like:

* `schema`, `validation`, `reject`, `currency`
  which align with the artifact channel.

### Multiple partial matches

If multiple candidates match:

1. LLM reranker returns:

   * `primary_match`
   * `secondary_matches`
   * `coverage = FULL|PARTIAL|NONE`
2. Planner action:

   * If **FULL**: wait on primary (monitor checks the artifact).
   * If **PARTIAL**: create a *compound monitor* (OR condition) or route a new “interface contract” work item to eliminate ambiguity.
   * If **NONE**: treat as unrouted/underspecified.

## Q3: JIT monitor script system

### Recommendation: declarative monitor DSL + safe executor

Use JSON “scripts” (a DSL), not arbitrary Python or shell.

This satisfies:

* “Planner writes arbitrary condition scripts” (the planner can express many conditions)
* Safety: no destructive operations
* Portability: no OS dependencies
* Auditability: monitors are data, not code

### MonitorSpec format

```json
{
  "monitor_version": 1,
  "monitor_id": "mon_4d21b8c9",
  "run_id": "run_2026_02_12_001",

  "waiting_slice": { "layer": "l1", "slice_id": "LIB-01" },
  "signal_id": "sig_9a3c2f7a1b2e",

  "condition": {
    "type": "git_symbol_exists",
    "ref": "pdd/run_2026_02_12_001/l1/dirty",
    "file_glob": "libraries/**.py",
    "symbol_fqn": "RiskEngine.check_exposure",
    "signature_regex": "def\\s+check_exposure\\s*\\("
  },

  "execution": {
    "mode": "hybrid",
    "poll_interval_sec": 20,
    "event_triggers": ["GIT_DIRTY_ADVANCED", "SLICE_MERGED"]
  },

  "timeout": {
    "timeout_sec": 7200,
    "on_timeout": "ESCALATE"
  },

  "wake": {
    "action": "WAKE_SLICE",
    "payload": {
      "reason": "Dependency now present on shared branch",
      "artifact_key": "RiskEngine.check_exposure"
    }
  },

  "status": {
    "state": "ACTIVE",
    "created_at": "2026-02-12T07:23:11Z",
    "last_checked_at": null,
    "failures": 0
  }
}
```

### Execution model: hybrid (event-driven + polling fallback)

* **Event-driven** when possible:

  * WorktreeManager emits events when:

    * a slice is merged to dirty
    * dirty advances (new HEAD)
  * MonitorExecutor runs monitors subscribed to those events immediately.
* **Polling fallback**:

  * Periodic checks handle missed events and external updates (e.g., user adds constraints).

### What monitors can access

Monitors should access only **read-only views**:

* Git refs/branches: `git show`, `git grep`, `git ls-tree`
* File contents at a ref
* Work item store status
* Constraint files under `analysis/constraints/`
* Slice status registry

### Safety constraints (must-have)

* Monitor executor runs only **whitelisted condition types**.
* No arbitrary command execution.
* No repo writes. (Executor refuses `git checkout`, `git merge`, etc.)
* Writes are limited to:

  * updating monitor status files
  * writing wake events
  * writing logs/receipts in `.pdd_runs/...`

### Lifecycle management

* **Register**: planner writes monitor spec file to:

  * `.pdd_runs/<run_id>/coordination/monitors/<monitor_id>.json`
* **Track**: MonitorRegistry maintains:

  * active monitors
  * mapping: `slice_id -> [monitor_id]`
  * mapping: `signal_id -> monitor_id`
* **Fire**: when condition becomes true:

  * mark monitor `FIRED`
  * emit wake event
* **Cleanup**:

  * when slice resumes, remove/close monitors associated with that signal
  * keep an immutable receipt record for audit

### Failure handling

* If a monitor check throws:

  * increment `failures`
  * exponential backoff on polling interval
  * if failures exceed threshold (e.g., 5), escalate:

    * emit a new planner signal: `MONITOR_FAILED`
* If condition never met by timeout:

  * escalate to planner for re-triage:

    * maybe the provider slice never got routed
    * maybe interface changed
    * maybe cycle exists

## Q4: “Wake agent” mechanics

### Key interpretation: agents are not long-running processes

In this system, “agent” = “a slice run that invokes an LLM implementor.”
So waking means **re-queueing the slice** to run again with updated repo state and additional context.

### Wake protocol

1. Monitor fires -> writes a `WakeEvent`:

   * `.pdd_runs/<run_id>/coordination/wake_events/wake_<timestamp>_<slice_id>.json`
2. Scheduler consumes wake event:

   * moves slice from `WAITING` set to `READY` queue
3. Before resuming:

   * **sync slice worktree** with shared dirty:

     * `git fetch origin`
     * `git rebase pdd/<run_id>/<layer>/dirty` (preferred)
     * if rebase conflict -> emit `MERGE_CONFLICT` signal and go back to triage
4. Resume the PromotionLoop for that slice:

   * new iteration number (simple, auditable)
   * previous signal + wake payload is appended to bundle context (`bundle.under_spec.decisions` or a new `bundle.coordination` section)

### What state is restored

* The slice’s **git branch** already contains partial progress commits.
* The evidence bundle history persists on disk.
* The new run includes:

  * `last_signal_id`
  * `wake_payload` (what changed: commit SHA, artifact found, constraint added)
  * optional: pointer to the provider’s merge commit for context

### Continue vs rerun-from-scratch

PromotionLoop reruns from the top of an iteration, but because:

* functions already implemented are no longer “unresolved”
* gaps are recomputed
  the effect is **continue-from-where-stopped**, without fragile in-memory checkpointing.

## Q5: PromotionLoop changes (reactive model)

### L1 step sequence change

Current:
`COLLECT_BASELINE → GAP_EXPLORATION → PLAN → IMPLEMENT → UNDER_SPEC → ...`

New for L1:
`COLLECT_BASELINE → GAP_EXPLORATION → IMPLEMENT → COORDINATE → (WAITING | ANALYZE → PROMOTE → INTEGRATE → VERIFY → ALIGN)`

### Required new states

Add:

* `StepResult.status = "WAITING"`
* `SliceResult.status = "WAITING"`

“WAITING” is not “BLOCKED”:

* **BLOCKED** = unresolvable without human decision or spec change (terminal for scheduler unless user acts)
* **WAITING** = resolvable by expected future condition (monitor-based)

### PLAN step behavior

* For `ctx.layer == "l1"`:

  * `PlanStep.run()` returns `NOOP` (or `OK` with empty plan)
  * skip planning gate (pre-implementation constraints check), because L1 must block *during* implementation, not before

### IMPLEMENT step behavior (L1)

* L1 `ImplementStep` must run even if `bundle.plan.intentions` is empty.
* It should run if there are L1 gaps or unresolved functions.

### New “COORDINATE” step

Replace `UnderSpecCheckStep` (or make it layer-conditional):

* For L1: treat `bundle.implementation.under_spec_events` as **signals**
* Call reactive planner triage
* Register monitors
* Return `WAITING`

For L2/L3: keep existing under-spec behavior (block/resolve constraints), optionally also supporting monitors for external deps.

### Convergence logic changes

* If a slice returns `WAITING`, PromotionLoop exits early and saves bundle.
* Stagnation detection should ignore `WAITING` iterations or track separately (otherwise waiting looks like stagnation).
* Max iteration budget should also have a **max-wake budget**:

  * e.g., `max_wait_cycles = 10` before escalation.

## Q6: Parallel coordination via shared branch

### Merge protocol (shared dirty)

* Producer slice merges to `pdd/<run_id>/<layer>/dirty` using `WorktreeManager.merge_slice_to_dirty`.
* Merge operations must be serialized (single integration lock), because they mutate the shared branch.
* After merge:

  * WorktreeManager emits events: `SLICE_MERGED` and `GIT_DIRTY_ADVANCED`.
  * MonitorExecutor runs subscribed monitors.

### Pull protocol (consumer on wake)

On wake, consumer slice must incorporate new dirty HEAD:

* `git fetch origin`
* `git rebase pdd/<run_id>/<layer>/dirty` (preferred)
* if conflict: emit `MERGE_CONFLICT` signal -> planner triage

### Interface mismatch (provider changed signature)

Expected:

* Monitor triggers on “symbol exists,” but consumer may still fail if signature differs.

Handling:

1. Consumer resumes and re-attempts; if mismatch remains, it emits a new signal:

   * `classification = INTERFACE_MISMATCH`
   * includes:

     * expected signature hint (from prior attempt)
     * observed signature snippet (from shared branch grep/show)
2. Planner triage chooses:

   * route consumer adaptation work item
   * or route provider interface correction
   * or spec expansion to formalize interface contract

### Circular dependencies

A<->B can deadlock if both wait on each other.

Prevention/detection:

* Maintain a runtime **wait graph**:

  * nodes: slices
  * edges: “slice X waiting on artifact owned by slice Y”
* When adding a new wait edge, detect cycles.
* If cycle detected:

  * planner creates a **contract-breaking work item**:

    * “Define minimal interface stub for X->Y dependency in provider slice”
  * route that stub to one side (or a designated “contract authority” slice)
  * monitor on stub merge, then both can proceed

Cycle-breaking rule:

* “Interface-first commits” are allowed and encouraged:

  * add signature + doc/spec comments + `raise NotImplementedError` (or placeholder) only if the spec supports it
  * then fill implementation after consumers integrate

## Q7: Planner triage: already specified vs needs routing vs underspecified

### Triage decision procedure (deterministic first, LLM second)

Given a signal S:

1. **Search work items** (spec-text-first + artifact channel)
2. If strong coverage match exists:

   * If match is assigned/in-progress:

     * schedule monitor on **git artifact presence** (preferred) or work-item completion
   * If match is already merged/done:

     * schedule monitor that will fire immediately (or wake immediately) and instruct consumer to rebase/pull
3. If no work item match:

   * Search **full spec catalog** (all spec comments in repo)
   * If spec exists but is not routed:

     * create/rout a work item to correct owner slice
     * schedule monitor
4. If not found in spec at all:

   * mark **underspecified**
   * initiate **spec expansion** (see Q8)
   * route expansion work item
   * schedule monitor

### Distinguishing “unrouted” vs “partial coverage”

Use a coverage classifier:

* Input: signal.need + top spec matches
* Output:

  * `FULL_COVERAGE` / `PARTIAL_COVERAGE` / `NO_COVERAGE`
  * plus: “what missing detail is required?”

Rule:

* **Unrouted**: a spec comment exists that *directly* names the artifact or behavior, but no work item maps to it (or it’s assigned to the wrong slice).
* **Partial coverage**: spec mentions something related but does not define the interface/behavior needed to implement the blocked function.
* **Underspecified**: no spec text implies the artifact/behavior at all.

Yes: this classification should use an LLM when uncertain. Use deterministic heuristics only to prune candidates.

## Q8: Spec expansion mechanism

### What “expand the spec” means mechanically

Expansion must end up as one of:

1. **New spec comments** added to skeleton files (preferred, preserves “code is spec”)
2. **New stub function(s)** with spec comments (when an interface is missing)
3. **Constraint entries** (when the missing piece is a decision, not code)

### Who produces the expansion

Planner does not directly edit code in-place. It:

* creates a **spec expansion work item** (spec text)
* routes it to the appropriate slice agent (usually the provider slice)

### Validation of expansion (prevent drift)

Use the already-implemented QA/scoring architecture:

* Multi-model proposal (3 models if in auto mode)
* Consistency check against existing spec text
* Require explicit provenance:

  * “Expansion created to resolve signal_id X”
  * include citations to existing spec_refs that motivated the change
* If confidence low or contradictions detected:

  * block in interactive mode (user must approve/steer)

### Expansion feedback loop

* Planner routes expansion work item -> provider agent implements (adds stub/spec + implementation) -> merges to dirty -> monitor fires -> consumer wakes.

## Q9: Integration with existing systems

### WorktreeManager integration

* Add event hooks after merge and scheduler ticks so monitors can react immediately (`SLICE_MERGED`, `GIT_DIRTY_ADVANCED`).

### ImplementationRunner integration

* On halt/blocker, emit structured `CoordinationSignal` envelopes (or embed required fields inside existing `under_spec_events` during migration).
* Persist emitted signals in the iteration directory via `iter_NNN/signals.json`.

### UnderSpecManager integration

* Reuse `UnderSpecManager` for "needs decision" signals by routing them through `constraint_present` monitors.

### Planner integration

* Add a reactive triage capability (new `TRIAGE_SIGNAL` or broadened `RESOLVE_SIGNAL`) without reintroducing an L1 pre-plan gate.
* Add `Planner.triage_signal(context, signal)` as a convenience adapter.

## Q10: Concrete implementation plan (files to create/modify)

### Create new package: `orchestration/coordination/`

* `signals.py`

  * `CoordinationSignal` parse/serialize
  * `signals.json` writer/reader
* `work_items.py`

  * `WorkItem` (id, spec_text, owner_slice, status, location, tags)
  * `WorkItemStore` (JSONL + compact index)
  * `search()` implementing exact/fuzzy/semantic stages + candidate pack for LLM rerank
* `monitors.py`

  * `MonitorSpec`
  * condition checkers (`git_symbol_exists`, `work_item_done`, `constraint_present`, etc.)
* `monitor_executor.py`

  * hybrid event/poll runtime
  * writes wake events
* `wake_queue.py`

  * file-based wake event enqueue/dequeue
* `wait_graph.py`

  * cycle detection for active waits

### Modify `orchestration/promotion_loop.py`

* Extend `StepResult.status` and `SliceResult.status` with `WAITING`.
* Make L1 `PlanStep.run()` a no-op (skip planning gate).
* Make L1 `ImplementStep.run()` execute without requiring `bundle.plan.intentions`.
* Replace `UnderSpecCheckStep` with `CoordinateStep`:

  * calls planner triage on signals
  * registers monitors
  * returns `WAITING` when monitors exist

### Modify `orchestration/promotion_scheduler.py`

* Replace with (or add) `ReactivePromotionScheduler` that:

  * supports `WAITING` slices
  * runs `MonitorExecutor` concurrently
  * re-queues slices on wake events
  * terminates when all slices are COMPLETE or terminally BLOCKED/FAILED

### Modify `orchestration/pdd_lifecycle.py`

* Use `ReactivePromotionScheduler` for L1 (optionally all layers).
* Tie monitor-executor lifecycle to each layer run.

### Modify `planner/api.py` and `planner/router.py`

* Add a triage capability (`TRIAGE_SIGNAL` or broadened `RESOLVE_SIGNAL`).
* Add `Planner.triage_signal(context, signal)` convenience adapter.
* Ensure L1 planner triage:

  * uses `WorkItemStore` + spec catalog + optional LLM rerank
  * outputs routing decisions + monitor specs

### Modify `orchestration/implementation/runner.py` and `implementation/types.py`

* Update implementor output contract so under-spec output uses the `CoordinationSignal` envelope shape (or carries equivalent required fields inside legacy `under_spec_events` during migration).
* Write `signals.json` in the iteration directory.

### Migration strategy (no big-bang)

1. Add `WAITING` status plumbing + wake queue + monitor executor (initially only `constraint_present` monitors).
2. Make L1 PLAN a no-op and allow L1 IMPLEMENT without plan intentions.
3. Add COORDINATE step that:

   * handles legacy under-spec events
   * schedules simple monitors (`constraint_present`, `git_symbol_exists`)
4. Add work item store + search + LLM reranker.
5. Replace scheduler with reactive version.

### Shortest path to first working reactive behavior

* Implement `WAITING` + `constraint_present` monitors + `git_symbol_exists` monitors first.
* Add work-item search/routing next.
* Add spec expansion last.

---

# 1) Planning Module architecture (core abstractions, API, and how it replaces AutoResponder/AutoSignalResolver)

## 1) Intent Agent architecture

### 1.1 Role and hard authority boundary

**Intent Agent** is the only user-facing interface. It mediates all interaction for the entire lifecycle.

**Planner** is the single constraint and decision authority.

This boundary is non-negotiable:

* **Intent Agent may persist**:

  * Question queue state (open/closed/stale)
  * `question_id → canonical_key` mapping (for dedup/reassessment)
  * User-facing framing metadata (problem frame, concept map, scope)
  * Answer provenance (raw user answers and what question they answered)
  * Skeleton revision state

* **Intent Agent must not own or write**:

  * Constraint objects (authoritative or hypothetical)
  * Tradeoff positions as decision records
  * Any “final” planning decisions
  * Architectural decisions beyond what authority policy delegates
  * Slice scheduling and worker coordination
  * Implementation-detail choices unless the user explicitly constrains them

Instead:

* Intent Agent produces an **AnswerTranslation artifact** (a projection of user input).
* Planner ingests that artifact, validates it, decides what becomes authoritative, and writes to **ConstraintsStore** / decision records.
* Intent Agent **observes** what Planner wrote (via store-change signals/watermarks) and updates the question queue.

### 1.2 Component model

**Deterministic orchestrator + LLM strategies**, with progressive gates.

**IntentAgentOrchestrator (deterministic)**

* Event loop: handles user messages + internal question signals + store-change signals.
* Maintains queue ordering, deduplication, staleness, batching.
* Calls LLM strategies for interpretation/rewriting only.
* Persists session state and event log.

**LLM strategies (pluggable, bounded responsibilities)**

* `IntentFrameStrategy`: update problem frame from user text.
* `ConceptMapStrategy`: maintain mapping between user terms and normalized concepts.
* `QuestionDraftStrategy`: convert internal question signals into user-facing question drafts (constraint-level).
* `QualityValidatorStrategy`: enforce question quality gate (pass/fail + reasons).
* `QuestionRepairStrategy`: repair failed drafts (up to 2 retries).
* `AnswerTranslateStrategy`: convert a user answer into an AnswerTranslation artifact (non-authoritative).
* `QueueReassessStrategy`: re-evaluate pending questions after Planner writes constraints/decisions.
* `SkeletonSynthesisStrategy`: produce pre-decomposition skeleton artifacts (workflows/entities/interfaces).
* `UnknownsStrategy` (optional intake assist): generate/refresh candidate unknowns to ask about (proportional depth).
* `RedefinitionDetectStrategy` (optional, execution-heavy flows): detect meaningful drift between original intent and evolving plan.

**State stores (file-backed, append-only where it matters)**

* `IntentSessionStore` (snapshot JSON).
* `IntentEventLog` (append-only JSONL: user messages, internal signals, answers, queue mutations).
* `QuestionQueueStore` (snapshot + optional JSONL mutations).

### 1.3 Intent Agent state model (corrected)

Intent Agent state is **user-interface state**, not constraint authority.

**Persistent artifacts**

* Snapshot: `.pdd_runs/<run_id>/intent/session_state.json`
* Append-only log: `.pdd_runs/<run_id>/intent/events.jsonl`
* Queue snapshot: `.pdd_runs/<run_id>/intent/question_queue.json`
* Raw answers: `.pdd_runs/<run_id>/intent/answers.jsonl`
* Answer translations (projection to Planner): `.pdd_runs/<run_id>/intent/answer_translations/<translation_id>.json`
* Skeleton outputs: `.pdd_runs/<run_id>/intent/skeleton/...`
* Planner question signal source (read-only): `.pdd_runs/<run_id>/coordination/user_questions.jsonl`
* Exportable pipeline snapshot (derived): `analysis/intent/intent_snapshot.json`

**State includes**

* Problem frame + scope
* Concept map + allowed vocabulary (user-introduced terms)
* Queue state + `question_id → canonical_key` map
* Answer provenance (raw answers + which translation was produced)
* Watermarks to observe:

  * new internal question signals
  * Planner constraint/decision updates (via signals or store revision)

#### JSON Schema: IntentSessionState

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://spec-manager.local/schemas/IntentSessionState.schema.json",
  "title": "IntentSessionState",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "version",
    "run_id",
    "session_id",
    "phase",
    "original_intent",
    "problem_frame",
    "concept_map",
    "question_queue_state",
    "question_key_map",
    "answer_provenance",
    "skeleton_state",
    "watermarks"
  ],
  "properties": {
    "version": { "type": "integer", "minimum": 1 },
    "run_id": { "type": "string", "minLength": 1 },
    "session_id": { "type": "string", "minLength": 1 },

    "phase": {
      "type": "string",
      "enum": ["INTAKE", "EXECUTION"]
    },

    "original_intent": {
      "type": "object",
      "additionalProperties": false,
      "required": ["user_statement", "captured_at"],
      "properties": {
        "user_statement": { "type": "string" },
        "captured_at": { "type": "string", "format": "date-time" }
      }
    },

    "problem_frame": {
      "type": "object",
      "additionalProperties": false,
      "required": ["current_restatement", "goals", "non_goals", "scope", "success_metrics"],
      "properties": {
        "current_restatement": { "type": "string" },
        "goals": { "type": "array", "items": { "type": "string" } },
        "non_goals": { "type": "array", "items": { "type": "string" } },
        "scope": {
          "type": "object",
          "additionalProperties": false,
          "required": ["in", "out"],
          "properties": {
            "in": { "type": "array", "items": { "type": "string" } },
            "out": { "type": "array", "items": { "type": "string" } }
          }
        },
        "success_metrics": { "type": "array", "items": { "type": "string" } },
        "risk_flags": { "type": "array", "items": { "type": "string" } },

        "frame_assumptions": {
          "type": "array",
          "description": "Non-authoritative framing assumptions (not constraints).",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["text", "status", "source", "created_at"],
            "properties": {
              "text": { "type": "string" },
              "status": { "type": "string", "enum": ["HYPOTHESIS", "CONFIRMED", "REJECTED"] },
              "source": { "type": "string", "enum": ["user", "intent_agent"] },
              "created_at": { "type": "string", "format": "date-time" }
            }
          }
        }
      }
    },

    "concept_map": {
      "type": "object",
      "additionalProperties": false,
      "required": ["user_terms", "normalized_terms", "user_introduced_terms"],
      "properties": {
        "user_terms": {
          "type": "object",
          "additionalProperties": {
            "type": "object",
            "additionalProperties": false,
            "required": ["maps_to", "confidence"],
            "properties": {
              "maps_to": { "type": "array", "items": { "type": "string" } },
              "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
            }
          }
        },
        "normalized_terms": {
          "type": "object",
          "additionalProperties": {
            "type": "object",
            "additionalProperties": false,
            "required": ["user_phrases"],
            "properties": {
              "user_phrases": { "type": "array", "items": { "type": "string" } }
            }
          }
        },
        "user_introduced_terms": {
          "type": "array",
          "description": "Vocabulary terms the user has used; technical terms are only allowed in questions if present here.",
          "items": { "type": "string" }
        }
      }
    },

    "question_queue_state": {
      "type": "object",
      "additionalProperties": false,
      "required": ["open_ids", "closed_ids", "stale_ids", "last_presented_question_id"],
      "properties": {
        "open_ids": { "type": "array", "items": { "type": "string" } },
        "closed_ids": { "type": "array", "items": { "type": "string" } },
        "stale_ids": { "type": "array", "items": { "type": "string" } },
        "last_presented_question_id": { "type": "string" },
        "active_batch_id": { "type": "string" }
      }
    },

    "question_key_map": {
      "type": "object",
      "description": "Intent Agent-owned references (not constraint objects).",
      "additionalProperties": {
        "type": "object",
        "additionalProperties": false,
        "required": ["canonical_key"],
        "properties": {
          "canonical_key": { "type": "string" },
          "planner_constraint_ids": { "type": "array", "items": { "type": "string" } },
          "planner_decision_ids": { "type": "array", "items": { "type": "string" } }
        }
      }
    },

    "answer_provenance": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["answer_id", "question_id", "raw_text", "created_at"],
        "properties": {
          "answer_id": { "type": "string" },
          "question_id": { "type": "string" },
          "raw_text": { "type": "string" },
          "created_at": { "type": "string", "format": "date-time" },
          "answer_translation_ref": { "type": "string" },
          "planner_ingest_trace_id": { "type": "string" }
        }
      }
    },

    "skeleton_state": {
      "type": "object",
      "additionalProperties": false,
      "required": ["revision", "structure_kind", "artifact_paths", "last_generated_at"],
      "properties": {
        "revision": { "type": "integer", "minimum": 0 },
        "structure_kind": { "type": "string", "enum": ["PRE_DECOMPOSITION", "PHASE0_LIBRARIES"] },
        "artifact_paths": { "type": "array", "items": { "type": "string" } },
        "last_generated_at": { "type": "string", "format": "date-time" }
      }
    },

    "watermarks": {
      "type": "object",
      "additionalProperties": false,
      "required": ["user_question_signal_watermark", "planner_update_watermark"],
      "properties": {
        "user_question_signal_watermark": { "type": "string" },
        "planner_update_watermark": { "type": "string" }
      }
    }
  }
}
```

### 1.4 Persistence and resumption

#### 1.4.1 What is saved

* Intent session snapshot in `session_state.json` (no constraint objects)
* Event logs:

  * user messages
  * question signals received
  * quality gate records
  * answers and translations produced
  * queue reassessment actions
* Queue snapshot (including open/closed/stale IDs and batch metadata)
* Skeleton revisions and artifact path references
* Watermarks used to observe new signals:

  * `user_question_signal_watermark`
  * `planner_update_watermark`

#### 1.4.2 Resume behavior

Resumption is deterministic and queue-consistent:

1. Load `session_state.json`.
2. Read any new **UserQuestionSignals** since `user_question_signal_watermark`.
3. Read any new **Planner update signals** (constraint/decision saved events) since `planner_update_watermark`.
4. Show pipeline progress since the last session (from planner update signals and slice status if available).
5. Re-run reassessment against the latest Planner updates, then recompute queue ordering and staleness.
6. Present the next highest-priority question (or batch).
7. Optionally show a short "next up" queue preview.

#### 1.4.3 Auto mode behavior (no human)

In `--auto` mode:

* Intent Agent may still generate internal questions, but user-facing prompts are not emitted; they are used to identify blocking unknowns and document why work cannot proceed.
* Questions requiring human authority remain unresolved.
* Planner either blocks or makes best-effort decisions only where authority policy permits.
* If pipeline advanced via policy-permitted auto resolution, mark corresponding questions as `ANSWERED` with provenance `"auto resolution"`.
* If any decision was taken without user authority, emit an explicit `Review decision` question item.

### 1.5 Relationship to Planner and pipeline (clarified)

**Intent Agent is a layer above the Planner.**

**Planner owns:**

* Constraint lifecycle (collection → enrichment → authority decision → propagation)
* Decision authority policy
* Writing to `ConstraintsStore`
* Writing decision records (tradeoffs, architecture choices)
* Emitting store-update signals

**Intent Agent owns:**

* User interaction and question quality enforcement
* Translating user answers into **AnswerTranslation** artifacts
* Submitting AnswerTranslations to Planner
* Observing Planner outputs and updating queue state/skeletons accordingly

**Answer flow is Planner-mediated** (details in Section 4).

Interaction points:

* **From user → system**: Intent Agent translates answers into **AnswerTranslation** artifacts, persists provenance, and signals wake.
* **From system → user**: Planner/internal agents emit question signals; Intent Agent dedups, prioritizes, and asks.

Question provenance stays explicit in one queue item type:

* `origin.kind` can be `"INTENT_AGENT"`, `"PLANNER"`, `"UNDER_SPEC"`, or `"PROMOTION_LOOP"`.
* Priority and wording may differ by origin, but lifecycle is identical.

---

## 2) Question queue design

### 2.1 QuestionItem model and hard quality gate fields

Queue items represent **underlying unknowns** in user-facing taxonomy types (Section 5.4). Internal-only questions never enter the user queue directly.

A question only enters the user queue if it:

* is classified as one of the 5 valid user-facing types, and
* passes the **mandatory quality gate** (Section 5.5)

`canonical_key` remains the stable dedup/reassessment handle and is inferred at ingest (LLM), not hardcoded templates.

#### JSON Schema: QuestionItem (with quality gate fields)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://spec-manager.local/schemas/QuestionItem.schema.json",
  "title": "QuestionItem",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "question_id",
    "status",
    "taxonomy_type",
    "scope_kind",
    "canonical_key",
    "user_prompt",
    "origins",
    "blockers",
    "priority",
    "quality_gate",
    "timestamps"
  ],
  "properties": {
    "question_id": { "type": "string", "minLength": 1 },

    "status": {
      "type": "string",
      "enum": ["OPEN", "ANSWERED", "STALE", "SUPERSEDED", "DISMISSED", "UNASKABLE"]
    },

    "taxonomy_type": {
      "type": "string",
      "enum": ["INTENT", "CONSTRAINT", "TRADEOFF", "SCOPE", "VALIDATION"]
    },

    "scope_kind": {
      "type": "string",
      "enum": ["SYSTEM_WIDE", "FEATURE_SPECIFIC"]
    },

    "canonical_key": {
      "type": "string",
      "description": "Stable key for dedup/reassessment. Reference only; not a constraint object."
    },

    "user_prompt": {
      "type": "object",
      "additionalProperties": false,
      "required": ["text", "scenario", "why_it_matters", "answer_spec"],
      "properties": {
        "text": { "type": "string" },
        "scenario": { "type": "string", "description": "Concrete scenario grounding the question." },
        "why_it_matters": { "type": "string" },

        "answer_spec": {
          "type": "object",
          "additionalProperties": false,
          "required": ["kind"],
          "properties": {
            "kind": {
              "type": "string",
              "enum": ["choice", "yes_no", "value", "bounded_text"]
            },
            "choices": {
              "type": "array",
              "items": {
                "type": "object",
                "additionalProperties": false,
                "required": ["id", "label"],
                "properties": {
                  "id": { "type": "string" },
                  "label": { "type": "string" }
                }
              }
            },
            "value_type": {
              "type": "string",
              "enum": ["integer", "number", "currency", "duration", "date", "string"]
            },
            "units_hint": { "type": "string" },
            "text_bounds": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "max_items": { "type": "integer", "minimum": 1 },
                "max_chars": { "type": "integer", "minimum": 1 }
              }
            }
          }
        }
      }
    },

    "system_binding": {
      "type": "object",
      "additionalProperties": true,
      "properties": {
        "constraint_key_hints": { "type": "array", "items": { "type": "string" } },
        "decision_requirement_ids": { "type": "array", "items": { "type": "string" } },
        "work_items": { "type": "array", "items": { "type": "string" } }
      }
    },

    "origins": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["source_kind", "created_at"],
        "properties": {
          "source_kind": {
            "type": "string",
            "enum": ["PLANNER", "UNDER_SPEC", "PROMOTION_LOOP", "PDD_LIFECYCLE", "INTENT_AGENT", "SLICE_AGENT"]
          },
          "trace_id": { "type": "string" },
          "signal_id": { "type": "string" },
          "slice_id": { "type": "string" },
          "layer": { "type": "string" },
          "created_at": { "type": "string", "format": "date-time" },

          "spec_refs": {
            "type": "array",
            "items": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "spec_text": { "type": "string" },
                "source_file": { "type": "string" },
                "source_line_hint": { "type": "integer" }
              }
            }
          },

          "code_refs": {
            "type": "array",
            "items": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "file": { "type": "string" },
                "symbol": { "type": "string" },
                "line": { "type": "integer" }
              }
            }
          }
        }
      }
    },

    "blockers": {
      "type": "object",
      "additionalProperties": false,
      "required": ["severity", "blocked_slices"],
      "properties": {
        "severity": {
          "type": "string",
          "enum": ["BLOCKING", "HIGH_RISK", "MEDIUM_RISK", "INFO"]
        },
        "blocked_slices": { "type": "array", "items": { "type": "string" } },
        "blocked_layers": { "type": "array", "items": { "type": "string" } },
        "blocked_steps": { "type": "array", "items": { "type": "string" } }
      }
    },

    "priority": {
      "type": "object",
      "additionalProperties": false,
      "required": ["score", "explanation"],
      "properties": {
        "score": { "type": "number", "minimum": 0, "maximum": 1 },
        "explanation": { "type": "string" }
      }
    },

    "quality_gate": {
      "type": "object",
      "additionalProperties": false,
      "required": ["status", "attempts", "last_quality_record_id", "last_checked_at"],
      "properties": {
        "status": { "type": "string", "enum": ["PASS", "FAIL", "PENDING"] },
        "attempts": { "type": "integer", "minimum": 0 },
        "last_quality_record_id": { "type": "string" },
        "last_checked_at": { "type": "string", "format": "date-time" }
      }
    },

    "timestamps": {
      "type": "object",
      "additionalProperties": false,
      "required": ["created_at", "updated_at"],
      "properties": {
        "created_at": { "type": "string", "format": "date-time" },
        "updated_at": { "type": "string", "format": "date-time" }
      }
    }
  }
}
```

### 2.2 Priority model

Priority is a deterministic base score + optional LLM tie-break for top-K.

Deterministic features:

* number of blocked slices (more blocks → higher)
* severity (BLOCKING > HIGH_RISK > MEDIUM_RISK > INFO)
* scope kind (SYSTEM_WIDE > FEATURE_SPECIFIC)
* layer/stage criticality (planning-level blockers > late-stage style issues)
* staleness penalty (no remaining blockers → downrank)

LLM tie-break (top 5 only):

* “Which question unlocks the most progress with the least user burden?”
* LLM may reorder within the top 5, but should not promote clear low-impact items above known blockers without logged justification.

### 2.3 Reassessment algorithm (after Planner applies answers)

Reassessment is triggered by **Planner update signals** (constraint saved / decision recorded), not by the Intent Agent writing constraints.

Steps:

1. Receive Planner update signal(s) (or observe store revision change).
2. Mechanical pass:

   * If a question’s `canonical_key` is now mapped to one or more `planner_constraint_ids`, mark `ANSWERED`.
   * If all blockers cleared and severity is not HIGH_RISK, mark `STALE`.
3. LLM reassess pass (only for remaining OPEN where ambiguity remains):

   * Determine KEEP vs STALE vs SUPERSEDED vs REWORD based on updated frame and new authoritative store references.
4. Apply actions, persist `QueueReassessResult`, update `question_key_map` references.

#### JSON Schema: QueueReassessResult

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://spec-manager.local/schemas/QueueReassessResult.schema.json",
  "title": "QueueReassessResult",
  "type": "object",
  "additionalProperties": false,
  "required": ["version", "run_id", "session_id", "trigger", "created_at", "actions"],
  "properties": {
    "version": { "type": "integer", "minimum": 1 },
    "run_id": { "type": "string" },
    "session_id": { "type": "string" },

    "trigger": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "ref"],
      "properties": {
        "kind": { "type": "string", "enum": ["PLANNER_CONSTRAINT_SAVED", "PLANNER_DECISION_RECORDED", "USER_ANSWER_INGESTED"] },
        "ref": { "type": "string", "description": "Signal id, constraint id, decision id, or trace id." }
      }
    },

    "created_at": { "type": "string", "format": "date-time" },

    "actions": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["question_id", "action", "reason"],
        "properties": {
          "question_id": { "type": "string" },
          "action": { "type": "string", "enum": ["KEEP", "ANSWERED", "STALE", "SUPERSEDED", "REWORD", "DISMISSED"] },
          "reason": { "type": "string" },

          "replacement": {
            "type": "object",
            "additionalProperties": false,
            "properties": {
              "new_question_id": { "type": "string" },
              "new_canonical_key": { "type": "string" },
              "new_user_prompt_text": { "type": "string" }
            }
          }
        }
      }
    }
  }
}
```

### 2.4 Deduplication

Dedup is driven by `canonical_key` + semantic equivalence.

Dedup tiers:

1. Same canonical_key → merge origins/blockers; keep best prompt.
2. Same planner decision requirement id → merge.
3. Semantic match (LLM) among same taxonomy_type and same scope_kind.

Dedup never discards provenance: it merges `origins[]`.

### 2.5 Batching rules

Default: **one question per interaction**.

Batching allowed only when:

* 2–3 questions share the same domain concern and scope, and
* answering together reduces ambiguity, and
* all questions still individually pass the quality gate

Batch size limit: 3.

### 2.6 Staleness handling

A question becomes `STALE` (not deleted) when:

* no blocked slices remain and it isn’t HIGH_RISK, or
* it is superseded by a confirmed problem redefinition, or
* Planner recorded a decision/constraint that makes it irrelevant

Stale items remain in the log for auditability.

---

## 3) Signal flow from internal agents to Intent Agent

### 3.1 UserQuestionSignal type

Internal agents never talk to the user. They emit **UserQuestionSignal** events that request user input.

This is a projection across the boundary:

* internal context can be included for traceability
* the final user prompt is produced by Intent Agent and must pass the quality gate

This signal family is distinct from `CoordinationSignal` (inter-slice dependency waiting), but it uses the same file-based emit/react pattern to keep producers decoupled from the interface.

#### JSON Schema: UserQuestionSignal

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://spec-manager.local/schemas/UserQuestionSignal.schema.json",
  "title": "UserQuestionSignal",
  "type": "object",
  "additionalProperties": false,
  "required": ["uq_version", "uq_id", "run_id", "created_at", "source", "question", "context"],
  "properties": {
    "uq_version": { "type": "integer", "minimum": 1 },
    "uq_id": { "type": "string", "minLength": 1 },
    "run_id": { "type": "string", "minLength": 1 },
    "created_at": { "type": "string", "format": "date-time" },

    "source": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind"],
      "properties": {
        "kind": {
          "type": "string",
          "enum": ["PLANNER", "UNDER_SPEC", "PROMOTION_LOOP", "PDD_LIFECYCLE", "SLICE_AGENT"]
        },
        "trace_id": { "type": "string" },
        "slice_id": { "type": "string" },
        "layer": { "type": "string" },
        "signal_id": { "type": "string" }
      }
    },

    "question": {
      "type": "object",
      "additionalProperties": false,
      "required": ["text"],
      "properties": {
        "text": { "type": "string", "description": "Internal draft question text; may be technical." },

        "taxonomy_hint": {
          "type": "string",
          "description": "May include internal-only types; Intent Agent must reframe to user-valid types.",
          "enum": [
            "INTENT", "CONSTRAINT", "TRADEOFF", "SCOPE", "VALIDATION",
            "ARCHITECTURE", "IMPLEMENTATION", "DESIGN_PATTERN", "OPTIMIZATION",
            "UNKNOWN"
          ]
        },

        "canonical_key_hint": { "type": "string" },

        "answer_spec_hint": {
          "type": "object",
          "additionalProperties": true,
          "properties": {
            "preferred_kind": { "type": "string", "enum": ["choice", "yes_no", "value", "bounded_text"] },
            "choices": { "type": "array", "items": { "type": "string" } }
          }
        }
      }
    },

    "context": {
      "type": "object",
      "additionalProperties": false,
      "required": ["blocking"],
      "properties": {
        "blocking": {
          "type": "object",
          "additionalProperties": false,
          "required": ["severity", "blocked_slices"],
          "properties": {
            "severity": { "type": "string", "enum": ["BLOCKING", "HIGH_RISK", "MEDIUM_RISK", "INFO"] },
            "blocked_slices": { "type": "array", "items": { "type": "string" } }
          }
        },

        "spec_refs": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "properties": {
              "spec_text": { "type": "string" },
              "source_file": { "type": "string" },
              "source_line_hint": { "type": "integer" }
            }
          }
        },

        "code_refs": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "properties": {
              "file": { "type": "string" },
              "symbol": { "type": "string" },
              "line": { "type": "integer" }
            }
          }
        }
      }
    },

    "payload": {
      "type": "object",
      "description": "Extensible payload for planner-specific fields (decision requirement ids, etc.).",
      "additionalProperties": true
    }
  }
}
```

**Storage location**

* `.pdd_runs/<run_id>/coordination/user_questions.jsonl` (append-only)

### 3.2 Who emits UserQuestionSignal

* **Planner**

  * AuthorityDecider marks items `human_required`
  * QuestionComposer produces draft questions
  * Output of `QuestionComposerStrategy` maps into one or more `UserQuestionSignal`s
  * Planner emits UserQuestionSignals for each human-required unknown

* **UnderSpecManager**

  * When ambiguity cannot be resolved automatically
  * Emits UserQuestionSignals instead of running InteractiveWorkflow

* **PromotionLoop / PddLifecycle**

  * Lifecycle checkpoints become signals (Section 10)
  * No direct `input()` calls

* **Slice agents**

  * Rare; only when a slice has user-domain ambiguity
  * Must still be reframed into user-valid taxonomy types by Intent Agent
  * Agent never talks to the user directly

### 3.3 Intent Agent ingestion pipeline (signal -> queued question)

Intent Agent maintains a **watermark** (last processed byte offset or last `uq_id`/timestamp) and periodically reads new lines from `user_questions.jsonl`.

Pipeline is gated:

1. **Ingest** UserQuestionSignal
2. **Classify/reframe** into user-valid taxonomy type (Section 5.4)
3. **Normalize** / validate canonical key (using LLM if needed)
4. **Draft** user question with:

   * domain-language text
   * scenario
   * bounded answer_spec
5. **Quality gate** (Section 5.5)

   * PASS -> create QuestionItem and enqueue
   * FAIL -> repair up to 2 retries
   * FAIL after retries -> mark UNASKABLE and escalate back to Planner for reformulation or auto-resolution (never degrade and ask anyway)
6. **Queue update**

   * dedup against existing queue
   * compute priority and update queue state

### 3.4 Immediate vs queued vs self-resolve

* **Immediate ask**: only if queue is empty or current question is INFO and new question is BLOCKING.
* **Queued**: default.
* **Self-resolve**: only in `--auto` mode and only for questions that:

  * do not require human authority, and
  * can be resolved by research/tools with validation, and
  * can be confidently inferred from existing authoritative constraints, and
  * do not violate “block on ambiguity” (i.e., resolution must be supported and confidence-checked by Planner)

---

## 4) Answer flow from user back to agents

### 4.1 Planner-mediated answer lifecycle (required flow)

Correct flow:

```
User answers →
Intent Agent records raw answer provenance →
Intent Agent produces AnswerTranslation artifact →
Planner ingests AnswerTranslation →
Planner validates + decides what becomes authoritative →
Planner writes to ConstraintsStore / decision record store →
Planner emits update signals →
Intent Agent observes updates → marks questions answered/reassesses queue
```

Intent Agent never writes constraints.

### 4.2 Planner ingestion and validation responsibilities

Planner ingestion step must:

* validate translation artifact schema
* validate that the proposed constraints are:

  * in a user-valid taxonomy space (constraint/tradeoff/scope/validation/intent), and
  * consistent with existing authoritative constraints (or produce conflict resolution questions)
* apply authority policy:

  * user answers are authoritative inputs
  * planner-derived enrichments are non-authoritative unless sourced
* write accepted constraints into **ConstraintsStore**
* write decisions into a **DecisionRecordStore** (tradeoffs/architecture outcomes)
* emit update signals:

  * `constraint_saved`
  * `decision_recorded`

Intent Agent uses these signals to close questions.

### 4.3 AnswerTranslate recursion guard (mandatory)

`AnswerTranslateStrategy` may propose follow-up questions, but:

* Follow-ups must pass the **same quality gate** as all other questions.
* Recursion cap:

  * **max 2 follow-up questions per user answer** (across the full reassessment cycle)
* Follow-ups that fail quality gate after retries:

  * are routed to Planner for auto-resolution or reformulation
  * are not surfaced to the user as degraded questions

### 4.4 AnswerTranslation artifact

This artifact is a boundary projection: **non-authoritative**.

#### JSON Schema: AnswerTranslation

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://spec-manager.local/schemas/AnswerTranslation.schema.json",
  "title": "AnswerTranslation",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "version",
    "translation_id",
    "run_id",
    "session_id",
    "question_id",
    "answer_id",
    "created_at",
    "user_answer",
    "extracted",
    "recursion_budget",
    "provenance"
  ],
  "properties": {
    "version": { "type": "integer", "minimum": 1 },
    "translation_id": { "type": "string" },
    "run_id": { "type": "string" },
    "session_id": { "type": "string" },
    "question_id": { "type": "string" },
    "answer_id": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" },

    "user_answer": {
      "type": "object",
      "additionalProperties": false,
      "required": ["raw_text"],
      "properties": {
        "raw_text": { "type": "string" },
        "selected_choice_id": { "type": "string" },
        "parsed_values": { "type": "object", "additionalProperties": true }
      }
    },

    "extracted": {
      "type": "object",
      "additionalProperties": false,
      "required": ["constraint_candidates", "scope_candidates", "tradeoff_candidates", "validation_candidates", "followup_question_drafts"],
      "properties": {
        "constraint_candidates": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["canonical_key_hint", "question", "answer", "scope_kind", "confidence"],
            "properties": {
              "canonical_key_hint": { "type": "string" },
              "question": { "type": "string", "description": "Proposed constraint question (domain language)." },
              "answer": { "type": "string", "description": "Proposed constraint answer (domain language)." },
              "scope_kind": { "type": "string", "enum": ["SYSTEM_WIDE", "FEATURE_SPECIFIC"] },
              "target_slice_id": { "type": "string" },
              "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
              "rationale": { "type": "string" }
            }
          }
        },

        "scope_candidates": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["in", "out"],
            "properties": {
              "in": { "type": "array", "items": { "type": "string" } },
              "out": { "type": "array", "items": { "type": "string" } }
            }
          }
        },

        "tradeoff_candidates": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["axis", "preference", "confidence"],
            "properties": {
              "axis": { "type": "string", "description": "Domain-level tradeoff axis (no implementation terms)." },
              "preference": { "type": "string", "description": "User preference phrased as a priority." },
              "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
            }
          }
        },

        "validation_candidates": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["acceptance_statement"],
            "properties": {
              "acceptance_statement": { "type": "string" }
            }
          }
        },

        "followup_question_drafts": {
          "type": "array",
          "description": "Draft follow-ups; must pass the same quality gate before enqueue.",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["draft_id", "taxonomy_type", "canonical_key_hint", "text", "scenario", "answer_spec"],
            "properties": {
              "draft_id": { "type": "string" },
              "taxonomy_type": { "type": "string", "enum": ["INTENT", "CONSTRAINT", "TRADEOFF", "SCOPE", "VALIDATION"] },
              "canonical_key_hint": { "type": "string" },
              "text": { "type": "string" },
              "scenario": { "type": "string" },
              "answer_spec": {
                "type": "object",
                "additionalProperties": false,
                "required": ["kind"],
                "properties": {
                  "kind": { "type": "string", "enum": ["choice", "yes_no", "value", "bounded_text"] },
                  "choices": { "type": "array", "items": { "type": "string" } }
                }
              }
            }
          }
        }
      }
    },

    "recursion_budget": {
      "type": "object",
      "additionalProperties": false,
      "required": ["max_followups", "used_followups"],
      "properties": {
        "max_followups": { "type": "integer", "const": 2 },
        "used_followups": { "type": "integer", "minimum": 0 }
      }
    },

    "provenance": {
      "type": "object",
      "additionalProperties": false,
      "required": ["produced_by", "model_id"],
      "properties": {
        "produced_by": { "type": "string", "enum": ["INTENT_AGENT"] },
        "model_id": { "type": "string" }
      }
    }
  }
}
```

### 4.5 Queue reassessment and blocked slice resume (merged operational detail)

* Raw user answers are persisted append-only at `.pdd_runs/<run_id>/intent/answers.jsonl`.
* Blocked slices register `constraint_present` monitors keyed by `constraint_id` or `canonical_key`.
* Planner-emitted `constraint_saved`/`decision_recorded` signals (and optional direct wake hooks) resume waiting slices in PromotionLoop.
* Follow-up drafts that pass the quality gate and recursion policy become first-class queue items with origin `INTENT_AGENT` and provenance linked to `question_id`/`answer_id`.
* Queue reassessment runs immediately after planner updates to close answered items, mark stale items, deduplicate, and reprioritize.

---
## 5) Intent understanding algorithm

### 5.1 Interaction model (single agent, progressive gating)

The user talks only to the Intent Agent.

Internally, the Intent Agent behaves like:

* conversational UI to the user
* event-driven mediator to the pipeline (signals in/out)

### 5.2 Proportional depth: how intent is built incrementally

Each user message updates:

* problem frame restatement
* scope in/out
* domain terms and concept map
* candidate unknowns (as potential questions)
* constraint hypotheses (non-authoritative assumptions to validate)

Then the agent chooses:

* ask **one** highest-value question, or
* produce/update the pre-decomposition skeleton if there is enough to proceed

“Enough to proceed” means:

* core workflows can be identified
* at least the major constraint dimensions have initial coverage or explicitly open questions
* no irreversible assumptions are required to start skeleton work

### 5.3 Vague input handling (no questionnaire dumps)

If user input is vague, the agent asks a single **INTENT** question that disambiguates between plausible frames.

Example (valid INTENT question):

* **Scenario:** “Different systems use ‘settlement processing’ to mean different things.”
* **Question:** “Which best matches what you mean by ‘settlement processing’ right now?”
* **Answer (choice):**

  * (A) “Confirming and recording completed movements of money/securities”
  * (B) “Matching trades/instructions and resolving breaks”
  * (C) “Reconciling internal records against external counterparties”
  * (D) “Something else (describe in 1–2 sentences)”

This is bounded, scenario-grounded, and domain-answerable.

Additional disambiguation example:

* **Scenario:** “A request like ‘build me a trading platform’ can refer to different workflow families.”
* **Question:** “Which is closest to what you mean right now?”
* **Answer (choice):**

  * (A) “Order routing + execution”
  * (B) “Portfolio + risk + reporting”
  * (C) “Treasury + settlement + reconciliation”
  * (D) “Another variant (describe in 1–2 sentences)”

### 5.4 Question taxonomy (valid vs prohibited)

All questions are classified into **exactly one** of these types.

#### 5.4.1 Valid user-facing question types (ONLY these reach the user)

| Type           | What it asks                                                                                                        | Typical answer form     | Examples (all must be scenario-grounded)                                                                                                                         |
| -------------- | ------------------------------------------------------------------------------------------------------------------- | ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **INTENT**     | What problem is being solved / what does a term mean in this domain                                                 | choice / bounded_text   | “When you say ‘reconciliation’, do you mean matching internal records to external statements, or reconciling across internal systems?”                           |
| **CONSTRAINT** | Boundaries and requirements (behavioral, operational, regulatory, organizational, legal, financial, platform, data) | value / choice / yes_no | “If a transaction record is corrected, must the system keep the original record and the correction history for audit?”                                           |
| **TRADEOFF**   | When priorities conflict, which priority wins                                                                       | choice                  | “If an operation can’t complete quickly and also can’t be allowed to partially complete, which matters more: fast response or never showing partial completion?” |
| **SCOPE**      | What’s in/out now vs later; integration boundaries                                                                  | choice / yes_no         | “Is multi-currency support required in the first release, or can it be added later?”                                                                             |
| **VALIDATION** | How correctness will be judged (acceptance criteria, example walkthroughs)                                          | bounded_text / choice   | “Provide one example settlement from start to finish and what counts as ‘done’ for your users.”                                                                  |

#### 5.4.2 Prohibited internal-only question types (NEVER reach the user directly)

These types may appear in UserQuestionSignals as hints, but must be reframed into valid types before user exposure.

| Internal-only type | Why prohibited                                                       | Reframe pattern (to a valid type)                                                    |
| ------------------ | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| **ARCHITECTURE**   | Users aren’t responsible for system design patterns                  | Ask about required behavior/timing/visibility (CONSTRAINT/TRADEOFF)                  |
| **IMPLEMENTATION** | Libraries/frameworks are system choices unless user constrained them | Ask about compatibility/lock-in/licensing/operational constraints (CONSTRAINT/SCOPE) |
| **DESIGN_PATTERN** | Code structuring is internal                                         | Ask about change frequency, ownership boundaries, audit needs (CONSTRAINT/SCOPE)     |
| **OPTIMIZATION**   | Performance tactics are internal                                     | Ask about performance targets and acceptable delays (CONSTRAINT/TRADEOFF)            |

#### Reframing examples (required)

* **Internal (ARCHITECTURE):** “Should this be event-driven or synchronous?”

  * **User-valid (CONSTRAINT):**
    **Scenario:** “Users may need status updates immediately after recording a settlement, and different screens/reports may still update at different times.”
    **Question:** “After a settlement is recorded, do users need to see it updated everywhere immediately, or is a short delay (seconds to minutes) acceptable?”
    **Choices:** (A) Immediately everywhere, (B) Short delay is fine, (C) Depends (describe where it must be immediate)

* **Internal (IMPLEMENTATION):** “Which database should we use?”

  * **User-valid (CONSTRAINT/SCOPE):**
    **Scenario:** “Some organizations have platform commitments that constrain where data can live.”
    **Question:** “Do you have an existing platform commitment for where this data must live (for example, an approved vendor or on‑prem requirement), or is this a new decision?”
    **Choices:** (A) Existing commitment, (B) New decision, (C) Not sure yet

* **Internal (OPTIMIZATION):** “Should we add caching?”

  * **User-valid (CONSTRAINT):**
    **Scenario:** “Some screens can show slightly out-of-date values if it makes them faster.”
    **Question:** “For user-facing balances and totals, is it acceptable if the displayed value is briefly out of date (for example, up to 30 seconds) to keep the system responsive?”
    **Choices:** (A) No, must be current, (B) Yes, brief delay OK, (C) Depends by screen

### 5.4.3 System-wide vs feature-specific

Every question and its canonical key must be tagged as:

* **SYSTEM_WIDE**: affects multiple workflows/slices (asked earlier, higher priority)
* **FEATURE_SPECIFIC**: only affects a specific workflow (asked when that workflow is planned)

### 5.4.4 Constraint dimension list (for CONSTRAINT questions)

CONSTRAINT questions must map to one (or more) of these dimensions:

* **Operational**: latency, throughput, availability, RTO/RPO, batch windows
* **Regulatory**: compliance regimes, audit requirements, data residency
* **Organizational**: team size, expertise, operational ownership, support hours
* **Legal/Licensing**: open-source policy, vendor restrictions, contractual constraints
* **Financial**: budget ceilings, cost targets, cost sensitivity to volume
* **Platform**: existing cloud/on‑prem commitments, network constraints, identity provider constraints
* **Data**: sensitivity, retention, volume estimates, lineage requirements, access controls

### 5.4.5 Early interaction focus boundaries

Early questions focus on:

* intended users and primary workflows
* constraints that strongly shape behavior (latency/consistency/regulatory/auditability)
* integrations and data sources

Avoid early questions about:

* specific libraries
* internal component names
* implementation technologies

Those can be constrained later if the user cares.

### 5.5 Question quality gate (hard enforcement)

Every user-facing question must pass **all five** rules.

#### 5.5.1 The five rules (pass/fail)

1. **Domain language only**

   * Answerable by a business-domain expert who has never written code
   * No architecture jargon, implementation jargon, framework names
   * Exception: if the user introduced a technical term, it may be used (tracked in `concept_map.user_introduced_terms`)

2. **Bounded answerability**

   * Must have a concrete answer space:

     * choice set (preferred)
     * yes/no
     * concrete value (number/date/duration/etc.)
     * bounded_text (explicit bounds like “up to 3 items”)
   * No open-ended “what do you think about…”

3. **Specific behavior or property**

   * Must reference a concrete behavior/outcome/property
   * Avoid abstract dimensions (“consistency”, “scalability”) unless immediately grounded in observable behavior

4. **Scenario grounded**

   * Must include a scenario or a failure mode that explains why it matters

5. **One question per interaction (default)**

   * One atomic decision per QuestionItem
   * Batching only per Section 2.5 and still must pass this rule at the batch level

#### 5.5.2 Enforcement pipeline

```
QuestionDraftStrategy produces candidate →
QualityValidatorStrategy evaluates →
PASS: enqueue
FAIL: QuestionRepairStrategy retries (max 2) →
FAIL after retries: mark UNASKABLE + escalate to Planner (reformulate or auto-resolve)
```

All attempts are logged as QualityCheckRecords in the event log.

#### JSON Schema: QualityCheckRecord

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://spec-manager.local/schemas/QualityCheckRecord.schema.json",
  "title": "QualityCheckRecord",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "record_id",
    "question_id",
    "attempt",
    "created_at",
    "candidate",
    "checks",
    "result",
    "reason",
    "validator_version"
  ],
  "properties": {
    "record_id": { "type": "string" },
    "question_id": { "type": "string" },
    "attempt": { "type": "integer", "minimum": 1 },
    "created_at": { "type": "string", "format": "date-time" },

    "candidate": {
      "type": "object",
      "additionalProperties": false,
      "required": ["text", "scenario", "answer_spec_kind", "taxonomy_type"],
      "properties": {
        "text": { "type": "string" },
        "scenario": { "type": "string" },
        "answer_spec_kind": { "type": "string", "enum": ["choice", "yes_no", "value", "bounded_text"] },
        "taxonomy_type": { "type": "string", "enum": ["INTENT", "CONSTRAINT", "TRADEOFF", "SCOPE", "VALIDATION"] }
      }
    },

    "checks": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "domain_language_only",
        "bounded_answerability",
        "specific_behavior",
        "scenario_grounded",
        "single_question"
      ],
      "properties": {
        "domain_language_only": { "type": "boolean" },
        "bounded_answerability": { "type": "boolean" },
        "specific_behavior": { "type": "boolean" },
        "scenario_grounded": { "type": "boolean" },
        "single_question": { "type": "boolean" }
      }
    },

    "result": { "type": "string", "enum": ["PASS", "FAIL"] },
    "reason": { "type": "string", "description": "Short explanation of failure or confirmation." },
    "validator_version": { "type": "string" }
  }
}
```

#### Example quality record (illustrative)

```json
{
  "record_id": "qc_01",
  "question_id": "q_123",
  "attempt": 1,
  "created_at": "2026-02-13T10:12:00Z",
  "candidate": {
    "text": "Do you require eventual consistency for transaction records?",
    "scenario": "Different parts of the system may update at different times.",
    "answer_spec_kind": "choice",
    "taxonomy_type": "CONSTRAINT"
  },
  "checks": {
    "domain_language_only": false,
    "bounded_answerability": true,
    "specific_behavior": false,
    "scenario_grounded": false,
    "single_question": true
  },
  "result": "FAIL",
  "reason": "Uses architecture jargon and does not describe an observable business behavior.",
  "validator_version": "qv_1.0"
}
```

### 5.6 BAD → GOOD correction table (required)

All “GOOD” examples below satisfy the five rules.

| BAD (prohibited)                                                                      | GOOD (user-facing, scenario grounded, bounded)                                                                                                                                                                                                                                                                                                                            |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| “For transaction records, do you require strong consistency or eventual consistency?” | **Scenario:** “Users may need status updates immediately after recording a settlement, and different screens/reports may still update at different times.” **Question:** “After a settlement is recorded, do users need to see it reflected everywhere immediately, or is a short delay (seconds to minutes) acceptable?” **Choices:** (A) Immediate everywhere, (B) Short delay OK, (C) Depends (where must be immediate?) |
| “Should this run event-driven, batch, or synchronous?”                                | **Scenario:** “Some organizations process settlements as they arrive; others process them in scheduled runs.” **Question:** “Should settlements be processed as they arrive throughout the day, or collected and processed at scheduled times (for example, end of day)?” **Choices:** (A) As they arrive, (B) Scheduled runs, (C) Both (explain which are immediate)     |
| “What is the minimum acceptable behavior for this flow?”                              | **Scenario:** “Sometimes a settlement completes internally but the confirmation to the counterparty fails.” **Question:** “If a settlement completes internally but the confirmation to the counterparty fails, what should happen next?” **Choices:** (A) Retry automatically, (B) Pause and alert a human, (C) Proceed but flag for manual follow-up                    |
| “Should external integrations be plug-in points or hardwired?”                        | **Scenario:** “Some systems must be able to switch providers later.” **Question:** “If this system connects to an external clearing house or data provider, do you expect the provider to be fixed long-term or possibly change?” **Choices:** (A) Fixed provider, (B) Provider may change, (C) Not sure yet                                                              |
| “Should we use WebSockets or polling for real-time updates?”                          | **Scenario:** “Users may need near-real-time status updates.” **Question:** “When a settlement status changes, how quickly do users need to see the update?” **Choices:** (A) Within a few seconds, (B) Within a few minutes is fine, (C) Only needs to update on refresh                                                                                                 |
| “Which database should we use for the ledger?”                                        | **Scenario:** “Some organizations restrict what vendors can be used.” **Question:** “Are there vendor or platform restrictions that limit which storage technologies are allowed (approved vendor list, on‑prem requirement, etc.), or is this open?” **Choices:** (A) Restricted (describe), (B) Open, (C) Not sure                                                      |
| “Should we use caching to improve performance?”                                       | **Scenario:** “Some values can be slightly delayed if it keeps the system responsive.” **Question:** “For user-visible balances, is it acceptable if the displayed value is briefly out of date (for example, up to 30 seconds)?” **Choices:** (A) No, must be current, (B) Yes, brief delay OK, (C) Depends (which screens?)                                             |

### 5.7 When to produce the initial skeleton

Produce a pre-decomposition skeleton when:

* there is a stable restatement of the problem frame (even if marked “tentative”)
* core workflows are identifiable
* major constraint dimensions have either:

  * at least one answered constraint, or
  * an explicit queued question (not silent assumptions)

Skeleton creation is incremental; it is revised as constraints arrive.
When unresolved items remain, represent them as explicit TODO/question handles tied to constraints, not implementation-detail assumptions.

---

## 6) Skeleton format and depth

### 6.1 Output artifacts and directory structure (pre-decomposition)

For intent-level intake, the Intent Agent must **not invent library boundaries**.

Intent Agent produces coupled artifacts in a pre-decomposition layout:

```
system/
  intent.md
  workflows/
    <workflow>.py
  entities/
    <entity>.py
  interfaces/
    <interface>.py
analysis/intent/
  intent_snapshot.json
  question_queue.json
```

Artifact requirements:

* `system/intent.md`: problem frame/restatement, scope, success metrics, confirmed constraints, assumptions (clearly marked), tradeoff positions, open questions (IDs + short text), and pointers to authoritative constraints by ID (do not copy full constraint objects).
* `workflows/*.py`: domain workflows as function/class stubs with spec comment blocks and TODOs tied to question IDs.
* `entities/*.py`: domain entities/value objects with structural shapes.
* `interfaces/*.py`: external boundaries (providers, counterparties, identity, reporting feeds).
* `analysis/intent/intent_snapshot.json`: machine-readable snapshot for planner handoff.
* `analysis/intent/question_queue.json`: open question queue with stable IDs and statuses.

### 6.2 Depth rule

Skeleton is **one level deeper than names**:

* Include top-level workflows + key interfaces (what calls what)
* Include domain entities (structural shapes)
* Include placeholders for external dependencies
* Include TODOs tied to question IDs
* Do not implement business logic

Concretely:

* Yes: `SettlementProcessor.process(instruction) -> Receipt`
* Yes: `Ledger.post(entry) -> PostingResult`
* Yes: `RiskEngine.check_exposure(tx) -> ExposureResult`
* No: actual exposure computation

### 6.3 Embedding open unknowns in the skeleton

Every unresolved constraint becomes a TODO with a stable question handle:

```python
# Q:q_7f3a (canonical_key: constraint.operational.visibility_delay)
# Scenario: users may need status updates immediately after recording a settlement.
# TODO: finalize acceptable status propagation delay based on user answer.
def record_settlement(settlement_instruction):
    raise NotImplementedError
```

Alternative example at an interface boundary:

```python
# Q:q_7f3a (canonical_key: constraint.operational.visibility_delay)
# Need: confirm whether ledger postings must be strongly consistent or can be eventually consistent.
def post(self, entry: LedgerEntry) -> PostingResult:
    raise NotImplementedError
```

This makes “unknowns” durable and discoverable by downstream agents.

### 6.4 Metadata snapshot (no constraint objects)

Write machine-readable intent metadata:

* `analysis/intent/intent_snapshot.json`

  * problem_frame
  * `concept_map`
  * queue open question IDs + canonical keys
  * references to planner-authored constraints/decisions by ID (if available)
  * tradeoff positions

It must not embed constraint objects.

* `analysis/intent/question_queue.json`

  * queue item IDs
  * question text
  * current status
  * linked constraint IDs/canonical keys

This is the handshake contract into the existing pipeline.

## 7) Problem redefinition protocol

### 7.1 Triggers (system-level) and user-level phrasing (quality-gated)

Triggers remain system-side. A redefinition proposal is triggered when:

* Planner decomposes a user term into multiple subsystems and the decomposition changes scope materially
* Conflicts between requirements emerge, including incompatible requirements discovered during implementation
* Architecture implications materially change operational expectations (for example, a different operational model than the user expects)

But the resulting user interaction must be **domain language, scenario grounded, bounded**, and pass the quality gate.

Example (VALID TRADEOFF question):

* **Scenario:** "We found a tension between two requirements as currently stated."
* **Question:** "You asked for (1) immediate visibility of every recorded transaction everywhere and (2) processing thousands of transactions per second. Achieving both together adds substantial complexity. What matters more for the initial version?"
* **Choices:** (A) Immediate visibility, (B) Highest throughput, (C) Balanced (accept some delay to keep throughput)

### 7.2 Redefinition interaction pattern (single queue item, explicit confirmation)

When triggered, Intent Agent creates a **RedefinitionCheck** queue item handled as a single bounded confirmation question.

It presents:

* original intent statement
* current restatement
* what changed and why (1-3 bullets)
* the smallest bounded decision needed from the user:

  * (A) yes, adopt new restatement
  * (B) no, keep original framing
  * (C) partial (specify what changes)

This becomes authoritative only after Planner ingests the AnswerTranslation and writes scope/constraint updates.

User response updates:

* `problem_frame.current_restatement`
* `scope.in/out`
* constraints (as needed)
* queue reassessment (many questions may become stale)

### 7.3 Preventing drift

Maintain **alignment invariants** in problem frame metadata (a lightweight alignment checksum):

* a short list of "must remain true" statements derived from original intent and user-confirmed scope/constraints
* when Planner proposes a plan that violates an invariant, emit a TRADEOFF or SCOPE question for user confirmation before commitment

This prevents silent re-interpretation.

## 8) Relationship to Phase 0

### 8.1 Decomposition ownership (explicit)

* **Prose intake** -> Phase 0 owns decomposition:

  * sectionize -> discover -> route -> coverage -> assemble -> `libraries/...`
  * Intent Agent wraps Phase 0 outputs into user questions + pre-filled framing
  * Intent Agent can still produce a distilled intent snapshot and a skeleton derived from Phase 0 outputs (charters + constraints)

* **Intent-level intake** -> Intent Agent produces **pre-decomposition** skeleton only:

  * `system/workflows/entities/interfaces`
  * no library boundaries invented here

Library decomposition happens later when Planner has enough constraints and stable workflow surfaces:

* optional: run Phase 0 on `system/intent.md` + skeleton comments to propose library boundaries
* or Planner/L2 planning produces library boundaries directly, backed by constraints and evidence

### 8.2 Phase 0 as a strategy, not a parallel intake truth

Phase 0 remains an internal strategy invoked when:

* user supplies complete prose specs
* or system wants to propose library decomposition after intent-level work stabilizes

If input is already intent-level, pipeline starts from the `system/` pre-decomposition skeleton, and Phase 0 is optional (skip, or run later on generated intent prose when useful).

Phase 0 outputs remain authoritative evidence for routing/coverage within its scope.

### 8.3 Interface contract

* Phase 0 output becomes *authoritative evidence* for constraints and library responsibility summaries
* Intent Agent treats Phase 0 constraints as authoritative inputs into the constraint store (already bootstrapped in lifecycle)

---

## 10) Integration wiring

### 10.1 New modules/files to create

Create `spec_manager/orchestration/intent_agent/`:

* `agent.py`

  * `IntentAgentOrchestrator`
* `state.py`

  * session state load/save + schemas
* `queue.py`

  * queue operations + dedup + priority + batching + reassess
* `quality_gate.py`

  * `QualityValidatorStrategy`, `QuestionRepairStrategy`, record persistence
* `taxonomy.py`

  * taxonomy classification + reframing helpers
* `signals.py`

  * read/write for `UserQuestionSignal` store
* `answer_translation.py`

  * write AnswerTranslation artifacts
* `skeleton.py`

  * pre-decomposition skeleton renderer (`system/` layout)

Add coordination stores:

* `.pdd_runs/<run_id>/coordination/user_questions.jsonl` (already specified)
* `.pdd_runs/<run_id>/coordination/planner_updates.jsonl` (constraint/decision saved signals)

### 10.2 Modify existing modules (explicit replacements)

#### A) Planner: ingest AnswerTranslation and emit updates

* Add Planner capability: `INGEST_USER_ANSWER`

  * input: path to AnswerTranslation artifact
  * output: trace id + list of written constraint ids + decision ids
* Ensure Planner is the only writer to ConstraintsStore and decision store.
* Use existing `on_constraint_saved` callback to emit update events to:

  * `.pdd_runs/<run_id>/coordination/planner_updates.jsonl`

Update event examples (not a required schema here):

* `{"kind":"constraint_saved","constraint_id":"c_...","canonical_key":"...","trace_id":"...","created_at":"..."}`
* `{"kind":"decision_recorded","decision_id":"d_...","axis":"...","trace_id":"...","created_at":"..."}`

#### B) UnderSpecManager: replace InteractiveWorkflow with UserQuestionSignals

Replace `_resolve_interactive` in `under_spec_manager.py`:

* Old behavior:

  * write `constraint_request.md`
  * run InteractiveWorkflow
  * parse constraints locally

* New behavior:

  * emit UserQuestionSignals (one per under-spec event, or dedup cluster)
  * return outcome indicating WAITING/BLOCKED (depending on lifecycle state)
  * do not write constraints

UnderSpec events that cannot be resolved automatically become queue items via Intent Agent.

#### C) PromotionLoop: block by WAITING on questions, not raw CLI prompts

In `promotion_loop.py` (CoordinateStep / under-spec handling):

* When under-spec unresolved in interactive mode:

  * emit UserQuestionSignals (via UnderSpecManager)
  * transition slice to WAITING
  * monitors/wake triggered only when Planner writes required constraints

#### D) PddLifecycle: replace human checkpoints with Intent Agent signals

All `input()` prompts must be removed from lifecycle core.

Specifically, replace these methods’ behavior:

* `_request_approval` (L1 approval)
* `_request_l2_checkpoint` (L2 checkpoint)
* `_request_release_signoff` (release signoff)

They must:

* emit UserQuestionSignals of type VALIDATION / SCOPE / TRADEOFF as appropriate
* return WAITING until Planner records the user’s answer outcomes

**Overview documents may still be generated** for context, but they are not the approval mechanism.

#### E) InteractiveWorkflow: preserve only as internal tool

* InteractiveWorkflow can remain for:

  * offline refinement tooling
  * auto-mode experiments
* It must not be the user interface in interactive mode.
* In interactive mode, it should emit UserQuestionSignals instead of calling `input()`.

### 10.3 Lifecycle checkpoint replacement mapping (required)

#### Mapping table: old → new

| Existing method / mechanism             | Current behavior                                          | Replacement mechanism                                                                                                                   |
| --------------------------------------- | --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `PddLifecycle._request_approval`        | Shows overview, prompts `[a/f/q]`                         | Emit VALIDATION + (optional) SCOPE questions as UserQuestionSignals; wait until blocking questions answered and user confirms alignment |
| `PddLifecycle._request_l2_checkpoint`   | Prompts approve/quit with minimal context                 | Emit Planner’s human-required items (TRADEOFF/CONSTRAINT/SCOPE) as UserQuestionSignals; wait until BLOCKING items resolved              |
| `UnderSpecManager._resolve_interactive` | Writes `constraint_request.md` + runs InteractiveWorkflow | Emit UserQuestionSignals for each unresolved under-spec event; slice enters WAITING until Planner writes constraints                    |
| `PddLifecycle._request_release_signoff` | Prompts approve/reject after scorecard                    | Emit VALIDATION signoff question with bounded options; wait until recorded                                                              |

#### Before/after flows (required)

**1) L1 approval**

Before:

```
L1 completes →
overview generated →
_request_approval() calls input() →
approve/feedback/quit (no planning context surfaced)
```

After:

```
L1 completes →
Planner emits:
  - user questions for human-required items (if any)
  - planner_updates for constraints/decisions it recorded automatically
Intent Agent presents:
  - captured intent summary (problem frame)
  - authoritative constraints (by reference + user-friendly rendering)
  - next BLOCKING question (one at a time)
User answers →
Intent Agent writes AnswerTranslation →
Planner ingests + writes →
Intent Agent observes updates →
When no BLOCKING questions remain:
  - Intent Agent asks VALIDATION alignment question:
    "Does this summary match what you want?" (bounded choices)
Proceed to L2
```

**2) L2 checkpoint**

Before:

```
L2 planner runs →
_request_l2_checkpoint() asks approve/quit (no surfaced tradeoffs/authority escalations)
under_spec events may go to InteractiveWorkflow
```

After:

```
L2 planner runs strategy pipeline →
AuthorityDecider marks human_required →
Planner emits UserQuestionSignals (TRADEOFF/CONSTRAINT/SCOPE)
Intent Agent enforces quality gate and asks them in priority order
User answers → AnswerTranslation → Planner writes
Checkpoint passes when BLOCKING human_required items resolved
Proceed to L3
```

**3) Under-spec interactive resolution**

Before:

```
UnderSpecManager writes constraint_request.md →
InteractiveWorkflow prompts user →
UnderSpecManager parses constraints and writes
```

After:

```
UnderSpecManager emits UserQuestionSignals →
slice enters WAITING →
Intent Agent asks user questions (quality-gated) →
user answers → AnswerTranslation →
Planner writes constraints →
wake events fire →
slice resumes
```

**4) Release signoff**

Before:

```
scorecard printed →
input() approve/reject
```

After:

```
Planner emits final validation summary signals (or artifact) →
Intent Agent asks VALIDATION signoff question:
  Scenario: "This is what was built and verified."
  Question: "Does this meet your acceptance expectations for release?"
  Choices: (A) Approve release, (B) Not yet — list up to 3 issues, (C) Approve with known gaps recorded
User answer → AnswerTranslation → Planner records decision + (if B) new questions/constraints
```

### 10.4 CLI adapter (backward compatibility)

A CLI runner may remain, but must be a thin adapter that:

* reads queued QuestionItems from the Intent Agent store
* displays them and collects user answers
* forwards answers to the Intent Agent (not to Planner directly)
* never constructs its own questions

### 10.5 Migration path (incremental)

1. Introduce UserQuestionSignal store and Intent Agent queue + quality gate.
2. Modify UnderSpecManager interactive path to emit UserQuestionSignals (no InteractiveWorkflow).
3. Add Planner capability to ingest AnswerTranslation and write constraints/decisions.
4. Add planner update signals so Intent Agent can observe authoritative writes.
5. Replace lifecycle `input()` checkpoints with signals + WAITING semantics.
6. Introduce pre-decomposition skeleton output for intent-level intake; keep Phase 0 for prose intake.

This produces a single coherent user interaction layer with enforced question quality, clear authority boundaries, and lifecycle checkpoints that surface planning decisions through the same question queue mechanism.

---

## The big idea

Introduce a **Planner** that is the *single internal* auto-mode decision authority across:

* interactive refinement signal resolution (today: `AutoResponder`/`AutoSignalResolver`)
* PromotionLoop planning-related steps (today: ad-hoc per-step logic + UnderSpec pipeline)

Research becomes a **tool** the planner can invoke when needed.

## How it replaces/wraps `AutoResponder` and `AutoSignalResolver`

### Replace `AutoSignalResolver` with a Planner-backed resolver

(no PromotionLoop changes required)

Add a new resolver implementation:

* `PlannerSignalResolver` implements the existing `SignalResolver` protocol.
* Internally calls `Planner.resolve_signal(signal)`.

**Direct replacement:** update `create_resolver(mode="auto")` to return
`PlannerSignalResolver` directly (no feature flag).

### What happens to `AutoResponder`?

Treat it as a *legacy policy stage* and migrate it into
`planning/tools/research_tool.py`:

* SteeringScript match
* Evidence store lookup
* ResearchCoordinator fallback

Planner calls those stages as **tools** in a controlled order,
rather than being the system.

Concretely:

* Delete `AutoResponder` as a public actor.
* Inline its remaining steering/evidence/research logic into planner tools
  (especially `planning/tools/research_tool.py`).

## Module layout

Create a new package: `spec_manager/planning/`

Recommended submodules (minimal but complete):

* `spec_manager/planning/api.py`

  * public types: `PlanningRequest`, `PlanningResult`, `PlanningContext`, `Planner`
* `spec_manager/planning/router.py`

  * `LayerRouter`, `CapabilityRouter` (routes to layer planners +
    per-capability strategies)
* `spec_manager/planning/layers/`

  * `l1.py`: `L1Planner` (+ L1 discovery + L1 skeleton plan generator)
  * `l2.py`: `L2Planner`
  * `l3.py`: `L3Planner`
* `spec_manager/planning/tools/`

  * `research_tool.py`: adapter over `ResearchCoordinator`
    (+ optional BrennerBot tool)
  * `integration_tool.py`: integration analysis
    (skeleton extraction → graph → diff/risk)
  * `constraints_tool.py`: adapter over `ConstraintsStore`/`UnderSpecManager`
  * `evidence_tool.py`: adapter over `EvidenceStoreResearcher`/`EvidenceIndex`
* `spec_manager/planning/jit/`

  * `state_machine.py`: pause/resume planning state machine
    (adapted from article_writer)
  * `actions.py`: `NextAction` pattern for planning micro-phases
* `spec_manager/planning/trace.py`

  * `PlannerTrace`, `DecisionRecord`, `ToolCallRecord`,
    `ModelCallRecord`, `ReplayBundle`

This keeps "planning" cohesive without rewriting PromotionLoop.

## 1) Planner decomposition

### 1.1 Keep the current Planner API, add a constraint/tradeoff pipeline behind PLAN + UNDER_SPEC

Do **not** add a parallel system. Extend what already exists:

* `Planner` (router + trace) stays the entry point.
* For capabilities:

  * `PLAN`: produce intentions **plus decision requirements** and (optionally) architecture candidates.
  * `UNDER_SPEC`: produce **constraint answers** in auto mode OR **refined questions** in interactive mode.
  * Other capabilities unchanged.

### 1.2 Introduce a “Planning Session” internal pipeline (strategies, not a new external module)

A session is a sequence of strategy steps that can be skipped based on impact.

#### Step A — Problem framing and translation (LLM)

**Goal:** convert domain language → planner-reasonable plan space.

**Inputs**

* `ctx` (layer, slice_id, mode)
* gaps + discovery (L1 skeleton graph, L2 topology/interaction summaries, etc.)
* verbatim constraints evidence (from Phase 0) + any prior decisions

**Outputs**

* `ProblemFrame` (structured dict):

  * `goal`: what is being accomplished
  * `scope`: function/library/inter-library edge/system
  * `domain_markers`: phrases signaling implied constraints
  * `decision_points`: list of decisions likely needed
  * `tradeoff_axes`: subset of TRADEOFFS.md relevant to this frame
  * `unknowns`: missing information + what would resolve it

**Invocation trigger (proportional cost)**

* Always for L2 `PLAN` when gaps include topology/boundary/gov findings
* Sometimes for L1: only if gap touches external deps, storage, concurrency, IO, security
* Rare for L3

#### Step B — Constraint collection (deterministic)

Load authoritative constraints + prior system decisions, without inference.

**Outputs**

* `ConstraintContext`:

  * `authoritative`: constraints from spec/humans (validated)
  * `decisions`: software-only decisions previously made by the system (also treated as constraints)
  * `unverified`: inferred hypotheses (kept separate; not gate-eligible)

#### Step C — Constraint enrichment (LLM, gated)

Discover:

* **implied constraints** (domain markers → constraints)
* **solution-introduced constraints** (dependency/pattern introduces legal/econ/op/org/time burdens)
* **conflicts** among authoritative constraints
* **missing constraint questions** needed to choose safely

**Outputs**

* `ConstraintHypotheses[]` (non-authoritative)
* `DecisionRequirements[]` (authoritative-needed; these power PlanningGate)
* `ConflictReport` (if any)

**Invocation trigger**

* Only for decisions above a threshold impact (see 1.4)

#### Step D — Candidate generation (LLM, scoped)

* For non-architecture decisions: generate 2–3 candidates if impact ≥ medium
* For architecture (L2): use the fractal multi-proposer algorithm (Section 2)

**Output**

* `Candidates[]` each with:

  * `position`: tradeoff priorities
  * `constraints_introduced`: including non-software dimensions
  * `requires_human_constraints`: questions (constraints, not solutions)
  * `implementation_obligations`: constraints that flow down to L1

#### Step E — Candidate assessment (LLM + existing reviewers)

Evaluate each candidate against:

* authoritative constraints (satisfied / violated / unknown)
* coupling / blast radius / reversibility
* architecture reviewers (existing L2 ReviewPack pattern)

**Outputs**

* `Assessment[]` per candidate
* `Unknowns[]` which become under-spec questions

#### Step F — Decision authority (policy + LLM check)

**Goal:** decide when planner can commit vs must ask humans.

**Outputs**

* `DecisionOutcome`:

  * `commit`: chosen candidate (if allowed)
  * `new_constraints_to_write`: software-only decisions
  * `under_spec_events_to_emit`: missing constraints, non-software approvals, conflicts

#### Step G — Publish / propagate (deterministic)

* Persist new constraints/decisions
* Attach artifacts to planner trace
* Emit coordination hooks (Section 3)

### 1.3 Strategy/agent decomposition

Implement the session pipeline as **strategies** (callable units) invoked from layer planners, not as new capability router types.

Recommended internal components (each can be a thin wrapper over `run_agent()`):

* `ProblemFramerStrategy`
* `ConstraintBootstrapStrategy` (Phase 0 → store; also used at run start)
* `ConstraintEnricherStrategy`
* `TradeoffMapperStrategy` (reads `design/TRADEOFFS.md` into an axis shortlist)
* `NonSoftwareChecklistStrategy` (dependency/pattern → question pack across dimensions)
* `ArchitecturePlannerStrategy` (Section 2)
* `CandidateEvaluatorStrategy`
* `AuthorityDeciderStrategy`
* `QuestionComposerStrategy` (turn unknowns/conflicts into human-usable constraint prompts)

### 1.4 Proportional cost: an impact classifier

Add a cheap “impact classifier” that gates Steps A/C/D/E:

**Inputs**

* layer
* gap kinds/severity
* touched files count
* whether decision introduces new external dependency / new infra / cross-library contract

**Outputs**

* `impact: LOW | MEDIUM | HIGH`
* `blast_radius: LOCAL | SLICE | CROSS_SLICE | SYSTEM`
* `reversibility: EASY | MEDIUM | HARD`

**Policy**

* LOW: no enrichment, no candidate gen; rely on existing constraints only
* MEDIUM: enrichment + small option set
* HIGH: full pipeline + multi-proposer (if architecture)

---

## Revised Section 2: Architecture planning via progressive refinement (no interaction graph artifact)

### 2.0 Invariants

Architecture planning must:

* **Route, not extract**: planners/proposers consume *source artifacts* (charters, constraints.md spans, pins registries, wiring files, L1 evidence) rather than synthesizing a new “interaction graph” representation.
* **Be fractal + progressive**: start with coarse, scoped understanding; refine only where a decision’s blast radius demands it; avoid “enumerate all scopes then solve.”
* **Compose incrementally**: architecture emerges from accumulated scoped decisions and wiring deltas, not a one-shot global composition step.
* **Treat uncertainty as blocking**: if a decision requires non-software constraints or missing facts, emit decision requirements and block via existing under-spec.

---

### 2.1 What L2 “knows” without extraction

L2 already has two legitimate, non-violating inputs:

1. **Routed Phase 0 artifacts** (authoritative text, verbatim)

   * `libraries/<LIB>/charter.md`
   * `libraries/<LIB>/constraints.md`
   * `libraries/<LIB>/details.md` / whatever Phase 0 produced
   * cross-library references already exist implicitly as: “text spans routed into multiple libraries” and/or mentions of other libraries in routed spans (these remain verbatim)

2. **L1→L2 discovered reality** (implementation evidence)

   * pin/edge proposals, imports, function-level interactions captured in evidence bundles
   * any existing manifests/registries created during L1 (if present)

Plus L2’s existing discovery step:

* **Architecture topology derived from internal arch files** (`component_manifest`, `pins_registry`, `entrypoints`, `wiring`) is acceptable because it’s parsing *controlled internal formats*, not extracting spec meaning.

**Key change from the prior design**: L2 does **not** precompute a comprehensive interaction graph across all libraries. It only gathers the *minimum* evidence needed for *the current decision scope*.

---

### 2.2 Architecture refinement loop inside L2 (decision-point driven)

Instead of “build full interaction graph → define all scopes → propose all scopes,” L2 works like this each time it runs for a slice:

#### Step 1 — Establish the current baseline (coarse, routed)

For the current slice `S` (usually a library slice):

* Load **authoritative constraints** relevant to `S` (system + library + any previously committed architecture decisions).
* Load **source artifacts** for `S` (charter + constraints spans + local arch files).
* Load **recent L1 evidence** relevant to `S` (from the bundle/evidence store).

This is routing/lookup, not extraction.

#### Step 2 — Detect architecture decision points (LLM, scoped to current slice)

Run a “DecisionPointDetector” that looks only at:

* current open gaps for the slice
* the slice’s routed artifacts
* the slice’s current arch files / topology
* recent L1 evidence touching the slice

It outputs a list of **DecisionPoints**, each with a **minimal scope** (see 2.3).

Examples of decision points:

* “Library `payments` needs to publish transaction-posted information; should it be a pin call vs an event?”
* “`ledger` depends on `risk`; directionality seems inverted; needs boundary correction.”
* “A new external dependency is implied by gaps; approval needed.”

This is where “branching when demanded” begins: a DecisionPoint is the unit that can trigger parallel exploration.

#### Step 3 — For each DecisionPoint, explore candidates *only for that point*

For each DecisionPoint `D`:

* Build a **ScopePacket** (routed sources only; see 2.5).
* Assign **tradeoff positions** to proposers for *this decision* (not for the entire system).
* Run `K` independent proposers (K small, e.g. 3) that each produce a candidate for this decision scope.
* Evaluate candidates against authoritative constraints.
* Either:

  * **Commit** a candidate (software-only authority) and emit wiring intentions, or
  * Emit **decision requirements** (human constraints needed) and block.

#### Step 4 — Incremental composition = “apply committed decisions”

There is no global “compose all scopes.” Composition is incremental:

* Each committed decision becomes:

  * a small set of wiring intentions (L2 output) and
  * a set of **architecture decision constraints** (software-only) that propagate forward/backward.

Over repeated iterations, the architecture is simply the accumulation of committed scoped decisions.

---

### 2.3 Progressive scoping: scopes are discovered, not enumerated

A DecisionPoint always carries a **scope** that is chosen as the smallest self-contained unit needed to decide correctly.

Scopes are created **on-demand** as decision points appear:

#### Intra-library scope

Used when the decision is fully contained inside one library boundary.

* `scope = intra:<LIB>`
* Inputs: `<LIB>` charter/constraints + local arch files + L1 evidence touching `<LIB>`

#### Inter-library interaction scope

Used only when there is *direct evidence* of an interaction that matters.

* `scope = inter:<LIB_A>→<LIB_B>:<interaction_handle>`
* **Interaction handle** is not a synthesized edge; it’s a pointer to *existing evidence*, such as:

  * a pin consumption/production mismatch in topology
  * a named contract/event referenced in both libraries’ routed spans
  * an L1 import/call proposal that crosses library boundary
  * an architecture gap referencing both components

This avoids “define all inter-scopes upfront.” The set of inter-scopes grows only when the system encounters evidence that an inter-scope is necessary.

#### Refinement as information increases

A scope can be refined (narrowed) when implementation reveals more:

* From `inter:A→B` coarse → `inter:A→B:EventX` once EventX exists in wiring/pins
* From `intra:payments` coarse → `intra:payments:submission_pipeline` once internal subcomponents are explicit

This is done by creating a *new DecisionPoint with a narrower scope*, not by rebuilding a global map.

---

### 2.4 Discovery through implementation: how L1 feeds architecture refinement

L1 does not “complete architecture,” but it continuously produces evidence that can trigger new L2 decision points later:

* New cross-library imports/calls observed during implementation
* Pin/edge proposals created by the implementation runner
* Spec-driven data shapes materializing as actual function signatures / DTOs
* “Cannot implement without deciding X” events

These show up as:

* evidence bundle entries
* gaps discovered during analysis
* under-spec events

**Mechanism**: when L1 introduces new cross-boundary evidence, it should emit (or cause) a work item / signal that results in an L2 DecisionPoint being created for the relevant slice(s). (See Section “Branching mechanism”.)

---

### 2.5 ScopePacket: what proposers receive without an interaction graph

A proposer never receives a comprehensive interaction graph. It receives a **ScopePacket**: a routed bundle of *the sources relevant to this DecisionPoint*.

**ScopePacket fields**

* `decision_id`
* `scope` (intra or inter as above)
* `trigger_evidence` (pointers, not summaries)

  * e.g., gap IDs, pin IDs, file paths, evidence bundle refs, constraint span IDs
* `source_artifacts` (verbatim or pointer form)

  * For intra: `<LIB>` charter.md + constraints.md spans relevant to the trigger + current wiring/manifest files for `<LIB>`
  * For inter: both libraries’ charters + the *specific* routed spans that mention the interaction + the specific wiring/pin declarations that touch it + L1 evidence items that show the interaction
* `authoritative_constraints` (system + applicable library + prior committed arch decisions that apply to this scope)
* `current_arch_state_refs`

  * file paths + identifiers; avoid synthesizing new structure
* `tradeoff_assignment`

  * “prioritize X, sacrifice Y” for this proposer
* `positions_taken`

  * a list like `["consistency-first", "simplicity-first"]` (no proposal content)

This ScopePacket is the proposer's only context: routed charters/constraint spans, relevant arch files, relevant evidence refs, applicable authoritative constraints/decisions, and tradeoff assignment plus positions taken.
It explicitly excludes any precomputed `edges`, `traffic`, or `failure modes` dataset.

This is routing: it moves originals (or verbatim excerpts) into the proposer context. It does not extract and repackage into a derived “graph.”

---

### 2.6 Revised architecture candidate contract (scoped, graphless)

Candidates are scoped outputs for a single DecisionPoint.

**Candidate output**

* `candidate_id`
* `decision_id`
* `scope`
* `position`

  * explicit priorities/sacrifices for the relevant tradeoff axes
* `proposal`

  * **intra candidates**:

    * internal component boundary adjustments (if any)
    * wiring changes inside the library (pins/handlers/routes), expressed as references to existing arch files + intended edits
  * **inter candidates**:

    * contract definition (event/message/interface), expressed in terms of:

      * what each side must provide/consume
      * ownership of schema and versioning expectations
    * wiring intentions to connect the two sides (again via file refs)
* `constraints_introduced`

  * `software`: committed obligations that L1/L2 must satisfy (idempotency, ordering, schema stability, retry semantics)
  * `non_software`: obligations that require human authority (license class, ops burden, cost drivers, org dependencies)
* `decision_requirements`

  * questions that must be answered to choose/commit safely (especially non-software dimensions)
* `assumptions` (non-authoritative)

  * explicit list; if any assumption touches non-software or high-impact behavior, it should turn into a decision requirement instead
* `trace`

  * list of references to source artifacts and span IDs used to justify the proposal (preserves authority chain)

This is the proposer output contract: a single scoped candidate that proposes wiring/contract changes using file refs plus intended edits, explicitly declares introduced constraints and decision requirements, and maintains trace to source artifacts.

---

### 2.7 Evaluation and incremental composition (no global backtracking pass)

Evaluation happens per DecisionPoint; composition is “apply decisions as they are made.”

#### Per-decision evaluation

For each candidate:

* Check authoritative constraints: `satisfied | violated | unknown`
* If `unknown` touches a gate-critical constraint or non-software dimension → emit decision requirements and block.
* Prefer candidates that:

  * minimize coupling across boundaries,
  * are reversible at this stage,
  * introduce fewer non-software obligations unless already approved.

#### Incremental composition

When a candidate is selected:

* Persist a **PlannerDecisionConstraint** record for that decision (software-only, authoritative within system authority).
* Emit L2 wiring intentions to implement the decision.
* Add any L1 obligations as constraints that apply to downstream implementation.
* On later iterations, new decision points see these committed constraints as part of the baseline.

No “compose everything” step is required, because the promotion loop already provides iterative convergence with gates/demotion.

---

### 2.8 Coarse→refined architecture and constraint flow (Q3)

#### Architecture decisions become constraints progressively

When L2 selects a candidate for a DecisionPoint, it writes **PlannerDecisionConstraints** (software-only, authoritative within system authority) at the appropriate precision.

Precision progression:

* **Coarse decision constraint** (early):

  * “Interaction A→B must be async message-based; no direct calls.”
* **Refined decision constraints** (later, once discovered):

  * “A publishes `TransactionPosted` event with fields X/Y; at-least-once delivery; B must be idempotent using key K; schema versioning rule V.”

#### Refinement without overwriting (information permanence)

Never overwrite a prior decision record. Refinement produces a new constraint that **supersedes** the prior one:

* `constraint.status = ACTIVE | SUPERSEDED`
* `constraint.supersedes = [older_constraint_id]`
* `constraint.trace = …` (source refs + decision point refs)

This preserves:

* the chain of decisions,
* why refinement occurred,
* what changed.

#### Authoritative vs non-authoritative split remains intact

* **Candidates** and **assumptions** are non-authoritative.
* **Selected decisions** (software-only) become authoritative constraints.
* Any decision requiring non-software authority produces under-spec requirements and blocks until humans answer.

---

## 3) Constraint flow through the pipeline

### 3.1 Constraint artifact types (information permanence + source authority)

Use three classes of artifacts:

1. **Verbatim evidence** (already exists)

   * `libraries/<LIB>/constraints.md` (Phase 0 output)
   * preserve original text + source comments + element IDs

2. **Authoritative constraint facts** (gate-eligible)

   * stored in `analysis/constraints/*.json` via `ConstraintsStore`
   * includes spec constraints bootstrapped + human answers + system software decisions

3. **Non-authoritative hypotheses**

   * stored separately (e.g., `analysis/constraints_hypotheses/*.json`)
   * used for prompting/research; never satisfies gates

### 3.2 Forward flow

* Phase 0 → bootstrap spec constraints into `ConstraintsStore`
* L1 planning/implementation:

  * uses constraints snapshot
  * adds *software-only* decisions (if authority allows)
  * emits under-spec events when missing constraints
* L2 architecture planning:

  * consumes constraints + scoped source artifacts + routed evidence
  * produces architecture decisions as constraints for L1 (contracts, ordering, idempotency)
* L3:

  * should rarely add constraints; mostly emits demotion when behavior/arch must change

### 3.3 Backward flow (inter-layer)

When L2 introduces obligations that L1 must implement:

* persist as authoritative software constraints with:

  * `applies_to_layers: ["L1","L2"]`
  * `scope: intra:<LIB>` or `inter:<A>→<B>`
* if implementation is missing, it triggers:

  * either demotion (existing mechanism), or
  * a coordination work item targeting the owning slice

### 3.4 Use existing coordination infrastructure (no parallel system)

Use what you already have:

* **WaitGraph**

  * add edges: `slice` WAITING_ON `constraint_id`
* **WakeQueue**

  * wake on constraint addition
* **Monitors**

  * extend `ConstraintPresentCondition` semantics (see wiring section) OR emit wake events directly when store writes happen

Minimal viable: emit wake directly on store write, using constraint IDs as payload keys.

---

## 4) Intake classification expansion (beyond CONSTRAINTS/DETAIL)

Intake should stay “broad capture”; deep inference belongs to the planner. The right expansion is **shallow tagging**, not deep implication.

### 4.1 Keep current routing categories, add constraint subtyping metadata

For spans routed to `constraints.md`, add a companion index file per library:

* `libraries/<LIB>/constraints_index.json`

Each entry points to the element ID and carries shallow tags:

* `subtype`: invariant | tradeoff_preference | dependency_declaration | domain_marker | policy | performance | security | privacy | compliance | ops
* `scope_hint`: intra | inter | system
* `entities`: optional list of mentioned deps/providers (strings only)

This is:

* cheap (few items),
* preserves original text,
* gives the planner handles to find implied constraints and non-software triggers.

### 4.2 What stays in the planner (not intake)

* inferring implied constraints (e.g., HFT → latency SLO)
* enumerating non-software obligations from dependencies/patterns
* detecting conflicts

## 5) Non-software constraint model

### 5.1 Representation

Add explicit dimension + authority metadata to constraint questions and facts:

* `dimension`: software | legal | economic | organizational | temporal | operational
* `authority_required`: planner_ok | human_required
* `decision_type`: dependency | infrastructure | data_policy | security | performance | architecture

### 5.2 What the system can do autonomously

Allowed:

* generate **questions** and **checklists**
* apply **human-provided policies** (e.g., "Apache 2.0 only")
* research factual properties (license text, pricing tiers) in auto mode

Not allowed:

* decide acceptability of legal/cost/org/time/ops constraints without an explicit policy constraint from humans.

### 5.3 When to ask humans (proportional policy)

Ask when all are true:

* decision impact is MEDIUM/HIGH **and**
* the decision introduces or changes:
  * external dependency
  * infrastructure/provider
  * data retention/privacy/security posture
  * operational burden (deployments, oncall, scaling)
  * irreversible coupling direction

Ask less (or not at all) when:

* it's stdlib / already-approved internal module
* it's low blast radius + easily reversible

### 5.4 Output format for human questions (constraints, not solutions)

For a dependency decision, emit a single under-spec event whose answer format is structured:

* Allowed licenses:
* Budget constraints / cost sensitivity:
* Allowed vendors/providers:
* Operational constraints (oncall, managed vs self-hosted):
* Team constraints (language/runtime, expertise):
* Delivery timeline constraints:
* Risk posture (security/compliance baseline):

This prevents solution-pushing while giving humans a clean way to constrain the space.

---

## 6) Concrete wiring changes

### 6.1 Fix the constraints tool/store mismatch (required)

**Problem:** `planner/tools/constraints_tool.py` expects `{"constraints": [...]}` but `ConstraintsStore` writes `[...]`. Tool always returns empty.

**Change**

* Update `ConstraintsTool.load_constraints()` to accept both:

  * list root (current store)
  * dict root with `constraints` (legacy/alternate)

This immediately makes the tool usable by planners.

### 6.2 Bootstrap Phase 0 constraints into ConstraintsStore (required)

Add a bootstrap step right after intake completes.

**Where**

* `orchestration/pdd_lifecycle.py` after `results["intake"] = self._run_intake()`

**What**

* For each library dir:

  * read `libraries/<LIB>/constraints.md`
  * parse element IDs and the verbatim blocks
  * write constraints as **authoritative existing** into:

    * `analysis/constraints/<LIB>.json`

Also load system-level constraints (Phase 0 system constraints directory) into:

* `analysis/constraints/__system__.json` (or similar)

### 6.3 Make reads include system-level constraints

Update:

* `ConstraintsStore.load(slice_id)` (or add `load_all(slice_id)`) to merge:

  * `__system__` constraints
  * `<slice_id>` constraints

Update:

* `under_spec/planning_gate.py` to use the merged view

### 6.4 Make PlanningGate meaningful: intentions must carry decision requirements

Update layer planners (primarily L2) so `build_plan()` returns intentions with:

* `decision_requirements: [{decision_id, question, kind, dimension, scope_hint, impact}]`

Then PlanningGate can:

* check if each `decision_id` exists as a constraint_id in store
* if not, emit under-spec events **before implementation**

### 6.5 UnderSpecManager must pass layer context to the planner (required)

Currently `_resolve_via_planner()` uses `PlanningContext(layer="any")`, which routes to L1 planner.

Change:

* `UnderSpecManager.resolve()` accepts `layer` (or full `PlanningContext`)
* PromotionLoop passes the current layer when calling UnderSpecManager for L2/L3

This enables L2-specific under-spec resolution and better question refinement.

### 6.6 Add question refinement in interactive mode (recommended)

Before writing `analysis/constraint_requests/<slice>.md`, call a planner strategy:

* input: events + local context + constraints snapshot
* output: rewritten questions that are specific and constraint-shaped

Then write those questions into the request doc.

### 6.7 Architecture planning integration points

Replace the previous "ArchitecturePlannerStrategy + interaction graph artifacts" integration with:

#### 6.7 Revised integration points

1. **L2Planner.build_plan() becomes decision-point driven**

   * Add an internal call sequence:

     * `detect_decision_points(gaps, discovery, evidence, constraints)`
     * for each decision point:

       * if impact >= threshold: `run_proposers(scope_packet, tradeoff_assignments)`
       * `evaluate_and_select_or_block()`
     * emit:

       * `intentions` (wiring)
       * `decision_requirements` (for PlanningGate)
       * `new_constraints_to_write` (selected software-only decisions)

2. **Persist per-decision artifacts, not global graphs**

   * `reports/pdd/<run_id>/architecture/decisions/<decision_id>/candidates/*.json`
   * `.../selected.json`
   * `.../evaluation.json`

3. **DecisionPoints tracked as WorkItems**

   * Written/read via `WorkItemStore` so they persist across iterations and can be woken when constraints arrive.

4. **PlanningGate blocks on decision_requirements as before**

   * No change to the gate concept; it now blocks on *decision ids* produced by L2 decision points.

Everything else in Sections 1, 3, 4, 5, 6 (other than 6.7), 7 remains compatible.

## 7) Implementation plan (ordered, minimal breakage)

### Step 1 — Fix constraints tool format compatibility

Files:

* `planner/tools/constraints_tool.py`

Outcome:

* planner can actually read constraints store

### Step 2 — Bootstrap constraints store from Phase 0 output

Files:

* `orchestration/pdd_lifecycle.py` (after intake)
* new helper module, e.g. `orchestration/under_spec/bootstrap.py`

Outcome:

* `analysis/constraints/<slice>.json` populated from `constraints.md`

### Step 3 — Add system-level constraints merge

Files:

* `orchestration/under_spec/manager.py` (`ConstraintsStore`)
* `orchestration/under_spec/planning_gate.py`

Outcome:

* gate and planner see both system + slice constraints

### Step 4 — Introduce decision_requirements in L2 planning

Files:

* `planner/layers/l2.py`
* (optional) `planner/layers/common/impact.py` (impact classifier)

Outcome:

* PlanningGate starts blocking on uncovered decisions early

### Step 5 — UnderSpecManager: layer-aware planner calls + question refinement

Files:

* `orchestration/under_spec/manager.py`
* `orchestration/promotion_loop.py` (pass layer to manager)

Outcome:

* L2/L3 under-spec resolution can use L2/L3 planners; interactive questions improve

### Step 6 — Non-software constraint checklist + authority policy

Files:

* new `planner/constraints/authority.py`
* new `planner/constraints/non_software.py`
* integrate into L2 planner strategies

Outcome:

* dependency/infra choices reliably surface human-required constraints

### Step 7 — Fractal architecture planning (multi-proposer per scope)

Files:

* new `planner/architecture/*` (decision-point detection, scoping, proposer orchestration, evaluation, incremental composition)
* integrate into `planner/layers/l2.py`

Outcome:

* architecture planning explores tradeoff space, chooses or blocks with precise questions

### Step 8 — Propagation hooks via coordination

Files:

* `orchestration/coordination/*` (optional small additions)
* `orchestration/under_spec/manager.py` emit wake events on store updates

Outcome:

* blocked slices wake when constraints arrive

## Summary of what changes behaviorally

After these changes:

* Phase 0 constraints become **usable constraints facts** immediately.
* The planner can:

  * infer implied constraints (as hypotheses),
  * enumerate tradeoff axes,
  * generate multiple architecture candidates per scope,
  * evaluate against authoritative constraints,
  * decide only when authorized,
  * otherwise block with **specific constraint questions**.
* Constraints and decisions persist and flow across L1/L2/L3 using the existing under-spec store and coordination mechanisms.

---

## 3) Layer-aware planner hierarchy

General planner + skeleton planners + discovery + research dimensions

### Hierarchy

Implement a two-level planner structure:

#### 1. GeneralPlanner (root)

* owns routing, tool orchestration, model routing, trace
* delegates layer specifics

#### 2. Layer planners (L1/L2/L3)

* each owns discovery strategy + skeleton planner
* each knows how to turn (gaps + context) into plans for that layer

```text
Planner (General)
  ├─ L1Planner (code-as-spec)
  │    ├─ L1DiscoveryRouter
  │    ├─ L1SkeletonPlanner
  │    └─ L1LayerResearchAdapter
  ├─ L2Planner (architecture)
  │    ├─ L2DiscoveryRouter
  │    ├─ L2SkeletonPlanner
  │    └─ L2LayerResearchAdapter
  └─ L3Planner (quality)
       ├─ L3DiscoveryRouter
       ├─ L3SkeletonPlanner
       └─ L3LayerResearchAdapter

(shared)
IF
   ├─ ResearchTool (EvidenceStore + Firecrawl + optional BrennerBot)
   ├─ IntegrationAnalyzer (skeleton → graph, + diff/risk)
   ├─ ConstraintsTool (constraints + under-spec lifecycle)
   └─ Trace/Replay
```

### Research dimensions (layer research vs web research)

Treat "research" as a routed capability with explicit dimension:

#### Local evidence research

* Evidence store search (existing `EvidenceIndex`)
* Prior constraints / prior decisions (constraints store)

#### Layer research

* L1: "code-as-spec interpretation" (what does the skeleton imply?)
* L2: architecture pattern lookup (within repo + internal docs)
* L3: refactor best practices (repo conventions + receipts)

#### Web research

* Firecrawl pipeline (GLM tool use)

#### External research tool

* optional BrennerBot (see section 6)

The planner chooses dimension based on:

* whether the question is resolvable from code/architecture context
* whether external facts are required (APIs, standards, third-party behavior)

### "Layer-specific discovery routing" (no parsing; LLM does pattern recognition)

Each layer planner implements:

```python
class LayerPlanner(Protocol):
    layer: Layer
    def discover(self, ctx: PlanningContext) -> dict[str, Any]: ...
    def build_plan(self, ctx: PlanningContext, gaps: list[dict],
                  discovery: dict) -> dict[str, Any]: ...
    def resolve_under_spec(self, ctx: PlanningContext,
                          events: list[dict],
                          discovery: dict) -> dict[str, Any]: ...
```

**Discovery outputs are graphs/skeletons** (dynamic JSON), not ASTs.

#### L1 Discovery (code concerns)

* Input: slice files (not just `.py`, ideally "all text-like files")
* Output: **code-as-spec skeleton graph**

  * nodes: `function`, `class`, `spec_comment_block`
  * edges: `declares`, `mentions`, `calls` (best-effort, LLM-derived)

#### L2 Discovery (architecture)

* Input: component manifests, pins registry, entrypoints,
  event handlers, "arch files"
* Output: **architecture topology graph**

  * nodes: `component`, `pin`, `edge`, `handler`, `route`
  * edges: `provides`, `consumes`, `wired_to`, `declared_in`

#### L3 Discovery (quality)

* Input: changed files + quality receipts + diffs
* Output: **quality graph**

  * nodes: `file`, `function_span`, `smell`, `risk`
  * edges: `contains`, `impacts`, `depends_on`

---

## 4) Model routing strategy (Opus vs GPT‑5.2 XHigh vs GLM‑4.7)

### Principle: route by **work type**, not by pipeline stage

The current research coordinator always does Opus → GLM → GPT.
Planning should instead dispatch *only what's needed*.

### Model strengths (operational)

* **Opus**: deep reasoning, integration tradeoffs,
  adversarial critique, "what am I missing?"
* **GPT‑5.2 XHigh**: structured synthesis, plan generation,
  balanced judgment, writing executable plans
* **GLM‑4.7**: tool-heavy work (web research),
  breadth-first retrieval, search iteration

| Planner task type                                               | Primary model | Secondary model (only if gated) |
| --------------------------------------------------------------- | ------------: | ------------------------------: |
| Integration analysis (graph diff, risk, blast radius)           |          Opus | GPT (format + plan integration) |
| Plan synthesis (intentions/wiring/refactor steps,               |               |                 Opus (critique) |
| acceptance criteria)                                            | GPT‑5.2 XHigh |                               — |
| Under-spec resolution from local repo context                   |          Opus |              GPT (final answer) |
| Web research execution (Firecrawl/search loops)                 |       GLM‑4.7 |                 GPT (synthesis) |
| "What should we research?"                                      |          Opus |                               — |
| (query generation, hypotheses)                                 |               |                               — |
| "Is this plan coherent + minimal?" (plan lint)                  |          Opus |                               — |
| Normalization into required JSON/dict shapes                    |           GPT |                               — |

### Non-brute-force dispatch policy (important)

Implement a gated "escalate only when needed" policy:

#### 1. **Try deterministic/local first**

* constraints store coverage
* steering script match
* evidence store search

#### 2. **Try integration analysis**

* if code/architecture already implies answer, decide without web

#### 3. **Only then do web**

* if (and only if) planner flags "requires external facts"

#### 4. **Critique only when risk is high**

* architecture wiring changes (L2)
* refactors spanning multiple files (L3)
* low confidence decisions

This avoids the "always run three models" anti-pattern.

---

## 5) PromotionLoop integration (GAP / PLAN / UNDER_SPEC)

### Recommended integration approach: **wrap first**, then optionally replace

You can integrate without rewriting the 10-step PromotionLoop:

#### A) GAP step integration

* Keep `GapExplorationStep`'s current layer dispatch
  (it already matches the step dispatch table).
* After gaps are collected, call:

```python
planner.plan(PlanningRequest(
  capability="GAP",
  context=ctx_to_planning_context(ctx, bundle),
  inputs={"raw_gaps": bundle.gaps.open_gaps}
))
```

Planner output for GAP should:

* cluster/dedupe gaps
* prioritize gaps (smallest safe first)
* attach *integration notes* (what files/components are implicated)
* emit "decision requirements" (what constraints are needed before implementing)

Store these as additional fields in the bundle (dynamic structures).

#### B) PLAN step integration

Replace `PlanStep._plan_l1/_plan_l2/_plan_l3` with planner call:

```python
result = planner.plan(PlanningRequest(
  capability="PLAN",
  context=...,
  inputs={
    "gaps": bundle.gaps.open_gaps,
    "gap_analysis": bundle.analysis.gap_analysis,
    "prior_artifacts": {...}
  }
))
bundle.plan.intentions = result.outputs["intentions"]
bundle.plan.plan_artifacts = result.outputs.get("plan_artifacts", {})
```

Planner should generate:

* L1: function intentions referencing skeleton nodes
* L2: wiring plan referencing graph edges/pins/components
* L3: refactor plan grouped by function-span with "no behavior change" criteria

#### Integration with the promotion loop (Q1)

##### Where architecture exploration lives

Architecture exploration happens **inside the L2 PromotionLoop**, specifically in the **PLAN** step (`PlanStep` → planner PLAN entrypoint such as `planner.plan_from_gaps()` → `L2Planner.build_plan()`).

* Each L2 iteration:

  1. gaps are collected
  2. L2 planner detects decision points for *this slice* from current gaps + local routed artifacts + recent evidence
  3. for each decision point, run scoped proposers (branching) if impact ≥ threshold
  4. commit decisions or emit decision requirements
  5. planning gate blocks early if requirements uncovered

This matches Progressive Gating and Error Amplification: decide only what you can support, block early on uncertainty.

##### Does L2 run multiple iterations?

Yes: PromotionLoop already iterates per slice in L2. Progressive refinement is achieved by:

* resolving a subset of decisions per iteration,
* implementing wiring deltas,
* discovering new gaps/decision points,
* repeating.

There is no need to invent a separate “multi-iteration L2 planner” outside the loop.

##### Does architectural exploration happen within a single L2 promotion step or across multiple promotion cycles?

Both, naturally:

* **Within a single L2 iteration**: explore candidates for the current decision points and either decide or block.
* **Across iterations**: as wiring changes land and analysis finds new gaps, new decision points appear.
* **Across layer transitions** (L1→L2 transition refinement): architectural refinement can demote back to L1, causing new implementation evidence, which then changes the architecture decision landscape on the next transition round.

##### Branching mechanism (Q2)

###### What triggers a branch?

A branch is created when L2 detects a **DecisionPoint** that is:

1. **High-impact or cross-cutting**, and
2. **Multi-modal** (multiple plausible architectural approaches), and
3. Not already decided by existing authoritative constraints.

Concrete triggers (examples):

* A gap references wiring across boundaries with multiple valid patterns (sync call vs event vs shared store).
* L1 evidence shows a new cross-library interaction that violates existing directionality or contracts.
* A dependency/infrastructure choice emerges (Kafka vs in-process; DB ownership).
* Constraints conflict or tradeoff preferences exist (“correctness over speed”).
* “Architectural hotspot” signals from verify/refinement (e.g., coupling too high) require reconsidering a boundary.

###### How is branching different from under-spec?

* **Branching** = explore multiple software architectural candidates when the system *could* decide but should consider tradeoffs.
* **Under-spec** = block because the system *cannot* decide safely (missing constraints / human authority required / unknown satisfaction).

Branching may produce under-spec events if it discovers missing constraints.

###### How architectural branches map to the slice model

A branch is tied to a **DecisionPoint**, and each DecisionPoint is assigned an **owner slice** for execution, even if it affects multiple libraries.

Rule (deterministic, minimal new machinery):

* `intra:<LIB>` decisions are owned by slice `<LIB>`.
* `inter:<A>→<B>` decisions are owned by a stable owner:

  * e.g., `owner = min(A, B)` lexicographically, or “producer side” if determinable from the trigger evidence.

The decision’s resulting constraints are written with `applies_to = [A, B]`, so both slices see and obey it via PlanningGate.

###### How are branches tracked using existing coordination infrastructure?

Represent each DecisionPoint as a `WorkItem` (new kind) in the existing `WorkItemStore`.

**WorkItem: ARCH_DECISION**

* `id = decision_id`
* `scope`
* `owner_slice`
* `status = OPEN | EXPLORING | BLOCKED | DECIDED`
* `trigger_refs` (gap IDs, pin refs, file refs, evidence refs)
* `required_constraints` (ids that must be answered)
* `candidate_refs` (paths to candidate artifacts)
* `selected_candidate_ref` (if decided)

**WaitGraph integration**

* If `required_constraints` is non-empty:

  * add `WaitEdge(owner_slice → constraint_id)` (or decision_id → constraint_id)
* When constraints are added, WakeQueue wakes the owner slice (already part of the under-spec flow).

This uses existing coordination primitives and avoids introducing “branch manager” infrastructure.

#### C) UNDER_SPEC integration

Do **not** delete `UnderSpecManager`; make it call planner for resolution.

* UnderSpecManager remains the authority for:

  * constraint persistence
  * validation
  * partition resolved vs blocked

* Planner becomes the *resolver* it consults when it needs an answer.

Concretely:

* Add an injectable resolver interface to UnderSpecManager
  (or pass `Planner`):

  * `resolver.resolve(event, ctx) -> DecisionOutcome`

Planner output:

* either a resolved constraint payload
* or a blocked question (with structured options + "what evidence would decide")

This unifies:

* UnderSpec from PlanStep (planning gate uncovered decisions)
* UnderSpec from ImplementStep (runtime ambiguity)
* UnderSpec from interactive refinement (spec ambiguity)

### Longer-term option: collapse GAP+PLAN+UNDER_SPEC into one planner step

After wrap-first stabilizes, you can introduce a single `PlanningStep`
that internally runs the planner micro-state-machine:

* DISCOVER -> GAP -> PLAN -> UNDER_SPEC
  but keeps the PromotionLoop macro-state-machine unchanged.

---

## 6) Adapting JIT tooling patterns from `scripts/article_writer/`

### What to reuse directly

#### 1. **State machine core** (pause/resume + WAITING_INPUT)

* The planner needs this for:

  * under-spec questions (interactive mode)
  * multi-tool planning sequences (integration → research → design → validate)
  * "ask for more inputs" without guessing

#### 2. **NextAction pattern**

* Use `NextAction` to make planner execution explicit and testable:

  * `CALL_AGENT`时长Opus/GPT agent)
  * `RUN_TOOL` (evidence store search, firecrawl）
  * `USER_INPUT` (interactive under-spec)
  * `COMPLETE`

#### 3. **Context logging**

* Article writer's `ContextLogger` pattern maps cleanly to:

  * `PlannerTrace` (structured audit log + replay)

### What to adapt (rename + re-scope)

#### 1. **Phase enum**

Instead of article phases (DRAFT/REVISE),
planner phases should be:

```text
INIT
DISCOVER
INTEGRATION_ANALYSIS
GAP_UNDERSTANDING
RESEARCH (optional)
DESIGN
VALIDATE
COMPLETE
```

#### 2. **ReviewPack concept**

Turn "5 reviewers for L2/L3" into a first-class `ReviewPack`:

* `ReviewPack(name, agents[], merge_strategy, acceptance_checks[])`
* Planner can dynamically construct packs based on:

  * layer
  * gap type
  * risk (e.g., add adversarial reviewer only when risky)

This generalizes beyond GAP (it can also validate plans).

#### 3. **extract_skeleton**

Replace "document skeleton extraction" with **layer skeleton extraction**:

* L1: code skeleton graph
* L2: architecture topology graph
* L3: quality graph

Implementation remains "LLM for pattern recognition."

### What must be purpose-built

* **ModelRouter** (planning-specific, not article-writing)
* **IntegrationAnalyzer** (graph diff + risk)
* **PromotionLoop adapters** (bundle update + step hooks)
* **PlannerTrace + ReplayBundle** (for QA eval + debugging)

---

## 7) BrennerBot analysis (what to learn/avoid; whether to use it as a tool)

### What BrennerBot does well

#### Explicit loop structure + operatorized thinking

* BrennerBot describes an "11-phase loop" and four core cognitive
  operators (Level‑Split, Exclusion‑Test, Object‑Transpose,
  Scale‑Check) as reusable moves for rigorous inquiry. ([BrennerBot][1])

#### Multi-agent role separation

* The project explicitly assigns distinct responsibilities to different
  agents/models (hypothesis generation, test design,
  adversarial critique). ([GitHub][2])

#### Auditable artifacts + evidence hygiene

* It emphasizes durable artifacts (hypothesis slates,
  discriminative tests, assumption ledgers) and an evidence-pack
  workflow with stable IDs intended for citation. ([GitHub][2])

#### Deterministic merge + coordination bus

* It's built around Agent Mail as a coordination bus with a thread-id
  "join key" contract tying conversations, execution sessions,
  and artifacts together. ([GitHub][2])

### Where it's wasteful for spec-manager purposes

#### Human-in-the-loop cockpit runtime

* BrennerBot's reference architecture expects humans to manage multiple
  terminal sessions (ntm/tmux) and compile artifacts, rather than
  programmatic dynamic dispatch. ([GitHub][ Ministers])

#### Triangulation as a default habit

* It recommends "triangulation" by reading/producing multiple model
  syntheses to control narrative bias. That's valuable for scientific
  research, but often overkill for engineering planning where you can
  gate by risk/confidence. ([GitHub][2])

### What the planner should learn from BrennerBot (directly transferable)

#### Operator library as planning operators

* Level‑Split → separate "spec vs implementation vs integration"
* Exclusion‑Test → generate discriminative checks
  ("what evidence would falsify this plan?")
* Object‑Transpose → propose alternative wiring/entrypoint structures
* Scale‑Check → blast-radius and complexity sanity checks

#### Join-key contract

* Use a stable `trace_id` (run_id/slice_id/iteration/capability/event_id)
  that ties并发:

  * planner trace
  * model calls
  * artifacts produced
  * eval comparisons

### Should spec-manager call BrennerBot as an external tool?

Recommendation: **optional, narrow use**

* Use BrennerBot-style workflows as a *specialized external research tool*
  only when:

  * an under-spec event is fundamentally a research problem
    (not a code-integration problem)
  * you benefit from hypothesis/test framing and adversarial critique

* Otherwise, build competing capabilities inside the planner:

  * because spec-manager needs programmatic routing + automatic tool use
    (Firecrawl/evidence store/constraints), not human-managed terminals.

In other words: borrow the methodology; don't inherit the runtime.

---

## 8) QA instrumentation (planner is the unit under test)

### Instrumentation goals

During eval, you need to inspect:

* what the planner decided
* what it considered
* what evidence it used
* which model did what
* why it blocked

### Required artifacts per planning request

Write a single directory per `trace_id`, e.g.:
`workspace/analysis/planner_traces/{trace_id}/`

Contents:

* `request.json` (PlanningRequest snapshot)
* `decision.json` (final PlanningResult + confidence + rationale)
* `calls/`

  * `model_calls.jsonl` (one line per run_agent call:
    agent_name/model/prompt_hash/output_hash)
  * `tool_calls.jsonl` (evidence store queries, firecrawl outputs, etc.)

* `artifacts/`

  * `integration_graph.json` (if produced)
  * `plan.json` (intentions)
  * `under_spec_questions.json` (if blocked)
  * `replay.json`

  * enough to re re-run planner in "replay mode"
    without touching the repo state

### Decision record schema (what the evaluator compares to ground truth)

Each decision should include:

* `decision_text` (or `constraint_payload`)
* `confidence`
* `assumptions` (explicit)
* `evidence_refs` (file paths, snippet hashes, web sources)
* `alternatives_considered` (at least 2 when non-trivial)
* `discriminative_checks` (what would change the decision)

This makes QA comparisons meaningful: the evaluator can score
not just correctness, but *epistemic hygiene* and failure mode.

### Debugging hooks

Add a `PlannerDebugView` helper that can render (from trace):

* "why did you choose this?" (from stored rationale)
* "what evidence did you use?"
* "which model touched this decision?"
* "what would have made you block earlier?"

No new runtime UI required—just deterministic files.

---

## Core abstractions

### 1) `PlanningRequest`

A single request type that can represent:

* "resolve this ambiguity signal"
* "turn these gaps into a plan"
* "resolve these under-spec events"
* "produce integration analysis for this slice/layer"

```python
# spec_manager/planning/api.py
from dataclasses import dataclass
from typing import Any, Literal

Layer = Literal["l1", "l2", "l3", "any"]
Capability = Literal[
    "RESOLVE_SIGNAL",     # interactive refinement + under-spec questions
    "GAP",                # gap understanding / clustering / prioritization
    "PLAN",               # plan synthesis (intentions/wiring/refactor)
    "UNDER_SPEC",         # resolve or block; produce constraints or questions
    "INTEGRATION_ANALYSIS"
]

@dataclass
class PlanningContext:
    run_id: str | None
    slice_id: str | None
    iteration: int | None
    layer: Layer
    mode: Literal["auto", "interactive"]

    workspace_root: str
    slice_root: str | None = None
    # optional structured state:
    bundle_ref: Any | None = None     # EvidenceBundle or lightweight view
    signal_ref: Any | None = None     # InputSignal or Ambiguity
    metadata: dict[str, Any] | None = None

@dataclass
class PlanningRequest:
    capability: Capability
    context: PlanningContext
    inputs: dict[str, Any]            # gaps/events/spec text/etc (dynamic by design)
    constraints_hint: dict[str, Any] | None = None
```

### 2) `PlanningResult`

A result that can represent:

* resolved decision text (steering response)
* a plan artifact (intentions)
* a set of unresolved blockers/questions (under-spec)
* integration analysis artifacts

```python
@dataclass
class PlanningResult:
    status: Literal["OK", "BLOCKED", "NEEDS_INPUT", "NOOP", "ERROR"]
    outputs: dict[str, Any]           # dynamic artifacts: plan, decisions,
                                      # questions, graphs
    trace_id: str
```

### 3) `Planner` (public API)

Single entrypoint plus convenience wrappers:

```python
class Planner:
    def plan(self, req: PlanningRequest) -> PlanningResult: ...

    # Adapters for existing call sites (don't leak planning internals):
    def resolve_signal(self, signal) -> "SteeringResponse | None": ...
    def plan_from_gaps(self, ctx, gaps: list[dict]) -> list[dict]: ...
    def resolve_under_spec(self, ctx) -> dict[str, Any]: ...
```

### 4) Planner internal data flow (single request)

```text
PlanningRequest
  → Planner.plan()
      → Trace.start()
      → LayerRouter.select(layer) → L1Planner/L2Planner/L3Planner
      → PlannerStateMachine.run():
           DISCOVER (layer-specific)
           INTEGRATION_ANALYSIS (graph + diff + risks)
           DECIDE (constraints/steering/evidence/research as needed)
           DESIGN (plan synthesis)
           VALIDATE (coverage + constraints + "block on ambiguity")
      → Trace.persist()
  → PlanningResult(outputs + trace_id)
```

This is the key architectural shift: **planning is not "a response."
Planning is a multi-phase decision workflow with state.**

---

### Violation 9: Planning module uses AST to parse code it should already understand

**Is it a violation?** Yes.

**Severity:** **Structural**.

Planning should be scheduling and constraint management over:

* GapQueue items
* pins/evidence
* workspace status
* lineage/drift signals

Not AST.

**Correct design:**
Planning consumes the same EvidenceBundle used by gates and promotion.
If it needs additional facts, it asks `code_analysis.py`, not a parser.

**Migration path:**

1. Remove AST dependence from `planning/workflow.py` by swapping in `FileTranslationState` / EvidenceBundle.
2. Delete or convert `planning/code_parser.py` to a thin adapter over `code_analysis.py` (if legacy callers exist).

---

### Violation 10: Data flow direction (code→analysis→graph→decisions vs decisions→graph→verification)

**Is it a violation?** Yes.

**Severity:** **Philosophical**.

The philosophy requires: the LLM is the pattern recognizer and the thing doing the task; the graph is the artifact of that work. Mechanical steps verify, not define.

**Correct data flow:**

```text
code/diff
  → LLM (implements + emits pins/edges/evidence/questions)
  → Graph store (PinRegistry + AdjacencyGraph + lineage)
  → Gates verify (graph queries + runtime tests + anchor checks)
  → if fail: demote (write constraints into L1), loop
```

**Migration path:**

1. Require LLM outputs structured pins/edges with evidence.
2. Make graph construction depend on LLM output, not AST.
3. Keep AST tools only as validators until confidence is sufficient.

---

## Violations you likely missed

### A) Phase 0 is “clean” but may be *misplaced* in the global pipeline

If `pdd_orchestrator.py` runs P0 every time regardless of trigger, that violates:

* **Principle 5:** you already know what to edit when change originates from demotion/gates
* **Principle 12:** redundant routing/discovery step
* Target architecture statement: “Routing only at the bottom layer.”

**Fix:** Make Phase 0 a *conditional entrypoint* used only for external intake (new prose requirements / demoted algorithm descriptions / genuinely new constraints). Otherwise bypass it.

### 5) Conditional Phase 0 and partial intake routing

#### When Phase 0 is needed

Phase 0 is invoked only when there is **new L0 content** that must be routed into L1, or when a demotion declares that a missing requirement must be added.

Concrete detection policy (incremental, no fragile heuristics required):

* Maintain an **IntakeQueue** directory (or manifest) in workspace:

  * e.g. `.pdd_intake_queue/`
* Phase 0 runs if and only if either:

  1. the queue is non-empty, or
  2. a DemotionTicket has `routing_required=True`.

If intake input is raw prose:

* Run Phase 0 Intake to produce PDD skeletons (libraries) plus a coverage ledger.
* Commit the intake result to `pdd/<run_id>/base`.
* Limit Phase 0 rework to max 2 passes, and only rerun when coverage is below 100% or there is fatal routing overlap.

This avoids guessing based on file extensions.

#### Partial Phase 0 (route one requirement, not everything)

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

#### Does PromotionLoop invoke Phase 0 mid-loop?

Yes, but **only through DemotionTickets**:

* If a gate/test failure indicates “requirement missing entirely”, ticket sets `routing_required=True`.
* DemotionManager triggers `route_items([payload])`.
* The routed patch becomes an L1 spec insertion, then the normal loop continues.

No global reroute.

This is the concrete implementation target for the earlier statement in **DemotionManager.apply**, replacing “see §5” with a precise routing contract:

* If `ticket.routing_required`:
  * create a `RoutingItem` from `routing_payload`
  * invoke partial Phase 0 on that item
  * resulting routed patch becomes part of the demotion application.

---

### B) `pdd_lifecycle.py` stages (“Architecture” and “Code Quality”) risk direct-edit workflows

A separate “Architecture phase where agent proposes candidates” and “Code quality reviewers” often implies:

* discovering targets instead of using demotion tickets
* proposing direct edits to L2/L3 instead of promoting from L1 constraints

That conflicts with:

* **Principle 4 (promotion, not direct editing)**
* Target layering: architecture emerges from promotion, not a standalone stage

**Fix:** Convert these stages into **reviewers that only emit DemotionTickets**, not patches.

---

### C) Two sources of truth risk: extracted “atoms/graphs” vs “code-as-spec”

If AtomDescriptor/PinProjection become authoritative objects that downstream trusts more than pins + code, you’ve created an implicit separate spec layer.

This violates **Principle 3** even if code is still present.

**Fix:** Ensure every derived object is either:

* a view over pins/graph, or
* a cached “fact” that is always tied to evidence pins and invalidated by diffs

---

### D) Rigid type system may encode language assumptions

Even if you avoid AST, types like `Function`, `Class`, `Decorator`, `ImportGraph` can violate **Principle 7** if treated as mandatory structure.

**Fix:** Use typed wrappers only for *your own invariants* (pins, edges, gates), not for language constructs. Keep “what exists in the code” as dynamic facts emitted by LLM.

---

### E) “Block on ambiguity” may be unimplemented in a way that causes silent guessing

The presence of an under-spec step in the target loop is not enough; the architecture must support a hard stop.

Common failure mode: under-spec becomes “best effort” and gates become “skip.”

**Fix:** Under-spec must emit questions that become an explicit “waiting for constraints” state; no promotion continues until resolved.

### Gap 2: Planning Integrates with Constraints

#### The real problem

What’s missing is not “constraint reasoning” as a single feature; it’s a **constraint lifecycle** with:

* **Authoritative inputs** (spec + human constraints) that are *persisted* and queryable
* **Derived understanding** (implied constraints, tradeoff space, solution‑introduced constraints) that is *non‑authoritative* but drives questions/research
* **Decision commitments** (software-only choices the system is allowed to make) that become constraints for downstream work
* **Scope + propagation** so constraints/decisions move across L1/L2/L3 without losing provenance
* A **decision authority policy** that is conservative under uncertainty and explicit about when humans must answer

Right now, Phase 0 produces `constraints.md` (verbatim), but:

* nothing bootstraps those into the constraint store,
* the planner doesn’t consult constraints,
* the constraints tool can’t read the store format,
* the planning gate checks against an empty store,
* intentions don’t include decision requirements, so the gate can’t block early.

The design below connects all of that while honoring: proportional cost, information permanence, source authority, error amplification, coupling, fractal scoping, exploration-over-convergence.

#### Target behavior

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
   * `plan.under_spec.events.json` (events derived in PlanStep)
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

### Gap 3: Library Quality Validator (Post-Phase 0)

#### Target behavior

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

### Gap 4: Small Test Generation

#### Target behavior

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
   Yes; but implement minimally: a registry with at least a pytest runner that wraps your existing test execution path.

5. **What if test fails?**
   DemotionTicket + retry loop; implementor fixes code or test. If ambiguity, emit under-spec and block.

6. **Emit body + tests in one output?**
   Yes; schema already includes `tests[]` with diffs.

---

### Test strategy (Gap 4)

* `test_implementor_schema_includes_tests_and_runner_applies_patch()`
* `test_generated_tests_discovered_by_gate_and_run()`
* `test_failing_generated_test_creates_demotion_ticket()`

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

## Parts that are well-designed and should not change (conceptually)

Based on what you described, these align with the philosophy and should be preserved:

* **Phase 0 intake routing pipeline** (summarize → discover → route spans → coverage check → assemble)
  This is the strongest alignment with Principles 1/2/10/12.
* **AdjacencyGraph (typed weighted directed graph)**
  This matches Principle 6—keep it as the core substrate.
* **PinRegistry** (forward/backward trace, drift detection)
  This is essential; it’s the ledger for evidence.
* **GapQueue** (aggregation + stagnation detection)
  This supports iterative convergence.
* **WorkspaceManager** (run-scoped workspace)
  Needed for per-slice loop.
* **core/code_analysis.py + edit_in_place.py (LLM-based, language-agnostic)**
  These are the nucleus of the correct architecture.
* **refinement_engine/detector.py (graph-based coupling/cohesion)**
  This is what later phases should look like.

---

## Is the overall architecture correct in concept?

Yes—with one condition:

* **Pins + graph must be the first-class artifact produced by LLM work**, not an artifact reconstructed from syntax.

The conceptual stack (Layer 1 code-as-spec → Layer 2 architecture via pins → Layer 3 clean code) matches the philosophy. The current implementation flips the causal arrow (syntax extraction first), which is why it feels misaligned.

---

## Practical migration order (minimize risk to 2300 tests)

1. **Delete/neutralize leaf AST modules first** via adapters:

   * `analysis/ast_extractor.py` → route calls to `code_analysis`
   * `planning/code_parser.py` → wrapper over `code_analysis`

2. **Fold scanners into `gap_detection`:**

   * comment + stub scanners become internal implementations that call `code_analysis`

3. **Convert gates to consume `GapInventory + PinRegistry + AdjacencyGraph`**

   * stop calling any AST code from gates

4. **Make adjacency extractors “evidence-first”**

   * use stored edges if present; only infer via LLM when missing

5. **Move projection classification to pin creation time**

   * delete `projection_classifier.py`

This sequence keeps behavior stable while progressively eliminating parsing dependencies.

---

If you want one concrete litmus test for every remaining module:
**If it needs source text to rediscover relationships that could have been recorded as pins/edges at promotion time, it should be deleted or turned into an evidence consumer.**

---

## Priority order for fixing (what blocks what)

1. **Introduce the iterative per-slice PromotionLoop** (even if it still calls legacy phases internally).
   Without this, demotion and constant iteration can’t exist.
2. **Create the canonical EvidenceBundle** (facts + pins + edges + diff + provenance) produced once per slice.
   This is the prerequisite for removing redundant per-phase parsing.
3. **Move pin + edge creation into the LLM task outputs** (promotion/implementation).
   This inverts the data flow; AST becomes optional verification.
4. **Refactor gates to consume EvidenceBundle (graph queries + runtime results)**.
   This removes the AST-centric substrate.
5. **Implement full demotion chain** (gate failure → DemotionTicket → Layer 1 patch → GapQueue).
   This flips “skip” into “converge.”
6. **Make Phase 0 conditional** (external intake only).
7. **Delete/convert redundant analyzers and planning parsers**.

## Minimal incremental implementation order (to keep extension small)

### Implementation order and dependencies

#### Direct replacement order (no feature flags, no compatibility shims)

This is not production code - implement directly without compatibility shims.

1. **Step 1 - Core types and Planner API**

* Implement `planning/api.py`: `PlanningRequest`, `PlanningResult`,
  `PlanningContext`, `Planner`
* Implement `planning/trace.py`: `PlannerTrace`, `DecisionRecord`,
  `ToolCallRecord`, `ModelCallRecord`
* Implement `planning/jit/state_machine.py` + `actions.py`:
  planning micro-state-machine

2. **Step 2 - Layer planners and tools**

* Implement `spec_manager/planning/layers/l1.py`, `l2.py`, `l3.py`:
  layer-specific planners with discovery + skeleton planning
* Implement `spec_manager/planning/tools/`:
  `research_tool`, `integration_tool`, `constraints_tool`, `evidence_tool`
* Implement `spec_manager/planning/router.py`:
  `LayerRouter`, `CapabilityRouter`

3. **Step 3 - Replace AutoSignalResolver**

* Add `PlannerSignalResolver` implementing `SignalResolver`
* Update `create_resolver(mode="auto")` to return
  `PlannerSignalResolver` directly
* Move steering/evidence/research logic into
  `spec_manager/planning/tools/research_tool.py`
* Delete `AutoResponder` as a public actor
  (inline remaining logic into planner tools)

4. **Step 4 - Replace PromotionLoop step internals**

* Replace `_plan_l1/_plan_l2/_plan_l3` with
  `planner.plan(capability="PLAN")`
* Inject planner into `UnderSpecManager` as the resolver
* Wire GAP post-processing through planner for
  clustering/prioritization

5. **Step 5 - Update tests**

* Update all tests that reference `AutoResponder`/`AutoSignalResolver`
* Add tests for `Planner`, layer planners, tools, and trace

#### Gap-sequenced dependencies (complements direct replacement order)

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

1. Add L2/L3 dirty/clean branches + worktrees (no behavior change yet).
2. Add `tick_pipeline()` that only:

   * snapshots and tests L1 dirty→clean
   * merges L1 clean→L2 dirty and tests
   * merges L2 clean→L3 dirty and tests
3. Add backpressure refs (`l2/upstream_accepted`, `l3/upstream_accepted`) to prevent unbounded queue growth.
4. Wire PromotionLoop INTEGRATE to call `tick_pipeline()` after merging slice→L1 dirty.
5. Add layer transition logic + “reopen lower layer on demotion.”

This preserves your per-slice PromotionLoop/EvidenceBundle/DemotionTicket design unchanged; it only refines how “integration” and “promotion beyond the active layer” are executed and tracked.

---

## propagate l2 clean->l3 dirty + l3 tests->clean


Legend:

* **Delete**: functionality becomes unnecessary in the PDD model
* **Rewire**: keep module, but make it consume EvidenceBundle/graph/pins (no parsing)
* **Convert**: keep module, but replace AST/tokenize with `code_analysis.py` (LLM facts)
* **Left alone**: acceptable as runtime verification/plugin; not part of core truth

> Note: I’m classifying everything you listed (it’s more than 25). If you want exactly the 25 from your LANGUAGE_AGNOSTIC catalog, this mapping still applies; just filter to that set.

### Q1: Which modules should be deleted entirely?

#### Delete in the target design (no conceptual need)

These exist mainly to **rediscover structure or relationships** after an LLM already had to understand the code to do its job:

* `planning/code_parser.py`
* `analysis/ast_extractor.py`
* `analysis/import_scanner.py`
* `analysis/import_graph.py`
* `analysis/projection_classifier.py`
* `compliance/detection/call_graph.py`
* `projection/lineage/import_graph.py`
* `compliance/detection/comment_scanner.py` (fold into `gap_detection`)
* `compliance/detection/stub_scanner.py` (fold into `gap_detection`)

#### Remove from “core”; keep only behind abstractions if truly needed

These are inherently **language/toolchain-specific**, so they violate “language-agnostic” unless abstracted:

* `compliance/detection/runtime_detector.py`  → plugin
* `compliance/detection/coverage_analyzer.py` → plugin
* `projection/lineage/test_pin_discovery.py`  → plugin (if you still want it)

#### Deprecate then delete

* `analysis/adjacency/extractors/{call_graph,event_graph,store_graph}.py`
  Target: edges are produced during promotion and stored; extractors become optional fallback.

### Module-by-module decision matrix (delete vs keep, and what replaces it)

Legend:

* **DELETE** = no place in target design (keep only a temporary shim if needed for incremental migration).
* **KEEP (Graph)** = becomes pure graph/pin algorithm, no code parsing.
* **KEEP (LLM)** = a real LLM task (pattern recognition / intent).
* **PLUGIN** = language/runtime-specific adapter behind an abstraction; not a core dependency.

| Module                                          |                      Target decision | What it becomes (language-agnostic)                                                         | Replacement mode        |
| ----------------------------------------------- | -----------------------------------: | ------------------------------------------------------------------------------------------- | ----------------------- |
| `planning/code_parser.py`                       |                           **DELETE** | Structure comes from `code_analysis.py` or promotion evidence; no separate “parser”         | A → then remove         |
| `planning/reverser.py`                          |                       **KEEP (LLM)** | Reverse-translate **spans** (functions/blocks) → intent comments/summaries                  | B                       |
| `compliance/detection/comment_scanner.py`       |                           **DELETE** | Fold into `gap_detection` (produce comment-gap spans)                                       | C (via GapInventory)    |
| `compliance/detection/stub_scanner.py`          |                           **DELETE** | Fold into `gap_detection` using `SourceAnalysis.functions[].is_stub`                        | C                       |
| `compliance/detection/runtime_detector.py`      |            **PLUGIN** (often delete) | Only via per-language runtime probe; never required for core gates                          | Plugin                  |
| `compliance/detection/coverage_analyzer.py`     |            **PLUGIN** (often delete) | Coverage is toolchain-specific; not a universal core step                                   | Plugin                  |
| `branches/gap_detection.py`                     |            **KEEP (Graph/Evidence)** | Canonical **GapInventory builder** (spans + reasons), using LLM classification where needed | A/B inside; outputs C   |
| `analysis/adjacency/extractors/call_graph.py`   |               **DEPRECATE → DELETE** | CALL edges come from promotion evidence; fallback: on-demand LLM signal extraction          | C primarily; B fallback |
| `analysis/adjacency/extractors/event_graph.py`  |               **DEPRECATE → DELETE** | EVENT edges come from promotion evidence; fallback: on-demand LLM signal extraction         | C primarily; B fallback |
| `analysis/adjacency/extractors/store_graph.py`  |               **DEPRECATE → DELETE** | STORE_TOUCH edges come from promotion evidence; fallback: on-demand LLM signal extraction   | C primarily; B fallback |
| `analysis/import_graph.py`                      |                           **DELETE** | Import relationships that matter are represented as **PinProjections / REFERENCE edges**    | C                       |
| `analysis/import_scanner.py`                    |                           **DELETE** | “Who uses pin X?” is a **PinRegistryIndex query**, not parsing                              | C                       |
| `analysis/data_flow.py`                         |  **DELETE (or optional LLM helper)** | If needed, make it an on-demand “explain IO contract” LLM query on a span                   | B (optional)            |
| `analysis/projection_classifier.py`             |                           **DELETE** | Projection type is chosen at creation (PinProjection), not inferred later                   | C                       |
| `compliance/detection/call_graph.py`            |                           **DELETE** | Connectivity uses existing `AdjacencyGraph` CALL edges                                      | C                       |
| `compliance/promotion/algorithmic_gates.py`     |                     **KEEP (Graph)** | Gates run on `GapInventory + AdjacencyGraph + PinRegistry + test results`                   | C                       |
| `compliance/promotion/architectural_quality.py` | **KEEP (Graph + text fingerprints)** | No AST similarity; use span fingerprints + pin registry; LLM only as tie-breaker            | C + (B tie-break)       |
| `compliance/promotion/pin_coverage.py`          |                     **KEEP (Graph)** | Coverage = span coverage via PinProjections/architecture nodes, not syntax                  | C                       |
| `compliance/promotion/introduction_checker.py`  |                  **KEEP (Evidence)** | INTRODUCTION nodes must have spec-comment spans (GapInventory / code_analysis)              | C (+A if needed)        |
| `projection/lineage/import_graph.py`            |                           **DELETE** | Lineage uses PinProjections + AdjacencyGraph edges                                          | C                       |
| `projection/lineage/builder.py`                 |                     **KEEP (Graph)** | Infer lineage purely from pin + adjacency relationships                                     | C                       |
| `projection/lineage/test_pin_baseline.py`       |                         **OPTIONAL** | Baseline = hash of **test spans** (via code_analysis), not AST                              | A (optional)            |
| `projection/lineage/test_pin_discovery.py`      |                **PLUGIN / OPTIONAL** | If you need “test → pin” mapping, do it via runtime instrumentation per language            | Plugin                  |
| `branches/collapse.py`                          |                       **KEEP (LLM)** | Brownfield → produce pins/graphs/gaps by **routing spans**, not parsing syntax              | B (+A for spans)        |
| `analysis/ast_extractor.py`                     |                           **DELETE** | Replaced by `code_analysis` + on-demand LLM signal extraction                               | A/B                     |

---

### Phase 1–2

| Module                    | Current role                       | Disposition                                   | Why                                                                                                         |
| ------------------------- | ---------------------------------- | --------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `planning/code_parser.py` | AST structure parsing              | **Delete** (or **Convert** if legacy callers) | A “parser” is not a first-class concept; planning should consume EvidenceBundle.                            |
| `planning/reverser.py`    | AST boundaries + reverse-translate | **Delete**                                    | Reverse-translation implies a separate spec layer; ingestion should be routing/pinning, not reconstruction. |

### Phase 3 detection

| Module                                      | Current role                  | Disposition                          | Why                                                                                                    |
| ------------------------------------------- | ----------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| `compliance/detection/comment_scanner.py`   | tokenize comment extraction   | **Delete**                           | “Find comments” is gap exploration; should be emitted as gap pins by LLM during real work.             |
| `compliance/detection/stub_scanner.py`      | AST stub detection            | **Delete**                           | Same: stub detection is a fact in EvidenceBundle, not a standalone parser.                             |
| `compliance/detection/runtime_detector.py`  | Python runtime probes         | **Left alone** (plugin)              | Runtime verification is fine, but must not be core truth or required for language-agnostic behavior.   |
| `compliance/detection/call_graph.py`        | AST call graph for compliance | **Rewire**                           | Compliance should query AdjacencyGraph / RelationshipFacts, not rebuild it.                            |
| `compliance/detection/coverage_analyzer.py` | AST + coverage.py mapping     | **Rewire** (keep coverage, drop AST) | If you keep coverage at all, map coverage to pins/diffs, not AST constructs. Treat as optional plugin. |
| `compliance/detection/orchestrator.py`      | aggregates scanners           | **Rewire**                           | Should orchestrate EvidenceBundle creation + plugin verifiers, not AST scanners.                       |

### Phase 4

| Module                 | Current role                | Disposition | Why                                                                                                  |
| ---------------------- | --------------------------- | ----------- | ---------------------------------------------------------------------------------------------------- |
| `branches/collapse.py` | AST codebase classification | **Convert** | Ingestion classification can be LLM-based, but output must be pins/routes, not extracted constructs. |

### Phase 5 pin & promotion

| Module                                          | Current role                                 | Disposition                                      | Why                                                                                                 |
| ----------------------------------------------- | -------------------------------------------- | ------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| `pin_functions/orchestrator.py`                 | AST scan atoms + import graph to create pins | **Rewire**                                       | Pins should come from LLM outputs; this becomes a verifier/normalizer over pin proposals.           |
| `compliance/promotion/algorithmic_gates.py`     | 5 gates via AST                              | **Rewire**                                       | Gates must be graph queries + runtime checks over EvidenceBundle.                                   |
| `compliance/promotion/architectural_quality.py` | AST-based quality                            | **Convert**                                      | Architectural quality is fuzzy; use LLM evaluation over pinned evidence + diff.                     |
| `compliance/promotion/pin_coverage.py`          | AST pin coverage                             | **Rewire**                                       | Pin coverage is diff/span coverage; no AST needed.                                                  |
| `compliance/promotion/introduction_checker.py`  | AST intro checks                             | **Convert** (or **Rewire** if purely graph rule) | If “introduced algorithms/specs” is semantic, it’s LLM. If it’s a graph invariant, rewire to graph. |

### Phase 6 adjacency

| Module                                         | Current role            | Disposition | Why                                                     |
| ---------------------------------------------- | ----------------------- | ----------- | ------------------------------------------------------- |
| `analysis/adjacency/extractors/call_graph.py`  | AST calls               | **Rewire**  | Read RelationshipFacts emitted by LLM, then add edges.  |
| `analysis/adjacency/extractors/event_graph.py` | AST events              | **Rewire**  | Same.                                                   |
| `analysis/adjacency/extractors/store_graph.py` | AST stores              | **Rewire**  | Same.                                                   |
| `analysis/adjacency/runner.py`                 | orchestrates extractors | **Rewire**  | Becomes “merge relationship facts into AdjacencyGraph.” |

### Phase 7 projection/lineage and analysis utilities

| Module                                     | Current role            | Disposition                                 | Why                                                                              |
| ------------------------------------------ | ----------------------- | ------------------------------------------- | -------------------------------------------------------------------------------- |
| `projection/lineage/import_graph.py`       | AST imports             | **Rewire**                                  | Imports are just one dependency edge type; should come from RelationshipFacts.   |
| `projection/lineage/builder.py`            | AST patterns/decorators | **Convert**                                 | Pattern recognition is LLM territory; don’t encode Python constructs.            |
| `projection/lineage/test_pin_baseline.py`  | AST test signatures     | **Convert**                                 | Tests should be identified via LLM facts and/or runtime discovery; map to pins.  |
| `projection/lineage/test_pin_discovery.py` | AST test→pin mapping    | **Convert**                                 | This is semantic mapping; LLM + coverage (optional) beats AST.                   |
| `analysis/import_graph.py`                 | AST imports             | **Delete** (duplicate)                      | Consolidate import dependency into one relationship pipeline.                    |
| `analysis/import_scanner.py`               | AST import hits         | **Delete**                                  | Redundant once you have RelationshipFacts + pins.                                |
| `analysis/projection_classifier.py`        | AST projection types    | **Convert**                                 | Classification should be LLM-based (language-agnostic).                          |
| `analysis/data_flow.py`                    | AST data flow           | **Convert** (or **Delete** if nonessential) | If you truly need dataflow, it must be LLM-based; AST dataflow won’t generalize. |

---

## Direct answers to your embedded questions

* **(V1) “Is sequential architecture just not yet implemented, or does it make target harder?”**
  It makes the target harder because it encourages global discovery, global artifacts, and “stage outputs,” which fight per-slice iteration and demotion. Even if rewiring is possible, the architecture is currently training every module to assume pipeline semantics.

* **(V2) “Should pin creation happen inside the agent workflow?”**
  Yes. Pin creation should be part of promotion decisions: `PinFunction` and `PinProjection` are emitted while architecture is written, and projection types are decided at write time. Mechanical scanners (`import_scanner`, `projection_classifier`) are optional verification fallbacks only, while usage queries should come from `PinRegistryIndex`.

* **(V3) “Should gates operate on data produced by prior phases?”**
  Yes, but not “prior phases” in the pipeline sense—on the **single EvidenceBundle** produced per slice. Gates should never re-parse source to re-learn facts that already exist.

* **(V4) “Should graph edges be byproduct of LLM work or single LLM call?”**
  Prefer byproduct of the implementation/promotion agent (best alignment). A single relationship-analysis call is acceptable as long as it emits edges and evidence; don’t split into multiple mechanical extractors.

* **(V5) “Is brownfield ingestion an exception to no-extraction?”**
  Brownfield ingestion can involve summarization and classification, but the output should be **routing + pins**, not extracted structured representations that become an alternate spec.

* **(V6) “One comprehensive LLM analysis per file?”**
  Yes as a conceptual model: one canonical facts provider per file/diff. Internally it can be multiple calls, but downstream must see **one shared evidence artifact**, not a parade of redundant parsers.

* **(V7) “Is pin schema referencing code a violation?”**
  No. Pins are pointers. The violation is *how they’re populated and used*.

* **(V8) “Is lack of demotion just not yet implemented or structurally hard?”**
  It’s structurally hard in the current pipeline because “skip” is the natural failure path. You need explicit DemotionTickets + Layer1 patching to make demotion the default behavior.

* **(V9) “Should planning consume FileTranslationState instead of having its own parser?”**
  Yes. Planning should be a consumer of the same evidence/pins used everywhere else.

* **(V10) “Should primary data flow be reversed?”**
  Yes: LLM produces graph/evidence as it works; mechanical steps verify. You still read code text as input, but you don’t treat syntax extraction as the system’s understanding.

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

If you want the next step to be maximally actionable: I can write a concrete target “interfaces and artifacts” spec (schemas for EvidenceBundle, RelationshipFacts, PinProposals, DemotionTickets, GateResults) that you can implement incrementally while keeping the current system runnable.
