### S1 Problem statement

Raw embeddings give underspecified directions. Global clustering over those directions drifts. Chunking breaks associations. The system needs directions that stay reliable as meaning evolves.

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

## S4 Disentanglement feasibility

Disentanglement in your architecture becomes feasible because you have:

* explicit structure (graphs, typed interfaces, grammars)
* repeated usage contexts (where patterns appear)
* objective signals (energy/tension/residual deltas)
* outcome feedback
* hypothesis isolation and two-stage commit

That combination supplies the inductive biases that the disentanglement literature says you need.

---

# Goals

## G1 Reliable directions

   * Directions conditioned on structure, rather than raw span text.

## G2 Multi-resolution understanding

   * Coarse-to-fine ingestion without fixed chunking as the main primitive.

## G3 Revision as a first-class operation

   * Meaning shifts propagate through the field and graph.

## G4 Bounded working set

   * Explicit focus, active, contextual, inactive tiers with promotion and demotion.

## G5 High recall with controllable cost

   * Cheap candidate generation, expensive validation only where needed.

## G6 Evidence permanence

   * Raw spans and all derived claims remain traceable to original spans.

## G7 Ambiguity preservation

   * Conflicts stay explicit and queryable. Averaging does not erase forks.

## G8 Confidence and diagnostics

   * System produces measurable uncertainty, tension, and the next information it wants.

## G9 Global consolidation

   * Local patching accumulates. Periodic consolidation realigns the field across the full graph while ingestion keeps running.

## G10 Ambiguity preservation under consolidation

   * Consolidation keeps conflict artifacts and hypothesis forks. It reduces drift and improves consistency. It does not collapse multi-modal meaning into a single "average truth."

## G11 Robustness

   * Large disagreements stop dominating smoothing. Disagreements become diagnostics.

## G12 Structural abstraction

* Compress graph memory into reusable patterns.
* Expand patterns into evidence bundles when feeding the LLM.

## G13 Confidence-weighted promotion

* Promote abstractions when confidence rises.
* Keep low-confidence abstractions as hypotheses.

## G14 Failure memory

* Store explicit "bad pattern" memory and use it as a brake.

## G15 Outcome feedback

* Use light task outcomes to tune promotion, gating, and retrieval policies.

## G16 Risk governance

* Surface ambiguity proportional to risk and user profile.
* Enable abstention / deferral for high-risk outputs.

## G30 Noise becomes a computable object

* Every anomaly becomes a NoiseSeed with metrics and provenance.

## G31 Noise becomes a queue

* The system keeps a backlog of "interesting threads," explores them when budget exists.

## G32 Exploration is hypothesis-safe

* Exploration writes into workspace overlays and hypothesis branches, then commits via P6 2SC.

## G33 Exploration is guided

* Use learning progress, novelty, and information gain, avoid chasing irreducible randomness.

## G34 LLM reasoning is used as a refinement tool

* LLM proposes structure, missing evidence, and disambiguations, bounded by budgets.

## G35 Distillation produces tokens

* Repeated, useful noise becomes IdeaTokens, PatternCandidates, GrammarRules.

## G17 Graphs are the grammar

* A grammar is a set of typed graph rewrite rules.
* Parsing is graph rewriting plus scoring.

## G18 Tokens are graph objects

* Tokens exist inside a grammar as nodes, hyperedges, subgraphs, and pattern instances.
* Tokens can come from text spans, from graph coordinates, or from both.

## G19 Emergent structure

* Structure appears when encountered.
* New grammars and token types can emerge from recurring subgraphs and successful parses.

## G20 Multi-interpretation ingestion

* Ingestion maintains a parse forest of competing hypotheses.
* Re-ingestion happens by replaying evidence through a different grammar set or a different hypothesis mixture.

## G21 Computable directions across coordinate systems

## G22 Hippocampus workspace is first-class

* Hippocampus runs a fast, branching workspace graph, separate from long-term memory.

## G23 Two-stage commit

* Neocortex outputs proposals.
* Hippocampus re-ingests, re-parses, re-solves, then commits or quarantines.

## G24 Low path dependence

* Curriculum ingestion and periodic cold solves reduce first-mover geometry lock-in.

## G25 Paradigm shift support

* High-provenance disruptive evidence gets a forced path to branch or restructure, via surprise budget.

## G26 Graph stays traversable

* Gating, retraction, and poison containment keep redundant paths and preserve reachability.
* Small-world mesh targets guide bridge redundancy.

## G27 Grammar evolution is safe

* Grammar rules emerge, then sandbox, then promote with measurable error bounds.

## G28 Multi-coordinate adapters are governable

* Adapters are versioned, canaried, drift-detected, rolled back.

## G29 Hippocampus actively seeks evidence

* Diagnostics drive which ambiguity to resolve next, using expected uncertainty reduction.

* Every token type has one or more embedding spaces.
* Traversal and matching use explicit coordinate transforms, so math stays consistent as you move across token types and domains.


## G36 Manifold as a first-class substrate

* Explicit `ManifoldState` objects exist per epoch and hypothesis.
* Readers pin a `ManifoldView` (epoch + log cut) and see a coherent geometry.

## G37 Explicit translation operators

* Graph/observations → manifold (lift)
* manifold → vector fields (project)
* manifold → graph proposals (pullback)

## G38 Governed blending

* Ephemeral blending is always allowed.
* Cached blending is allowed but versioned.
* Promotion of blends into topology requires a governed commit.

## G39 Dragon closure

* Every open gap becomes either:
  * an implemented method,
  * an explicit bypass rule, or
  * a deliberate non-goal with an alternative.

## G40 Zero downtime sleep

* Consolidation runs continuously.
* Overlay remains writable.
* No downtime for reads or writes.

## G41 A/B continuous deployment

* Shadow → canary → ramp → graduate/rollback is supported for epochs, adapters, grammar, and blend recipes.

## G42 Workspace is first-class
* A workspace is an addressable object with a stable ID, base snapshot, and event log.

## G43 Structured lifetime (parent closes children)
* Child workspaces cannot outlive their parent.
* Cancellation and closure propagate down the tree.

## G44 Fork-join parallel thought
* A parent workspace can spawn many children.
* Children can run independently and export results for reconciliation.

## G45 Capsules and messages
* Workspaces exchange information as portable subgraph capsules with manifests, lineage, and fingerprints.

## G46 Commit via ingest (no LLM diffs)
* The LLM does not compute deltas.
* The workspace submits graph-form artifacts to ingest; ingest computes canonicalization, conflicts, and candidates.

## G47 Overlap detection across workspaces
* Detect overlap and near-duplication across all open workspaces.
* Enable loop/oscillation detection and dedup.

## G48 Convergence-safe merge primitives
* Provide deterministic, idempotent merge building blocks (CRDT-style joins where applicable).
* Where semantic conflict exists, preserve ambiguity instead of overwriting.

## G49 Bounded view compilation
* Provide a deterministic mechanism to compile a bounded view of a large workspace into a context window.
* The LLM can expand/contract the view by manipulating focus pointers in the workspace.

## G50 Observability and budgets
* Every workspace operation is logged.
* Quotas bound memory growth, fanout, and commit volume.

---

# Claims

## C1 Field embeddings exist and are unique

Under mild anchoring conditions.

## C2 Local relaxation converges

To the field solution on a fixed graph.

## C3 Field embeddings attenuate underspecified noise

Relative to raw embeddings, under a simple noise model.

## C4 Tier promotion logic bounds RAM and compute

Independent of total corpus size.

## C5 Ingestion produces stable idea handles

Via graph-supported clustering, rather than geometry-only clustering.

### P4C1 Lossless structural compression

* Abstractions are reversible (original evidence graph can be reconstructed from pattern instances + residual edges).

### P4C2 MDL-driven abstraction reduces description length

* Given a candidate pattern set, choosing patterns by MDL yields shorter descriptions than raw graph encoding (for those patterns). (Algorithm is heuristic; objective is principled.)

### P4C3 Confidence-weighted promotion has probabilistic meaning

* Promotion threshold can be expressed as a posterior guarantee on pattern reliability.

### P4C4 Failure memory decreases repeat error probability

* Under a simple policy update rule, repeated failed patterns are increasingly suppressed.

### P4C5 Risk governance provides calibrated deferral

* Conformal or conformalized selective methods can provide distribution-free risk/coverage control for abstention decisions.

---

# P1 invariants

### P1I1 Evidence permanence

For every node and edge:

* a provenance record exists that references source spans or earlier events
* provenance never disappears

### P1I2 Non-destructive updates

No operation deletes nodes, edges, or prior states.

* merges create aliases
* revisions create new states
* deletions become tombstones with provenance

### P1I3 Field state never overwrites history

`x` updates append a new state record. Prior `x` remains retrievable.

### P1I4 Ambiguity stays explicit

If conflict persists past a threshold budget, the system either:

* records the conflict in the conflict ledger, or
* branches hypotheses

### P1I5 Compression keeps a lossless backstore

ANN codes and quantized vectors are allowed.
A lossless or near-lossless backstore remains available for re-evaluation and auditing.

### P4I1 Abstractions are derived artifacts

* Abstractions never replace raw evidence nodes.
* Abstractions only reference evidence via explicit instance mappings.

### P4I2 Expansion is always possible

* Any abstraction presented to the LLM expands to a concrete evidence set with span references.

### P4I3 Failure memory is append-only

* Failure events accumulate and are only compacted by "sleep" with provenance kept.

### P4I4 Governance never hides ambiguity silently

* If the system suppresses an ambiguity from the user view, it still writes it into the ambiguity ledger with risk score and rationale.

---

# P6 invariants

### P6I1 Workspace isolation

* HWS changes do not mutate long-term memory (LTM) directly.
* LTM changes only via commit events.

### P6I2 Evidence permanence

* Every committed memory object traces to evidence, or is flagged "structural-only" and linked to anchored objects.

### P6I3 Snapshot reads

* Readers see a stable epoch snapshot.
* Writers create overlays and commit new epochs, similar to MVCC / snapshot isolation.

### P6I4 Safe reclamation

* Old snapshots are reclaimed after a grace period, similar to RCU.

### P6I5 Governance never discards ambiguity

* Ambiguities may be hidden from UI by policy, yet remain in the ambiguity ledger with risk metadata.

---

# P7 invariants

### P7I1 Seeds are append-only

* NoiseSeeds and traces live in the event log.

### P7I2 Seeds never directly rewrite LTM

* Seeds refine into hypotheses inside workspace overlays.
* Commit goes through P6 2SC.

### P7I3 Noise never disappears

* Even when downweighted, the seed remains in the ledger, with a status.

### P7I4 Curiosity respects risk governance

* High-risk ambiguity is surfaced, or deferred, based on user profile (P4).

---


# P9 invariants

### P9I1 — Read coherence

Every request pins a view:

* `epoch_id`
* `lsn_end` (event-log offset)
* `hyp_id`

All reads for the request use that pinned view.

### P9I2 — Overlay is always writable

Ingestion and workspace commits append to the event log continuously. The overlay applier may lag, but never blocks writes.

### P9I3 — Blends are reversible

No blend may become the only representation of its primitives. `BlendRecipe` must be explicit and all primitives remain computable.

### P9I4 — No force becomes law silently

Fields may guide traversal and scheduling.

Fields may only alter topology (edge gates, bridges, anchor policies) via two-stage commit + governance.

### P9I5 — Translation proposals are provenance-bearing

Any manifold→graph proposal must carry:

* evidence bundle
* diagnostics deltas
* risk tags
* stability window

### P9I6 — A/B never breaks correctness

All A/B routing is read-view based. The write path is unified (event log). Candidate arms are either:

* read-only (shadow), or
* effect-isolated (canary with side effects gated through the same commit pipeline).

---

# P10 invariants

### P10I1 Isolation

* Workspace edits never directly mutate LTM.

### P10I2 Snapshot base

* Each workspace pins a base LTM snapshot (epoch_id, lsn_end) for read coherence.

### P10I3 Structured concurrency closure

* If a workspace closes, all descendants close.

### P10I4 Idempotent import/export

* Importing the same capsule twice has no effect beyond the first import.

### P10I5 Loop-free capsule routing

* A workspace rejects any capsule whose hop-trace already contains that workspace.

### P10I6 Convergence of replicated workspace state

* If two replicas of a workspace (or two reconciliation runs) apply the same set of workspace events, they converge to the same WSG state.

### P10I7 Partial persistence

* Only explicitly exported regions may be submitted to ingest.
* Private scratch content may remain uncommitted and is GC-able.

### P10I8 Overlap registry monotonicity

* Fingerprints and lineage records are append-only within a workspace session.

### P10I9 Risk and provenance propagate

* Workspace-created objects are marked either provenance-anchored or structural-only.
* Risk tags propagate with capsules and commit envelopes.

---

# Components

## Comp1 Ingestion Stream

## Comp2 Graph Store

## Comp3 Field Solver

## Comp4 Tiered Memory Manager

## Comp5 Candidate Generator

## Comp6 Edge Validator

## Comp7 Idea Manager

## Comp8 Retrieval Planner

## Comp9 Index Layer

## Comp10 Telemetry and Replay Log

## Comp11 Modality Router

## Comp12 Tokenizer Stack

## Comp13 Graph Grammar Engine

## Comp14 Parse Forest Store

## Comp15 Grammar Library

## Comp16 Grammar Miner and Compiler

## Comp17 Token Type Registry

## Comp18 Coordinate System Registry

## Comp19 Adapter and Alignment Trainer

## Comp20 Traversal Planner

## Comp21 Re-ingestion Orchestrator

