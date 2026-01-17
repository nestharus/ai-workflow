# Workspace Library

Hippocampus workspace, two-stage commit, overlays, LLM workspaces, session management.

---

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


---

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


---

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


---

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


---

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


---

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


---

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



---

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


---

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


---

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


---

### P6.1 Workspace overlay model

Let \(G^{(e)}\) be the long-term graph at epoch \(e\).
HWS stores an overlay \(\Delta G\) such that the workspace view is:
\[
G^{\text{hws}} = G^{(e)} \oplus \Delta G
\]
Reads use \(G^{(e)}\) or \(G^{\text{hws}}\) depending on scope.

This is the same principle as snapshot isolation, readers see a stable snapshot while writers create new versions.


---

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


---

### P10.1 Convergence-safe state model (event-set join)

Represent a workspace state as:

  State(ws) = BaseView + Join(Events(ws))

Where:
* Events(ws) is an append-only set of operations with unique IDs.
* Join is deterministic, commutative, associative, and idempotent (a semilattice join).

This implies: if any two replicas/reconciliations apply the same set of events, they converge to the same state.


---

## P10.2 Workspace graph as a graph CRDT (optional mode)

When a workspace requires deterministic merge semantics under concurrent edits, model the WSG using CRDT components:

* V: a CRDT set of vertices
* E: a CRDT set of edges

To maintain the graph invariant that edges reference existing vertices, use a standard CRDT approach:

* remove-vertex either removes incident edges (remove-wins), or
* add-edge can restore missing vertices (add-wins)

P10 defaults to remove-wins for safety in a workspace (deleting a node removes its edges), implemented with tombstones.


---

## P10.3 Delta-state replication for workspaces (optional)

Workspaces may sync their event logs as deltas rather than full states. This is compatible with delta-state CRDT designs where small delta fragments are joined into the replica state.


---

## P10.4 Overlap as near-duplicate detection

Overlap between two capsules/regions is estimated using a multi-stage signature:

1) Structure hash: WL-style hashing over labeled neighborhoods
2) Set resemblance: MinHash sketch over structural shingles
3) Cosine-like similarity: SimHash over embedded shingles

This supports fast approximate overlap queries over many workspaces.
---


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


---

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


---

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


---

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


---

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


---

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


---

### Algorithm 58: MESSAGE_SEND

```pseudo
MESSAGE_SEND(from_ws, to_ws, cap, note):
  cap.hop_trace.append(to_ws)
  msg = WorkspaceMessage(from_ws, to_ws, cap, note)
  MSG.deliver(msg)
```


---

### Algorithm 59: RECONCILE_CHILD_TO_PARENT

```pseudo
RECONCILE_CHILD_TO_PARENT(parent_ws, child_ws, selection_spec):
  cap = EXPORT_CAPSULE(child_ws, selection_spec)
  overlap = OVERLAP_QUERY(parent_ws, cap.fingerprint)

  // RECON does not decide policy; it only computes signals.
  rec = ReconcileRecord(parent_ws, child_ws, cap.capsule_id, overlap)
  return rec, cap
```


---

### Algorithm 60: COMMIT_TO_INGEST (no LLM diffs)

```pseudo
COMMIT_TO_INGEST(ws_id, exported_capsules, intent):
  payload = BUILD_GRAPH_PAYLOAD(ws_id, exported_capsules)
  env = WorkspaceCommitEnvelope(ws_id, payload, base_epoch, base_lsn_end)
  CGW.submit_to_ingest(env)
  return env
```


---

### Algorithm 61: OVERLAP_SIGNATURE (structure + content)

```pseudo
OVERLAP_SIGNATURE(subgraph):
  wl_hash  = WL_HASH(subgraph, iterations = k)
  shingle_set = SHINGLES(subgraph)                // labels, edge types, local WL labels
  minhash = MINHASH(shingle_set)
  simhash = SIMHASH(EMBED(shingle_set))
  return {wl_hash, minhash, simhash}
```


---

### Algorithm 62: OVERLAP_DETECT

```pseudo
OVERLAP_DETECT(fingerprint_a, fingerprint_b):
  // fast filters
  if HAMMING(simhash_a, simhash_b) > H: return low_overlap

  // approximate set similarity
  j_hat = MINHASH_ESTIMATE(minhash_a, minhash_b)
  return j_hat
```


---

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


---

### Algorithm 64: WORKSPACE_GC

```pseudo
WORKSPACE_GC(ws_id):
  // Only for closed workspaces or expired TTL.
  // Preserve audit log pointers, remove bulk graph payload.
  compact event log; drop scratch-only regions; keep exported capsules and commit envelopes.
```



---

### Algorithm 40

Module mining from pattern graphs

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


---

### Algorithm 41

Build pattern functionality profiles

```pseudo
function BUILD_PROFILES(pattern_instances I, Enc):
  for inst in I:
    a = Enc( CANONICAL_VECTOR(inst.macro_node) )
    UPDATE_FACTOR_PROFILE(inst.pattern_id, a)
    UPDATE_CONTEXT_PROFILE(inst.pattern_id, inst.neighborhood_types)
    UPDATE_EFFECT_PROFILE(inst.pattern_id, DELTA_ENERGY(inst))
```


---

### Algorithm 42

Idea proposal via substitution and hybridization

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


---

## G22 Hippocampus workspace is first-class

* Hippocampus runs a fast, branching workspace graph, separate from long-term memory.

