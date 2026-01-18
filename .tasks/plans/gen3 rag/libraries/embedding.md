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

### Algorithm 10: Structural Abstraction Mining (sleep-time)

Runs inside Algorithm 9 (Global Consolidation) after snapshot creation, before index build.

```pseudo
function STRUCTURAL_ABSTRACTION_MINE(snapshot snap):
  C = MINE_CANDIDATE_SUBGRAPHS(snap.graph_view)       // motifs, stars, cliques, chains, rules
  P = {}
  I = {}

  for cand in C:
    pat = CANONICALIZE_TO_PATTERN(cand)              // slotify entities, normalize types
    score = MDL_GAIN(snap.graph_view, pat)           // Δ description length
    conf  = ESTIMATE_PATTERN_CONFIDENCE(pat)         // from stats/provenance
    score' = score - λ * penalty(conf)

    if score' > 0:
      P.add(pat)

  // choose non-overlapping / best-cover instance set (greedy)
  for pat in SORT_BY_SCORE(P):
    matches = FIND_MATCHES(snap.graph_view, pat)
    matches = FILTER_OVERLAPS(matches, I)
    I.add(BEST_MATCHES(matches))

  WRITE_PATTERN_LIBRARY(P)
  WRITE_PATTERN_INSTANCES(I)
  return (P, I)
```

MDL summarization and "replace subgraph with single vertex" is a known compression pattern in graph summarization and grammar induction lines of work.

### Algorithm 11: Online Pattern Instantiation (day-time)

Matches new evidence into existing abstractions without deleting evidence.

```pseudo
function TRY_INSTANTIATE_PATTERNS(new_node v, hyp h):
  candidates = ANN_PATTERN_RETRIEVE(v.x, h)
  for pat in TOPK(candidates):
    if FAST_STRUCTURAL_GATE(pat, v):
      match = LOCAL_SUBGRAPH_MATCH(pat, around=v, radius=r)
      if match.found:
        inst = CREATE_INSTANCE(pat, match, hyp=h)
        UPDATE_PATTERN_STATS_ON_USE(pat, inst)
        ATTACH_MACRONODE(inst)                       // optional macro node in contextual tier
```

This is the "reuse patterns with alterations" hook: slot bindings vary per instance. Case-based reasoning is the classic framing for retrieve → reuse → revise → retain.

### Algorithm 12: Expansion Compiler (decompress for LLM)

Produces context packs that can be expanded by token budget.

```pseudo
function COMPILE_CONTEXT_FOR_LLM(query q, budget B, risk_profile R):
  items = RETRIEVE_RELEVANT_NODES_AND_PATTERNS(q)

  pack = []
  for item in PRIORITIZE(items, by=risk_and_relevance):
    if item is PatternInstance:
      frame = RENDER_PATTERN_FRAME(item)            // canonical_text + filled slots
      evidence = SELECT_SUPPORT_SPANS(item, cap=B_remaining)
      pack.add(frame)
      pack.add(evidence)
    else:
      pack.add(FETCH_SPAN(item.span_ref))

    if TOKENS(pack) >= B: break

  return pack
```

This matches "compressed memory + reflection/summary + expansion on demand" patterns seen in long-term agent memory and hierarchical retrieval systems.

### Algorithm 13: Confidence-weighted Pattern Promotion

```pseudo
function UPDATE_PATTERN_CONFIDENCE(pat_id, outcome):
  stats = GET_STATS(pat_id)
  if outcome == win:   stats.wins += 1
  if outcome == loss:  stats.losses += 1
  stats.uses += 1

  stats.θ_posterior = BETA_UPDATE(stats.θ_posterior, outcome)

  if P(θ >= τ | posterior) >= 1-δ and stats.uses >= Nmin:
    PROMOTE_PATTERN(pat_id)                          // candidate -> stable -> pinned

  if P(θ >= τ_low | posterior) < ε:
    DEMOTE_OR_QUARANTINE(pat_id)
```

"Pinned pattern" is the abstraction analogue of pinned facts.

### Algorithm 14: Failure Memory Write + Avoid

