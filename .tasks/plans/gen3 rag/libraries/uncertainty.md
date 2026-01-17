# Uncertainty Library

Ambiguity ledger, risk tagging, failure memory, confidence scoring, selective prediction.

---

### P4I4 Governance never hides ambiguity silently

* If the system suppresses an ambiguity from the user view, it still writes it into the ambiguity ledger with risk score and rationale.

---

### D9 ConflictRecord

Explicit ambiguity store.

```
ConflictRecord {
  conflict_id: ConflictId
  edge_ids: list<EdgeId>
  node_ids: list<NodeId>
  hyp_id: HypId
  score: float                // based on tensions and residuals
  kind: kind                  // contradiction | underspecified | boundary
  opened_t: Time
  last_checked_t: Time
  status: open | resolved | branched
  resolution: bytes?          // optional link to decision event
}
```

---

### D20 FeedbackEvent

Light outcome signal.

```text
FeedbackEvent {
  fb_id: FbId
  kind: enum {task_success, task_fail, user_edit, click, dwell, correction}
  target: enum {pattern, edge, node, retrieval_plan}
  target_id: bytes
  reward: float                 // normalized
  context_features: bytes
  created_t: Time
}
```

---

### D21 UserRiskProfile

Governance control surface.

```text
UserRiskProfile {
  user_id: UserId
  domain: enum {general, medical, legal, finance, ops, ...}
  risk_tolerance: float         // 0..1
  deferral_preference: enum {ask_me, hedge, decide}
  audit_level: enum {low, medium, high}
}
```

---

### D22 AmbiguityLedgerEntry

```text
AmbiguityLedgerEntry {
  amb_id: AmbId
  node_ids: list<NodeId>
  edge_ids: list<EdgeId>
  hyp_ids: list<HypId>
  metrics: {r, T, var}         // residual/tension/variance
  risk_score: float
  surfaced: bool
  created_t: Time
}
```

---

### D59 SurpriseBudget

```text
SurpriseBudget {
  domain: DomainId
  window: TimeWindow
  budget: float
  spent: float
}
```

---

### P4.3 Failure memory as negative prior / gating brake

Let (F(\cdot)) be a failure score predicted from FailureCase signatures and context features.

Convert to a multiplicative brake on pattern usage:
[
\text{use_score}(p,ctx) = \text{base_score}(p,ctx)\cdot \exp(-\eta F(p,ctx))
]

Optionally, apply it to edge gates (g) inside instances derived from that pattern:
[
g_{ij}^{(h)} \leftarrow g_{ij}^{(h)} \cdot \exp(-\eta F(p,ctx))
]

---

### P4.4 Light outcome feedback as contextual bandit over system actions

Define an action set (\mathcal{A}) over system knobs, e.g.:

* choose which patterns to expand to LLM
* choose which conflicts to validate next
* choose promote vs branch vs retract
* choose bridge candidates to validate

Observe reward (r_t) from task outcome (light feedback). Use contextual bandit updates (UCB/Thompson) to adapt policy with sublinear regret under standard assumptions. ([Stanford University][3])

---

### P4.5 Risk governance via selective prediction / conformal risk control

Use uncertainty (residual/tension/variance) as a heuristic score, then conformalize deferral thresholds for calibrated risk control. ([People @ EECS][2])

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

### Algorithm 16: Risk & Ambiguity Governance

```pseudo
function GOVERN_OUTPUT(answer_candidates, ambiguity_metrics, user_profile R):
  risk = COMPUTE_RISK(ambiguity_metrics, R.domain, R.risk_tolerance)

  WRITE_AMBIGUITY_LEDGER(ambiguity_metrics, risk)

  if risk > TH_DEFERRAL(R):
    return DEFERRAL_OUTPUT(ambiguity_report, request_clarification)
  else if risk > TH_SURFACE(R):
    return ANSWER_WITH_AMBIGUITY_BOUNDS(answer_candidates, ambiguity_report)
  else:
    return BEST_ANSWER(answer_candidates)
```

