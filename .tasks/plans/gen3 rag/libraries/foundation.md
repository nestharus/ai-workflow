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

## D11 Epoch

A versioned read view of the system.

```
Epoch {
  epoch_id: EpochId
  parent_epoch: EpochId?
  snapshot_lsn: LogOffset
  created_t: Time
  status: building | ready | active | retired

  node_state_store: StoreRef      // NodeState keyed by (node_id, hyp_id)
  edge_belief_store: StoreRef     // EdgeBelief keyed by edge_id
  ann_indices: list<IndexVersion>
  summaries: StoreRef             // optional multi-level summaries
}
```

## D12 Snapshot

A consistent cut for offline compute.

```
Snapshot {
  snapshot_id: SnapshotId
  base_epoch: EpochId
  lsn: LogOffset
  graph_view: GraphViewRef        // MVCC view or reconstructed state at lsn
  hypotheses: list<HypId>
}
```

Snapshot semantics align with snapshot isolation style "time travel" reads in MVCC. ([Microsoft][13])

## D13 EdgeBelief additions

Robust weighting is explicit and per hypothesis.

```
EdgeBelief {
  ...
  g: float                        // gate in [0,1]
  rw: map<HypId, float>           // robust weight in [0,1]
  rw_eps: float                   // epsilon used in rw update
  delta: float                    // robust scale parameter
}
```

## D14 IndexVersion

Versioned index artifacts with atomic promotion.

```
IndexVersion {
  index_id: IndexId
  epoch_id: EpochId
  tier: Tier
  kind: Kind                      // b | x
  hyp_id: HypId?
  status: building | ready
  location: URI
}
```

## D15 ConsolidationJob

```
ConsolidationJob {
  job_id: JobId
  snapshot_id: SnapshotId
  target_epoch_id: EpochId
  hypotheses: list<HypId>
  solver: SolverConfig
  started_t: Time
  finished_t: Time?
}
```

## P4 data structures


---

### P1C1 proof sketch

By construction:

* all raw spans remain in the raw store referenced by `SpanRef`
* each node creation writes an `ObservationRecord`
* each derived update appends to event log
* node states append to `NodeState` history
* merges and splits create alias edges and lineage pointers

Therefore any current state and any prior state is reconstructible from the append-only log plus raw store.


---

### P2C5 No evidence loss

Sketch:

* Consolidation creates a new epoch and new node states.
* It leaves ObservationRecords, prior NodeStates, ConflictRecords, hypotheses, and the event log intact.
* Therefore any prior world state can be reconstructed by choosing an older epoch or replaying events.

Event sourcing is the established pattern for this audit and replay property. ([Microsoft Learn][7])


## P5 proofs and proof obligations


---

## P5C2 Rewrite steps preserve evidence permanence

Each rewrite emits tokens with provenance pointers and leaves raw spans untouched. Rule application is append-only over epoch views and event log. Expansion from tokens back to spans remains possible by construction.

Proof obligation in Lean:

* inductive invariant over events: every token has a path to some ObservationRecord or is marked structural-only and tied to anchor nodes


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

### Lean8 Gated quadratic uniqueness

This extends the earlier SPD quadratic lemma. It uses `Matrix.PosDef` from mathlib. ([Lean Community][4])

```lean
import Mathlib.LinearAlgebra.Matrix.PosDef
import Mathlib.Analysis.Convex.Quadratic

namespace GraphFieldGated

variable {ι : Type} [Fintype ι] [DecidableEq ι]
variable (Q : Matrix ι ι ℝ) (c : ι → ℝ)

def energy (x : ι → ℝ) : ℝ :=
  (Matrix.dotProduct x (Q.mulVec x)) - 2 * (Matrix.dotProduct c x)

theorem unique_minimizer_of_posDef (hQ : Matrix.PosDef Q) :
    ∃! x* : ι → ℝ, ∀ x, energy Q c x* ≤ energy Q c x := by
  -- use strict convexity of quadratic form from PosDef
  sorry

end GraphFieldGated
```

### Lean9 Evidence permanence invariants

Model the system as an event-sourced state machine and prove invariants by induction over event lists.

```lean
namespace IngestionInvariants

inductive Event
| addNode : Nat → Event
| addObs  : Nat → Event
| addEdge : Nat → Event
| addState : Nat → Event
| updateGate : Nat → Event
| branchHyp : Nat → Event

structure Store where
  hasSpan : Nat → Prop
  hasObs  : Nat → Prop
  hasState : Nat → Prop

def step : Store → Event → Store := by
  intro s e
  -- define how store evolves for each event
  exact s

def invariantEvidence (s : Store) : Prop :=
  ∀ n, s.hasObs n → s.hasSpan n

theorem invariant_preserved :
  ∀ (s0 : Store) (es : List Event),
    invariantEvidence s0 →
    invariantEvidence (es.foldl step s0) := by
  intro s0 es h
  -- list induction on es
  sorry

end IngestionInvariants
```

This proves the shape of "no evidence gets lost" formally once the `step` function encodes append-only behavior.

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

### P1I5 Compression keeps a lossless backstore

ANN codes and quantized vectors are allowed.
A lossless or near-lossless backstore remains available for re-evaluation and auditing.


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

# P8: Disentanglement and Pattern Transfer

## P8.1 Define disentanglement for this architecture

### Structural disentanglement

Take complex patterns and decompose them into smaller reusable modules with typed interfaces.

* Pattern = a graph template or a grammar rewrite rule (P4/P5)
* Module = a subpattern used across many patterns, with a stable boundary
* Boundary = the slots and edge-types that connect module to the rest

Goal: represent a pattern as "modules + wiring" rather than a monolith.

### Direction disentanglement

