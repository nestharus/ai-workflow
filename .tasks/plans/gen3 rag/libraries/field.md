## Comp3 Field Solver [(=Comp3)]

## Comp8 Retrieval Planner [(=Comp8)]

## Comp27 Cold Solve Scheduler (ROOT) [(=Comp27)]

---

## Algorithm 3: Field relaxation on a subgraph [(=Algorithm 3)]

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
```

Coordinate update under gated quadratic stays closed form:
[
x_i \leftarrow
\frac{\alpha_i b_i + \sum_{j} w_{ij}g_{ij} x_j}{\alpha_i + \mu_i + \sum_{j} w_{ij}g_{ij}}
]

```pseudo
function FIELD_RELAX_GATED(nodes S, hypothesis h, steps T):
  repeat T times:
    for i in SHUFFLE(S):
      denom = alpha[i] + mu[i] + SUM_{j in N(i)} w[i,j] * g[i,j,h]
      numer = alpha[i] * b[i] + SUM_{j in N(i)} w[i,j] * g[i,j,h] * x[j,h]
      x[i,h] = numer / denom
```

---

### P9I3 — Blends are reversible (=[P9]) [(=P9I3)]

No blend may become the only representation of its primitives. `BlendRecipe` must be explicit and all primitives remain computable.

---

### P9I4 — No force becomes law silently (=[P9]) [(=P9I4)]

Fields may guide traversal and scheduling.

Fields may only alter topology (edge gates, bridges, anchor policies) via two-stage commit + governance.

---

### D7 NodeState [(=D7)]

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

---

### D46 ManifoldView [(=D46)]

A pinned read view.

```text
ManifoldView {
  epoch_id: EpochId
  lsn_end: LogOffset
  hyp_id: HypId
}
```

---

### D47 ManifoldState [(=D47)]

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

---

### D48 TangentFrame [(=D48)]

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

---

### D49 EdgeTransport [(=D49)]

A discrete parallel transport operator between tangent frames.

```text
EdgeTransport {
  edge_id: EdgeId
  hyp_id: HypId
  R_ij: Matrix[m x m]               // approx orthogonal map from i-frame to j-frame
  weight: float                     // typically W_eff(edge)
}
```

---

### D50 ConnectionLaplacian [(=D50)]

A block Laplacian over tangent bundles.

```text
ConnectionLaplacian {
  hyp_id: HypId
  m: int
  // implicit operator form; can be applied without materializing full blocks
  apply(y): y -> y
}
```

---

### D51 BlendRecipe [(=D51)]

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

---

### D53 TranslationProposal [(=D53)]

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

---

### P2.2 IRLS weight update rule [(=P2.2)]

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

---

### P2.3 Linear solve in each IRLS step [(=P2.3)]

Let (L_{\tilde{w}}) be the Laplacian built from (\tilde{w}*{ij}^{(k,h)}). As before:
[
(L*{\tilde{w}} + A + M) X^{(h)} = A B
]

---

### P9.1 Discrete manifold (robust gated field) [(=P9.1)]

Per hypothesis h, the manifold is induced by the robust gated objective (P1–P2), which is a weighted graph-smoothing + anchoring energy.

Let W_eff encode the effective conductance:

* W_eff(e) = w_base(e) * gate(e,h) * robust_weight(e,h)

Then the per-hypothesis solve is:

[L_{W_eff} + A + M] X = A B

The graph Laplacian can be decomposed as a sum of per-edge rank-1 terms:

L = Σ_{(i,j)∈E} w_{ij} (e_i - e_j)(e_i - e_j)^T

This decomposition is the basis for low-rank updates when edge weights change.

---

### P9.2 Local tangent frames (projection basis) [(=P9.2)]

For node i, compute a weighted covariance of neighbor displacements:

C_i = Σ_{j∈N(i)} W_eff(i,j) (x_j - x_i)(x_j - x_i)^T

Let U_i be the top-m eigenvectors of C_i. U_i is the local tangent basis.

This is the standard "local PCA / local tangent space" idea used in manifold learning (e.g., LTSA-style pipelines).

---

### P9.3 Discrete parallel transport via connection Laplacian (solves the translation dragon) [(=P9.3)]

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

---

### P9.4 Vector-diffusion distance (optional) [(=P9.4)]

Use top eigenpairs of a normalized connection Laplacian (VDM) to embed nodes so that both proximity and alignment are captured.

This provides a principled "wormhole" signal:

* nodes that are not structurally adjacent can be geometrically close if a consistent transport exists.

---

### P9.5 Field blending (control, not topology) [(=P9.5)]

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

---

### Algorithm 65: Robust Field Solve via IRLS [(=Algorithm 65)]

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

---

### Algorithm 24: Hippocampal workspace session [(=Algorithm 24)]

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

### Algorithm 27: Cold solve and re-rooting [(=Algorithm 27)]

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

### Algorithm 30: Grammar sandbox and promotion [(=Algorithm 30)]

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

### Algorithm 31: Adapter lifecycle and drift management [(=Algorithm 31)]

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

## Algorithm 44 — MANIFOLD_UPDATE_LOCAL (online) [(=Algorithm 44)]

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

---

## Algorithm 45 — CHART_BUILD (incremental) [(=Algorithm 45)]

```pseudo
function CHART_BUILD(view, nodes S, m):
  for i in S:
    N = NEIGHBORHOOD(i)
    C = Σ_{j in N} W_eff(i,j) * (X[j]-X[i]) (X[j]-X[i])^T
    U, evals = TOP_EIGENVECTORS(C, m)
    STORE TangentFrame(i, view.hyp_id, U, evals, built_lsn=view.lsn_end)
