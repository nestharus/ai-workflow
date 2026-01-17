# Ingestion Library

Multi-modality routing, tokenization, graph grammar parsing, parse forests.

---

## Algorithm 1: Streaming ingestion

Goal: create evidence nodes, create idea handles, build edges, update tiers, update the field locally.

```pseudo
function INGEST_STREAM(stream):
  for span in STREAM_TO_SPANS(stream):                 // sentence-level or structure markers
    v = NEW_NODE(level=EVIDENCE, span_ref=span.ref)

    v.b = EMBED(span.text)                             // base observation
    v.x = v.b                                          // init field state
    v.u = HIGH
    v.tier = FOCUS
    v.a = INIT_ACTIVATION()

    GRAPH.ADD_NODE(v)

    // structural edges
    ADD_ADJACENCY_EDGES(v)
    ADD_CONTAINMENT_EDGES(v)
    ADD_REFERENCE_EDGES(v, span.text)

    // idea attachment
    candidates = FIND_IDEA_CANDIDATES(v.x)              // ANN over idea nodes in context+inactive
    best = SELECT_OR_CREATE_IDEA(candidates, v)

    GRAPH.ADD_EDGE(v.id, best.id, type=MEMBERSHIP, w=INIT_MEMBERSHIP_WEIGHT(v,best))

    // tier maintenance
    UPDATE_ACTIVATION(v)
    PROMOTE_DEMOTE_TIERS()

    // local field update
    AFFECTED = NEIGHBORHOOD(v, radius=r_tier(v.tier))
    FIELD_RELAX(AFFECTED, steps=s_tier(v.tier))

    UPDATE_INDICES(AFFECTED)
    LOG_EVENT(...)
```

---

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

---

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

---

## P5.1 Graph grammar semantics

Represent the current world as a typed hypergraph (G).

A rule (p) is a rewrite:
[
L \xleftarrow{l} K \xrightarrow{r} R
]
where:

* (L) is the match pattern
* (K) is the interface preserved during rewriting
* (R) is the replacement graph

DPO and related algebraic approaches define when a match is valid and how rewriting constructs the new graph via pushouts. ([University of Leicester Computer Science][4])

For language-like parsing on graphs, HRG and related formalisms provide the "context-free grammar for graphs" analogue. ([People CS Umeå][5])

---

## P5.2 Probabilistic and scored rewriting

Attach a score to each rule application. This can be probability or cost.

Probabilistic graph grammars exist with rule probabilities inducing derivation probabilities. ([Springer][6])

Define a derivation score for a hypothesis (h):
[
S(h) = \sum_{\text{rule apps } a \in h} \log P(a) ;-; \lambda \cdot \text{Tension}(h);-;\gamma \cdot \text{Complexity}(h)
]

* (P(a)) from the rule score model
* Tension comes from the field diagnostics inside the hypothesis
* Complexity penalizes overly complex parses

---

### Algorithm 1

Ingestion becomes append-only for state.

Patch `INGEST_STREAM` so `x` updates create `NodeState` records.

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

---

## Algorithm 17

### Modality routing and tokenizer selection

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

---

## Algorithm 18

### Incremental graph grammar parsing with hypothesis beam

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

This mirrors the packed-forest idea used to manage ambiguity growth in GLR style parsing. ([IJCAI][2])

---

## Algorithm 19

### Rule application as graph rewrite with provenance

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

Graph transformation via DPO gives a formal foundation for safe rewrites and composition. ([University of Leicester Computer Science][4])

---

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

---

## P5C3 Packed forest representation preserves derivations

For the string case, packed forests and graph-structured stacks are standard ways to share substructure and represent ambiguity compactly in GLR style parsing. ([IJCAI][2])
For graph grammars, completeness depends on grammar restrictions and parsing algorithm. HRG parsing has known polynomial-time recognition under restrictions, and general cases can be hard. ([ACL Anthology][10])

Spec requirement:

* grammar classes used online must satisfy a "uniform parsing budget" policy
* heavy grammars run in sleep-time or under strict scope limits

---

### P6C5 Grammar promotion controls error

**Claim.** Beta posterior gating yields bounded promotion risk under the assumed win/loss observation model.
**Sketch.**

* Same as P4 promotion proof pattern.

---

## G17 Graphs are the grammar

* A grammar is a set of typed graph rewrite rules.
* Parsing is graph rewriting plus scoring.

---

## G18 Tokens are graph objects

* Tokens exist inside a grammar as nodes, hyperedges, subgraphs, and pattern instances.
* Tokens can come from text spans, from graph coordinates, or from both.

---

## G19 Emergent structure

* Structure appears when encountered.
* New grammars and token types can emerge from recurring subgraphs and successful parses.

