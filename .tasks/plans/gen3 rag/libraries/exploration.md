### Algorithm 32: Diagnostics-driven inquiry planning ([=Algorithm 32])

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

### Algorithm 33: Noise scan ([=Algorithm 33])

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

**P4C2 (@[+P4C2]) proof sketch: MDL-driven abstraction reduces description length**

**Claim.** Given a candidate pattern set, choosing patterns by MDL yields shorter descriptions than raw graph encoding (for those patterns). (Algorithm is heuristic; objective is principled.)

**Sketch.** The objective directly minimizes description length. Greedy selection may not find global optimum but provides local improvement guarantees standard in submodular-style optimization.

**P4C3 (@[+P4C3]) proof sketch: Promotion guarantee**

**Claim.** If a pattern is promoted only when (\Pr(\theta_p \ge \tau) \ge 1-\delta), then promotion implies a posterior reliability guarantee.

**Sketch.** Direct from the posterior CDF of the Beta distribution.

**P4C5 (@[+P4C5]) proof sketch: Risk governance calibration**

**Claim.** Conformal prediction can convert heuristic uncertainty into prediction sets with distribution-free coverage, and selective conformal risk control combines deferral with risk control.

**Sketch.** Conformal coverage guarantee is standard; selection layer trades coverage vs abstention.

### Algorithm 34: Thread queue update ([=Algorithm 34])

```pseudo
function UPDATE_THREAD_QUEUE(new_seeds):
  for s in new_seeds:
    s.metrics.novelty = NOVELTY(s)
    s.metrics.recurry = RECURRENCE(s)
    s.prov_score = PROVENANCE(s)
    score = ISCORE(s)

    if score > TH_QUEUE:
      TQ.push(s, priority=score)
    else:
      s.status = parked
```

### Algorithm 35: Explore a seed ([=Algorithm 35])

Two-stage: cheap structure first, then LLM refinement when value exists.

```pseudo
function EXPLORE_SEED(seed s):
  if CBUD.llm_remaining(domain(s)) <= 0 and CBUD.explore_remaining(domain(s)) <= 0:
    s.status = parked
    return

  bundle = EBC_COMPILE(s, budget_tokens=K)

  // Stage A: structural probes
  probes = RUN_STRUCTURAL_PROBES(bundle)
  if probes.outcome == "resolved":
    trace = WRITE_TRACE(s, probes)
    return

  // Stage B: LLM refine
  if SHOULD_CALL_LLM(s, bundle):
    proposal = LLMR_PROPOSE(bundle)            // actions + rationale + confidence
    APPLY_PROPOSAL_AS_HYPOTHESES(proposal)     // workspace overlay only
    CBUD.spend_llm(domain(s), cost_llm(proposal))

  // Stage C: validate and measure learning progress
  RUN_LOCAL_FIELD_REPAIR(bundle.scope)
  after = MEASURE_METRICS(s)

  trace = WRITE_TRACE(s, before_metrics, after, proposals)
  UPDATE_LEARNING_PROGRESS(s, trace)
  UPDATE_FAILURE_MEMORY(s, trace)
```

LLM-driven curiosity and intrinsic reward signals for LLM training and auditing exist in recent work, so "LLM used as refiner" fits the current research direction.

### Algorithm 36: Distill traces into tokens ([=Algorithm 36])

```pseudo
function DISTILL(epoch e):
  traces = FETCH_RECENT_TRACES(e)
  clusters = CLUSTER_TRACES_BY_SIGNATURE(traces)

  for c in clusters:
    if RECURRENCE_HIGH(c) and LP_HIGH(c):
      idea = MAKE_IDEA_TOKEN(c)
      PROMOTE_IDEA(idea)                      // IdeaToken, PatternCandidate, BridgeCandidate, RuleCandidate
    else if FAILURE_HIGH(c):
      QUARANTINE_SIGNATURE(c.signature)
```

Learning progress guided exploration and goal selection is a standard curiosity mechanism in intrinsic motivation systems.

### Algorithm 37: Curiosity scheduler ([=Algorithm 37])

Online plus sleep-time pass.

```pseudo
function CURIOSITY_SCHEDULER():
  while CBUD.explore_remaining > 0:
    s = TQ.pop()
    if s == none: break
    EXPLORE_SEED(s)

function SLEEP_CURIOSITY_PASS(snapshot snap):
  // deeper budgets, heavier probes
  for s in TOPN_SEEDS(snap, Nsleep):
    EXPLORE_SEED(s)
  DISTILL(snap.epoch)
```