---

# Data structures

## D1 Node

```
Node {
  id: NodeId
  level: Level                // token, sentence, paragraph, section, doc, idea
  span_ref: SpanRef            // pointer into raw text store, optional for idea nodes
  b: Vector[d]                 // base embedding (observation)
  x: Vector[d]                 // field embedding (mutable)
  u: float                     // uncertainty score
  tier: Tier                   // Focus | Active | Context | Inactive
  a: float                     // activation score
  created_t: Time
  updated_t: Time
}
```

## D2 Edge

```
Edge {
  src: NodeId
  dst: NodeId
  type: EdgeType              // adjacency, containment, reference, membership, coactivation, contradiction
  w: float                    // weight
  meta: Map                   // optional evidence, provenance, validator score
}
```

## D3 Graph

Use a typed, weighted multigraph.

* Active tiers in RAM: adjacency lists per node, plus per-edge type partitions.
* Inactive tier on disk: LSM-backed edge table keyed by (src, type, dst).

## D4 ANN indices

Separate indices per tier and per embedding kind.

* Focus and Active: brute force scan or small HNSW.
* Context: HNSW for x vectors.
* Inactive: IVF+PQ or HNSW+PQ depending on scale.

## D5 Event log

Append-only ingestion events for replay:

```
Event {
  t: Time
  kind: AddNode | AddEdge | UpdateEdgeWeight | Promote | Demote | Reembed | MergeIdea | SplitIdea
  payload: bytes
}
```

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

### D7 NodeState

Stores field state over time and across hypotheses.

```
NodeState {
  state_id: StateId
  node_id: NodeId
  hyp_id: HypId               // hypothesis branch
  x: Vector[d]
  u: float                    // uncertainty
  r: float                    // anchor residual ||x - b||
  T: float                    // node tension sum_j t_ij
  created_t: Time
  parent_state: StateId?      // lineage for revisions
}
```

Node keeps pointers:

* `node.current_state[hyp_id] -> state_id`
* `node.state_history -> list<StateId>`

### D8 EdgeBelief

Edge weights become beliefs with provenance and status.

```
EdgeBelief {
  edge_id: EdgeId
  src: NodeId
  dst: NodeId
  type: EdgeType
  w_base: float               // structural prior
  g: float                    // gate in [0,1], belief that smoothing applies
  status: Status              // proposed | supported | contradicted | unknown
  conf: float                 // confidence in status
  t: float                    // edge tension = w_eff * ||x_i - x_j||^2
  evidence: list<SpanRef>     // validator spans or rationale anchors
  updated_t: Time
}
```

Effective smoothing weight:

* `w_eff = w_base * g`

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

Snapshot semantics align with snapshot isolation style "time travel" reads in MVCC.

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

### D16 Pattern

A reusable structural template.

```text
Pattern {
  pat_id: PatId
  graph: PatternGraph              // small typed multigraph with slots
  slot_schema: list<SlotSpec>      // slot types: Entity, Concept, Number, Time, etc.
  canonical_text: string?          // optional "frame" text for LLM expansion
  created_t: Time
  version: int
}
```

### D17 PatternInstance

Binds a pattern to a concrete part of the evidence graph.

```text
PatternInstance {
  inst_id: InstId
  pat_id: PatId
  hyp_id: HypId
  node_map: Map<PatternNode, NodeId>    // lossless mapping
  edge_map: Map<PatternEdge, EdgeId>    // optional
  residual_edges: list<EdgeId>          // edges inside match that pattern does not cover
  support_spans: list<SpanRef>
  created_t: Time
}
```

### D18 PatternStats

Confidence-weighted promotion state.

```text
PatternStats {
  pat_id: PatId
  hyp_id: HypId
  uses: int
  wins: int                  // "worked" outcomes
  losses: int                // "failed" outcomes
  prov_score: float          // provenance aggregate
  θ_posterior: BetaParams    // (a,b) for reliability
  promoted_level: enum {candidate, stable, pinned}
  updated_t: Time
}
```

### D19 FailureCase

Explicit bad memory.

```text
FailureCase {
  fail_id: FailId
  pat_id: PatId?
  inst_id: InstId?
  signature: bytes32            // pattern + context hash
  context_features: bytes       // compact feature vector
  reason: enum {validator_reject, user_correction, task_fail}
  evidence: list<SpanRef>
  severity: float
  created_t: Time
}
```

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

### D23 ModuleLibrary

Library of reusable structural components extracted from patterns.

```text
ModuleLibrary {
  modules: Map<ModuleId, Module>
  interface_index: Map<InterfaceSignature, list<ModuleId>>
  usage_stats: Map<ModuleId, ModuleStats>
}

Module {
  mod_id: ModuleId
  subgraph: PatternGraph              // stable reusable component
  interface: InterfaceSpec            // typed slots and boundary edges
  provenance: list<PatId>             // patterns this was extracted from
  mdl_gain: float                     // compression gain
  created_t: Time
}
```

### D24 FactorDictionary

Sparse factor basis for canonical embeddings.

```text
FactorDictionary {
  dict_id: DictId
  D: Matrix[d_C × K]                  // factor directions, columns normalized
  Enc: EncoderFunc                    // x -> sparse coefficients a
  version: int
  epoch: EpochId
  fit_error: float
  sparsity: float                     // mean |a|_0
  created_t: Time
}
```

### D25 PatternDecomposition

Pattern represented as modules plus wiring.

```text
PatternDecomposition {
  pat_id: PatId
  modules: list<ModuleId>
  wiring: list<WiringConstraint>      // how modules connect
  residual_edges: list<EdgeSpec>      // edges not covered by modules
  compression_ratio: float
}
```

### D26 TradeoffProfile

Characterizes pattern functionality and performance across contexts.

```text
TradeoffProfile {
  pat_id: PatId
  factor_profile: SparseDistribution  // distribution over factor activations
  context_profile: Distribution       // contexts where pattern appears
  effect_metrics: {
    delta_E: float                    // mean energy reduction
    delta_T: float                    // mean tension reduction
    win_rate: float                   // task success rate
    cost: float                       // compute and memory footprint
    stability: float
    generality: float
    brittleness: float
    interpretability: float
  }
  pareto_rank: int                    // rank on Pareto frontier
  updated_t: Time
}
```

### D27 IdeaCandidate

Proposed pattern substitution or hybrid.

```text
IdeaCandidate {
  cand_id: CandId
  kind: enum {substitution, hybrid}
  region: RegionRef                   // where to apply
  source_patterns: list<PatId>        // patterns being combined/transferred
  rewrite: RewriteSpec                // graph transformation
  predicted_gain: float               // expected effect delta
  factor_match_score: float           // how well factors align
  interface_compat: float             // interface compatibility score
  created_t: Time
  epoch: EpochId
}
```

## D28 Graph token

A token that exists in a grammar, not necessarily in text.

```text
GraphToken {
  tok_id: TokId
  tok_type: TokTypeId                 // word, sentence, ASTNode, Function, Subsystem, Pattern, Idea, Hypothesis, ...
  provenance: list<SpanRef>           // can be empty when tok is purely structural
  anchor_nodes: list<NodeId>          // links into evidence graph
  graph_coords: GraphCoordRef         // pointers to subgraph or match bindings
  hyp_id: HypId
  tier: Tier
  created_t: Time
}
```

## D29 Grammar rule as graph rewrite

Use an algebraic graph transformation style rule object.

```text
Rule {
  rule_id: RuleId
  domain: DomainId                    // English, Python, Logs, Images, Mixed, ...
  lhs: PatternGraph                   // match graph
  interface: PatternGraph             // glue graph
  rhs: PatternGraph                   // output graph
  emit: EmitSpec                      // token types to create, edges to add
  score: RuleScoreModel               // probability, cost, priors
  conf: float                         // learned or curated confidence
  version: int
}
```

This matches standard graph transformation and graph grammar formalisms in the DPO family.

## D30 Parse hypothesis

A single interpretation state, contains a token graph plus mappings back to evidence.

```text
ParseHypothesis {
  hyp_id: HypId
  domain: DomainId
  input_region: RegionRef
  token_graph: GraphViewRef
  bindings: list<Binding>             // rule matches and slot bindings
  score: float
  uncertainty: float
  parent: HypId?
}
```

## D31 Parse forest

Packed storage of many hypotheses sharing substructure.

```text
ParseForest {
  region: RegionRef
  packed_dag: DAGRef                  // shared subgraphs across hypotheses
  active_hyps: list<HypId>
  best_hyps: list<HypId>
}
```

This mirrors packed forest and graph-structured stack ideas used to control ambiguity blow-up in GLR style parsing.

## D32 Coordinate system

A named vector space plus its mapping to a canonical space.

```text
CoordSystem {
  cs_id: CSId
  dim: int
  kind: enum {text, code, graph, table, image, hybrid}
  embedder_id: string
  canonical_map: MapId                // cs -> canonical transform
}
```

## D33 Adapter map

A transform between spaces.

```text
AdapterMap {
  map_id: MapId
  src: CSId
  dst: CSId                           // usually canonical
  form: enum {orthogonal, linear, nonlinear}
  params: bytes
  fit_error: float
  updated_t: Time
}
```

Multi-view alignment and fusion is a standard frame for coordinating multiple embedding spaces.

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

### D39 Workspace

```
Workspace {
  ws_id: WsId
  agent_id: AgentId
  parent_ws: WsId?          // null for root
  base_epoch: EpochId
  base_lsn_end: LogOffset
  created_t: Time
  ttl: Duration
  status: enum {open, closing, closed}
  children: set<WsId>
  wsg: WorkspaceGraphRef
  event_log: WorkspaceEventLogRef
  indices: {ann_index?, wl_index?, text_index?}
}
```

### D40 WorkspaceEvent

```
WorkspaceEvent {
  ev_id: EvId
  ws_id: WsId
  parent_ev: EvId?          // causal link (optional)
  t: Time
  kind: enum {
    add_node, add_edge, update_attr, remove_node, remove_edge,
    import_capsule, export_capsule,
    create_child, close_ws,
    add_note, add_link, add_tag,
    viewport_set_focus
  }
  payload: bytes
}
```

Notes:
* remove_* is implemented via tombstones (never physical delete in-session).

### D41 WorkspaceGraph

```
WorkspaceGraph {
  nodes: map<NodeId, NodeRec>
  edges: map<EdgeId, EdgeRec>
  tombstones: {nodes: set<NodeId>, edges: set<EdgeId>}
}

NodeRec {
  node_id: NodeId
  type: TypeId?               // optional; open vocabulary
  attrs: map<string, Value>
  provenance: list<SpanRef>   // may be empty
  structural_only: bool
  risk_tags: set<RiskTag>
  origin: OriginRef
}

EdgeRec {
  edge_id: EdgeId
  src: NodeId
  dst: NodeId
  etype: TypeId?
  attrs: map<string, Value>
  provenance: list<SpanRef>
  structural_only: bool
  risk_tags: set<RiskTag>
  origin: OriginRef
}

OriginRef {
  source: enum {ltm_import, agent_create, child_import, tool_import}
  capsule_id: CapsuleId?      // if imported
  ws_id: WsId
  ev_id: EvId
}
```

### D42 Capsule

```
Capsule {
  capsule_id: CapsuleId
  created_t: Time
  origin_ws: WsId
  base_epoch: EpochId
  base_lsn_end: LogOffset

  // Portable payload
  subgraph: bytes              // graph encoding
  manifest: CapsuleManifest
  fingerprint: CapsuleFingerprint
  hop_trace: list<WsId>
}

CapsuleManifest {
  region_id: RegionId
  node_ids: list<NodeId>
  edge_ids: list<EdgeId>
  dependencies: list<DependencyRef>
  invariants: list<InvariantHint>
  intent: string?
  risk_tags: set<RiskTag>
}

CapsuleFingerprint {
  wl_hash: string              // Weisfeiler-Lehman style structure hash
  minhash: bytes               // set resemblance sketch
  simhash: uint64              // cosine-like sketch
  embed_centroid: float[d]?    // optional
}
```

### D43 WorkspaceMessage

```
WorkspaceMessage {
  msg_id: MsgId
  from_ws: WsId
  to_ws: WsId
  sent_t: Time
  kind: enum {capsule, control, status}
  capsule: Capsule?
  note: string?
}
```

### D44 ReconcileRecord

```
ReconcileRecord {
  parent_ws: WsId
  child_ws: WsId
  child_capsule: CapsuleId
  decision: enum {imported, imported_as_branch, parked, rejected}
  reasons: list<string>
  overlap: float
  created_t: Time
}
```

### D45 WorkspaceCommitEnvelope

```
WorkspaceCommitEnvelope {
  env_id: EnvId
  ws_id: WsId
  base_epoch: EpochId
  base_lsn_end: LogOffset
  exported_capsules: list<CapsuleId>
  payload: bytes              // graph-form artifacts
  provenance: list<SpanRef>
  risk_tags: set<RiskTag>
  requested_actions: enum {ingest_only, ingest_and_propose_promotion}
}
```

### D46 ManifoldView

A pinned read view.

```text
ManifoldView {
  epoch_id: EpochId
  lsn_end: LogOffset
  hyp_id: HypId
}
```

### D47 ManifoldState

The explicit manifold state per epoch/hypothesis.

```text
ManifoldState {
  epoch_id: EpochId
  hyp_id: HypId

  X: NodeId -> Vector[dC]           // canonical coordinates
  W_eff: EdgeId -> float            // w_base * gate * robust
  A: NodeId -> float                // anchor weights α_i
  M: NodeId -> float                // regularizer μ_i

  diag: {
    r: NodeId -> float              // residual
    T: NodeId -> float              // tension
    u: NodeId -> float              // uncertainty
    var: NodeId -> float            // local variance proxy
  }
}
```

