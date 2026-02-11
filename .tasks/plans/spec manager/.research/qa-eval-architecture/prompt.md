# Research: QA Eval Architecture with Planner

## What I Need From You

Design the **QA evaluation architecture** for the spec manager's planning module. The planner is now fully implemented and wired into the pipeline. We need to evaluate it with real LLM calls against ground truth, score planner decision quality, and use the trace/replay system for debugging.

This is the second research prompt in the series. The planning module (Research Prompt 1) is implemented. Now we need to test it properly.

---

## Current State

### What Exists

**Planning Module** (`spec_manager/planner/`):
- `api.py` — Planner class + PlanningContext/PlanningRequest/PlanningResult
- `router.py` — LayerPlanner protocol + LayerRouter + CapabilityRouter
- `layers/l1.py` — L1Planner (code-as-spec discovery + function intentions)
- `layers/l2.py` — L2Planner (architecture topology + wiring intentions)
- `layers/l3.py` — L3Planner (quality graph + refactor intentions)
- `tools/research_tool.py` — ResearchTool (steering → evidence → web escalation)
- `tools/integration_tool.py` — IntegrationTool (graph building + risk assessment)
- `tools/constraints_tool.py` — ConstraintsTool (persistent constraint store)
- `tools/evidence_tool.py` — EvidenceTool (TF-IDF over hollowed specs)
- `trace.py` — PlannerTrace + DecisionRecord + ModelCallRecord + ToolCallRecord
- `jit/state_machine.py` — PlannerStateMachine (9 phases, 5 statuses)
- `jit/actions.py` — NextAction (CALL_AGENT, RUN_TOOL, USER_INPUT, COMPLETE, ERROR)

**Planner Integration Points**:
- `PlannerSignalResolver` replaces `AutoSignalResolver` for auto mode — routes through planner first, falls back to research tools
- `PlanStep` in PromotionLoop delegates to planner's `plan_from_gaps()` when planner is injected
- `UnderSpecCheckStep` delegates to planner's `resolve_under_spec()` when planner is injected
- `PddLifecycle._build_planner()` constructs Planner with evidence/steering/research tools

**Trace System** (`planner/trace.py`):
Each planning invocation writes to `workspace/analysis/planner_traces/{trace_id}/`:
```
request.json          — PlanningRequest snapshot
decision.json         — final PlanningResult + confidence + rationale
calls/model_calls.jsonl   — one line per LLM call
calls/tool_calls.jsonl    — evidence-store queries, etc.
artifacts/            — integration graphs, plans, etc.
replay.json           — enough to re-run planner without repo state
```

**Planner Capabilities** (dispatched via CapabilityRouter):
- `RESOLVE_SIGNAL` — resolve ambiguity signals during refinement
- `GAP` — gap understanding/clustering/prioritization
- `PLAN` — plan synthesis (function/wiring/refactor intentions)
- `UNDER_SPEC` — resolve or block; produce constraints or questions
- `INTEGRATION_ANALYSIS` — check integration constraints

**Existing Eval Infrastructure**:
- `EvalRunner` — runs pipeline against spec fixtures with optional LLM judge
- `load_sequence_spec()` — loads manifest + source + ground truth from YAML fixtures
- `WorkspaceIntegration` — creates temporary workspace from spec for eval runs
- `RunReporter` + `Scorecard` — 5 hard gates + 11 soft signals (pipeline-level, not planner-level)

**Existing Eval Results** (before planner):
- Phase 0: 52/52 requirements, 100% coverage
- P1-P10: 38/38 functions, 0 errors
- L1 PromotionLoop: 7/10 steps (provenance blocks INTEGRATE/VERIFY/ALIGN)
- L2 PromotionLoop: 10/10 steps
- L3 PromotionLoop: 10/10 steps
- 10 bugs found and fixed across L1/L2/L3 evals

**What Has NOT Been Tested**:
- Full `pdd_lifecycle.run()` end-to-end (L1→L2→L3 with output chaining)
- Planner decision quality (no ground truth comparison)
- Planner trace inspection and replay
- Cross-layer transitions with demotion propagation

### Fixture Structure