```pseudo
function RECORD_FAILURE(target, reason, evidence, severity, ctx):
  f = NEW_FAILURE_CASE(target, reason, evidence, severity, ctx)
  FAILURE_STORE.APPEND(f)

function FAILURE_BRAKE_SCORE(pat_id, ctx):
  sig = HASH(pat_id, ctx_bucket(ctx))
  return LOOKUP_FAILURE_RATE(sig)                   // smoothed count-based model

function PATTERN_SCORE(pat_id, ctx):
  base = BASE_PATTERN_SCORE(pat_id, ctx)
  brake = exp(-η * FAILURE_BRAKE_SCORE(pat_id, ctx))
  return base * brake
```

This is aligned with storing self-reflective "lessons" from mistakes for later avoidance in agent memory work.

### Algorithm 15: Light Outcome Feedback Loop (bandit)

```pseudo
function POLICY_STEP(context φ):
  a = SELECT_ACTION_UCB_OR_TS(φ)                     // which knob to turn
  EXECUTE_ACTION(a)
  r = OBSERVE_REWARD()                               // task success, user edit, implicit
  UPDATE_POLICY(φ, a, r)
  STORE_FEEDBACK_EVENT(φ, a, r)
```

Bandit foundations and safe online learning to re-rank provide the template for "light feedback, safe updates."

### Algorithm 16: Risk & Ambiguity Governance

```pseudo
function GOVERN_OUTPUT(answer_candidates, ambiguity_metrics, user_profile R):
  risk = COMPUTE_RISK(ambiguity_metrics, R.domain, R.risk_tolerance)

  WRITE_AMBIGUITY_LEDGER(ambiguity_metrics, risk)

  if risk > TH_DEFERRAL(R):
    return DEFERRAL_OUTPUT(ambiguity_report, request_clarification)
  else if risk > TH_SURFACE(R):
    return ANSWER_WITH_AMBIGUITY_BOUNDS(answer_candidates, ambiguity_report)
  else:
    return BEST_ANSWER(answer_candidates)
```

Conformal / selective frameworks supply calibrated abstention and risk control patterns for deferral decisions.

]
This preserves distances and angles in the mapped space. Manifold alignment via Procrustes uses this idea.

### General multi-view alignment

Use alignment and fusion approaches from multi-view representation learning when orthogonal mapping feels too rigid.

### P6.4 Connectivity targets

Define a cluster graph (H) whose nodes are communities in (G).
Target: small-world style redundancy, keep average path length low and maintain multiple inter-cluster bridges.

Practical invariant:

* for each cluster pair ((A,B)) with frequent co-retrieval, maintain at least (k) disjoint bridge candidates.

### P6.5 Adapter drift detection

Monitor an online error series (E_t) for an adapter, like retrieval regression or alignment loss.
Use adaptive-window drift detection for change points.

---

### P9.1 Discrete manifold (robust gated field)

Per hypothesis h, the manifold is induced by the robust gated objective (P1–P2), which is a weighted graph-smoothing + anchoring energy.

Let W_eff encode the effective conductance:

* W_eff(e) = w_base(e) * gate(e,h) * robust_weight(e,h)

Then the per-hypothesis solve is:

[L_{W_eff} + A + M] X = A B

The graph Laplacian can be decomposed as a sum of per-edge rank-1 terms:

L = Σ_{(i,j)∈E} w_{ij} (e_i - e_j)(e_i - e_j)^T

This decomposition is the basis for low-rank updates when edge weights change.

### P9.2 Local tangent frames (projection basis)

For node i, compute a weighted covariance of neighbor displacements:

C_i = Σ_{j∈N(i)} W_eff(i,j) (x_j - x_i)(x_j - x_i)^T

Let U_i be the top-m eigenvectors of C_i. U_i is the local tangent basis.

This is the standard "local PCA / local tangent space" idea used in manifold learning (e.g., LTSA-style pipelines).

### P9.3 Discrete parallel transport via connection Laplacian (solves the translation dragon)

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

### P9.4 Vector-diffusion distance (optional)

Use top eigenpairs of a normalized connection Laplacian (VDM) to embed nodes so that both proximity and alignment are captured.

This provides a principled "wormhole" signal:

* nodes that are not structurally adjacent can be geometrically close if a consistent transport exists.

### P9.5 Field blending (control, not topology)

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

### P7.1 Noise features

For a seed (s), define a feature vector:
[
\phi(s) = [T(s), r(s), \widehat{var}(s), nov(s), rec(s), prov(s), risk(s), cost(s)]
]

Sources for signals:

* (T) tension from field edges
* (r) anchor residual
* (\widehat{var}) uncertainty proxy
* (nov) novelty score
* (rec) recurrence across time and contexts
* (prov) provenance score (P6)
* (risk) governance risk (P4)
* (cost) predicted exploration cost

### P7.2 Interestingness score

[
I(s) = w_T T + w_r r + w_v \widehat{var} + w_n nov + w_{rec} rec + w_p prov - w_k risk - w_c cost
]

Weights can be:

* fixed per domain
* adapted via P4 light feedback (reward shaping)

### P7.3 Learning progress

Use improvement, not raw error. This avoids fixation on irreducible randomness.

For a trace (t) on seed (s):
[
LP(s) = \max(0,; \mathcal{L}_{ before}(s) - \mathcal{L}_{after}(s))
]
where (\mathcal{L}) can be a blend of tension and residual:
[
\mathcal{L}(s)=\alpha T(s) + \beta r(s)
]

This aligns with "learning progress" intrinsic motivation in IAC-style systems.

### P7.4 Novelty

Two options, both usable.

**Distance novelty**
[
nov(s)=\min_{p \in \mathcal{P}} |z(s)-z(p)|
]
where (z(\cdot)) is a structural embedding of the seed subgraph or pattern.

**Prediction novelty**
Use an exploration bonus based on prediction error of a fixed target representation, similar in spirit to RND.

Novelty search literature supports novelty as a primary driver for open-ended discovery.

### P7.5 Information gain for inquiry selection

For candidate inquiry action (a):
[
IG(a) = H(\Theta \mid D) - \mathbb{E}_{y \sim p(y \mid a,D)}[H(\Theta \mid D \cup (a,y))]
]
This is the classic expected informativeness frame for selecting data.

### P7.6 Utility for scheduling

[
U(s) = I(s) + \lambda LP(s) + \mu \max_{a \in A(s)} IG(a)
]
subject to budgets:
[
\sum cost(\text{explores}) \le B_{explore}, \quad \sum cost(\text{llm calls}) \le B_{llm}
]

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

### Algorithm 26: Curriculum ingestion controller

```pseudo
function CURRICULUM_STAGE(epoch e, stats):
  if e < E_BOOT: return bootstrap
  if stats.drift_high or stats.conflict_high: return expansion
  return open

function APPLY_CURRICULUM_PARAMS(stage):
  set default_alpha, gate, beam_width, validation_budget
  set grammar_policy, adapter_policy
```

Curriculum learning is a standard stabilization strategy.

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

### Algorithm 33: Noise scan

Runs after any of:

* local field update
* grammar parse step
* gating change
* adapter drift event
* repeated branch events

```pseudo
function NSCAN(epoch e, workspace_view W):
  seeds = []

  for v in W.nodes_touched:
    if T(v) > T0: seeds.add(SEED(high_tension, v))
    if r(v) > r0: seeds.add(SEED(high_residual, v))
    if var(v) > v0: seeds.add(SEED(high_variance, v))

  for m in W.grammar_near_misses:
    seeds.add(SEED(grammar_near_miss, m.subgraph_anchor))

  for gap in W.bridge_gaps:
    seeds.add(SEED(bridge_gap, gap.cluster_pair))

  for drift in W.adapter_drift_events:
    seeds.add(SEED(adapter_drift, drift.adapter_id))

  WRITE_SEEDS_APPEND_ONLY(seeds)
  return seeds
```

**P4C2 proof sketch: MDL-driven abstraction reduces description length**

**Claim.** Given a candidate pattern set, choosing patterns by MDL yields shorter descriptions than raw graph encoding (for those patterns). (Algorithm is heuristic; objective is principled.)

**Sketch.** The objective directly minimizes description length. Greedy selection may not find global optimum but provides local improvement guarantees standard in submodular-style optimization.

**P4C3 proof sketch: Promotion guarantee**

**Claim.** If a pattern is promoted only when (\Pr(\theta_p \ge \tau) \ge 1-\delta), then promotion implies a posterior reliability guarantee.

**Sketch.** Direct from the posterior CDF of the Beta distribution.

**P4C5 proof sketch: Risk governance calibration**

**Claim.** Conformal prediction can convert heuristic uncertainty into prediction sets with distribution-free coverage, and selective conformal risk control combines deferral with risk control.

**Sketch.** Conformal coverage guarantee is standard; selection layer trades coverage vs abstention.

### Algorithm 34: Thread queue update

