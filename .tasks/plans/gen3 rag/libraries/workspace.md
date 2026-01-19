### D39 Workspace [(=D39)]

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

### D40 WorkspaceEvent [(=D40)]

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

### D41 WorkspaceGraph [(=D41)]

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

### D42 Capsule [(=D42)]

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

### D43 WorkspaceMessage [(=D43)]

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

### D44 ReconcileRecord [(=D44)]

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

### D45 WorkspaceCommitEnvelope [(=D45)]

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

### D55 HippocampalWorkspace [(=D55)]

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

### D56 NeocortexProposal [(=D56)]

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

### D57 CommitRecord [(=D57)]

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

### P6.1 Workspace overlay model [(=P6.1)]

Let \(G^{(e)}\) be the long-term graph at epoch \(e\).
HWS stores an overlay \(\Delta G\) such that the workspace view is:
\[
G^{\text{hws}} = G^{(e)} \oplus \Delta G
\]
Reads use \(G^{(e)}\) or \(G^{\text{hws}}\) depending on scope.

This is the same principle as snapshot isolation, readers see a stable snapshot while writers create new versions.

### P6.2 Two-stage commit as an admissibility filter [(=P6.2)]

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

### P10.1 Convergence-safe state model (event-set join) [(=P10.1)]

Represent a workspace state as:

  State(ws) = BaseView + Join(Events(ws))

Where:
* Events(ws) is an append-only set of operations with unique IDs.
* Join is deterministic, commutative, associative, and idempotent (a semilattice join).

This implies: if any two replicas/reconciliations apply the same set of events, they converge to the same state.

## P10.2 Workspace graph as a graph CRDT (optional mode) [(=P10.2)]

When a workspace requires deterministic merge semantics under concurrent edits, model the WSG using CRDT components:

* V: a CRDT set of vertices
* E: a CRDT set of edges

To maintain the graph invariant that edges reference existing vertices, use a standard CRDT approach:

* remove-vertex either removes incident edges (remove-wins), or
* add-edge can restore missing vertices (add-wins)

P10 (+[P10]) defaults to remove-wins for safety in a workspace (deleting a node removes its edges), implemented with tombstones.

## P10.3 Delta-state replication for workspaces (optional) [(=P10.3)]

Workspaces may sync their event logs as deltas rather than full states. This is compatible with delta-state CRDT designs where small delta fragments are joined into the replica state.

## P10.4 Overlap as near-duplicate detection [(=P10.4)]

Overlap between two capsules/regions is estimated using a multi-stage signature:

1) Structure hash: WL-style hashing over labeled neighborhoods
2) Set resemblance: MinHash sketch over structural shingles
3) Cosine-like similarity: SimHash over embedded shingles

This supports fast approximate overlap queries over many workspaces.
---

### Algorithm 25: Two-stage commit from neocortex to hippocampus [(=Algorithm 25)]

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

### Algorithm 53: OPEN_WORKSPACE [(=Algorithm 53)]

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

### Algorithm 54: CLOSE_WORKSPACE_CASCADE (structured lifetime) [(=Algorithm 54)]

```pseudo
CLOSE_WORKSPACE_CASCADE(ws_id):
  if ws.status != open: return
  ws.status = closing
  for child in ws.children:
    CLOSE_WORKSPACE_CASCADE(child)
  ws.status = closed
  WGC.schedule(ws_id)
```

### Algorithm 55: SPAWN_CHILD (fork-join) [(=Algorithm 55)]

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

### Algorithm 56: EXPORT_CAPSULE [(=Algorithm 56)]

```pseudo
EXPORT_CAPSULE(ws_id, selection_spec):
  subgraph = EXTRACT_SUBGRAPH(ws_id, selection_spec)
  fp = OVERLAP_SIGNATURE(subgraph)
  cap = Capsule(subgraph, manifest, fp)
  cap.hop_trace = [ws_id]
  log event export_capsule
  return cap
```

### Algorithm 57: IMPORT_CAPSULE (idempotent) [(=Algorithm 57)]

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

### Algorithm 58: MESSAGE_SEND [(=Algorithm 58)]

```pseudo
MESSAGE_SEND(from_ws, to_ws, cap, note):
  cap.hop_trace.append(to_ws)
  msg = WorkspaceMessage(from_ws, to_ws, cap, note)
  MSG.deliver(msg)
```

### Algorithm 59: RECONCILE_CHILD_TO_PARENT [(=Algorithm 59)]

```pseudo
RECONCILE_CHILD_TO_PARENT(parent_ws, child_ws, selection_spec):
  cap = EXPORT_CAPSULE(child_ws, selection_spec)
  overlap = OVERLAP_QUERY(parent_ws, cap.fingerprint)

  // RECON does not decide policy; it only computes signals.
  rec = ReconcileRecord(parent_ws, child_ws, cap.capsule_id, overlap)
  return rec, cap
```

### Algorithm 60: COMMIT_TO_INGEST (no LLM diffs) [(=Algorithm 60)]

