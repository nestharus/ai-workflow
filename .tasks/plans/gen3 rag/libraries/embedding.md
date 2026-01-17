# Embedding Library

Multi-coordinate systems, adapters, alignment training, canonical projections, parallel transport.

---

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

### Why your architecture makes this robust

Locatello's result basically says: if you only see (x), the factorization is underdetermined.

You have extra constraints:

* token types and slot types
* graph neighborhoods
* hypothesis splits
* provenance strata
* outcome feedback

So you do "weak supervision by structure" instead of hoping for a miracle from raw vectors.

---

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

---

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

---

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

Multi-view alignment and fusion is a standard concept, including correlation-based alignment like CCA and mapping-based approaches like Procrustes. ([arXiv][3])

---

## P5.4 Adapter learning

Two practical adapter forms:

### Orthogonal Procrustes map

For paired vectors ((u_k, v_k)) in two spaces, find an orthogonal matrix (R) minimizing:
[
\min_{R^\top R = I} |UR - V|_F

---

### P6.5 Adapter drift detection

Monitor an online error series (E_t) for an adapter, like retrieval regression or alignment loss.
Use adaptive-window drift detection for change points.

---

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

Hyperedge replacement and related graph grammar formalisms provide a language for "graph as grammar". ([People CS Umeå][5])

---

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

Graph embeddings and substructure signatures like WL-based features and graph-level embeddings are standard tools. ([Journal of Machine Learning Research][8])
Code embeddings from AST structure exist as well. ([ACM Digital Library][9])

---

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

"Topology changes into different coordinate systems" becomes "travel happens in canonical space, with local boosts in native spaces."

---

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

Graph parsing for HRG and related grammars is studied, and complexity varies a lot by restrictions, so this is designed with hypothesis beams and domain restrictions. ([ACL Anthology][10])

---

## P5C4 Orthogonal adapter preserves geometry

If (A_v) is orthogonal, then (|A_v x - A_v y| = |x-y|). This gives stable similarity across mapped spaces. Procrustes-based alignment provides a practical way to fit such maps. ([ICML][7])

Lean target:

* prove distance preservation for orthogonal matrices
* prove the Procrustes minimizer exists under standard assumptions, optional

---

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

---

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

---

## G21 Computable directions across coordinate systems

* Every token type has one or more embedding spaces.
* Traversal and matching use explicit coordinate transforms, so math stays consistent as you move across token types and domains.

---

## G28 Multi-coordinate adapters are governable

* Adapters are versioned, canaried, drift-detected, rolled back.

---

## Option A: Sparse autoencoder or dictionary learning on canonical embeddings

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

---

## Option B: ICA style independence

ICA explicitly searches for statistically independent components. This can be useful for a "factor sanity check," especially when you have lots of mixed signals.

---

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

---

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

Multi-view alignment and fusion is a standard frame for coordinating multiple embedding spaces. ([arXiv][3])

---

## Traversal across coordinate systems

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

"Topology changes into different coordinate systems" becomes "travel happens in canonical space, with local boosts in native spaces."

---

## Orthogonal Procrustes map

For paired vectors ((u_k, v_k)) in two spaces, find an orthogonal matrix (R) minimizing:
[
\min_{R^\top R = I} |UR - V|_F

---

### General multi-view alignment

Use alignment and fusion approaches from multi-view representation learning when orthogonal mapping feels too rigid. ([arXiv][3])

---

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

---

### P6C6 Adapter rollout is safe under canary plus rollback

**Claim.** Rollout can be limited to fraction (f) and reverted on regression.
**Sketch.**

* Canarying is a standard safety pattern for deployments.

---

## Comp18 Coordinate System Registry

Manages coordinate systems and their canonical mappings.

---

## Comp19 Adapter and Alignment Trainer

Learns and maintains transforms between coordinate systems.

---

## Comp31 Adapter Lifecycle Manager (ADAPT)

Manages adapter lifecycle with drift detection, canary rollout, and rollback.

---

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

---

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

Multi-view alignment and fusion is a standard frame for coordinating multiple embedding spaces. ([arXiv][3])

---

### P5I1 Parse forest versioning

Parse forests are versioned by epoch. Old hypotheses compact via P2 sleep cycle, with provenance and failures retained.

---

### P5I2 Strict beam width

Strict beam width per region. Packed DAG sharing across hypotheses, similar in spirit to graph-structured stacks for ambiguity. ([IJCAI][2])

---

### P5I3 Grammar class restrictions per tier

Focus and Active: restricted grammars with cheap matching and bounded-degree neighborhoods. Context and Sleep: heavier grammars and deeper matching. Graph grammar parsing complexity varies widely across grammar classes and restrictions. ([sciencedirect.com][11])

---

### P5I4 Match candidate indexing

Index rule LHS patterns by WL-style neighborhood signatures. Use WL hashing to prune match candidates before subgraph matching. ([Journal of Machine Learning Research][8])

---

### P5I5 Coordinate transforms cached

Cache canonical projections (A_v b_i^{(v)}). Refit adapters in sleep-time, then bulk-refresh projections during consolidation.

---

### P5I6 Domain embedders specialized

Text embedder stays as the semantic anchor. Graph embedder covers topology. Code embedder covers AST and code structure. ([ACM Digital Library][9])

---
