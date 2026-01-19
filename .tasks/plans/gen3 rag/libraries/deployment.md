
### P9I6 — A/B never breaks correctness (=[P9]) [(=P9I6)]

All A/B routing is read-view based. The write path is unified (event log). Candidate arms are either:

* read-only (shadow), or
* effect-isolated (canary with side effects gated through the same commit pipeline).

---

# P10 invariants

### D54 ABExperiment [(=D54)]

```text
ABExperiment {
  exp_id: ExpId
  control_epoch: EpochId
  candidate_epoch: EpochId
  start_lsn: LogOffset
  traffic_split: float
  metrics: {quality, latency, risk, conflict_rate, drift}
  guardrails: {max_regression, rollback_thresholds}
  status: enum {shadow, canary, ramp, hold, rollback, graduate}
}
```

## Algorithm 52 — AB_ROLLOUT (shadow + canary + A/B) [(=Algorithm 52)]

```pseudo
function AB_ROLLOUT(exp):
  // Shadow: duplicate traffic, do not serve candidate responses
  exp.status = shadow
  RUN_SHADOW(exp, duration=W0)
  if VIOLATES_GUARDRAILS(exp): return ROLLBACK(exp)

  // Canary: small fraction of traffic served by candidate
  exp.status = canary
  exp.traffic_split = ε
  while exp.traffic_split < 1.0:
    ROUTE_TRAFFIC(exp)                  // deterministic split, pinned view
    UPDATE_METRICS(exp)
    if VIOLATES_GUARDRAILS(exp): return ROLLBACK(exp)
    exp.traffic_split *= 2

  exp.status = graduate
  PROMOTE_CANDIDATE(exp.candidate_epoch)
  RETIRE_OLD_EPOCHS_AFTER_GRACE()
```

Side-effect rule:

* shadow is always read-only
* canary/A-B must route writes through the same event-log + 2SC pipeline, to avoid divergent world states

### P6C6 Adapter rollout is safe under canary plus rollback [(=P6C6)]

**Claim.** Rollout can be limited to fraction (f) and reverted on regression.
**Sketch.**

* Canarying is a standard safety pattern for deployments.

---

## G41 A/B continuous deployment [(=G41)]

* Shadow → canary → ramp → graduate/rollback is supported for epochs, adapters, grammar, and blend recipes.

### NFG1 Ingestion performance [(=NFG1)]

Amortized sublinear in corpus size per span.

### NFG3 Retrieval latency [(=NFG3)]

Bounded latency with tiered ANN plus graph expansion budget.