```pseudo
COMMIT_TO_INGEST(ws_id, exported_capsules, intent):
  payload = BUILD_GRAPH_PAYLOAD(ws_id, exported_capsules)
  env = WorkspaceCommitEnvelope(ws_id, payload, base_epoch, base_lsn_end)
  CGW.submit_to_ingest(env)
  return env
```

### Algorithm 61: OVERLAP_SIGNATURE (structure + content) [(=Algorithm 61)]

```pseudo
OVERLAP_SIGNATURE(subgraph):
  wl_hash  = WL_HASH(subgraph, iterations = k)
  shingle_set = SHINGLES(subgraph)                // labels, edge types, local WL labels
  minhash = MINHASH(shingle_set)
  simhash = SIMHASH(EMBED(shingle_set))
  return {wl_hash, minhash, simhash}
```

### Algorithm 62: OVERLAP_DETECT [(=Algorithm 62)]

```pseudo
OVERLAP_DETECT(fingerprint_a, fingerprint_b):
  // fast filters
  if HAMMING(simhash_a, simhash_b) > H: return low_overlap

  // approximate set similarity
  j_hat = MINHASH_ESTIMATE(minhash_a, minhash_b)
  return j_hat
```

### Algorithm 63: OSCILLATION_SIGNAL [(=Algorithm 63)]

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

### Algorithm 64: WORKSPACE_GC [(=Algorithm 64)]

```pseudo
WORKSPACE_GC(ws_id):
  // Only for closed workspaces or expired TTL.
  // Preserve audit log pointers, remove bulk graph payload.
  compact event log; drop scratch-only regions; keep exported capsules and commit envelopes.
```


### P6C1 Workspace isolation [(=P6C1)]

**Claim.** LTM mutates only by commit events.
**Sketch.**

* HWS writes into overlay views.
* Commit controller is the only path that emits LTM events.
* Event log is append-only.

### P6C2 Snapshot consistency [(=P6C2)]

**Claim.** Readers obtain a stable view \(G^{\(e\)}\) while commits create \(G^{(e+1)}\).
**Sketch.**

* MVCC style: writers create new versions, readers keep old.
* Equivalent discipline is described by snapshot isolation.

## G42 Workspace is first-class [(=G42)]
* A workspace is an addressable object with a stable ID, base snapshot, and event log.

## G43 Structured lifetime (parent closes children) [(=G43)]
* Child workspaces cannot outlive their parent.
* Cancellation and closure propagate down the tree.

## G44 Fork-join parallel thought [(=G44)]
* A parent workspace can spawn many children.
* Children can run independently and export results for reconciliation.

## G45 Capsules and messages [(=G45)]
* Workspaces exchange information as portable subgraph capsules with manifests, lineage, and fingerprints.

## G46 Commit via ingest (no LLM diffs) [(=G46)]
* The LLM does not compute deltas.
* The workspace submits graph-form artifacts to ingest; ingest computes canonicalization, conflicts, and candidates.

## G47 Overlap detection across workspaces [(=G47)]
* Detect overlap and near-duplication across all open workspaces.
* Enable loop/oscillation detection and dedup.

## G48 Convergence-safe merge primitives [(=G48)]
* Provide deterministic, idempotent merge building blocks (CRDT-style joins where applicable).
* Where semantic conflict exists, preserve ambiguity instead of overwriting.

## G49 Bounded view compilation [(=G49)]
* Provide a deterministic mechanism to compile a bounded view of a large workspace into a context window.
* The LLM can expand/contract the view by manipulating focus pointers in the workspace.

## G50 Observability and budgets [(=G50)]
* Every workspace operation is logged.
* Quotas bound memory growth, fanout, and commit volume.

---

### P6I1 Workspace isolation (=[P6]) [(=P6I1)]

* HWS changes do not mutate long-term memory (LTM) directly.
* LTM changes only via commit events.

### P6I2 Evidence permanence (=[P6]) [(=P6I2)]

* Every committed memory object traces to evidence, or is flagged "structural-only" and linked to anchored objects.

### P6I3 Snapshot reads (=[P6]) [(=P6I3)]

* Readers see a stable epoch snapshot.
* Writers create overlays and commit new epochs, similar to MVCC / snapshot isolation.

### P6I4 Safe reclamation (=[P6]) [(=P6I4)]

* Old snapshots are reclaimed after a grace period, similar to RCU.

### P6I5 Governance never discards ambiguity (=[P6]) [(=P6I5)]

* Ambiguities may be hidden from UI by policy, yet remain in the ambiguity ledger with risk metadata.

---

# P7 invariants

### P10I1 Isolation (=[P10]) [(=P10I1)]

* Workspace edits never directly mutate LTM.

### P10I2 Snapshot base (=[P10]) [(=P10I2)]

* Each workspace pins a base LTM snapshot (epoch_id, lsn_end) for read coherence.

### P10I3 Structured concurrency closure (=[P10]) [(=P10I3)]

* If a workspace closes, all descendants close.

### P10I4 Idempotent import/export (=[P10]) [(=P10I4)]

* Importing the same capsule twice has no effect beyond the first import.

### P10I5 Loop-free capsule routing (=[P10]) [(=P10I5)]

