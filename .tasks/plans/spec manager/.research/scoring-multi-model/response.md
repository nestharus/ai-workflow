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

## 4) Cross-model comparison framework

### 4.1 Comparison inputs

For each run:

* `reports/pdd/{run_id}/scores.json` (RunReporter)
* `reports/pdd/{run_id}/planner_scorecard.json` (PlannerReporter; optional)
* `reports/pdd/{run_id}/quality_scorecard.json` (new; optional)
* `reports/pdd/{run_id}/architecture_digest.json` (new)
* `reports/pdd/{run_id}/code_digest.json` (new)
* Snapshot manifest + file hashes (immutability)

---

### 4.2 Apples-to-apples alignment

Models may produce different component sets. Avoid naïve “component count diff”.

Use a two-step **canonical responsibility alignment** (LLM-assisted, cached):

1. **Canonical responsibilities generation**

   * Input: spec summary + requirement list
   * Output: list of canonical responsibilities (5–20 items), each with a name + description
     Example: `["Audit log ingestion", "Notification routing", "Data persistence", ...]`

2. **Per-model mapping**

   * Input: canonical responsibilities + that model’s architecture digest component list
   * Output: mapping responsibilities → components (many-to-many allowed), with confidence

This yields comparison metrics:

* `responsibility_coverage_rate`
* `duplication_rate` (multiple components doing the same thing)
* `missing_responsibilities`

This approach is robust to “7 components vs 9 components”.

---

### 4.3 Comparative judging (pairwise) for “which is better”

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
* Optionally compute an Elo/Bradley–Terry rating later; not required for v1.

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

Generate both:

1. `reports/pdd/comparisons/{comparison_id}/comparison.json`
   (all raw metrics, mappings, pairwise judgments)

2. `reports/pdd/comparisons/{comparison_id}/comparison_report.md`
   Sections:

   * Summary table: models × (gates, quality, fidelity, efficiency, cost)
   * Architecture: topology stats + canonical responsibility coverage table
   * Code: sampled file scores + systemic risks
   * Pairwise judgments: short rationales
   * Recommendation block (optional, config-gated)

---

### 4.6 Non-determinism

Support `--runs-per-model K`:

* Report mean/std for key metrics.
* For pairwise comparisons, either compare “best run” per model or do pairwise on medians.

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
* `fixtures/judges/arch_cases/…`

---

## 6) Artifact preservation schema (immutability + comparison readiness)

### 6.1 Fix the current global-report collision

Right now `FinalReportGenerator` reads:

* `workspace_root/reports/component_manifest.json`
* `workspace_root/reports/architecture_proposals.json`

Those will be overwritten by subsequent runs → breaks multi-model.

**Change required: all run artifacts must be written run-scoped.**

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

  * or a full “output subtree” if “touched files” isn’t reliable yet

Plus:

* `reports/pdd/{run_id}/` contents
* `analysis/planner_traces/` entries for that run OR a filtered copy (optional)

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

---

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

Then comparison can compute total cost accurately.

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
