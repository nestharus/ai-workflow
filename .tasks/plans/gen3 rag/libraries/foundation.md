# Foundation Library

Evidence permanence, observation records, provenance tracking, non-destructive updates.

### P1I1 Evidence permanence

For every node and edge:

* a provenance record exists that references source spans or earlier events
* provenance never disappears

---

### P1I2 Non-destructive updates

No operation deletes nodes, edges, or prior states.

* merges create aliases
* revisions create new states
* deletions become tombstones with provenance

---

### P1I3 Field state never overwrites history

`x` updates append a new state record. Prior `x` remains retrievable.

---

### P1I4 Ambiguity stays explicit

If conflict persists past a threshold budget, the system either:

* records the conflict in the conflict ledger, or
* branches hypotheses

---

### P4I3 Failure memory is append-only

* Failure events accumulate and are only compacted by "sleep" with provenance kept.

---

### P9I5 — Translation proposals are provenance-bearing

Any manifold→graph proposal must carry:

* evidence bundle
* diagnostics deltas
* risk tags
* stability window

---

### D6 ObservationRecord

Stores what the embedder saw and produced, independent of later structure changes.

```
ObservationRecord {
  obs_id: ObsId
  node_id: NodeId
  embedder_id: string
  embedder_version: string
  input_hash: bytes32
  span_ref: SpanRef
  b: Vector[d]                // float16 or float32 backstore
  created_t: Time
}
```

Reason: later re-embedding with a different model changes results. Keeping the original observation preserves the historical signal.

---

### D10 Hypothesis

Branch container.

```
Hypothesis {
  hyp_id: HypId
  parent: HypId?
  scope_nodes: set<NodeId>      // local fork scope
  created_t: Time
  weight: float                 // prior weight for selection
}
```

## P4 data structures

---

---

### P7C1 Evidence stays

**Claim.** Every seed, idea, and derived structure links back to spans or anchored graph coordinates.

**Sketch.**

By construction:
* Seeds store provenance lists
* IdeaTokens store anchors
* All derived structure references NoiseSeed or IdeaToken which have provenance

---

## G6 Evidence permanence

* Raw spans and all derived claims remain traceable to original spans.

---

## Spec v0.1: Graph-Conditioned Semantic Field Ingestion

## Spec v0.1: Graph-Conditioned Semantic Field Ingestion

### Problem

Raw embeddings give underspecified directions. Global clustering over those directions drifts. Chunking breaks associations. The system needs directions that stay reliable as meaning evolves.

### Core move

Treat embeddings as observations. Treat the graph as structure. Compute a semantic field over the graph. Use that field as the working direction system.

This aligns with:

* Gaussian random fields and harmonic functions on graphs.
* Graph signal processing and graph filtering.
* Message passing as a generic computation pattern on graphs.
* Dynamic graphs and time-varying representations.

---

## Problem

Raw embeddings give underspecified directions. Global clustering over those directions drifts. Chunking breaks associations. The system needs directions that stay reliable as meaning evolves.

---

## Core move

Treat embeddings as observations. Treat the graph as structure. Compute a semantic field over the graph. Use that field as the working direction system.

This aligns with:

* Gaussian random fields and harmonic functions on graphs.
* Graph signal processing and graph filtering.
* Message passing as a generic computation pattern on graphs.
* Dynamic graphs and time-varying representations.

---

## Where the raw material comes from

You already generate the right artifacts:

* P4: Pattern library + instances
* P5: Grammar rules and parse forests
* P6: Hippocampus workspace + 2-stage commit + global consolidation
* P7: Seed queue and exploration traces (good for "where patterns fail" and "where patterns transfer")

P6 "sleep" is the right place to run heavy disentanglement.

---

## Why your architecture makes this robust

Locatello's result basically says: if you only see (x), the factorization is underdetermined.

You have extra constraints:

* token types and slot types
* graph neighborhoods
* hypothesis splits
* provenance strata
* outcome feedback

So you do "weak supervision by structure" instead of hoping for a miracle from raw vectors.

---

## New pipeline

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

## Modality routing and tokenizer selection

Starts from raw unstructured input.

