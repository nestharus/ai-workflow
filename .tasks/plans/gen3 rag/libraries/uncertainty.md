### P4I4 Governance never hides ambiguity silently (=[P4]) [(=P4I4)]

* If the system suppresses an ambiguity from the user view, it still writes it into the ambiguity ledger with risk score and rationale.

---

# P6 invariants

### D9 ConflictRecord [(=D9)]

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

### D20 FeedbackEvent [(=D20)]

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

### D21 UserRiskProfile [(=D21)]

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

### D22 AmbiguityLedgerEntry [(=D22)]

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

### D59 SurpriseBudget [(=D59)]

```text
SurpriseBudget {
  domain: DomainId
  window: TimeWindow
  budget: float
  spent: float
}
```

### P4.3 Failure memory as negative prior / gating brake [(=P4.3)]

Let (F(\cdot)) be a failure score predicted from FailureCase signatures and context features.

Convert to a multiplicative brake on pattern usage:
[
\text{use_score}(p,ctx) = \text{base_score}(p,ctx)\cdot \exp(-\eta F(p,ctx))
]

Optionally, apply it to edge gates (g) inside instances derived from that pattern:
[
g_{ij}^{(h)} \leftarrow g_{ij}^{(h)} \cdot \exp(-\eta F(p,ctx))
]

### P4.4 Light outcome feedback as contextual bandit over system actions [(=P4.4)]

Define an action set (\mathcal{A}) over system knobs, e.g.:

* choose which patterns to expand to LLM
* choose which conflicts to validate next
* choose promote vs branch vs retract
* choose bridge candidates to validate

Observe reward (r_t) from task outcome (light feedback). Use contextual bandit updates (UCB/Thompson) to adapt policy with sublinear regret under standard assumptions.

### P4.5 Risk governance via selective prediction / conformal risk control [(=P4.5)]

Use uncertainty (residual/tension/variance) as a heuristic score, then conformalize deferral thresholds for calibrated risk control.

### Algorithm 15: Light Outcome Feedback Loop (bandit) [(=Algorithm 15)]

```pseudo
function POLICY_STEP(context φ):
  a = SELECT_ACTION_UCB_OR_TS(φ)                     // which knob to turn
  EXECUTE_ACTION(a)
  r = OBSERVE_REWARD()                               // task success, user edit, implicit
  UPDATE_POLICY(φ, a, r)
  STORE_FEEDBACK_EVENT(φ, a, r)
```

Bandit foundations and safe online learning to re-rank provide the template for "light feedback, safe updates."

### Algorithm 16: Risk & Ambiguity Governance [(=Algorithm 16)]

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

Conformal / selective frameworks supply calibrated abstention and risk control patterns for deferral decisions.

]
This preserves distances and angles in the mapped space. Manifold alignment via Procrustes uses this idea.

### P6.3 Surprise budget as forced retention of high-provenance tension [(=P6.3)]

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

### Algorithm 28: Surprise budget and provenance override [(=Algorithm 28)]

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

### P4C4 Failure memory decreases repeat error probability [(=P4C4)]

* Under a simple policy update rule, repeated failed patterns are increasingly suppressed.

### P4C5 Risk governance provides calibrated deferral [(=P4C5)]

* Conformal or conformalized selective methods can provide distribution-free risk/coverage control for abstention decisions.

---

# P1 invariants

### P6C4 Surprise budget prevents calcification by construction [(=P6C4)]

**Claim.** High-provenance disruptive evidence cannot be suppressed purely by robust downweighting once clamped, it either forces branching or forces re-anchoring in some hypothesis.
**Sketch.**

* Weight clamp ensures it continues contributing to the objective.
* If conflict persists, solver yields high tension.
* Policy forces branch or re-anchor when tension and provenance exceed thresholds.

## G7 Ambiguity preservation [(=G7)]

   * Conflicts stay explicit and queryable. Averaging does not erase forks.

## G8 Confidence and diagnostics [(=G8)]

   * System produces measurable uncertainty, tension, and the next information it wants.

## G10 Ambiguity preservation under consolidation [(=G10)]

   * Consolidation keeps conflict artifacts and hypothesis forks. It reduces drift and improves consistency. It does not collapse multi-modal meaning into a single "average truth."

## G13 Confidence-weighted promotion [(=G13)]

* Promote abstractions when confidence rises.
* Keep low-confidence abstractions as hypotheses.

## G14 Failure memory [(=G14)]

* Store explicit "bad pattern" memory and use it as a brake.

## G15 Outcome feedback [(=G15)]

* Use light task outcomes to tune promotion, gating, and retrieval policies.

## G16 Risk governance [(=G16)]

* Surface ambiguity proportional to risk and user profile.
* Enable abstention / deferral for high-risk outputs.

## G25 Paradigm shift support [(=G25)]

* High-provenance disruptive evidence gets a forced path to branch or restructure, via surprise budget.

## Comp28 Surprise Budget Manager (SURP) [(=Comp28)]

## Algorithm 4: Tier promotion and demotion [(=Algorithm 4)]

Explicit focus, active, contextual, inactive logic, inspired by virtual memory style thinking.

```pseudo
function PROMOTE_DEMOTE_TIERS():
  for node in (FOCUS ∪ ACTIVE ∪ CONTEXT):
    node.a = DECAY(node.a) + BOOSTS(node)
    if node.tier == CONTEXT and node.a > TH_UP_ACTIVE: PROMOTE(node, ACTIVE)
    if node.tier == ACTIVE  and node.a > TH_UP_FOCUS:  PROMOTE(node, FOCUS)

    if node.tier == FOCUS  and node.a < TH_DN_ACTIVE:  DEMOTE(node, ACTIVE)
    if node.tier == ACTIVE and node.a < TH_DN_CONTEXT: DEMOTE(node, CONTEXT)
    if node.tier == CONTEXT and node.a < TH_DN_INACTIVE: DEMOTE(node, INACTIVE)

  ENFORCE_CAPS()        // keep |FOCUS|<=K, |ACTIVE|<=M, |CONTEXT|<=N
```

Caps are hard safety rails.

### P1C4 Persistent conflict durability [(=P1C4)]

Persistent conflict produces a durable ambiguity artifact (ConflictRecord or Hypothesis branch).