Conformal / selective frameworks supply calibrated abstention and risk control patterns for deferral decisions. ([People @ EECS][2])

---

### P6.3 Surprise budget as forced retention of high-provenance tension

Define surprise of evidence (e):
[
\text{surp}(e) = \text{prov}(e) \cdot \sigma(T_e)
]
When (\text{surp}(e)) is high, the system spends budget to avoid suppressing it via reweighting.

Implementation hook in IRLS:

* robust weights (w(r)) are lower bounded for high-provenance residuals:
  [
  w'(r,e) = \max(w(r), w_{\min}\cdot \mathbf{1}[\text{prov}(e)\ge p_0])
  ]
  Effect: high-provenance conflict remains active, then forces branch or re-anchor.

---

### Algorithm 4

Resolution loop increases confidence by seeking targeted evidence.

```pseudo
function RESOLVE_CONFLICTS(budget):
  while budget > 0:
    c = POP_HIGHEST_SCORE_CONFLICT()
    if c == none: break

    e = PICK_HIGHEST_TENSION_EDGE(c)
    spans = FETCH_SPANS(e.src, e.dst)
    verdict, conf, evidence = VALIDATE_EDGE(e.type, spans)

    UPDATE EdgeBelief(e):
      status = verdict
      conf = conf
      evidence += evidence

    if verdict == supported:
      INCREASE_GATE(e.g)
    if verdict == contradicted:
      DECREASE_GATE(e.g)
      if PERSISTENT(c):
        BRANCH_HYPOTHESIS(c)

    LOCAL = NEIGHBORHOOD({e.src, e.dst}, radius=r_conflict)
    FIELD_UPDATE_WITH_DIAGNOSTICS(LOCAL)

    budget -= COST(verdict)
```

---

### Algorithm 28: Surprise budget and provenance override

```pseudo
function HANDLE_DISRUPTIVE_EVIDENCE(hws, evidence e):
  surp = prov(e) * sigmoid(tension_contrib(e))
  if surp < S0: return

  if SURP.budget_remaining(domain(e)) > surp:
    SURP.spend(surp)
    CLAMP_ROBUST_WEIGHTS_FOR(e)          // keep it active in solve
    FORCE_BRANCH_IF_CONFLICT(hws, e)     // preserve both sides
  else:
    QUEUE_FOR_GLOBAL_REVIEW(e)
```

---

### P4C4 Failure memory decreases repeat error probability

* Under a simple policy update rule, repeated failed patterns are increasingly suppressed.

---

### P4C5 Risk governance calibration

**Claim.** Conformal prediction can convert heuristic uncertainty into prediction sets with distribution-free coverage, and selective conformal risk control combines deferral with risk control. ([People @ EECS][2])

**Sketch.** Conformal coverage guarantee is standard; selection layer trades coverage vs abstention.

---

### Algorithm 36

#### Distill traces into tokens

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

Learning progress guided exploration and goal selection is a standard curiosity mechanism in intrinsic motivation systems. ([Swarthmore Computer Science][p7-5])

---

### Algorithm 37

#### Curiosity scheduler

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

---

### Algorithm 38

#### Decay and cleanup

```pseudo
function SEED_DECAY(seed s):
  if STALE(s) and RECURRENCE_LOW(s):
    s.status = archived
  if FAILURE_HIGH(s) and LP_LOW(s):
    s.status = quarantined
```

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

### P1C4 proof sketch

Conflict scores derive from residual and tension.
If tension remains above threshold after validator updates and local relaxation, the policy triggers branching.
Since branching is append-only and the conflict record persists, ambiguity becomes durable.

---

### P6C4 Surprise budget prevents calcification by construction

**Claim.** High-provenance disruptive evidence cannot be suppressed purely by robust downweighting once clamped, it either forces branching or forces re-anchoring in some hypothesis.
**Sketch.**

