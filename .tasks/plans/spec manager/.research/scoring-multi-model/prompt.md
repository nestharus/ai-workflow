# Research: Scoring and Multi-Model Comparison

## What I Need From You

Design the **architecture quality scoring**, **code quality scoring**, **multi-model comparison framework**, and **LLM Judge upgrades** for the spec manager pipeline. The pipeline now has full scoring infrastructure (RunReporter + PlannerReporter), full trace instrumentation (per-decision trace with model_id), and a planner eval harness. What's missing is:

1. **Quality judges** — the current scoring is purely mechanical (gate pass rates, iteration counts, LOC churn). There is no LLM-based evaluation of whether the architecture or code is actually *good*.
2. **Multi-model execution** — running the same spec through different models independently, preserving artifacts, and comparing outputs.
3. **Cross-model comparison** — aggregating and visualizing how different models perform on the same spec.

This is the third research prompt. Research Prompt 1 designed the planning module. Research Prompt 2 designed the QA eval architecture. Both are implemented. This prompt builds on top of both.

---

## Current State

### What Exists

**Pipeline Scoring** (`orchestration/scoring.py` — `RunReporter`):
- 5 hard gates: `gates.final_pass`, `ci.final_pass`, `governance.no_fail`, `alignment.no_high`, `l3.no_behavior_change`
- 11 soft signals: gap closure, gate first-attempt rates (L1/L2), pin consumption, component coverage, reviewer first-pass rate, refactor churn, total demotions, iteration efficiency, CI first-pass rate, stagnation rate
- Outputs: `scores.json` + `scorecard.md` under `reports/pdd/{run_id}/`
- **Gap**: `governance.no_fail` is stubbed (always PASS). No architecture quality assessment. No code quality beyond `l3.refactor_churn`.

**Planner Scoring** (`refinement/evals/planner/reporter.py` — `PlannerReporter`):
- 5 hard gates: trace integrity, no error status, under-spec safety, schema validity, no OOS intentions
- 12 soft signals: resolve accuracy, gap recall/precision, plan coverage/redundancy, integration risk recall, unsafe resolution rate, evidence-first rate, model calls p50/p95, tool calls per decision, iterations per slice
- Outputs: `planner_scorecard.json` + `planner_scorecard.md` + `planner_decisions.jsonl`
- **Gap**: Planner metrics are quality-agnostic — they measure whether the planner *worked* (no errors, matched ground truth) but not whether the resulting architecture/code is *good*.

**Final Report** (`orchestration/final_report.py` — `FinalReportGenerator`):
- Sections: executive summary, architecture topology, scorecard, demotion summary, known risks, evidence links
- **Gap**: Topology section only lists component manifest entries. No architecture quality assessment, no dependency analysis, no pattern recognition.

**Planner Eval Harness** (`refinement/evals/planner/harness.py`):
- Three modes: e2e (full pipeline), slice (single PromotionLoop), replay (single decision re-run)
- Scorer map: RESOLVE_SIGNAL, PLAN, UNDER_SPEC, INTEGRATION_ANALYSIS
- **Gap**: No multi-model orchestration. No shadow-mode comparison.

**Trace System** (`planner/trace.py`):
- Each decision writes `request.json`, `decision.json`, `model_calls.jsonl`, `tool_calls.jsonl`, `artifacts/`, `replay.json`
- `index.jsonl` tracks trace_id, timestamp, model_id, slice_id, layer, capability, decision_key
- **Gap**: model_id is tracked but nothing consumes it for comparison. No cross-run alignment.

**Existing LLM Judge** (`refinement/evals/judge_scorer.py`):
- Phase 0 eval uses an LLM judge for semantic scoring of requirement capture
- Fuzzy substring matching + LLM fallback for items the fuzzy scorer can't match
- **Gap**: Only judges Phase 0 outputs (sectionization + requirement routing). Not used at L1/L2/L3 layer level.

