## The real problem

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

---

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

## 2) Fractal architectural planning algorithm (L2)

This is scoped, multi-proposer, tradeoff-informed, and composable.

### 2.1 Inputs to architectural planning

For a given run + slice set:

1. **Authoritative constraints**

   * system-level + relevant library-level constraints
   * previously committed architecture decisions (software-only)

2. **Library responsibilities** (Phase 0 output)

   * charters, detail files, constraints.md, analysis.md

3. **Library interaction knowledge**

   * Phase 0 references (where text was routed, cross-library refs)
   * L1 outputs (pin/edge proposals, imports, call graph summaries)
   * L2 analysis step output (`architecture_graph.index.json`-like summaries)

### 2.2 Build an interaction graph (LLM synthesis, preserved as artifact)

Produce a `LibraryInteractionGraph`:

* `nodes`: libraries (plus optional key components)
* `edges` with:

  * `type`: call | event | shared-store | batch | sync-io
  * `direction`
  * `data`: payload summary (shape-level)
  * `ordering`: must-happen-before, idempotency needs
  * `traffic`: low/med/high (coarse)
  * `failure_mode`: retry/at-least-once/exactly-once/compensate
  * `constraint_hotspot`: bool

This graph is the *basis* for inter-library architecture scoping.

### 2.3 Define scopes (fractal)

Create two scope sets:

#### A) Intra-library scopes (per library)

* scope_id: `intra:<LIB>`
* focus: internal organization, boundaries, state ownership, concurrency model

#### B) Inter-library scopes (per interaction edge or small cluster)

* scope_id: `inter:<LIB_A>→<LIB_B>:<edge_type>`
* focus: contracts, coupling direction, communication style, shared state rules

Scoping rule: **atomic units**

* intra: library internals
* inter: relationships (edges), not whole-system “big bang”

### 2.4 Multi-proposer candidate generation per scope

For each scope, generate `K` candidates (K=3–5 recommended).

#### Tradeoff position assignment (no convergence)

Before running proposers, the orchestrator assigns each proposer a **tradeoff profile** and an **archetype hint**:

* Tradeoff axes are selected from `design/TRADEOFFS.md` (not all axes; just relevant ones per scope).
* Archetype hints come from `design/patterns/CORE_PATTERNS.md`:

  * layered, hexagonal, event-driven, pipe-and-filter, microkernel, etc.

Each proposer receives:

* scope context (charter, constraints, interaction subgraph, current skeleton)
* its assigned tradeoff position
* a list of other positions being explored (but not their proposals)
* a strict instruction: **do not converge**; explore your assigned position

#### Candidate output contract

Each proposer must emit structured JSON:

* `candidate_id`
* `scope_id`
* `archetype`
* `tradeoff_profile`: explicit priorities + sacrifices
* `architecture_changes`: topology/wiring intentions (L2-level)
* `contracts`: interfaces/events/messages (if inter-scope)
* `constraints_introduced`:

  * software constraints (e.g., message schema stability, idempotency requirement)
  * non-software obligations (license, ops burden, costs)
* `decision_requirements`:

  * missing constraints needed to choose safely
* `compatibility_requirements`:

  * what other scopes must satisfy (e.g., “producers must publish event X”)

### 2.5 Candidate evaluation

Run two evaluators:

1. **Constraint evaluator (LLM)**

   * For each authoritative constraint: satisfied / violated / unknown
   * For each introduced obligation: can we satisfy with known constraints? if not → under-spec question

2. **Architecture reviewers (existing L2 review pack)**

   * boundary correctness, topology, pin coverage, drift, governance

Produce a `ScopeEvaluation` per candidate:

* `blockers`: violations or unknowns
* `risk`: coupling + error amplification estimate
* `reversibility`
* `recommendation`: accept / reject / needs-human

### 2.6 Composition across scopes

Composition is constraint-driven, not “merge proposals blindly”.

**Algorithm (greedy with backtracking, LLM-assisted when needed):**

1. Select best intra-library candidate per library that has **no violations** and **no unknowns requiring humans**.
2. For each inter-library scope:

   * filter candidates compatible with chosen intra candidates (`compatibility_requirements`)
   * pick best remaining candidate
3. If an inter candidate is incompatible:

   * try the next-best inter candidate
   * else backtrack intra selection for the involved library(ies)
4. If composition cannot satisfy constraints without human input:

   * emit under-spec events with *constraint questions*, not solution requests

**Output**

* `SelectedArchitecturePlan`:

  * chosen candidates by scope
  * a consolidated set of L2 wiring intentions
  * generated software constraints to push down to L1

### 2.7 Connect to existing L2 layer output

L2 currently expects:

* “architecture topology + wiring intentions”
* an assembler that applies minimal patches without inventing business logic

So the L2 plan output becomes:

* `intentions`: wiring tasks derived from `SelectedArchitecturePlan`
* `decision_requirements`: under-spec questions surfaced **before** implementation
* `artifacts`:

  * `architecture_candidates.json`
  * `architecture_evaluations.json`
  * `interaction_graph.json`
  * `selected_architecture.json`

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

  * consumes constraints + interaction graph
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

---

## 5) Non-software constraint model

### 5.1 Representation

Add explicit dimension + authority metadata to constraint questions and facts:

* `dimension`: software | legal | economic | organizational | temporal | operational
* `authority_required`: planner_ok | human_required
* `decision_type`: dependency | infrastructure | data_policy | security | performance | architecture

### 5.2 What the system can do autonomously

Allowed:

* generate **questions** and **checklists**
* apply **human-provided policies** (e.g., “Apache 2.0 only”)
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

* it’s stdlib / already-approved internal module
* it’s low blast radius + easily reversible

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

* Add `ArchitecturePlannerStrategy` invoked from `planner/layers/l2.py build_plan()`
* Persist architecture artifacts under run reports (`reports/pdd/<run_id>/...`) using existing `_write_run_report()` in lifecycle

---

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

* new `planner/architecture/*` (interaction graph, scoping, proposer orchestration, evaluation, composition)
* integrate into `planner/layers/l2.py`

Outcome:

* architecture planning explores tradeoff space, chooses or blocks with precise questions

### Step 8 — Propagation hooks via coordination

Files:

* `orchestration/coordination/*` (optional small additions)
* `orchestration/under_spec/manager.py` emit wake events on store updates

Outcome:

* blocked slices wake when constraints arrive

---

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