### D48 TangentFrame

A local chart basis for node i.

```text
TangentFrame {
  node_id: NodeId
  hyp_id: HypId
  basis: Matrix[dC x m]             // orthonormal columns (m << dC)
  evals: Vector[m]                  // local spectrum proxy
  built_lsn: LogOffset
}
```

### D49 EdgeTransport

A discrete parallel transport operator between tangent frames.

```text
EdgeTransport {
  edge_id: EdgeId
  hyp_id: HypId
  R_ij: Matrix[m x m]               // approx orthogonal map from i-frame to j-frame
  weight: float                     // typically W_eff(edge)
}
```

### D50 ConnectionLaplacian

A block Laplacian over tangent bundles.

```text
ConnectionLaplacian {
  hyp_id: HypId
  m: int
  // implicit operator form; can be applied without materializing full blocks
  apply(y): y -> y
}
```

### D51 BlendRecipe

```text
BlendRecipe {
  blend_id: BlendId
  name: string
  version: int
  terms: list<{field_id, weight}>
  scope: enum {query, domain, policy, epoch}
  constraints: {risk_caps, novelty_caps, max_abs_weight, ...}
}
```

### D52 CompositeField (ephemeral)

```text
CompositeField {
  view: ManifoldView
  recipe: BlendRecipe
  score: NodeId -> float
  grad_tangent: NodeId -> Vector[m]?   // optional tangent gradient
}
```

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

### D55 HippocampalWorkspace

```text
HippocampalWorkspace {
  hws_id: HwsId
  base_epoch: EpochId
  region: RegionRef
  forest: ParseForestRef            // packed hypotheses
  overlay_graph: GraphOverlayRef    // copy-on-write overlay on top of base epoch
  active_hyps: list<HypId>
  created_t: Time
  ttl: Duration
}
```

### D56 NeocortexProposal

```text
NeocortexProposal {
  prop_id: PropId
  base_epoch: EpochId
  region: RegionRef
  payload: { tokens, edges, candidate_rules?, candidate_adapters? }
  provenance: list<SpanRef>
  confidence: float
  prov_score: float
  risk_tags: set<RiskTag>
  created_t: Time
}
```

### D57 CommitRecord

```text
CommitRecord {
  commit_id: CommitId
  prop_id: PropId
  base_epoch: EpochId
  new_epoch: EpochId
  decision: enum {committed, branched, quarantined, rejected}
  reasons: list<Reason>
  metrics: { residual, tension, variance }
  created_t: Time
}
```

### D58 CurriculumStage

```text
CurriculumStage {
  stage_id: enum {bootstrap, expansion, open}
  default_alpha: float
  default_gate: float
  beam_width: int
  validation_budget: int
  grammar_policy: GrammarPolicyRef
  adapter_policy: AdapterPolicyRef
}
```

### D59 SurpriseBudget

```text
SurpriseBudget {
  domain: DomainId
  window: TimeWindow
  budget: float
  spent: float
}
```

### D60 ConnectivityState

```text
ConnectivityState {
  epoch: EpochId
  cluster_graph: SuperGraphRef
  articulation_candidates: list<NodeId>
  bridge_candidates: list<EdgeId>
  redundancy_targets: {k_paths, long_links_per_cluster}
}
```

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

\frac{1}{2}r^2 & r \le \delta \
\delta r - \frac{1}{2}\delta^2 & r > \delta
\end{cases}
]
Huber comes from robust estimation work.

This keeps "everything is a hypothesis" intact. The objective is per hypothesis branch.

### P2.2 IRLS weight update rule

IRLS builds a quadratic surrogate by reweighting edges.

Define a robust weight function:
[
\omega_\delta(r) = \frac{\rho'_\delta(r)}{r + \varepsilon}
]

For Huber:
[
\omega_\delta(r) =
\begin{cases}
1 & r \le \delta \
\frac{\delta}{r+\varepsilon} & r > \delta
\end{cases}
]

Effective edge weight in IRLS iteration (k):
[
\tilde{w}*{ij}^{(k,h)} = w*{ij},g_{ij}^{(h)},\omega_{\delta_{ij}}(d_{ij}^{(k,h)})
]

Then the surrogate objective at iteration (k) becomes a weighted quadratic:
[
\tilde{\mathcal{E}}^{(k,h)}(X) =
\sum_{(i,j)} \tilde{w}_{ij}^{(k,h)} \lVert x_i^{(h)} - x_j^{(h)} \rVert^2
+
\sum_i \alpha_i \lVert x_i^{(h)} - b_i \rVert^2
+
\sum_i \mu_i \lVert x_i^{(h)} \rVert^2
+ C
]

Minimizing this surrogate is a Laplacian system solve with weights (\tilde{w}).

IRLS for robust regression is a standard approach.
IRLS as MM is covered in MM tutorials and more recent analyses.

### P2.3 Linear solve in each IRLS step

Let (L_{\tilde{w}}) be the Laplacian built from (\tilde{w}*{ij}^{(k,h)}). As before:
[
(L*{\tilde{w}} + A + M) X^{(h)} = A B
]

For scale, this is an SDD system. Nearly linear-time solvers exist in theory, and practical iterative solvers with preconditioning work well.

### P4.1 Structural abstraction as MDL graph compression

Let (G) be the evidence graph view (snapshot epoch). Let (\mathcal{P}) be a set of candidate patterns and (\mathcal{I}) a set of pattern instances covering subgraphs of (G).

Define a description length:
[
L(G, \mathcal{P}, \mathcal{I}) = L(\mathcal{P}) + L(\mathcal{I}) + L(\text{residual}(G \mid \mathcal{P},\mathcal{I}))
]

Goal (sleep-time):
[
(\mathcal{P}^*, \mathcal{I}^*) = \arg\min_{\mathcal{P},\mathcal{I}} L(G,\mathcal{P},\mathcal{I})
]

This is the same principle used in MDL-based graph summarization systems: include a structure if it reduces total description length.

#### Confidence-weighted MDL

Add a penalty for low-confidence patterns:
[
L'(G,\mathcal{P},\mathcal{I}) = L(G,\mathcal{P},\mathcal{I}) + \sum_{p\in\mathcal{P}} \lambda \cdot \phi(\text{conf}(p))
]
where (\phi) decreases as confidence increases (example: (\phi(c)= -\log(c+\epsilon))).

This aligns with "abstract with confidence".

### P4.2 Pattern promotion as Bayesian reliability

Each pattern (p) has an unknown reliability (\theta_p \in [0,1]) ("probability this pattern helps").

Maintain Beta posterior:

* prior: (\theta_p \sim \mathrm{Beta}(a_0,b_0))
* after wins/losses: (\theta_p \mid \text{data} \sim \mathrm{Beta}(a_0+w,; b_0+\ell))

Promotion rule:
[
\Pr(\theta_p \ge \tau) \ge 1-\delta
\Rightarrow \text{promote}(p)
]

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

### P4.4 Light outcome feedback as contextual bandit over system actions

Define an action set (\mathcal{A}) over system knobs, e.g.:

* choose which patterns to expand to LLM
* choose which conflicts to validate next
* choose promote vs branch vs retract
* choose bridge candidates to validate

Observe reward (r_t) from task outcome (light feedback). Use contextual bandit updates (UCB/Thompson) to adapt policy with sublinear regret under standard assumptions.

### P4.5 Risk governance via selective prediction / conformal risk control

Use uncertainty (residual/tension/variance) as a heuristic score, then conformalize deferral thresholds for calibrated risk control.

## P5.1 Graph grammar semantics

Represent the current world as a typed hypergraph (G).

A rule (p) is a rewrite:
[
L \xleftarrow{l} K \xrightarrow{r} R
]
where:

* (L) is the match pattern
* (K) is the interface preserved during rewriting
* (R) is the replacement graph

DPO and related algebraic approaches define when a match is valid and how rewriting constructs the new graph via pushouts.

For language-like parsing on graphs, HRG and related formalisms provide the “context-free grammar for graphs” analogue.

## P5.2 Probabilistic and scored rewriting

Attach a score to each rule application. This can be probability or cost.

Probabilistic graph grammars exist with rule probabilities inducing derivation probabilities.

Define a derivation score for a hypothesis (h):
[
S(h) = \sum_{\text{rule apps } a \in h} \log P(a) ;-; \lambda \cdot \text{Tension}(h);-;\gamma \cdot \text{Complexity}(h)
]

* (P(a)) from the rule score model
* Tension comes from the field diagnostics inside the hypothesis
* Complexity penalizes overly complex parses

## P5.3 Multi-coordinate embeddings as a bundle with a canonical field

Each token (i) can have observations from multiple coordinate systems (v \in \mathcal{V}(i)):

* (b_i^{(v)} \in \mathbb{R}^{d_v})

Each coordinate system (v) has a mapping into a canonical space (C):

* (A_v: \mathbb{R}^{d_v} \to \mathbb{R}^{d_C})

Canonical observation for node (i):
[
\bar{b}*i = \frac{\sum*{v \in \mathcal{V}(i)} \beta_i^{(v)} A_v b_i^{(v)}}{\sum_{v \in \mathcal{V}(i)} \beta_i^{(v)}}
]
where (\beta_i^{(v)}) are confidence weights per view.

Canonical field solve per hypothesis stays the same Laplacian style objective, now anchored to (\bar{b}*i):
[
\sum*{(i,j)} w_{ij} g_{ij},\rho_\delta(|x_i-x_j|)
+
\sum_i \alpha_i |x_i-\bar{b}_i|^2
+
\sum_i \mu_i |x_i|^2
]

Multi-view alignment and fusion is a standard concept, including correlation-based alignment like CCA and mapping-based approaches like Procrustes.

## P5.4 Adapter learning

Two practical adapter forms:

### Orthogonal Procrustes map

For paired vectors ((u_k, v_k)) in two spaces, find an orthogonal matrix (R) minimizing:
[
\min_{R^\top R = I} |UR - V|_F

### Algorithm 10: Structural Abstraction Mining (sleep-time)

Runs inside Algorithm 9 (Global Consolidation) after snapshot creation, before index build.

```pseudo
function STRUCTURAL_ABSTRACTION_MINE(snapshot snap):
  C = MINE_CANDIDATE_SUBGRAPHS(snap.graph_view)       // motifs, stars, cliques, chains, rules
  P = {}
  I = {}

  for cand in C:
    pat = CANONICALIZE_TO_PATTERN(cand)              // slotify entities, normalize types
    score = MDL_GAIN(snap.graph_view, pat)           // Δ description length
    conf  = ESTIMATE_PATTERN_CONFIDENCE(pat)         // from stats/provenance
    score' = score - λ * penalty(conf)

    if score' > 0:
      P.add(pat)

  // choose non-overlapping / best-cover instance set (greedy)
  for pat in SORT_BY_SCORE(P):
    matches = FIND_MATCHES(snap.graph_view, pat)
    matches = FILTER_OVERLAPS(matches, I)
    I.add(BEST_MATCHES(matches))

  WRITE_PATTERN_LIBRARY(P)
  WRITE_PATTERN_INSTANCES(I)
  return (P, I)
```

MDL summarization and "replace subgraph with single vertex" is a known compression pattern in graph summarization and grammar induction lines of work.

### Algorithm 11: Online Pattern Instantiation (day-time)

Matches new evidence into existing abstractions without deleting evidence.

```pseudo
function TRY_INSTANTIATE_PATTERNS(new_node v, hyp h):
  candidates = ANN_PATTERN_RETRIEVE(v.x, h)
  for pat in TOPK(candidates):
    if FAST_STRUCTURAL_GATE(pat, v):
      match = LOCAL_SUBGRAPH_MATCH(pat, around=v, radius=r)
      if match.found:
        inst = CREATE_INSTANCE(pat, match, hyp=h)
        UPDATE_PATTERN_STATS_ON_USE(pat, inst)
        ATTACH_MACRONODE(inst)                       // optional macro node in contextual tier
```

This is the "reuse patterns with alterations" hook: slot bindings vary per instance. Case-based reasoning is the classic framing for retrieve → reuse → revise → retain.

### Algorithm 12: Expansion Compiler (decompress for LLM)

Produces context packs that can be expanded by token budget.

```pseudo
function COMPILE_CONTEXT_FOR_LLM(query q, budget B, risk_profile R):
  items = RETRIEVE_RELEVANT_NODES_AND_PATTERNS(q)

  pack = []
  for item in PRIORITIZE(items, by=risk_and_relevance):
    if item is PatternInstance:
      frame = RENDER_PATTERN_FRAME(item)            // canonical_text + filled slots
      evidence = SELECT_SUPPORT_SPANS(item, cap=B_remaining)
      pack.add(frame)
      pack.add(evidence)
    else:
      pack.add(FETCH_SPAN(item.span_ref))

    if TOKENS(pack) >= B: break

  return pack
```

This matches "compressed memory + reflection/summary + expansion on demand" patterns seen in long-term agent memory and hierarchical retrieval systems.

### Algorithm 13: Confidence-weighted Pattern Promotion

```pseudo
function UPDATE_PATTERN_CONFIDENCE(pat_id, outcome):
  stats = GET_STATS(pat_id)
  if outcome == win:   stats.wins += 1
  if outcome == loss:  stats.losses += 1
  stats.uses += 1

  stats.θ_posterior = BETA_UPDATE(stats.θ_posterior, outcome)

  if P(θ >= τ | posterior) >= 1-δ and stats.uses >= Nmin:
    PROMOTE_PATTERN(pat_id)                          // candidate -> stable -> pinned

  if P(θ >= τ_low | posterior) < ε:
    DEMOTE_OR_QUARANTINE(pat_id)
```

"Pinned pattern" is the abstraction analogue of pinned facts.

### Algorithm 14: Failure Memory Write + Avoid

```pseudo
function RECORD_FAILURE(target, reason, evidence, severity, ctx):
  f = NEW_FAILURE_CASE(target, reason, evidence, severity, ctx)
  FAILURE_STORE.APPEND(f)

function FAILURE_BRAKE_SCORE(pat_id, ctx):
  sig = HASH(pat_id, ctx_bucket(ctx))
  return LOOKUP_FAILURE_RATE(sig)                   // smoothed count-based model

function PATTERN_SCORE(pat_id, ctx):
  base = BASE_PATTERN_SCORE(pat_id, ctx)
  brake = exp(-η * FAILURE_BRAKE_SCORE(pat_id, ctx))
  return base * brake
```

This is aligned with storing self-reflective "lessons" from mistakes for later avoidance in agent memory work.

### Algorithm 15: Light Outcome Feedback Loop (bandit)

```pseudo
function POLICY_STEP(context φ):
  a = SELECT_ACTION_UCB_OR_TS(φ)                     // which knob to turn
  EXECUTE_ACTION(a)
  r = OBSERVE_REWARD()                               // task success, user edit, implicit
  UPDATE_POLICY(φ, a, r)
  STORE_FEEDBACK_EVENT(φ, a, r)
```

Bandit foundations and safe online learning to re-rank provide the template for "light feedback, safe updates."

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

Conformal / selective frameworks supply calibrated abstention and risk control patterns for deferral decisions.

]
This preserves distances and angles in the mapped space. Manifold alignment via Procrustes uses this idea.

### General multi-view alignment

Use alignment and fusion approaches from multi-view representation learning when orthogonal mapping feels too rigid.

### P6.1 Workspace overlay model

Let \(G^{(e)}\) be the long-term graph at epoch \(e\).
HWS stores an overlay \(\Delta G\) such that the workspace view is:
\[
G^{\text{hws}} = G^{(e)} \oplus \Delta G
\]
Reads use \(G^{(e)}\) or \(G^{\text{hws}}\) depending on scope.

This is the same principle as snapshot isolation, readers see a stable snapshot while writers create new versions.

### P6.2 Two-stage commit as an admissibility filter

Neocortex emits proposal (P).
Hippocampus produces a set of re-ingested hypotheses ({h_k}) with scores:
[
S(h_k) = \log P(\text{parse}_k) - \lambda T(h_k) - \gamma C(h_k) - \eta R(h_k)
]

* (T) tension from field diagnostics
* (C) complexity
* (R) risk penalty from governance layer

Commit selects:
[
h^* = \arg\max_k S(h_k)
]
then applies a promotion rule:
[
\Pr(\theta_{h^*} \ge \tau) \ge 1-\delta
\Rightarrow \text{commit}
]
else branch or quarantine.

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

### P6.4 Connectivity targets

Define a cluster graph (H) whose nodes are communities in (G).
Target: small-world style redundancy, keep average path length low and maintain multiple inter-cluster bridges.

Practical invariant:

* for each cluster pair ((A,B)) with frequent co-retrieval, maintain at least (k) disjoint bridge candidates.

### P6.5 Adapter drift detection

Monitor an online error series (E_t) for an adapter, like retrieval regression or alignment loss.
Use adaptive-window drift detection for change points.

---

### P9.1 Discrete manifold (robust gated field)

Per hypothesis h, the manifold is induced by the robust gated objective (P1–P2), which is a weighted graph-smoothing + anchoring energy.

Let W_eff encode the effective conductance:

* W_eff(e) = w_base(e) * gate(e,h) * robust_weight(e,h)

Then the per-hypothesis solve is:

[L_{W_eff} + A + M] X = A B

The graph Laplacian can be decomposed as a sum of per-edge rank-1 terms:

L = Σ_{(i,j)∈E} w_{ij} (e_i - e_j)(e_i - e_j)^T

This decomposition is the basis for low-rank updates when edge weights change.

### P9.2 Local tangent frames (projection basis)

For node i, compute a weighted covariance of neighbor displacements:

C_i = Σ_{j∈N(i)} W_eff(i,j) (x_j - x_i)(x_j - x_i)^T

Let U_i be the top-m eigenvectors of C_i. U_i is the local tangent basis.

This is the standard "local PCA / local tangent space" idea used in manifold learning (e.g., LTSA-style pipelines).

### P9.3 Discrete parallel transport via connection Laplacian (solves the translation dragon)

Local frames alone do not let you compare directions across distant nodes; you need transport.

Define an edge-wise orthogonal alignment between frames:

R_ij = argmin_{R ∈ O(m)} || U_i R - U_j ||_F

(Orthogonal Procrustes; solved by SVD.)

Build a connection graph operator on tangent vectors:

* For each edge (i,j): block weight S_{ij} = W_eff(i,j) R_ij
* Block degree D_{ii} = (Σ_j W_eff(i,j)) I_m

Define the connection Laplacian operator:

L_conn = D - S

This operator generalizes scalar Laplacians to vector fields and supports:

* smoothing vector fields
* constructing near-parallel coordinates
* defining vector-diffusion distances

### P9.4 Vector-diffusion distance (optional)

Use top eigenpairs of a normalized connection Laplacian (VDM) to embed nodes so that both proximity and alignment are captured.

This provides a principled "wormhole" signal:

* nodes that are not structurally adjacent can be geometrically close if a consistent transport exists.

### P9.5 Field blending (control, not topology)

Primitive scalar fields include:

* goal distance d_q(i) (query similarity)
* tension T(i)
* residual r(i)
* uncertainty u(i)
* risk(i)
* novelty nov(i)

A BlendRecipe defines a composite score:

S_q(i) = Σ_k λ_k field_k(i)

Optional tangent gradient uses local transport + finite differences:

∇_t S(i) ≈ Σ_{j∈N(i)} W_eff(i,j) (S(j) - S(i)) * R_ij^T 1

The composite field guides traversal and scheduling; it never directly mutates W_eff/A/M.


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

### P7.2 Interestingness score

[
I(s) = w_T T + w_r r + w_v \widehat{var} + w_n nov + w_{rec} rec + w_p prov - w_k risk - w_c cost
]

Weights can be:

* fixed per domain
* adapted via P4 light feedback (reward shaping)

### P7.3 Learning progress

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

### P7.4 Novelty

Two options, both usable.

**Distance novelty**
[
nov(s)=\min_{p \in \mathcal{P}} |z(s)-z(p)|
]
where (z(\cdot)) is a structural embedding of the seed subgraph or pattern.

**Prediction novelty**
Use an exploration bonus based on prediction error of a fixed target representation, similar in spirit to RND.

Novelty search literature supports novelty as a primary driver for open-ended discovery.

### P7.5 Information gain for inquiry selection

For candidate inquiry action (a):
[
IG(a) = H(\Theta \mid D) - \mathbb{E}_{y \sim p(y \mid a,D)}[H(\Theta \mid D \cup (a,y))]
]
This is the classic expected informativeness frame for selecting data.

### P7.6 Utility for scheduling

[
U(s) = I(s) + \lambda LP(s) + \mu \max_{a \in A(s)} IG(a)
]
subject to budgets:
[
\sum cost(\text{explores}) \le B_{explore}, \quad \sum cost(\text{llm calls}) \le B_{llm}
]

---

### P10.1 Convergence-safe state model (event-set join)

Represent a workspace state as:

  State(ws) = BaseView + Join(Events(ws))

Where:
* Events(ws) is an append-only set of operations with unique IDs.
* Join is deterministic, commutative, associative, and idempotent (a semilattice join).

This implies: if any two replicas/reconciliations apply the same set of events, they converge to the same state.

## P10.2 Workspace graph as a graph CRDT (optional mode)

When a workspace requires deterministic merge semantics under concurrent edits, model the WSG using CRDT components:

* V: a CRDT set of vertices
* E: a CRDT set of edges

To maintain the graph invariant that edges reference existing vertices, use a standard CRDT approach:

* remove-vertex either removes incident edges (remove-wins), or
* add-edge can restore missing vertices (add-wins)

P10 defaults to remove-wins for safety in a workspace (deleting a node removes its edges), implemented with tombstones.

## P10.3 Delta-state replication for workspaces (optional)

Workspaces may sync their event logs as deltas rather than full states. This is compatible with delta-state CRDT designs where small delta fragments are joined into the replica state.

## P10.4 Overlap as near-duplicate detection

Overlap between two capsules/regions is estimated using a multi-stage signature:

1) Structure hash: WL-style hashing over labeled neighborhoods
2) Set resemblance: MinHash sketch over structural shingles
3) Cosine-like similarity: SimHash over embedded shingles

