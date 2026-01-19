## P8.3 Direction disentanglement in your system [(=P8.3)]

**Option A: Sparse autoencoder or dictionary learning on canonical embeddings**

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

**Option B: ICA style independence**

ICA explicitly searches for statistically independent components. This can be useful for a "factor sanity check," especially when you have lots of mixed signals.

**Option C: NMF for parts-based factors**

If you want factors to behave like "parts" that add up (good for certain counts and structured features), NMF is a known tool.

### D24 FactorDictionary [(=D24)]

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

### D62 AdapterCandidate [(=D62)]

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

## P5.3 Multi-coordinate embeddings as a bundle with a canonical field [(=P5.3)]

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

### Lean12 Distance preservation under orthogonal maps [(=Lean12)]

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

## P5.4 Adapter learning [(=P5.4)]

Two practical adapter forms:

### P6.5 Adapter drift detection [(=P6.5)]

Monitor an online error series (E_t) for an adapter, like retrieval regression or alignment loss.
Use adaptive-window drift detection for change points.

---

### Algorithm 39: Factor learning in sleep [(=Algorithm 39)]

```pseudo
function LEARN_FACTORS(epoch e):
  X = SAMPLE_CANONICAL_VECTORS(e)              // token canonical x_i
  (D, Enc) = TRAIN_SPARSE_AUTOENCODER(X)       // x ≈ D a, a sparse
  STORE_FACTOR_DICT(D, Enc, version=e)
```

Basis: sparse coding style factorization.

## G21 Computable directions across coordinate systems [(=G21)]

* Every token type has one or more embedding spaces.
* Traversal and matching use explicit coordinate transforms, so math stays consistent as you move across token types and domains.

---

## G28 Multi-coordinate adapters are governable [(=G28)]

* Adapters are versioned, canaried, drift-detected, rolled back.

## D33 Adapter map [(=D33)]

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

## D32 Coordinate system [(=D32)]

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
