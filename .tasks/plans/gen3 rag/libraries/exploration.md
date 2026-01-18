# Exploration Library

Noise detection, seed queues, interestingness scoring, learning progress, novelty, information gain.

---

## P8.8 The new idea engine

Noise becomes one input. The main generative driver becomes "pattern transfer + hybridization."

### New objects

* ModuleLibrary
* FactorDictionary
* PatternDecomposition graph (pattern = modules + wiring)
* TradeoffProfile (metrics + contexts)
* IdeaCandidate (a proposed substitution or hybrid with predicted gain)

### New pipeline

1. detect opportunity

   * a noise seed
   * a near-miss parse
   * repeated conflict
   * a region with high cost patterns
2. compile context bundle

   * local subgraph
   * factor-needs signature
   * constraints and risk tags
3. propose candidates

   * substitution candidates from similar factor profiles
   * hybrid candidates from complementary tradeoffs
4. simulate in workspace

   * apply rewrite in hippocampal workspace overlay
   * run local relaxation
   * compute effect delta
5. validate

   * LLM labels and explains
   * system checks provenance and constraints
6. distill and promote

   * if repeated success: promote module or pattern
   * if repeated failure: store failure memory

DreamCoder is a useful reference point for the "learn a library of components and a search policy, then reuse them" loop, even though your substrate is graphs rather than programs.

---

### D34 NoiseSeed

```text
NoiseSeed {
  seed_id: SeedId
  seed_type: enum {
    high_tension, high_residual, high_variance,
    grammar_near_miss, repeated_branching,
    retrieval_dead_end, adapter_drift,
    bridge_gap, concept_collision
  }
  target: enum {node, edge, subgraph, hypothesis, rule, adapter}
  target_id: bytes
  hyp_scope: HypScopeRef
  provenance: list<SpanRef>            // may be empty for structural-only seeds
  graph_coords: GraphCoordRef?         // subgraph anchors, match bindings
  metrics: {T, r, var, novelty, recurrency}
  prov_score: float
  risk_tags: set<RiskTag>
  created_t: Time
  status: enum {queued, exploring, parked, promoted, quarantined, archived}
}
```

---

### D35 ExplorationTrace

```text
ExplorationTrace {
  trace_id: TraceId
  seed_id: SeedId
  actions: list<ActionRecord>          // walk, expand, branch, validate, propose_rule, propose_bridge
  before_metrics: {T, r, var}
  after_metrics: {T, r, var}
  evidence_used: list<SpanRef>
  proposals: list<ProposalRef>         // graph deltas, new tokens, new rules, new bridges
  outcome: enum {gain, neutral, loss}
  created_t: Time
}
```

---

### D36 EvidenceBundle

```text
EvidenceBundle {
  bundle_id: BundleId
  seed_id: SeedId
  neighborhood: list<NodeId|EdgeId>    // top-k by tension and relevance
  competing_hyps: list<HypId>
  support_spans: list<SpanRef>
  near_miss_patterns: list<PatId>
  candidate_bridges: list<EdgeCandidate>
  budget_tokens: int
}
```

---

### D37 CuriosityBudget

```text
CuriosityBudget {
  domain: DomainId
  window: TimeWindow
  explore_budget: float
  llm_budget: float
  spent_explore: float
  spent_llm: float
}
```

---

### D38 IdeaToken

A stable "thread" once substantiated.

```text
IdeaToken {
  idea_id: IdeaId
  label: string                        // human handle
  tok_type: TokTypeId                  // Idea, HypothesisFrame, Pattern, RuleCandidate, BridgeCandidate
  anchors: list<NodeId|SpanRef>
  canonical_frame: string              // compact description for expansion
  confidence: float
  hyp_id: HypId
  created_t: Time
}
```

---

### D63 InquiryTask

```text
InquiryTask {
  task_id: TaskId
  target: enum {node, edge, hypothesis, rule, adapter}
  target_id: bytes
  objective: enum {reduce_uncertainty, resolve_conflict, validate_bridge}
  expected_gain: float
  cost: float
  created_t: Time
}
```

---

### P7.1 Noise features