```pseudo
function UPDATE_THREAD_QUEUE(new_seeds):
  for s in new_seeds:
    s.metrics.novelty = NOVELTY(s)
    s.metrics.recurry = RECURRENCE(s)
    s.prov_score = PROVENANCE(s)
    score = ISCORE(s)

    if score > TH_QUEUE:
      TQ.push(s, priority=score)
    else:
      s.status = parked
```

### Algorithm 35: Explore a seed

Two-stage: cheap structure first, then LLM refinement when value exists.

```pseudo
function EXPLORE_SEED(seed s):
  if CBUD.llm_remaining(domain(s)) <= 0 and CBUD.explore_remaining(domain(s)) <= 0:
    s.status = parked
    return

  bundle = EBC_COMPILE(s, budget_tokens=K)

  // Stage A: structural probes
  probes = RUN_STRUCTURAL_PROBES(bundle)
  if probes.outcome == "resolved":
    trace = WRITE_TRACE(s, probes)
    return

  // Stage B: LLM refine
  if SHOULD_CALL_LLM(s, bundle):
    proposal = LLMR_PROPOSE(bundle)            // actions + rationale + confidence
    APPLY_PROPOSAL_AS_HYPOTHESES(proposal)     // workspace overlay only
    CBUD.spend_llm(domain(s), cost_llm(proposal))

  // Stage C: validate and measure learning progress
  RUN_LOCAL_FIELD_REPAIR(bundle.scope)
  after = MEASURE_METRICS(s)

  trace = WRITE_TRACE(s, before_metrics, after, proposals)
  UPDATE_LEARNING_PROGRESS(s, trace)
  UPDATE_FAILURE_MEMORY(s, trace)
```

LLM-driven curiosity and intrinsic reward signals for LLM training and auditing exist in recent work, so "LLM used as refiner" fits the current research direction.

### Algorithm 36: Distill traces into tokens

```pseudo
function DISTILL(epoch e):
  traces = FETCH_RECENT_TRACES(e)
  clusters = CLUSTER_TRACES_BY_SIGNATURE(traces)

  for c in clusters:
    if RECURRENCE_HIGH(c) and LP_HIGH(c):
      idea = MAKE_IDEA_TOKEN(c)
      PROMOTE_IDEA(idea)                      // IdeaToken, PatternCandidate, BridgeCandidate, RuleCandidate
    else if FAILURE_HIGH(c):
      QUARANTINE_SIGNATURE(c.signature)
```

Learning progress guided exploration and goal selection is a standard curiosity mechanism in intrinsic motivation systems.

### Algorithm 37: Curiosity scheduler

Online plus sleep-time pass.

```pseudo
function CURIOSITY_SCHEDULER():
  while CBUD.explore_remaining > 0:
    s = TQ.pop()
    if s == none: break
    EXPLORE_SEED(s)

function SLEEP_CURIOSITY_PASS(snapshot snap):
  // deeper budgets, heavier probes
  for s in TOPN_SEEDS(snap, Nsleep):
    EXPLORE_SEED(s)
  DISTILL(snap.epoch)
```

### Algorithm 38: Decay and cleanup

```pseudo
function SEED_DECAY(seed s):
  if STALE(s) and RECURRENCE_LOW(s):
    s.status = archived
  if FAILURE_HIGH(s) and LP_LOW(s):
    s.status = quarantined
```

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

### Algorithm 58: MESSAGE_SEND

```pseudo
MESSAGE_SEND(from_ws, to_ws, cap, note):
  cap.hop_trace.append(to_ws)
  msg = WorkspaceMessage(from_ws, to_ws, cap, note)
  MSG.deliver(msg)
```

### Algorithm 59: RECONCILE_CHILD_TO_PARENT

```pseudo
RECONCILE_CHILD_TO_PARENT(parent_ws, child_ws, selection_spec):
  cap = EXPORT_CAPSULE(child_ws, selection_spec)
  overlap = OVERLAP_QUERY(parent_ws, cap.fingerprint)

  // RECON does not decide policy; it only computes signals.
  rec = ReconcileRecord(parent_ws, child_ws, cap.capsule_id, overlap)
  return rec, cap
```

### Algorithm 60: COMMIT_TO_INGEST (no LLM diffs)