This supports fast approximate overlap queries over many workspaces.
---

## Algorithm 1: Streaming ingestion

Goal: create evidence nodes, create idea handles, build edges, update tiers, update the field locally.

Ingestion becomes append-only for state. `x` updates create `NodeState` records.

```pseudo
function INGEST_STREAM(stream):
  for span in STREAM_TO_SPANS(stream):
    v = NEW_NODE(level=EVIDENCE, span_ref=span.ref)

    b = EMBED(span.text)
    STORE ObservationRecord(node=v.id, b=b, embedder_id, version, input_hash)

    INIT NodeState for each active hypothesis h:
      state = NEW_STATE(node=v.id, hyp=h, x=b, u=HIGH, r=0, T=0)
      v.current_state[h] = state.id

    GRAPH.ADD_NODE(v)
    ADD_EDGES_WITH_BELIEFS(v, span.text)        // creates EdgeBelief with g default values

    ATTACH_TO_IDEAS(v)                          // membership edges become EdgeBelief too

    PROMOTE_DEMOTE_TIERS()

    AFFECTED = NEIGHBORHOOD(v, radius=r_tier(v.tier))
    FIELD_UPDATE_WITH_DIAGNOSTICS(AFFECTED)

    CONFLICT_SCAN_AND_QUEUE(AFFECTED)
    UPDATE_INDICES(AFFECTED)
    LOG_EVENT(...)
```

## Algorithm 2: Idea candidate selection

Idea-first means “create handles early, refine later”.

```pseudo
function SELECT_OR_CREATE_IDEA(candidates, v):
  for idea in TOPK(candidates):
    if PASS_FAST_GATE(v, idea):                        // cosine, overlap, structure checks
      if PASS_VALIDATION(v, idea):                     // optional LLM/classifier
        return idea

  // else create a provisional idea handle
  idea = NEW_NODE(level=IDEA, span_ref=null)
  idea.b = v.b                                         // seed from evidence
  idea.x = v.x
  idea.u = HIGH
  idea.tier = CONTEXT
  GRAPH.ADD_NODE(idea)
  return idea
```

Validation is where hard constraints live. Geometry proposes. Validation commits.

## Algorithm 3: Field relaxation on a subgraph

Field update computes diagnostics and uses gates.

```pseudo
function FIELD_UPDATE_WITH_DIAGNOSTICS(nodes S):
  for hypothesis h in ACTIVE_HYPOTHESES_IN_SCOPE(S):
    FIELD_RELAX_GATED(S, h, steps=s_tier)

    // compute diagnostics
    for i in S:
      x = STATE(i,h).x
      b = OBS(i).b
      r = NORM(x - b)
      T = SUM_{(i,j)} w_eff(i,j,h) * NORM2(x - STATE(j,h).x)
      APPEND_STATE_METRICS(i,h,r,T)

    for each edge (i,j) touching S:
      t = w_eff(i,j) * NORM2(STATE(i,h).x - STATE(j,h).x)
      UPDATE_EDGE_TENSION(edge_id, t)

function FIELD_RELAX_GATED(nodes S, hypothesis h, steps T):
  repeat T times:
    for i in SHUFFLE(S):
      denom = alpha[i] + mu[i] + SUM_{j in N(i)} w[i,j] * g[i,j,h]
      numer = alpha[i] * b[i] + SUM_{j in N(i)} w[i,j] * g[i,j,h] * x[j,h]
      x[i,h] = numer / denom
```

Coordinate update under gated quadratic stays closed form:
[
x_i \leftarrow
\frac{\alpha_i b_i + \sum_{j} w_{ij}g_{ij} x_j}{\alpha_i + \mu_i + \sum_{j} w_{ij}g_{ij}}
]

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

## Algorithm 5: Boundary detection without fixed chunking

Use change in direction as a signal, plus structure cues. Bayesian online changepoint detection is a clean option.

```pseudo
function STREAM_TO_SPANS(stream):
  run BOCPD over feature z_t = [cos(b_t, b_{t-1}), punctuation, heading, entity_shift]
  emit boundary when P(changepoint) > tau
  yield span
```

## Algorithm 6: Conflict scan

Conflict scan detects high tension and residual to identify ambiguity.

```pseudo
function CONFLICT_SCAN_AND_QUEUE(nodes S):
  for i in S:
    if STATE(i,main).T > TH_TENSION or STATE(i,main).r > TH_RESID:
      edges = TOPK_EDGES_BY_TENSION(i)
      CREATE_OR_UPDATE_CONFLICT_RECORD(i, edges)
```

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

### Algorithm 9: Global Consolidation

This is the "sleep" phase. It keeps ingestion running via snapshot isolation + versioned commit.