For a seed (s), define a feature vector:
[
\phi(s) = [T(s), r(s), \widehat{var}(s), nov(s), rec(s), prov(s), risk(s), cost(s)]
]

Sources for signals:

* (T) tension from field edges
* (r) anchor residual
* (\widehat{var}) uncertainty proxy
* (nov) novelty score
* (rec) recurrence across time and contexts
* (prov) provenance score (P6)
* (risk) governance risk (P4)
* (cost) predicted exploration cost

---

### P7.2 Interestingness score

[
I(s) = w_T T + w_r r + w_v \widehat{var} + w_n nov + w_{rec} rec + w_p prov - w_k risk - w_c cost
]

Weights can be:

* fixed per domain
* adapted via P4 light feedback (reward shaping)

---

### P7.3 Learning progress

Use improvement, not raw error. This avoids fixation on irreducible randomness. ([arXiv][p7-1])

For a trace (t) on seed (s):
[
LP(s) = \max(0,; \mathcal{L}*{before}(s) - \mathcal{L}*{after}(s))
]
where (\mathcal{L}) can be a blend of tension and residual:
[
\mathcal{L}(s)=\alpha T(s) + \beta r(s)
]

This aligns with "learning progress" intrinsic motivation in IAC-style systems. ([Swarthmore Computer Science][p7-5])

---

### P7.4 Novelty

Two options, both usable.

**Distance novelty**
[
nov(s)=\min_{p \in \mathcal{P}} |z(s)-z(p)|
]
where (z(\cdot)) is a structural embedding of the seed subgraph or pattern.

**Prediction novelty**
Use an exploration bonus based on prediction error of a fixed target representation, similar in spirit to RND. ([arXiv][p7-6])

Novelty search literature supports novelty as a primary driver for open-ended discovery. ([Swarthmore Computer Science][p7-2])

---

### P7.5 Information gain for inquiry selection

For candidate inquiry action (a):
[
IG(a) = H(\Theta \mid D) - \mathbb{E}_{y \sim p(y \mid a,D)}[H(\Theta \mid D \cup (a,y))]
]
This is the classic expected informativeness frame for selecting data. ([MIT Press Direct][p7-3])

---

### P7.6 Utility for scheduling

[
U(s) = I(s) + \lambda LP(s) + \mu \max_{a \in A(s)} IG(a)
]
subject to budgets:
[
\sum cost(\text{explores}) \le B_{explore}, \quad \sum cost(\text{llm calls}) \le B_{llm}
]

---

### Algorithm 32: Diagnostics-driven inquiry planning

```pseudo
function PLAN_INQUIRIES(epoch e):
  candidates = FIND_HIGH_VALUE_AMBIGUITIES(e)        // high usage, high tension, high variance
  tasks = []
  for c in candidates:
    gain = EST_EXPECTED_UNCERTAINTY_REDUCTION(c)
    cost = EST_COST(c)
    tasks.append((gain/cost, MAKE_TASK(c)))

  return TOPK(tasks, budget=validation_budget)
```

Active learning literature gives the template for selecting data to reduce uncertainty efficiently.

---

### Algorithm 33

#### Noise scan

Runs after any of:

* local field update
* grammar parse step
* gating change
* adapter drift event
* repeated branch events

```pseudo
function NSCAN(epoch e, workspace_view W):
  seeds = []

  for v in W.nodes_touched:
    if T(v) > T0: seeds.add(SEED(high_tension, v))
    if r(v) > r0: seeds.add(SEED(high_residual, v))
    if var(v) > v0: seeds.add(SEED(high_variance, v))

  for m in W.grammar_near_misses:
    seeds.add(SEED(grammar_near_miss, m.subgraph_anchor))

  for gap in W.bridge_gaps:
    seeds.add(SEED(bridge_gap, gap.cluster_pair))

  for drift in W.adapter_drift_events:
    seeds.add(SEED(adapter_drift, drift.adapter_id))

  WRITE_SEEDS_APPEND_ONLY(seeds)
  return seeds
```

---

### P7C2 Exploration stays bounded

**Claim.** Exploration terminates inside each window because spending is monotone and capped by budgets.

**Sketch.**

