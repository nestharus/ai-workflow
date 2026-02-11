## 1) Planning Module architecture (core abstractions, API, and how it replaces AutoResponder/AutoSignalResolver)

### The big idea

Introduce a **Planner** that is the *single* auto-mode decision authority across:

* interactive refinement signal resolution (today: `AutoResponder`/`AutoSignalResolver`)
* PromotionLoop planning-related steps (today: ad-hoc per-step logic + UnderSpec pipeline)

Research becomes a **tool** the planner can invoke when needed.

---

### Module layout

Create a new package: `spec_manager/planning/`

Recommended submodules (minimal but complete):

* `spec_manager/planning/api.py`

  * public types: `PlanningRequest`, `PlanningResult`, `PlanningContext`, `Planner`
* `spec_manager/planning/router.py`

  * `LayerRouter`, `CapabilityRouter` (routes to layer planners + per-capability strategies)
* `spec_manager/planning/layers/`

  * `l1.py`: `L1Planner` (+ L1 discovery + L1 skeleton plan generator)
  * `l2.py`: `L2Planner`
  * `l3.py`: `L3Planner`
* `spec_manager/planning/tools/`

  * `research_tool.py`: adapter over `ResearchCoordinator` (+ optional BrennerBot tool)
  * `integration_tool.py`: integration analysis (skeleton extraction → graph → diff/risk)
  * `constraints_tool.py`: adapter over `ConstraintsStore`/`UnderSpecManager`
  * `evidence_tool.py`: adapter over `EvidenceStoreResearcher`/`EvidenceIndex`
* `spec_manager/planning/jit/`

  * `state_machine.py`: pause/resume planning state machine (adapted from article_writer)
  * `actions.py`: `NextAction` pattern for planning micro-phases
* `spec_manager/planning/trace.py`

  * `PlannerTrace`, `DecisionRecord`, `ToolCallRecord`, `ModelCallRecord`, `ReplayBundle`

This keeps “planning” cohesive without rewriting PromotionLoop.

---

### Core abstractions

#### 1) `PlanningRequest`

A single request type that can represent:

* “resolve this ambiguity signal”
* “turn these gaps into a plan”
* “resolve these under-spec events”
* “produce integration analysis for this slice/layer”

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
    metadata: dict[str, Any] = None

@dataclass
class PlanningRequest:
    capability: Capability
    context: PlanningContext
    inputs: dict[str, Any]            # gaps/events/spec text/etc (dynamic by design)
    constraints_hint: dict[str, Any] | None = None
```

#### 2) `PlanningResult`

A result that can represent:

* resolved decision text (steering response)
* a plan artifact (intentions)
* a set of unresolved blockers/questions (under-spec)
* integration analysis artifacts

```python
@dataclass
class PlanningResult:
    status: Literal["OK", "BLOCKED", "NEEDS_INPUT", "NOOP", "ERROR"]
    outputs: dict[str, Any]           # dynamic artifacts: plan, decisions, questions, graphs
    trace_id: str
```

#### 3) `Planner` (public API)

Single entrypoint plus convenience wrappers:

```python
class Planner:
    def plan(self, req: PlanningRequest) -> PlanningResult: ...

    # Adapters for existing call sites (don’t leak planning internals):
    def resolve_signal(self, signal) -> "SteeringResponse | None": ...
    def plan_from_gaps(self, ctx, gaps: list[dict]) -> list[dict]: ...
    def resolve_under_spec(self, ctx, events: list[dict]) -> dict[str, Any]: ...
```

---

### How it replaces/wraps `AutoResponder` and `AutoSignalResolver`

#### Replace `AutoSignalResolver` with a Planner-backed resolver (no PromotionLoop changes required)

Add a new resolver implementation:

* `PlannerSignalResolver` implements the existing `SignalResolver` protocol.
* Internally calls `Planner.resolve_signal(signal)`.

**Drop-in change:** update `create_resolver(mode="auto")` to return `PlannerSignalResolver` instead of `AutoSignalResolver` when `use_planner=True` (feature flag for migration).

#### What happens to `AutoResponder`?

Treat it as a *legacy policy stage* and migrate it into `planning/tools/research_tool.py`:

* SteeringScript match
* Evidence store lookup
* ResearchCoordinator fallback

Planner calls those stages as **tools** in a controlled order, rather than being the system.

Concretely:

* `AutoResponder.respond()` becomes a helper used by `ResearchTool.answer()` (or is inlined).
* Existing behavior preserved while planner adds integration analysis + design planning.

---

### Planner internal data flow (single request)

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
           VALIDATE (coverage + constraints + “block on ambiguity”)
      → Trace.persist()
  → PlanningResult(outputs + trace_id)
```