---

## G20 Multi-interpretation ingestion

* Ingestion maintains a parse forest of competing hypotheses.
* Re-ingestion happens by replaying evidence through a different grammar set or a different hypothesis mixture.

---

## G24 Low path dependence

* Curriculum ingestion and periodic cold solves reduce first-mover geometry lock-in.

---

## G27 Grammar evolution is safe

* Grammar rules emerge, then sandbox, then promote with measurable error bounds.

---

## D28 Graph token

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

---

## D29 Grammar rule as graph rewrite

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

This matches standard graph transformation and graph grammar formalisms in the DPO family. ([ACM Digital Library][1])

---

## D30 Parse hypothesis

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

---

## D31 Parse forest

Packed storage of many hypotheses sharing substructure.

```text
ParseForest {
  region: RegionRef
  packed_dag: DAGRef                  // shared subgraphs across hypotheses
  active_hyps: list<HypId>
  best_hyps: list<HypId>
}
```

This mirrors packed forest and graph-structured stack ideas used to control ambiguity blow-up in GLR style parsing. ([IJCAI][2])

---

## Incremental graph grammar parsing with hypothesis beam

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

This mirrors the packed-forest idea used to manage ambiguity growth in GLR style parsing. ([IJCAI][2])

---

## Graph token embedding bundle and canonical projection

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

## Re-ingestion under reinterpretation

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

## P5 components

1. **Modality Router**
2. **Tokenizer Stack**
3. **Graph Grammar Engine**
4. **Parse Forest Store**
5. **Grammar Library**
6. **Grammar Miner and Compiler**
7. **Token Type Registry**
8. **Coordinate System Registry**
9. **Adapter and Alignment Trainer**
10. **Traversal Planner**
11. **Re-ingestion Orchestrator**

---

---

## P5 math

---

## Algorithm 4: Tier promotion and demotion

Explicit focus, active, contextual, inactive logic, inspired by virtual memory style thinking.

```pseudo
function PROMOTE_DEMOTE_TIERS():
  for node in (FOCUS ∪ ACTIVE ∪ CONTEXT):
    node.a = DECAY(node.a) + BOOSTS(node)
    if node.tier == CONTEXT and node.a > TH_UP_ACTIVE: PROMOTE(node, ACTIVE)
    if node.tier == ACTIVE  and node.a > TH_UP_FOCUS:  PROMOTE(node, FOCUS)

    if node.tier == FOCUS  and node.a < TH_DN_ACTIVE:  DEMOTE(node, ACTIVE)
    if node.tier == ACTIVE and node.a < TH_DN_CONTEXT: DEMOTE(node, CONTEXT)
    if node.tier == CONTEXT and node.a < TH_DN_INACTIVE: DEMOTE(node, INACTIVE)

  ENFORCE_CAPS()        // keep |FOCUS|<=K, |ACTIVE|<=M, |CONTEXT|<=N
```

Caps are hard safety rails.

---

## Algorithm 5: Boundary detection without fixed chunking

Use change in direction as a signal, plus structure cues. Bayesian online changepoint detection is a clean option.

```pseudo
function STREAM_TO_SPANS(stream):
  run BOCPD over feature z_t = [cos(b_t, b_{t-1}), punctuation, heading, entity_shift]
  emit boundary when P(changepoint) > tau
  yield span
```

---

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

## Components

### Comp1 Ingestion Stream

Main streaming ingestion pipeline.

---

### Comp11 Modality Router

Routes raw input to appropriate tokenizer based on detected modality.

---

### Comp12 Tokenizer Stack

Domain-specific tokenization engines for text, code, tables, images, etc.

---

### Comp13 Graph Grammar Engine

Applies graph rewrite rules to token graphs to build parse hypotheses.

---

### Comp14 Parse Forest Store

Stores packed parse forests with shared substructure across hypotheses.

---

### Comp15 Grammar Library

Repository of graph rewrite rules organized by domain and version.

---

### Comp16 Grammar Miner and Compiler

Discovers patterns and compiles them into executable grammar rules.

---

### Comp17 Token Type Registry

Central registry of token types with schemas and versioning.

---

### Comp21 Re-ingestion Orchestrator

Manages controlled replay of evidence through new grammars or adapters.

---

### Comp24 Secondary Ingestion Engine (H2)

Hippocampal workspace ingestion engine for hypothesis exploration.

---

### Comp26 Curriculum Manager (CURR)

Controls ingestion parameters based on curriculum stage (bootstrap, expansion, open).

---

### Comp30 Grammar Sandbox + Rule Promotion (GRAM-SBX)

Sandboxes candidate grammar rules, measures performance, promotes based on confidence.

---