* Each explore step consumes positive budget.
* Budgets are finite per window.
* Loop stops when budget hits zero.

Lean skeleton:

```lean
namespace CuriosityBudget

def spend (b : Nat) (c : Nat) : Nat := b - min b c

theorem spend_monotone (b c : Nat) : spend b c ≤ b := by
  simp [spend]

theorem finite_steps_under_budget
  (B : Nat) (costs : List Nat) (hpos : ∀ c ∈ costs, 0 < c) :
  (List.foldl spend B costs) ≤ B := by
  -- fold of spend stays ≤ initial budget
  -- extend to show number of positive-cost actions is bounded by B / cmin
  sorry

end CuriosityBudget
```

---

### P7C3 Learning progress avoids irreducible noise fixation

**Claim.** A reward based on improvement de-prioritizes regions where prediction error stays high with little improvement.

**Sketch.**

* In purely noisy regions, training yields little reduction in loss, so (LP) stays near zero.
* Scheduler selects seeds with higher (LP), so compute flows toward learnable structure.

This is the core argument in compression progress and learning progress intrinsic motivation work.

---

### P7C4 Novelty helps coverage

**Claim.** Novelty-driven search supports open-ended discovery and avoids deception by objectives.

**Sketch.**

Novelty search literature demonstrates that novelty as an objective enables discovery of diverse solutions and avoids local optima in deceptive fitness landscapes.

---

### P7C5 Information gain guides ambiguity resolution

**Claim.** Expected informativeness is a principled selection objective for querying and validation.

**Sketch.**

Information gain maximizes expected reduction in uncertainty about model parameters or hypotheses, providing a principled framework for active learning and inquiry.

Optional guarantee path:

* If the exploration objective satisfies adaptive submodularity, adaptive greedy stays near-optimal.

---

## G30 Noise becomes a computable object

* Every anomaly becomes a NoiseSeed with metrics and provenance.

---

## G31 Noise becomes a queue

* The system keeps a backlog of "interesting threads," explores them when budget exists.

---

## G32 Exploration is hypothesis-safe

* Exploration writes into workspace overlays and hypothesis branches, then commits via P6 2SC.

---

## G33 Exploration is guided

* Use learning progress, novelty, and information gain, avoid chasing irreducible randomness.

---

## G34 LLM reasoning is used as a refinement tool

* LLM proposes structure, missing evidence, and disambiguations, bounded by budgets.

---

## G29 Hippocampus actively seeks evidence

* Diagnostics drive which ambiguity to resolve next, using expected uncertainty reduction.

---

### Algorithm 15: Light Outcome Feedback Loop (bandit)

```pseudo
function POLICY_STEP(context φ):
  a = SELECT_ACTION_UCB_OR_TS(φ)                     // which knob to turn
  EXECUTE_ACTION(a)
  r = OBSERVE_REWARD()                               // task success, user edit, implicit
  UPDATE_POLICY(φ, a, r)
  STORE_FEEDBACK_EVENT(φ, a, r)
```

Bandit foundations and safe online learning to re-rank provide the template for "light feedback, safe updates." ([Stanford University][3])

---

## P7 math

### P7.1 Noise features

For a seed (s), define a feature vector:
[
\phi(s) = [T(s), r(s), \widehat{var}(s), nov(s), rec(s), prov(s), risk(s), cost(s)]
]

Sources for signals:

* (T) tension from field edges
* (r) anchor residual
* (\widehat{var}) uncertainty proxy
* (nov) novelty score
* (rec) recurrence across time and contexts
* (prov) provenance score (P6)
* (risk) governance risk (P4)
* (cost) predicted exploration cost

### P7.2 Interestingness score

[
I(s) = w_T T + w_r r + w_v \widehat{var} + w_n nov + w_{rec} rec + w_p prov - w_k risk - w_c cost
]

Weights can be:

* fixed per domain
* adapted via P4 light feedback (reward shaping)

### P7.3 Learning progress

Use improvement, not raw error. This avoids fixation on irreducible randomness. ([arXiv][p7-1])

For a trace (t) on seed (s):
[
LP(s) = \max(0,; \mathcal{L}*{before}(s) - \mathcal{L}*{after}(s))
]
where (\mathcal{L}) can be a blend of tension and residual:
[
\mathcal{L}(s)=\alpha T(s) + \beta r(s)
]

