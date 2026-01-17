# Deployment Library

A/B testing, canary deployments, rollback, zero-downtime, shadow evaluation.

---

## Performance targets

* Ingestion: amortized sublinear in corpus size per span.
* Field updates: local, bounded by tier neighborhoods.
* Retrieval: bounded latency with tiered ANN plus graph expansion budget.

---

### P9I6 — A/B never breaks correctness

All A/B routing is read-view based. The write path is unified (event log). Candidate arms are either:

* read-only (shadow), or
* effect-isolated (canary with side effects gated through the same commit pipeline).

---

### D53 TranslationProposal

```text
TranslationProposal {
  prop_id: PropId
  kind: enum {bridge_edge, rule_candidate, pattern_candidate, adapter_candidate}
  base_view: ManifoldView
  payload: bytes
  evidence: EvidenceBundleRef
  deltas: {ΔT, Δr, Δrisk, Δlatency}
  expected_gain: float
  risk_tags: set<RiskTag>
  status: enum {shadow, canary, promoted, rejected}
}
```

---

### D54 ABExperiment

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

---

### D61 GrammarRuleCandidate

```text
GrammarRuleCandidate {
  rule_id: RuleId
  source_pattern: PatId?
  domain: DomainId
  version: int
  status: enum {shadow, canary, promoted, rolled_back}
  stats: {precision, conflict_rate, drift_rate}
  posterior: BetaParams
}
```

---

### D62 AdapterCandidate

```text
AdapterCandidate {
  map_id: MapId
  src: CSId
  dst: CSId
  version: int
  status: enum {shadow, canary, promoted, rolled_back}
  fit_error: float
  drift_score: float
  updated_t: Time
}
```

---

## Algorithm 22

### Traversal across coordinate systems

Travel uses canonical field coordinates, while still allowing domain-native similarity when needed.

```pseudo
function TRAVERSE(query q, start_nodes S):
  q_bundle = EMBED_QUERY_BUNDLE(q)                     // per domain, per view
  q_canon = CANONICALIZE(q_bundle)

  frontier = PRIORITY_QUEUE()
  for s in S:
    frontier.push(s, score = SIM_CANON(q_canon, X(s)))

  while budget remains:
    v = frontier.pop()
    yield v

    for edge in OUT_EDGES(v):
      u = edge.dst

      // canonical travel
      score = SIM_CANON(q_canon, X(u)) - EDGE_COST(edge)

      // optional domain boost when token types match
      if SHARE_COORD_SYSTEM(u, q_bundle):
        score += λ * SIM_DOMAIN(q_bundle, u)

      frontier.push(u, score)
```

"Topology changes into different coordinate systems" becomes "travel happens in canonical space, with local boosts in native spaces."

---

## Algorithm 51 — CONTINUOUS_SLEEP_NO_DOWNTIME

Sleep runs as continuous background consolidation with snapshot isolation and delta catch-up.

```pseudo
function CONTINUOUS_SLEEP_NO_DOWNTIME(trigger):
  lsn0 = EVENT_LOG.TAIL_LSN()
  snap = CREATE_SNAPSHOT(lsn0)

  // Build candidate epoch from snapshot
  epoch_new = BUILD_EPOCH(snap)
  BUILD_INDICES(epoch_new)
  BUILD_CHARTS(epoch_new)
  BUILD_CONN_OPERATOR(epoch_new)

  // Catch up while ingestion continues
  lsn1 = EVENT_LOG.TAIL_LSN()
  APPLY_DELTAS(epoch_new, from=lsn0, to=lsn1)

  REGISTER_CANDIDATE(epoch_new, ready_lsn=lsn1)
  START_AB_EXPERIMENT(control=ACTIVE_EPOCH, candidate=epoch_new, start_lsn=lsn1)
```

---

## Algorithm 52 — AB_ROLLOUT (shadow + canary + A/B)

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

---

### P6C6 Adapter rollout is safe under canary plus rollback