### What Does NOT Exist

1. **Architecture quality judge** — no LLM-based evaluation of whether the produced architecture (component topology, dependency graph, API contracts) is well-designed
2. **Code quality judge** — no evaluation of whether the produced code follows good patterns, is maintainable, has appropriate abstractions (beyond LOC churn)
3. **Multi-model runner** — no CLI or harness to run the same spec through Model A, Model B, Model C independently
4. **Artifact preservation** — no framework to preserve and version full pipeline outputs per model per run
5. **Cross-model comparison report** — no way to compare Model A's architecture against Model B's architecture
6. **Quality-weighted scoring** — current scoring treats all gate passes equally; a pipeline that passes all gates but produces terrible architecture scores the same as one that produces excellent architecture

---

## Specific Questions

### Q1: How should architecture quality be scored?

The pipeline produces architecture artifacts at each layer:
- **L1**: Library skeletons with function signatures, docstrings, type hints, spec comments
- **L2**: Component wiring — which libraries compose into which components, API contracts between them, dependency topology
- **L3**: Refined file-level code with quality improvements, pattern consistency

Architecture quality is subjective. Two valid architectures for the same spec might have very different structures.

**Dimensions to consider**:
- **Cohesion**: Does each component have a clear, single responsibility?
- **Coupling**: Are dependencies between components minimal and well-defined?
- **Completeness**: Are all spec requirements covered by the architecture?
- **Consistency**: Do similar problems use similar patterns?
- **Clarity**: Are API contracts, interfaces, and responsibilities clear?
- **Extensibility**: Can the architecture accommodate foreseeable changes?

**Questions**:
- Should architecture quality scoring use an LLM judge (send the architecture to Claude/GPT and ask "rate this architecture on these dimensions")? Or should it be mechanical (count dependency violations, measure coupling metrics from the graph)?
- If LLM-based: What context does the judge need? The full spec? Just the component manifest? The dependency graph? All skeleton files?
- How do we handle the fact that multiple valid architectures exist for the same spec? The judge shouldn't penalize a valid alternative design.
- Should there be a separate architecture quality scorecard, or should architecture metrics be added to the existing RunReporter/PlannerReporter?
- What thresholds make sense? Architecture quality is more nuanced than pass/fail.

### Q2: How should code quality be scored?

The pipeline currently measures only `l3.refactor_churn` (changed LOC / total LOC). This tells us how much L3 changed, not whether the code is good.

**Dimensions to consider**:
- **Correctness**: Does the code implement what the spec says? (This is partially covered by existing gates)
- **Readability**: Are names descriptive? Is the code self-documenting?
- **Maintainability**: Is the code structured for easy modification?
- **Pattern adherence**: Does the code follow established patterns in the codebase?
- **Test coverage**: Are the important paths tested? (Currently measured by CI gates)
- **Error handling**: Are edge cases covered? Are errors handled gracefully?

**Questions**:
- Should code quality scoring be LLM-based (send code to judge) or mechanical (cyclomatic complexity, function length, naming conventions)?
- The pipeline generates Python code. Should we use Python-specific quality tools (pylint, mypy, radon) in addition to or instead of LLM judges?
- How does code quality scoring interact with L3 (quality layer)? L3 already uses 5 quality reviewers. Should the scoring happen independently of L3's reviewers, or should it consume L3's review results?
- Per-file scoring vs. aggregate scoring? A single bad file in an otherwise good codebase should be caught.
- Should code quality be a hard gate (bad code blocks the pipeline) or always a soft signal?

### Q3: How should the multi-model runner work?

We want to run the same spec through multiple models independently:
- **Claude Opus** (primary, current default)
- **GPT 5.3 codex xhigh** (high-quality code generation)
- **GLM** (alternative)

Each model run produces a complete pipeline output: L1 skeletons, L2 components, L3 refined code, traces, evidence bundles, scores.

