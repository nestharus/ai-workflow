## Algorithm 1: Streaming ingestion [(=Algorithm 1)]

Goal: create evidence nodes, create idea handles, build edges, update tiers, update the field locally.

Ingestion becomes append-only for state. `x` updates create `NodeState` records.

```pseudo
function INGEST_STREAM(stream):
  for span in STREAM_TO_SPANS(stream):
    v = NEW_NODE(level=EVIDENCE, span_ref=span.ref)

    b = EMBED(span.text)
    STORE ObservationRecord(node=v.id, b=b, embedder_id, version, input_hash)

    INIT NodeState for each active hypothesis h:
      state = NEW_STATE(node=v.id, hyp=h, x=b, u=HIGH, r=0, T=0)
      v.current_state[h] = state.id

    GRAPH.ADD_NODE(v)
    ADD_EDGES_WITH_BELIEFS(v, span.text)        // creates EdgeBelief with g default values

    ATTACH_TO_IDEAS(v)                          // membership edges become EdgeBelief too

    PROMOTE_DEMOTE_TIERS()

    AFFECTED = NEIGHBORHOOD(v, radius=r_tier(v.tier))
    FIELD_UPDATE_WITH_DIAGNOSTICS(AFFECTED)

    CONFLICT_SCAN_AND_QUEUE(AFFECTED)
    UPDATE_INDICES(AFFECTED)
    LOG_EVENT(...)
```

### D58 CurriculumStage [(=D58)]

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

### D61 GrammarRuleCandidate [(=D61)]

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

## P5.1 Graph grammar semantics [(=P5.1)]

Represent the current world as a typed hypergraph (G).

A rule (p) is a rewrite:
[
L \xleftarrow{l} K \xrightarrow{r} R
]
where:

* (L) is the match pattern
* (K) is the interface preserved during rewriting
* (R) is the replacement graph

DPO and related algebraic approaches define when a match is valid and how rewriting constructs the new graph via pushouts.

For language-like parsing on graphs, HRG and related formalisms provide the “context-free grammar for graphs” analogue.

## P5.2 Probabilistic and scored rewriting [(=P5.2)]

Attach a score to each rule application. This can be probability or cost.

Probabilistic graph grammars exist with rule probabilities inducing derivation probabilities.

Define a derivation score for a hypothesis (h):
[
S(h) = \sum_{\text{rule apps } a \in h} \log P(a) ;-; \lambda \cdot \text{Tension}(h);-;\gamma \cdot \text{Complexity}(h)
]

* (P(a)) from the rule score model
* Tension comes from the field diagnostics inside the hypothesis
* Complexity penalizes overly complex parses

## Algorithm 17 [(=Algorithm 17)]
Modality routing and tokenizer selection (+[T7])

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

## Algorithm 18 [(=Algorithm 18)]
Incremental graph grammar parsing with hypothesis beam (+[T8])

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

## Algorithm 19 [(=Algorithm 19)]
Rule application as graph rewrite with provenance (+[T9])

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

### Algorithm 26: Curriculum ingestion controller [(=Algorithm 26)]

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

## P5C3 Packed forest representation preserves derivations [(=P5C3)]

For the string case, packed forests and graph-structured stacks are standard ways to share substructure and represent ambiguity compactly in GLR style parsing.
For graph grammars, completeness depends on grammar restrictions and parsing algorithm. HRG parsing has known polynomial-time recognition under restrictions, and general cases can be hard.

Spec requirement:

* grammar classes used online must satisfy a “uniform parsing budget” policy
* heavy grammars run in sleep-time or under strict scope limits

### P6C5 Grammar promotion controls error [(=P6C5)]

**Claim.** Beta posterior gating yields bounded promotion risk under the assumed win/loss observation model.
**Sketch.**

* Same as P4 promotion proof pattern.

## G17 Graphs are the grammar [(=G17)]

* A grammar is a set of typed graph rewrite rules.
* Parsing is graph rewriting plus scoring.

## G18 Tokens are graph objects [(=G18)]

* Tokens exist inside a grammar as nodes, hyperedges, subgraphs, and pattern instances.
* Tokens can come from text spans, from graph coordinates, or from both.

## G20 Multi-interpretation ingestion [(=G20)]