This is the key architectural shift: **planning is not “a response.” Planning is a multi-phase decision workflow with state.**

---

## 2) Layer-aware planner hierarchy (general planner + skeleton planners + discovery + research dimensions)

### Hierarchy

Implement a two-level planner structure:

1. **GeneralPlanner (root)**

* owns routing, tool orchestration, model routing, trace
* delegates layer specifics

2. **Layer planners (L1/L2/L3)**

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
  ├─ ResearchTool (EvidenceStore + Firecrawl + optional BrennerBot)
  ├─ IntegrationAnalyzer (skeleton → graph → diff/risk)
  ├─ ConstraintsTool (constraints + under-spec lifecycle)
  └─ Trace/Replay
```

---

### “Layer-specific discovery routing” (no parsing; LLM does pattern recognition)

Each layer planner implements:

```python
class LayerPlanner(Protocol):
    layer: Layer
    def discover(self, ctx: PlanningContext) -> dict[str, Any]: ...
    def build_plan(self, ctx: PlanningContext, gaps: list[dict], discovery: dict) -> dict[str, Any]: ...
    def resolve_under_spec(self, ctx: PlanningContext, events: list[dict], discovery: dict) -> dict[str, Any]: ...
```

**Discovery outputs are graphs/skeletons** (dynamic JSON), not ASTs.

#### L1 Discovery (code concerns)

* Input: slice files (not just `.py`, ideally “all text-like files”)
* Output: **code-as-spec skeleton graph**

  * nodes: `function`, `class`, `spec_comment_block`
  * edges: `declares`, `mentions`, `calls` (best-effort, LLM-derived)

#### L2 Discovery (architecture)

* Input: component manifests, pins registry, entrypoints, event handlers, “arch files”
* Output: **architecture topology graph**

  * nodes: `component`, `pin`, `edge`, `handler`, `route`
  * edges: `provides`, `consumes`, `wired_to`, `declared_in`

#### L3 Discovery (quality)

* Input: changed files + quality receipts + diffs
* Output: **quality graph**

  * nodes: `file`, `function_span`, `smell`, `risk`
  * edges: `contains`, `impacts`, `depends_on`

---

### Research dimensions (layer research vs web research)

Treat “research” as a routed capability with explicit dimension:

* **Local evidence research**

  * Evidence store search (existing `EvidenceIndex`)
  * Prior constraints / prior decisions (constraints store)
* **Layer research**

  * L1: “code-as-spec interpretation” (what does the skeleton imply?)
  * L2: architecture pattern lookup (within repo + internal docs)
  * L3: refactor best practices (repo conventions + receipts)
* **Web research**

  * Firecrawl pipeline (GLM tool use)
* **External research tool**

  * optional BrennerBot (see section 6)

The planner chooses dimension based on:

* whether the question is resolvable from code/architecture context
* whether external facts are required (APIs, standards, third-party behavior)

---

## 3) Model routing strategy (Opus vs GPT‑5.2 XHigh vs GLM‑4.7)

### Principle: route by **work type**, not by pipeline stage

The current research coordinator always does Opus → GLM → GPT. Planning should instead dispatch *only what’s needed*.

### Model strengths (operational)

* **Opus**: deep reasoning, integration tradeoffs, adversarial critique, “what am I missing?”
* **GPT‑5.2 XHigh**: structured synthesis, plan generation, balanced judgment, writing executable plans
* **GLM‑4.7**: tool-heavy work (web research), breadth-first retrieval, search iteration

### Routing matrix (planner tasks → model)

| Planner task type                                                      | Primary model | Secondary model (only if gated) |
| ---------------------------------------------------------------------- | ------------: | ------------------------------: |
| Integration analysis (graph diff, risk, blast radius)                  |          Opus | GPT (format + plan integration) |
| Plan synthesis (intentions/wiring/refactor steps, acceptance criteria) | GPT‑5.2 XHigh |                 Opus (critique) |
| Under-spec resolution from local repo context                          |          Opus |              GPT (final answer) |
| Web research execution (Firecrawl/search loops)                        |       GLM‑4.7 |                 GPT (synthesis) |
| “What should we research?” (query generation, hypotheses)              |          Opus |                               — |
| “Is this plan coherent + minimal?” (plan lint)                         |          Opus |                               — |
| Normalization into required JSON/dict shapes                           |           GPT |                               — |

### Non-brute-force dispatch policy (important)

Implement a gated “escalate only when needed” policy:

1. **Try deterministic/local first**

* constraints store coverage
* steering script match
* evidence store search

2. **Try integration analysis**

* if code/architecture already implies answer, decide without web

3. **Only then do web**

* if (and only if) planner flags “requires external facts”

4. **Critique only when risk is high**

* architecture wiring changes (L2)
* refactors spanning multiple files (L3)
* low confidence decisions

This avoids the “always run three models” anti-pattern.

---

## 4) PromotionLoop integration (GAP / PLAN / UNDER_SPEC)

### Recommended integration approach: **wrap first**, then optionally replace

You can integrate without rewriting the 10-step PromotionLoop:

#### A) GAP step integration

* Keep `GapExplorationStep`’s current layer dispatch (it already matches the step dispatch table).
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
* emit “decision requirements” (what constraints are needed before implementing)

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
* L3: refactor plan grouped by function-span with “no behavior change” criteria

#### C) UNDER_SPEC integration

Do **not** delete `UnderSpecManager`; make it call planner for resolution.

* UnderSpecManager remains the authority for:

  * constraint persistence
  * validation
  * partition resolved vs blocked

* Planner becomes the *resolver* it consults when it needs an answer.

Concretely:

* Add an injectable resolver interface to UnderSpecManager (or pass `Planner`):

  * `resolver.resolve(event, ctx) -> DecisionOutcome`

Planner output:

* either a resolved constraint payload
* or a blocked question (with structured options + “what evidence would decide”)

This unifies:

* UnderSpec from PlanStep (planning gate uncovered decisions)
* UnderSpec from ImplementStep (runtime ambiguity)
* UnderSpec from interactive refinement (spec ambiguity)

### Longer-term option: collapse GAP+PLAN+UNDER_SPEC into one planner step

After wrap-first stabilizes, you can introduce a single `PlanningStep` that internally runs the planner micro-state-machine:

* DISCOVER → GAP → PLAN → UNDER_SPEC
  but keeps the PromotionLoop macro-state-machine unchanged.

---

## 5) Adapting JIT tooling patterns from `scripts/article_writer/`

### What to reuse directly

1. **State machine core** (pause/resume + WAITING_INPUT)

* The planner needs this for:

  * under-spec questions (interactive mode)
  * multi-tool planning sequences (integration → research → design → validate)
  * “ask for more inputs” without guessing

2. **NextAction pattern**

* Use `NextAction` to make planner execution explicit and testable:

  * `CALL_AGENT` (Opus/GPT agent)
  * `RUN_TOOL` (evidence store search, firecrawl)
  * `USER_INPUT` (interactive under-spec)
  * `COMPLETE`

3. **Context logging**

* Article writer’s `ContextLogger` pattern maps cleanly to:

  * `PlannerTrace` (structured audit log + replay)

### What to adapt (rename + re-scope)

1. **Phase enum**
   Instead of article phases (DRAFT/REVISE), planner phases should be:

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

2. **ReviewPack concept**
   Turn “5 reviewers for L2/L3” into a first-class `ReviewPack`:

* `ReviewPack(name, agents[], merge_strategy, acceptance_checks[])`
* Planner can dynamically construct packs based on:

  * layer
  * gap type
  * risk (e.g., add adversarial reviewer only when risky)

This generalizes beyond GAP (it can also validate plans).

3. **extract_skeleton**
   Replace “document skeleton extraction” with **layer skeleton extraction**:

* L1: code skeleton graph
* L2: architecture topology graph
* L3: quality graph

Implementation remains “LLM for pattern recognition.”

### What must be purpose-built

* **ModelRouter** (planning-specific, not article-writing)
* **IntegrationAnalyzer** (graph diff + risk)
* **PromotionLoop adapters** (bundle update + step hooks)
* **PlannerTrace + ReplayBundle** (for QA eval + debugging)

---

## 6) BrennerBot analysis (what to learn/avoid; whether to use it as a tool)

### What BrennerBot does well

* **Explicit loop structure + operatorized thinking**

  * BrennerBot describes an “11-phase loop” and four core cognitive operators (Level‑Split, Exclusion‑Test, Object‑Transpose, Scale‑Check) as reusable moves for rigorous inquiry. ([BrennerBot][1])
* **Multi-agent role separation**

  * The project explicitly assigns distinct responsibilities to different agents/models (hypothesis generation, test design, adversarial critique). ([GitHub][2])
* **Auditable artifacts + evidence hygiene**

  * It emphasizes durable artifacts (hypothesis slates, discriminative tests, assumption ledgers) and an evidence-pack workflow with stable IDs intended for citation. ([GitHub][2])
* **Deterministic merge + coordination bus**

  * It’s built around Agent Mail as a coordination bus with a thread-id “join key” contract tying conversations, execution sessions, and artifacts together. ([GitHub][2])

### Where it’s wasteful for spec-manager purposes

* **Human-in-the-loop cockpit runtime**

  * BrennerBot’s reference architecture expects humans to manage multiple terminal sessions (ntm/tmux) and compile artifacts, rather than programmatic dynamic dispatch. ([GitHub][2])
* **Triangulation as a default habit**

  * It recommends “triangulation” by reading/producing multiple model syntheses to control narrative bias. That’s valuable for scientific research, but often overkill for engineering planning where you can gate by risk/confidence. ([GitHub][2])

### What the planner should learn from BrennerBot (directly transferable)

* **Operator library as planning operators**

  * Level‑Split → separate “spec vs implementation vs integration”
  * Exclusion‑Test → generate discriminative checks (“what evidence would falsify this plan?”)
  * Object‑Transpose → propose alternative wiring/entrypoint structures
  * Scale‑Check → blast-radius and complexity sanity checks
* **Join-key contract**

  * Use a stable `trace_id` (run_id/slice_id/iteration/capability/event_id) that ties:

    * planner trace
    * model calls
    * artifacts produced
    * eval comparisons

### Should spec-manager call BrennerBot as an external tool?

Recommendation: **optional, narrow use**

* Use BrennerBot-style workflows as a *specialized external research tool* only when:

  * an under-spec event is fundamentally a research problem (not a code-integration problem)
  * you benefit from hypothesis/test framing and adversarial critique
* Otherwise, build competing capabilities inside the planner:

  * because spec-manager needs programmatic routing + automatic tool use (Firecrawl/evidence store/constraints), not human-managed terminals.

In other words: borrow the methodology; don’t inherit the runtime.

---

## 7) QA instrumentation (planner is the unit under test)

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

  * `model_calls.jsonl` (one line per run_agent call: agent_name/model/prompt_hash/output_hash)
  * `tool_calls.jsonl` (evidence store queries, firecrawl outputs, etc.)
* `artifacts/`

  * `integration_graph.json` (if produced)
  * `plan.json` (intentions)
  * `under_spec_questions.json` (if blocked)
* `replay.json`

  * enough to re-run planner in “replay mode” without touching the repo state

### Decision record schema (what the evaluator compares to ground truth)

Each decision should include:

* `decision_text` (or `constraint_payload`)
* `confidence`
* `assumptions` (explicit)
* `evidence_refs` (file paths, snippet hashes, web sources)
* `alternatives_considered` (at least 2 when non-trivial)
* `discriminative_checks` (what would change the decision)

This makes QA comparisons meaningful: the evaluator can score not just correctness, but *epistemic hygiene* and failure mode.

### Debugging hooks

Add a `PlannerDebugView` helper that can render (from trace):

* “why did you choose this?” (from stored rationale)
* “what evidence did you use?”
* “which model touched this decision?”
* “what would have made you block earlier?”

No new runtime UI required—just deterministic files.

---

## 8) Migration path (no test breaks, incremental cutover)

### Phase 0 — add planner with adapters (no behavior changes)

* Implement `Planner`, but internally:

  * route `RESOLVE_SIGNAL` to the existing AutoResponder/ResearchCoordinator chain
  * record traces (optional, behind flag)

### Phase 1 — replace AutoSignalResolver in auto mode (safe cutover)

* Add `PlannerSignalResolver` implementing `SignalResolver`.
* Update `create_resolver(mode="auto")` to return planner-backed resolver behind `--use-planner`.
* Keep `InteractiveSignalResolver` behavior unchanged (planner first, then prompt).

### Phase 2 — UnderSpecCheck uses planner (centralizes ambiguity resolution)

* Inject planner into UnderSpecManager as the resolver.
* Keep constraints persistence/validation in UnderSpecManager.

### Phase 3 — PlanStep uses planner (replace simplistic intention generation)

* Replace `_plan_l1/_plan_l2/_plan_l3` with `planner.plan(capability="PLAN")`.
* Keep planning gate unchanged initially; later let planner produce explicit decision requirements.

### Phase 4 — GAP post-processing via planner (optional)

* Keep existing gap detectors but let planner cluster/prioritize + attach integration notes.

### Phase 5 — deprecate AutoResponder as a public actor

* Move steering/evidence/research logic into planner tools.
* Leave AutoResponder as a thin compatibility wrapper until tests are updated.

This path preserves the current behavior while progressively shifting authority to the planner.

[1]: https://brennerbot.org/ "BrennerBot"
[2]: https://github.com/Dicklesworthstone/brenner_bot "GitHub - Dicklesworthstone/brenner_bot: Harness the scientific methods of Sydney Brenner using AI Agents"