* A workspace rejects any capsule whose hop-trace already contains that workspace.

### P10I6 Convergence of replicated workspace state (=[P10]) [(=P10I6)]

* If two replicas of a workspace (or two reconciliation runs) apply the same set of workspace events, they converge to the same WSG state.

### P10I7 Partial persistence (=[P10]) [(=P10I7)]

* Only explicitly exported regions may be submitted to ingest.
* Private scratch content may remain uncommitted and is GC-able.

### P10I8 Overlap registry monotonicity (=[P10]) [(=P10I8)]

* Fingerprints and lineage records are append-only within a workspace session.

### P10I9 Risk and provenance propagate (=[P10]) [(=P10I9)]

* Workspace-created objects are marked either provenance-anchored or structural-only.
* Risk tags propagate with capsules and commit envelopes.

---

### P10I10 Memory layer operations [(=P10I10)]

The memory layer must support the following operations. A coordination system may call them, but P10 (+[P10]) does not define the policy for when.

* WS_OPEN(agent_id, base_epoch, base_lsn_end, ttl) -> ws_id
* WS_CLOSE(ws_id, reason)
* WS_SPAWN_CHILD(parent_ws_id, ttl, seed_capsules[]) -> child_ws_id
* WS_EXPORT(parent_ws_id, selection_spec) -> capsule
* WS_IMPORT(ws_id, capsule) -> import_record
* WS_SEND(from_ws, to_ws, capsule, note)
* WS_QUERY(ws_id, query_spec) -> results
* WS_VIEW(ws_id, viewport_spec) -> prompt_pack
* WS_COMMIT(ws_id, exported_capsules, intent) -> commit_envelope

## Comp22 Hippocampal Workspace Store (HWS) [(=Comp22)]

## Comp23 Proposal Gateway (NGW) [(=Comp23)]
for neocortex outputs

## Comp25 Commit Controller (2SC) [(=Comp25)]

### P10I11 P6 two-stage commit integration [(=P10I11)]

Workspace commits go through ingest + hippocampus decision (commit/branch/quarantine).

### P10I12 P7 exploration integration [(=P10I12)]

Explorers can run in child workspaces; exported traces and subgraphs are reconciled.

### P10I13 P9 manifold integration [(=P10I13)]

Workspaces may optionally run a local field solve for ranking/diagnostics; not required.

### P10I14 No global spawn policy [(=P10I14)]

No global policy for when to spawn children or how to allocate budgets.

### P10I15 No automatic conflict resolution [(=P10I15)]

No automatic resolution of semantic conflict; ambiguity is preserved and surfaced.

### P10I16 No mandatory schema objects [(=P10I16)]

No requirement that the LLM use specific schema objects (idea nodes/facets). Those are allowed but not mandatory.

---


## Algorithm 6: Conflict scan [(=Algorithm 6)]

Conflict scan detects high tension and residual to identify ambiguity.

```pseudo
function CONFLICT_SCAN_AND_QUEUE(nodes S):
  for i in S:
    if STATE(i,main).T > TH_TENSION or STATE(i,main).r > TH_RESID:
      edges = TOPK_EDGES_BY_TENSION(i)
      CREATE_OR_UPDATE_CONFLICT_RECORD(i, edges)
```

## Algorithm 21 [(=Algorithm 21)]


## Algorithm 22 [(=Algorithm 22)]


## Comp1 Ingestion Stream [(=Comp1)]
Main streaming ingestion pipeline.


## Comp11 Modality Router [(=Comp11)]
Routes raw input to appropriate tokenizer based on detected modality.


## Comp12 Tokenizer Stack [(=Comp12)]
Domain-specific tokenization engines for text, code, tables, images, etc.


## Comp13 Graph Grammar Engine [(=Comp13)]
Applies graph rewrite rules to token graphs to build parse hypotheses.


## Comp14 Parse Forest Store [(=Comp14)]
Stores packed parse forests with shared substructure across hypotheses.


## Comp15 Grammar Library [(=Comp15)]
Repository of graph rewrite rules organized by domain and version.


## Comp16 Grammar Miner and Compiler [(=Comp16)]
Discovers patterns and compiles them into executable grammar rules.


## Comp17 Token Type Registry [(=Comp17)]
Central registry of token types with schemas and versioning.


## Comp18 Coordinate System Registry [(=Comp18)]


## Comp19 Adapter and Alignment Trainer [(=Comp19)]


## Comp21 Re-ingestion Orchestrator [(=Comp21)]
Manages controlled replay of evidence through new grammars or adapters.

---


## Comp24 Secondary Ingestion Engine (H2) [(=Comp24)]
Hippocampal workspace ingestion engine for hypothesis exploration.


## Comp26 Curriculum Manager (CURR) [(=Comp26)]
Controls ingestion parameters based on curriculum stage (bootstrap, expansion, open).


## Comp30 Grammar Sandbox + Rule Promotion (GRAM-SBX) [(=Comp30)]
Sandboxes candidate grammar rules, measures performance, promotes based on confidence.


## Comp31 Adapter Lifecycle Manager (ADAPT) [(=Comp31)]
with drift detection