**Claim.** Rollout can be limited to fraction (f) and reverted on regression.
**Sketch.**

* Canarying is a standard safety pattern for deployments.

---

## G41 A/B continuous deployment

* Shadow → canary → ramp → graduate/rollback is supported for epochs, adapters, grammar, and blend recipes.

---

## Performance and memory

* **Abstraction reduces working-set size**: macro-nodes stand in for repeated subgraphs, while evidence remains in inactive storage.
* **Expansion is demand-driven**: expand only to token budget and risk profile.
* **Pattern mining is sleep-time**: runs during global consolidation, amortized.
* **Online matching is bounded**: local structural match only around focus/active tiers.

---

## Safety and stability

* **Failure memory is prioritized** in replay and learning (similar spirit to prioritized replay). ([arXiv][7])
* **Safe online learning**: keep "policy deltas" small, prefer conservative exploration (safe re-ranking literature is a good template). ([Proceedings of Machine Learning Research][8])
* **Governance is separate**: it sits above retrieval/field state and never destroys evidence.

---

## Compute strategy

* Local relaxation bounded by tier caps
* Conflict resolution budgeted as a background loop with strict quotas
* Validator calls rate-limited and triggered by tension

---

## Hot path

Ingestion hot path stays:

* embed once
* add edges
* local relax
* push conflict candidates
  Heavy work runs on the conflict queue.

---

## Performance control

Graph parsing and graph rewriting can get expensive fast, so P5 adds hard controls.

1. **Grammar class restrictions per tier**

* Focus and Active: restricted grammars with cheap matching and bounded-degree neighborhoods.
* Context and Sleep: heavier grammars and deeper matching.

Graph grammar parsing complexity varies widely across grammar classes and restrictions. ([sciencedirect.com][11])

2. **Match candidate acceleration**

* Index rule LHS patterns by WL-style neighborhood signatures.
* Use WL hashing to prune match candidates before subgraph matching. ([Journal of Machine Learning Research][8])

3. **Hypothesis beam and packed storage**

* Strict beam width per region.
* Packed DAG sharing across hypotheses, similar in spirit to graph-structured stacks for ambiguity. ([IJCAI][2])

4. **Coordinate transforms cached**

* Cache canonical projections (A_v b_i^{(v)}).
* Refit adapters in sleep-time, then bulk-refresh projections during consolidation.

5. **Domain embedders remain specialized**

* Text embedder stays as the semantic anchor.
* Graph embedder covers topology.
* Code embedder covers AST and code structure. ([ACM Digital Library][9])

---

## Performance

* Hard budgets: `explore_budget`, `llm_budget`
* Beam limits: number of hypotheses spawned per seed
* Cheap probes first, LLM second
* Packed forests reuse (P5), overlays reuse (P6)
* Sleep pass does deeper mining, online pass stays shallow

---

## Safety

* Governance gating: risk tags influence whether exploration runs automatically, or requires user branch choice
* High-risk seeds can trigger "surface ambiguity" behavior instead of silent repair
* Failure memory blocks infinite loops on unproductive seeds

---

### P9I1 — Read coherence

Every request pins a view:

* `epoch_id`
* `lsn_end` (event-log offset)
* `hyp_id`

All reads for the request use that pinned view.

---

### P9I2 — Overlay is always writable

Ingestion and workspace commits append to the event log continuously. The overlay applier may lag, but never blocks writes.

---

### P9I3 — Blends are reversible

No blend may become the only representation of its primitives. `BlendRecipe` must be explicit and all primitives remain computable.

---

### P9I4 — No force becomes law silently

Fields may guide traversal and scheduling.

Fields may only alter topology (edge gates, bridges, anchor policies) via two-stage commit + governance.

---

### P9I5 — Translation proposals are provenance-bearing

Any manifold→graph proposal must carry:

* evidence bundle
* diagnostics deltas
* risk tags
* stability window

---