This aligns with "learning progress" intrinsic motivation in IAC-style systems. ([Swarthmore Computer Science][p7-5])

### P7.4 Novelty

Two options, both usable.

**Distance novelty**
[
nov(s)=\min_{p \in \mathcal{P}} |z(s)-z(p)|
]
where (z(\cdot)) is a structural embedding of the seed subgraph or pattern.

**Prediction novelty**
Use an exploration bonus based on prediction error of a fixed target representation, similar in spirit to RND. ([arXiv][p7-6])

Novelty search literature supports novelty as a primary driver for open-ended discovery. ([Swarthmore Computer Science][p7-2])

### P7.5 Information gain for inquiry selection

For candidate inquiry action (a):
[
IG(a) = H(\Theta \mid D) - \mathbb{E}_{y \sim p(y \mid a,D)}[H(\Theta \mid D \cup (a,y))]
]
This is the classic expected informativeness frame for selecting data. ([MIT Press Direct][p7-3])

### P7.6 Utility for scheduling

[
U(s) = I(s) + \lambda LP(s) + \mu \max_{a \in A(s)} IG(a)
]
subject to budgets:
[
\sum cost(\text{explores}) \le B_{explore}, \quad \sum cost(\text{llm calls}) \le B_{llm}
]

---

---

## Comp5 Candidate Generator

(Component definition from plan.md - to be elaborated)

---

## Comp7 Idea Manager

(Component definition from plan.md - to be elaborated)

---

## Comp32 Inquiry Planner (INQ)

For evidence seeking.

---

### P7I5 Archived seed queryability

Archived seeds remain queryable for audit.

---

### P7I6 Failure memory blocks loops

Failure memory blocks infinite loops on unproductive seeds.

---

### P7I7 Exploration hard budgets

Hard budgets: `explore_budget`, `llm_budget`.

---

### P7I8 Beam limits per seed

Number of hypotheses spawned per seed is limited.

---

### P7I9 Governance gating

Risk tags influence whether exploration runs automatically, or requires user branch choice.

---

### P7I10 High-risk surfaces ambiguity

High-risk seeds can trigger "surface ambiguity" behavior instead of silent repair.

---

### P7I11 Cheap probes first

Cheap probes first, LLM second.

---

### P7I12 Forest and overlay reuse

Packed forests reuse (P5), overlays reuse (P6).

---

### P7I13 Sleep vs online depth

Sleep pass does deeper mining, online pass stays shallow.

---

### P7I14 Seed compactness

Seeds are compact, mostly metrics plus anchors.

---

### P7I15 Trace compression

Traces compress into signatures and aggregate stats.

---

---

### Algorithm 32: Diagnostics-driven inquiry planning

```pseudo
function PLAN_INQUIRIES(epoch e):
  candidates = FIND_HIGH_VALUE_AMBIGUITIES(e)        // high usage, high tension, high variance
  tasks = []
  for c in candidates:
    gain = EST_EXPECTED_UNCERTAINTY_REDUCTION(c)
    cost = EST_COST(c)
    tasks.append((gain/cost, MAKE_TASK(c)))

  return TOPK(tasks, budget=validation_budget)
```

Active learning literature gives the template for selecting data to reduce uncertainty efficiently.

---

---

---

### Algorithm 43

Simulate and validate an idea candidate

```pseudo
function EVALUATE_IDEA(candidate c):
  hws = HWS_OPEN(region=c.region, base_epoch=c.epoch)
  APPLY_REWRITE_IN_WORKSPACE(hws, c.rewrite)
  RUN_LOCAL_FIELD_REPAIR(hws)
  delta = MEASURE_DELTA(hws, baseline)

  if delta.good:
    bundle = COMPILE_EVIDENCE_BUNDLE(c, hws)
    llm = LLM_REFINE(bundle)                   // label + missing evidence
    STORE_IDEA_TOKEN(c, delta, llm)
    return PROMOTE_AS_HYPOTHESIS(c)
  else:
    RECORD_FAILURE(c)
```

---