**Questions**:
- Should multi-model execution be a CLI command (`spec-manager eval --multi-model opus,gpt5.3,glm`)? Or a separate script?
- How should model configuration be structured? The planner already accepts `model_id` — should every LLM call in the pipeline be parameterized by model config?
- Should runs be sequential (one model at a time) or concurrent? Sequential is simpler; concurrent saves time but may need isolation.
- Where should per-model artifacts be stored? Current structure is `.pdd_runs/{run_id}/` — should it be `.pdd_runs/{run_id}_{model_id}/`? Or `.pdd_runs/{run_id}/models/{model_id}/`?
- What about mixed-model runs (e.g., Opus for planning, GPT for implementation)? Should this be a supported configuration?
- How do we handle model-specific quirks (different context windows, different JSON formatting tendencies, different instruction-following quality)?

### Q4: How should cross-model comparison work?

Given N model runs on the same spec, we need to compare:
- **Architecture**: Did models produce similar or different architectures? Which is better?
- **Code quality**: Which model's code is higher quality?
- **Efficiency**: Which model needed fewer iterations, fewer demotions, fewer LLM calls?
- **Correctness**: Which model's output better satisfies the spec requirements?
- **Cost**: Token usage, latency, cost per run

**Questions**:
- Should cross-model comparison use an LLM judge ("here are two architectures for the same spec — which is better and why")?
- How do we align outputs for comparison? Model A might produce 7 libraries while Model B produces 9. How do we compare "equivalent" components?
- What visualization/reporting format? Side-by-side markdown? JSON diff? Interactive dashboard?
- Should comparison be pairwise (Model A vs Model B) or aggregate (rank all models on each dimension)?
- How do we account for non-determinism? The same model run twice might produce different results. Do we need multiple runs per model?
- What's the minimum set of comparison metrics that provides actionable insight for model routing?

### Q5: How should the LLM Judge be upgraded?

The existing LLM judge (`refinement/evals/scoring.py`) only scores Phase 0 outputs. We need judges for:
- Architecture quality (Q1)
- Code quality (Q2)
- Cross-model comparison (Q4)
- Spec fidelity (does the output satisfy the spec?)