## P10 non-goals

* No global policy for when to spawn children or how to allocate budgets.
* No automatic resolution of semantic conflict; ambiguity is preserved and surfaced.
* No requirement that the LLM use specific schema objects (idea nodes/facets). Those are allowed but not mandatory.

---

---

## P4 non-functionals

### Performance and memory

* **Abstraction reduces working-set size**: macro-nodes stand in for repeated subgraphs, while evidence remains in inactive storage.
* **Expansion is demand-driven**: expand only to token budget and risk profile.
* **Pattern mining is sleep-time**: runs during global consolidation, amortized.
* **Online matching is bounded**: local structural match only around focus/active tiers.

### Safety and stability

* **Failure memory is prioritized** in replay and learning (similar spirit to prioritized replay). ([arXiv][7])
* **Safe online learning**: keep "policy deltas" small, prefer conservative exploration (safe re-ranking literature is a good template). ([Proceedings of Machine Learning Research][8])
* **Governance is separate**: it sits above retrieval/field state and never destroys evidence.

---

## Optimization and memory strategies

### 1. Tier-locality as the main speed lever

* Keep Focus, Active, Context in RAM.
* Keep Inactive on disk, accessed via ANN and edge tables.

This is the same design principle as virtual memory and tiered recall systems.

### 2. Separate indices by tier and by embedding kind

* HNSW for fast recall in Context.
* PQ or IVF+PQ for Inactive scale.

### 3. Quantize aggressively outside Focus

* Store inactive embeddings as int8 PQ codes.
* Keep only centroids and a small residual cache in RAM.

### 4. Batch edge writes, defer compaction

* Use LSM-style batching for high ingest rates.
* Periodic compaction merges edge runs.

### 5. Local field updates, global re-solves rarely

* Per span: relax only within a hop radius determined by tier.
* Global solve: scheduled offline or during low load, used to reduce drift.

### 6. Uncertainty-driven compute

* High uncertainty nodes get more validation and more relaxation steps.
* Low uncertainty nodes get cheap maintenance.

### 7. Event-sourced replay

* Every mutation is an event.
* Enables rebuilds, A/B comparisons, and regression debugging.

---

## P1 non-functionals

This patch adds storage, so performance needs explicit handling.

### Storage strategy

* Raw spans: immutable compressed store, dedup by content hash
* ObservationRecord: float16 or float32 backstore on disk
* ANN store: PQ codes for scale and speed, full vector backstore for audits ([ACM Digital Library][5])
* Graph edges: LSM-backed edge table for high write rates ([UMass Boston CS][6])
* NodeState history:

  * RAM keeps current states for Focus, Active, Context
  * disk keeps full history, optionally delta-compressed

### Compute strategy

* Local relaxation bounded by tier caps
* Conflict resolution budgeted as a background loop with strict quotas
* Validator calls rate-limited and triggered by tension

### Hot path

Ingestion hot path stays:

* embed once
* add edges
* local relax
* push conflict candidates
  Heavy work runs on the conflict queue.

---

## P5 non-functionals

---

## P7 non-functionals

### Performance

* Hard budgets: `explore_budget`, `llm_budget`
* Beam limits: number of hypotheses spawned per seed
* Cheap probes first, LLM second
* Packed forests reuse (P5), overlays reuse (P6)
* Sleep pass does deeper mining, online pass stays shallow

### Memory

* Seeds are compact, mostly metrics plus anchors
* Traces compress into signatures and aggregate stats
* Archived seeds remain queryable for audit

### Safety

* Governance gating: risk tags influence whether exploration runs automatically, or requires user branch choice
* High-risk seeds can trigger "surface ambiguity" behavior instead of silent repair
* Failure memory blocks infinite loops on unproductive seeds

---


### NFG1 Ingestion performance

Amortized sublinear in corpus size per span.

---

### NFG3 Retrieval latency

Bounded latency with tiered ANN plus graph expansion budget.

---
