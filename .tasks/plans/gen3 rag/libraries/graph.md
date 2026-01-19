### D8 EdgeBelief [(=D8)]

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

### D60 ConnectivityState [(=D60)]

```text
ConnectivityState {
  epoch: EpochId
  cluster_graph: SuperGraphRef
  articulation_candidates: list<NodeId>
  bridge_candidates: list<EdgeId>
  redundancy_targets: {k_paths, long_links_per_cluster}
}
```

### P6.4 Connectivity targets [(=P6.4)]

Define a cluster graph (H) whose nodes are communities in (G).
Target: small-world style redundancy, keep average path length low and maintain multiple inter-cluster bridges.

Practical invariant:

* for each cluster pair ((A,B)) with frequent co-retrieval, maintain at least (k) disjoint bridge candidates.

### Algorithm 29: Connectivity guard and bridge repair [(=Algorithm 29)]

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

## G26 Graph stays traversable [(=G26)]

* Gating, retraction, and poison containment keep redundant paths and preserve reachability.
* Small-world mesh targets guide bridge redundancy.

## D1 Node [(=D1)]

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

## D2 Edge [(=D2)]

```
Edge {
  src: NodeId
  dst: NodeId
  type: EdgeType              // adjacency, containment, reference, membership, coactivation, contradiction
  w: float                    // weight
  meta: Map                   // optional evidence, provenance, validator score
}
```

## D3 Graph [(=D3)]

Use a typed, weighted multigraph.

* Active tiers in RAM: adjacency lists per node, plus per-edge type partitions.
* Inactive tier on disk: LSM-backed edge table keyed by (src, type, dst).

## Comp2 Graph Store [(=Comp2)]

## Comp6 Edge Validator [(=Comp6)]

## Comp20 Traversal Planner [(=Comp20)]

## Comp29 Connectivity Monitor + Bridge Synthesizer (CONN) [(=Comp29)]

## D13 EdgeBelief additions [(=D13)]

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