* Weight clamp ensures it continues contributing to the objective.
* If conflict persists, solver yields high tension.
* Policy forces branch or re-anchor when tension and provenance exceed thresholds.

---

## G7 Ambiguity preservation

* Conflicts stay explicit and queryable. Averaging does not erase forks.

---

## G8 Confidence and diagnostics

* System produces measurable uncertainty, tension, and the next information it wants.

---

## G10 Ambiguity preservation under consolidation

* Consolidation keeps conflict artifacts and hypothesis forks. It reduces drift and improves consistency. It does not collapse multi-modal meaning into a single "average truth."

---

## G13 Confidence-weighted promotion

* Promote abstractions when confidence rises.
* Keep low-confidence abstractions as hypotheses.

---

## G14 Failure memory

* Store explicit "bad pattern" memory and use it as a brake.

---

## G15 Outcome feedback

* Use light task outcomes to tune promotion, gating, and retrieval policies.

---

## G16 Risk governance

* Surface ambiguity proportional to risk and user profile.
* Enable abstention / deferral for high-risk outputs.

---

## G25 Paradigm shift support

* High-provenance disruptive evidence gets a forced path to branch or restructure, via surprise budget.

---

## 6. Uncertainty-driven compute

* High uncertainty nodes get more validation and more relaxation steps.
* Low uncertainty nodes get cheap maintenance.

---

## Comp28 Surprise Budget Manager (SURP)

---

## Algorithm 6: Conflict scan

Conflict scan detects high tension and residual to identify ambiguity.

```pseudo
function CONFLICT_SCAN_AND_QUEUE(nodes S):
  for i in S:
    if STATE(i,main).T > TH_TENSION or STATE(i,main).r > TH_RESID:
      edges = TOPK_EDGES_BY_TENSION(i)
      CREATE_OR_UPDATE_CONFLICT_RECORD(i, edges)
```

---

## Algorithm 7: Conflict resolution

Resolution loop increases confidence by seeking targeted evidence.

```pseudo
function RESOLVE_CONFLICTS(budget):
  while budget > 0:
    c = POP_HIGHEST_SCORE_CONFLICT()
    if c == none: break

    e = PICK_HIGHEST_TENSION_EDGE(c)
    spans = FETCH_SPANS(e.src, e.dst)
    verdict, conf, evidence = VALIDATE_EDGE(e.type, spans)

    UPDATE EdgeBelief(e):
      status = verdict
      conf = conf
      evidence += evidence

    if verdict == supported:
      INCREASE_GATE(e.g)
    if verdict == contradicted:
      DECREASE_GATE(e.g)
      if PERSISTENT(c):
        BRANCH_HYPOTHESIS(c)

    LOCAL = NEIGHBORHOOD({e.src, e.dst}, radius=r_conflict)
    FIELD_UPDATE_WITH_DIAGNOSTICS(LOCAL)

    budget -= COST(verdict)
```

---

## Algorithm 8: Hypothesis branching

Hypothesis branching preserves ambiguity instead of averaging it.

```pseudo
function BRANCH_HYPOTHESIS(conflict c):
  h0 = c.hyp_id
  h1 = NEW_HYPOTHESIS(parent=h0, scope=c.node_ids)

  for node i in c.node_ids:
    // copy current state into new hypothesis
    s0 = STATE(i,h0)
    s1 = NEW_STATE(node=i, hyp=h1, x=s0.x, u=s0.u, r=s0.r, T=s0.T, parent_state=s0.id)
    SET_CURRENT_STATE(i,h1,s1)

  // split gates for edges in scope
  for edge e touching scope:
    if e.status == contradicted:
      SET_GATE(e,h0, small)
      SET_GATE(e,h1, small)
    else:
      COPY_GATE(e,h0 -> h1)

  MARK_CONFLICT(c, status="branched")
```

Branching stays local to keep memory and compute bounded.