**Questions**:
- Should there be one generalized judge or specialized judges per domain (arch judge, code judge, spec judge)?
- What model should the judge use? Using the same model to judge its own output creates bias. Should we always use a different model as judge?
- How should judge prompts be structured? Per-dimension scoring with rubrics? Holistic assessment? Comparative ranking?
- How do we evaluate the judge itself? (Meta-evaluation: are the judge's scores correlated with human assessment?)
- Should judge results be cached? Judging is expensive (full artifact context per call).
- How does the judge integrate with the existing scoring framework? New PlannerMetric entries? New ScorecardMetric entries? Separate QualityScorecard?

### Q6: How should artifacts be preserved for comparison?

Each pipeline run produces many artifacts: skeletons, manifests, evidence bundles, traces, reports, scores. For comparison, we need to preserve and version these.

**Questions**:
- What is the minimal set of artifacts needed for comparison? (We don't need every intermediate file)
- Should artifacts be stored in a structured comparison directory? E.g., `comparisons/{comparison_id}/models/{model_id}/`?
- How do we snapshot a run for comparison? Copy all artifacts? Or just reference the run directory?
- Should there be a comparison manifest that lists which runs are being compared, on which spec, with which models?
- How do we handle large artifacts (full Python files, large dependency graphs)? Store as-is, or summarize?
- What metadata should be attached? (timestamp, model version, prompt version, spec version, pipeline version)

### Q7: How does this integrate with the existing scoring and reporting?

Currently we have:
- `RunReporter` → `Scorecard` (pipeline-level, 5+11 metrics)
- `PlannerReporter` → `PlannerScorecard` (planner-level, 5+12 metrics)
- `FinalReportGenerator` → `final_report.md` + `scorecard.json`

Adding quality scoring and multi-model comparison creates new reporting needs.

**Questions**:
- Should quality metrics (arch + code) be added to the existing `Scorecard`, or should there be a new `QualityScorecard`?
- Should the multi-model comparison report be a new report type, or an extension of `final_report.md`?
- How should the reporting hierarchy work? `per_model_scorecard → comparison_report → executive_summary`?
- Should the comparison report include recommendations? ("Based on these results, we recommend Model X for architecture tasks and Model Y for code generation")
- How does this feed into Research Prompt 4 (Model Routing Refinement)? The comparison results should inform which model gets routed where.

---

## What Currently Exists (detailed references)

### RunReporter (`orchestration/scoring.py`)

```python
class RunReporter:
    def compute(self, run_results: dict) -> Scorecard
    def write(self, scorecard: Scorecard) -> tuple[Path, Path]

class Scorecard:
    run_id: str
    hard_gates: list[ScorecardMetric]   # 5 gates
    soft_signals: list[ScorecardMetric] # 11 signals
    overall_pass: bool
    summary: str

class ScorecardMetric:
    name: str
    raw: float
    score: float     # 0.0-1.0
    status: str      # PASS | WARN | FAIL
    hard_gate: bool
    evidence_refs: list[str]
    detail: str
```

### PlannerReporter (`refinement/evals/planner/reporter.py`)

```python
class PlannerReporter:
    def compute(self, verdicts: list, traces: list) -> PlannerScorecard
    def write(self, scorecard: PlannerScorecard) -> None

class PlannerScorecard:
    run_id: str
    model_id: str
    hard_gates: list[PlannerMetric]   # 5 gates
    soft_signals: list[PlannerMetric] # 12 signals
    overall_pass: bool
    decisions_evaluated: int
    decisions_total: int

class PlannerMetric:
    name: str
    raw: float
    score: float
    status: str
    hard_gate: bool
    detail: str
    evidence_refs: list[str]
```

### FinalReportGenerator (`orchestration/final_report.py`)

```python
class FinalReportGenerator:
    def generate(self, run_results, scorecard=None) -> tuple[Path, Path]
    # Produces final_report.md with sections:
    #   Executive Summary, Architecture Topology, Scorecard,
    #   Demotion Summary, Known Risks, Evidence Links
```

### Planner Eval Harness (`refinement/evals/planner/harness.py`)

```python
class PlannerEvalHarness:
    def run_and_score(self, config: EvalConfig) -> EvalResult
    def score_existing_traces(self, run_id: str) -> EvalResult
    # Modes: e2e, slice, replay
    # Scorer map: RESOLVE_SIGNAL, PLAN, UNDER_SPEC, INTEGRATION_ANALYSIS
```

### Trace System (`planner/trace.py`)

```python
class PlannerTrace:
    trace_id: str
    model_calls: list[ModelCallRecord]   # with tokens_in, tokens_out
    tool_calls: list[ToolCallRecord]
    artifacts: dict[str, Any]
    def persist(self, workspace_root) -> Path
    # index.jsonl entry includes model_id, decision_key
```

### Existing LLM Judge (`refinement/evals/judge_scorer.py`)

```python
class LlmJudgeScorer:
    def score(self, expected, actual, context) -> float
    # Used for Phase 0 requirement matching
    # Sends actual vs expected to LLM, asks for similarity score
```

### Layer Outputs (what gets scored)

| Layer | Output | Architecture Artifact | Code Artifact |
|-------|--------|----------------------|---------------|
| L1 | Library skeletons | Function signatures, module structure | Skeleton Python files with spec comments |
| L2 | Component wiring | Component manifest, dependency topology, API contracts | Wiring code, import structure |
| L3 | Refined files | (L2 topology preserved) | Clean code, patterns, error handling |

---

## Design Constraints

1. **No language-specific parsing** — use LLM judges, not AST parsers, for quality assessment. The pipeline is language-agnostic by design.
2. **Judge must not be same model as producer** — to avoid self-evaluation bias, architecture/code produced by Model A should be judged by a different model (or an ensemble).
3. **Mechanical metrics first, LLM judges second** — compute what you can mechanically (coupling, cohesion proxies, function counts, dependency depth) before invoking expensive LLM judges.
4. **Comparison must be apples-to-apples** — same spec, same fixtures, same pipeline version. Only the model varies.
5. **Artifacts must be immutable** — once a run completes, its artifacts must not be modified. Comparison reads from preserved artifacts.
6. **Cost-aware** — LLM judge calls are expensive. Cache aggressively. Don't re-judge unchanged artifacts.
7. **Incremental adoption** — quality scoring and multi-model comparison should be optional additions, not required for every run. The pipeline must work without them.
8. **Model-agnostic harness** — the comparison framework should work with any model that provides a chat completion API. Don't hardcode model-specific behavior.
9. **Output chaining preserved** — multi-model comparison must not break the L1→L2→L3 output chaining requirement. Each model run is independent and self-contained.

---

## Deliverables

1. **Architecture quality scoring design** — dimensions, judge prompts, scoring rubric, integration with existing scorecard
2. **Code quality scoring design** — dimensions, mechanical metrics + LLM judge, per-file and aggregate scoring
3. **Multi-model runner design** — CLI interface, model configuration, artifact storage, isolation strategy
4. **Cross-model comparison framework** — alignment strategy, comparison dimensions, reporting format
5. **LLM Judge architecture** — specialized judges, prompt templates, anti-bias measures, caching, meta-evaluation
6. **Artifact preservation schema** — what to preserve, directory structure, metadata, immutability guarantees
7. **Integration plan** — how new scoring/comparison integrates with existing RunReporter + PlannerReporter + FinalReportGenerator + PlannerEvalHarness
8. **Implementation plan** — concrete steps, files to create/modify, dependencies between components

---

## Context Files (in context.zip)

- `orchestration/scoring.py` — RunReporter + Scorecard + ScorecardMetric (pipeline scoring)
- `orchestration/final_report.py` — FinalReportGenerator (consolidated report)
- `refinement/evals/planner/reporter.py` — PlannerReporter + PlannerScorecard + PlannerMetric
- `refinement/evals/planner/harness.py` — PlannerEvalHarness + EvalConfig + EvalResult
- `refinement/evals/planner/ground_truth.py` — GroundTruthSet + GroundTruthCase + loaders
- `refinement/evals/planner/trace_loader.py` — TraceEntry + LoadedTrace + index/filter/stats
- `refinement/evals/planner/scorers/base.py` — Verdict + _matches_atom
- `refinement/evals/planner/scorers/plan.py` — PlanScorer (dedupe/scope invariants)
- `refinement/evals/planner/scorers/resolve_signal.py` — ResolveSignalScorer
- `refinement/evals/planner/scorers/under_spec.py` — UnderSpecScorer
- `refinement/evals/planner/scorers/integration_analysis.py` — IntegrationAnalysisScorer
- `refinement/evals/planner/export_gt.py` — GroundTruthExporter
- `planner/api.py` — Planner class + PlanningContext/PlanningRequest/PlanningResult
- `planner/trace.py` — PlannerTrace + DecisionRecord + ModelCallRecord
- `orchestration/pdd_lifecycle.py` — PddLifecycle (L1→L2→L3 orchestrator)
- `orchestration/promotion_loop.py` — PromotionLoop (10-step state machine per slice)
- `refinement/evals/judge_scorer.py` — existing LLM judge scorer (Phase 0 only)
- `CURRENT_STATE_ASSESSMENT.md` — what's been evaluated, bugs found
- `LONG_TERM_GOALS.md` — QA methodology, design principles
- `.research/UPCOMING.md` — research prompt roadmap