```pseudo
function GLOBAL_CONSOLIDATION(trigger):
  // 1) Create snapshot
  lsn0 = EVENT_LOG.TAIL_LSN()
  snap = CREATE_SNAPSHOT(lsn0)               // MVCC view or replay up to lsn0

  // 2) Choose hypothesis set to consolidate
  H = SELECT_HYPOTHESES(snap)                // main + top-weight forks + active conflicts

  // 3) Solve robust field on snapshot
  X_hat = {}
  for h in H parallel:
    X_hat[h] = ROBUST_FIELD_SOLVE_IRLS(snap, h)

  // 4) Build new epoch artifacts
  epoch_new = NEW_EPOCH(parent=ACTIVE_EPOCH, snapshot_lsn=lsn0)
  WRITE_NODE_STATES(epoch_new, X_hat)
  BUILD_INDICES(epoch_new, snap, H)          // HNSW, PQ, tiered indices
  BUILD_SUMMARIES(epoch_new, snap, H)        // optional

  // 5) Delta catch-up
  lsn1 = EVENT_LOG.TAIL_LSN()
  APPLY_DELTAS(epoch_new, from=lsn0, to=lsn1)

  // 6) Finalize indices after deltas
  FINALIZE_INDEX_DELTAS(epoch_new)

  // 7) Publish epoch via atomic swap + grace period
  PUBLISH_EPOCH(epoch_new)                   // RCU-style publish
  RETIRE_OLD_EPOCHS()
```

Snapshot isolation is the foundation for the consistent snapshot step.
Atomic publish semantics follow RCU style "publish pointer, wait grace period, reclaim old."

Event sourcing stays the audit layer that makes rebuilds reproducible.

#### Notes on BUILD_INDICES

This is a versioned build, then swap. The Lucene style segment approach is a practical reference point for "build new segments, then open them" behavior.

### Algorithm 65: Robust Field Solve via IRLS

Runs per hypothesis on the snapshot.

```pseudo
function ROBUST_FIELD_SOLVE_IRLS(snapshot snap, hyp h):
  X = INIT_FROM_PREV_EPOCH(snap, h)          // warm start
  for k in 1..Kmax:
    // 1) Update robust weights per edge
    for each smoothing edge e=(i,j) in snap.graph_view:
      r = NORM(X[i] - X[j])
      rw[e] = HUBER_WEIGHT(r, delta[e], eps) // 1 or delta/(r+eps)
      w_eff[e] = w_base[e] * gate[e,h] * rw[e]

    // 2) Solve weighted quadratic surrogate
    X_new = SOLVE_SDD_SYSTEM(w_eff, anchors, regs)

    // 3) Check progress
    if STOPPING_RULE(E(X_new), E(X), ||X_new-X||):
      X = X_new
      break

    X = X_new

  return X
```

Default stopping rule:

* relative objective decrease below (\tau)
* or max iteration count
* plus max per-iteration solver tolerance schedule

### Algorithm 66: Apply deltas after snapshot

This absorbs "daytime patches" that happened during the offline run.

```pseudo
function APPLY_DELTAS(epoch_new, from lsn0, to lsn1):
  events = EVENT_LOG.READ_RANGE(lsn0, lsn1)
  for ev in events:
    APPLY_EVENT_TO_EPOCH(epoch_new, ev)

    // local repair around touched nodes
    S = LOCAL_SCOPE(ev)
    LOCAL_RELAX_OR_IRLS_STEPS(epoch_new, S)     // cheap, bounded
    UPDATE_INDEX_DELTAS(epoch_new, S)
```

This keeps the new epoch aligned with live changes while keeping the offline solve isolated.

### Algorithm 67: Publish epoch with RCU semantics

```pseudo
function PUBLISH_EPOCH(epoch_new):
  epoch_new.status = ready
  ATOMIC_SWAP(GLOBAL_EPOCH_PTR, epoch_new.epoch_id)
  epoch_new.status = active

  // grace period before reclaim of old epochs
  WAIT_GRACE_PERIOD()
```

RCU provides the pattern: readers run lock-free against a stable snapshot while writer swaps the pointer then waits a grace period before reclaim.

## Algorithm 17

### Modality routing and tokenizer selection

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

## Algorithm 18

### Incremental graph grammar parsing with hypothesis beam

Grammar is applied to tokens to produce new graph tokens and token graphs.

```pseudo
function PARSE_REGION(region, dom, tokset):
  forest = INIT_PARSE_FOREST(region)

  // seed hypothesis with raw token graph
  h0 = NEW_HYP(region, dom)
  h0.token_graph = BUILD_TOKEN_GRAPH(tokset)          // adjacency edges, containment edges
  PUSH(forest.active_hyps, h0)

  for step in 1..MAX_STEPS:
    next = []
    for h in TOPK_BY_SCORE(forest.active_hyps, BEAM):
      matches = RULE_MATCH_INDEX[dom].CANDIDATE_MATCHES(h.token_graph)

      for m in matches:
        if PASS_FAST_MATCH_CHECK(m):
          h2 = APPLY_RULE(h, m)                       // graph rewrite, emits GraphTokens
          SCORE_UPDATE(h2)                            // rule prob, tension, complexity
          next.append(h2)

    forest = PACK_AND_MERGE(forest, next)             // share subgraphs across hyps
    if STOP_CONDITION(forest): break

  return forest
```

This mirrors the packed-forest idea used to manage ambiguity growth in GLR style parsing.

## Algorithm 19

### Rule application as graph rewrite with provenance

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

Graph transformation via DPO gives a formal foundation for safe rewrites and composition.

## Algorithm 20

### Grammar emergence from patterns

Turns P4 patterns into executable grammar rules.

```pseudo
function MINE_AND_COMPILE_GRAMMAR(snapshot snap, dom):
  patterns = STRUCTURAL_ABSTRACTION_MINE(snap)         // P4 Algorithm 10
  for pat in patterns:
    if pat.conf >= TH_RULE_CANDIDATE:
      rule = COMPILE_PATTERN_TO_RULE(pat, dom)         // lhs is pat, rhs emits macro token
      SHADOW_RUN(rule)                                 // collect precision, failure cases
      if PROMOTION_TEST(rule):                         // confidence-weighted
        GRAMMAR_LIBRARY.ADD(rule)
```

Hyperedge replacement and related graph grammar formalisms provide a language for “graph as grammar”.

## Algorithm 21

### Graph token embedding bundle and canonical projection

Every new graph token gets multi-embedder observations plus canonical anchor.

```pseudo
function EMBED_TOKEN(tok):
  obs = []

  if tok.provenance has spans:
    obs.append( TEXT_EMBED(tok.support_text) )

  obs.append( STRUCT_EMBED(tok.graph_coords) )         // WL hashes, graph2vec, GNN, etc.
  if tok.tok_type in CODE_TYPES:
    obs.append( CODE_EMBED(tok.graph_coords) )

  // map each obs into canonical space and combine by confidence
  b_bar = WEIGHTED_CANONICAL_COMBINE(obs, adapters, confidences)

  STORE_OBSERVATIONS(tok, obs)
  STORE_CANONICAL_ANCHOR(tok, b_bar)
```

Graph embeddings and substructure signatures like WL-based features and graph-level embeddings are standard tools.
Code embeddings from AST structure exist as well.

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

“Topology changes into different coordinate systems” becomes “travel happens in canonical space, with local boosts in native spaces.”

## Algorithm 23

### Re-ingestion under reinterpretation

This is the controlled way to replay the same evidence through a new grammar set or new adapters.

```pseudo
function REINTERPRET(epoch e, region R, new_grammar_set G*):
  snap = CREATE_SNAPSHOT(e.snapshot_lsn)
  forest = PARSE_REGION(R, dom=ROUTE(R), tokset=EXTRACT_RAW_TOKENS(R), grammar=G*)
  hyps = SELECT_TOP_HYPOTHESES(forest)

  for h in hyps:
    INTEGRATE_PARSE_GRAPH_AS_HYPOTHESIS(h)             // creates tokens, edges, anchors
    RUN_LOCAL_FIELD_REPAIR(h.scope)

  SCHEDULE_GLOBAL_CONSOLIDATION()
```

Graph parsing for HRG and related grammars is studied, and complexity varies a lot by restrictions, so this is designed with hypothesis beams and domain restrictions.

### Algorithm 24: Hippocampal workspace session

```pseudo
function HWS_OPEN(region R, base_epoch e):
  hws.base_epoch = e
  hws.overlay_graph = NEW_OVERLAY(e)
  hws.forest = INIT_PARSE_FOREST(R)
  return hws

function HWS_STEP(hws, proposal_or_input X):
  // build workspace tokens and graphs
  forest = PARSE_REGION_WITH_P5(hws, X)
  RUN_LOCAL_FIELD_REPAIR(hws.overlay_graph, forest.active_hyps)
  UPDATE_DIAGNOSTICS(hws)
  return hws

function HWS_CLOSE(hws):
  ARCHIVE(hws)         // TTL based
```

### Algorithm 25: Two-stage commit from neocortex to hippocampus

```pseudo
function HIPPOCAMPUS_2SC(proposal P):
  // Stage 0: admission
  if P.prov_score < P0 and P.confidence < C0:
    return QUARANTINE(P, reason="low provenance")

  // Stage 1: secondary ingestion into HWS
  hws = HWS_OPEN(P.region, P.base_epoch)
  hws = HWS_STEP(hws, P.payload)

  // Stage 2: choose best hypothesis and decision
  h_star = SELECT_BEST_HYP(hws.forest, metrics=hws.diagnostics, risk=P.risk_tags)

  decision = DECIDE_COMMIT_BRANCH_QUAR(h_star, budgets=SURP, curr=CURR.stage)
  record = WRITE_COMMIT_RECORD(P, h_star, decision)

  if decision == committed:
    APPLY_COMMIT_AS_NEW_EPOCH(h_star)     // append events, build indices async
  if decision == branched:
    STORE_BRANCH(h_star)                  // keep both
  if decision == quarantined:
    STORE_QUARANTINED(P, h_star)

  return record
```

This resembles snapshot read plus write-as-new-version discipline.

### Algorithm 26: Curriculum ingestion controller

```pseudo
function CURRICULUM_STAGE(epoch e, stats):
  if e < E_BOOT: return bootstrap
  if stats.drift_high or stats.conflict_high: return expansion
  return open

function APPLY_CURRICULUM_PARAMS(stage):
  set default_alpha, gate, beam_width, validation_budget
  set grammar_policy, adapter_policy
```

Curriculum learning is a standard stabilization strategy.

### Algorithm 27: Cold solve and re-rooting

```pseudo
function SHOULD_COLD_SOLVE(global_metrics M):
  return (M.path_dependence_score > θp) or (M.adapter_drift > θd) or (M.tension > θt)

function GLOBAL_CONSOLIDATION_COLD(epoch e):
  snap = SNAPSHOT_EVIDENCE_LOG(e)                  // raw event log
  REBUILD_GRAPH_FROM_EVIDENCE(snap)                // no warm-start states
  REFIT_ADAPTERS(snap)
  REMINE_PATTERNS_AND_GRAMMARS(snap)
  SOLVE_CANONICAL_FIELD(snap)
  SWAP_IN_NEW_INDICES_AT_EPOCH_BOUNDARY()
```

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

### Algorithm 29: Connectivity guard and bridge repair

```pseudo
function ON_GATE_CHANGE(epoch e, updates U):
  affected = FIND_AFFECTED_CLUSTERS(U)
  for cluster in affected:
    if RISK_OF_DISCONNECT(cluster, e):
      bridges = PROPOSE_BRIDGES(cluster, e)        // embedding + co-retrieval
      VALIDATE_BRIDGES(bridges)                    // inquiry tasks
      ADD_SKIP_CONNECTIONS(accepted_bridges)
```

Small-world connectivity is the target pattern.

### Algorithm 30: Grammar sandbox and promotion

```pseudo
function GRAMMAR_SANDBOX(rule r):
  r.status = shadow
  results = RUN_SHADOW_PARSE(r, heldout_regions)

  UPDATE_RULE_STATS(r, results)
  if POSTERIOR_OK(r) and FAILURE_RATE_OK(r):
    r.status = canary
    CANARY_RUN(rule=r, fraction=f)                // small percentage of ingestions
    if CANARY_OK(r):
      PROMOTE_RULE(r)
    else:
      ROLL_BACK_RULE(r)
```

Packed forests and shared parse forests are a known strategy to manage ambiguity in parsing.

### Algorithm 31: Adapter lifecycle and drift management

```pseudo
function ADAPTER_FIT(src_cs, dst_cs, paired_samples):
  cand = FIT_MAP(paired_samples)
  cand.status = shadow
  E0 = EVAL_OFFLINE(cand)

  if E0 > EMAX: return REJECT(cand)

  cand.status = canary
  CANARY_ROUTE(cand, traffic=f)                    // apply to a subset
  if CANARY_METRICS_OK(cand):
    PROMOTE(cand)
  else:
    ROLLBACK(cand)

function ADAPTER_DRIFT_MONITOR(adapter a):
  series = STREAM_ALIGNMENT_ERRORS(a)
  if ADWIN_DETECT(series):                         // change point
    TRIGGER_REFIT(a)
```

ADWIN is a standard drift detector with adaptive windowing.
Canary rollouts are a standard safety practice for changing live systems.

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

### Algorithm 33: Noise scan

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

**P4C2 proof sketch: MDL-driven abstraction reduces description length**