```

---

## Algorithm 46 — BUILD_CONNECTION_LAPLACIAN (incremental) [(=Algorithm 46)]

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

---

## Algorithm 47 — PROJECT_VECTOR_FIELDS (manifold → usable vectors) [(=Algorithm 47)]

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

---

## Algorithm 48 — BLEND_COMPUTE (runtime) [(=Algorithm 48)]

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

---

## Algorithm 49 — MANIFOLD_TO_GRAPH_PROPOSALS (pullback) [(=Algorithm 49)]

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

---

## C1 Field embeddings exist and are unique [(=C1)]

Under mild anchoring conditions.

## C2 Local relaxation converges [(=C2)]

To the field solution on a fixed graph.

## C3 Field embeddings attenuate underspecified noise [(=C3)]

Relative to raw embeddings, under a simple noise model.

## P5C1 Multi-view canonical field solve exists and is unique [(=P5C1)]

With anchors (\bar{b}_i) and (\alpha_i+\mu_i>0) per connected component, the canonical quadratic system remains SPD. Uniqueness follows the same argument as earlier field proofs, since the only change is the anchor target, not the Hessian structure.

Proof obligation in Lean:

* show SPD of (L + A + M)
* show unique minimizer exists

---

## G1 Reliable directions [(=G1)]

* Directions conditioned on structure, rather than raw span text.

---

## G3 Revision as a first-class operation [(=G3)]

* Meaning shifts propagate through the field and graph.

---

## G5 High recall with controllable cost [(=G5)]

* Cheap candidate generation, expensive validation only where needed.

---

## G9 Global consolidation [(=G9)]

* Local patching accumulates. Periodic consolidation realigns the field across the full graph while ingestion keeps running.

---

## G11 Robustness [(=G11)]

* Large disagreements stop dominating smoothing. Disagreements become diagnostics.

---

## G36 Manifold as a first-class substrate [(=G36)]

* Explicit `ManifoldState` objects exist per epoch and hypothesis.
* Readers pin a `ManifoldView` (epoch + log cut) and see a coherent geometry.

---

## G37 Explicit translation operators [(=G37)]

* Graph/observations → manifold (lift)
* manifold → vector fields (project)
* manifold → graph proposals (pullback)

---

## G38 Governed blending [(=G38)]

* Ephemeral blending is always allowed.
* Cached blending is allowed but versioned.
* Promotion of blends into topology requires a governed commit.

---

### D52 CompositeField (ephemeral) [(=D52)]

```text
CompositeField {
  view: ManifoldView
  recipe: BlendRecipe
  score: NodeId -> float
  grad_tangent: NodeId -> Vector[m]?   // optional tangent gradient
}
```

---

### P2I1 Field update locality [(=P2I1)]

Local, bounded by tier neighborhoods.

---

### P2I2 Local field updates bounded [(=P2I2)]

Per span: relax only within a hop radius determined by tier. Global solve: scheduled offline or during low load, used to reduce drift.

---

### P2I3 Local relaxation bounded [(=P2I3)]

Local relaxation bounded by tier caps.

---

### P2I4 Conflict resolution strict quotas [(=P2I4)]

Conflict resolution budgeted as a background loop with strict quotas.

---

### P2I5 Validator rate limiting [(=P2I5)]

Validator calls rate-limited and triggered by tension.

---

---

## Algorithm 7: Conflict resolution [(=Algorithm 7)]

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

---

---

### P2C3 IRLS descent [(=P2C3)]

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

---

---

### P2C4 Convergence to a stationary point [(=P2C4)]

Sketch:

* MM descent yields a monotone non-increasing objective sequence.
* (\mathcal{E}) is bounded below, so objective values converge.
* Under standard MM conditions (continuity, proper majorizer, tangency), every limit point of ({X^{(k)}}) is a stationary point.
* If (\rho) is convex (Huber), then (\mathcal{E}) is convex, so the stationary point is a global minimizer.

---

### P1C2 Unique field minimizer [(=P1C2)]

Gated quadratic field per hypothesis has a unique minimizer under the same anchoring condition as v0.1.

---

### P1C3 Field relaxation convergence [(=P1C3)]

Field relaxation converges per hypothesis.

---

### P1C5 Robust loss convergence [(=P1C5)]

Robust loss reduces influence of large disagreements while preserving convergence to a minimizer.

---