Represent canonical vectors as sparse combinations of basis directions.

* Token canonical vector (x \in \mathbb{R}^{d_C})
* Factor dictionary (D \in \mathbb{R}^{d_C \times K})
* Sparse coefficients (a \in \mathbb{R}^K)

Goal: replace "one entangled vector" with "few active factors."

This is the same family of ideas as sparse coding and dictionary learning. A major warning: fully unsupervised disentanglement has identifiability limits. It needs inductive bias and constraints. Your system already has strong biases: typed edges, slot schemas, hypotheses, provenance, and outcome feedback. That is exactly how you escape the "disentanglement is impossible" regime.

## P8.2 How disentanglement fits into your current stack

### Where the raw material comes from

You already generate the right artifacts:

* P4: Pattern library + instances
* P5: Grammar rules and parse forests
* P6: Hippocampus workspace + 2-stage commit + global consolidation
* P7: Seed queue and exploration traces (good for "where patterns fail" and "where patterns transfer")

P6 "sleep" is the right place to run heavy disentanglement.

## P8.3 Direction disentanglement in your system

### Option A: Sparse autoencoder or dictionary learning on canonical embeddings

Train a sparse autoencoder on canonical token vectors (or on layer activations from the neocortex if available).

Objective (one clean form):
\[
\min_{D, a_i}\sum_i |x_i - D a_i|_2^2 + \lambda|a_i|_1
\quad \text{s.t. } |D_{\cdot k}|_2 = 1
\]

* (x_i): canonical vectors from your hippocampus token store
* (D): factor directions
* (a_i): sparse factor activations per token

This aligns with sparse coding and modern dictionary learning interpretations of transformer internals.

Why this is a good fit here:

* Your whole architecture wants "directions" as a computational primitive.
* Sparse factors give you a compact "what is active here" signature.

### Option B: ICA style independence

ICA explicitly searches for statistically independent components. This can be useful for a "factor sanity check," especially when you have lots of mixed signals.

### Option C: NMF for parts-based factors

If you want factors to behave like "parts" that add up (good for certain counts and structured features), NMF is a known tool.

---

### S3 Why your architecture makes this robust

Locatello's result basically says: if you only see (x), the factorization is underdetermined.

You have extra constraints:

* token types and slot types
* graph neighborhoods
* hypothesis splits
* provenance strata
* outcome feedback

So you do "weak supervision by structure" instead of hoping for a miracle from raw vectors.

## P8.4 Structural disentanglement in your system

You already mine patterns. P4 patterns still tend to be "fat."

You now add module extraction:

### Module extraction idea

Given a corpus of pattern graphs, find subgraphs that:

* recur across patterns
* have stable boundaries (interfaces)
* reduce description length when added as reusable primitives

This is structurally the same principle as your MDL compression work in P4, just one level deeper. It turns patterns into an algebra of parts.

Result:

* Pattern = DAG of modules + wiring constraints
* Module = token type in the grammar

This gives "components" that can be moved between contexts.

## P8.5 How to compute "functionality/purpose" of a pattern

You want to detect that two uses share functionality even if surface structure differs.

In your system, "function" is measurable via effects:

A pattern instance has an effect signature:

* energy reduction: (\Delta E) in its local neighborhood after relaxation
* conflict resolution: change in tension / contradiction rate
* retrieval utility: downstream task success deltas (P4 feedback)
* cost: compute and memory footprint

So define for a pattern (p):

* usage contexts: distribution over neighbor token types and domains
* factor profile: distribution of sparse coefficients (a) across instances
* effect metrics: (\mathbb{E}[\Delta E], \mathbb{E}[\Delta T], \text{win rate})

That makes "purpose" computable.

Now "pattern transfer" becomes:

* find a new context whose factor-needs match a pattern's factor profile
* verify via effect metrics and local solve

## P8.6 Tradeoffs and why one pattern wins over another

Once you have effect metrics, tradeoffs become explicit.

Example metrics:

* stability contribution (reduces tension)
* generality (works across many contexts)
* brittleness (failure rate, sensitivity to small changes)
* interpretability (trace quality to spans and anchors)
* cost

Compute a Pareto frontier over these metrics per domain.

Then you can answer:

* "Pattern A beats pattern B here because A is cheaper and equally stable"
* "Pattern B beats A when the domain is noisy because B is robust"

This is the missing bridge from "patterns exist" to "patterns have reasons."

## P8.7 Rebuilding content using disentangled patterns

Rebuild here means: re-represent a region using a different set of modules and factors, then re-evaluate.

Two modes:

### Mode 1: Compression rebuild

* replace subgraphs with module tokens
* preserve residual edges
* keep provenance pointers

This is your existing compression principle, upgraded from "pattern tokens" to "module tokens."

### Mode 2: Transform rebuild

* propose substitutions: module A → module B in a compatible interface slot
* propose hybrids: glue module A's interface to module B's interior using a connector module
* run local solve
* evaluate effect metrics
* store as a new hypothesis first
* commit via P6 2-stage commit

That is "try the idea without polluting memory."

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

## P8.10 Where the LLM sits

The LLM is useful for:

* naming modules and ideas
* interpreting tradeoffs in human terms
* proposing missing evidence
* proposing connector modules when interfaces almost match

The LLM does not need to be the primary disentanglement engine. The math and graph constraints do that work.

---

## S4 Disentanglement feasibility

Disentanglement in your architecture becomes feasible because you have:

* explicit structure (graphs, typed interfaces, grammars)
* repeated usage contexts (where patterns appear)
* objective signals (energy/tension/residual deltas)
* outcome feedback
* hypothesis isolation and two-stage commit

That combination supplies the inductive biases that the disentanglement literature says you need.

