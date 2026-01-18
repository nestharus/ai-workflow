# Storage Library

Versioned snapshots, epochs, indexes, atomic commits, MVCC semantics.

### P1I5 Compression keeps a lossless backstore

ANN codes and quantized vectors are allowed.
A lossless or near-lossless backstore remains available for re-evaluation and auditing.

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

---

### Algorithm 67: Publish epoch with RCU semantics

```pseudo
function PUBLISH_EPOCH(epoch_new):
  epoch_new.status = ready
  ATOMIC_SWAP(GLOBAL_EPOCH_PTR, epoch_new.epoch_id)
  epoch_new.status = active

  // grace period before reclaim of old epochs
  WAIT_GRACE_PERIOD()
```

RCU provides the pattern: readers run lock-free against a stable snapshot while writer swaps the pointer then waits a grace period before reclaim. ([Kernel.org][6])

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

### P6C3 Safe reclamation

**Claim.** Old epochs are reclaimed after all readers leave, via grace periods.
**Sketch.**

* Track reader epochs.
* Reclaim when min reader epoch advances past reclaim target, same pattern as RCU grace periods.

---

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

---

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

```
```

---

### P1I6 Event-sourced replay

Every mutation is an event. Enables rebuilds, A/B comparisons, and regression debugging.

---

### P1I7 Raw spans are immutable

Immutable compressed store, dedup by content hash.

---

### P1I8 ObservationRecord persistence

Float16 or float32 backstore on disk.

---

### P1I9 ANN store with full backstore

PQ codes for scale and speed, full vector backstore for audits. ([ACM Digital Library][5])

---

### P1I10 NodeState history persistence

RAM keeps current states for Focus, Active, Context. Disk keeps full history, optionally delta-compressed.

---

### P1I11 Graph edge durability

LSM-backed edge table for high write rates. ([UMass Boston CS][6])

---

### P1I12 Ingestion hot path

Embed once, add edges, local relax, push conflict candidates. Heavy work runs on the conflict queue.

---

### P1I13 Tier-locality storage

Keep Focus, Active, Context in RAM. Keep Inactive on disk, accessed via ANN and edge tables. This is the same design principle as virtual memory and tiered recall systems.

---

### P1I14 Index structure by tier

HNSW for fast recall in Context. PQ or IVF+PQ for Inactive scale.

---

### P1I15 Inactive embedding quantization

Store inactive embeddings as int8 PQ codes. Keep only centroids and a small residual cache in RAM.

---

### P1I16 Edge write batching

Use LSM-style batching for high ingest rates. Periodic compaction merges edge runs.

---

## G4 Bounded working set

* Explicit focus, active, contextual, inactive tiers with promotion and demotion.

---

## G40 Zero downtime sleep

* Consolidation runs continuously.
* Overlay remains writable.
* No downtime for reads or writes.
---

## D4 ANN indices

Separate indices per tier and per embedding kind.

* Focus and Active: brute force scan or small HNSW.
* Context: HNSW for x vectors.
* Inactive: IVF+PQ or HNSW+PQ depending on scale.

---

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

---

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

---

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

---

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

---

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

---

## 1. Tier-locality as the main speed lever

* Keep Focus, Active, Context in RAM.
* Keep Inactive on disk, accessed via ANN and edge tables.

This is the same design principle as virtual memory and tiered recall systems.

---

## 2. Separate indices by tier and by embedding kind

* HNSW for fast recall in Context.
* PQ or IVF+PQ for Inactive scale.

---

## 3. Quantize aggressively outside Focus

* Store inactive embeddings as int8 PQ codes.
* Keep only centroids and a small residual cache in RAM.

---

## 4. Batch edge writes, defer compaction

* Use LSM-style batching for high ingest rates.
* Periodic compaction merges edge runs.

---

## 5. Local field updates, global re-solves rarely

* Per span: relax only within a hop radius determined by tier.
* Global solve: scheduled offline or during low load, used to reduce drift.

---

## Storage strategy

* Raw spans: immutable compressed store, dedup by content hash
* ObservationRecord: float16 or float32 backstore on disk
* ANN store: PQ codes for scale and speed, full vector backstore for audits ([ACM Digital Library][5])
* Graph edges: LSM-backed edge table for high write rates ([UMass Boston CS][6])
* NodeState history:

  * RAM keeps current states for Focus, Active, Context
  * disk keeps full history, optionally delta-compressed

---

## Memory and compaction

* Parse forests are versioned by epoch.
* Old hypotheses compact via P2 sleep cycle, with provenance and failures retained.

---

## Memory

* Seeds are compact, mostly metrics plus anchors
* Traces compress into signatures and aggregate stats
* Archived seeds remain queryable for audit

---

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

Snapshot isolation is the foundation for the consistent snapshot step. ([Microsoft][1])
Atomic publish semantics follow RCU style "publish pointer, wait grace period, reclaim old." ([Kernel.org][6])

Event sourcing stays the audit layer that makes rebuilds reproducible. ([Microsoft Learn][7])

#### Notes on BUILD_INDICES

This is a versioned build, then swap. The Lucene style segment approach is a practical reference point for "build new segments, then open them" behavior. ([Mike McCandless Blog][8])

---

### 7. Event-sourced replay

* Every mutation is an event.
* Enables rebuilds, A/B comparisons, and regression debugging.

---

## Comp4 Tiered Memory Manager

(Component definition pending - see plan.md L737)

---

## Comp9 Index Layer

(Component definition pending - see plan.md L747)

---

## Comp10 Telemetry and Replay Log

(Component definition pending - see plan.md L749)

---

## C4 Tier promotion logic bounds RAM and compute

Independent of total corpus size.

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

---

### P2C1 Snapshot consistency

Snapshot created at LSN (l_0) defines a consistent view.

Sketch:

* Event log defines a total order of mutations.
* Snapshot at (l_0) reads all events (\le l_0).
* MVCC snapshot isolation gives a consistent read view that stays stable while writes continue. ([Microsoft][1])

---

---

### P2C2 Non-blocking commit

Atomic pointer swap gives epoch-level consistency for readers.

Sketch:

* Readers dereference one global epoch pointer at entry.
* All reads use that epoch's stores and indices.
* Writer publishes new epoch by atomic swap.
* RCU grace period ensures old epoch memory remains valid for all readers started before swap. ([Kernel.org][6])

---