### Algorithm 38: Decay and cleanup ([=Algorithm 38])

```pseudo
function SEED_DECAY(seed s):
  if STALE(s) and RECURRENCE_LOW(s):
    s.status = archived
  if FAILURE_HIGH(s) and LP_LOW(s):
    s.status = quarantined
```

### Algorithm 42: Idea proposal via substitution and hybridization ([=Algorithm 42])

```pseudo
function PROPOSE_IDEAS(context subgraph G, Enc):
  need = AGGREGATE_FACTORS(Enc, nodes_in(G))
  candidates = RETRIEVE_PATTERNS_BY_FACTOR_SIMILARITY(need)

  // filter by interface compatibility
  candidates = FILTER_BY_MODULE_INTERFACE(candidates, G)

  // tradeoff selection
  candidates = PARETO_FILTER(candidates, metrics={stability,cost,robustness})

  hybrids = GENERATE_HYBRIDS(candidates)       // module splice + connector search
  return TOPK(candidates ∪ hybrids)
```

### Algorithm 43: Simulate and validate an idea candidate ([=Algorithm 43])

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

## Comp32 Inquiry Planner (INQ) ([=Comp32])
for evidence seeking

## Comp5 Candidate Generator ([=Comp5])

## Comp7 Idea Manager ([=Comp7])

### D34 NoiseSeed ([=D34])

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

### D35 ExplorationTrace ([=D35])

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

### D36 EvidenceBundle ([=D36])

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

### D37 CuriosityBudget ([=D37])

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

### D38 IdeaToken ([=D38])

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

### D63 InquiryTask ([=D63])

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

\frac{1}{2}r^2 & r \le \delta \
\delta r - \frac{1}{2}\delta^2 & r > \delta
\end{cases}
]
Huber comes from robust estimation work.

This keeps "everything is a hypothesis" intact. The objective is per hypothesis branch.

# P2 patch ([=P2])

## G22 Hippocampus workspace is first-class ([=G22])

* Hippocampus runs a fast, branching workspace graph, separate from long-term memory.


## G23 Two-stage commit ([=G23])

* Neocortex outputs proposals.
* Hippocampus re-ingests, re-parses, re-solves, then commits or quarantines.


## G29 Hippocampus actively seeks evidence ([=G29])

* Diagnostics drive which ambiguity to resolve next, using expected uncertainty reduction.

## G30 Noise becomes a computable object ([=G30])

* Every anomaly becomes a NoiseSeed with metrics and provenance.

## G31 Noise becomes a queue ([=G31])

* The system keeps a backlog of "interesting threads," explores them when budget exists.

## G32 Exploration is hypothesis-safe ([=G32])

* Exploration writes into workspace overlays and hypothesis branches, then commits via P6 (@[+P6]) 2SC.

## G33 Exploration is guided ([=G33])

* Use learning progress, novelty, and information gain, avoid chasing irreducible randomness.

## G34 LLM reasoning is used as a refinement tool ([=G34])

* LLM proposes structure, missing evidence, and disambiguations, bounded by budgets.

### P7.1 Noise features ([=P7.1])

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

### P7.2 Interestingness score ([=P7.2])

[
I(s) = w_T T + w_r r + w_v \widehat{var} + w_n nov + w_{rec} rec + w_p prov - w_k risk - w_c cost
]

Weights can be:

* fixed per domain
* adapted via P4 (@[+P4]) light feedback (reward shaping)

### P7.3 Learning progress ([=P7.3])

Use improvement, not raw error. This avoids fixation on irreducible randomness.

For a trace (t) on seed (s):
[
LP(s) = \max(0,; \mathcal{L}*{before}(s) - \mathcal{L}*{after}(s))
]
where (\mathcal{L}) can be a blend of tension and residual:
[
\mathcal{L}(s)=\alpha T(s) + \beta r(s)
]

This aligns with "learning progress" intrinsic motivation in IAC-style systems.

### P7.4 Novelty ([=P7.4])

Two options, both usable.

**Distance novelty**
[
nov(s)=\min_{p \in \mathcal{P}} |z(s)-z(p)|
]
where (z(\cdot)) is a structural embedding of the seed subgraph or pattern.

