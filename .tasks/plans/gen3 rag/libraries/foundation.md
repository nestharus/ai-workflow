### P1I1 Evidence permanence (=[P1]) [(=P1I1)]

For every node and edge:

* a provenance record exists that references source spans or earlier events
* provenance never disappears

---

### P1I2 Non-destructive updates (=[P1]) [(=P1I2)]

No operation deletes nodes, edges, or prior states.

* merges create aliases
* revisions create new states
* deletions become tombstones with provenance

---

### P1I3 Field state never overwrites history (=[P1]) [(=P1I3)]

`x` updates append a new state record. Prior `x` remains retrievable.

---

### P1I4 Ambiguity stays explicit (=[P1]) [(=P1I4)]

If conflict persists past a threshold budget, the system either:

* records the conflict in the conflict ledger, or
* branches hypotheses

---

### P4I3 Failure memory is append-only (=[P4]) [(=P4I3)]

* Failure events accumulate and are only compacted by "sleep" with provenance kept.

---

### P9I5 — Translation proposals are provenance-bearing (=[P9]) [(=P9I5)]

Any manifold→graph proposal must carry:

* evidence bundle
* diagnostics deltas
* risk tags
* stability window

---

### D6 ObservationRecord [(=D6)]

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

### D10 Hypothesis [(=D10)]

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

### P7C1 Evidence stays [(=P7C1)]

**Claim.** Every seed, idea, and derived structure links back to spans or anchored graph coordinates.

**Sketch.**

By construction:
* Seeds store provenance lists
* IdeaTokens store anchors
* All derived structure references NoiseSeed or IdeaToken which have provenance

---

## G6 Evidence permanence [(=G6)]

* Raw spans and all derived claims remain traceable to original spans.

---

---


### S1 Problem statement [(=S1)]

Raw embeddings give underspecified directions. Global clustering over those directions drifts. Chunking breaks associations. The system needs directions that stay reliable as meaning evolves.

---

### S2 Core approach [(=S2)]

Treat embeddings as observations. Treat the graph as structure. Compute a semantic field over the graph. Use that field as the working direction system.

This aligns with:

* Gaussian random fields and harmonic functions on graphs.
* Graph signal processing and graph filtering.
* Message passing as a generic computation pattern on graphs.
* Dynamic graphs and time-varying representations.

---

---

### P2C5 No evidence loss [(=P2C5)]

Sketch:

* Consolidation creates a new epoch and new node states.
* It leaves ObservationRecords, prior NodeStates, ConflictRecords, hypotheses, and the event log intact.
* Therefore any prior world state can be reconstructed by choosing an older epoch or replaying events.

Event sourcing is the established pattern for this audit and replay property. ([Microsoft Learn][7])

---

---

## P5C2 Rewrite steps preserve evidence permanence [(=P5C2)]

Each rewrite emits tokens with provenance pointers and leaves raw spans untouched. Rule application is append-only over epoch views and event log. Expansion from tokens back to spans remains possible by construction.

Proof obligation in Lean:

* inductive invariant over events: every token has a path to some ObservationRecord or is marked structural-only and tied to anchor nodes

---

### P1C1 Evidence permanence [(=P1C1)]

Evidence permanence holds under all operations.

---