```pseudo
function ROUTE_AND_TOKENIZE(input stream):
  regions = SEGMENT_STREAM(stream)              // rough boundaries
  for region in regions:
    dom = PREDICT_DOMAIN(region)                // English, code, table, image, logs, mixed
    tokset = TOKENIZER_STACK[dom].TOKENIZE(region)
    yield (region, dom, tokset)
```

Domain routing can be light at first and later refined using hypothesis outcomes.

---

## Rule application as graph rewrite with provenance

Uses DPO-like rewrite semantics, keeps non-destructive update invariants.

```pseudo
function APPLY_RULE(h, match m):
  rule = m.rule
  g2 = COPY_VIEW(h.token_graph)

  // rewrite in a new graph view, never overwrites the old view
  g2 = GRAPH_REWRITE_DPO(g2, rule, m)                 // produces new graph

  // emit tokens from rhs
  emitted = EMIT_TOKENS(rule.emit, bindings=m.bindings, hyp=h.hyp_id)
  ATTACH_PROVENANCE(emitted, m.support_spans)

  h2 = NEW_HYP_FROM(h)
  h2.token_graph = g2
  h2.bindings += (rule, m.bindings)
  return h2
```

Graph transformation via DPO gives a formal foundation for safe rewrites and composition. ([University of Leicester Computer Science][4])

---

## Proof 1: Existence and uniqueness of the field solution

**Claim C1.** If (\alpha_i + \mu_i > 0) for every connected component, then (\mathcal{E}(X)) has a unique minimizer.

**Sketch**

* (\mathcal{E}(X)) is a sum of convex quadratics in (X).
* The Hessian in each dimension is (Q = L + A + M).
* (L) is positive semidefinite.
* (A+M) contributes positive diagonal mass on anchored nodes.
* That makes (Q) positive definite on each connected component that has at least one anchored node, so the quadratic is strictly convex, so the minimizer is unique.
* The linear system ((L+A+M)X = AB) has a unique solution.

This is standard for Laplacian-regularized objectives and Gaussian field style constructions.

---

## Proof 2: Energy decreases under relaxation, convergence on fixed graph

**Claim C2.** The update
[
x_i \leftarrow \frac{\alpha_i b_i + \sum_j w_{ij} x_j}{\alpha_i + \mu_i + \sum_j w_{ij}}
]
monotonically decreases (\mathcal{E}) when updating one node at a time with others fixed. Repeating converges to the unique minimizer.

**Sketch**

* (\mathcal{E}) is quadratic and separable per node when holding neighbors fixed.
* The update sets (x_i) to the exact minimizer of (\mathcal{E}) restricted to coordinate block (i).
* Block coordinate descent on a strictly convex quadratic decreases energy each step and converges to the unique minimizer.

---

## Proof 3: Noise attenuation, directions become more reliable

**Claim C3.** Under the model (b = s + \varepsilon), with zero-mean iid noise and a smoothness prior where neighboring nodes share similar (s), the field solution (x) has lower expected error than (b) along high-frequency graph modes.

**Sketch**

* In one dimension, the solution is linear: (x = (L+A+M)^{-1}A b = S b).
* In the Laplacian eigenbasis, this is a low-pass graph filter with transfer function roughly (h(\lambda)=\alpha/(\alpha+\lambda+\mu)).
* High-frequency components have large (\lambda), so (h(\lambda)) shrinks those components.
* If noise injects energy broadly, high-frequency noise gets attenuated more than the low-frequency signal.
* So expected MSE decreases in regimes where the signal is graph-smooth and noise is less graph-smooth.

This is graph filtering language from graph signal processing.

---

## Proof 4: Tier caps bound compute and memory

**Claim C4.** If tier caps ((K,M,N)) are enforced, then:

* Field updates cost (O(d \cdot |E_{local}|)) with (|E_{local}|) bounded by tier neighborhood size.
* Focus and active tier latency is bounded independent of total corpus size.
* Total memory in RAM is (O((K+M+N)\cdot d + |E_{RAM}|)).

**Sketch**

* All RAM operations are restricted to capped tiers.
* Inactive tier lives on disk and is accessed via ANN and edge lookups.

---

## P1 claim set