```pseudo
COMMIT_TO_INGEST(ws_id, exported_capsules, intent):
  payload = BUILD_GRAPH_PAYLOAD(ws_id, exported_capsules)
  env = WorkspaceCommitEnvelope(ws_id, payload, base_epoch, base_lsn_end)
  CGW.submit_to_ingest(env)
  return env
```

### Algorithm 61: OVERLAP_SIGNATURE (structure + content)

```pseudo
OVERLAP_SIGNATURE(subgraph):
  wl_hash  = WL_HASH(subgraph, iterations = k)
  shingle_set = SHINGLES(subgraph)                // labels, edge types, local WL labels
  minhash = MINHASH(shingle_set)
  simhash = SIMHASH(EMBED(shingle_set))
  return {wl_hash, minhash, simhash}
```

### Algorithm 62: OVERLAP_DETECT

```pseudo
OVERLAP_DETECT(fingerprint_a, fingerprint_b):
  // fast filters
  if HAMMING(simhash_a, simhash_b) > H: return low_overlap

  // approximate set similarity
  j_hat = MINHASH_ESTIMATE(minhash_a, minhash_b)
  return j_hat
```

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

### Algorithm 64: WORKSPACE_GC

```pseudo
WORKSPACE_GC(ws_id):
  // Only for closed workspaces or expired TTL.
  // Preserve audit log pointers, remove bulk graph payload.
  compact event log; drop scratch-only regions; keep exported capsules and commit envelopes.
```

### Algorithm 39: Factor learning in sleep

```pseudo
function LEARN_FACTORS(epoch e):
  X = SAMPLE_CANONICAL_VECTORS(e)              // token canonical x_i
  (D, Enc) = TRAIN_SPARSE_AUTOENCODER(X)       // x ≈ D a, a sparse
  STORE_FACTOR_DICT(D, Enc, version=e)
```

Basis: sparse coding style factorization.

### Algorithm 40: Module mining from pattern graphs

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

### Algorithm 41: Build pattern functionality profiles

```pseudo
function BUILD_PROFILES(pattern_instances I, Enc):
  for inst in I:
    a = Enc( CANONICAL_VECTOR(inst.macro_node) )
    UPDATE_FACTOR_PROFILE(inst.pattern_id, a)
    UPDATE_CONTEXT_PROFILE(inst.pattern_id, inst.neighborhood_types)
    UPDATE_EFFECT_PROFILE(inst.pattern_id, DELTA_ENERGY(inst))
```

### Algorithm 42: Idea proposal via substitution and hybridization

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

### Algorithm 43: Simulate and validate an idea candidate

```pseudo
function EVALUATE_IDEA(candidate c):
  hws = HWS_OPEN(region=c.region, base_epoch=c.epoch)
  APPLY_REWRITE_IN_WORKSPACE(hws, c.rewrite)
  RUN_LOCAL_FIELD_REPAIR(hws)
  delta = MEASURE_DELTA(hws, baseline)

  if delta.good:
    bundle = COMPILE_EVIDENCE_BUNDLE(c, hws)
    llm = LLM_REFINE(bundle)                   // label + missing evidence
    STORE_IDEA_TOKEN(c, delta, llm)
    return PROMOTE_AS_HYPOTHESIS(c)
  else:
    RECORD_FAILURE(c)
```

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

Multi-view alignment and fusion is a standard frame for coordinating multiple embedding spaces.

### D34 NoiseSeed

```text
NoiseSeed {
  seed_id: SeedId
  seed_type: enum {
    high_tension, high_residual, high_variance,
    grammar_near_miss, repeated_branching,
    retrieval_dead_end, adapter_drift,
    bridge_gap, concept_collision
  }
  target: enum {node, edge, subgraph, hypothesis, rule, adapter}
  target_id: bytes
  hyp_scope: HypScopeRef
  provenance: list<SpanRef>            // may be empty for structural-only seeds
  graph_coords: GraphCoordRef?         // subgraph anchors, match bindings
  metrics: {T, r, var, novelty, recurrency}
  prov_score: float
  risk_tags: set<RiskTag>
  created_t: Time
  status: enum {queued, exploring, parked, promoted, quarantined, archived}
}
```

### D35 ExplorationTrace

```text
ExplorationTrace {
  trace_id: TraceId
  seed_id: SeedId
  actions: list<ActionRecord>          // walk, expand, branch, validate, propose_rule, propose_bridge
  before_metrics: {T, r, var}
  after_metrics: {T, r, var}
  evidence_used: list<SpanRef>
  proposals: list<ProposalRef>         // graph deltas, new tokens, new rules, new bridges
  outcome: enum {gain, neutral, loss}
  created_t: Time
}
```