**Claim.** Given a candidate pattern set, choosing patterns by MDL yields shorter descriptions than raw graph encoding (for those patterns). (Algorithm is heuristic; objective is principled.)

**Sketch.** The objective directly minimizes description length. Greedy selection may not find global optimum but provides local improvement guarantees standard in submodular-style optimization.

**P4C3 proof sketch: Promotion guarantee**

**Claim.** If a pattern is promoted only when (\Pr(\theta_p \ge \tau) \ge 1-\delta), then promotion implies a posterior reliability guarantee.

**Sketch.** Direct from the posterior CDF of the Beta distribution.

**P4C5 proof sketch: Risk governance calibration**

**Claim.** Conformal prediction can convert heuristic uncertainty into prediction sets with distribution-free coverage, and selective conformal risk control combines deferral with risk control.

**Sketch.** Conformal coverage guarantee is standard; selection layer trades coverage vs abstention.

### Algorithm 34: Thread queue update

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

### Algorithm 35: Explore a seed

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

### Algorithm 36: Distill traces into tokens

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

### Algorithm 37: Curiosity scheduler

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

### Algorithm 38: Decay and cleanup

```pseudo
function SEED_DECAY(seed s):
  if STALE(s) and RECURRENCE_LOW(s):
    s.status = archived
  if FAILURE_HIGH(s) and LP_LOW(s):
    s.status = quarantined
```

### P10I10 Memory layer operations

The memory layer must support the following operations. A coordination system may call them, but P10 does not define the policy for when.

* WS_OPEN(agent_id, base_epoch, base_lsn_end, ttl) -> ws_id
* WS_CLOSE(ws_id, reason)
* WS_SPAWN_CHILD(parent_ws_id, ttl, seed_capsules[]) -> child_ws_id
* WS_EXPORT(parent_ws_id, selection_spec) -> capsule
* WS_IMPORT(ws_id, capsule) -> import_record
* WS_SEND(from_ws, to_ws, capsule, note)
* WS_QUERY(ws_id, query_spec) -> results
* WS_VIEW(ws_id, viewport_spec) -> prompt_pack
* WS_COMMIT(ws_id, exported_capsules, intent) -> commit_envelope

### Algorithm 53: OPEN_WORKSPACE

```pseudo
OPEN_WORKSPACE(agent_id, base_epoch, base_lsn_end, ttl):
  ws = new Workspace
  ws.base_epoch = base_epoch
  ws.base_lsn_end = base_lsn_end
  ws.status = open
  ws.ttl = ttl
  ws.event_log = empty
  return ws
```

### Algorithm 54: CLOSE_WORKSPACE_CASCADE (structured lifetime)

```pseudo
CLOSE_WORKSPACE_CASCADE(ws_id):
  if ws.status != open: return
  ws.status = closing
  for child in ws.children:
    CLOSE_WORKSPACE_CASCADE(child)
  ws.status = closed
  WGC.schedule(ws_id)
```

### Algorithm 55: SPAWN_CHILD (fork-join)

```pseudo
SPAWN_CHILD(parent_ws, ttl, seed_capsules):
  child = OPEN_WORKSPACE(agent_id = parent.agent_id,
                         base_epoch = parent.base_epoch,
                         base_lsn_end = parent.base_lsn_end,
                         ttl = ttl)
  child.parent_ws = parent.ws_id
  parent.children.add(child.ws_id)

  for cap in seed_capsules:
    WS_IMPORT(child.ws_id, cap)

  log event create_child
  return child.ws_id
```

### Algorithm 56: EXPORT_CAPSULE

```pseudo
EXPORT_CAPSULE(ws_id, selection_spec):
  subgraph = EXTRACT_SUBGRAPH(ws_id, selection_spec)
  fp = OVERLAP_SIGNATURE(subgraph)
  cap = Capsule(subgraph, manifest, fp)
  cap.hop_trace = [ws_id]
  log event export_capsule
  return cap
```

### Algorithm 57: IMPORT_CAPSULE (idempotent)

```pseudo
IMPORT_CAPSULE(ws_id, cap):
  // loop guard
  if ws_id in cap.hop_trace: reject

  // idempotence
  if cap.capsule_id in ws.import_registry: return existing_record

  // remap IDs to avoid collision
  mapping = BUILD_ID_REMAP(ws_id, cap.manifest)
  APPLY_SUBGRAPH_WITH_REMAP(ws_id, cap.subgraph, mapping)

  // record lineage
  ws.import_registry.add(cap.capsule_id)
  log event import_capsule

  // update overlap index
  OVI.add(ws_id, cap.fingerprint)

  return import_record
```

### Algorithm 58: MESSAGE_SEND

```pseudo
MESSAGE_SEND(from_ws, to_ws, cap, note):
  cap.hop_trace.append(to_ws)
  msg = WorkspaceMessage(from_ws, to_ws, cap, note)
  MSG.deliver(msg)
```

### Algorithm 59: RECONCILE_CHILD_TO_PARENT

```pseudo
RECONCILE_CHILD_TO_PARENT(parent_ws, child_ws, selection_spec):
  cap = EXPORT_CAPSULE(child_ws, selection_spec)
  overlap = OVERLAP_QUERY(parent_ws, cap.fingerprint)

  // RECON does not decide policy; it only computes signals.
  rec = ReconcileRecord(parent_ws, child_ws, cap.capsule_id, overlap)
  return rec, cap
```

### Algorithm 60: COMMIT_TO_INGEST (no LLM diffs)

```pseudo
COMMIT_TO_INGEST(ws_id, exported_capsules, intent):
  payload = BUILD_GRAPH_PAYLOAD(ws_id, exported_capsules)
  env = WorkspaceCommitEnvelope(ws_id, payload, base_epoch, base_lsn_end)
  CGW.submit_to_ingest(env)
  return env
```

### Algorithm 61: OVERLAP_SIGNATURE (structure + content)

```pseudo
OVERLAP_SIGNATURE(subgraph):
  wl_hash  = WL_HASH(subgraph, iterations = k)
  shingle_set = SHINGLES(subgraph)                // labels, edge types, local WL labels
  minhash = MINHASH(shingle_set)
  simhash = SIMHASH(EMBED(shingle_set))
  return {wl_hash, minhash, simhash}
```

### Algorithm 62: OVERLAP_DETECT

```pseudo
OVERLAP_DETECT(fingerprint_a, fingerprint_b):
  // fast filters
  if HAMMING(simhash_a, simhash_b) > H: return low_overlap

  // approximate set similarity
  j_hat = MINHASH_ESTIMATE(minhash_a, minhash_b)
  return j_hat
```

### Algorithm 63: OSCILLATION_SIGNAL

```pseudo
OSCILLATION_SIGNAL(ws_id, window):
  // Detect repeated edits with high overlap and low net progress.
  // This is a signal for an external coordinator, not an automatic stop.

  recent_exports = exports_in_window(ws_id, window)
  if count(recent_exports) < N: return none

  overlaps = pairwise_overlap(recent_exports)
  if median(overlaps) > tau_overlap and net_progress(ws_id, window) < eps:
    return signal("oscillation_suspected")
```

### Algorithm 64: WORKSPACE_GC

```pseudo
WORKSPACE_GC(ws_id):
  // Only for closed workspaces or expired TTL.
  // Preserve audit log pointers, remove bulk graph payload.
  compact event log; drop scratch-only regions; keep exported capsules and commit envelopes.
```


### Algorithm 39: Factor learning in sleep

```pseudo
function LEARN_FACTORS(epoch e):
  X = SAMPLE_CANONICAL_VECTORS(e)              // token canonical x_i
  (D, Enc) = TRAIN_SPARSE_AUTOENCODER(X)       // x ≈ D a, a sparse
  STORE_FACTOR_DICT(D, Enc, version=e)
```

Basis: sparse coding style factorization.

### Algorithm 40: Module mining from pattern graphs

```pseudo
function MINE_MODULES(patterns P):
  C = CANDIDATE_SUBGRAPHS(P)                   // frequent motifs + stable interfaces
  M = {}
  for cand in C:
    gain = MDL_GAIN_WITH_MODULE(cand)
    if gain > 0:
      M.add(cand)
  PROMOTE_TOP_MODULES(M)
  return M
```

### Algorithm 41: Build pattern functionality profiles

```pseudo
function BUILD_PROFILES(pattern_instances I, Enc):
  for inst in I:
    a = Enc( CANONICAL_VECTOR(inst.macro_node) )
    UPDATE_FACTOR_PROFILE(inst.pattern_id, a)
    UPDATE_CONTEXT_PROFILE(inst.pattern_id, inst.neighborhood_types)
    UPDATE_EFFECT_PROFILE(inst.pattern_id, DELTA_ENERGY(inst))
```

### Algorithm 42: Idea proposal via substitution and hybridization

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

### Algorithm 43: Simulate and validate an idea candidate

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

## Algorithm 44 — MANIFOLD_UPDATE_LOCAL (online)

Incremental manifold updates after events, without global regeneration.

```pseudo
function MANIFOLD_UPDATE_LOCAL(view, event ev):
  APPLY_EVENT_TO_OVERLAY(ev)                    // append-only log; overlay materialization



  S = LOCAL_SCOPE(ev)                           // bounded neighborhood
  X0 = READ_X(view.epoch_id, view.hyp_id)       // warm start

  // update effective weights in S
  UPDATE_GATES_AND_ROBUST_WEIGHTS(S)

  // few-step IRLS / relaxation in S only
  for t in 1..T_local:
    X_S = SOLVE_LOCAL_SDD(W_eff, A, M, S, warm_start=X0)

  UPDATE_DIAGNOSTICS(S)
  UPDATE_INDICES_DELTAS(S)
  UPDATE_CHARTS_DELTAS(S)
```

Implementation notes (optional accelerators):

* warm-started iterative solves are the baseline
* rank-k Cholesky update/downdate is an optional accelerator when the sparsity pattern is stable
  UPDATE_INDICES_DELTAS(S)
  UPDATE_CHARTS_DELTAS(S)
```

Implementation notes (optional accelerators):

* warm-started iterative solves are the baseline
* rank-k Cholesky update/downdate is an optional accelerator when the sparsity pattern is stable

## Algorithm 45 — CHART_BUILD (incremental)

```pseudo
function CHART_BUILD(view, nodes S, m):
  for i in S:
    N = NEIGHBORHOOD(i)
    C = Σ_{j in N} W_eff(i,j) * (X[j]-X[i]) (X[j]-X[i])^T
    U, evals = TOP_EIGENVECTORS(C, m)
    STORE TangentFrame(i, view.hyp_id, U, evals, built_lsn=view.lsn_end)
```

## Algorithm 46 — BUILD_CONNECTION_LAPLACIAN (incremental)

```pseudo
function BUILD_CONNECTION_LAPLACIAN(view, nodes S):
  for each edge (i,j) touching S:
    Ui = FRAME(i)
    Uj = FRAME(j)

    // Procrustes alignment
    R_ij = ORTHOGONAL_PROCRUSTES(Ui, Uj)
    STORE EdgeTransport(edge(i,j), R_ij, weight=W_eff(i,j))

  UPDATE_CONNECTION_OPERATOR(view.hyp_id)
```

## Algorithm 47 — PROJECT_VECTOR_FIELDS (manifold → usable vectors)

Provides stable “direction vectors” by operating in the transported tangent bundle.

```pseudo
function PROJECT_VECTOR_FIELDS(view, scalar field S):
  for i:
    v_i = 0
    for j in N(i):
      v_i += W_eff(i,j) * (S(j) - S(i)) * R_ij^T * one
    v_i = NORMALIZE(v_i)
  return v
```

Optional: smooth the vector field by solving a connection Laplacian system:

```pseudo
function SMOOTH_VECTOR_FIELD(view, v, λ):
  // (L_conn + λI) y = λ v
  y = SOLVE_CONN_SYSTEM(L_conn, v)
  return y
```

## Algorithm 48 — BLEND_COMPUTE (runtime)

```pseudo
function BLEND_COMPUTE(view, query q, recipe R):
  d_q(i)   = ANN_DISTANCE(q_canon, X[i])
  T(i), r(i), u(i), var(i) = DIAGNOSTICS(i)
  risk(i)  = RISK_LAYER(i, view)
  nov(i)   = NOVELTY(i, view)

  score(i) = Σ_k R.weight[k] * field_k(i)

  if R.requires_gradient:
    grad(i) = PROJECT_VECTOR_FIELDS(view, score)

  return CompositeField(view, R, score, grad)
```

## Algorithm 49 — MANIFOLD_TO_GRAPH_PROPOSALS (pullback)

Detect “geometric wormholes” and propose auditable bridges/rules.

```pseudo
function MANIFOLD_TO_GRAPH_PROPOSALS(view, budget):
  props = []
  for i in HIGH_VALUE_NODES(view):
    nn = ANN_KNN(X[i], K)
    for j in nn:
      if GEOM_CLOSE(i,j) and STRUCTURALLY_FAR(i,j):
        bundle = COMPILE_EVIDENCE(i,j)
        gain   = ESTIMATE_GAIN(bundle)
        risk   = ESTIMATE_RISK(bundle)
        if gain > TH and risk < CAP:
          props.add(MAKE_PROPOSAL(i,j,bundle,gain,risk))
  return TOPK(props, budget)