```text
fixtures/
├── chaotic_treasury_expanded.yaml              # Phase 0 manifest
├── chaotic_treasury_expanded/                   # 10 source .md files
├── chaotic_treasury_expanded_ground_truth.yaml  # 52 requirements, 8 libraries
├── chaotic_treasury_expanded_phase0_output/     # Verified Phase 0 output
├── chaotic_treasury_expanded_pdd.yaml           # PDD manifest (Python skeletons)
└── chaotic_treasury_expanded_pdd/               # 8 Python skeleton files
```

### Key Design Principles

1. **Simulations prove nothing** — run step-by-step with REAL LLM calls
2. **Output chaining** — each step consumes the previous step's output, not original fixtures
3. **Manual verification** — fuzzy scorers produce false negatives; always manually verify
4. **Root cause analysis** — trace bugs to origin, assess blast radius, propagate fixes
5. **Block on ambiguity** — don't guess, surface the question

---

## Specific Questions

### Q1: How should planner decisions be compared to ground truth?

The planner makes 5 types of decisions (one per capability). Each has different inputs/outputs:

| Capability | Input | Output | What "correct" means |
|-----------|-------|--------|---------------------|
| RESOLVE_SIGNAL | Ambiguity signal | Resolution dict or None | Answer matches spec intent |
| GAP | Evidence bundle | Gap clusters + priorities | Identifies real gaps, no false positives |
| PLAN | Gaps + discovery | Intentions list | Intentions are actionable, complete, not redundant |
| UNDER_SPEC | Under-spec events | Blocked/constraints/questions | Blocks when it should, resolves when it can |
| INTEGRATION_ANALYSIS | Context | Risk assessment + graph | Identifies real dependencies and risks |

**Questions**:
- What does ground truth look like for each capability? The existing ground truth (`chaotic_treasury_expanded_ground_truth.yaml`) covers Phase 0 outputs (libraries, requirements, sections) but NOT planner decisions.
- Do we need a separate ground truth schema for planner decisions? Or can we derive correctness from downstream pipeline outcomes (e.g., "the planner's plan led to successful implementation")?
- How granular should comparison be? Per-decision exact match vs. aggregate quality metrics?
- How do we handle non-deterministic LLM outputs? The same question may have multiple valid answers.

### Q2: How should the QA eval harness work with the planner in the loop?

The existing QA methodology runs in interactive mode with Claude answering ambiguity questions. Now the planner answers first. The eval should:

1. Run the pipeline with the planner making decisions
2. Capture every planner decision via the trace system
3. Compare planner decisions against ground truth (or Claude's judgment)
4. Score planner quality across multiple dimensions
5. Identify which decisions were wrong and why

**Questions**:
- Should the eval run the planner in isolation (individual capability calls with crafted inputs) or in-situ (full pipeline with planner making real decisions)?
- In in-situ mode, how do we prevent cascading errors? If the planner makes one bad decision early, all subsequent decisions are based on bad state.
- Should there be a "shadow mode" where both the planner AND Claude make decisions, and we compare? How would this work mechanically?
- What is the right eval entry point? `PromotionLoop.run_slice()` per slice? `PddLifecycle.run()` full pipeline? Individual capability calls via `Planner.plan()`?

### Q3: What planner quality metrics should we track?

The existing `RunReporter` tracks pipeline-level metrics (gap closure, gate pass rates, iteration efficiency). We need planner-specific quality metrics.

**Proposed dimensions**:
- **Accuracy**: Did the planner make the right decision? (compare to ground truth)
- **Precision**: Did the planner avoid false positives? (e.g., flagging non-existent gaps)
- **Epistemic hygiene**: Did the planner block when it should have? (no hallucinated answers)
- **Efficiency**: How many LLM calls did the planner make per decision? (token cost)
- **Convergence**: Did planner decisions lead to pipeline convergence? (fewer iterations)
- **Tool usage**: Did the planner use the right tools? (evidence before web, local before remote)

**Questions**:
- Which metrics are hard gates (pipeline blocks if planner fails) vs. soft signals (diagnostics)?
- How do we score epistemic hygiene quantitatively? It's easy to say "the planner hallucinated" but hard to measure systematically.
- Should planner metrics be part of the existing Scorecard, or a separate PlannerScorecard?
- What thresholds define PASS/WARN/FAIL for each metric?

### Q4: How should the trace/replay system be used for debugging?

The trace system writes `request.json`, `decision.json`, `model_calls.jsonl`, `tool_calls.jsonl`, `artifacts/`, and `replay.json` for every planning invocation. This is the raw data.

**Questions**:
- What analysis tools should consume traces? A CLI command? A notebook? A test harness?
- How should replay work? Can we re-run a specific trace_id with modified inputs to test fixes?
- Should there be a trace diff tool that compares two runs (e.g., before/after a planner change)?
- How should traces be aggregated across a full pipeline run? One trace per planner call, but we need run-level summaries.
- What visualization would help? Timeline of decisions? Decision tree? Model call heatmap?

### Q5: How does the planner eval integrate with multi-model comparison?

Research Prompt 3 will cover running the same spec through Opus/GPT 5.3/GLM independently. The planner eval should produce artifacts that feed into model comparison.

**Questions**:
- Should each model have its own trace directory? How are traces organized for cross-model comparison?
- What planner metrics are useful for model comparison vs. what's only useful for debugging?
- Should the eval harness be parameterized by model config, or should model switching happen at a lower level?

### Q6: What ground truth should we create for the treasury spec?

The existing ground truth covers Phase 0 (52 requirements, 8 libraries, 10 sections). For planner eval, we need ground truth at higher levels:

**L1 level**: For each library skeleton, what are the correct function intentions? What under-spec events should block? What signals should resolve to what answers?

**L2 level**: For each component, what is the correct wiring? What architecture gaps should be detected? What topology should emerge?

**L3 level**: For each file, what quality issues should be found? What refactoring intentions are correct? What should NOT be changed (behavior preservation)?

**Questions**:
- Should ground truth be hand-crafted or derived from a "gold standard" run with expert review?
- How do we handle ground truth for non-deterministic decisions? (Multiple valid plans exist for the same gaps)
- Should ground truth capture the decision process (rationale, evidence used) or just the outcome?
- What granularity? Per-slice per-step per-iteration? Or just final outcomes?

### Q7: How should we handle the output chaining requirement?

Per the QA methodology, each step must consume the previous step's output. The planner sits inside the PromotionLoop, which sits inside each layer of PddLifecycle:

```
Phase 0 output → L1 planner decisions → L1 implementation → L2 planner decisions → L2 implementation → L3 planner decisions → L3 implementation
```

**Questions**:
- How do we capture and preserve planner state between layers? The planner is reconstructed per layer in `_build_planner()`.
- Should there be a "planner state snapshot" saved between layers so L2 can see what L1 decided?
- How do we handle the case where L1 implementation is imperfect (e.g., skeleton fixtures) — L2/L3 planner decisions will be based on incomplete input?
- Should we create "ideal L1 output" fixtures to test L2/L3 planner decisions in isolation?

---

## What Currently Exists (detailed references)

### Planner Public API (`planner/api.py`)

```python
class Planner:
    def plan(self, req: PlanningRequest) -> PlanningResult:
        """Route to correct layer planner + capability handler."""

    def resolve_signal(self, signal, context: PlanningContext) -> Any:
        """Resolve an ambiguity signal. Returns resolution dict or None."""

    def plan_from_gaps(self, context: PlanningContext, gaps: list[dict]) -> list[dict]:
        """Generate plan intentions from gaps. Returns intention dicts."""

    def resolve_under_spec(self, context: PlanningContext, events: list[dict]) -> dict:
        """Resolve or block under-spec events. Returns {blocked, constraints}."""
```

### LayerPlanner Protocol (`planner/router.py`)

```python
@runtime_checkable
class LayerPlanner(Protocol):
    layer: str
    def discover(self, ctx: Any) -> dict[str, Any]: ...
    def build_plan(self, ctx: Any, gaps: list, discovery: dict) -> dict: ...
    def resolve_under_spec(self, ctx: Any, events: list, discovery: dict) -> dict: ...
    def resolve_signal(self, ctx: Any, signal: Any) -> dict | None: ...
```

### PlannerTrace (`planner/trace.py`)

```python
class PlannerTrace:
    trace_id: str
    request_snapshot: dict
    decision: DecisionRecord | None
    model_calls: list[ModelCallRecord]
    tool_calls: list[ToolCallRecord]
    artifacts: dict[str, Any]

    def persist(self, workspace_root) -> Path:
        """Write full trace to workspace/analysis/planner_traces/{trace_id}/"""
```

### PlannerSignalResolver (`refinement/interactive/signal_resolver.py`)

```python
class PlannerSignalResolver:
    """Replaces AutoSignalResolver for auto mode.
    Routes through planner first, falls back to research tools."""

    def resolve(self, signal) -> str:
        # 1. Try planner layer-specific resolution
        # 2. Fall back to research tool (steering → evidence → web)
```

### PromotionLoop Integration (`orchestration/promotion_loop.py`)

```python
class PlanStep:
    def __init__(self, planner=None):
        self._planner = planner

    def _plan_via_planner(self, ctx, bundle):
        planning_ctx = PlanningContext(
            run_id=ctx.run_id, slice_id=ctx.slice_id, layer=ctx.layer,
            mode=ctx.mode, workspace_root=ctx.workspace_root,
            slice_root=ctx.slice_root, bundle_ref=bundle,
        )
        return self._planner.plan_from_gaps(planning_ctx, bundle.gaps.open_gaps)
```

### Scoring Framework (`orchestration/scoring.py`)

```python
class RunReporter:
    """Aggregates receipts → scores.json + scorecard.md"""
    def compute(self, run_results) -> Scorecard
    def write(self, scorecard) -> None

class Scorecard:
    hard_gates: list[ScorecardMetric]   # 5 gates
    soft_signals: list[ScorecardMetric] # 11 signals
    overall_pass: bool
```

### JIT State Machine (`planner/jit/state_machine.py`)

```python
class PlanPhase(Enum):
    INIT = "init"
    DISCOVER = "discover"
    INTEGRATION_ANALYSIS = "integration_analysis"
    GAP_UNDERSTANDING = "gap_understanding"
    RESEARCH = "research"
    DESIGN = "design"
    VALIDATE = "validate"
    COMPLETE = "complete"
    ERROR = "error"

class PlannerStateMachine:
    def advance(self, action: NextAction) -> PlanPhase
    def can_advance(self) -> bool
    def reset(self) -> None
```

---

## Design Constraints

1. **Simulations prove nothing** — the eval must use REAL LLM calls against real fixtures
2. **Output chaining** — never evaluate a step on original fixtures if a prior step produced output
3. **Manual verification over fuzzy scoring** — fuzzy scores produce false negatives (47/52 vs real 52/52)
4. **Planner decisions are non-deterministic** — the same input may produce different valid outputs
5. **Trace data must be sufficient for debugging** — if a decision is wrong, the trace must show WHY
6. **Backward compatible** — planner eval extends, doesn't replace, existing pipeline eval
7. **Model-parametric** — the same eval harness must work across different model configurations

---

## Deliverables

1. **Ground truth schema** — what format, what granularity, how to create for treasury spec
2. **Eval harness design** — how to run planner QA (in-situ vs. isolated, entry points, shadow mode)
3. **Planner scorecard** — metrics, thresholds, hard gates vs. soft signals, integration with RunReporter
4. **Trace analysis tooling** — CLI commands, replay, diff, aggregation, visualization
5. **Output chaining strategy** — how planner state flows between layers, fixture creation for isolated testing
6. **Multi-model compatibility** — how trace/scoring integrates with model comparison (prep for Research Prompt 3)
7. **Implementation plan** — concrete steps, files to create/modify, dependencies between components

---

## Context Files (in context.zip)

- `planner/api.py` — Planner class + core types
- `planner/router.py` — LayerPlanner protocol + routing
- `planner/layers/l1.py` — L1Planner (code-as-spec)
- `planner/layers/l2.py` — L2Planner (architecture)
- `planner/layers/l3.py` — L3Planner (quality)
- `planner/trace.py` — PlannerTrace + record types
- `planner/jit/state_machine.py` — PlannerStateMachine
- `planner/tools/research_tool.py` — ResearchTool
- `planner/tools/evidence_tool.py` — EvidenceTool
- `refinement/interactive/signal_resolver.py` — PlannerSignalResolver + create_resolver
- `orchestration/promotion_loop.py` — PromotionLoop + PlanStep + UnderSpecCheckStep
- `orchestration/pdd_lifecycle.py` — PddLifecycle + _build_planner()
- `orchestration/scoring.py` — RunReporter + Scorecard
- `orchestration/under_spec/manager.py` — UnderSpecManager
- `CURRENT_STATE_ASSESSMENT.md` — what's been evaluated, bugs found
- `LONG_TERM_GOALS.md` — QA methodology, design principles, eval strategy
- `chaotic_treasury_expanded_ground_truth.yaml` — existing Phase 0 ground truth