### D36 EvidenceBundle

```text
EvidenceBundle {
  bundle_id: BundleId
  seed_id: SeedId
  neighborhood: list<NodeId|EdgeId>    // top-k by tension and relevance
  competing_hyps: list<HypId>
  support_spans: list<SpanRef>
  near_miss_patterns: list<PatId>
  candidate_bridges: list<EdgeCandidate>
  budget_tokens: int
}
```

### D37 CuriosityBudget

```text
CuriosityBudget {
  domain: DomainId
  window: TimeWindow
  explore_budget: float
  llm_budget: float
  spent_explore: float
  spent_llm: float
}
```

### D38 IdeaToken

A stable "thread" once substantiated.

```text
IdeaToken {
  idea_id: IdeaId
  label: string                        // human handle
  tok_type: TokTypeId                  // Idea, HypothesisFrame, Pattern, RuleCandidate, BridgeCandidate
  anchors: list<NodeId|SpanRef>
  canonical_frame: string              // compact description for expansion
  confidence: float
  hyp_id: HypId
  created_t: Time
}
```

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

### D46 ManifoldView

A pinned read view.

```text
ManifoldView {
  epoch_id: EpochId
  lsn_end: LogOffset
  hyp_id: HypId
}
```

### D47 ManifoldState

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

### D48 TangentFrame

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

### D49 EdgeTransport

A discrete parallel transport operator between tangent frames.

```text
EdgeTransport {
  edge_id: EdgeId
  hyp_id: HypId
  R_ij: Matrix[m x m]               // approx orthogonal map from i-frame to j-frame
  weight: float                     // typically W_eff(edge)
}
```

### D50 ConnectionLaplacian

A block Laplacian over tangent bundles.

```text
ConnectionLaplacian {
  hyp_id: HypId
  m: int
  // implicit operator form; can be applied without materializing full blocks
  apply(y): y -> y
}
```

### D51 BlendRecipe

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

### D52 CompositeField (ephemeral)

```text
CompositeField {
  view: ManifoldView
  recipe: BlendRecipe
  score: NodeId -> float
  grad_tangent: NodeId -> Vector[m]?   // optional tangent gradient
}
```

### D53 TranslationProposal

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

### D54 ABExperiment

```text
ABExperiment {
  exp_id: ExpId
  control_epoch: EpochId
  candidate_epoch: EpochId
  start_lsn: LogOffset
  traffic_split: float
  metrics: {quality, latency, risk, conflict_rate, drift}
  guardrails: {max_regression, rollback_thresholds}
  status: enum {shadow, canary, ramp, hold, rollback, graduate}
}
```

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

### D58 CurriculumStage

```text
CurriculumStage {
  stage_id: enum {bootstrap, expansion, open}
  default_alpha: float
  default_gate: float
  beam_width: int
  validation_budget: int
  grammar_policy: GrammarPolicyRef
  adapter_policy: AdapterPolicyRef
}
```

### D59 SurpriseBudget

```text
SurpriseBudget {
  domain: DomainId
  window: TimeWindow
  budget: float
  spent: float
}
```

### D60 ConnectivityState

```text
ConnectivityState {
  epoch: EpochId
  cluster_graph: SuperGraphRef
  articulation_candidates: list<NodeId>
  bridge_candidates: list<EdgeId>
  redundancy_targets: {k_paths, long_links_per_cluster}
}
```

### D61 GrammarRuleCandidate

```text
GrammarRuleCandidate {
  rule_id: RuleId
  source_pattern: PatId?
  domain: DomainId
  version: int
  status: enum {shadow, canary, promoted, rolled_back}
  stats: {precision, conflict_rate, drift_rate}
  posterior: BetaParams
}
```

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

### D63 InquiryTask

```text
InquiryTask {
  task_id: TaskId
  target: enum {node, edge, hypothesis, rule, adapter}
  target_id: bytes
  objective: enum {reduce_uncertainty, resolve_conflict, validate_bridge}
  expected_gain: float
  cost: float
  created_t: Time
}
```

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

---

## P6.5 Adapter drift detection

Monitor embedding adapter fit error over time to detect distribution shift.

---