* Ingestion maintains a parse forest of competing hypotheses.
* Re-ingestion happens by replaying evidence through a different grammar set or a different hypothesis mixture.

## G24 Low path dependence [(=G24)]

* Curriculum ingestion and periodic cold solves reduce first-mover geometry lock-in.

## G27 Grammar evolution is safe [(=G27)]

* Grammar rules emerge, then sandbox, then promote with measurable error bounds.

## D28 Graph token [(=D28)]

A token that exists in a grammar, not necessarily in text.

```text
GraphToken {
  tok_id: TokId
  tok_type: TokTypeId                 // word, sentence, ASTNode, Function, Subsystem, Pattern, Idea, Hypothesis, ...
  provenance: list<SpanRef>           // can be empty when tok is purely structural
  anchor_nodes: list<NodeId>          // links into evidence graph
  graph_coords: GraphCoordRef         // pointers to subgraph or match bindings
  hyp_id: HypId
  tier: Tier
  created_t: Time
}
```

## D29 Grammar rule as graph rewrite [(=D29)]

Use an algebraic graph transformation style rule object.

```text
Rule {
  rule_id: RuleId
  domain: DomainId                    // English, Python, Logs, Images, Mixed, ...
  lhs: PatternGraph                   // match graph
  interface: PatternGraph             // glue graph
  rhs: PatternGraph                   // output graph
  emit: EmitSpec                      // token types to create, edges to add
  score: RuleScoreModel               // probability, cost, priors
  conf: float                         // learned or curated confidence
  version: int
}
```

This matches standard graph transformation and graph grammar formalisms in the DPO family.

## D30 Parse hypothesis [(=D30)]

A single interpretation state, contains a token graph plus mappings back to evidence.

```text
ParseHypothesis {
  hyp_id: HypId
  domain: DomainId
  input_region: RegionRef
  token_graph: GraphViewRef
  bindings: list<Binding>             // rule matches and slot bindings
  score: float
  uncertainty: float
  parent: HypId?
}
```

## D31 Parse forest [(=D31)]

Packed storage of many hypotheses sharing substructure.

```text
ParseForest {
  region: RegionRef
  packed_dag: DAGRef                  // shared subgraphs across hypotheses
  active_hyps: list<HypId>
  best_hyps: list<HypId>
}
```

This mirrors packed forest and graph-structured stack ideas used to control ambiguity blow-up in GLR style parsing.

## Algorithm 23 [(=Algorithm 23)]
Re-ingestion under reinterpretation (+[T13])
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

## C5 Ingestion produces stable idea handles [(=C5)]

Via graph-supported clustering, rather than geometry-only clustering.

### P1I12 Ingestion hot path [(=P1I12)]

Embed once, add edges, local relax, push conflict candidates. Heavy work runs on the conflict queue.

## P5C4 Orthogonal adapter preserves geometry [(=P5C4)]

If (A_v) is orthogonal, then (|A_v x - A_v y| = |x-y|). This gives stable similarity across mapped spaces. Procrustes-based alignment provides a practical way to fit such maps.

Lean target:

* prove distance preservation for orthogonal matrices
* prove the Procrustes minimizer exists under standard assumptions, optional


### P5I1 Parse forest versioning [(=P5I1)]

Parse forests are versioned by epoch. Old hypotheses compact via P2 (+[P2]) sleep cycle, with provenance and failures retained.

---



### P5I2 Strict beam width [(=P5I2)]

Strict beam width per region. Packed DAG sharing across hypotheses, similar in spirit to graph-structured stacks for ambiguity.


### P5I3 Grammar class restrictions per tier [(=P5I3)]

Focus and Active: restricted grammars with cheap matching and bounded-degree neighborhoods. Context and Sleep: heavier grammars and deeper matching. Graph grammar parsing complexity varies widely across grammar classes and restrictions.


### P5I4 Match candidate indexing [(=P5I4)]

Index rule LHS patterns by WL-style neighborhood signatures. Use WL hashing to prune match candidates before subgraph matching.


### P5I5 Coordinate transforms cached [(=P5I5)]

Cache canonical projections (A_v b_i^{(v)}). Refit adapters in sleep-time, then bulk-refresh projections during consolidation.


### P5I6 Domain embedders specialized [(=P5I6)]

Text embedder stays as the semantic anchor. Graph embedder covers topology. Code embedder covers AST and code structure.