```

## Algorithm 50 — FORCE_TO_TOPOLOGY_PROMOTION (governed)

Turns persistent, reproduced utility into topology, without collapsing diagnostics.

```pseudo
function FORCE_TO_TOPOLOGY_PROMOTION(prop):
  if prop.risk_tags high: return QUARANTINE

  if NOT REPRODUCED(prop, N_runs):
    return KEEP_EPHEMERAL

  if NOT STABLE_ACROSS_EPOCHS(prop, K_epochs):
    return KEEP_AS_HYPOTHESIS

  if violates_guardrails(prop):
    return REJECT

  return SUBMIT_TO_2SC(prop)     // validation -> commit -> epoch publish
```

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

## Lean1 Existence and uniqueness of the field solution

**Claim C1.** If (\alpha_i + \mu_i > 0) for every connected component, then (\mathcal{E}(X)) has a unique minimizer.

**Sketch**

* (\mathcal{E}(X)) is a sum of convex quadratics in (X).
* The Hessian in each dimension is (Q = L + A + M).
* (L) is positive semidefinite.
* (A+M) contributes positive diagonal mass on anchored nodes.
* That makes (Q) positive definite on each connected component that has at least one anchored node, so the quadratic is strictly convex, so the minimizer is unique.
* The linear system ((L+A+M)X = AB) has a unique solution.

This is standard for Laplacian-regularized objectives and Gaussian field style constructions.

## Lean2 Energy decreases under relaxation, convergence on fixed graph

**Claim C2.** The update
[
x_i \leftarrow \frac{\alpha_i b_i + \sum_j w_{ij} x_j}{\alpha_i + \mu_i + \sum_j w_{ij}}
]
monotonically decreases (\mathcal{E}) when updating one node at a time with others fixed. Repeating converges to the unique minimizer.

**Sketch**

* (\mathcal{E}) is quadratic and separable per node when holding neighbors fixed.
* The update sets (x_i) to the exact minimizer of (\mathcal{E}) restricted to coordinate block (i).
* Block coordinate descent on a strictly convex quadratic decreases energy each step and converges to the unique minimizer.

## Lean3 Noise attenuation, directions become more reliable

**Claim C3.** Under the model (b = s + \varepsilon), with zero-mean iid noise and a smoothness prior where neighboring nodes share similar (s), the field solution (x) has lower expected error than (b) along high-frequency graph modes.

**Sketch**

* In one dimension, the solution is linear: (x = (L+A+M)^{-1}A b = S b).
* In the Laplacian eigenbasis, this is a low-pass graph filter with transfer function roughly (h(\lambda)=\alpha/(\alpha+\lambda+\mu)).
* High-frequency components have large (\lambda), so (h(\lambda)) shrinks those components.
* If noise injects energy broadly, high-frequency noise gets attenuated more than the low-frequency signal.
* So expected MSE decreases in regimes where the signal is graph-smooth and noise is less graph-smooth.

This is graph filtering language from graph signal processing.

## Lean4 Tier caps bound compute and memory

**Claim C4.** If tier caps ((K,M,N)) are enforced, then:

* Field updates cost (O(d \cdot |E_{local}|)) with (|E_{local}|) bounded by tier neighborhood size.
* Focus and active tier latency is bounded independent of total corpus size.
* Total memory in RAM is (O((K+M+N)\cdot d + |E_{RAM}|)).

**Sketch**

* All RAM operations are restricted to capped tiers.
* Inactive tier lives on disk and is accessed via ANN and edge lookups.

### P1C1 Evidence permanence

Evidence permanence holds under all operations.

### P1C2 Unique field minimizer

Gated quadratic field per hypothesis has a unique minimizer under the same anchoring condition as v0.1.

### P1C3 Field relaxation convergence

Field relaxation converges per hypothesis.

### P1C4 Persistent conflict durability

Persistent conflict produces a durable ambiguity artifact (ConflictRecord or Hypothesis branch).

### P1C5 Robust loss convergence

Robust loss reduces influence of large disagreements while preserving convergence to a minimizer.

### P1C1 proof sketch

By construction:

* all raw spans remain in the raw store referenced by `SpanRef`
* each node creation writes an `ObservationRecord`
* each derived update appends to event log
* node states append to `NodeState` history
* merges and splits create alias edges and lineage pointers

Therefore any current state and any prior state is reconstructible from the append-only log plus raw store.

### P1C2 and P1C3 proof sketch

For a fixed hypothesis (h), gated quadratic energy remains strictly convex when (\alpha_i + \mu_i > 0) per connected component.
The matrix (Q = L_g + A + M) stays SPD.
Coordinate descent decreases energy and converges to the unique minimizer.

This is the same style of argument used for harmonic energy minimization on graphs.

### P1C4 proof sketch

Conflict scores derive from residual and tension.
If tension remains above threshold after validator updates and local relaxation, the policy triggers branching.
Since branching is append-only and the conflict record persists, ambiguity becomes durable.

### P2C1 Snapshot consistency

Snapshot created at LSN (l_0) defines a consistent view.

Sketch:

* Event log defines a total order of mutations.
* Snapshot at (l_0) reads all events (\le l_0).
* MVCC snapshot isolation gives a consistent read view that stays stable while writes continue.

### P2C2 Non-blocking commit

Atomic pointer swap gives epoch-level consistency for readers.

Sketch:

* Readers dereference one global epoch pointer at entry.
* All reads use that epoch's stores and indices.
* Writer publishes new epoch by atomic swap.
* RCU grace period ensures old epoch memory remains valid for all readers started before swap.

### P2C3 IRLS descent

Each IRLS iteration decreases \(\mathcal{E}\).

Sketch for Huber:

* IRLS weight construction corresponds to a majorization of the robust term.
* The surrogate \(\tilde{\mathcal{E}}^{(k)}\) satisfies:

  * \(\tilde{\mathcal{E}}^{(k)}(X) \ge \mathcal{E}(X)\) for all \(X\)
  * \(\tilde{\mathcal{E}}^{(k)}(X^{(k)}) = \mathcal{E}(X^{(k)})\)
* Minimizing the surrogate gives:
  \[
  \mathcal{E}(X^{(k+1)}) \le \tilde{\mathcal{E}}^{(k)}(X^{(k+1)}) \le \tilde{\mathcal{E}}^{(k)}(X^{(k)}) = \mathcal{E}(X^{(k)})
  \]
  This is MM logic.

### P2C4 Convergence to a stationary point

Sketch:

* MM descent yields a monotone non-increasing objective sequence.
* (\mathcal{E}) is bounded below, so objective values converge.
* Under standard MM conditions (continuity, proper majorizer, tangency), every limit point of ({X^{(k)}}) is a stationary point.
* If (\rho) is convex (Huber), then (\mathcal{E}) is convex, so the stationary point is a global minimizer.

References for MM stationary point behavior and MM in signal processing.

### P2C5 No evidence loss

Sketch:

* Consolidation creates a new epoch and new node states.
* It leaves ObservationRecords, prior NodeStates, ConflictRecords, hypotheses, and the event log intact.
* Therefore any prior world state can be reconstructed by choosing an older epoch or replaying events.

Event sourcing is the established pattern for this audit and replay property.

## P5C1 Multi-view canonical field solve exists and is unique

With anchors (\bar{b}_i) and (\alpha_i+\mu_i>0) per connected component, the canonical quadratic system remains SPD. Uniqueness follows the same argument as earlier field proofs, since the only change is the anchor target, not the Hessian structure.

Proof obligation in Lean:

* show SPD of (L + A + M)
* show unique minimizer exists

## P5C2 Rewrite steps preserve evidence permanence

Each rewrite emits tokens with provenance pointers and leaves raw spans untouched. Rule application is append-only over epoch views and event log. Expansion from tokens back to spans remains possible by construction.

Proof obligation in Lean:

* inductive invariant over events: every token has a path to some ObservationRecord or is marked structural-only and tied to anchor nodes

## P5C3 Packed forest representation preserves derivations

For the string case, packed forests and graph-structured stacks are standard ways to share substructure and represent ambiguity compactly in GLR style parsing.
For graph grammars, completeness depends on grammar restrictions and parsing algorithm. HRG parsing has known polynomial-time recognition under restrictions, and general cases can be hard.

Spec requirement:

* grammar classes used online must satisfy a “uniform parsing budget” policy
* heavy grammars run in sleep-time or under strict scope limits

## P5C4 Orthogonal adapter preserves geometry

If (A_v) is orthogonal, then (|A_v x - A_v y| = |x-y|). This gives stable similarity across mapped spaces. Procrustes-based alignment provides a practical way to fit such maps.

Lean target:

* prove distance preservation for orthogonal matrices
* prove the Procrustes minimizer exists under standard assumptions, optional

### P6C1 Workspace isolation

**Claim.** LTM mutates only by commit events.
**Sketch.**

* HWS writes into overlay views.
* Commit controller is the only path that emits LTM events.
* Event log is append-only.

### P6C2 Snapshot consistency

**Claim.** Readers obtain a stable view \(G^{\(e\)}\) while commits create \(G^{(e+1)}\).
**Sketch.**

* MVCC style: writers create new versions, readers keep old.
* Equivalent discipline is described by snapshot isolation.

### P6C3 Safe reclamation

**Claim.** Old epochs are reclaimed after all readers leave, via grace periods.
**Sketch.**

* Track reader epochs.
* Reclaim when min reader epoch advances past reclaim target, same pattern as RCU grace periods.

### P6C4 Surprise budget prevents calcification by construction

**Claim.** High-provenance disruptive evidence cannot be suppressed purely by robust downweighting once clamped, it either forces branching or forces re-anchoring in some hypothesis.
**Sketch.**

* Weight clamp ensures it continues contributing to the objective.
* If conflict persists, solver yields high tension.
* Policy forces branch or re-anchor when tension and provenance exceed thresholds.

### P6C5 Grammar promotion controls error

**Claim.** Beta posterior gating yields bounded promotion risk under the assumed win/loss observation model.
**Sketch.**

* Same as P4 promotion proof pattern.

### P6C6 Adapter rollout is safe under canary plus rollback

**Claim.** Rollout can be limited to fraction (f) and reverted on regression.
**Sketch.**

* Canarying is a standard safety pattern for deployments.

---

### P7C1 Evidence stays

**Claim.** Every seed, idea, and derived structure links back to spans or anchored graph coordinates.

**Sketch.**

By construction:
* Seeds store provenance lists
* IdeaTokens store anchors
* All derived structure references NoiseSeed or IdeaToken which have provenance

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

### P7C3 Learning progress avoids irreducible noise fixation

**Claim.** A reward based on improvement de-prioritizes regions where prediction error stays high with little improvement.

**Sketch.**

* In purely noisy regions, training yields little reduction in loss, so (LP) stays near zero.
* Scheduler selects seeds with higher (LP), so compute flows toward learnable structure.

This is the core argument in compression progress and learning progress intrinsic motivation work.

### P7C4 Novelty helps coverage

**Claim.** Novelty-driven search supports open-ended discovery and avoids deception by objectives.

**Sketch.**

Novelty search literature demonstrates that novelty as an objective enables discovery of diverse solutions and avoids local optima in deceptive fitness landscapes.

### P7C5 Information gain guides ambiguity resolution

**Claim.** Expected informativeness is a principled selection objective for querying and validation.

**Sketch.**

Information gain maximizes expected reduction in uncertainty about model parameters or hypotheses, providing a principled framework for active learning and inquiry.

Optional guarantee path:

* If the exploration objective satisfies adaptive submodularity, adaptive greedy stays near-optimal.

## Lean5 Core quadratic energy proofs

Lean is a good fit for the quadratic core: uniqueness, strict convexity, and "energy decreases" lemmas. Mathlib already covers a wide range of linear algebra and analysis.

Below is a Lean + mathlib4 skeleton. It targets the key proof obligations. It uses placeholders where you would connect to existing lemmas about positive definiteness and strict convexity.

```lean
/-
Lean + mathlib4 skeleton.
Goal: formalize uniqueness of minimizer for quadratic energy on finite graphs.

This file assumes:
  - a finite set of nodes ι
  - embeddings live in (ι → ℝ^d) or (ι → ℝ) per coordinate
  - energy E(x) = xᵀ Q x - 2 cᵀ x + const
  - Q is symmetric positive definite
-/

import Mathlib.LinearAlgebra.Matrix.Symmetric
import Mathlib.LinearAlgebra.Matrix.PositiveDefinite
import Mathlib.Analysis.Convex.Quadratic
import Mathlib.Analysis.NormedSpace.OperatorNorm

open scoped BigOperators
open Matrix

namespace GraphField

variable {ι : Type} [Fintype ι] [DecidableEq ι]

-- Coordinate-wise view: one embedding dimension at a time.
-- x : ι → ℝ can be represented as a vector over a finite basis.

-- Abstract quadratic form: Q : Matrix ι ι ℝ, c : ι → ℝ
variable (Q : Matrix ι ι ℝ) (c : ι → ℝ)

def energy (x : ι → ℝ) : ℝ :=
  (Matrix.dotProduct x (Q.mulVec x)) - 2 * (Matrix.dotProduct c x)

-- Core theorem: SPD Q gives unique minimizer.
theorem unique_minimizer_of_posDef
    (hQ : Matrix.PosDef Q) :
    ∃! x* : ι → ℝ, ∀ x : ι → ℝ, energy Q c x* ≤ energy Q c x := by
  -- Strategy:
  -- 1) show energy is strictly convex using hQ
  -- 2) strict convexity on a finite-dimensional real vector space gives unique minimizer
  -- 3) minimizer characterized by Q x* = c
  -- mathlib has lemmas connecting PosDef to StrictConvex for quadratic forms
  sorry

-- One-step coordinate descent decreases energy.
-- Needs a definition of the coordinate update operator for node i.
variable (i : ι)