**Prediction novelty**
Use an exploration bonus based on prediction error of a fixed target representation, similar in spirit to RND.

Novelty search literature supports novelty as a primary driver for open-ended discovery.

### P7.5 Information gain for inquiry selection ([=P7.5])

For candidate inquiry action (a):
[
IG(a) = H(\Theta \mid D) - \mathbb{E}_{y \sim p(y \mid a,D)}[H(\Theta \mid D \cup (a,y))]
]
This is the classic expected informativeness frame for selecting data.

### P7.6 Utility for scheduling ([=P7.6])

[
U(s) = I(s) + \lambda LP(s) + \mu \max_{a \in A(s)} IG(a)
]
subject to budgets:
[
\sum cost(\text{explores}) \le B_{explore}, \quad \sum cost(\text{llm calls}) \le B_{llm}
]

---

### P7C2 Exploration stays bounded ([=P7C2])

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

### P7C3 Learning progress avoids irreducible noise fixation ([=P7C3])

**Claim.** A reward based on improvement de-prioritizes regions where prediction error stays high with little improvement.

**Sketch.**

* In purely noisy regions, training yields little reduction in loss, so (LP) stays near zero.
* Scheduler selects seeds with higher (LP), so compute flows toward learnable structure.

This is the core argument in compression progress and learning progress intrinsic motivation work.

### P7C4 Novelty helps coverage ([=P7C4])

**Claim.** Novelty-driven search supports open-ended discovery and avoids deception by objectives.

**Sketch.**

Novelty search literature demonstrates that novelty as an objective enables discovery of diverse solutions and avoids local optima in deceptive fitness landscapes.

### P7C5 Information gain guides ambiguity resolution ([=P7C5])

**Claim.** Expected informativeness is a principled selection objective for querying and validation.

**Sketch.**

Information gain maximizes expected reduction in uncertainty about model parameters or hypotheses, providing a principled framework for active learning and inquiry.

Optional guarantee path:

* If the exploration objective satisfies adaptive submodularity, adaptive greedy stays near-optimal.

### P7I1 Seeds are append-only (@[=P7]) ([=P7I1])

* NoiseSeeds and traces live in the event log.

### P7I10 High-risk surfaces ambiguity ([=P7I10])

High-risk seeds can trigger "surface ambiguity" behavior instead of silent repair.

### P7I11 Cheap probes first ([=P7I11])

Cheap probes first, LLM second.

### P7I12 Forest and overlay reuse ([=P7I12])

Packed forests reuse (P5), overlays reuse (P6).

### P7I13 Sleep vs online depth ([=P7I13])

Sleep pass does deeper mining, online pass stays shallow.

### P7I14 Seed compactness ([=P7I14])

Seeds are compact, mostly metrics plus anchors.

### P7I15 Trace compression ([=P7I15])

Traces compress into signatures and aggregate stats.

### P7I2 Seeds never directly rewrite LTM (@[=P7]) ([=P7I2])

* Seeds refine into hypotheses inside workspace overlays.
* Commit goes through P6 (@[+P6]) 2SC.

### P7I3 Noise never disappears (@[=P7]) ([=P7I3])

* Even when downweighted, the seed remains in the ledger, with a status.

### P7I4 Curiosity respects risk governance (@[=P7]) ([=P7I4])

* High-risk ambiguity is surfaced, or deferred, based on user profile (P4).

---


# P9 invariants ([=P9])

### P7I5 Archived seed queryability ([=P7I5])

Archived seeds remain queryable for audit.

### P7I6 Failure memory blocks loops ([=P7I6])

Failure memory blocks infinite loops on unproductive seeds.

---

### P7I7 Exploration hard budgets ([=P7I7])

Hard budgets: `explore_budget`, `llm_budget`.

### P7I8 Beam limits per seed ([=P7I8])

Number of hypotheses spawned per seed is limited.

### P7I9 Governance gating ([=P7I9])

Risk tags influence whether exploration runs automatically, or requires user branch choice.

## P8.8 The new idea engine ([=P8.8])

Noise becomes one input. The main generative driver becomes "pattern transfer + hybridization."

**New objects**

* ModuleLibrary
* FactorDictionary
* PatternDecomposition graph (pattern = modules + wiring)
* TradeoffProfile (metrics + contexts)
* IdeaCandidate (a proposed substitution or hybrid with predicted gain)

**New pipeline**

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
