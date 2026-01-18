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

---

## Algorithm 4: Tier promotion and demotion

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

---