---

## G23 Two-stage commit

* Neocortex outputs proposals.
* Hippocampus re-ingests, re-parses, re-solves, then commits or quarantines.

---

## G42 Workspace is first-class

* A workspace is an addressable object with a stable ID, base snapshot, and event log.

---

## G43 Structured lifetime (parent closes children)

* Child workspaces cannot outlive their parent.
* Cancellation and closure propagate down the tree.

---

## G44 Fork-join parallel thought

* A parent workspace can spawn many children.
* Children can run independently and export results for reconciliation.

---

## G45 Capsules and messages

* Workspaces exchange information as portable subgraph capsules with manifests, lineage, and fingerprints.

---

## G46 Commit via ingest (no LLM diffs)

* The LLM does not compute deltas.
* The workspace submits graph-form artifacts to ingest; ingest computes canonicalization, conflicts, and candidates.

---

## G47 Overlap detection across workspaces

* Detect overlap and near-duplication across all open workspaces.
* Enable loop/oscillation detection and dedup.

---

## G48 Convergence-safe merge primitives

* Provide deterministic, idempotent merge building blocks (CRDT-style joins where applicable).
* Where semantic conflict exists, preserve ambiguity instead of overwriting.

---

## G49 Bounded view compilation

* Provide a deterministic mechanism to compile a bounded view of a large workspace into a context window.
* The LLM can expand/contract the view by manipulating focus pointers in the workspace.

---

## G50 Observability and budgets

* Every workspace operation is logged.
* Quotas bound memory growth, fanout, and commit volume.


---

## P10 core operations (tooling surface)

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

---

## P6 math

## P6.1 Workspace overlay model

Workspace overlays base epoch with copy-on-write semantics for nodes and edges.

## P6.2 Two-stage commit as an admissibility filter

Proposals from hippocampus go through tension and provenance checks before entering neocortex.

## P6.3 Surprise budget as forced retention of high-provenance tension

High-provenance disagreements are marked and not silently resolved.

## P6.4 Connectivity targets

Graph maintains connectivity bounds to prevent fragmentation.

## P6.5 Adapter drift detection

Monitor embedding adapter fit error over time to detect distribution shift.

---

## P10 math

## P10.1 Convergence-safe state model (event-set join)

Workspaces use event-sourced state with deterministic merge semantics.

## P10.2 Workspace graph as a graph CRDT (optional mode)

For distributed collaboration, workspaces can use CRDT semantics.

## P10.3 Delta-state replication for workspaces (optional)

Efficient synchronization via delta-state propagation.

## P10.4 Overlap as near-duplicate detection

Detect overlapping or redundant work across workspaces using content signatures.

---

## P6 goals

* G22: Hippocampus workspace is first-class
* G23: Two-stage commit
* G24: Low path dependence
* G25: Paradigm shift support
* G26: Graph stays traversable
* G27: Grammar evolution is safe
* G28: Multi-coordinate adapters are governable
* G29: Hippocampus actively seeks evidence

---

## P6 components

1. **Hippocampal Workspace Manager**
2. **Neocortex Commit Gate**
3. **Curriculum Controller**
4. **Cold Solver and Re-rooting Engine**
5. **Surprise Budget Tracker**
6. **Connectivity Guard**
7. **Grammar Sandbox**
8. **Adapter Lifecycle Manager**
9. **Inquiry Planner**

---

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

---

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

---

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


---

### P6I1 Workspace isolation

* HWS changes do not mutate long-term memory (LTM) directly.
* LTM changes only via commit events.

---

### P6I2 Evidence permanence

* Every committed memory object traces to evidence, or is flagged "structural-only" and linked to anchored objects.

---

### P6I3 Snapshot reads

* Readers see a stable epoch snapshot.
* Writers create overlays and commit new epochs, similar to MVCC / snapshot isolation.

---

### P6I4 Safe reclamation

* Old snapshots are reclaimed after a grace period, similar to RCU.

---

### P6I5 Governance never discards ambiguity

* Ambiguities may be hidden from UI by policy, yet remain in the ambiguity ledger with risk metadata.


---

### P10I1 Isolation

* Workspace edits never directly mutate LTM.

---

### P10I2 Snapshot base

* Each workspace pins a base LTM snapshot (epoch_id, lsn_end) for read coherence.

---

### P10I3 Structured concurrency closure

* If a workspace closes, all descendants close.

---

### P10I4 Idempotent import/export

* Importing the same capsule twice has no effect beyond the first import.

---

### P10I5 Loop-free capsule routing

* A workspace rejects any capsule whose hop-trace already contains that workspace.

---

### P10I6 Convergence of replicated workspace state

* If two replicas of a workspace (or two reconciliation runs) apply the same set of workspace events, they converge to the same WSG state.

---

### P10I7 Partial persistence

* Only explicitly exported regions may be submitted to ingest.
* Private scratch content may remain uncommitted and is GC-able.

---

### P10I8 Overlap registry monotonicity

* Fingerprints and lineage records are append-only within a workspace session.

---

### P10I9 Risk and provenance propagate

* Workspace-created objects are marked either provenance-anchored or structural-only.
* Risk tags propagate with capsules and commit envelopes.

---

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

## Comp22 Hippocampal Workspace Store (HWS)

---

## Comp23 Proposal Gateway (NGW)

for neocortex outputs

---

## Comp25 Commit Controller (2SC)


---

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