P1C1. Evidence permanence holds under all operations.
P1C2. Gated quadratic field per hypothesis has a unique minimizer under the same anchoring condition as v0.1.
P1C3. Field relaxation converges per hypothesis.
P1C4. Persistent conflict produces a durable ambiguity artifact (ConflictRecord or Hypothesis branch).
P1C5. Robust loss reduces influence of large disagreements while preserving convergence to a minimizer.

---

## Lean proof skeletons (P1)

Two tracks: quadratic uniqueness and state machine invariants.

---

## Lean: Monotone failure brake

```lean
namespace FailureBrake

open Real

def brake (η F : ℝ) : ℝ := Real.exp (-η * F)

theorem brake_monotone {η : ℝ} (hη : 0 < η) :
  Monotone (fun F => brake η F) := by
  sorry

end FailureBrake
```

---

## 7. Event-sourced replay

* Every mutation is an event.
* Enables rebuilds, A/B comparisons, and regression debugging.

---

### S1 Problem statement

Raw embeddings give underspecified directions. Global clustering over those directions drifts. Chunking breaks associations. The system needs directions that stay reliable as meaning evolves.

---

### S2 Core approach

Treat embeddings as observations. Treat the graph as structure. Compute a semantic field over the graph. Use that field as the working direction system.

This aligns with:

* Gaussian random fields and harmonic functions on graphs.
* Graph signal processing and graph filtering.
* Message passing as a generic computation pattern on graphs.
* Dynamic graphs and time-varying representations.

---

---

### P2C5 No evidence loss

Sketch:

* Consolidation creates a new epoch and new node states.
* It leaves ObservationRecords, prior NodeStates, ConflictRecords, hypotheses, and the event log intact.
* Therefore any prior world state can be reconstructed by choosing an older epoch or replaying events.

Event sourcing is the established pattern for this audit and replay property. ([Microsoft Learn][7])

---

---

## P5C2 Rewrite steps preserve evidence permanence

Each rewrite emits tokens with provenance pointers and leaves raw spans untouched. Rule application is append-only over epoch views and event log. Expansion from tokens back to spans remains possible by construction.

Proof obligation in Lean:

* inductive invariant over events: every token has a path to some ObservationRecord or is marked structural-only and tied to anchor nodes

---

### P6C1 Workspace isolation

**Claim.** LTM mutates only by commit events.
**Sketch.**

* HWS writes into overlay views.
* Commit controller is the only path that emits LTM events.
* Event log is append-only.

---

### P6C2 Snapshot consistency

**Claim.** Readers obtain a stable view \(G^{\(e\)}\) while commits create \(G^{(e+1)}\).
**Sketch.**

* MVCC style: writers create new versions, readers keep old.
* Equivalent discipline is described by snapshot isolation.

---

### P6C3 Safe reclamation

**Claim.** Old epochs are reclaimed after all readers leave, via grace periods.
**Sketch.**

* Track reader epochs.
* Reclaim when min reader epoch advances past reclaim target, same pattern as RCU grace periods.

---

### P6C4 Surprise budget prevents calcification by construction

**Claim.** High-provenance disruptive evidence cannot be suppressed purely by robust downweighting once clamped, it either forces branching or forces re-anchoring in some hypothesis.
**Sketch.**

* Weight clamp ensures it continues contributing to the objective.
* If conflict persists, solver yields high tension.
* Policy forces branch or re-anchor when tension and provenance exceed thresholds.

---

### P6C5 Grammar promotion controls error

**Claim.** Beta posterior gating yields bounded promotion risk under the assumed win/loss observation model.
**Sketch.**

* Same as P4 promotion proof pattern.

---

### P6C6 Adapter rollout is safe under canary plus rollback

**Claim.** Rollout can be limited to fraction (f) and reverted on regression.
**Sketch.**

* Canarying is a standard safety pattern for deployments.

---

---

### P7C1 Evidence stays

**Claim.** Every seed, idea, and derived structure links back to spans or anchored graph coordinates.

**Sketch.**

By construction:
* Seeds store provenance lists
* IdeaTokens store anchors
* All derived structure references NoiseSeed or IdeaToken which have provenance

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
