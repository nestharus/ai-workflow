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

### P2C1 Snapshot consistency

Snapshot created at LSN (l_0) defines a consistent view.

Sketch:

* Event log defines a total order of mutations.
* Snapshot at (l_0) reads all events (\le l_0).
* MVCC snapshot isolation gives a consistent read view that stays stable while writes continue. ([Microsoft][1])

---

### P2C2 Non-blocking commit

Atomic pointer swap gives epoch-level consistency for readers.

Sketch:

* Readers dereference one global epoch pointer at entry.
* All reads use that epoch's stores and indices.
* Writer publishes new epoch by atomic swap.
* RCU grace period ensures old epoch memory remains valid for all readers started before swap. ([Kernel.org][6])

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

---

### 7. Event-sourced replay

* Every mutation is an event.
* Enables rebuilds, A/B comparisons, and regression debugging.

---

## Lean4 Tier caps bound compute and memory

**Claim C4.** If tier caps ((K,M,N)) are enforced, then:

* Field updates cost (O(d \cdot |E_{local}|)) with (|E_{local}|) bounded by tier neighborhood size.
* Focus and active tier latency is bounded independent of total corpus size.
* Total memory in RAM is (O((K+M+N)\cdot d + |E_{RAM}|)).

**Sketch**

* All RAM operations are restricted to capped tiers.
* Inactive tier lives on disk and is accessed via ANN and edge lookups.

---

## Comp4 Tiered Memory Manager

(Component definition pending - see plan.md L737)

---

## Comp9 Index Layer

(Component definition pending - see plan.md L747)

---

## Comp10 Telemetry and Replay Log

(Component definition pending - see plan.md L749)

