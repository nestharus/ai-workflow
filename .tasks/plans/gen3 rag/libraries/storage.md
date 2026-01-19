### P1I5 Compression keeps a lossless backstore (=[P1]) [(=P1I5)]

ANN codes and quantized vectors are allowed.
A lossless or near-lossless backstore remains available for re-evaluation and auditing.

---

### P9I1 — Read coherence (=[P9]) [(=P9I1)]

Every request pins a view:

* `epoch_id`
* `lsn_end` (event-log offset)
* `hyp_id`

All reads for the request use that pinned view.

---

### P9I2 — Overlay is always writable (=[P9]) [(=P9I2)]

Ingestion and workspace commits append to the event log continuously. The overlay applier may lag, but never blocks writes.

---

### Algorithm 66: Apply deltas after snapshot [(=Algorithm 66)]

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

### Algorithm 67: Publish epoch with RCU semantics [(=Algorithm 67)]

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

## Algorithm 51 — CONTINUOUS_SLEEP_NO_DOWNTIME [(=Algorithm 51)]

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

### P6C3 Safe reclamation [(=P6C3)]

**Claim.** Old epochs are reclaimed after all readers leave, via grace periods.
**Sketch.**

* Track reader epochs.
* Reclaim when min reader epoch advances past reclaim target, same pattern as RCU grace periods.

---

### P1I6 Event-sourced replay [(=P1I6)]

Every mutation is an event. Enables rebuilds, A/B comparisons, and regression debugging.

---

### P1I7 Raw spans are immutable [(=P1I7)]

Immutable compressed store, dedup by content hash.

---

### P1I8 ObservationRecord persistence [(=P1I8)]

Float16 or float32 backstore on disk.

---

### P1I9 ANN store with full backstore [(=P1I9)]

PQ codes for scale and speed, full vector backstore for audits.

---

### P1I10 NodeState history persistence [(=P1I10)]

RAM keeps current states for Focus, Active, Context. Disk keeps full history, optionally delta-compressed.

---

### P1I11 Graph edge durability [(=P1I11)]

LSM-backed edge table for high write rates.

---

### P1I13 Tier-locality storage [(=P1I13)]

Keep Focus, Active, Context in RAM. Keep Inactive on disk, accessed via ANN and edge tables. This is the same design principle as virtual memory and tiered recall systems.

---

### P1I14 Index structure by tier [(=P1I14)]

HNSW for fast recall in Context. PQ or IVF+PQ for Inactive scale.

---

### P1I15 Inactive embedding quantization [(=P1I15)]

Store inactive embeddings as int8 PQ codes. Keep only centroids and a small residual cache in RAM.

---

### P1I16 Edge write batching [(=P1I16)]

Use LSM-style batching for high ingest rates. Periodic compaction merges edge runs.

---

## G4 Bounded working set [(=G4)]

* Explicit focus, active, contextual, inactive tiers with promotion and demotion.

---

## G40 Zero downtime sleep [(=G40)]

* Consolidation runs continuously.
* Overlay remains writable.
* No downtime for reads or writes.
---

## D4 ANN indices [(=D4)]

Separate indices per tier and per embedding kind.

* Focus and Active: brute force scan or small HNSW.
* Context: HNSW for x vectors.
* Inactive: IVF+PQ or HNSW+PQ depending on scale.

---

## D5 Event log [(=D5)]

Append-only ingestion events for replay:

```
Event {
  t: Time
  kind: AddNode | AddEdge | UpdateEdgeWeight | Promote | Demote | Reembed | MergeIdea | SplitIdea
  payload: bytes
}
```

## D11 Epoch [(=D11)]

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

## D12 Snapshot [(=D12)]

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

## D14 IndexVersion [(=D14)]

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

## D15 ConsolidationJob [(=D15)]

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

---

---

---


---

---

### Algorithm 9: Global Consolidation [(=Algorithm 9)]

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

Event sourcing stays the audit layer that makes rebuilds reproducible. ([Microsoft Learn][7])

#### Notes on BUILD_INDICES

This is a versioned build, then swap. The Lucene style segment approach is a practical reference point for "build new segments, then open them" behavior. ([Mike McCandless Blog][8])

---

---

## Comp4 Tiered Memory Manager [(=Comp4)]

(Component definition pending - see plan.md L737)

---

## Comp9 Index Layer [(=Comp9)]

(Component definition pending - see plan.md L747)

---

## Comp10 Telemetry and Replay Log [(=Comp10)]

(Component definition pending - see plan.md L749)

---

## C4 Tier promotion logic bounds RAM and compute [(=C4)]

Independent of total corpus size.

---

## Algorithm 8: Hypothesis branching [(=Algorithm 8)]

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

### P2C1 Snapshot consistency [(=P2C1)]

Snapshot created at LSN (l_0) defines a consistent view.

Sketch:

* Event log defines a total order of mutations.
* Snapshot at (l_0) reads all events (\le l_0).
* MVCC snapshot isolation gives a consistent read view that stays stable while writes continue. ([Microsoft][1])

---

---

### P2C2 Non-blocking commit [(=P2C2)]

Atomic pointer swap gives epoch-level consistency for readers.

Sketch:

* Readers dereference one global epoch pointer at entry.
* All reads use that epoch's stores and indices.
* Writer publishes new epoch by atomic swap.
* RCU grace period ensures old epoch memory remains valid for all readers started before swap. ([Kernel.org][6])

---

## T14 Notes on BUILD_INDICES [(=T14)]
