## G39 Dragon closure [(=G39)]

* Every open gap becomes either:
  * an implemented method,
  * an explicit bypass rule, or
  * a deliberate non-goal with an alternative.

### P1C6: Evidence permanence proof sketch [(=P1C6)] (+[P1C1])

By construction:

* all raw spans remain in the raw store referenced by `SpanRef`
* each node creation writes an `ObservationRecord`
* each derived update appends to event log
* node states append to `NodeState` history
* merges and splits create alias edges and lineage pointers

Therefore any current state and any prior state is reconstructible from the append-only log plus raw store.

### P1C7: Unique field minimizer and convergence proof sketch [(=P1C7)] (+[P1C2]) (+[P1C3])

For a fixed hypothesis (h), gated quadratic energy remains strictly convex when (\alpha_i + \mu_i > 0) per connected component.
The matrix (Q = L_g + A + M) stays SPD.
Coordinate descent decreases energy and converges to the unique minimizer.

This is the same style of argument used for harmonic energy minimization on graphs.

### P1C8: Persistent conflict durability proof sketch [(=P1C8)] (+[P1C4])

Conflict scores derive from residual and tension.
If tension remains above threshold after validator updates and local relaxation, the policy triggers branching.
Since branching is append-only and the conflict record persists, ambiguity becomes durable.

### T1 Structural disentanglement [(=T1)]

Take complex patterns and decompose them into smaller reusable modules with typed interfaces.

* Pattern = a graph template or a grammar rewrite rule (P4/P5)
* Module = a subpattern used across many patterns, with a stable boundary
* Boundary = the slots and edge-types that connect module to the rest

Goal: represent a pattern as "modules + wiring" rather than a monolith.


### T10 Grammar emergence from patterns [(=T10)]

Turns P4 (+[P4]) patterns into executable grammar rules.

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

Hyperedge replacement and related graph grammar formalisms provide a language for “graph as grammar”.


### T11 Graph token embedding bundle and canonical projection [(=T11)]

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


### T12 Traversal across coordinate systems [(=T12)]

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

“Topology changes into different coordinate systems” becomes “travel happens in canonical space, with local boosts in native spaces.”


### T13 Re-ingestion under reinterpretation [(=T13)]

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

Graph parsing for HRG and related grammars is studied, and complexity varies a lot by restrictions, so this is designed with hypothesis beams and domain restrictions.


#### T14 Notes on BUILD_INDICES [(=T14)]

This is a versioned build, then swap. The Lucene style segment approach is a practical reference point for "build new segments, then open them" behavior.


### T2 Direction disentanglement [(=T2)]

Represent canonical vectors as sparse combinations of basis directions.

* Token canonical vector (x \in \mathbb{R}^{d_C})
* Factor dictionary (D \in \mathbb{R}^{d_C \times K})
* Sparse coefficients (a \in \mathbb{R}^K)

Goal: replace "one entangled vector" with "few active factors."

This is the same family of ideas as sparse coding and dictionary learning. A major warning: fully unsupervised disentanglement has identifiability limits. It needs inductive bias and constraints. Your system already has strong biases: typed edges, slot schemas, hypotheses, provenance, and outcome feedback. That is exactly how you escape the "disentanglement is impossible" regime.


### T3 Module extraction idea [(=T3)]

Given a corpus of pattern graphs, find subgraphs that:

* recur across patterns
* have stable boundaries (interfaces)
* reduce description length when added as reusable primitives

This is structurally the same principle as your MDL compression work in P4, just one level deeper. It turns patterns into an algebra of parts.

Result:

* Pattern = DAG of modules + wiring constraints
* Module = token type in the grammar

This gives "components" that can be moved between contexts.


#### T4 Confidence-weighted MDL [(=T4)]

Add a penalty for low-confidence patterns:
[
L'(G,\mathcal{P},\mathcal{I}) = L(G,\mathcal{P},\mathcal{I}) + \sum_{p\in\mathcal{P}} \lambda \cdot \phi(\text{conf}(p))
]
where (\phi) decreases as confidence increases (example: (\phi(c)= -\log(c+\epsilon))).

This aligns with "abstract with confidence".


### T5 Orthogonal Procrustes map [(=T5)]

For paired vectors ((u_k, v_k)) in two spaces, find an orthogonal matrix (R) minimizing:
[
\min_{R^\top R = I} |UR - V|_F


### T6 General multi-view alignment [(=T6)]

Use alignment and fusion approaches from multi-view representation learning when orthogonal mapping feels too rigid.


### T7 Modality routing and tokenizer selection [(=T7)]

Starts from raw unstructured input.

```pseudo
function ROUTE_AND_TOKENIZE(input stream):
  regions = SEGMENT_STREAM(stream)              // rough boundaries
  for region in regions:
    dom = PREDICT_DOMAIN(region)                // English, code, table, image, logs, mixed
    tokset = TOKENIZER_STACK[dom].TOKENIZE(region)
    yield (region, dom, tokset)
```

Domain routing can be light at first and later refined using hypothesis outcomes.


### T8 Incremental graph grammar parsing with hypothesis beam [(=T8)]

Grammar is applied to tokens to produce new graph tokens and token graphs.

```pseudo
function PARSE_REGION(region, dom, tokset):
  forest = INIT_PARSE_FOREST(region)

  // seed hypothesis with raw token graph
  h0 = NEW_HYP(region, dom)
  h0.token_graph = BUILD_TOKEN_GRAPH(tokset)          // adjacency edges, containment edges
  PUSH(forest.active_hyps, h0)

  for step in 1..MAX_STEPS:
    next = []
    for h in TOPK_BY_SCORE(forest.active_hyps, BEAM):
      matches = RULE_MATCH_INDEX[dom].CANDIDATE_MATCHES(h.token_graph)

      for m in matches:
        if PASS_FAST_MATCH_CHECK(m):
          h2 = APPLY_RULE(h, m)                       // graph rewrite, emits GraphTokens
          SCORE_UPDATE(h2)                            // rule prob, tension, complexity
          next.append(h2)

    forest = PACK_AND_MERGE(forest, next)             // share subgraphs across hyps
    if STOP_CONDITION(forest): break

  return forest
```

This mirrors the packed-forest idea used to manage ambiguity growth in GLR style parsing.


### T9 Rule application as graph rewrite with provenance [(=T9)]

Uses DPO-like rewrite semantics, keeps non-destructive update invariants.

```pseudo
function APPLY_RULE(h, match m):
  rule = m.rule
  g2 = COPY_VIEW(h.token_graph)

  // rewrite in a new graph view, never overwrites the old view
  g2 = GRAPH_REWRITE_DPO(g2, rule, m)                 // produces new graph

  // emit tokens from rhs
  emitted = EMIT_TOKENS(rule.emit, bindings=m.bindings, hyp=h.hyp_id)
  ATTACH_PROVENANCE(emitted, m.support_spans)

  h2 = NEW_HYP_FROM(h)
  h2.token_graph = g2
  h2.bindings += (rule, m.bindings)
  return h2
```

Graph transformation via DPO gives a formal foundation for safe rewrites and composition.