def coordUpdate (x : ι → ℝ) : ι → ℝ := by
  -- implement x with coordinate i replaced by argmin of energy along that coordinate
  -- for quadratic energy, this is closed form
  exact x

theorem energy_decreases_coordUpdate
    (hQ : Matrix.PosDef Q) :
    ∀ x : ι → ℝ, energy Q c (coordUpdate Q c i x) ≤ energy Q c x := by
  -- Strategy:
  -- energy restricted to coordinate i is a 1D strictly convex quadratic
  -- coordUpdate picks its minimizer
  sorry

end GraphField
```

This is the proof "spine" for C1 and C2. After that, you can build the vector-valued version by applying the scalar proof (d) times.

Two tracks: quadratic uniqueness and state machine invariants.

### Lean8 Gated quadratic uniqueness

Gated quadratic uniqueness.

This extends the earlier SPD quadratic lemma. It uses `Matrix.PosDef` from mathlib.

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

Evidence permanence invariants.

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

### Lean6 Lossless compress/expand

```lean
-- Sketch: define a graph, pattern instances with explicit node maps, and prove expand ∘ compress = id.

namespace PatternCompression

structure Graph (V E : Type) where
  edges : E → V × V

structure PatternInstance (V PV : Type) where
  nodeMap : PV → V
  residualEdges : List (V × V)

def compress {V E PV : Type} (G : Graph V E) : List (PatternInstance V PV) := by
  exact []

def expand {V E PV : Type} (I : List (PatternInstance V PV)) : Graph V (V×V) := by
  refine ⟨?edges⟩
  intro e; exact e

theorem expand_compress_id
  {V E PV : Type} (G : Graph V E) :
  expand (compress (V:=V) (E:=E) (PV:=PV) G) = (by
    -- extensional equality proof would go here
    exact G) := by
  sorry

end PatternCompression
```

### Lean7 Monotone failure brake

```lean
namespace FailureBrake

open Real

def brake (η F : ℝ) : ℝ := Real.exp (-η * F)

theorem brake_monotone {η : ℝ} (hη : 0 < η) :
  Monotone (fun F => brake η F) := by
  -- exp(-ηF) is monotone decreasing in F, so this is Antitone;
  -- write the correct lemma as Antitone if preferred.
  sorry

end FailureBrake
```

(When making this formal, use `Antitone` for the decreasing property.)

### Lean10 IRLS descent and stationary point shape

Lean formalization target: one coordinate dimension at a time, finite node set, convex Huber robust objective.

```lean
import Mathlib.Analysis.Convex.Function
import Mathlib.Analysis.SpecialFunctions.Pow
import Mathlib.LinearAlgebra.Matrix.PosDef

open scoped BigOperators
namespace RobustIRLS

variable {ι : Type} [Fintype ι] [DecidableEq ι]

-- A scalar per node. Vector case is d copies.
def huber (δ : ℝ) (r : ℝ) : ℝ :=
  if r ≤ δ then (1/2) * r^2 else δ*r - (1/2)*δ^2

-- Graph objective in scalar form:
-- sum_e w_e * huber(δ_e, |x_i - x_j|) + anchor terms + reg terms
-- This file sketches the proof spine. Details require additional lemmas.

theorem irls_majorizes
  (/* assumptions on δ, eps, weights */) :
  True := by
  -- show surrogate >= objective and tangency at current iterate
  sorry

theorem irls_descent
  (/* assumptions: majorizer property, exact minimization of surrogate */) :
  True := by
  -- prove E(x_{k+1}) ≤ E(x_k)
  sorry

theorem mm_limitpoint_stationary
  (/* assumptions: continuity, bounded below, tangency, majorization */) :
  True := by
  -- standard MM theorem: any cluster point is stationary
  sorry

end RobustIRLS
```

This aligns with the MM descent logic used in MM references.

### Lean11 Snapshot and epoch invariants

Model as an event log plus an epoch pointer.

```lean
namespace EpochSafety

inductive Event
| addNode : Nat → Event
| addEdge : Nat → Event
| addObs  : Nat → Event
| addState : Nat → Event

structure Store where
  applied : Nat → Prop            -- events applied up to lsn
  hasObs  : Nat → Prop
  hasSpan : Nat → Prop

def applyUpTo (s : Store) (lsn : Nat) : Store := s

def snapshotConsistent (s : Store) (lsn : Nat) : Prop :=
  True

def epochPublishSafe : Prop := True

theorem snapshot_consistency :
  ∀ s lsn, snapshotConsistent (applyUpTo s lsn) lsn := by
  intro; trivial

theorem publish_atomic_epoch :
  epochPublishSafe := by
  trivial

end EpochSafety
```

This is a placeholder spine. To make it real, the `Store` and `applyUpTo` definitions encode the log replay semantics and the epoch pointer swap rules.

### Lean12 Distance preservation under orthogonal maps

```lean
import Mathlib.LinearAlgebra.Matrix.Orthogonal
import Mathlib.Analysis.NormedSpace.Basic

namespace CoordMaps

open Matrix

variable {n : Type} [Fintype n] [DecidableEq n]

-- Sketch: for an orthogonal matrix R, show ‖R.mulVec x - R.mulVec y‖ = ‖x - y‖.
theorem orthogonal_preserves_norm
  (R : Matrix n n ℝ) (hR : R.IsOrtho) (x y : n → ℝ) :
  ‖R.mulVec x - R.mulVec y‖ = ‖x - y‖ := by
  -- use inner-product preservation lemmas from IsOrtho
  sorry

end CoordMaps
```

### Lean13 Canonical field uniqueness with multi-view anchors

```lean
import Mathlib.LinearAlgebra.Matrix.PosDef

namespace CanonField

variable {ι : Type} [Fintype ι] [DecidableEq ι]

-- Q = L + A + M is SPD, so quadratic energy has unique minimizer.
theorem canonical_field_unique
  (Q : Matrix ι ι ℝ) (hQ : Matrix.PosDef Q) (bbar : ι → ℝ) :
  ∃! x* : ι → ℝ, True := by
  -- reuse earlier quadratic minimizer theorem shape
  sorry

end CanonField

### Lean14 Event-sourced isolation

```lean
namespace Hippocampus

-- Abstract sketch
inductive Event
| CommitEdge : Nat → Nat → Event
| CommitNode : Nat → Event

structure LTMState where
  edges : Nat → Nat → Prop

def apply_event : LTMState → Event → LTMState := by
  intro s e
  cases e with
  | CommitEdge u v =>
      exact { edges := fun a b => s.edges a b ∨ (a = u ∧ b = v) }
  | CommitNode n =>
      exact s

-- Workspace updates do not call apply_event
theorem workspace_isolation
  (s : LTMState) (ws_updates : Nat) :
  ∃ s' : LTMState, s' = s := by
  exact ⟨s, rfl⟩

end Hippocampus
```

### Lean15 RCU style reclamation condition as a predicate

```lean
namespace Reclaim

def safe_to_reclaim (target_epoch : Nat) (reader_epochs : List Nat) : Prop :=
  ∀ r ∈ reader_epochs, r > target_epoch

theorem reclaim_monotone
  (t : Nat) (rs1 rs2 : List Nat)
  (h : ∀ r ∈ rs2, r ∈ rs1) :
  safe_to_reclaim t rs1 → safe_to_reclaim t rs2 := by
  intro h1 r hr2
  have hr1 : r ∈ rs1 := h r hr2
  exact h1 r hr1

end Reclaim
```

### P10I11 P6 two-stage commit integration

Workspace commits go through ingest + hippocampus decision (commit/branch/quarantine).

### P10I12 P7 exploration integration

Explorers can run in child workspaces; exported traces and subgraphs are reconciled.

### P10I13 P9 manifold integration

Workspaces may optionally run a local field solve for ranking/diagnostics; not required.

### P10I14 No global spawn policy

No global policy for when to spawn children or how to allocate budgets.

### P10I15 No automatic conflict resolution

No automatic resolution of semantic conflict; ambiguity is preserved and surfaced.

### P10I16 No mandatory schema objects

No requirement that the LLM use specific schema objects (idea nodes/facets). Those are allowed but not mandatory.

---

# Non-functionals


### P4I5 Abstraction reduces working-set size

Macro-nodes stand in for repeated subgraphs, while evidence remains in inactive storage.

### P4I6 Expansion is demand-driven

Expand only to token budget and risk profile.

### P4I7 Pattern mining is sleep-time

Runs during global consolidation, amortized.

### P4I8 Online matching is bounded

Local structural match only around focus/active tiers.

### P4I9 Failure memory is prioritized

Prioritized in replay and learning (similar spirit to prioritized replay).

### P4I10 Safe online learning

Keep "policy deltas" small, prefer conservative exploration (safe re-ranking literature is a good template).

### P4I11 Governance is separate

It sits above retrieval/field state and never destroys evidence.

### NFG1 Ingestion performance

Amortized sublinear in corpus size per span.

### P2I1 Field update locality

Local, bounded by tier neighborhoods.

### NFG3 Retrieval latency

Bounded latency with tiered ANN plus graph expansion budget.

### P1I13 Tier-locality storage

Keep Focus, Active, Context in RAM. Keep Inactive on disk, accessed via ANN and edge tables. This is the same design principle as virtual memory and tiered recall systems.

### P1I14 Index structure by tier

HNSW for fast recall in Context. PQ or IVF+PQ for Inactive scale.

### P1I15 Inactive embedding quantization

Store inactive embeddings as int8 PQ codes. Keep only centroids and a small residual cache in RAM.

### P1I16 Edge write batching

Use LSM-style batching for high ingest rates. Periodic compaction merges edge runs.

### P2I2 Local field updates bounded

Per span: relax only within a hop radius determined by tier. Global solve: scheduled offline or during low load, used to reduce drift.

### P2I6 Uncertainty-driven compute

High uncertainty nodes get more validation and more relaxation steps. Low uncertainty nodes get cheap maintenance.

### P1I6 Event-sourced replay

Every mutation is an event. Enables rebuilds, A/B comparisons, and regression debugging.

### P1I7 Raw spans are immutable

Immutable compressed store, dedup by content hash.

### P1I8 ObservationRecord persistence

Float16 or float32 backstore on disk.

### P1I9 ANN store with full backstore

PQ codes for scale and speed, full vector backstore for audits.

### P1I11 Graph edge durability

LSM-backed edge table for high write rates.

### P1I10 NodeState history persistence

RAM keeps current states for Focus, Active, Context. Disk keeps full history, optionally delta-compressed.

### P2I3 Local relaxation bounded

Local relaxation bounded by tier caps.

### P2I4 Conflict resolution strict quotas

Conflict resolution budgeted as a background loop with strict quotas.

### P2I5 Validator rate limiting

Validator calls rate-limited and triggered by tension.

### P1I12 Ingestion hot path

Embed once, add edges, local relax, push conflict candidates. Heavy work runs on the conflict queue.

### P5I3 Grammar class restrictions per tier

Focus and Active: restricted grammars with cheap matching and bounded-degree neighborhoods. Context and Sleep: heavier grammars and deeper matching. Graph grammar parsing complexity varies widely across grammar classes and restrictions.

### P5I4 Match candidate indexing

Index rule LHS patterns by WL-style neighborhood signatures. Use WL hashing to prune match candidates before subgraph matching.

### P5I2 Strict beam width

Strict beam width per region. Packed DAG sharing across hypotheses, similar in spirit to graph-structured stacks for ambiguity.

### P5I5 Coordinate transforms cached

Cache canonical projections (A_v b_i^{(v)}). Refit adapters in sleep-time, then bulk-refresh projections during consolidation.

### P5I6 Domain embedders specialized

Text embedder stays as the semantic anchor. Graph embedder covers topology. Code embedder covers AST and code structure.

### P5I1 Parse forest versioning

Parse forests are versioned by epoch. Old hypotheses compact via P2 sleep cycle, with provenance and failures retained.

---


### P7I7 Exploration hard budgets

Hard budgets: `explore_budget`, `llm_budget`.

### P7I8 Beam limits per seed

Number of hypotheses spawned per seed is limited.

### P7I11 Cheap probes first

Cheap probes first, LLM second.

### P7I12 Forest and overlay reuse

Packed forests reuse (P5), overlays reuse (P6).

### P7I13 Sleep vs online depth

Sleep pass does deeper mining, online pass stays shallow.

### P7I14 Seed compactness

Seeds are compact, mostly metrics plus anchors.

### P7I15 Trace compression

Traces compress into signatures and aggregate stats.

### P7I5 Archived seed queryability

Archived seeds remain queryable for audit.

### P7I9 Governance gating

Risk tags influence whether exploration runs automatically, or requires user branch choice.

### P7I10 High-risk surfaces ambiguity

High-risk seeds can trigger "surface ambiguity" behavior instead of silent repair.

### P7I6 Failure memory blocks loops

Failure memory blocks infinite loops on unproductive seeds.

---

## Comp22 Hippocampal Workspace Store (HWS)

## Comp23 Proposal Gateway (NGW)
for neocortex outputs

## Comp24 Secondary Ingestion Engine (H2)

## Comp25 Commit Controller (2SC)

## Comp26 Curriculum Manager (CURR)

## Comp27 Cold Solve Scheduler (ROOT)

## Comp28 Surprise Budget Manager (SURP)

## Comp29 Connectivity Monitor + Bridge Synthesizer (CONN)

## Comp30 Grammar Sandbox + Rule Promotion (GRAM-SBX)

## Comp31 Adapter Lifecycle Manager (ADAPT)
with drift detection

## Comp32 Inquiry Planner (INQ)
for evidence seeking
